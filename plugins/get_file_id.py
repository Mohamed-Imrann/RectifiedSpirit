import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

from pyrogram import Client, filters
from pyrogram.types import Message

@Client.on_message(filters.private & filters.command("get_file_id"))
async def get_file_id_command(client, message: Message):
    if not message.reply_to_message or not message.reply_to_message.media:
        return await message.reply_text("Reply to a media file to get its file ID.")
    
    file_id = message.reply_to_message.media.file_id
    await message.reply_text(f"**File ID:**\n`{file_id}`")
