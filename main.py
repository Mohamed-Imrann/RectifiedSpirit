import asyncio
import logging

from pyrogram import Client, idle
from pyromod import listen  # needed for client.ask / client.listen

from aiohttp import web

from info import API_ID, API_HASH, BOT_TOKEN, SESSION, PORT
from plugins import web_server
from database.series_sql import init_db


logging.basicConfig(level=logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)


class Bot(Client):
    def __init__(self):
        super().__init__(
            name=SESSION,
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            plugins={"root": "plugins"},
            workers=200,
            sleep_threshold=2,
        )

    async def start(self):
        await super().start()
        await init_db()

        app = web.AppRunner(await web_server())
        await app.setup()
        await web.TCPSite(app, "0.0.0.0", PORT).start()

        me = await self.get_me()
        logging.info(f"✅ Bot started as @{me.username} | Web: 0.0.0.0:{PORT}")

    async def stop(self, *args):
        await super().stop()
        logging.info("🛑 Bot stopped.")


if __name__ == "__main__":
    Bot().run()
