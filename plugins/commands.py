import logging
import os
import random
import sys
import time
from datetime import datetime

import asyncio
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from Script import script
from database.crazy_db import delete_all_series_and_links, delete_series_and_links, get_series
from database.gfilters_mdb import del_allg, delete_gfilter, get_gfilters
from database.ia_filterdb import Media
from database.join_reqs import JoinReqs
from database.users_chats_db import db
from info import (
    ADMINS,
    API_ID,
    API_HASH,
    AUTH_USERS,
    BOT_TOKEN,
    DB_CHANNEL,
    LOG_CHANNEL,
    PICS,
    REQ_CHANNEL_ONE,
    REQ_CHANNEL_TWO,
)
from utils import get_readable_file_size, get_readable_time, temp

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@Client.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    if not await db.is_user_exist(message.from_user.id):
        await db.add_user(message.from_user.id, message.from_user.first_name)
        await client.send_message(LOG_CHANNEL, script.LOG_TEXT_P.format(message.from_user.id, message.from_user.mention))

    if len(message.command) > 1 and message.command[1] == "subscribe":
        if REQ_CHANNEL_ONE and REQ_CHANNEL_TWO:
            await message.reply_text(
                "Please join both channels to use the bot:",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("Channel 1", url=temp.LINK_ONE)],
                        [InlineKeyboardButton("Channel 2", url=temp.LINK_TWO)],
                    ]
                ),
            )
        elif REQ_CHANNEL_ONE:
            await message.reply_text(
                "Please join our channel to use the bot:",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("Join Channel", url=temp.LINK_ONE)],
                    ]
                ),
            )
        elif REQ_CHANNEL_TWO:
            await message.reply_text(
                "Please join our channel to use the bot:",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("Join Channel", url=temp.LINK_TWO)],
                    ]
                ),
            )
        else:
            await message.reply_text("No force subscribe channels configured.")
        return

    await message.reply_text(
        f"Hello {message.from_user.first_name}!\n"
        "I am a Telegram bot for managing series and movies. "
        "Use /help to see available commands."
    )


@Client.on_message(filters.command("help") & filters.private)
async def help_command(client: Client, message: Message):
    help_text = (
        "Here are the commands you can use:\n"
        "/start - Start the bot\n"
        "/help - Get this help message\n"
        "For admins:\n"
        "/admin - Access the admin panel\n"
        "/broadcast - Broadcast a message (reply to a message)\n"
        "/ban [user_id] - Ban a user\n"
        "/unban [user_id] - Unban a user\n"
        "/status - Get bot status\n"
    )
    await message.reply_text(help_text)


@Client.on_message(filters.command("status") & filters.user(ADMINS))
async def status_command(client: Client, message: Message):
    # This is a placeholder for a more detailed status.
    # In a real bot, you'd fetch database stats, memory usage, etc.
    await message.reply_text(
        "Bot is running normally.\n"
        f"API ID: `{API_ID}`\n"
        f"API Hash: `{API_HASH[:5]}...`\n"  # Mask hash for security
        f"Bot Token: `{BOT_TOKEN[:5]}...`\n"  # Mask token for security
        f"Admins: {', '.join(map(str, ADMINS))}"
    )


@Client.on_message(filters.command("stats") & filters.user(ADMINS))
async def stats_command(client: Client, message: Message):
    total_users = await db.total_users_count()
    total_chats = await db.total_chat_count()
    total_files = await Media.count_documents({})
    db_size = await db.get_db_size()
    db_size = get_readable_file_size(db_size)

    # Placeholder for other database stats if implemented
    db1_files = 0
    db1_size = "0 MB"
    db2_files = 0
    db2_size = "0 MB"
    db3_files = 0
    db3_size = "0 MB"
    db4_files = 0
    db4_size = "0 MB"
    db5_files = 0
    db5_size = "0 MB"

    uptime = get_readable_time(time.time() - temp.START_TIME)

    await message.reply_text(
        script.STATUS_TXT.format(
            total_files,
            total_users,
            total_chats,
            db_size,
            db1_files,
            db1_size,
            db2_files,
            db2_size,
            db3_files,
            db3_size,
            db4_files,
            db4_size,
            db5_files,
            db5_size,
            uptime,
        )
    )


@Client.on_message(filters.command("restart") & filters.user(ADMINS))
async def restart_command(client: Client, message: Message):
    await message.reply_text("Restarting bot...")
    os.execl(sys.executable, sys.executable, "bot.py")


@Client.on_message(filters.command("totalusers") & filters.user(ADMINS))
async def total_users_command(client: Client, message: Message):
    total_users = await db.total_users_count()
    await message.reply_text(f"Total users in bot: {total_users}")


@Client.on_message(filters.command("viewall") & filters.user(ADMINS))
async def view_all_series_command(client: Client, message: Message):
    all_series = get_series()
    if not all_series:
        return await message.reply_text("No series found in the database.")

    text = "**All Series:**\n\n"
    for series in all_series:
        text += f"- {series.get('title', 'N/A')} (`{series.get('key', 'N/A')}`)\n"

    await message.reply_text(text)


@Client.on_message(filters.command("deleteseries") & filters.user(ADMINS))
async def delete_series_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /deleteseries [series_key]")

    series_key = message.command[1].lower().replace(" ", "")
    series_data = get_series(series_key)

    if not series_data:
        return await message.reply_text(f"Series with key `{series_key}` not found.")

    await delete_series_and_links(series_key)
    await message.reply_text(f"Series `{series_data['title']}` and its associated links have been deleted.")


@Client.on_message(filters.command("deleteallseries") & filters.user(ADMINS))
async def delete_all_series_command(client: Client, message: Message):
    await message.reply_text(
        "Are you sure you want to delete ALL series and their links? This action is irreversible.",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Yes, Delete All", callback_data="confirm_delete_all_series")],
                [InlineKeyboardButton("No, Cancel", callback_data="cancel_delete_all_series")],
            ]
        ),
    )


@Client.on_callback_query(filters.regex("^confirm_delete_all_series$") & filters.user(ADMINS))
async def confirm_delete_all_series_callback(client: Client, callback_query: CallbackQuery):
    await delete_all_series_and_links()
    await callback_query.message.edit_text("All series and their associated links have been deleted.")
    await callback_query.answer("All series deleted!", show_alert=True)


@Client.on_callback_query(filters.regex("^cancel_delete_all_series$") & filters.user(ADMINS))
async def cancel_delete_all_series_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.message.edit_text("Deletion cancelled.")
    await callback_query.answer("Deletion cancelled.", show_alert=True)


@Client.on_message(filters.command("gfilters") & filters.user(ADMINS))
async def view_gfilters_command(client: Client, message: Message):
    gfilters = await get_gfilters(message.chat.id)
    if not gfilters:
        return await message.reply_text("No global filters found for this chat.")

    text = "**Global Filters:**\n\n"
    for gfilter in gfilters:
        text += f"- `{gfilter}`\n"

    await message.reply_text(text)


@Client.on_message(filters.command("gdel") & filters.user(ADMINS))
async def delete_gfilter_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /gdel [filter_text]")

    filter_text = " ".join(message.command[1:])
    await delete_gfilter(message, filter_text, message.chat.id)


@Client.on_message(filters.command("gdelall") & filters.user(ADMINS))
async def delete_all_gfilters_command(client: Client, message: Message):
    await message.reply_text(
        "Are you sure you want to delete ALL global filters for this chat? This action is irreversible.",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Yes, Delete All", callback_data=f"confirm_del_allg_{message.chat.id}")],
                [InlineKeyboardButton("No, Cancel", callback_data="cancel_del_allg")],
            ]
        ),
    )


@Client.on_callback_query(filters.regex("^confirm_del_allg_") & filters.user(ADMINS))
async def confirm_delete_all_gfilters_callback(client: Client, callback_query: CallbackQuery):
    chat_id = int(callback_query.data.split("_")[2])
    await del_allg(callback_query.message, chat_id)
    await callback_query.answer("All global filters deleted!", show_alert=True)


@Client.on_callback_query(filters.regex("^cancel_del_allg$") & filters.user(ADMINS))
async def cancel_delete_all_gfilters_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.message.edit_text("Deletion cancelled.")
    await callback_query.answer("Deletion cancelled.", show_alert=True)
