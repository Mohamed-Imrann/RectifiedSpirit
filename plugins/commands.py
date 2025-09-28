#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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
from pyrogram.errors import ChatAdminRequired, FloodWait, BadRequest
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
#from database.ia_filterdb import Media, get_file_details, unpack_new_file_id
from database.users_chats_db import db
from database.request_forcesub_db import delete_all_one, delete_all_two
from .request_forcesub import create_request_forcesub_buttons
from database.join_reqs import JoinReqs
db1 = JoinReqs
from pymongo import MongoClient
from info import ADMINS, AUTH_CHANNEL, LOG_CHANNEL, CUSTOM_FILE_CAPTION, BATCH_FILE_CAPTION, PROTECT_CONTENT, DATABASE_URI, DATABASE_NAME, AUTO_DELETE_TIME, AUTO_DELETE_MSG, BATCH_FILE_CAPTION as CUSTOM_CAPTION, DB_CHANNEL, RAW_DB_CHANNEL, STICKER, STICKER_ID, PIC, PICS, START_TXT
from utils import get_size, is_subscribed, temp, temp_requests
import re
import json
import base64

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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
    try:
        #logger.info(f"Start command received from user {message.from_user.id} in chat {message.chat.id}")
        
        if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            #logger.info(f"Processing group chat: {message.chat.title} ({message.chat.id})")
            await asyncio.sleep(4)
            if not await db.get_chat(message.chat.id):
                total = await client.get_chat_members_count(message.chat.id)
                #logger.info(f"Adding new group to database: {message.chat.title} with {total} members")
                await client.send_message(LOG_CHANNEL, script.LOG_TEXT_G.format(message.chat.title, message.chat.id, total, "Unknown"))       
                await db.add_chat(message.chat.id, message.chat.title)
            return 

        if not await db.is_user_exist(message.from_user.id):
            #logger.info(f"Adding new user to database: {message.from_user.first_name} ({message.from_user.id})")
            await db.add_user(message.from_user.id, message.from_user.first_name)

        deep_link = None
        if len(message.command) > 1:
            deep_link = message.text.split(None, 1)[1]
            #logger.info(f"Processing deep link: {deep_link}")
            
        if AUTH_CHANNEL and not await is_subscribed(client, message):
            try:
                invite_link = await client.create_chat_invite_link(int(AUTH_CHANNEL))
            except ChatAdminRequired:
                logger.error("ChatAdminRequired error while creating invite link")
                return
            
            btn = [[InlineKeyboardButton("❆ Jᴏɪɴ Oᴜʀ Bᴀᴄᴋ-Uᴘ Cʜᴀɴɴᴇʟ ❆", url=invite_link.invite_link)]]
            if len(message.command) > 1 and message.command[1] != "subscribe":
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
            if len(message.command) > 1 and message.command[1] != "subscribe":
                #logger.info(message.command)
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
                        #logger.warning(f"Channel {channel_id} not in allowed database channels")
                        await temp_msg.delete()
                        return
                    ids = range(start, end + 1)
                    #logger.info(f"Fetching messages from channel {channel_id}, IDs {start} to {end}")
                else:
                    #logger.error(f"Invalid parameters in deep link: {deep_link}")
                    await temp_msg.delete()
                    return

                try:
                    messages = await asyncio.wait_for(
                        get_messages(client, f"-100{channel_id}", ids),
                        timeout=30.0
                    )
                    #logger.info(f"Successfully fetched {len(messages)} messages")
                except asyncio.TimeoutError:
                    logger.error("Timeout while fetching messages")
                    await temp_msg.delete()
                    return
                except Exception as e:
                    logger.error(f"Error fetching messages: {e}")
                    await temp_msg.delete()
                    return

                await temp_msg.delete()
                track_msgs = []

                for msg in messages:
                    try:
                        caption = CUSTOM_CAPTION.format(
                            previouscaption="" if not msg.caption else msg.caption.html,
                            filename=msg.document.file_name
                        ) if bool(CUSTOM_CAPTION) and bool(msg.document) else ("" if not msg.caption else msg.caption.html)

                        # Properly handle reply_markup
                        reply_markup = msg.reply_markup

                        if AUTO_DELETE_TIME and AUTO_DELETE_TIME > 0:
                            try:
                                #logger.info(f"Copying message with auto-delete enabled")
                                copied_msg = await msg.copy(
                                    chat_id=message.from_user.id,
                                    caption=caption,
                                    parse_mode=enums.ParseMode.HTML,
                                    reply_markup=reply_markup
                                )
                                if copied_msg:
                                    track_msgs.append(copied_msg)
                                    #logger.info(f"Message copied successfully, tracking for deletion")
                            except FloodWait as e:
                                logger.warning(f"FloodWait encountered: {e.value} seconds")
                                await asyncio.sleep(e.value)
                                copied_msg = await msg.copy(
                                    chat_id=message.from_user.id,
                                    caption=caption,
                                    parse_mode=enums.ParseMode.HTML,
                                    reply_markup=reply_markup
                                )
                                if copied_msg:
                                    track_msgs.append(copied_msg)
                            except BadRequest as e:
                                logger.error(f"BadRequest copying message: {str(e)}")
                                continue
                            except Exception as e:
                                logger.error(f"Error copying message: {str(e)}")
                                continue
                        else:
                            try:
                                #logger.info(f"Copying message without auto-delete")
                                await msg.copy(
                                    chat_id=message.from_user.id,
                                    caption=caption,
                                    parse_mode=enums.ParseMode.HTML,
                                    reply_markup=reply_markup
                                )
                                await asyncio.sleep(0.5)
                            except FloodWait as e:
                                logger.warning(f"FloodWait encountered: {e.value} seconds")
                                await asyncio.sleep(e.value)
                                await msg.copy(
                                    chat_id=message.from_user.id,
                                    caption=caption,
                                    parse_mode=enums.ParseMode.HTML,
                                    reply_markup=reply_markup
                                )
                            except BadRequest as e:
                                logger.error(f"BadRequest copying message: {str(e)}")
                                continue
                            except Exception as e:
                                logger.error(f"Error copying message: {str(e)}")
                                continue
                    except Exception as e:
                        logger.error(f"Unexpected error processing message: {str(e)}")
                        continue

                if track_msgs:
                    #logger.info(f"Sending auto-delete notification for {len(track_msgs)} messages")
                    delete_data = await client.send_message(
                        chat_id=message.from_user.id,
                        text=AUTO_DELETE_MSG.format(time=AUTO_DELETE_TIME)
                    )
                    asyncio.create_task(delete_file(track_msgs, client, delete_data))
                else:
                    #logger.info("No messages to track for deletion")
                return

            elif deep_link.startswith("e_"):
                args = deep_link.split("_")
                if len(args) < 2:
                    logger.error("Invalid series key: not enough arguments")
                    return 
                    
                series_name = args[1]
                #logger.info(f"Looking for series: {series_name}")
                series_data = ecollection.find_one({"series": series_name})
                if not series_data or not series_data.get("files"):
                    logger.warning(f"No files found for series: {series_name}")
                    return
                    
                await message.reply(f"📤 Sending {series_name} files...")
                messages = []
                files_count = len(series_data["files"])
                #logger.info(f"Found {files_count} files in series {series_name}")

                for i, entry in enumerate(series_data["files"]):
                    try:
                        #logger.info(f"Sending file {i+1}/{files_count} from series {series_name}")
                        sent_msg = await client.send_cached_media(
                            message.chat.id, 
                            entry["file_id"],
                            caption=entry.get("caption", ""),
                            protect_content=PROTECT_CONTENT
                        )
                        messages.append(sent_msg)
                        await asyncio.sleep(3)
                    except FloodWait as e:
                        logger.warning(f"FloodWait encountered: {e.value} seconds")
                        await asyncio.sleep(e.value)
                    except BadRequest as e:
                        logger.error(f"BadRequest sending file {i+1}: {str(e)}")
                        continue
                    except Exception as e:
                        logger.error(f"Error sending file {i+1}: {str(e)}")
                        continue

                #await message.reply(f"✅ All files from {series_name} have been sent.")
                #logger.info(f"Successfully sent {len(messages)} files from series {series_name}")
                return
            
            elif deep_link.startswith("B-"):
                #logger.info(f"Processing batch file deep link: {deep_link}")
                sts = await message.reply("𝖳𝗁𝖾 𝖱𝖾𝗊𝗎𝖾𝗌𝗍𝖾𝖽 𝖥𝗂𝗅𝖾𝗌.....\n𝖪𝗂𝗇𝖽𝗅𝗒 𝖶𝖺𝗂𝗍!!!!")
                file_id = deep_link.split("-", 1)[1]
                msgs = BATCH_FILES.get(file_id)

                if not msgs:
                    #logger.info(f"Downloading batch file: {file_id}")
                    file = await client.download_media(file_id)
                    try:
                        with open(file) as file_data:
                            msgs = json.loads(file_data.read())
                            #logger.info(f"Loaded {len(msgs)} messages from batch file")
                    except Exception as e:
                        logger.error(f"Error opening batch file: {str(e)}")
                        await sts.edit("FAILED")
                        return await client.send_message(LOG_CHANNEL, f"UNABLE TO OPEN FILE: {str(e)}")
                    os.remove(file)
                    BATCH_FILES[file_id] = msgs

                new_messages = []
                for msg in msgs:
                    try:
                        title = msg.get("title")
                        size = get_size(int(msg.get("size", 0)))
                        f_caption = msg.get("caption", "")

                        if BATCH_FILE_CAPTION:
                            try:
                                f_caption = BATCH_FILE_CAPTION.format(
                                    file_name='' if title is None else title,
                                    file_size='' if size is None else size,
                                    file_caption='' if f_caption is None else f_caption
                                )
                            except Exception as e:
                                logger.error(f"Error formatting batch caption: {str(e)}")
                                f_caption = f_caption

                        if f_caption is None:
                            f_caption = f"{title}"

                        #logger.info(f"Sending cached media: {title}")
                        bj = await client.send_cached_media(
                            chat_id=message.from_user.id,
                            file_id=msg.get("file_id"),
                            caption=f_caption,
                            protect_content=msg.get('protect', PROTECT_CONTENT)
                        )
                        new_messages.append(bj)
                        await asyncio.sleep(1)
                    except FloodWait as e:
                        logger.warning(f"FloodWait encountered: {e.x} seconds")
                        await asyncio.sleep(e.x)
                        try:
                            bj = await client.send_cached_media(
                                chat_id=message.from_user.id,
                                file_id=msg.get("file_id"),
                                caption=f_caption,
                                protect_content=msg.get('protect', PROTECT_CONTENT)
                            )
                            new_messages.append(bj)
                        except Exception as e:
                            logger.error(f"Error after FloodWait: {str(e)}")
                            continue
                    except BadRequest as e:
                        logger.error(f"BadRequest sending cached media: {str(e)}")
                        continue
                    except Exception as e:
                        logger.error(f"Error sending cached media: {str(e)}")
                        continue

                await sts.delete()
                #await message.reply(f"✅ All files have been sent.")
                #logger.info(f"Successfully sent {len(new_messages)} files from batch")
                return

        buttons = [[InlineKeyboardButton('Switch Inline', switch_inline_query_current_chat='')]]
        reply_markup = InlineKeyboardMarkup(buttons)
        
        #logger.info("Sending start message with sticker")
        try:
            await message.reply_sticker(STICKER_ID)
        except Exception as e:
            logger.error(f"Error sending sticker: {str(e)}")
        
        #logger.info("Sending start message text")
        try:
            await message.reply_text(
                text=START_TXT,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error sending start text: {str(e)}")
        
        return
    except Exception as e:
        logger.error(f"Unexpected error in start_command: {str(e)}", exc_info=True)
        try:
            await message.reply_text(f"Something Went Wrong, Try Again")
        except:
            pass

@Client.on_message(filters.command("logs") & filters.user(ADMINS))
async def log_file(bot, message):
    """Send log file"""
    #logger.info(f"Admin {message.from_user.id} requested log file")
    try:
        await message.reply_document('TelegramBot.txt')
        logger.info("Log file sent successfully")
    except Exception as e:
        logger.error(f"Error sending log file: {str(e)}")
        await message.reply(str(e)) 
    
@Client.on_message(filters.command('restart') & filters.user(ADMINS))
async def restart_bot(client, message):
    logger.info(f"Admin {message.from_user.id} requested bot restart")
    try:
        msg = await message.reply_text(
            text="<b>Bot Restarting ...</b>"
        )        
        await msg.edit("<b>Restart Successfully Completed ✅</b>")
        #logger.info("Executing restart commands")
        system("git pull -f && pip3 install --no-cache-dir -r requirements.txt")
        execle(sys.executable, sys.executable, "bot.py", environ)
    except Exception as e:
        logger.error(f"Error during restart: {str(e)}")
        await message.reply_text(f"Restart failed: {str(e)}")

@Client.on_message(filters.command("purgerequests1") & filters.user(ADMINS))
async def purge_req_one(bot: Client, message: Message):
    #logger.info(f"Admin {message.from_user.id} requested to purge req one database")
    pls_wait = await bot.send_message(chat_id=message.chat.id, text="<b>Purging Req One Database...</b>", reply_to_message_id=message.id)
    await asyncio.sleep(1)
    await delete_all_one()
    #logger.info("Purged Req One Database.")
    await pls_wait.edit("<b>Req One Database Purged ✅.</b>" )

@Client.on_message(filters.command("purgerequests2") & filters.user(ADMINS))
async def purge_req_two(bot: Client, message: Message):
    #logger.info(f"Admin {message.from_user.id} requested to purge req two database")
    pls_wait = await bot.send_message(chat_id=message.chat.id, text="<b>Purging Req Two Database...</b>", reply_to_message_id=message.id)
    await asyncio.sleep(1)
    await delete_all_two()
    #logger.info("Purged Req Two Database.")
    await pls_wait.edit("<b>Req Two Database Purged ✅.</b>" )
    
@Client.on_message(filters.command("setchat1") & filters.user(ADMINS))
async def add_fsub_chats1(bot: Client, update: Message):
    #logger.info(f"Admin {update.from_user.id} requested to set chat 1")
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
    logger.info(f"Admin {update.from_user.id} requested to set chat 2")
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
        logger.info(f"Admin {update.from_user.id} requested to view fsub chats")
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

@Client.on_message(filters.command("delchat1") & filters.user(ADMINS))
async def delete_fsub_chat1(bot: Client, update: Message):
    logger.info(f"Admin {update.from_user.id} requested to delete chat 1")
    try:
        chat_data = await db1().get_fsub_chat1()
        if not chat_data:
            await update.reply_text("Chat 1 is not set in the database.", quote=True)
            return
        
        chat_id = chat_data['chat_id']
        await db1().delete_fsub_chat1(chat_id)
        
        # Update dynamic.env file
        with open("./dynamic.env", "wt+") as f:
            f.write("REQ_CHANNEL_ONE=None")
        
        text = f"Removed chat <code>{chat_id}</code> from the database."
        await update.reply_text(text=text, quote=True, parse_mode=enums.ParseMode.HTML)
        
        logger.info("Restarting to update REQ_CHANNEL_ONE from database...")
        await update.reply_text("Restarting...", quote=True)
        os.execl(sys.executable, sys.executable, "bot.py")
        
    except Exception as e:
        logger.error(f"Error deleting chat 1: {e}")
        await update.reply_text("An error occurred while deleting chat 1. Please check the logs.", quote=True)

@Client.on_message(filters.command("delchat2") & filters.user(ADMINS))
async def delete_fsub_chat2(bot: Client, update: Message):
    logger.info(f"Admin {update.from_user.id} requested to delete chat 2")
    try:
        chat_data = await db1().get_fsub_chat2()
        if not chat_data:
            await update.reply_text("Chat 2 is not set in the database.", quote=True)
            return
        
        chat_id = chat_data['chat_id']
        await db1().delete_fsub_chat2(chat_id)
        
        # Update dynamic.env file
        with open("./dynamic.env", "wt+") as f:
            f.write("REQ_CHANNEL_TWO=None")
        
        text = f"Removed chat <code>{chat_id}</code> from the database."
        await update.reply_text(text=text, quote=True, parse_mode=enums.ParseMode.HTML)
        
        logger.info("Restarting to update REQ_CHANNEL_TWO from database...")
        await update.reply_text("Restarting...", quote=True)
        os.execl(sys.executable, sys.executable, "bot.py")
        
    except Exception as e:
        logger.error(f"Error deleting chat 2: {e}")
        await update.reply_text("An error occurred while deleting chat 2. Please check the logs.", quote=True)
