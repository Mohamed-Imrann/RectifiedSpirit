from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram import Client, filters
from database.users_chats_db import db
from utils import temp


async def banned_users(_, client, message: Message):
    return (message.from_user is not None or not message.sender_chat) and (message.from_user.id in temp.BANNED_USERS)

async def disabled_chat(_, client, message: Message):
    return message.chat.id in temp.BANNED_CHATS

@Client.on_message(filters.private & filters.incoming & filters.create(banned_users))
async def ban_reply(bot, message):
    ban = await db.get_cloud_ban_status(message.from_user.id)
    await message.reply(f"‼️ <b>𝖲𝗈𝗋𝗋𝗒, 𝗒𝗈𝗎 𝖺𝗋𝖾 𝖻𝖺𝗇𝗇𝖾𝖽 𝖿𝗋𝗈𝗆 𝗎𝗌𝗂𝗇𝗀 𝗆𝖾.</b> ‼️\n\n<u>𝖡𝖺𝗇 𝖱𝖾𝖺𝗌𝗈𝗇:</u> {ban['ban_reason']}")

"""@Client.on_message(filters.group & filters.incoming & filters.create(disabled_chat))
async def grp_bd(bot, message):
    buttons = [[InlineKeyboardButton('👥 𝖠𝖽𝗆𝗂𝗇', url=BOT_ADMIN)]]
    chat = await db.get_cloud_chat(message.chat.id)
    k = await message.reply(text=f"<b>𝖠𝖼𝖼𝖾𝗌𝗌 𝗍𝗈 𝖳𝗁𝗂𝗌 𝖢𝗁𝖺𝗍 𝖨𝗌 𝖱𝖾𝗌𝗍𝗋𝗂𝖼𝗍𝖾𝖽!\n\n𝖯𝗅𝖾𝖺𝗌𝖾 𝖼𝗈𝗇𝗍𝖺𝖼𝗍 𝗍𝗁𝖾 𝖺𝖽𝗆𝗂𝗇 𝖿𝗈𝗋 𝖿𝗎𝗋𝗍𝗁𝖾𝗋 𝖽𝖾𝗍𝖺𝗂𝗅𝗌.</b>\n𝖱𝖾𝖺𝗌𝗈𝗇: <code>{chat['reason']}</code>.", reply_markup=InlineKeyboardMarkup(buttons))
    try: await k.pin()
    except: pass
    await bot.leave_chat(message.chat.id)"""
