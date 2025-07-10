from pyrogram import Client, filters
from pyrogram.types import Message
from database.gfilters_mdb import gfilters_db

@Client.on_message(filters.text & filters.group)
async def global_filter_handler(client: Client, message: Message):
    chat_id = message.chat.id
    text = message.text.lower()
    
    keywords = await gfilters_db.get_gfilters(chat_id)
    
    for keyword in keywords:
        if keyword.lower() in text:
            await message.reply_text(f"This message contains a globally filtered keyword: `{keyword}`")
            # You might want to delete the message or take other actions
            break

@Client.on_message(filters.command("addgfilter") & filters.group)
async def add_global_filter(client: Client, message: Message):
    if len(message.command) &lt; 2:
        await message.reply_text("Usage: /addgfilter [keyword]")
        return
    
    chat_id = message.chat.id
    keyword = message.text.split(" ", 1)[1]
    await gfilters_db.add_gfilter(chat_id, keyword)
    await message.reply_text(f"Global filter `{keyword}` added for this chat.")

@Client.on_message(filters.command("listgfilters") & filters.group)
async def list_global_filters(client: Client, message: Message):
    chat_id = message.chat.id
    keywords = await gfilters_db.get_gfilters(chat_id)
    
    if keywords:
        text = "Global filters for this chat:\n" + "\n".join(f"- `{k}`" for k in keywords)
    else:
        text = "No global filters set for this chat."
    await message.reply_text(text)
