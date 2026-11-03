"""
Utility: format IDR currency and build report messages.
"""
from datetime import datetime


def fmt_idr(amount: int) -> str:
    """Format integer to IDR string: 150000 -> Rp 150.000"""
    return f"Rp {amount:,.0f}".replace(",", ".")


def fmt_summary(rows: list[dict], period: str) -> str:
    period_label = {"today": "Hari Ini", "week": "Minggu Ini", "month": "Bulan Ini"}.get(period, "Bulan Ini")
    if not rows:
        return f"📊 *Ringkasan {period_label}*\n\n_Belum ada transaksi._"

    income_rows = [r for r in rows if r.get("is_income")]
    expense_rows = [r for r in rows if not r.get("is_income")]

    total_income = sum(r["total"] for r in income_rows)
    total_expense = sum(r["total"] for r in expense_rows)
    net = total_income - total_expense

    lines = [f"📊 *Ringkasan {period_label}*\n"]

    if expense_rows:
        lines.append("*Pengeluaran:*")
        for r in expense_rows:
            lines.append(f"  {r['emoji']} {r['category']} — {fmt_idr(r['total'])} ({r['count']}x)")
        lines.append(f"  ➖ *Total: {fmt_idr(total_expense)}*\n")

    if income_rows:
        lines.append("*Pemasukan:*")
        for r in income_rows:
            lines.append(f"  {r['emoji']} {r['category']} — {fmt_idr(r['total'])} ({r['count']}x)")
        lines.append(f"  ➕ *Total: {fmt_idr(total_income)}*\n")

    net_sign = "+" if net >= 0 else "-"
    lines.append(f"💰 *Selisih: {net_sign}{fmt_idr(abs(net))}*")
    return "\n".join(lines)


def fmt_budget_report(rows: list[dict]) -> str:
    if not rows:
        return "📋 *Budget Bulan Ini*\n\n_Belum ada budget yang diset._\nGunakan /setbudget untuk set budget."

    lines = ["📋 *Budget vs Pengeluaran Bulan Ini*\n"]
    for r in rows:
        pct = (r["spent"] / r["budget"] * 100) if r["budget"] > 0 else 0
        bar_filled = min(int(pct / 10), 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)
        status = "🔴" if pct >= 100 else "🟡" if pct >= 75 else "🟢"
        lines.append(
            f"{status} *{r['emoji']} {r['name']}*\n"
            f"   [{bar}] {pct:.0f}%\n"
            f"   {fmt_idr(r['spent'])} / {fmt_idr(r['budget'])}\n"
        )
    return "\n".join(lines)


def fmt_transaction(tx: dict) -> str:
    emoji = "🔴" if tx["type"] == "debit" else "🟢"
    sign = "-" if tx["type"] == "debit" else "+"
    cat = f"{tx.get('category_emoji', '')} {tx.get('category_name', 'Tidak Terkategori')}"
    date = tx["transaction_at"].strftime("%d %b %Y %H:%M") if hasattr(tx["transaction_at"], "strftime") else str(tx["transaction_at"])
    lines = [
        f"{emoji} *{sign}{fmt_idr(tx['amount'])}*",
        f"📝 {tx['description']}",
        f"🏷️ {cat}",
        f"📅 {date}",
        f"🔍 Sumber: {tx.get('source', 'manual')}",
    ]
    if tx.get("balance_after"):
        lines.append(f"💳 Saldo: {fmt_idr(tx['balance_after'])}")
    return "\n".join(lines)
