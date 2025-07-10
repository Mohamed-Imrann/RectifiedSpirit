from pyrogram import Client, filters
from pyrogram.types import Message

@Client.on_message(filters.media & filters.private)
async def get_file_id(client: Client, message: Message):
    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name
    elif message.video:
        file_id = message.video.file_id
        file_name = message.video.file_name
    elif message.audio:
        file_id = message.audio.file_id
        file_name = message.audio.file_name
    elif message.photo:
        file_id = message.photo.file_id
        file_name = "photo"
    else:
        return

    await message.reply_text(f"File Name: `{file_name}`\nFile ID: `{file_id}`")
