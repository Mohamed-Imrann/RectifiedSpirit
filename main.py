# main.py
import asyncio
import logging

from pyrogram import Client, idle
from pyromod import listen  # noqa: F401  (enables ask/listen)

from info import API_ID, API_HASH, BOT_TOKEN, USER_SESSION
from database.series_sql import init_db

logging.basicConfig(level=logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)


async def main():
    await init_db()

    # ✅ Bot client (short name - avoids "file name too long")
    bot = Client(
        name="bot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        plugins={"root": "plugins"},
        workers=200,
        sleep_threshold=2,
    )

    # ✅ User client (needed for channel history)
    user = Client(
        name="user",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=USER_SESSION,
        workers=50,
        sleep_threshold=2,
    )

    await user.start()
    await bot.start()

    # attach user client to bot so plugins can access it
    bot.user_client = user

    me = await bot.get_me()
    logging.info(f"✅ Bot started as @{me.username}")
    logging.info("✅ User session started (channel sync enabled)")

    await idle()

    await bot.stop()
    await user.stop()


if __name__ == "__main__":
    asyncio.run(main())
