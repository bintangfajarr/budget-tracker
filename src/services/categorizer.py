"""
AI Categorizer menggunakan OmniRoute (OpenAI-compatible gateway).

Strategi:
  1. Coba keyword matching dulu (cepat, gratis, offline)
  2. Kalau tidak ada match → kirim ke OmniRoute (model gratis)
  3. Kalau OmniRoute tidak tersedia → fallback ke None
"""
import json
import logging
import os
import re
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

# ─── Keyword rules (fast path) ────────────────────────────────────────────────

KEYWORD_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"gofood|grab\s*food|shopeefood|kfc|mcdonald|burger|pizza|starbucks|kopi|cafe|resto|warung|makan|bakso|soto|nasi|mie|ayam|seafood|indomaret\s*food|alfamart\s*food", re.I), "Makanan & Minuman"),
    (re.compile(r"gojek|grab(?!food)|maxim|ojek|parkir|toll|tol|bensin|pertamina|shell|spbu|busway|krl|mrt|lrt|blue\s*bird|taxi|transjakarta", re.I), "Transport"),
    (re.compile(r"shopee|tokopedia|lazada|bukalapak|blibli|indomaret|alfamart|alfamidi|minimarket|supermarket|hypermart|carrefour|ikea|uniqlo|zara|h&m|fashion|clothing", re.I), "Belanja"),
    (re.compile(r"pln|listrik|pdam|air|telkom|indihome|wifi|internet|pascabayar|tagihan|cicilan|angsuran|mortgage|token\s*listrik|bpjs|asuransi", re.I), "Tagihan & Utilitas"),
    (re.compile(r"netflix|spotify|youtube\s*premium|disney|vidio|games|steam|playstation|xbox|bioskop|cinema|cgv|cinepolis|XXI|hiburan", re.I), "Hiburan"),
    (re.compile(r"apotik|apotek|klinik|rumah\s*sakit|rs\s|dokter|halodoc|alodokter|kimia\s*farma|century|guardian|obat|vitamin|sehat", re.I), "Kesehatan"),
    (re.compile(r"sekolah|kuliah|kursus|udemy|coursera|ruangguru|zenius|bimbel|buku|gramedia|perpustakaan|spp|ukt|pendidikan", re.I), "Pendidikan"),
    (re.compile(r"investasi|saham|reksa\s*dana|bibit|ajaib|stockbit|bareksa|pluang|emas|logam\s*mulia|deposito|tabungan\s*berjangka", re.I), "Tabungan & Investasi"),
    # Outgoing first: "transfer to ..." and "transfer ke ..." are debits, and
    # would otherwise be caught by the incoming rule below on the word alone.
    (re.compile(r"transfer\s+to\b|transfer\s+ke\b|transfer\s*keluar|outgoing\s*transfer", re.I), "Transfer Keluar"),
    (re.compile(r"transfer\s*masuk|terima\s*transfer|incoming\s*transfer|receive", re.I), "Transfer Masuk"),
    (re.compile(r"gaji|salary|payroll|THR|insentif|bonus", re.I), "Gaji & Pemasukan"),
]

# Categories that can only apply to money coming in. Offering them for a debit
# invites exactly the mistake this fixes.
_INCOME_ONLY = ("Gaji & Pemasukan", "Transfer Masuk")

VALID_CATEGORIES = [
    "Makanan & Minuman",
    "Transport",
    "Belanja",
    "Tagihan & Utilitas",
    "Hiburan",
    "Kesehatan",
    "Pendidikan",
    "Tabungan & Investasi",
    "Gaji & Pemasukan",
    "Transfer Masuk",
    "Lain-lain",
]

# ─── Config ───────────────────────────────────────────────────────────────────

OMNIROUTE_BASE_URL = os.environ.get("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1")
OMNIROUTE_API_KEY  = os.environ.get("OMNIROUTE_API_KEY", "")
OMNIROUTE_MODEL    = os.environ.get("OMNIROUTE_MODEL", "openrouter/cohere/north-mini-code:free")
OMNIROUTE_TIMEOUT  = int(os.environ.get("OMNIROUTE_TIMEOUT", "30"))  # seconds

# Fallback endpoint, tried only when the primary fails. The free tier has a
# daily request cap, so one exhausted quota would otherwise leave every
# transaction uncategorised for the rest of the day.
FALLBACK_BASE_URL = os.environ.get("FALLBACK_BASE_URL", "")
FALLBACK_API_KEY  = os.environ.get("FALLBACK_API_KEY", "")
FALLBACK_MODEL    = os.environ.get("FALLBACK_MODEL", "")

# Reasoning models need room to think before emitting the answer; too low a
# value returns content=None with the answer stranded in `reasoning`.
OMNIROUTE_MAX_TOKENS = int(os.environ.get("OMNIROUTE_MAX_TOKENS", "800"))

# Set False untuk disable AI dan hanya pakai keyword
AI_ENABLED = os.environ.get("AI_CATEGORIZE", "true").lower() == "true"


# ─── Ollama call ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
Kamu adalah asisten keuangan pribadi. Tugasmu hanya mengkategorikan transaksi keuangan.

Daftar kategori yang tersedia (pilih HANYA dari daftar ini, tulis PERSIS seperti tertera):
- Makanan & Minuman
- Transport
- Belanja
- Tagihan & Utilitas
- Hiburan
- Kesehatan
- Pendidikan
- Tabungan & Investasi
- Gaji & Pemasukan
- Transfer Masuk
- Lain-lain

Jawab HANYA dengan nama kategori, tanpa penjelasan tambahan apapun.\
"""


def _endpoint_chain() -> list[tuple[str, str, str, str]]:
    """
    (label, base_url, api_key, model) in the order they should be tried.
    The fallback is included only when fully configured.
    """
    chain = [("primary", OMNIROUTE_BASE_URL, OMNIROUTE_API_KEY, OMNIROUTE_MODEL)]
    if FALLBACK_BASE_URL and FALLBACK_MODEL:
        chain.append(("fallback", FALLBACK_BASE_URL, FALLBACK_API_KEY, FALLBACK_MODEL))
    return chain


def _post_once(base_url: str, api_key: str, model: str,
               description: str, tx_type: str) -> tuple[str | None, str | None]:
    """
    One attempt. Returns (raw_text, error). Exactly one is non-None.

    `error` is a short machine-ish reason so the caller can decide whether
    moving to the next endpoint is worthwhile.
    """
    if tx_type == "debit":
        direction = "PENGELUARAN (uang keluar dari rekening)"
        excluded = ", ".join(_INCOME_ONLY)
        rule = (f"Ini transaksi keluar, jadi JANGAN pilih: {excluded}. "
                f"Kata 'Transfer' di sini berarti mengirim uang, bukan menerima.")
    else:
        direction = "PEMASUKAN (uang masuk ke rekening)"
        rule = "Ini transaksi masuk."

    user_msg = (
        f"Transaksi: \"{description}\"\n"
        f"Jenis: {direction}\n"
        f"{rule}\n"
        f"Jawab HANYA nama kategori."
    )

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        "temperature": 0.1,
        "max_tokens": OMNIROUTE_MAX_TOKENS,
        "stream": False,
    }).encode()

    # Some gateways sit behind Cloudflare and reject python-urllib's default
    # User-Agent with a 1010 challenge, so send an explicit one.
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "budget-tracker/1.0",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # A base_url already ending in /chat/completions is used verbatim; this
    # lets the fallback point at a local shim that exposes a bare root path.
    base = base_url.rstrip("/")
    url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=OMNIROUTE_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:160]
        except Exception:
            pass
        return None, f"http_{e.code}: {detail}"
    except urllib.error.URLError as e:
        return None, f"unreachable: {e}"
    except Exception as e:
        return None, f"failed: {e}"

    return raw, None


def _extract_answer(raw: str) -> str | None:
    """
    Pull the answer out of either a plain JSON body or an SSE stream.

    Some gateways (z0ne, for one) reply with SSE even when stream:false is
    requested, so both shapes have to be handled.
    """
    text = raw.strip()

    if text.startswith("{"):
        try:
            body = json.loads(text)
        except json.JSONDecodeError:
            return None
        try:
            msg = body["choices"][0]["message"]
        except (KeyError, IndexError):
            return None
        content = msg.get("content")
        if content and content.strip():
            return content.strip()
        for key in ("reasoning", "reasoning_content"):
            alt = msg.get(key)
            if alt and str(alt).strip():
                return str(alt).strip()[-300:]
        return None

    # SSE
    content, reasoning = "", ""
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if chunk == "[DONE]":
            break
        try:
            ch = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        for choice in ch.get("choices", []):
            delta = choice.get("delta") or {}
            if delta.get("content"):
                content += delta["content"]
            if delta.get("reasoning_content"):
                reasoning += delta["reasoning_content"]

    answer = (content or reasoning).strip()
    return answer[-300:] if answer else None


def _call_omniroute(description: str, tx_type: str = "debit") -> str | None:
    """
    Ask the model to categorize, walking the endpoint chain on failure.
    Returns the raw model string, or None when every endpoint failed.
    """
    for label, base_url, api_key, model in _endpoint_chain():
        raw, err = _post_once(base_url, api_key, model, description, tx_type)

        if err:
            logger.warning("categorizer %s (%s) failed: %s", label, model, err)
            continue

        answer = _extract_answer(raw)
        if answer:
            if label != "primary":
                logger.info("categorizer used %s (%s)", label, model)
            return answer

        logger.warning("categorizer %s (%s) returned nothing usable", label, model)

    return None


# Backwards-compatible alias: older code/tests may still call _call_ollama.
_call_ollama = _call_omniroute


def _normalize_ai_response(raw: str) -> str | None:
    """
    Match Hermes output to exact category name.
    Handles minor formatting differences (extra spaces, lowercase, etc).
    """
    if not raw:
        return None

    cleaned = raw.strip().rstrip(".")

    # Exact match first
    for cat in VALID_CATEGORIES:
        if cleaned.lower() == cat.lower():
            return cat

    # Partial match (model sometimes adds context)
    for cat in VALID_CATEGORIES:
        if cat.lower() in cleaned.lower():
            return cat

    return None


# ─── Public API ───────────────────────────────────────────────────────────────

def _reject_impossible(category: str | None, tx_type: str) -> str | None:
    """Drop a category that cannot apply to this direction."""
    if category and tx_type == "debit" and category in _INCOME_ONLY:
        logger.info("rejected %r for a debit transaction", category)
        return None
    return category


def auto_categorize(
    description: str,
    merchant: str | None = None,
    tx_type: str = "debit",
) -> str | None:
    """
    Categorize a transaction.

    Flow:
      1. Keyword matching (fast, no network)
      2. Hermes via Ollama (AI, local network)
      3. Fallback: None (caller decides default)

    Returns category name string or None.
    """
    text = f"{description or ''} {merchant or ''}"

    # 1. Fast keyword path
    for pattern, category in KEYWORD_RULES:
        if pattern.search(text):
            logger.debug(f"Keyword match: '{text[:50]}' → {category}")
            return category

    # 2. AI path
    if not AI_ENABLED:
        return None

    label = description or merchant or ""
    if not label.strip():
        return None

    logger.debug(f"Sending to OmniRoute: '{label[:80]}'")
    raw = _call_omniroute(label, tx_type)
    if raw is None:
        return None

    result = _reject_impossible(_normalize_ai_response(raw), tx_type)
    if result:
        logger.info(f"OmniRoute categorized '{label[:50]}' → {result}")
    else:
        logger.warning(f"OmniRoute returned unrecognized category: '{raw}' for '{label[:50]}'")

    return result
