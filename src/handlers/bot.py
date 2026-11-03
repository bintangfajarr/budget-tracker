"""
Telegram Bot handlers.
Commands:
  /start        - Welcome
  /tambah       - Input transaksi manual (guided)
  /ringkasan    - Ringkasan bulan ini
  /hari         - Ringkasan hari ini
  /minggu       - Ringkasan minggu ini
  /riwayat      - 10 transaksi terakhir
  /budget       - Laporan budget vs aktual
  /setbudget    - Set budget kategori
  /kategori     - Daftar kategori
  /bantuan      - Help
"""
import logging
import os
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from src.models.database import (
    get_all_categories,
    get_category_by_id,
    get_summary,
    get_recent_transactions,
    insert_transaction,
    update_transaction_category,
    get_budgets_vs_actual,
    set_budget,
)
from src.services.formatter import fmt_idr, fmt_summary, fmt_budget_report, fmt_transaction
from src.services.categorizer import auto_categorize

logger = logging.getLogger(__name__)

# Conversation states
(
    ASK_TYPE, ASK_AMOUNT, ASK_DESCRIPTION, ASK_CATEGORY, ASK_DATE,
    BUD_CATEGORY, BUD_AMOUNT,
) = range(7)


def _allowed(user_id: int) -> bool:
    raw = os.environ.get("ALLOWED_USER_IDS", "")
    if not raw:
        return True
    allowed = [int(x.strip()) for x in raw.split(",") if x.strip()]
    return user_id in allowed


def _auth(func):
    """Decorator to restrict bot to allowed users."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        if not _allowed(uid):
            await update.message.reply_text("⛔ Akses tidak diizinkan.")
            return ConversationHandler.END
        return await func(update, context)
    wrapper.__name__ = func.__name__
    return wrapper


# ─── /start ──────────────────────────────────────────────────────────────────

@_auth
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name
    await update.message.reply_text(
        f"👋 Halo *{name}*\\! Selamat datang di *Budget Tracker* 💰\n\n"
        "Saya membantu kamu mencatat dan memantau pengeluaran secara otomatis dari email Jago "
        "dan input manual\\.\n\n"
        "*Perintah yang tersedia:*\n"
        "/tambah — Catat transaksi manual\n"
        "/ringkasan — Ringkasan bulan ini\n"
        "/hari — Ringkasan hari ini\n"
        "/minggu — Ringkasan minggu ini\n"
        "/riwayat — 10 transaksi terakhir\n"
        "/budget — Status budget vs pengeluaran\n"
        "/setbudget — Set budget kategori\n"
        "/kategori — Daftar kategori\n"
        "/bantuan — Bantuan",
        parse_mode="MarkdownV2",
    )


# ─── /bantuan ────────────────────────────────────────────────────────────────

@_auth
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Budget Tracker — Bantuan*\n\n"
        "📥 *Otomatis:* Transaksi dari email Jago akan otomatis dicatat setiap beberapa menit\\.\n\n"
        "✏️ *Manual:* Gunakan /tambah untuk mencatat transaksi yang tidak ada di email\\.\n\n"
        "📊 *Laporan:*\n"
        "• /hari — pengeluaran hari ini\n"
        "• /minggu — pengeluaran minggu ini\n"
        "• /ringkasan — pengeluaran bulan ini\n"
        "• /riwayat — 10 transaksi terakhir\n"
        "• /budget — pantau budget per kategori\n\n"
        "🏷️ *Kategori:* /kategori untuk melihat semua kategori\\.",
        parse_mode="MarkdownV2",
    )


# ─── /kategori ───────────────────────────────────────────────────────────────

@_auth
async def cmd_kategori(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cats = get_all_categories()
    expense = [c for c in cats if not c["is_income"]]
    income = [c for c in cats if c["is_income"]]

    lines = ["🏷️ *Daftar Kategori*\n", "*Pengeluaran:*"]
    for c in expense:
        lines.append(f"  {c['emoji']} {c['name']}")
    lines.append("\n*Pemasukan:*")
    for c in income:
        lines.append(f"  {c['emoji']} {c['name']}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─── /ringkasan, /hari, /minggu ──────────────────────────────────────────────

async def _send_summary(update: Update, uid: int, period: str):
    rows = get_summary(uid, period)
    await update.message.reply_text(fmt_summary(rows, period), parse_mode="Markdown")


@_auth
async def cmd_ringkasan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_summary(update, update.effective_user.id, "month")


@_auth
async def cmd_hari(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_summary(update, update.effective_user.id, "today")


@_auth
async def cmd_minggu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_summary(update, update.effective_user.id, "week")


# ─── /riwayat ────────────────────────────────────────────────────────────────

@_auth
async def cmd_riwayat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txs = get_recent_transactions(update.effective_user.id, 10)
    if not txs:
        await update.message.reply_text("Belum ada transaksi.")
        return

    messages = ["📋 *10 Transaksi Terakhir*\n"]
    for i, tx in enumerate(txs, 1):
        emoji = "🔴" if tx["type"] == "debit" else "🟢"
        sign = "-" if tx["type"] == "debit" else "+"
        cat = f"{tx.get('category_emoji', '')} {tx.get('category_name', '—')}"
        date = tx["transaction_at"].strftime("%d/%m %H:%M") if hasattr(tx["transaction_at"], "strftime") else "—"
        messages.append(f"{i}\\. {emoji} *{sign}{fmt_idr(tx['amount'])}*  `{date}`\n   {tx['description'][:40]}\n   {cat}")

    await update.message.reply_text("\n\n".join(messages), parse_mode="MarkdownV2")


# ─── /budget ─────────────────────────────────────────────────────────────────

@_auth
async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_budgets_vs_actual(update.effective_user.id)
    await update.message.reply_text(fmt_budget_report(rows), parse_mode="Markdown")


# ─── /setbudget conversation ─────────────────────────────────────────────────

@_auth
async def cmd_setbudget_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cats = [c for c in get_all_categories() if not c["is_income"]]
    buttons = [[InlineKeyboardButton(f"{c['emoji']} {c['name']}", callback_data=f"bcat:{c['id']}")] for c in cats]
    await update.message.reply_text(
        "Pilih kategori yang ingin di-set budgetnya:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return BUD_CATEGORY


async def bud_pick_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_id = int(query.data.split(":")[1])
    cat = get_category_by_id(cat_id)
    context.user_data["bud_cat_id"] = cat_id
    context.user_data["bud_cat_name"] = cat["name"]
    await query.edit_message_text(
        f"Set budget untuk *{cat['emoji']} {cat['name']}*\n\nMasukkan nominal budget (contoh: 500000):",
        parse_mode="Markdown",
    )
    return BUD_AMOUNT


async def bud_set_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip().replace(".", "").replace(",", "").replace("rp", "").replace("Rp", "").strip()
    try:
        amount = int(raw)
        assert amount > 0
    except (ValueError, AssertionError):
        await update.message.reply_text("❌ Nominal tidak valid. Masukkan angka, contoh: 500000")
        return BUD_AMOUNT

    from datetime import date
    month = date.today().replace(day=1)
    set_budget(context.user_data["bud_cat_id"], amount, month)
    cat_name = context.user_data["bud_cat_name"]
    await update.message.reply_text(
        f"✅ Budget untuk *{cat_name}* bulan ini diset ke *{fmt_idr(amount)}*",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ─── /tambah conversation ─────────────────────────────────────────────────────

@_auth
async def cmd_tambah_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["💸 Pengeluaran", "💵 Pemasukan"]]
    await update.message.reply_text(
        "Catat transaksi baru.\n\nJenis transaksi:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
    )
    return ASK_TYPE


async def ask_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    context.user_data["tx_type"] = "debit" if "Pengeluaran" in text else "credit"
    await update.message.reply_text(
        "Masukkan nominal (contoh: 50000):",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ASK_AMOUNT


async def ask_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip().replace(".", "").replace(",", "").replace("Rp", "").replace("rp", "").strip()
    try:
        amount = int(raw)
        assert amount > 0
    except (ValueError, AssertionError):
        await update.message.reply_text("❌ Nominal tidak valid. Contoh: 50000")
        return ASK_AMOUNT

    context.user_data["tx_amount"] = amount
    await update.message.reply_text("Masukkan keterangan / nama merchant:")
    return ASK_DESCRIPTION


async def ask_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["tx_description"] = update.message.text.strip()

    tx_type = context.user_data["tx_type"]
    description = context.user_data["tx_description"]

    # Try AI categorization (keyword → Hermes fallback)
    auto = auto_categorize(description, tx_type=tx_type)

    cats = get_all_categories()
    is_income = tx_type == "credit"
    filtered = [c for c in cats if c["is_income"] == is_income]

    buttons = [[InlineKeyboardButton(f"{c['emoji']} {c['name']}", callback_data=f"cat:{c['id']}")] for c in filtered]

    hint = f"\n\n🤖 Rekomendasi AI: *{auto}*" if auto else ""
    await update.message.reply_text(
        f"Pilih kategori:{hint}",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )
    return ASK_CATEGORY


async def save_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    cat_id = int(query.data.split(":")[1])
    cat = get_category_by_id(cat_id)

    row = insert_transaction({
        "amount": context.user_data["tx_amount"],
        "type": context.user_data["tx_type"],
        "description": context.user_data["tx_description"],
        "category_id": cat_id,
        "source": "manual",
        "email_uid": None,
        "merchant": None,
        "balance_after": None,
        "transaction_at": datetime.now(),
        "telegram_user_id": update.effective_user.id,
    })

    sign = "-" if row["type"] == "debit" else "+"
    await query.edit_message_text(
        f"✅ Transaksi disimpan\\!\n\n"
        f"{'🔴' if row['type'] == 'debit' else '🟢'} *{sign}{fmt_idr(row['amount'])}*\n"
        f"📝 {row['description']}\n"
        f"🏷️ {cat['emoji']} {cat['name']}",
        parse_mode="MarkdownV2",
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ─── Email notification callback ─────────────────────────────────────────────

def make_email_notify(app: Application, allowed_ids: list[int]):
    """Returns async callback to notify users when email transaction arrives."""
    async def notify(tx: dict, cat_name: str | None):
        sign = "-" if tx["type"] == "debit" else "+"
        text = (
            f"📧 *Transaksi Baru dari Email*\n\n"
            f"{'🔴' if tx['type'] == 'debit' else '🟢'} *{sign}{fmt_idr(tx['amount'])}*\n"
            f"📝 {tx['description']}\n"
            f"🏷️ {cat_name or 'Belum dikategori'}\n"
        )
        if tx.get("balance_after"):
            text += f"💳 Saldo: {fmt_idr(tx['balance_after'])}"

        for uid in allowed_ids:
            try:
                await app.bot.send_message(uid, text, parse_mode="Markdown")
            except Exception as e:
                logger.warning(f"Failed to notify user {uid}: {e}")

    return notify


# ─── Build Application ────────────────────────────────────────────────────────

def build_application() -> Application:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()

    # /tambah conversation
    tambah_conv = ConversationHandler(
        entry_points=[CommandHandler("tambah", cmd_tambah_start)],
        states={
            ASK_TYPE:        [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_amount)],
            ASK_AMOUNT:      [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_description)],
            ASK_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_category)],
            ASK_CATEGORY:    [CallbackQueryHandler(save_transaction, pattern=r"^cat:\d+$")],
        },
        fallbacks=[CommandHandler("batal", cancel)],
    )

    # /setbudget conversation
    setbudget_conv = ConversationHandler(
        entry_points=[CommandHandler("setbudget", cmd_setbudget_start)],
        states={
            BUD_CATEGORY: [CallbackQueryHandler(bud_pick_category, pattern=r"^bcat:\d+$")],
            BUD_AMOUNT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, bud_set_amount)],
        },
        fallbacks=[CommandHandler("batal", cancel)],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("bantuan", cmd_help))
    app.add_handler(CommandHandler("kategori", cmd_kategori))
    app.add_handler(CommandHandler("ringkasan", cmd_ringkasan))
    app.add_handler(CommandHandler("hari", cmd_hari))
    app.add_handler(CommandHandler("minggu", cmd_minggu))
    app.add_handler(CommandHandler("riwayat", cmd_riwayat))
    app.add_handler(CommandHandler("budget", cmd_budget))
    app.add_handler(tambah_conv)
    app.add_handler(setbudget_conv)

    return app
