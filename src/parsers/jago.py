"""
Gmail IMAP email fetcher & Jago Bank notification parser.
"""
import imaplib
import email
import logging
import os
import re
from datetime import datetime
from email.header import decode_header
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

JAGO_SENDER_PATTERNS = [
    "noreply@jago.com",
    "notification@jago.com",
    "info@jago.com",
    "no-reply@jago.com",
]


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


def parse_jago_email(subject: str, body: str) -> dict | None:
    """
    Parse Jago Bank notification email.
    Returns dict with keys: amount, type, description, merchant, balance_after
    or None if not a transaction email.
    """
    subj_lower = subject.lower()
    body_norm = " ".join(body.split())

    tx_type = None
    if any(k in subj_lower for k in ["pembayaran", "transaksi", "debit", "keluar", "transfer keluar", "pembelian"]):
        tx_type = "debit"
    elif any(k in subj_lower for k in ["masuk", "kredit", "terima", "credit", "top up", "topup"]):
        tx_type = "credit"

    # Try to extract from body regardless of subject
    amount_patterns = [
        r"(?:Rp|IDR)[\s.]*([\d.,]+)",
        r"sebesar\s+(?:Rp|IDR)?[\s.]*([\d.,]+)",
        r"nominal[\s:]+(?:Rp|IDR)?[\s.]*([\d.,]+)",
        r"jumlah[\s:]+(?:Rp|IDR)?[\s.]*([\d.,]+)",
    ]

    amount = None
    for pat in amount_patterns:
        m = re.search(pat, body_norm, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(".", "").replace(",", "")
            try:
                amount = int(raw)
                break
            except ValueError:
                continue

    if amount is None:
        return None

    # Infer type from body if not from subject
    if tx_type is None:
        if re.search(r"\b(debit|keluar|bayar|pembayaran|transfer ke)\b", body_norm, re.IGNORECASE):
            tx_type = "debit"
        else:
            tx_type = "credit"

    # Extract merchant/description
    merchant = None
    merchant_patterns = [
        r"(?:merchant|toko|kepada|ke)\s*[:\-]?\s*([A-Za-z0-9\s&'\-\.]+?)(?:\s{2,}|Rp|IDR|\n|$)",
        r"pembayaran\s+(?:ke|di)\s+([A-Za-z0-9\s&'\-\.]+?)(?:\s{2,}|Rp|IDR|\n|$)",
    ]
    for pat in merchant_patterns:
        m = re.search(pat, body_norm, re.IGNORECASE)
        if m:
            merchant = m.group(1).strip()
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

    def fetch_new_jago_emails(self, since_uid: str = None) -> list[dict]:
        """
        Fetch unread Jago notification emails.
        Returns list of parsed transaction dicts with 'email_uid' key.
        """
        results = []
        try:
            mail = self._connect()
            mail.select("INBOX")

            search_criteria = '(UNSEEN)'
            if since_uid:
                search_criteria = f'(UID {int(since_uid)+1}:*)'

            _, data = mail.uid("search", None, search_criteria)
            uids = data[0].split() if data[0] else []

            for uid in uids:
                uid_str = uid.decode()
                _, msg_data = mail.uid("fetch", uid, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    continue

                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                sender = msg.get("From", "").lower()
                if not any(p in sender for p in JAGO_SENDER_PATTERNS):
                    continue

                subject = _decode_header_field(msg.get("Subject", ""))
                body = _get_email_body(msg)

                parsed = parse_jago_email(subject, body)
                if parsed is None:
                    continue

                # Parse date
                date_str = msg.get("Date", "")
                try:
                    from email.utils import parsedate_to_datetime
                    tx_date = parsedate_to_datetime(date_str)
                except Exception:
                    tx_date = datetime.now()

                parsed["email_uid"] = uid_str
                parsed["transaction_at"] = tx_date
                parsed["source"] = "email"
                results.append(parsed)

            mail.logout()
        except Exception as e:
            logger.error(f"Gmail fetch error: {e}", exc_info=True)

        return results
