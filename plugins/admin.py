import logging
import time
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from info import ADMINS, OWNER_ID, LOG_CHANNEL
from database import db
import psutil
from utils.helpers import humanbytes, get_time

logger = logging.getLogger(__name__)
START_TIME = time.time()


@Client.on_message(filters.command("stats") & filters.user(ADMINS))
async def stats_command(client: Client, message: Message):
    """Get bot statistics"""
    msg = await message.reply("🔄 Fetching statistics...")
    
    try:
        stats = await db.get_stats()
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage('/').percent
        uptime = get_time(time.time() - START_TIME)
        
        text = f"""
📊 <b>Bot Statistics</b>

<b>📚 Database Stats:</b>
├ 📁 Total Files: <code>{stats.get('total_files', 0)}</code>
├ 👤 Total Users: <code>{stats.get('total_users', 0)}</code>
├ 👥 Total Groups: <code>{stats.get('total_groups', 0)}</code>
├ 📺 Total Series: <code>{stats.get('total_series', 0)}</code>
├ 📀 Total Seasons: <code>{stats.get('total_seasons', 0)}</code>
├ 🎬 Total Episodes: <code>{stats.get('total_episodes', 0)}</code>
└ 🔍 Total Filters: <code>{stats.get('total_filters', 0)}</code>

<b>💻 System Stats:</b>
├ 🖥 CPU: <code>{cpu}%</code>
├ 💾 RAM: <code>{ram}%</code>
├ 💿 Disk: <code>{disk}%</code>
└ ⏱ Uptime: <code>{uptime}</code>
"""
        await msg.edit(text)
    except Exception as e:
        logger.error(f"Error in stats: {e}")
        await msg.edit(f"❌ Error: {e}")


@Client.on_message(filters.command("broadcast") & filters.user(ADMINS) & filters.reply)
async def broadcast_command(client: Client, message: Message):
    """Broadcast message to all users"""
    msg = await message.reply("🔄 Starting broadcast...")
    
    try:
        users = await db.get_all_users()
        broadcast_msg = message.reply_to_message
        total = len(users)
        successful = 0
        failed = 0
        
        for user in users:
            try:
                await broadcast_msg.copy(chat_id=user.get('id'))
                successful += 1
            except:
                failed += 1
            
            if (successful + failed) % 50 == 0:
                await msg.edit(f"📢 Broadcasting...\n✅ {successful}\n❌ {failed}\n📊 {successful + failed}/{total}")
        
        await msg.edit(f"✅ <b>Broadcast Completed!</b>\n\n📊 Total: {total}\n✅ Successful: {successful}\n❌ Failed: {failed}")
    except Exception as e:
        logger.error(f"Error in broadcast: {e}")
        await msg.edit(f"❌ Error: {e}")


@Client.on_message(filters.command("ban") & filters.user(ADMINS))
async def ban_user_command(client: Client, message: Message):
    """Ban a user"""
    if len(message.command) < 2:
        await message.reply("⚠️ Usage: `/ban <user_id> [reason]`")
        return
    
    try:
        user_id = int(message.command[1])
        reason = " ".join(message.command[2:]) if len(message.command) > 2 else "No reason"
        await db.ban_user(user_id, reason)
        await message.reply(f"✅ User {user_id} banned\n📝 Reason: {reason}")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")


@Client.on_message(filters.command("unban") & filters.user(ADMINS))
async def unban_user_command(client: Client, message: Message):
    """Unban a user"""
    if len(message.command) < 2:
        await message.reply("⚠️ Usage: `/unban <user_id>`")
        return
    
    try:
        user_id = int(message.command[1])
        await db.unban_user(user_id)
        await message.reply(f"✅ User {user_id} unbanned")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")


@Client.on_message(filters.command("delete") & filters.user(ADMINS))
async def delete_file_command(client: Client, message: Message):
    """Delete file from database"""
    if len(message.command) < 2:
        await message.reply("⚠️ Usage: `/delete <file_id>`")
        return
    
    try:
        file_id = message.command[1]
        file_info = await db.get_file(file_id)
        if not file_info:
            await message.reply("❌ File not found")
            return
        
        await db.delete_file(file_id)
        await message.reply(f"✅ File deleted: {file_info.get('file_name', 'Unknown')}")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")


@Client.on_message(filters.command("deleteall") & filters.user([OWNER_ID]))
async def delete_all_command(client: Client, message: Message):
    """Delete all files - OWNER ONLY"""
    buttons = [[
        InlineKeyboardButton("✅ Confirm", callback_data="confirm_deleteall"),
        InlineKeyboardButton("❌ Cancel", callback_data="cancel_deleteall")
    ]]
    await message.reply("⚠️ Delete ALL files? This cannot be undone!", reply_markup=InlineKeyboardMarkup(buttons))


@Client.on_callback_query(filters.regex("^confirm_deleteall$"))
async def confirm_deleteall(client, query):
    if query.from_user.id != OWNER_ID:
        return await query.answer("❌ Owner only!", show_alert=True)
    
    await query.message.edit("🔄 Deleting...")
    try:
        await db.pgdb.delete_all_files()
        await query.message.edit("✅ All files deleted!")
    except Exception as e:
        await query.message.edit(f"❌ Error: {e}")


@Client.on_callback_query(filters.regex("^cancel_deleteall$"))
async def cancel_deleteall(client, query):
    await query.message.edit("✅ Cancelled")
