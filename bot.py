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

load_dotenv("./dynamic.env", override=True, encoding="utf-8")

from pyrogram import idle
from pyrogram import Client, __version__
from pyrogram.raw.all import layer
from database.users_chats_db import db
from database.join_reqs import JoinReqs
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
            workers=1000,
            plugins={"root": "plugins"},
            sleep_threshold=2,
        )

    async def start(self, **kwargs):
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
        for admin in ADMINS:
            try:
                await self.send_message(admin, text="Bot Restarted")
                logging.info("Admin Sending")
            except Exception as e:
                logging.warning(f"Failed to send restart message to {admin}: {e}")
        await asyncio.sleep(4)
        for id in DB_CHANNEL:
            try:
                await self.get_chat(id)
                test = await self.send_message(id, text="Bot Restarted")
                logging.info("Channel Sending")
                await test.delete()
            except Exception as e:
                logging.warning(f"Failed to send restart message to {id}: {e}")
        logging.info('Done Things')
        
    async def stop(self, *args):
        await super().stop()
        logging.info("Bot stopped. Bye.")
    
    async def iter_messages(
        self,
        chat_id: Union[int, str],
        limit: int,
        offset: int = 0,
    ) -> Optional[AsyncGenerator["types.Message", None]]:
        """Iterate through a chat sequentially.
        This convenience method does the same as repeatedly calling :meth:`~pyrogram.Client.get_messages` in a loop, thus saving
        you from the hassle of setting up boilerplate code. It is useful for getting the whole chat messages with a
        single call.
        Parameters:
            chat_id (``int`` | ``str``):
                Unique identifier (int) or username (str) of the target chat.
                For your personal cloud (Saved Messages) you can simply use "me" or "self".
                For a contact that exists in your Telegram address book you can use his phone number (str).
                
            limit (``int``):
                Identifier of the last message to be returned.
                
            offset (``int``, *optional*):
                Identifier of the first message to be returned.
                Defaults to 0.
        Returns:
            ``Generator``: A generator yielding :obj:`~pyrogram.types.Message` objects.
        Example:
            .. code-block:: python
                for message in app.iter_messages("pyrogram", 1, 15000):
                    print(message.text)
        """
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
