import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from info import ADMINS, LOG_CHANNEL
from database.users_chats_db import db

@Client.on_message(filters.private & filters.command("route") & filters.user(ADMINS))
async def route_message(client, message: Message):
    if len(message.command) &lt; 3:
        return await message.reply_text("Usage: /route [user_id] [message_text]")
    
    target_user_id = int(message.command[1])
    message_text = " ".join(message.command[2:])
    
    try:
        await client.send_message(target_user_id, message_text)
        await message.reply_text(f"Message sent to user {target_user_id}.")
    except Exception as e:
        await message.reply_text(f"Failed to send message to user {target_user_id}: {e}")
