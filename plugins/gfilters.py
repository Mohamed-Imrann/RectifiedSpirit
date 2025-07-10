import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from database.gfilters_mdb import add_gfilter, find_gfilter, get_gfilters, delete_gfilter, del_allg, count_gfilters
from info import ADMINS
import re

@Client.on_message(filters.command("gadd") & filters.user(ADMINS))
async def gadd_filter_command(client, message: Message):
    if len(message.command) &lt; 3:
        return await message.reply_text("Usage: /gadd [filter_text] - [reply_text] (optional: |button_text:button_url|alert_message)")
    
    full_text = message.text.split(" ", 1)[1]
    
    if " - " not in full_text:
        return await message.reply_text("Invalid format. Use 'filter_text - reply_text'.")
    
    parts = full_text.split(" - ", 1)
    filter_text = parts[0].strip()
    reply_content = parts[1].strip()
    
    reply_text = reply_content
    button = None
    alert = None
    file_id = None

    # Check for button and alert
    if "|" in reply_content:
        reply_text_parts = reply_content.split("|", 1)
        reply_text = reply_text_parts[0].strip()
        
        button_alert_part = reply_text_parts[1].strip()
        if ":" in button_alert_part:
            button_parts = button_alert_part.split(":", 1)
            button_text = button_parts[0].strip()
            button_url = button_parts[1].strip()
            button = f"{button_text}:{button_url}"
        
        if len(button_alert_part.split("|")) > 1: # Check if there's an alert after button
            alert = button_alert_part.split("|", 1)[1].strip()

    # Check for replied media
    if message.reply_to_message and message.reply_to_message.media:
        file_id = message.reply_to_message.media.file_id

    await add_gfilter(message.chat.id, filter_text, reply_text, button, file_id, alert)
    await message.reply_text(f"Global filter `{filter_text}` added successfully!")

@Client.on_message(filters.text & filters.group & filters.incoming & ~filters.edited)
async def check_gfilter(client, message: Message):
    if message.text.startswith("/"):
        return # Ignore commands
    
    reply_text, button, alert, file_id = await find_gfilter(message.chat.id, message.text.strip())
    
    if reply_text:
        reply_markup = None
        if button:
            button_text, button_url = button.split(":", 1)
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(button_text, url=button_url)]])
        
        if file_id:
            try:
                await client.send_cached_media(
                    chat_id=message.chat.id,
                    file_id=file_id,
                    caption=reply_text,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Error sending cached media for gfilter: {e}")
                await message.reply_text(reply_text, reply_markup=reply_markup)
        else:
            await message.reply_text(reply_text, reply_markup=reply_markup)
        
        if alert:
            try:
                await message.reply_text(alert)
            except Exception as e:
                logger.error(f"Error sending alert for gfilter: {e}")
