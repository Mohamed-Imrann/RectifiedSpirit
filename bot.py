ifort logging.config
import asyncio
import os
import sys
from dotenv import load_dotenv
from pyromod import listen
from pyrogram import idle, Client, __version__, types
from pyrogram.raw.all import layer
from aiohttp import web
from typing import Union, Optional, AsyncGenerator

from database.users_chats_db import db
from database.join_reqs import JoinReqs
from info import *
from utils import temp
from plugins import web_server

# Logging configuration
logging.config.fileConfig('logging.conf')
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
logging.getLogger("imdbpy").setLevel(logging.ERROR)
logging.getLogger("asyncio").setLevel(logging.CRITICAL - 1)

# Load environment variables
load_dotenv("./dynamic.env", override=True, encoding="utf-8")

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
        # Check REQ_CHANNEL_ONE and TWO, update env if nneede
        await super().start()
        if REQ_CHANNEL_ONE is None or REQ_CHANNEL_TWO is None:
            with open("./dynamic.env", "wt+", encoding="utf-8") as f:
                if REQ_CHANNEL_ONE is None:
                    req1 = await JoinReqs().get_fsub_chat1()
                    req1 = req1['chat_id'] if req1 else False
                    f.write(f"REQ_CHANNEL_ONE={req1}\n")
                else:
                    f.write(f"REQ_CHANNEL_ONE={REQ_CHANNEL_ONE}\n")
                
                if REQ_CHANNEL_TWO is None:
                    req2 = await JoinReqs().get_fsub_chat2()
                    req2 = req2['chat_id'] if req2 else False
                    f.write(f"REQ_CHANNEL_TWO={req2}\n")
                else:
                    f.write(f"REQ_CHANNEL_TWO={REQ_CHANNEL_TWO}\n")
            
            # Restart the bot after updating the environment
            os.execl(sys.executable, sys.executable, "bot.py")
            return

        me = await self.get_me()
        temp.ME = me.id
        temp.U_NAME = me.username
        temp.B_NAME = me.first_name
        self.username = '@' + me.username

        logging.info(
            f"{me.first_name} With For Pyrogram v{__version__} "
            f"(Layer {layer}) Started On @{me.username}"
        )

        app = web.AppRunner(await web_server())
        await app.setup()
        await web.TCPSite(app, "0.0.0.0", PORT).start()

        # Handle force subscription channel 1
        if REQ_CHANNEL_ONE:
            try:
                temp.LINK_ONE = (
                    await self.create_chat_invite_link(
                        chat_id=REQ_CHANNEL_ONE,
                        creates_join_request=True
                    )
                ).invite_link
            except Exception as a:
                logging.warning(a)
                logging.warning("Bot can't export invite link from Force Sub Channel!")
                logging.warning(
                    f"Check REQ_CHANNEL_ONE value and make sure bot is admin "
                    f"in channel with invite permission. Current value: {REQ_CHANNEL_ONE}"
                )
                logging.info("Bot stopped. Join https://t.me/EbizaSupport for support.")
                sys.exit()

        # Handle force subscription channel 2
        if REQ_CHANNEL_TWO:
            try:
                temp.LINK_TWO = (
                    await self.create_chat_invite_link(
                        chat_id=REQ_CHANNEL_TWO,
                        creates_join_request=True
                    )
                ).invite_link
            except Exception as b:
                logging.warning(b)
                logging.warning("Bot can't export invite link from Force Sub Channel!")
                logging.warning(
                    f"Check REQ_CHANNEL_TWO value and make sure bot is admin "
                    f"in channel with invite permission. Current value: {REQ_CHANNEL_TWO}"
                )
                logging.info("Bot stopped. Join https://t.me/EbizaSupport for support.")                
                sys.exit()

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
            if new_diff <= 0: # Corrected syntax error here
                return
            messages = await self.get_messages(chat_id, list(range(current, current+new_diff+1)))
            for message in messages:
                yield message
                current += 1


app = Bot()
app.run()
