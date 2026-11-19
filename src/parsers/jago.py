"""
Gmail IMAP email fetcher & Jago Bank notification parser.
"""
import imaplib
import email
import email.message
import logging
import os
import re
from datetime import datetime, timedelta
from email.header import decode_header
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Senders whose mail is treated as a bank notification. Kept as a flat list of
# substrings so a display name like "BCA <bca@bca.co.id>" still matches.
BANK_SENDER_PATTERNS = [
    # Bank Jago
    "noreply@jago.com",
    "notification@jago.com",
    "info@jago.com",
    "no-reply@jago.com",
    # BCA
    "bca@bca.co.id",
    "noreply@bca.co.id",
    "no-reply@bca.co.id",
    "notifikasi@bca.co.id",
    "halobca@bca.co.id",
]

# Older name, kept so existing imports keep working.
JAGO_SENDER_PATTERNS = BANK_SENDER_PATTERNS


def _decode_str(s: str | bytes, charset: str = "utf-8") -> str:
    if isinstance(s, bytes):
        return s.decode(charset or "utf-8", errors="replace")
    return s


def _decode_header_field(raw) -> str:
    parts = decode_header(raw)
    return "".join(_decode_str(part, enc) for part, enc in parts)


def _get_email_body(msg: email.message.Message) -> str:
    """Extract plain text or HTML body from email."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if "attachment" in cd:
                continue
            if ct == "text/plain":
                body = _decode_str(
                    part.get_payload(decode=True),
                    part.get_content_charset("utf-8"),
                )
                break
            if ct == "text/html" and not body:
                html = _decode_str(
                    part.get_payload(decode=True),
                    part.get_content_charset("utf-8"),
                )
                body = BeautifulSoup(html, "lxml").get_text(separator=" ")
    else:
        ct = msg.get_content_type()
        raw = msg.get_payload(decode=True)
        if raw:
            text = _decode_str(raw, msg.get_content_charset("utf-8"))
            if ct == "text/html":
                body = BeautifulSoup(text, "lxml").get_text(separator=" ")
            else:
                body = text
    return body


# Words that follow a merchant name in Jago's wording rather than being part
# of it. Without trimming these, "KOPI KENANGAN sebesar" ends up stored as
# the merchant and then fed to the categorizer.
_MERCHANT_STOPWORDS = (
    "sebesar", "senilai", "sejumlah", "nominal", "jumlah", "total",
    "berhasil", "sukses", "gagal", "pending",
    "pada", "tanggal", "waktu", "melalui", "via", "dengan",
    "saldo", "sisa", "biaya", "admin", "ref", "referensi",
)


# Wording that means money LEFT the account. Checked against subject and body.
_DEBIT_SUBJECT_WORDS = (
    "pembayaran", "pembelian", "bayar", "debit", "keluar",
    "transfer keluar", "tarik", "penarikan", "biaya", "admin",
    "top up", "topup", "isi saldo", "qris",
)
_CREDIT_SUBJECT_WORDS = (
    "transfer masuk", "dana masuk", "uang masuk", "masuk",
    "kredit", "credit", "terima", "diterima", "refund",
    "pengembalian", "bunga", "cashback",
)

# BCA states the direction as a bare word in the body: "Debit Rp ..." or
# "Kredit Rp ...". These are checked before the looser phrase patterns.
_BCA_DEBIT_RE = r"\bdebit\s*(?:Rp|IDR|\d)"
_BCA_CREDIT_RE = r"\bkredit\s*(?:Rp|IDR|\d)"
_DEBIT_BODY_PATTERNS = (
    r"\btelah\s+membayar\b", r"\bmelakukan\s+transfer\b",
    r"\btransfer\s+(?:sebesar\s+)?[^\n]*\bke\b", r"\bpembayaran\s+(?:qris\s+)?ke\b",
    r"\bdidebet\b", r"\bdidebit\b", r"\bpenarikan\b", r"\btarik\s+tunai\b",
    r"\btop\s*up\b", r"\bbiaya\s+(?:admin|administrasi)\b",
    r"\bpembelian\b", r"\bqris\b",
)
_CREDIT_BODY_PATTERNS = (
    r"\bdana\s+masuk\b", r"\buang\s+masuk\b", r"\bmasuk\s+sebesar\b",
    r"\bditerima\s+dari\b", r"\bmenerima\b", r"\bdikredit\b",
    r"\brefund\b", r"\bpengembalian\b", r"\bcashback\b", r"\bbunga\b",
)

# A hard floor on how far back mail may be imported. EMAIL_LOOKBACK_DAYS only
# narrows the IMAP query and moves with the clock, so on its own it would let
# older mail back in after a restart or a widened window.
IMPORT_START_DATE = os.environ.get("IMPORT_START_DATE", "").strip()


def _before_start_date(when) -> bool:
    """True when a message predates IMPORT_START_DATE and must be ignored."""
    if not IMPORT_START_DATE or when is None:
        return False
    try:
        floor = datetime.strptime(IMPORT_START_DATE, "%Y-%m-%d").date()
    except ValueError:
        logger.warning("IMPORT_START_DATE=%r is not YYYY-MM-DD, ignoring",
                       IMPORT_START_DATE)
        return False
    actual = when.date() if hasattr(when, "date") else when
    return actual < floor




def _parse_amount(raw: str) -> int | None:
    """
    Convert a currency string to whole rupiah, accepting both conventions.

        Jago : "Rp 28.000"      dot = thousands
        Jago : "Rp 150.000,00"  dot = thousands, comma = cents
        BCA  : "IDR 28,100.00"  comma = thousands, dot = cents
        BCA  : "IDR 100,000.00" comma = thousands, dot = cents

    The separator cannot be identified by symbol, since both banks use both
    characters for opposite purposes. Instead the *last* separator followed by
    exactly two digits is treated as the decimal point and discarded; every
    other separator is a thousands group. Misreading this inflates an amount
    a hundredfold, which is how "IDR 28,100.00" became 2,810,000.
    """
    if not raw:
        return None

    text = raw.strip()
    text = re.sub(r"^(?:Rp|IDR)\s*", "", text, flags=re.IGNORECASE)
    text = text.strip().rstrip(".,")

    if not text:
        return None

    # a trailing separator with exactly two digits is cents, in either style
    m = re.search(r"[.,](\d{2})$", text)
    if m:
        # only treat it as cents when something precedes it, so "28,10" at the
        # very start is not mistaken for a fractional value
        head = text[: m.start()]
        if head and re.search(r"\d", head):
            text = head

    # whatever remains is digits plus thousands separators
    digits = re.sub(r"[.,\s]", "", text)

    if not digits.isdigit():
        return None
    try:
        value = int(digits)
    except ValueError:
        return None

    if value <= 0 or value > 10_000_000_000:
        logger.warning("implausible amount parsed from %r -> %s", raw, value)
        return None
    return value


# ── BCA "Internet Transaction Journal" ──────────────────────────────────────
# The mail is a flat list of "Label : Value" rows. Reading the labels directly
# is far more reliable than pattern-matching prose, so BCA gets its own parser
# and only falls through to the generic one if the shape is unfamiliar.

# Every label BCA uses in its journal mails. Values are delimited by the next
# known label rather than by whitespace: the body is whitespace-normalised
# before parsing, so the double spaces that separate rows in the raw mail are
# already gone by the time this runs.
_BCA_KNOWN_LABELS = (
    "status",
    "transaction date", "transaction type", "transaction amount",
    "transfer type", "transfer currency", "transfer amount",
    "payment to", "total payment", "top up amount",
    "merchant location", "merchant name", "merchant pan", "merchant",
    "acquirer", "terminal id",
    "source of fund", "source currency", "source account",
    "customer pan", "card number", "flazz card number",
    "beneficiary account", "beneficiary name", "beneficiary bank",
    "save to beneficiary list",
    "remarks", "reference no", "reference number", "rrn",
    "amount", "fee", "admin fee", "total amount", "nominal",
    "biller name", "payee", "to account name", "description",
    "note", "berita", "jenis transaksi", "tanggal transaksi",
)

# longest first, so "transfer amount" wins over "amount"
_BCA_LABELS_SORTED = sorted(_BCA_KNOWN_LABELS, key=len, reverse=True)

_BCA_LABEL_ALT = "|".join(re.escape(l) for l in _BCA_LABELS_SORTED)

# "Label :" possibly preceded by other text; captures up to the next label
_BCA_ROW_RE = re.compile(
    r"\b(" + _BCA_LABEL_ALT + r")\s*\.?\s*:\s*"
    r"(.*?)"
    r"(?=\s*\b(?:" + _BCA_LABEL_ALT + r")\s*\.?\s*:|$)",
    re.IGNORECASE,
)


def _bca_fields(body_norm: str) -> dict[str, str]:
    """Pull the Label : Value rows out of a BCA journal mail."""
    fields: dict[str, str] = {}
    for label, value in _BCA_ROW_RE.findall(body_norm):
        key = " ".join(label.split()).lower().rstrip(".")
        val = " ".join(value.split()).strip().rstrip(",;")
        if key and val and key not in fields:
            fields[key] = val
    return fields


# Transaction/Transfer Type values that mean money left the account.
_BCA_OUTGOING = (
    "qris payment", "payment", "transfer", "top up", "topup",
    "purchase", "withdrawal", "bill payment", "flazz",
    "e-wallet", "virtual account", "debit",
)
_BCA_INCOMING = (
    "incoming transfer", "credit", "refund", "reversal",
    "interest", "cashback", "received",
)

# Checked in order, so the most specific label wins.
_BCA_AMOUNT_LABELS = (
    "total payment", "transfer amount", "top up amount",
    "transaction amount", "total amount", "amount", "nominal",
)
_BCA_MERCHANT_LABELS = (
    "payment to", "beneficiary name", "merchant name",
    "to account name", "biller name", "payee", "merchant",
)
_BCA_TYPE_LABELS = (
    "transaction type", "transfer type", "jenis transaksi", "description",
)


def _bca_pick(fields: dict[str, str], candidates) -> str | None:
    for name in candidates:
        if name in fields:
            return fields[name]
    # tolerate small label variations
    for key, val in fields.items():
        if any(name in key for name in candidates):
            return val
    return None


def _parse_bca_email(subject: str, body_norm: str) -> dict | None:
    """
    Parse BCA's transaction journal. Returns None when the mail is not a
    transaction notice -- their marketing mail shares the same sender domain
    and would otherwise be recorded as spending.
    """
    fields = _bca_fields(body_norm)
    if not fields:
        return None

    # a genuine journal always carries an amount label and a status
    amount_raw = _bca_pick(fields, _BCA_AMOUNT_LABELS)
    if not amount_raw:
        return None

    amount = _parse_amount(amount_raw)
    if amount is None:
        return None

    # only completed transactions are recorded
    status = (_bca_pick(fields, ("status",)) or "").lower()
    if status and not any(w in status for w in ("success", "berhasil", "completed")):
        logger.info("BCA mail skipped, status=%r", status)
        return None

    tx_label = (_bca_pick(fields, _BCA_TYPE_LABELS) or subject or "").lower()

    tx_type = "debit"
    for w in _BCA_INCOMING:
        if w in tx_label:
            tx_type = "credit"
            break
    else:
        if not any(w in tx_label for w in _BCA_OUTGOING):
            logger.warning("BCA type not recognised, defaulting to debit: %r", tx_label[:60])

    merchant = _bca_pick(fields, _BCA_MERCHANT_LABELS)
    merchant = _clean_merchant(merchant) if merchant else None

    kind = _bca_pick(fields, _BCA_TYPE_LABELS)
    description = merchant or kind or subject.strip()
    if merchant and kind:
        description = f"{kind} - {merchant}"

    return {
        "amount": amount,
        "type": tx_type,
        "description": description,
        "merchant": merchant,
        "balance_after": None,   # BCA's journal does not include a balance
    }


def _detect_direction(subj_lower: str, body_norm: str) -> str:
    """
    Decide whether a transaction is debit or credit.

    Credit wording is checked first because "transfer masuk" also contains
    "transfer", which would otherwise be read as an outgoing transfer. When
    nothing matches the result is debit: an expense wrongly recorded as income
    inflates the balance and corrupts every later total, so the safer default
    is to treat an unknown as money leaving.
    """
    body_lower = body_norm.lower()

    # _BCA_MARKER_FIRST: BCA states the direction outright as "Debit Rp ..." or
    # "Kredit Rp ...". That is authoritative and must be read before any
    # keyword guessing, because BCA's own subject line ("Notifikasi Transaksi
    # BCA") contains "transaksi", which the debit vocabulary also matches.
    if re.search(_BCA_CREDIT_RE, body_lower, re.IGNORECASE):
        return "credit"
    if re.search(_BCA_DEBIT_RE, body_lower, re.IGNORECASE):
        return "debit"

    for w in _CREDIT_SUBJECT_WORDS:
        if w in subj_lower:
            return "credit"
    for p in _CREDIT_BODY_PATTERNS:
        if re.search(p, body_lower, re.IGNORECASE):
            return "credit"

    for w in _DEBIT_SUBJECT_WORDS:
        if w in subj_lower:
            return "debit"
    for p in _DEBIT_BODY_PATTERNS:
        if re.search(p, body_lower, re.IGNORECASE):
            return "debit"

    logger.warning("direction not recognised, defaulting to debit | subj=%r", subj_lower[:60])
    return "debit"


def _clean_merchant(raw: str) -> str | None:
    """Trim trailing filler words and punctuation from a captured merchant."""
    if not raw:
        return None

    text = " ".join(raw.split())          # collapse whitespace
    words = text.split()

    # drop trailing stopwords, e.g. "KOPI KENANGAN sebesar" -> "KOPI KENANGAN"
    while words and words[-1].lower().strip(".,;:-") in _MERCHANT_STOPWORDS:
        words.pop()

    text = " ".join(words).strip(" .,;:-")

    # a capture that is only an amount, a currency token or digits is not a name
    if not text or text.lower() in _MERCHANT_STOPWORDS:
        return None
    if re.fullmatch(r"(?:Rp|IDR)?[\s\d.,]*", text, re.IGNORECASE):
        return None
    if not re.search(r"[A-Za-z]{2,}", text):
        return None
    return text


# Mail from the bank that is not a transaction. These arrive from the same
# sender as the journal, so sender filtering alone is not enough.
_NON_TRANSACTION_SUBJECTS = (
    "password", "pin", "biometric", "biometrics",
    "phone no", "phone number", "registered", "registration",
    "beneficiary list", "beneficiary transfer list",
    "activation", "activated", "deactivat",
    "login", "sign in", "security", "verification", "verify",
    "otp", "token", "blocked", "blokir",
    "statement", "e-statement", "rekening koran",
    "promo", "promotion", "newsletter", "tips",
    "welcome", "selamat bergabung", "survey", "kuesioner",
    "maintenance", "pemeliharaan", "gangguan",
    "ulang tahun", "birthday",
)

# A journal entry names at least one of these. Without such a label the mail
# is an announcement, whatever digits it happens to contain.
_TRANSACTION_MARKERS = (
    "transaction type", "transfer type", "total payment",
    "transfer amount", "top up amount", "transaction amount",
    "jenis transaksi", "nominal", "payment to",
)


def _is_non_transaction(subject: str, body_norm: str) -> bool:
    """True when the mail is a notice rather than a transaction."""
    subj = (subject or "").lower()

    for word in _NON_TRANSACTION_SUBJECTS:
        if word in subj:
            return True

    low = body_norm.lower()
    if not any(marker in low for marker in _TRANSACTION_MARKERS):
        return True

    return False


# A declined or pending attempt moves no money. Recording one inflates every
# total, and three failed QRIS retries looked exactly like three purchases.
_FAILED_STATUS_WORDS = (
    "failed", "gagal", "declined", "rejected", "ditolak",
    "pending", "menunggu", "in process", "diproses",
    "cancelled", "canceled", "dibatalkan", "expired", "kedaluwarsa",
    "unsuccessful", "tidak berhasil", "reversal", "dibatalkan",
)


def _is_failed_transaction(body_norm: str) -> bool:
    """True when the notification reports a transaction that did not complete."""
    # Look only at the status field, not the whole body: a merchant name could
    # legitimately contain one of these words.
    m = re.search(r"\bstatus\b\s*:?\s*([A-Za-z ]{3,30})", body_norm, re.IGNORECASE)
    if not m:
        return False

    status = m.group(1).strip().lower()
    for word in _FAILED_STATUS_WORDS:
        if word in status:
            return True
    return False


def parse_bank_email(subject: str, body: str, sender: str = "") -> dict | None:
    """
    Entry point for any supported bank. Dispatches on the wording rather than
    the sender, so a forwarded mail still parses correctly.
    """
    body_norm = " ".join((body or "").split())

    if _is_non_transaction(subject or "", body_norm):
        logger.debug("skipped non-transaction mail: %r", (subject or "")[:60])
        return None

    if _is_failed_transaction(body_norm):
        logger.info("skipped failed/pending transaction: %r", (subject or "")[:60])
        return None

    low = body_norm.lower()
    looks_bca = (
        "bca" in (sender or "").lower()
        or "internet transaction journal" in (subject or "").lower()
        or "through mybca" in low
        or "halo bca" in low
        # a label layout is a stronger signal than any amount format, which a
        # failed transaction may not even include
        or ("transaction type" in low and "source of fund" in low)
        or ("transfer type" in low and "beneficiary" in low)
        or re.search(r"\bIDR\s[\d,]+\.\d{2}\b", body_norm) is not None
    )
    if looks_bca:
        parsed = _parse_bca_email(subject or "", body_norm)
        if parsed:
            return parsed
        # fall through: an unfamiliar BCA layout still gets the generic attempt

    return parse_jago_email(subject or "", body or "")


def parse_jago_email(subject: str, body: str) -> dict | None:
    """
    Parse Jago Bank notification email.
    Returns dict with keys: amount, type, description, merchant, balance_after
    or None if not a transaction email.
    """
    subj_lower = subject.lower()
    body_norm = " ".join(body.split())

    tx_type = _detect_direction(subj_lower, body_norm)

    # Try to extract from body regardless of subject
    amount_patterns = [
        # BCA puts the direction immediately before the figure
        r"(?:debit|kredit)\s*(?:Rp|IDR)\s*([\d.,]+)",
        r"(?:Rp|IDR)\s*([\d.,]+)",
        r"sebesar\s+(?:Rp|IDR)?[\s.]*([\d.,]+)",
        r"nominal[\s:]+(?:Rp|IDR)?[\s.]*([\d.,]+)",
        r"jumlah[\s:]+(?:Rp|IDR)?[\s.]*([\d.,]+)",
    ]

    amount = None
    for pat in amount_patterns:
        m = re.search(pat, body_norm, re.IGNORECASE)
        if m:
            amount = _parse_amount(m.group(1))
            if amount is not None:
                break

    if amount is None:
        return None

    # Extract merchant/description
    merchant = None
    # Stop at sentence punctuation and at the words that begin the next clause,
    # otherwise the capture runs into "... Saldo akhir Rp ...".
    _STOP = r"(?=\s*(?:\.|,|;|\n|$|Rp|IDR|\bsebesar\b|\bsenilai\b|\bsejumlah\b|"
    _STOP += r"\bberhasil\b|\bsukses\b|\bsaldo\b|\bsisa\b|\bpada\b|\btanggal\b|"
    _STOP += r"\bmelalui\b|\bvia\b|\bdengan\b|\bref\b|\breferensi\b|\btelah\b))"

    # (?:Rp|IDR)[\d.,\s]+ lets the pattern step over an amount that sits
    # between the keyword and the name, as in "QRIS Rp 35.000,00 di INDOMARET".
    _SKIP_AMT = r"(?:(?:Rp|IDR)\s*[\d.,]+\s*)?"
    _SKIP_ACCT = r"(?:\d{6,}\s+)?"

    merchant_patterns = [
        r"(?:ke|kepada)\s+rekening\s+\d+\s+([A-Za-z0-9\s&'\-\.]{2,60}?)" + _STOP,
        r"(?:qris|merchant|toko)\s+" + _SKIP_AMT + r"(?:ke\s+|di\s+)?([A-Za-z\s&'\-\.][A-Za-z0-9\s&'\-\.]{1,59}?)" + _STOP,
        r"(?:membayar|pembayaran|bayar)\s+(?:qris\s+)?(?:ke|di|kepada)\s+([A-Za-z0-9\s&'\-\.]{2,60}?)" + _STOP,
        r"(?:transfer|kirim)\s+" + _SKIP_AMT + r"(?:sebesar\s+[^\s]+\s+)?(?:ke|kepada)\s+" + _SKIP_ACCT + r"([A-Za-z\s&'\-\.][A-Za-z0-9\s&'\-\.]{1,59}?)" + _STOP,
        r"(?:dari)\s+([A-Za-z0-9\s&'\-\.]{2,60}?)" + _STOP,
        r"(?:ke|kepada)\s+" + _SKIP_ACCT + r"([A-Za-z\s&'\-\.][A-Za-z0-9\s&'\-\.]{1,59}?)" + _STOP,
    ]
    for pat in merchant_patterns:
        m = re.search(pat, body_norm, re.IGNORECASE)
        if m:
            merchant = _clean_merchant(m.group(1))
            break

    # Extract balance after
    balance_after = None
    bal_match = re.search(
        r"(?:saldo|balance)\s+(?:akhir|tersisa|sekarang)?[\s:]*(?:Rp|IDR)?[\s.]*([\d.,]+)",
        body_norm,
        re.IGNORECASE,
    )
    if bal_match:
        raw = bal_match.group(1).replace(".", "").replace(",", "")
        try:
            balance_after = int(raw)
        except ValueError:
            pass

    description = merchant or subject.strip()

    return {
        "amount": amount,
        "type": tx_type,
        "description": description,
        "merchant": merchant,
        "balance_after": balance_after,
    }


class GmailFetcher:
    def __init__(self):
        self.address = os.environ["GMAIL_ADDRESS"]
        self.password = os.environ["GMAIL_APP_PASSWORD"]

    def _connect(self) -> imaplib.IMAP4_SSL:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(self.address, self.password)
        return mail

    def _fetch_one(self, mail, uid):
        """
        Fetch and parse a single message. Returns a transaction dict or None.

        BODY.PEEK is used rather than RFC822 so Gmail does not flag the mail as
        read -- the user still sees unread bank notifications on their phone.
        """
        _, msg_data = mail.uid("fetch", uid, "(BODY.PEEK[])")
        if not msg_data or not msg_data[0]:
            return None

        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        sender = msg.get("From", "").lower()
        if not any(p in sender for p in BANK_SENDER_PATTERNS):
            return None

        subject = _decode_header_field(msg.get("Subject", ""))
        body = _get_email_body(msg)

        parsed = parse_bank_email(subject, body, sender)
        if parsed is None:
            return None

        tx_date = datetime.now()
        date_str = msg.get("Date", "")
        if date_str:
            try:
                from email.utils import parsedate_to_datetime
                tx_date = parsedate_to_datetime(date_str)
            except Exception:
                pass

        if _before_start_date(tx_date):
            logger.debug("skipped %s: predates IMPORT_START_DATE", uid.decode())
            return None

        parsed["email_uid"] = uid.decode()
        parsed["transaction_at"] = tx_date
        return parsed

    def fetch_new_jago_emails(self, since_uid: str = None) -> list[dict]:
        """
        Fetch bank notifications and return parsed transactions.

        Resilient on purpose: Gmail drops the socket when one session issues
        many large fetches, and a batch of a hundred messages must not be lost
        because the connection died on the ninetieth.
        """
        results: list[dict] = []

        days = int(os.environ.get("EMAIL_LOOKBACK_DAYS", "30"))
        since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")

        # Narrow the search server-side: asking Gmail for the bank's mail is
        # far cheaper than fetching the whole window and filtering locally.
        criteria = f'(SINCE {since})'

        mail = None
        try:
            mail = self._connect()
            mail.select("INBOX", readonly=True)

            _, data = mail.uid("search", None, criteria)
            uids = data[0].split() if data and data[0] else []
            logger.info("IMAP search %s matched %d message(s)", criteria, len(uids))

            reconnects = 0
            i = 0
            while i < len(uids):
                uid = uids[i]
                try:
                    parsed = self._fetch_one(mail, uid)
                    if parsed:
                        results.append(parsed)
                    i += 1

                except (imaplib.IMAP4.abort, OSError) as e:
                    # socket died mid-batch: reconnect and retry this uid once
                    if reconnects >= 3:
                        logger.error("giving up after %d reconnects: %s", reconnects, e)
                        break
                    reconnects += 1
                    logger.warning("IMAP connection lost (%s), reconnecting (%d)", e, reconnects)
                    try:
                        if mail is not None:
                            mail.logout()
                    except Exception:
                        pass
                    mail = self._connect()
                    mail.select("INBOX", readonly=True)
                    continue

                except Exception as e:
                    # a malformed message must not stop the rest
                    logger.warning("could not process uid %s: %s", uid, e)
                    i += 1

        except Exception as e:
            logger.error("Gmail fetch error: %s", e, exc_info=True)

        finally:
            if mail is not None:
                try:
                    mail.logout()
                except Exception:
                    pass

        logger.info("fetched %d transaction(s)", len(results))
        return results
