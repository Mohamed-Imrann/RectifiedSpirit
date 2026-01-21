import asyncio
import logging

from pyrogram import Client, idle
from pyromod import listen  # IMPORTANT: patch ask/listen before clients

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

    # Start both in SAME running loop
    await user.start()
    user.loop = asyncio.get_running_loop()
    logging.info("✅ User session started")

    bot.user_client = user

    await bot.start()
    bot.loop = asyncio.get_running_loop()
    me = await bot.get_me()
    logging.info(f"✅ Bot started as @{me.username}")

    # keep running
    await idle()

    await bot.stop()
    await user.stop()
    logging.info("🛑 Stopped bot & user")


if __name__ == "__main__":
    # ✅ DO THIS (not get_event_loop)
    asyncio.run(main())
