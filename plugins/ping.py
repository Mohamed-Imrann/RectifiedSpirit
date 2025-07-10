import time
from pyrogram import Client, filters
from pyrogram.types import Message

@Client.on_message(filters.command("ping"))
async def ping_command(client: Client, message: Message):
    start_time = time.time()
    sent_message = await message.reply_text("Pong!")
    end_time = time.time()
    latency = round((end_time - start_time) * 1000, 2)
    await sent_message.edit_text(f"Pong! `{latency}ms`")
