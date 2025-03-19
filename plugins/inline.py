import logging
from pyrogram import Client, filters, types
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent
from database.crazy_db import get_series, get_series_name, get_poster_manuel
from plugins.crazy import find_most_similar_title
from info import CACHE_TIME, AUTH_USERS
from imdb import Cinemagoer

logger = logging.getLogger(__name__)
cache_time = 0 if AUTH_USERS else CACHE_TIME
MAX_RESULTS = 50  # Limit the number of results
PLACEHOLDER_IMAGE_URL = "https://telegra.ph/file/15fe322237ac580f5ade8.jpg"

imdb = Cinemagoer()

def get_movie_poster(series_key):
    poster_url = get_poster_manuel(series_key)
    
    if not poster_url:
        series = get_series_name(series_key)
        if series:
            series_title = series.get('title', '')
            search_results = imdb.search_movie(series_title.lower(), results=3)
            if search_results:
                movie = find_most_similar_title(series_title, search_results)
                poster_url = movie.get('full-size cover url') if movie else None
    
    return poster_url or PLACEHOLDER_IMAGE_URL

@Client.on_inline_query()
async def inline_query_handler(client, inline_query):
    query_text = inline_query.query.lower().strip()
    results = []

    if not query_text:
        await inline_query.answer(results, cache_time=cache_time, is_personal=True)
        return

    series_infos = get_series()
    matching_series = [s for s in series_infos if query_text in s['title'].lower()]

    if not matching_series:
        matching_series = series_infos  # If no exact matches, return all

    # Sort and limit results
    matching_series = sorted(matching_series, key=lambda x: x['title'].lower())
    matching_series = matching_series[:MAX_RESULTS]

    for series in matching_series:
        series_key = series['key']
        title = series['title']
        result = InlineQueryResultArticle(
            id=series_key,
            title=title,
            description=f"Released: {series['released_on']} | Genre: {series['genre']} | Rating: {series['rating']}/10",
            input_message_content=InputTextMessageContent(
                f"**{title}**\nReleased: {series['released_on']}\nGenre: {series['genre']}\nRating: {series['rating']}/10"
            ),
            thumb_url=poster_url,  # Add the poster image as a thumbnail
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("View Details", callback_data=f"spellcheck-{series_key}-{inline_query.from_user.id}")]
            ])
        )
        results.append(result)

    await inline_query.answer(results, cache_time=cache_time, is_personal=True)
                                