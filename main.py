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
        workdir=".",   # ensure session file in same folder
    )

    # BOT
    bot = Client(
        "bot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        plugins={"root": "plugins"},
        workdir=".",   # bot.session also here
    )

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

    # Stop
    await bot.stop()
    await user.stop()
    logging.info("🛑 Stopped bot & user")


if __name__ == "__main__":
    # ✅ important: create ONE loop only
    asyncio.get_event_loop().run_until_complete(main())
