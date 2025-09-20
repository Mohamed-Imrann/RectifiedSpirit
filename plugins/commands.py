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
from database.ia_filterdb import Media, get_file_details, unpack_new_file_id
from database.users_chats_db import db
from plugins.fsub import ForceSub
from info import CHANNELS, ADMINS, AUTH_CHANNEL, LOG_CHANNEL, BATCH_FILE_CAPTION, CUSTOM_FILE_CAPTION, PROTECT_CONTENT, DATABASE_URI, DATABASE_NAME, STIC, AUTO_DELETE_TIME, AUTO_DELETE_MSG, BATCH_FILE_CAPTION as CUSTOM_CAPTION, DB_CHANNEL, RAW_DB_CHANNEL
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

mongo_client = pymongo.MongoClient(DATABASE_URI)
edb = mongo_client["file_database"]
ecollection = edb["episodes"]
logger = logging.getLogger(__name__)

@Client.on_message(filters.command("start"))
async def start_command(client, message):
    try:
        logger.info(f"Start command received from user {message.from_user.id} in chat {message.chat.id}")
        
        if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            logger.info(f"Processing group chat: {message.chat.title} ({message.chat.id})")
            await asyncio.sleep(4)
            if not await db.get_chat(message.chat.id):
                total = await client.get_chat_members_count(message.chat.id)
                logger.info(f"Adding new group to database: {message.chat.title} with {total} members")
                await client.send_message(LOG_CHANNEL, script.LOG_TEXT_G.format(message.chat.title, message.chat.id, total, "Unknown"))
                await db.add_chat(message.chat.id, message.chat.title)
            return

        if not await db.is_user_exist(message.from_user.id):
            logger.info(f"Adding new user to database: {message.from_user.first_name} ({message.from_user.id})")
            await db.add_user(message.from_user.id, message.from_user.first_name)

        if len(message.command) > 1:
            deep_link = message.text.split(None, 1)[1]
            logger.info(f"Processing deep link: {deep_link}")

            status = await ForceSub(client, message, file_id=deep_link)
            if not status:
                logger.info(f"ForceSub check failed for deep link: {deep_link}")
                if deep_link.startswith("B-"):
                    temp_requests[message.from_user.id] = deep_link.split("-", 1)[1]
                return

            if deep_link.startswith("get_"):
                temp_msg = await message.reply("Please wait...")
                logger.info(f"Processing get_ deep link: {deep_link}")
                try:
                    argument = deep_link.split("_")
                    if len(argument) == 4:
                        channel_id = argument[1]
                        if int(channel_id) not in RAW_DB_CHANNEL:
                            logger.warning(f"Channel {channel_id} not in allowed database channels")
                            await temp_msg.edit("The channel is not in the allowed database channels!")
                            return

                        start = int(argument[2])
                        end = int(argument[3])
                        ids = range(start, end + 1)
                        logger.info(f"Fetching messages from channel {channel_id}, IDs {start} to {end}")
                    else:
                        logger.error(f"Invalid parameters in deep link: {deep_link}")
                        await temp_msg.edit("Invalid parameters in the deep link!")
                        return
                except ValueError as e:
                    logger.error(f"ValueError processing deep link {deep_link}: {str(e)}")
                    await temp_msg.edit("Invalid link format!")
                    return

                try:
                    messages = await get_messages(client, f"-100{channel_id}", ids)
                    logger.info(f"Successfully fetched {len(messages)} messages")
                except Exception as e:
                    logger.error(f"Error fetching messages: {str(e)}")
                    await temp_msg.edit(f"Error while fetching messages: {str(e)}")
                    return

                await temp_msg.delete()
                track_msgs = []

                for msg in messages:
                    try:
                        if bool(CUSTOM_CAPTION) and bool(msg.document):
                            caption = CUSTOM_CAPTION.format(
                                file_caption="" if not msg.caption else msg.caption.html,
                                filename=msg.document.file_name
                            )
                        else:
                            caption = "" if not msg.caption else msg.caption.html

                        # Fix: Properly handle reply_markup
                        reply_markup = msg.reply_markup

                        if AUTO_DELETE_TIME and AUTO_DELETE_TIME > 0:
                            try:
                                logger.info(f"Copying message with auto-delete enabled")
                                copied_msg_for_deletion = await msg.copy(
                                    chat_id=message.from_user.id,
                                    caption=caption,
                                    parse_mode=enums.ParseMode.HTML,
                                    reply_markup=reply_markup
                                )
                                if copied_msg_for_deletion:
                                    track_msgs.append(copied_msg_for_deletion)
                                    logger.info(f"Message copied successfully, tracking for deletion")
                            except FloodWait as e:
                                logger.warning(f"FloodWait encountered: {e.value} seconds")
                                await asyncio.sleep(e.value)
                                copied_msg_for_deletion = await msg.copy(
                                    chat_id=message.from_user.id,
                                    caption=caption,
                                    parse_mode=enums.ParseMode.HTML,
                                    reply_markup=reply_markup
                                )
                                if copied_msg_for_deletion:
                                    track_msgs.append(copied_msg_for_deletion)
                            except BadRequest as e:
                                logger.error(f"BadRequest copying message: {str(e)}")
                                pass
                            except Exception as e:
                                logger.error(f"Error copying message: {str(e)}")
                                pass
                        else:
                            try:
                                logger.info(f"Copying message without auto-delete")
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
                                pass
                            except Exception as e:
                                logger.error(f"Error copying message: {str(e)}")
                                pass
                    except Exception as e:
                        logger.error(f"Unexpected error processing message: {str(e)}")
                        continue

                if track_msgs:
                    logger.info(f"Sending auto-delete notification for {len(track_msgs)} messages")
                    delete_data = await client.send_message(
                        chat_id=message.from_user.id,
                        text=AUTO_DELETE_MSG.format(time=AUTO_DELETE_TIME)
                    )
                    asyncio.create_task(delete_file(track_msgs, client, delete_data))
                else:
                    logger.info("No messages to track for deletion")
                return

            elif deep_link.startswith("B-"):
                logger.info(f"Processing batch file deep link: {deep_link}")
                sts = await message.reply("𝖳𝗁𝖾 𝖱𝖾𝗊𝗎𝖾𝗌𝗍𝖾𝖽 𝖥𝗂𝗅𝖾𝗌.....\n𝖪𝗂𝗇𝖽𝗅𝗒 𝖶𝖺𝗂𝗍!!!!")
                file_id = deep_link.split("-", 1)[1]
                msgs = BATCH_FILES.get(file_id)

                if not msgs:
                    logger.info(f"Downloading batch file: {file_id}")
                    file = await client.download_media(file_id)
                    try:
                        with open(file) as file_data:
                            msgs = json.loads(file_data.read())
                            logger.info(f"Loaded {len(msgs)} messages from batch file")
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

                        logger.info(f"Sending cached media: {title}")
                        # Fix: Ensure proper parameters for send_cached_media
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
                await message.reply(f"✅ All files have been sent.")
                logger.info(f"Successfully sent {len(new_messages)} files from batch")
                return

            elif deep_link.startswith("e_"):
                logger.info(f"Processing series deep link: {deep_link}")
                args = deep_link.split("_")
                if len(args) < 2:
                    logger.error("Invalid series key: not enough arguments")
                    return await message.reply("❌ Invalid series key.")

                series_name = args[1]
                logger.info(f"Looking for series: {series_name}")
                series_data = ecollection.find_one({"series": series_name})
                if not series_data or not series_data.get("files"):
                    logger.warning(f"No files found for series: {series_name}")
                    return await message.reply(f"No files found in {series_name}.")

                await message.reply(f"📤 Sending {series_name} files...")
                messages = []
                files_count = len(series_data["files"])
                logger.info(f"Found {files_count} files in series {series_name}")

                for i, entry in enumerate(series_data["files"]):
                    try:
                        logger.info(f"Sending file {i+1}/{files_count} from series {series_name}")
                        # Fix: Ensure proper parameters for send_cached_media
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

                await message.reply(f"✅ All files from {series_name} have been sent.")
                logger.info(f"Successfully sent {len(messages)} files from series {series_name}")
                return

        buttons = [[InlineKeyboardButton('Switch Inline', switch_inline_query_current_chat='')]]
        reply_markup = InlineKeyboardMarkup(buttons)
        
        logger.info("Sending start message with sticker")
        try:
            await message.reply_sticker("CAACAgUAAxkBAAJ0w2aZJMdpnEKbXtDVPJIvpL2XhIAhAAIrAAO8ljUq9-AkUFoHiMQeBA")
        except Exception as e:
            logger.error(f"Error sending sticker: {str(e)}")
        
        logger.info("Sending start message text")
        try:
            await message.reply_text(
                text=script.START_TXT,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Error sending start text: {str(e)}")
        
        return
    except Exception as e:
        logger.error(f"Unexpected error in start_command: {str(e)}", exc_info=True)
        try:
            await message.reply_text(f"An error occurred: {str(e)}")
        except:
            pass

async def delete_files_later(messages, client, process):
    """Auto-delete files after AUTO_DELETE_TIME."""
    logger.info(f"Scheduling deletion of {len(messages)} messages in {AUTO_DELETE_TIME} seconds")
    await asyncio.sleep(AUTO_DELETE_TIME)
    deleted_count = 0
    
    for msg in messages:
        try:
            await client.delete_messages(msg.chat.id, msg.id)
            deleted_count += 1
        except FloodWait as e:
            logger.warning(f"FloodWait during deletion: {e.value} seconds")
            await asyncio.sleep(e.value)
        except Exception as e:
            logger.error(f"Failed to delete message {msg.id}: {str(e)}")

    logger.info(f"Successfully deleted {deleted_count}/{len(messages)} messages")
    try:
        await process.reply(AUTO_DELETE_MSG)
    except Exception as e:
        logger.error(f"Error sending deletion confirmation: {str(e)}")
    
@Client.on_message(filters.command("logs") & filters.user(ADMINS))
async def log_file(bot, message):
    """Send log file"""
    logger.info(f"Admin {message.from_user.id} requested log file")
    try:
        await message.reply_document('TelegramBot.txt')
        logger.info("Log file sent successfully")
    except Exception as e:
        logger.error(f"Error sending log file: {str(e)}")
        await message.reply(str(e))

@Client.on_message(filters.command("help") & filters.user(ADMINS))
async def help(bot, message):
    logger.info(f"Admin {message.from_user.id} requested help")
    try:
        await message.reply_text(
            text=script.HELP_TXT,
            parse_mode=enums.ParseMode.HTML
        )
        logger.info("Help text sent successfully")
    except Exception as e:
        logger.error(f"Error sending help text: {str(e)}")
    
@Client.on_message(filters.command('restart') & filters.user(ADMINS))
async def restart_bot(client, message):
    logger.info(f"Admin {message.from_user.id} requested bot restart")
    try:
        msg = await message.reply_text(
            text="<b>Bot Restarting ...</b>"
        )        
        await msg.edit("<b>Restart Successfully Completed ✅</b>")
        logger.info("Executing restart commands")
        system("git pull -f && pip3 install --no-cache-dir -r requirements.txt")
        execle(sys.executable, sys.executable, "bot.py", environ)
    except Exception as e:
        logger.error(f"Error during restart: {str(e)}")
        await message.reply_text(f"Restart failed: {str(e)}")
