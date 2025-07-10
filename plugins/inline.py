import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

from pyrogram import Client, filters
from pyrogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup, InlineKeyboardButton
from database.ia_filterdb import get_search_results
from info import AUTH_USERS, PUBLIC_FILE_STORE, PROTECT_CONTENT, CUSTOM_FILE_CAPTION
from utils import get_readable_file_size, is_subscribed
import re

@Client.on_inline_query()
async def inline_search(client, inline_query: InlineQuery):
    query = inline_query.query.strip().lower()
    results = []

    if "hello" in query:
        results.append(
            InlineQueryResultArticle(
                title="Say Hello",
                input_message_content=InputTextMessageContent("Hello there!")
            )
        )
    if "bot" in query:
        results.append(
            InlineQueryResultArticle(
                title="About Bot",
                input_message_content=InputTextMessageContent("I am a SeriesBot!")
            )
        )

    if not query or results:
        await inline_query.answer(results, cache_time=5)
        return
    
    # Check if user is authorized
    if AUTH_USERS and inline_query.from_user.id not in AUTH_USERS:
        results.append(
            InlineQueryResultArticle(
                title="Not Authorized",
                input_message_content=InputTextMessageContent("You are not authorized to use this bot's inline search."),
                description="Please contact the bot owner for access."
            )
        )
        await inline_query.answer(results, cache_time=0)
        return

    # Check force subscribe if enabled
    if client.force_subscribe_channels and not await is_subscribed(client, inline_query):
        results.append(
            InlineQueryResultArticle(
                title="Please Subscribe",
                input_message_content=InputTextMessageContent("You must subscribe to our channels to use this bot."),
                description="Click here to subscribe.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Join Channel", url=client.force_subscribe_channels[0])] # Assuming first channel for simplicity
                ])
            )
        )
        await inline_query.answer(results, cache_time=0)
        return

    files, offset, total_results = await get_search_results(query, file_type="document", max_results=50)
    
    if files:
        for file in files:
            caption = CUSTOM_FILE_CAPTION.format(previouscaption=file.caption) if CUSTOM_FILE_CAPTION else file.caption
            results.append(
                InlineQueryResultArticle(
                    title=file.file_name,
                    input_message_content=InputTextMessageContent(
                        f"**File Name:** `{file.file_name}`\n**Size:** `{get_readable_file_size(file.file_size)}`\n\n{caption}",
                        parse_mode="Markdown"
                    ),
                    description=f"Size: {get_readable_file_size(file.file_size)}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Get File", callback_data=f"inline_get_file#{file.file_id}")]
                    ])
                )
            )
    else:
        results.append(
            InlineQueryResultArticle(
                title="No results found",
                input_message_content=InputTextMessageContent("No files found matching your query."),
                description="Try a different search term."
            )
        )
        
    await inline_query.answer(
        results=results,
        cache_time=0, # No caching for dynamic results
        is_personal=True # Results are personal to the user
    )

@Client.on_callback_query(filters.regex("^inline_get_file#"))
async def inline_get_file_callback(client, callback_query: CallbackQuery):
    file_id = callback_query.data.split("#")[1]
    file_details = await get_file_details(file_id)
    
    if not file_details:
        await callback_query.answer("File not found.", show_alert=True)
        return
    
    file_details = file_details[0]
    
    try:
        if PUBLIC_FILE_STORE:
            await client.send_cached_media(
                chat_id=callback_query.from_user.id,
                file_id=file_details.file_id,
                caption=CUSTOM_FILE_CAPTION.format(previouscaption=file_details.caption) if CUSTOM_FILE_CAPTION else file_details.caption,
                protect_content=PROTECT_CONTENT
            )
        else:
            await client.send_cached_media(
                chat_id=callback_query.from_user.id,
                file_id=file_details.file_id,
                caption=CUSTOM_FILE_CAPTION.format(previouscaption=file_details.caption) if CUSTOM_FILE_CAPTION else file_details.caption,
                protect_content=PROTECT_CONTENT
            )
        await callback_query.answer("File sent to your private chat!", show_alert=True)
    except Exception as e:
        logger.error(f"Error sending file from inline callback: {e}")
        await callback_query.answer("Failed to send file to your private chat. Please start the bot in PM first.", show_alert=True)
