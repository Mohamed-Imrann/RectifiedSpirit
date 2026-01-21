import asyncio
import logging

from pyrogram import Client, idle

from info import API_ID, API_HASH, BOT_TOKEN
from database.series_sql import init_db

logging.basicConfig(level=logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)


async def main():
    await init_db()

    # USER
    user = Client(
        "user",
        api_id=API_ID,
        api_hash=API_HASH,
        workdir=".",
    )

    # BOT
    bot = Client(
        "bot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        plugins={"root": "plugins"},
        workdir=".",
    )

    await user.start()
    logging.info("✅ User session started")

    bot.user_client = user  # plugins can use this

    await bot.start()
    me = await bot.get_me()
    logging.info(f"✅ Bot started as @{me.username}")

    await idle()

    await bot.stop()
    await user.stop()
    logging.info("🛑 Stopped bot & user")


if __name__ == "__main__":
    asyncio.run(main())
