"""
Auto-categorizer: maps keywords in description/merchant to categories.
"""
import re

# keyword -> category name mapping (case-insensitive)
KEYWORD_RULES: list[tuple[re.Pattern, str]] = [
    # Makanan & Minuman
    (re.compile(r"gofood|grab\s*food|shopeefood|kfc|mcdonald|burger|pizza|starbucks|kopi|cafe|resto|warung|makan|bakso|soto|nasi|mie|ayam|seafood|indomaret\s*food|alfamart\s*food", re.I), "Makanan & Minuman"),
    # Transport
    (re.compile(r"gojek|grab(?!food)|maxim|ojek|parkir|toll|tol|bensin|pertamina|shell|spbu|busway|krl|mrt|lrt|blue\s*bird|taxi|transjakarta", re.I), "Transport"),
    # Belanja
    (re.compile(r"shopee|tokopedia|lazada|bukalapak|blibli|indomaret|alfamart|alfamidi|minimarket|supermarket|hypermart|carrefour|ikea|uniqlo|zara|h&m|fashion|clothing", re.I), "Belanja"),
    # Tagihan & Utilitas
    (re.compile(r"pln|listrik|pdam|air|telkom|indihome|wifi|internet|pascabayar|tagihan|cicilan|angsuran|mortgage|token\s*listrik|bpjs|asuransi", re.I), "Tagihan & Utilitas"),
    # Hiburan
    (re.compile(r"netflix|spotify|youtube\s*premium|disney|vidio|games|steam|playstation|xbox|bioskop|cinema|cgv|cinepolis|XXI|hiburan", re.I), "Hiburan"),
    # Kesehatan
    (re.compile(r"apotik|apotek|klinik|rumah\s*sakit|rs\s|dokter|halodoc|alodokter|kimia\s*farma|century|guardian|obat|vitamin|sehat", re.I), "Kesehatan"),
    # Pendidikan
    (re.compile(r"sekolah|kuliah|kursus|udemy|coursera|ruangguru|zenius|bimbel|buku|gramedia|perpustakaan|spp|ukt|pendidikan", re.I), "Pendidikan"),
    # Tabungan & Investasi
    (re.compile(r"investasi|saham|reksa\s*dana|bibit|ajaib|stockbit|bareksa|pluang|emas|logam\s*mulia|deposito|tabungan\s*berjangka", re.I), "Tabungan & Investasi"),
    # Transfer masuk
    (re.compile(r"transfer\s*masuk|terima\s*transfer|incoming\s*transfer|receive", re.I), "Transfer Masuk"),
    # Gaji
    (re.compile(r"gaji|salary|payroll|THR|insentif|bonus", re.I), "Gaji & Pemasukan"),
]


def auto_categorize(description: str, merchant: str | None = None) -> str | None:
    """
    Returns category name if a keyword matches, else None.
    """
    text = f"{description or ''} {merchant or ''}"
    for pattern, category in KEYWORD_RULES:
        if pattern.search(text):
            return category
    return None
