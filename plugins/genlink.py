import re
import asyncio
import time
from pyrogram import filters, Client, enums
from pyrogram.errors import FloodWait
from pymongo import MongoClient
from pyrogram.errors.exceptions.bad_request_400 import ChannelInvalid, UsernameInvalid, UsernameNotModified
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from info import ADMINS, AUTH_CHANNEL, DB_CHANNEL, DATABASE_URI
from database.ia_filterdb import unpack_new_file_id
from utils import temp, get_message_id
import re
import os
import json
import base64
from pyrogram.file_id import FileId
import zlib
import logging

BATCH_STORE = int('-1002250913478')

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
mongo_client = MongoClient(DATABASE_URI)
db = mongo_client["file_database"]
collection = db["episodes"]

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
    await message.reply_text(f"{result_string}")



def unpack_new_file_id(new_file_id):
    decoded = FileId.decode(new_file_id)
    file_id = new_file_id  # Store full file_id
    file_ref = decoded.file_reference
    return file_id, file_ref


@Client.on_message(filters.command("eadd") & filters.reply & filters.create(allowed))
async def add_file(client, message):
    media = getattr(message.reply_to_message, message.reply_to_message.media.value, None)
    if not media:
        return await message.reply("Reply to a valid file (document, video, audio, etc.).")
    
    file_id, file_ref = unpack_new_file_id(media.file_id)
    caption = message.reply_to_message.caption or "No Caption"
    series_name = message.command[1] if len(message.command) > 1 else None
    if not series_name:
        return await message.reply("Usage: `/eadd <series_name>` (reply to a file)")
    
    series_data = collection.find_one({"series": series_name})
    new_entry = {"file_id": file_id, "file_ref": file_ref, "caption": caption}
    
    if series_data:
        collection.update_one({"series": series_name}, {"$push": {"files": new_entry}})
    else:
        collection.insert_one({"series": series_name, "files": [new_entry]})
    
    await message.reply(f"✅ File added to `{series_name}`")


@Client.on_message(filters.command("edell") & filters.create(allowed))
async def delete_series(client, message):
    series_name = message.command[1] if len(message.command) > 1 else None
    if not series_name:
        return await message.reply("Usage: `/edell series_name`")
    
    result = collection.delete_one({"series": series_name})
    
    if result.deleted_count == 0:
        return await message.reply(f"❌ No such series `{series_name}` found.")
    
    await message.reply(f"✅ `{series_name}` and all its files have been deleted.")

@Client.on_message(filters.command("eall") & filters.create(allowed))
async def list_series(client, message):
    series_list = collection.find()
    if not series_list:
        return await message.reply("No series found.")
    
    response = "**📂 Stored Series:**\n"
    for series in series_list:
        response += f"**{series['series']}** → {len(series['files'])} files\n"
    
    await message.reply(response)
