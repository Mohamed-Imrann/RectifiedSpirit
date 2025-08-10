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
from database.request_forcesub_db import delete_all_one, delete_all_two
from .request_forcesub import create_request_forcesub_buttons
from database.join_reqs import JoinReqs
db1 = JoinReqs
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

    deep_link = None
    if len(message.command) > 1:
        deep_link = message.text.split(None, 1)[1]
        
    if AUTH_CHANNEL and not await is_subscribed(client, message):
        try:
            invite_link = await client.create_chat_invite_link(int(AUTH_CHANNEL))
        except ChatAdminRequired:
            return
        
        btn = [[InlineKeyboardButton("❆ Jᴏɪɴ Oᴜʀ Bᴀᴄᴋ-Uᴘ Cʜᴀɴɴᴇʟ ❆", url=invite_link.invite_link)]]
        if message.command[1] != "subscribe":
            btn.append([InlineKeyboardButton("⏳ Try Again ⏳", callback_data=f"b:{deep_link}")])

        await client.send_message(
            chat_id=message.from_user.id,
            text="♦️ <b><u>READ THIS INSTRUCTION</u></b> ♦️\n\n🗣 <i>Follow instructions to access movies</i>",
            reply_markup=InlineKeyboardMarkup(btn),
            parse_mode=enums.ParseMode.MARKDOWN
        )
        return

    btn = await create_request_forcesub_buttons(message.from_user.id)
    if btn:
        if message.command[1] != "subscribe":
            logger.info(message.command)
            btn.append([InlineKeyboardButton("↻ Tʀʏ Aɢᴀɪɴ", callback_data=f"b:{deep_link}")])
            
        await client.send_message(
            chat_id=message.from_user.id,
            text="<b>Please join channels below to use bot</b>",
            reply_markup=InlineKeyboardMarkup(btn),
            parse_mode=enums.ParseMode.HTML
        )
        return False

    if deep_link:
        temp_msg = await message.reply("Please wait...")

        if deep_link.startswith("get_"):
            args = deep_link.split("_")
            if len(args) == 4:
                channel_id = args[1]
                start = int(args[2])
                end = int(args[3])
                if int(channel_id) not in RAW_DB_CHANNEL:
                    await temp_msg.delete()
                    return
                ids = range(start, end + 1)
            else:
                await temp_msg.edit("Invalid parameters!")
                return

            try:
                messages = await get_messages(client, f"-100{channel_id}", ids)
            except Exception as e:
                logger.error(f"Error fetching messages: {e}")
                await temp_msg.edit(f"Error while fetching messages")
                return

            await temp_msg.delete()
            track_msgs = []

            for msg in messages:
                caption = CUSTOM_CAPTION.format(
                    previouscaption="" if not msg.caption else msg.caption.html,
                    filename=msg.document.file_name
                ) if bool(CUSTOM_CAPTION) and bool(msg.document) else ("" if not msg.caption else msg.caption.html)

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
                except Exception as e:
                    logger.error(f"Error copying message: {e}")

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
                return

            series_name = args[1]
            series_data = ecollection.find_one({"series": series_name})
            if not series_data or not series_data.get("files"):
                logger.warning(f"No files found for series {series_name}")
                return

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
                    logger.warning(f"FloodWait for {e.value} sec")
                    await asyncio.sleep(e.value)
                    sent_msg = await client.send_cached_media(
                        message.chat.id, 
                        entry["file_id"],
                        caption=entry.get("caption", "")
                    )
                    if AUTO_DELETE_TIME and AUTO_DELETE_TIME > 0:
                        track_msgs.append(sent_msg)
                except Exception as e:
                    logger.error(f"Error sending cached media: {e}")

            if track_msgs:
                delete_data = await client.send_message(
                    chat_id=message.from_user.id,
                    text=AUTO_DELETE_MSG.format(time=AUTO_DELETE_TIME)
                )
                asyncio.create_task(delete_file(track_msgs, client, delete_data))
            return

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
    
@Client.on_message(filters.command('restart') & filters.user(ADMINS))
async def restart_bot(client, message):
    msg = await message.reply_text(
        text="<b>Bot Restarting ...</b>"
    )        
    await msg.edit("<b>Restart Successfully Completed ✅</b>")
    system("git pull -f && pip3 install --no-cache-dir -r requirements.txt")
    execle(sys.executable, sys.executable, "bot.py", environ)

    


@Client.on_message(filters.command("purgerequests1") & filters.user(ADMINS))
async def purge_req_one(bot: Client, message: Message):
    pls_wait = await bot.send_message(chat_id=message.chat.id, text="<b>Purging Req One Database...</b>", reply_to_message_id=message.id)
    await asyncio.sleep(1)
    await delete_all_one()
    print("Purged Req One Database.")
    await pls_wait.edit("<b>Req One Database Purged ✅.</b>" )

@Client.on_message(filters.command("purgerequests2") & filters.user(ADMINS))
async def purge_req_two(bot: Client, message: Message):
    pls_wait = await bot.send_message(chat_id=message.chat.id, text="<b>Purging Req Two Database...</b>", reply_to_message_id=message.id)
    await asyncio.sleep(1)
    await delete_all_two()
    print("Purged Req Two Database.")
    await pls_wait.edit("<b>Req Two Database Purged ✅.</b>" )
    
@Client.on_message(filters.command("setchat1") & filters.user(ADMINS))
async def add_fsub_chats1(bot: Client, update: Message):
    chat = update.command[1] if len(update.command) > 1 else None
    if not chat:
        await update.reply_text("Invalid chat id.", quote=True)
        return
    else:
        chat = int(chat)
    await db1().add_fsub_chat1(chat)
    text = f"Added chat <code>{chat}</code> to the database."
    await update.reply_text(text=text, quote=True, parse_mode=enums.ParseMode.HTML)
    with open("./dynamic.env", "wt+") as f:
        f.write(f"REQ_CHANNEL_ONE={chat}\n")
    logger.info("Restarting to update REQ_CHANNEL_ONE from database...")
    await update.reply_text("Restarting...", quote=True)
    os.execl(sys.executable, sys.executable, "bot.py")

@Client.on_message(filters.command("setchat2") & filters.user(ADMINS))
async def add_fsub_chats2(bot: Client, update: Message):
    chat = update.command[1] if len(update.command) > 1 else None
    if not chat:
        await update.reply_text("Invalid chat id.", quote=True)
        return
    else:
        chat = int(chat)
    await db1().add_fsub_chat2(chat)
    text = f"Added chat <code>{chat}</code> to the database."
    await update.reply_text(text=text, quote=True, parse_mode=enums.ParseMode.HTML)
    with open("./dynamic.env", "wt+") as f:
        f.write(f"REQ_CHANNEL_TWO={chat}\n")
    logger.info("Restarting to update REQ_CHANNEL_TWO from database...")
    await update.reply_text("Restarting...", quote=True)
    os.execl(sys.executable, sys.executable, "bot.py")

@Client.on_message(filters.command("viewchat") & filters.user(ADMINS))
async def get_fsub_chat(bot: Client, update: Message):
    try:
        processing_msg = await update.reply_text("Processing...", quote=True)
        chat1 = await db1().get_fsub_chat1()
        chat2 = await db1().get_fsub_chat2()
        if not chat1 and not chat2:
            await processing_msg.delete()
            await update.reply_text("No fsub chat found in the database.", quote=True)
            return
        text = "Fsub chats found:\n"
        if chat1:
            text += f"Chat 1: <code>{chat1['chat_id']}</code>\n"
        else:
            text += "Chat 1: Not set\n"
        if chat2:
            text += f"Chat 2: <code>{chat2['chat_id']}</code>\n"
        else:
            text += "Chat 2: Not set\n"
        await processing_msg.delete()
        await update.reply_text(text, quote=True, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        await processing_msg.delete()
        logging.error(f"Error fetching fsub chats: {e}")
        await update.reply_text("An error occurred while fetching the fsub chats. Please check the logs for more details.", quote=True)
