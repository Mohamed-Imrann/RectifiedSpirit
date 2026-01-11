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
import asyncio
import logging
import subprocess
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
from database.crazy_db import get_admin_assignments
from pyrogram import utils as pyroutils
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from datetime import datetime, timedelta
from aiocache import caches
from database.postgres import pgDb

pyroutils.MIN_CHAT_ID = -999999999999
pyroutils.MIN_CHANNEL_ID = -100999999999999

name = "main"

async def test_redis_connection():
    try:
        cache = caches.get('default')
        await cache.set("health_check", "ok", ttl=60)
        value = await cache.get("health_check")
        if value == "ok":
            logging.info("✅ Redis connection test passed.")
        else:
            logging.warning("⚠️ Redis connection test failed: unexpected value.")
    except Exception as e:
        logging.error(f"❌ Redis connection failed: {e}")
        raise

async def auto_restart():
    logging.info("Executing auto_restart function...")
    try:
        os.execl(sys.executable, sys.executable, *sys.argv)
    except Exception as e:
        logging.error(f"Error during auto_restart: {e}")
                                           

class Bot(Client):
  def __init__(self):
      super().__init__(
          name=SESSION,
          api_id=API_ID,
          api_hash=API_HASH,
          bot_token=BOT_TOKEN, 
          plugins={"root": "plugins"}
      )
      self.scheduler = AsyncIOScheduler()
      self.id = None
      self.name = None
      self.username = None
      self.mention = None

  async def start(self, **kwargs):
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
                  
          logging.info("Loading REQ_CHANNEL_ONE and REQ_CHANNEL_TWO from database if needed...")
          os.execl(sys.executable, sys.executable, "main.py")
          return

      await super().start()

      me = await self.get_me()
      temp.ME = me.id
      temp.U_NAME = me.username
      temp.B_NAME = me.first_name
      self.username = '@' + me.username
      logging.info(f"{me.first_name} ð–¶ð—‚ð—ð— ð–¥ð—ˆð—‹ ð–¯ð—’ð—‹ð—ˆð—€ð—‹ð–ºð—† v{__version__} (Layer {layer}) ð–²ð—ð–ºð–ºð—‹ð—ð–¾ð–½ ð–®ð—‡ @{me.username}")
      app = web.AppRunner(await web_server())
      await app.setup()
      bind_address = "0.0.0.0"
      await web.TCPSite(app, bind_address, PORT).start()
   
      if REQ_CHANNEL_ONE:
          try: temp.LINK_ONE = (await self.create_chat_invite_link(chat_id=REQ_CHANNEL_ONE, creates_join_request=True)).invite_link 
          except Exception as a:
              logging.warning(a)
              logging.warning("Bot can't Export Invite link from Force Sub Channel!")
              logging.warning(f"Please Double check the REQ_CHANNEL_ONE value and Make sure Bot is Admin in channel with Invite Users via Link Permission, Current Force Sub Channel Value: {REQ_CHANNEL_ONE}")
              logging.info("\nBot Stopped. Join https://t.me/EbizaSupport for support")
      
      if REQ_CHANNEL_TWO:
          try: temp.LINK_TWO = (await self.create_chat_invite_link(chat_id=REQ_CHANNEL_TWO, creates_join_request=True)).invite_link 
          except Exception as b:
              logging.warning(b)
              logging.warning("Bot can't Export Invite link from Force Sub Channel!")
              logging.warning(f"Please Double check the REQ_CHANNEL_TWO value and Make sure Bot is Admin in channel with Invite Users via Link Permission, Current Force Sub Channel Value: {REQ_CHANNEL_TWO}")
              logging.info("\nBot Stopped. Join https://t.me/EbizaSupport for support")
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
              logging.info(f"Channel Sending - {id}")
              await test.delete()
          except Exception as e:
              logging.warning(f"Failed to send restart message to {id}: {e}")
      
      self.scheduler.start()
      logging.info("Main bot scheduler started successfully.")

      self.scheduler.add_job(
          auto_restart,
          IntervalTrigger(hours=24),
          name="Auto Restart"
      )
      logging.info("Auto restart job scheduled every week")

      
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

async def pgDBinit():
    await pgDb.connect()


async def startup():
    try:
        await pgDBinit()
        await test_redis_connection()
        logging.info("Starting bot system...")
        await main()
    except KeyboardInterrupt:
        logging.info("Bot stopped by user")
    except Exception as e:
        logging.error(f"Error in main: {e}")
        os.execl(sys.executable, sys.executable, "bot.py")

async def main():
    try:
        main_bot = Bot()
        await main_bot.start()
        logging.info("Main bot started successfully")
        await asyncio.Event().wait()
    except Exception as e:
        logging.error(f"Critical error in main function: {e}")
        raise

if __name__ == "__main__":
    try:
        asyncio.run(startup())
    except Exception as e:
        logging.error(f"Critical error during startup: {e}")
        sys.exit(1)
      
