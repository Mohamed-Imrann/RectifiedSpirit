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
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from database.ia_filterdb import Media, get_file_details, unpack_new_file_id
from database.users_chats_db import db
from database.request_forcesub_db import delete_all_one, delete_all_two
from .request_forcesub import create_request_forcesub_buttons
from database.join_reqs import JoinReqs
db1 = JoinReqs
from pymongo import MongoClient
from info import ADMINS, AUTH_CHANNEL, LOG_CHANNEL, CUSTOM_FILE_CAPTION, PROTECT_CONTENT, DATABASE_URI, DATABASE_NAME, AUTO_DELETE_TIME, AUTO_DELETE_MSG, BATCH_FILE_CAPTION as CUSTOM_CAPTION, DB_CHANNEL, RAW_DB_CHANNEL, STICKER, STICKER_ID, PIC, PICS, START_TXT, BOT_USERNAME, SUPPORT_GROUP_LINK, UPDATES_CHANNEL_LINK, BOT_OWNER_LINK, WELCOME_MESSAGE, ABOUT_MESSAGE, START_DEEPLINK_MESSAGE
from utils import get_size, is_subscribed, temp, temp_requests, extract_user, split_quotes, get_file_id, broadcast_messages, broadcast_messages_group, get_settings, save_group_settings

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

mongo_client = MongoClient(DATABASE_URI)
edb = mongo_client["file_database"]
ecollection = edb["episodes"]

BATCH_FILES = {}

@Client.on_message(filters.command('start'))
async def start_command(client: Client, message: Message):
    user_id = message.from_user.id
    
    # Check force subscribe channels (REQ_CHANNEL_ONE, REQ_CHANNEL_TWO)
    force_sub_buttons = await create_request_forcesub_buttons(user_id)
    if force_sub_buttons:
        await message.reply_text(
            text="<b>Please join channels below to use bot</b>",
            reply_markup=InlineKeyboardMarkup(force_sub_buttons),
            parse_mode=enums.ParseMode.HTML
        )
        return

    # Check AUTH_CHANNEL (if configured)
    if AUTH_CHANNEL and not await is_subscribed(client, userid=user_id):
        try:
            invite_link = await client.create_chat_invite_link(int(AUTH_CHANNEL))
            btn = [[InlineKeyboardButton("❆ Jᴏɪɴ Oᴜʀ Bᴀᴄᴋ-Uᴘ Cʜᴀɴɴᴇʟ ❆", url=invite_link.invite_link)]]
            await message.reply_text(
                text="♦️ <b><u>READ THIS INSTRUCTION</u></b> ♦️\n\n🗣 <i>Follow instructions to access movies</i>",
                reply_markup=InlineKeyboardMarkup(btn),
                parse_mode=enums.ParseMode.MARKDOWN
            )
            return
        except Exception as e:
            logger.error(f"Error checking AUTH_CHANNEL or creating invite link for /start: {e}")
            await message.reply_text("An error occurred with channel verification. Please try again later.")
            return

    # Handle deep links
    if len(message.command) > 1:
        deep_link_payload = message.command[1]
        if deep_link_payload.startswith("file_"):
            file_identifier = deep_link_payload.replace("file_", "")
            # This part needs to be handled by pmfilter.py's handle_file_request
            # For now, we'll just send a message and let the user click a button
            # or directly call the handler if it's designed for direct calls.
            # Given the current structure, it's better to direct them to a callback.
            
            # Construct a callback_data that pmfilter.py's cb_handler can process
            callback_data = f"file#{file_identifier}" # Assuming this format for direct file_id
            
            # Simulate a callback query to trigger the file sending logic in pmfilter.py
            # This is a workaround as message.reply_markup doesn't trigger callbacks directly.
            # A better approach might be to refactor handle_file_request to be callable directly.
            
            # For now, let's provide a button for them to click.
            await message.reply_text(
                START_DEEPLINK_MESSAGE,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Get File", callback_data=callback_data)]
                ])
            )
            return
        elif deep_link_payload.startswith("get_"):
            # This is a deep link for a series/quality link_key from crazy_db
            # Format: get_{raw_channel_id}.{start_msg_id}.{end_msg_id}
            # This will be handled by pmfilter.py's handle_file_request (is_deep_link=True)
            callback_data = f"b:{deep_link_payload}"
            await message.reply_text(
                START_DEEPLINK_MESSAGE,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Get Content", callback_data=callback_data)]
                ])
            )
            return

    # Default start message
    await message.reply_text(
        WELCOME_MESSAGE.format(mention=message.from_user.mention),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Updates Channel", url=UPDATES_CHANNEL_LINK),
             InlineKeyboardButton("Support Group", url=SUPPORT_GROUP_LINK)],
            [InlineKeyboardButton("About Bot", callback_data="about_bot")]
        ])
    )
    await db.add_user(user_id) # Add user to database

@Client.on_message(filters.command('about'))
async def about_command(client: Client, message: Message):
    await message.reply_text(
        ABOUT_MESSAGE,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Updates Channel", url=UPDATES_CHANNEL_LINK),
             InlineKeyboardButton("Support Group", url=SUPPORT_GROUP_LINK)],
            [InlineKeyboardButton("Bot Owner", url=BOT_OWNER_LINK)]
        ])
    )

@Client.on_callback_query(filters.regex("about_bot"))
async def about_callback(client: Client, query: CallbackQuery):
    await query.message.edit_text(
        ABOUT_MESSAGE,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Updates Channel", url=UPDATES_CHANNEL_LINK),
             InlineKeyboardButton("Support Group", url=SUPPORT_GROUP_LINK)],
            [InlineKeyboardButton("Bot Owner", url=BOT_OWNER_LINK)]
        ])
    )
    await query.answer()

@Client.on_message(filters.command('stats') & filters.user(ADMINS))
async def stats_command(client: Client, message: Message):
    total_users = await db.total_users_count()
    total_chats = await db.total_chat_count()
    text = f"<b>Total Users:</b> {total_users}\n<b>Total Chats:</b> {total_chats}"
    await message.reply_text(text)

@Client.on_message(filters.command('broadcast') & filters.user(ADMINS))
async def broadcast_command(client: Client, message: Message):
    if not message.reply_to_message:
        await message.reply_text("Reply to a message to broadcast.")
        return
    
    all_users = await db.get_all_users()
    broadcast_msg = message.reply_to_message
    
    sent_count = 0
    blocked_count = 0
    deleted_count = 0
    
    for user in all_users:
        status, _ = await broadcast_messages(user['id'], broadcast_msg)
        if status == "Success":
            sent_count += 1
        elif status == "Blocked":
            blocked_count += 1
        elif status == "Deleted":
            deleted_count += 1
        await asyncio.sleep(0.1) # Small delay to avoid flood limits
    
    await message.reply_text(
        f"Broadcast complete.\n"
        f"Sent to: {sent_count} users\n"
        f"Blocked by: {blocked_count} users\n"
        f"Deleted accounts: {deleted_count} users"
    )

@Client.on_message(filters.command('gcast') & filters.user(ADMINS))
async def gcast_command(client: Client, message: Message):
    if not message.reply_to_message:
        await message.reply_text("Reply to a message to group broadcast.")
        return
    
    all_chats = await db.get_all_chats()
    broadcast_msg = message.reply_to_message
    
    sent_count = 0
    failed_count = 0
    
    for chat in all_chats:
        status, _ = await broadcast_messages_group(chat['id'], broadcast_msg)
        if status == "Success":
            sent_count += 1
        else:
            failed_count += 1
        await asyncio.sleep(0.1) # Small delay
    
    await message.reply_text(
        f"Group broadcast complete.\n"
        f"Sent to: {sent_count} chats\n"
        f"Failed for: {failed_count} chats"
    )

@Client.on_message(filters.command('ban') & filters.user(ADMINS))
async def ban_user_command(client: Client, message: Message):
    user_id, user_first_name = extract_user(message)
    if not user_id:
        await message.reply_text("Could not extract user from message.")
        return
    
    if user_id == client.me.id:
        await message.reply_text("I can't ban myself.")
        return
    
    if user_id in ADMINS:
        await message.reply_text("I can't ban an admin.")
        return

    if await db.is_user_banned(user_id):
        await message.reply_text(f"{user_first_name} is already banned.")
        return
    
    await db.ban_user(user_id)
    temp.BANNED_USERS.append(user_id)
    await message.reply_text(f"{user_first_name} has been banned.")

@Client.on_message(filters.command('unban') & filters.user(ADMINS))
async def unban_user_command(client: Client, message: Message):
    user_id, user_first_name = extract_user(message)
    if not user_id:
        await message.reply_text("Could not extract user from message.")
        return
    
    if not await db.is_user_banned(user_id):
        await message.reply_text(f"{user_first_name} is not banned.")
        return
    
    await db.unban_user(user_id)
    if user_id in temp.BANNED_USERS:
        temp.BANNED_USERS.remove(user_id)
    await message.reply_text(f"{user_first_name} has been unbanned.")

@Client.on_message(filters.command('bannedusers') & filters.user(ADMINS))
async def banned_users_command(client: Client, message: Message):
    banned_users = await db.get_all_banned_users()
    if not banned_users:
        await message.reply_text("No users are currently banned.")
        return
    
    text = "<b>Banned Users:</b>\n"
    for user_id in banned_users:
        try:
            user = await client.get_users(user_id)
            text += f"• {user.mention} (<code>{user_id}</code>)\n"
        except Exception:
            text += f"• User ID: <code>{user_id}</code> (Account deleted or inaccessible)\n"
    
    await message.reply_text(text, parse_mode=enums.ParseMode.HTML)

@Client.on_message(filters.command('ban_chat') & filters.user(ADMINS))
async def ban_chat_command(client: Client, message: Message):
    chat_id = message.chat.id
    if len(message.command) > 1:
        try:
            chat_id = int(message.command[1])
        except ValueError:
            await message.reply_text("Invalid chat ID.")
            return
    
    if await db.is_chat_banned(chat_id):
        await message.reply_text("This chat is already banned.")
        return
    
    await db.ban_chat(chat_id)
    temp.BANNED_CHATS.append(chat_id)
    await message.reply_text(f"Chat {chat_id} has been banned.")

@Client.on_message(filters.command('unban_chat') & filters.user(ADMINS))
async def unban_chat_command(client: Client, message: Message):
    chat_id = message.chat.id
    if len(message.command) > 1:
        try:
            chat_id = int(message.command[1])
        except ValueError:
            await message.reply_text("Invalid chat ID.")
            return
    
    if not await db.is_chat_banned(chat_id):
        await message.reply_text("This chat is not banned.")
        return
    
    await db.unban_chat(chat_id)
    if chat_id in temp.BANNED_CHATS:
        temp.BANNED_CHATS.remove(chat_id)
    await message.reply_text(f"Chat {chat_id} has been unbanned.")

@Client.on_message(filters.command('banned_chats') & filters.user(ADMINS))
async def banned_chats_command(client: Client, message: Message):
    banned_chats = await db.get_all_banned_chats()
    if not banned_chats:
        await message.reply_text("No chats are currently banned.")
        return
    
    text = "<b>Banned Chats:</b>\n"
    for chat_id in banned_chats:
        try:
            chat = await client.get_chat(chat_id)
            text += f"• {chat.title} (<code>{chat_id}</code>)\n"
        except Exception:
            text += f"• Chat ID: <code>{chat_id}</code> (Inaccessible)\n"
    
    await message.reply_text(text, parse_mode=enums.ParseMode.HTML)

@Client.on_message(filters.command('settings') & filters.group)
async def settings_command(client: Client, message: Message):
    chat_id = message.chat.id
    settings = await get_settings(chat_id)
    
    buttons = [
        [InlineKeyboardButton(f"Bot PM: {'✅ On' if settings.get('botpm', True) else '❌ Off'}", callback_data="toggle_botpm")],
        [InlineKeyboardButton(f"IMDB: {'✅ On' if settings.get('imdb', True) else '❌ Off'}", callback_data="toggle_imdb")],
        [InlineKeyboardButton(f"Spell Check: {'✅ On' if settings.get('spell_check', True) else '❌ Off'}", callback_data="toggle_spell_check")],
        [InlineKeyboardButton("Close", callback_data="close_data")]
    ]
    
    await message.reply_text(
        "<b>Group Settings:</b>",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=enums.ParseMode.HTML
    )

@Client.on_callback_query(filters.regex("^toggle_"))
async def toggle_settings_callback(client: Client, query: CallbackQuery):
    chat_id = query.message.chat.id
    setting_key = query.data.replace("toggle_", "")
    
    settings = await get_settings(chat_id)
    current_value = settings.get(setting_key, True) # Default to True if not set
    new_value = not current_value
    
    await save_group_settings(chat_id, setting_key, new_value)
    
    updated_settings = await get_settings(chat_id) # Fetch updated settings
    
    buttons = [
        [InlineKeyboardButton(f"Bot PM: {'✅ On' if updated_settings.get('botpm', True) else '❌ Off'}", callback_data="toggle_botpm")],
        [InlineKeyboardButton(f"IMDB: {'✅ On' if updated_settings.get('imdb', True) else '❌ Off'}", callback_data="toggle_imdb")],
        [InlineKeyboardButton(f"Spell Check: {'✅ On' if updated_settings.get('spell_check', True) else '❌ Off'}", callback_data="toggle_spell_check")],
        [InlineKeyboardButton("Close", callback_data="close_data")]
    ]
    
    await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
    await query.answer(f"{setting_key.replace('_', ' ').title()} toggled to {'On' if new_value else 'Off'}")

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
