import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

from pyrogram import Client, filters
from pyrogram.types import Message
from database.users_chats_db import db
from info import ADMINS

@Client.on_message(filters.command("ban_user") & filters.user(ADMINS))
async def ban_user(client, message: Message):
    if len(message.command) &lt; 2:
        return await message.reply_text("Usage: /ban_user [user_id] [reason]")
    
    user_id = int(message.command[1])
    reason = " ".join(message.command[2:]) if len(message.command) > 2 else "No reason provided."
    
    if not await db.is_user_exist(user_id):
        return await message.reply_text("User not found in database.")
    
    await db.ban_user(user_id, reason)
    await message.reply_text(f"User {user_id} has been banned for: {reason}")

@Client.on_message(filters.command("unban_user") & filters.user(ADMINS))
async def unban_user(client, message: Message):
    if len(message.command) &lt; 2:
        return await message.reply_text("Usage: /unban_user [user_id]")
    
    user_id = int(message.command[1])
    
    if not await db.is_user_exist(user_id):
        return await message.reply_text("User not found in database.")
    
    await db.remove_ban(user_id)
    await message.reply_text(f"User {user_id} has been unbanned.")

@Client.on_message(filters.command("banned_users") & filters.user(ADMINS))
async def banned_users(client, message: Message):
    banned_users_list, banned_chats_list = await db.get_banned()
    
    if not banned_users_list and not banned_chats_list:
        return await message.reply_text("No users or chats are currently banned.")
    
    text = "**Banned Users:**\n"
    if banned_users_list:
        for user_id in banned_users_list:
            user = await client.get_users(user_id)
            text += f"- {user.first_name} (`{user_id}`)\n"
    else:
        text += "None\n"
        
    text += "\n**Disabled Chats:**\n"
    if banned_chats_list:
        for chat_id in banned_chats_list:
            try:
                chat = await client.get_chat(chat_id)
                text += f"- {chat.title} (`{chat_id}`)\n"
            except Exception:
                text += f"- Unknown Chat (`{chat_id}`)\n"
    else:
        text += "None\n"
        
    await message.reply_text(text)
