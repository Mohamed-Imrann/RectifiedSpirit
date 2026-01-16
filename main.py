import asyncio
import logging

from pyrogram import Client, idle
from pyromod import listen

from info import API_ID, API_HASH, BOT_TOKEN
from database.series_sql import init_db

logging.basicConfig(level=logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)


async def main():
    await init_db()

    # BOT
    bot = Client(
        "bot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        plugins={"root": "plugins"},
    )

    # USER (session file based)
    user = Client(
        "user",
        api_id=API_ID,
        api_hash=API_HASH,
    )

    await user.start()          # ✅ no error now
    bot.user_client = user     # 🔥 attach user to bot
    await bot.start()

    me = await bot.get_me()
    logging.info(f"✅ Bot started @{me.username}")
    logging.info("✅ User session loaded from user.session")

    await idle()

    await bot.stop()
    await user.stop()


if __name__ == "__main__":
    asyncio.run(main())
