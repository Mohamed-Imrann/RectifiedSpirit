@Client.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply_text("Bot working ✅")
