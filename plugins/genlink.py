import re
import asyncio
from pyrogram import filters, Client, enums
from pyrogram.errors.exceptions.bad_request_400 import ChannelInvalid, UsernameInvalid, UsernameNotModified
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from info import ADMINS, AUTH_CHANNEL, DB_CHANNEL
from database.ia_filterdb import unpack_new_file_id
from utils import temp, get_message_id
import re
import os
import json
import base64
import zlib
import logging

BATCH_STORE = int('-1002250913478')


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

async def allowed(_, __, message):
    if message.from_user and message.from_user.id in ADMINS:
        return True
    return False


import logging
import asyncio

logger = logging.getLogger(__name__)

@Client.on_message(filters.private & filters.command('batch') & filters.create(allowed))
async def batch(client, message):
   
    while True:
        try:         
            first_message = await client.ask(
                text="Forward the First Message from DB Channel (with Quotes) or Send the DB Channel Post Link",
                chat_id=message.from_user.id,
                filters=(filters.forwarded | (filters.text & ~filters.forwarded)),
                timeout=60
            )
        except asyncio.TimeoutError:      
            return
        
        channel_id, f_msg_id = await get_message_id(client, first_message)
        
        if channel_id and f_msg_id:
            break
        else:
            await first_message.reply(" Error\n\nThis message/link is not from a valid DB Channel.", quote=True)
            continue

    while True:
        try:
            second_message = await client.ask(
                text="Forward the Last Message from DB Channel (with Quotes) or Send the DB Channel Post Link",
                chat_id=message.from_user.id,
                filters=(filters.forwarded | (filters.text & ~filters.forwarded)),
                timeout=60
            )
        except asyncio.TimeoutError:
            return

        s_channel_id, s_msg_id = await get_message_id(client, second_message)
        
        if s_channel_id == channel_id and s_msg_id:
            break
        else:
            await second_message.reply(" Error\n\nThis message/link is not from the same DB Channel.", quote=True)
            continue

    raw_channel_id = channel_id.replace("-100", "")
    result_string = f"get_{raw_channel_id}_{f_msg_id}_{s_msg_id}"
    logger.info(f"Generated result string: {result_string}")
    await message.reply_text(f"{result_string}")
