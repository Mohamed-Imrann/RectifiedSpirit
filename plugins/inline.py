import logging
import asyncio
import time
from typing import Dict, Tuple

from pyrogram import Client, filters, types
from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

# DB / helper imports (these are blocking in your original code)
from database.crazy_db import get_series, get_series_name, get_poster_manuel
from plugins.crazy import find_most_similar_title
from info import CACHE_TIME, AUTH_USERS
from imdb import Cinemagoer

logger = logging.getLogger(__name__)
cache_time = 0 if AUTH_USERS else CACHE_TIME

MAX_RESULTS = 30               # reduce number of inline results for speed
PLACEHOLDER_IMAGE_URL = "https://telegra.ph/file/15fe322237ac580f5ade8.jpg"
IMDB_CONCURRENCY = 3           # limit concurrent IMDb searches
POSTER_CACHE_TTL = 24 * 3600   # seconds (1 day)

imdb = Cinemagoer()

# Simple in-memory poster cache: key -> (url, timestamp)
_poster_cache: Dict[str, Tuple[str, float]] = {}
_imdb_semaphore = asyncio.Semaphore(IMDB_CONCURRENCY)


async def _get_series_async():
    """Run blocking DB call in thread to avoid blocking loop."""
    return await asyncio.to_thread(get_series)


async def _get_series_name_async(series_key):
    return await asyncio.to_thread(get_series_name, series_key)


async def _get_poster_manuel_async(series_key):
    return await asyncio.to_thread(get_poster_manuel, series_key)


async def _find_most_similar_title_async(title, search_results):
    # find_most_similar_title is likely blocking/sync in plugins.crazy
    return await asyncio.to_thread(find_most_similar_title, title, search_results)


async def _imdb_search_async(title, results=3):
    # limit concurrent access to Cinemagoer which can be slow/blocking
    async with _imdb_semaphore:
        return await asyncio.to_thread(imdb.search_movie, title, results=results)


async def get_movie_poster(series_key: str) -> str:
    """
    Async poster fetch with local cache and limited external calls.
    Tries manual DB poster first, then IMDb (cached).
    """
    # check manual poster in DB (fast when run in thread)
    poster_url = await _get_poster_manuel_async(series_key)
    if poster_url:
        return poster_url

    # check cache
    cached = _poster_cache.get(series_key)
    if cached:
        url, ts = cached
        if time.time() - ts < POSTER_CACHE_TTL:
            return url
        else:
            # expired
            del _poster_cache[series_key]

    # fallback: try to look up title and search imdb (limited concurrency)
    series = await _get_series_name_async(series_key)
    if not series:
        return PLACEHOLDER_IMAGE_URL

    series_title = series.get("title", "")
    if not series_title:
        return PLACEHOLDER_IMAGE_URL

    try:
        # imdb search (runs in thread and limited by semaphore)
        search_results = await _imdb_search_async(series_title.lower(), results=3)
        if search_results:
            # find_most_similar_title may be CPU-bound or sync; run in thread
            movie = await _find_most_similar_title_async(series_title, search_results)
            poster_url = movie.get("full-size cover url") if movie else None
            if poster_url:
                _poster_cache[series_key] = (poster_url, time.time())
                return poster_url
    except Exception as e:
        logger.debug("IMDb poster fetch failed for %s: %s", series_title, e)

    # final fallback
    return PLACEHOLDER_IMAGE_URL


@Client.on_inline_query()
async def inline_query_handler(client, inline_query):
    """
    Handles inline queries quickly:
      - Runs DB fetch in a thread
      - Limits number of results (MAX_RESULTS)
      - Only fetches external posters for the top N results (to keep replies fast)
      - Uses placeholder for remaining results
    """
    query_text = inline_query.query.lower().strip()
    results = []

    if not query_text:
        await inline_query.answer(results, cache_time=cache_time, is_personal=True)
        return

    # fetch series list without blocking the loop
    try:
        series_infos = await _get_series_async()
    except Exception as e:
        logger.exception("Failed to load series infos: %s", e)
        await inline_query.answer(
            results, cache_time=cache_time, is_personal=True
        )
        return

    # fast local filter (in-memory)
    matching_series = [s for s in series_infos if query_text in s["title"].lower()]

    # if no exact match, return a limited set (helps user discover)
    if not matching_series:
        matching_series = series_infos

    # sort and limit
    matching_series = sorted(matching_series, key=lambda x: x["title"].lower())
    matching_series = matching_series[:MAX_RESULTS]

    # Only fetch posters for the top K results to avoid multiple external calls
    POSTER_FETCH_LIMIT = 6
    tasks = []
    for idx, series in enumerate(matching_series):
        series_key = series["key"]
        if idx < POSTER_FETCH_LIMIT:
            # schedule poster fetch
            tasks.append(get_movie_poster(series_key))
        else:
            tasks.append(asyncio.sleep(0, result=PLACEHOLDER_IMAGE_URL))

    # run poster fetches concurrently but limited by the semaphore inside get_movie_poster
    poster_urls = await asyncio.gather(*tasks, return_exceptions=True)

    for idx, series in enumerate(matching_series):
        series_key = series["key"]
        title = series["title"]
        released_on = str(series.get("released_on", "Unknown"))
        genre = series.get("genre", "Unknown")
        rating = series.get("rating", "N/A")

        poster_url = poster_urls[idx]
        if isinstance(poster_url, Exception) or not poster_url:
            poster_url = PLACEHOLDER_IMAGE_URL

        description = f"Released: {released_on} | Genre: {genre} | Rating: {rating}/10"
        message_text = f"**{title}**\nReleased: {released_on}\nGenre: {genre}\nRating: {rating}/10"

        result = InlineQueryResultArticle(
            id=str(series_key),
            title=title,
            description=description,
            input_message_content=InputTextMessageContent(message_text),
            thumb_url=poster_url,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "View Details",
                            callback_data=f"spellcheck-{series_key}-{inline_query.from_user.id}",
                        )
                    ]
                ]
            ),
        )
        results.append(result)

    # answer inline query
    try:
        await inline_query.answer(results, cache_time=cache_time, is_personal=True)
    except Exception as e:
        # fail-safe: try answering with an empty result to avoid unhandled exceptions
        logger.exception("Failed to answer inline query: %s", e)
        await inline_query.answer([], cache_time=0, is_personal=True)
