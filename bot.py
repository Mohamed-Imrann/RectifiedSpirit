import logging
import logging.config
import asyncio

logging.config.fileConfig('logging.conf')
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
logging.getLogger("imdbpy").setLevel(logging.ERROR)
logging.getLogger("asyncio").setLevel(logging.CRITICAL -1)

import os 
import sys
from dotenv import load_dotenv
from pyromod import listen
from database.manager import init_databases
load_dotenv("./dynamic.env", override=True, encoding="utf-8")

from pyrogram import idle
from pyrogram import Client, __version__
from pyrogram.raw.all import layer
from database.users_chats_db import db
from database.join_reqs import JoinReqs
from database.manager import init_databases, close_databases, check_databases
from info import *
from utils import temp
from typing import Union, Optional, AsyncGenerator
from pyrogram import types
from aiohttp import web
from plugins import web_server

name = "main"

class Bot(Client):
    def __init__(self):
        super().__init__(
            name=SESSION,
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN, 
            workers=300,
            plugins={"root": "plugins"},
            sleep_threshold=10
        )

    async def start(self, **kwargs):
        await init_databases(postgres_uri=POSTGRES_URI, redis_url=REDIS_URL, max_retries=10, retry_delay=3.0)
            
        await super().start()
        me = await self.get_me()
        temp.ME = me.id
        temp.U_NAME = me.username
        temp.B_NAME = me.first_name
        self.username = '@' + me.username
        logging.info(f"{me.first_name} 𝖶𝗂𝗍𝗁 𝖥𝗈𝗋 𝖯𝗒𝗋𝗈𝗀𝗋𝖺𝗆 v{__version__} (Layer {layer}) 𝖲𝗍𝖺𝗋𝗍𝖾𝖽 𝖮𝗇 @{me.username}")
        app = web.AppRunner(await web_server())
        await app.setup()
        bind_address = "0.0.0.0"
        await web.TCPSite(app, bind_address, PORT).start()
        
    
    async def stop(self, *args):
        await super().stop()
        logging.info("Bot stopped. Bye.")
    
    async def iter_messages(
        self,
        chat_id: Union[int, str],
        limit: int,
        offset: int = 0,
    ) -> Optional[AsyncGenerator["types.Message", None]]:
        
        current = offset
        while True:
            new_diff = min(200, limit - current)
            if new_diff <= 0:
                return
            messages = await self.get_messages(chat_id, list(range(current, current+new_diff+1)))
            for message in messages:
                yield message
                current += 1


app = Bot()
app.run()
