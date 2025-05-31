import sys
import asyncio
import datetime, pytz, time
from os import environ, execle, system
import os
import logging
import random
from typing import List, Tuple
from Script import script
from pyrogram import Client, filters, enums
from pyrogram.errors import ChatAdminRequired, FloodWait
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from database.ia_filterdb import Media, get_file_details, unpack_new_file_id
from database.users_chats_db import db
from plugins.fsub import ForceSub
from pymongo import MongoClient
from info import ADMINS, AUTH_CHANNEL, LOG_CHANNEL, CUSTOM_FILE_CAPTION, PROTECT_CONTENT, DATABASE_URI, DATABASE_NAME, AUTO_DELETE_TIME, AUTO_DELETE_MSG, BATCH_FILE_CAPTION as CUSTOM_CAPTION, DB_CHANNEL, RAW_DB_CHANNEL, STICKER, STICKER_ID, PIC, PICS, START_TXT
from utils import get_size, is_subscribed, temp, temp_requests
import re
import json
import base64
logger = logging.getLogger(__name__)

import pymongo

BATCH_FILES = {}
from utils import get_messages, delete_file

mongo_client = MongoClient(DATABASE_URI)
edb = mongo_client["file_database"]
ecollection = edb["episodes"]
logger = logging.getLogger(__name__)

@Client.on_message(filters.command("start"))
async def start_command(client, message):
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        await asyncio.sleep(4)
        if not await db.get_chat(message.chat.id):
            total = await client.get_chat_members_count(message.chat.id)
            await client.send_message(LOG_CHANNEL, script.LOG_TEXT_G.format(message.chat.title, message.chat.id, total, "Unknown"))       
            await db.add_chat(message.chat.id, message.chat.title)
        return 
    
    if not await db.is_user_exist(message.from_user.id):
        await db.add_user(message.from_user.id, message.from_user.first_name)

    if len(message.command) > 1:
        deep_link = message.text.split(None, 1)[1]
        status = await ForceSub(client, message, file_id=deep_link)
        if not status:
            return
        
        temp_msg = await message.reply("Please wait...")

        if deep_link.startswith("get_"):
            args = deep_link.split("_")
            if len(args) == 4:
                channel_id = args[1]
                if int(channel_id) not in RAW_DB_CHANNEL:
                    await temp_msg.edit("The channel is not in the allowed database channels!")
                    return
                
                start = int(args[2])
                end = int(args[3])
                ids = range(start, end + 1)
            else:
                await temp_msg.edit("Invalid parameters in the deep link!")
                return

            try:
                messages = await get_messages(client, f"-100{channel_id}", ids)
            except Exception as e:
                await temp_msg.edit(f"Error while fetching messages: {str(e)}")
                return

            await temp_msg.delete()
            track_msgs = []

            for msg in messages:
                caption = CUSTOM_CAPTION.format(
                    previouscaption="" if not msg.caption else msg.caption.html,
                    filename=msg.document.file_name
                ) if bool(CUSTOM_CAPTION) and bool(msg.document) else "" if not msg.caption else msg.caption.html

                try:
                    copied_msg = await msg.copy(
                        chat_id=message.from_user.id,
                        caption=caption,
                        parse_mode=enums.ParseMode.HTML
                    )
                    if AUTO_DELETE_TIME and AUTO_DELETE_TIME > 0:
                        track_msgs.append(copied_msg)
                    await asyncio.sleep(0.5)
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                    copied_msg = await msg.copy(
                        chat_id=message.from_user.id,
                        caption=caption,
                        parse_mode=enums.ParseMode.HTML
                    )
                    if AUTO_DELETE_TIME and AUTO_DELETE_TIME > 0:
                        track_msgs.append(copied_msg)
                except:
                    pass

            if track_msgs:
                delete_data = await client.send_message(
                    chat_id=message.from_user.id,
                    text=AUTO_DELETE_MSG.format(time=AUTO_DELETE_TIME)
                )
                asyncio.create_task(delete_file(track_msgs, client, delete_data))

            return

        elif deep_link.startswith("e_"):
            args = deep_link.split("_")
            if len(args) < 2:
                return #await temp_msg.edit("❌ Invalid series key.")

            series_name = args[1]
            series_data = ecollection.find_one({"series": series_name})
            if not series_data or not series_data.get("files"):
                return #await temp_msg.edit(f"No files found in {series_name}.")

            #await temp_msg.edit(f"📤 Sending {series_name} files...")
            track_msgs = []

            for entry in series_data["files"]:
                try:
                    sent_msg = await client.send_cached_media(
                        message.chat.id, 
                        entry["file_id"],
                        caption=entry.get("caption", "")
                    )
                    if AUTO_DELETE_TIME and AUTO_DELETE_TIME > 0:
                        track_msgs.append(sent_msg)
                    await asyncio.sleep(0.5)
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                    sent_msg = await client.send_cached_media(
                        message.chat.id, 
                        entry["file_id"],
                        caption=entry.get("caption", "")
                    )
                    if AUTO_DELETE_TIME and AUTO_DELETE_TIME > 0:
                        track_msgs.append(sent_msg)
                except:
                    pass

            if track_msgs:
                delete_data = await client.send_message(
                    chat_id=message.from_user.id,
                    text=AUTO_DELETE_MSG.format(time=AUTO_DELETE_TIME)
                )
                asyncio.create_task(delete_file(track_msgs, client, delete_data))

            return

    #buttons = [[InlineKeyboardButton('Switch Inline', switch_inline_query_current_chat='')]]
    #reply_markup = InlineKeyboardMarkup(buttons)

    if STICKER:
        await message.reply_sticker(STICKER_ID)
        await message.reply_text(text=START_TXT, parse_mode=enums.ParseMode.MARKDOWN)
    elif PIC:
        await message.reply_photo(photo=PICS, caption=START_TXT, parse_mode=enums.ParseMode.MARKDOWN)
    else:
        await message.reply_text(text=START_TXT, parse_mode=enums.ParseMode.MARKDOWN)


@Client.on_message(filters.command("logs") & filters.user(ADMINS))
async def log_file(bot, message):
    """Send log file"""
    try:
        await message.reply_document('TelegramBot.txt')
    except Exception as e:
        await message.reply(str(e))

@Client.on_message(filters.command("help") & filters.user(ADMINS))
async def help(bot, message):
    await message.reply_text(
        text=script.HELP_TXT,
        parse_mode=enums.ParseMode.HTML
    )
    
@Client.on_message(filters.command('restart') & filters.user(ADMINS))
async def restart_bot(client, message):
    msg = await message.reply_text(
        text="<b>Bot Restarting ...</b>"
    )        
    await msg.edit("<b>Restart Successfully Completed ✅</b>")
    system("git pull -f && pip3 install --no-cache-dir -r requirements.txt")
    execle(sys.executable, sys.executable, "bot.py", environ)

    
