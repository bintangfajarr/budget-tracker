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
    (re.compile(r"transfer\s*masuk|terima\s*transfer|incoming\s*transfer|receive", re.I), "Transfer Masuk"),
    (re.compile(r"gaji|salary|payroll|THR|insentif|bonus", re.I), "Gaji & Pemasukan"),
]

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


def _call_omniroute(description: str, tx_type: str = "debit") -> str | None:
    """
    Call OmniRoute (OpenAI-compatible) for categorization.
    Returns the raw model string, or None on failure.

    Uses synchronous urllib to avoid extra dependencies.
    """
    direction = "pengeluaran" if tx_type == "debit" else "pemasukan"
    user_msg = f'Kategorikan transaksi {direction} ini: "{description}"'

    payload = json.dumps({
        "model": OMNIROUTE_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        "temperature": 0.1,
        "max_tokens": OMNIROUTE_MAX_TOKENS,
    }).encode()

    headers = {"Content-Type": "application/json"}
    if OMNIROUTE_API_KEY:
        headers["Authorization"] = f"Bearer {OMNIROUTE_API_KEY}"

    req = urllib.request.Request(
        f"{OMNIROUTE_BASE_URL}/chat/completions",
        data=payload,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=OMNIROUTE_TIMEOUT) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        logger.warning(f"OmniRoute HTTP {e.code}: {detail}")
        return None
    except urllib.error.URLError as e:
        logger.warning(f"OmniRoute unreachable: {e}")
        return None
    except Exception as e:
        logger.warning(f"OmniRoute call failed: {e}")
        return None

    try:
        msg = body["choices"][0]["message"]
    except (KeyError, IndexError):
        logger.warning(f"OmniRoute returned no choices: {str(body)[:200]}")
        return None

    # Preferred: plain content.
    content = msg.get("content")
    if content and content.strip():
        return content.strip()

    # Reasoning models (nemotron, ling, ...) may leave content empty and put
    # the answer in `reasoning` / `reasoning_content`. Use the tail, since the
    # conclusion lands at the end.
    for key in ("reasoning", "reasoning_content"):
        alt = msg.get(key)
        if alt and str(alt).strip():
            logger.debug(f"using '{key}' fallback for categorization")
            return str(alt).strip()[-300:]

    logger.warning("OmniRoute returned empty content and no reasoning")
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

    result = _normalize_ai_response(raw)
    if result:
        logger.info(f"OmniRoute categorized '{label[:50]}' → {result}")
    else:
        logger.warning(f"OmniRoute returned unrecognized category: '{raw}' for '{label[:50]}'")

    return result
