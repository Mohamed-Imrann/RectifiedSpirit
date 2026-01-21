import asyncio
import logging
from pyrogram import Client, idle
from info import API_ID, API_HASH, BOT_TOKEN
from database.series_sql import init_db

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

async def start_clients():
    # Initialize database
    await init_db()

    # USER client
    user = Client(
        "user",
        api_id=API_ID,
        api_hash=API_HASH,
        workdir=".",
    )

    # BOT client
    bot = Client(
        "bot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        plugins={"root": "plugins"},  # auto-load all plugins in /plugins
        workdir=".",
    )

    async with user, bot:
        logger.info("✅ User session started")
        bot.user_client = user  # Attach user client to bot

        me = await bot.get_me()
        logger.info(f"✅ Bot started as @{me.username}")

        await idle()
        logger.info("🛑 Bot and user stopped")

async def main():
    while True:
        try:
            await start_clients()
        except Exception as e:
            logger.error(f"❌ Bot crashed: {e}")
            logger.info("🔁 Restarting in 5 seconds…")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
