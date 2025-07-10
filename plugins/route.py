from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery

@Client.on_message(filters.private & filters.text)
async def route_private_messages(client: Client, message: Message):
    # This function can act as a central router for private messages
    # Based on message content, it can direct to other handlers
    if message.text.startswith("/"):
        # Let command handlers take over
        pass
    elif "search" in message.text.lower():
        # Example: if user types "search", direct to a search function
        await message.reply_text("Please provide your search query after /search command.")
    else:
        # Default response for unhandled text messages
        await message.reply_text("I received your message. If you need help, use /help.")

@Client.on_callback_query()
async def route_callbacks(client: Client, query: CallbackQuery):
    # This function can act as a central router for callback queries
    # Based on callback_data, it can direct to other handlers
    data = query.data
    if data.startswith("manage_series_data"):
        # This callback is handled by admin_ui.py, so we don't need to do anything here
        pass
    else:
        # Default response for unhandled callbacks
        await query.answer("Unhandled callback!", show_alert=False)
