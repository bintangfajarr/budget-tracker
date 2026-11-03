"""
Entry point: starts Telegram bot + email scheduler.
"""
import asyncio
import logging
import os

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    from src.models.database import init_db
    from src.handlers.bot import build_application, make_email_notify
    from src.services.email_poller import start_scheduler, set_notify_callback

    logger.info("Initializing database...")
    init_db()

    logger.info("Building Telegram bot...")
    app = build_application()

    # Setup email → Telegram notification
    raw_ids = os.environ.get("ALLOWED_USER_IDS", "")
    allowed_ids = [int(x.strip()) for x in raw_ids.split(",") if x.strip()]
    notify_cb = make_email_notify(app, allowed_ids)
    set_notify_callback(notify_cb)

    logger.info("Starting email scheduler...")
    start_scheduler()

    logger.info("Starting Telegram bot polling...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=["message", "callback_query"])

    logger.info("Bot is running. Press Ctrl+C to stop.")
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("Shutting down...")
        from src.services.email_poller import stop_scheduler
        stop_scheduler()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
