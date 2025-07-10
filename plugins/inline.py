import logging
from pyrogram import Client, filters, types
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent
from database.crazy_db import get_series, get_series_by_key, get_poster_file_id
from info import CACHE_TIME, AUTH_USERS, NO_POSTER_FOUND_IMG

logger = logging.getLogger(__name__)
cache_time = 0 if AUTH_USERS else CACHE_TIME
MAX_RESULTS = 50  # Limit the number of results

@Client.on_inline_query()
async def inline_query_handler(client, inline_query):
    query_text = inline_query.query.lower().strip()
    results = []

    if not query_text:
        await inline_query.answer(results, cache_time=cache_time, is_personal=True)
        return

    series_infos = get_series()
    # Filter for published series only
    published_series = [s for s in series_infos if s.get('published', False)]

    matching_series = [s for s in published_series if query_text in s['title'].lower()]

    if not matching_series:
        # If no exact matches, try to find series where the query is a substring of the title
        matching_series = [s for s in published_series if query_text in s['title'].lower()]

    # Sort and limit results
    matching_series = sorted(matching_series, key=lambda x: x['title'].lower())
    matching_series = matching_series[:MAX_RESULTS]

    for series in matching_series:
        series_key = series['_id']
        title = series['title']
        
        poster_file_id = get_poster_file_id(series_key) or NO_POSTER_FOUND_IMG
        
        result = InlineQueryResultArticle(
            id=series_key,
            title=title,
            description=f"Released: {series.get('released_on', 'N/A')} | Genre: {series.get('genre', 'N/A')} | Rating: {series.get('rating', 'N/A')}/10",
            input_message_content=InputTextMessageContent(
                f"**{title}**\nReleased: {series.get('released_on', 'N/A')}\nGenre: {series.get('genre', 'N/A')}\nRating: {series.get('rating', 'N/A')}/10"
            ),
            thumb_url=poster_file_id,  # Use the stored file_id as thumb_url
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("View Details", callback_data=f"spellcheck-{series_key}")]
            ])
        )
        results.append(result)

    await inline_query.answer(results, cache_time=cache_time, is_personal=True)
