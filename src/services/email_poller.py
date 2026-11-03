"""
Email polling service using APScheduler.
Runs in background, fetches new Jago emails and saves to DB.
"""
import logging
import os
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.parsers.jago import GmailFetcher
from src.models.database import (
    email_uid_exists,
    insert_transaction,
    get_all_categories,
)
from src.services.categorizer import auto_categorize

logger = logging.getLogger(__name__)

_fetcher = GmailFetcher()
_scheduler = AsyncIOScheduler()

# Will be injected by main.py to send Telegram notifications
_notify_callback = None


def set_notify_callback(fn):
    global _notify_callback
    _notify_callback = fn


async def _poll_emails():
    logger.info("Polling Gmail for new Jago notifications...")
    try:
        emails = _fetcher.fetch_new_jago_emails()
    except Exception as e:
        logger.error(f"Poll failed: {e}", exc_info=True)
        return

    categories = {c["name"]: c["id"] for c in get_all_categories()}

    for tx in emails:
        uid = tx.get("email_uid")
        if uid and email_uid_exists(uid):
            continue

        # Auto-categorize
        cat_name = auto_categorize(tx.get("description", ""), tx.get("merchant"))
        cat_id = categories.get(cat_name) if cat_name else None

        row = insert_transaction({
            "amount": tx["amount"],
            "type": tx["type"],
            "description": tx["description"],
            "category_id": cat_id,
            "source": "email",
            "email_uid": uid,
            "merchant": tx.get("merchant"),
            "balance_after": tx.get("balance_after"),
            "transaction_at": tx.get("transaction_at", datetime.now()),
            "telegram_user_id": None,
        })

        logger.info(f"Saved email transaction id={row['id']} amount={tx['amount']}")

        if _notify_callback:
            await _notify_callback(row, cat_name)


def start_scheduler():
    interval = int(os.environ.get("EMAIL_POLL_INTERVAL", 5))
    _scheduler.add_job(_poll_emails, "interval", minutes=interval, id="email_poll")
    _scheduler.start()
    logger.info(f"Email scheduler started (every {interval} min)")


def stop_scheduler():
    _scheduler.shutdown(wait=False)
