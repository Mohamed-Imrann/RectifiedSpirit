import logging

from pyrogram import Client
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
        self._runner: web.AppRunner | None = None

    async def start(self):
        # ✅ DB init MUST happen before plugins use DB
        await init_db()

        # ✅ start pyrogram (loads plugins)
        await super().start()

        # ✅ start aiohttp web server
        self._runner = web.AppRunner(await web_server())
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", int(PORT))
        await site.start()

        me = await self.get_me()
        logging.info(f"✅ Bot started as @{me.username} | Web: 0.0.0.0:{PORT}")

    async def stop(self, *args):
        # ✅ stop web server cleanly
        try:
            if self._runner:
                await self._runner.cleanup()
        except Exception:
            pass

        await super().stop()
        logging.info("🛑 Bot stopped.")


if __name__ == "__main__":
    Bot().run()
