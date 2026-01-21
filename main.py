import asyncio
import logging

from pyrogram import Client, idle

from info import API_ID, API_HASH, BOT_TOKEN
from database.series_sql import init_db

logging.basicConfig(level=logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)


async def main():
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
        plugins={"root": "plugins"},
        workdir=".",
    )

    # Use context managers for clean startup/shutdown
    async with user, bot:
        logging.info("✅ User session started")

        # Attach user client to bot for plugin access
        bot.user_client = user

        me = await bot.get_me()
        logging.info(f"✅ Bot started as @{me.username}")

        # Keep running until stopped
        await idle()

    logging.info("🛑 Stopped bot & user")


if __name__ == "__main__":
    asyncio.run(main())
