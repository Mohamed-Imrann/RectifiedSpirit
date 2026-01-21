import asyncio
import logging

from pyrogram import Client, idle
from pyromod import listen  # needed for client.ask / client.listen

from info import API_ID, API_HASH, BOT_TOKEN
from database.series_sql import init_db

logging.basicConfig(level=logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)


async def main():
    await init_db()

    # USER (session file = user.session / user.session-journal)
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

    try:
        # Start USER first
        await user.start()
        logging.info("✅ User session started")

        # attach user client to bot (plugins can access via client.user_client)
        bot.user_client = user

        # Start BOT
        await bot.start()
        me = await bot.get_me()
        logging.info(f"✅ Bot started as @{me.username}")

        # keep running
        await idle()

    finally:
        # Stop safely (even if crash happens)
        try:
            await bot.stop()
        except Exception:
            pass

        try:
            await user.stop()
        except Exception:
            pass

        logging.info("🛑 Stopped bot & user")


if __name__ == "__main__":
    # ✅ Python 3.12 safe
    asyncio.run(main())
