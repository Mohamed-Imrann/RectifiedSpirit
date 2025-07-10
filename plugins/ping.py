import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

from pyrogram import Client, filters
from pyrogram.types import Message
import time
from utils import temp

@Client.on_message(filters.command("ping"))
async def ping_command(client, message: Message):
    start_time = time.time()
    reply_message = await message.reply_text("Pong!")
    end_time = time.time()
    
    ping_time = round((end_time - start_time) * 1000, 3)
    
    await reply_message.edit_text(f"Pong! `{ping_time}ms`")
