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
from info import CHANNELS, ADMINS, AUTH_CHANNEL, LOG_CHANNEL, BATCH_FILE_CAPTION, CUSTOM_FILE_CAPTION, PROTECT_CONTENT, DATABASE_URI, DATABASE_NAME, STIC, AUTO_DELETE_TIME, AUTO_DELETE_MSG, BATCH_FILE_CAPTION as CUSTOM_CAPTION, DB_CHANNEL, RAW_DB_CHANNEL
from utils import get_size, is_subscribed, temp, temp_requests
import re
import json
import base64
logger = logging.getLogger(__name__)

import pymongo

BATCH_FILES = {}
from utils import get_messages, delete_file

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
        logger.info(deep_link)

        status = await ForceSub(client, message, file_id=deep_link)
        if not status:
            if deep_link.startswith("B-"):
                temp_requests[message.from_user.id] = deep_link.split("-", 1)[1]
            return

        if deep_link.startswith("get_"):
            temp_msg = await message.reply("Please wait...")
            try:
                argument = deep_link.split("_")
                if len(argument) == 4:
                    channel_id = argument[1]
                    if int(channel_id) not in RAW_DB_CHANNEL:
                        await temp_msg.edit("The channel is not in the allowed database channels!")
                        return

                    start = int(argument[2])
                    end = int(argument[3])
                    ids = range(start, end + 1)
                else:
                    await temp_msg.edit("Invalid parameters in the deep link!")
                    return
            except ValueError:
                await temp_msg.edit("Invalid link format!")
                return

            try:
                messages = await get_messages(client, f"-100{channel_id}", ids)
            except Exception as e:
                await temp_msg.edit(f"Error while fetching messages: {str(e)}")
                return

            await temp_msg.delete()
            track_msgs = []

            for msg in messages:
                if bool(CUSTOM_CAPTION) and bool(msg.document):
                    caption = CUSTOM_CAPTION.format(
                        previouscaption="" if not msg.caption else msg.caption.html,
                        filename=msg.document.file_name
                    )
                else:
                    caption = "" if not msg.caption else msg.caption.html

                if True:
                    reply_markup = msg.reply_markup
                else:
                    reply_markup = None

                if AUTO_DELETE_TIME and AUTO_DELETE_TIME > 0:
                    try:
                        copied_msg_for_deletion = await msg.copy(
                            chat_id=message.from_user.id,
                            caption=caption,
                            parse_mode=enums.ParseMode.HTML
                        )
                        if copied_msg_for_deletion:
                            track_msgs.append(copied_msg_for_deletion)
                    except FloodWait as e:
                        await asyncio.sleep(e.value)
                        copied_msg_for_deletion = await msg.copy(
                            chat_id=message.from_user.id,
                            caption=caption,
                            parse_mode=enums.ParseMode.HTML
                        )
                        if copied_msg_for_deletion:
                            track_msgs.append(copied_msg_for_deletion)
                    except Exception as e:
                        print(f"Error copying message: {e}")
                        pass
                else:
                    try:
                        await msg.copy(
                            chat_id=message.from_user.id,
                            caption=caption,
                            parse_mode=enums.ParseMode.HTML
                        )
                        await asyncio.sleep(0.5)
                    except FloodWait as e:
                        await asyncio.sleep(e.value)
                        await msg.copy(
                            chat_id=message.from_user.id,
                            caption=caption,
                            parse_mode=enums.ParseMode.HTML
                        )
                    except:
                        pass

            if track_msgs:
                delete_data = await client.send_message(
                    chat_id=message.from_user.id,
                    text=AUTO_DELETE_MSG.format(time=AUTO_DELETE_TIME)
                )
                asyncio.create_task(delete_file(track_msgs, client, delete_data))
            else:
                print("No messages to track for deletion.")

            return

        elif deep_link.startswith("B-"):
            sts = await message.reply("𝖳𝗁𝖾 𝖱𝖾𝗊𝗎𝖾𝗌𝗍𝖾𝖽 𝖥𝗂𝗅𝖾𝗌.....\n𝖪𝗂𝗇𝖽𝗅𝗒 𝖶𝖺𝗂𝗍!!!!")
            file_id = deep_link.split("-", 1)[1]
            msgs = BATCH_FILES.get(file_id)

            if not msgs:
                file = await client.download_media(file_id)
                try:
                    with open(file) as file_data:
                        msgs = json.loads(file_data.read())
                except:
                    await sts.edit("FAILED")
                    return await client.send_message(LOG_CHANNEL, "UNABLE TO OPEN FILE.")
                os.remove(file)
                BATCH_FILES[file_id] = msgs

            new_messages = []
            for msg in msgs:
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
                        logger.exception(e)
                        f_caption = f_caption

                if f_caption is None:
                    f_caption = f"{title}"

                try:
                    bj = await client.send_cached_media(
                        chat_id=message.from_user.id,
                        file_id=msg.get("file_id"),
                        caption=f_caption,
                        protect_content=msg.get('protect', False))
                except FloodWait as e:
                    await asyncio.sleep(e.x)
                    logger.warning(f"Floodwait of {e.x} sec.")
                    bj = await client.send_cached_media(
                        chat_id=message.from_user.id,
                        file_id=msg.get("file_id"),
                        caption=f_caption,
                        protect_content=msg.get('protect', False))
                except Exception as e:
                    logger.warning(e, exc_info=True)
                    continue

                new_messages.append(bj)
                await asyncio.sleep(1)

            await sts.delete()
            st = await message.reply_sticker(
                sticker=(random.choice(STIC))
            )
            return

        elif len(message.command) == 2 and message.command[1] in ["subscribe", "error", "okay", "help"]:
            if message.command[1] == "subscribe":
                await ForceSub(client, message)
                return

            buttons = [[
                InlineKeyboardButton('Switch Inline', switch_inline_query_current_chat='')
            ]]
            reply_markup = InlineKeyboardMarkup(buttons)
            m = await message.reply_sticker("CAACAgUAAxkBAAJ0w2aZJMdpnEKbXtDVPJIvpL2XhIAhAAIrAAO8ljUq9-AkUFoHiMQeBA")
            j = await message.reply_text(
                text=script.START_TXT,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML
            )
            await asyncio.sleep(30)
            await m.delete()
            await j.delete()
            return

        else:
            kk, file_id = message.command[1].split("_", 1) if "_" in message.command[1] else (False, False)
            pre = ('checksubp' if kk == 'filep' else 'checksub') if kk else False

            if not file_id:
                file_id = message.command[1]

            temp_msg = await message.reply("Processing your request...")
            await temp_msg.edit("Invalid link format! The format should start with 'get_' or 'B-'")
            await asyncio.sleep(5)
            await temp_msg.delete()

    buttons = [[InlineKeyboardButton('Switch Inline', switch_inline_query_current_chat='')]]
    reply_markup = InlineKeyboardMarkup(buttons)
    await message.reply_sticker("CAACAgUAAxkBAAJ0w2aZJMdpnEKbXtDVPJIvpL2XhIAhAAIrAAO8ljUq9-AkUFoHiMQeBA")
    await message.reply_text(
        text=script.START_TXT,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
        parse_mode=enums.ParseMode.HTML
    )
    return
    
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
    
