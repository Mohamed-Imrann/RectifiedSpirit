import logging
import asyncio
import time
import difflib
import random
from typing import List, Dict, Tuple, Optional

import pyrogram
from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    InputMediaPhoto,
)

from info import ADMINS
from database.crazy_db import (
    get_series,
    get_links,
    get_series_name,
    get_languages,
    get_seasons,
    get_poster_manuel,
)
from utils import temp
from imdb import Cinemagoer

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

SPELL = (
    'https://envs.sh/kJj.jpg'
).split()

imdb = Cinemagoer()

# CACHING / CONCURRENCY CONFIG
SERIES_CACHE_TTL = 300            # 5 minutes for series list
POSTER_CACHE_TTL = 24 * 3600      # 1 day for posters
IMDB_CONCURRENCY = 3              # concurrent IMDb searches
POSTER_FETCH_LIMIT = 4            # only fetch posters for top N results in callbacks

DEFAULT_POSTER = "https://envs.sh/kJK.jpg"

# in-memory caches
_series_cache: Dict[str, float] = {"ts": 0.0}
_series_list_cache: List[Dict] = []
_poster_cache: Dict[str, Tuple[Optional[str], float]] = {}

_imdb_semaphore = asyncio.Semaphore(IMDB_CONCURRENCY)


# -------------------------
# Helper async wrappers
# -------------------------
async def _get_series_async():
    """Fetch series list in a thread so it doesn't block."""
    global _series_list_cache, _series_cache
    now = time.time()
    if now - _series_cache.get("ts", 0) < SERIES_CACHE_TTL and _series_list_cache:
        return _series_list_cache
    try:
        series = await asyncio.to_thread(get_series)
        if series:
            _series_list_cache = series
            _series_cache["ts"] = now
        return series or []
    except Exception as e:
        logger.exception("Error loading series list: %s", e)
        return _series_list_cache or []


async def _get_series_name_async(arg):
    return await asyncio.to_thread(get_series_name, arg)


async def _get_links_async(arg):
    return await asyncio.to_thread(get_links, arg)


async def _get_seasons_async(arg):
    return await asyncio.to_thread(get_seasons, arg)


async def _get_poster_manuel_async(series_key):
    return await asyncio.to_thread(get_poster_manuel, series_key)


async def _imdb_search_async(title: str, results: int = 5):
    # Cinemagoer is blocking: run in thread and limit concurrency
    async with _imdb_semaphore:
        return await asyncio.to_thread(imdb.search_movie, title, results)


async def _find_most_similar_title_async(query_title: str, search_results):
    # Use difflib in thread (may be CPU-bound for larger lists)
    def _inner():
        titles = [m.get("title", "").lower() for m in search_results]
        matches = difflib.get_close_matches(query_title.lower(), titles, n=1, cutoff=0.6)
        if matches:
            for movie in search_results:
                if movie.get("title", "").lower() == matches[0]:
                    return movie
        return None
    return await asyncio.to_thread(_inner)


# -------------------------
# Poster fetch with cache
# -------------------------
async def get_movie_poster(series_key: str) -> Optional[str]:
    """Try manual poster -> cached poster -> imdb lookup (limited)."""
    # manual poster from DB
    try:
        poster_url = await _get_poster_manuel_async(series_key)
        if poster_url:
            return poster_url
    except Exception:
        logger.exception("Error fetching manual poster for %s", series_key)

    # check poster cache
    cached = _poster_cache.get(series_key)
    if cached:
        url, ts = cached
        if time.time() - ts < POSTER_CACHE_TTL:
            return url
        else:
            _poster_cache.pop(series_key, None)

    # fallback: try imdb (search + match)
    series = await _get_series_name_async(series_key)
    if not series:
        return None

    title = series.get("title", "")
    if not title:
        return None

    try:
        search_results = await _imdb_search_async(title.lower(), results=6)
        if search_results:
            movie = await _find_most_similar_title_async(title, search_results)
            poster_url = movie.get("full-size cover url") if movie else None
            if poster_url:
                _poster_cache[series_key] = (poster_url, time.time())
                return poster_url
    except Exception:
        logger.exception("IMDb poster lookup failed for %s", title)

    return None


# -------------------------
# Utility functions
# -------------------------
def chunk_buttons(buttons: List[InlineKeyboardButton], chunk_size: int = 3):
    return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]


async def alert_admins(client: Client, series_key: str):
    alert_message = f"⚠️ Failed to fetch poster for series: <code>{series_key}</code>"
    for admin_id in ADMINS:
        try:
            await client.send_message(chat_id=admin_id, text=alert_message, parse_mode=enums.ParseMode.HTML)
        except Exception:
            logger.exception("Failed to alert admin %s about %s", admin_id, series_key)


async def DeleteMessage(msg):
    await asyncio.sleep(600)
    try:
        await msg.delete()
    except Exception:
        pass


# -------------------------
# Message handler (non-blocking)
# -------------------------
@Client.on_message(filters.text & (filters.private | filters.group))
async def handle_message(client: Client, message):
    # Offload all blocking work into the series_filter async function which uses to_thread safely.
    try:
        await series_filter(client, message)
    except Exception:
        logger.exception("Error in series_filter for message %s", message.message_id)


async def series_filter(client: Client, message):
    text = message.text.strip()
    user_id = str(message.from_user.id)

    # load series list (cached)
    series_infos = await _get_series_async()
    if not series_infos:
        # nothing to do
        return

    series_keys = [s["key"] for s in series_infos]
    series_names = [s["title"] for s in series_infos]

    series_key = None
    series_name = None

    # direct match by key or title
    if text in series_keys:
        series_key = text
    elif text in series_names:
        series_name = text
    else:
        # fuzzy matches: nearest titles
        close_matches = difflib.get_close_matches(text, series_names, n=3, cutoff=0.6)
        if not close_matches:
            first_word = text.split()[0]
            close_matches = [name for name in series_names if name.lower().startswith(first_word.lower())][:4]

        if close_matches:
            # send quick choose buttons (no heavy operations)
            buttons = [
                InlineKeyboardButton(
                    match,
                    callback_data=f"spellcheck·{series_infos[series_names.index(match)]['key']}·{user_id}"
                )
                for match in close_matches
            ]
            buttons_chunked = chunk_buttons(buttons, chunk_size=2)
            buttons_chunked.append([InlineKeyboardButton("✨Latest Series✨", url="https://t.me/+7luzbTPly8NmMDU1")])
            reply_markup = InlineKeyboardMarkup(buttons_chunked)
            try:
                etho = await message.reply_photo(photo=random.choice(SPELL), caption="<b>Choose Your Series:</b>", reply_markup=reply_markup)
                asyncio.create_task(DeleteMessage(etho))
            except Exception:
                # fallback to text reply if photo fails
                try:
                    etho = await message.reply_text("<b>Choose Your Series:</b>", reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML)
                    asyncio.create_task(DeleteMessage(etho))
                except Exception:
                    pass
            return

    # At this point either series_key or series_name was found
    if series_name:
        series = await _get_series_name_async(series_name)
        if not series:
            return
        series_key = series.get("key")

    if not series_key:
        return

    # fetch series details (non-blocking)
    series = await _get_series_name_async(series_key)
    if not series:
        return

    languages = series.get("languages", [])
    reply_text = (
        f"○ <b>Title:</b> <code>{series['title']}</code>\n"
        f"○ <b>Released On:</b> <code>{series.get('released_on','Unknown')}</code>\n"
        f"○ <b>Genre:</b> <code>{series.get('genre','Unknown')}</code>\n"
        f"○ <b>Rating:</b> <code>{series.get('rating','N/A')}</code>\n\n"
        "Available Languages:\n"
    )

    # fetch poster asynchronously but do not block entire flow longer than a short time
    poster_task = asyncio.create_task(get_movie_poster(series_key))

    buttons = [InlineKeyboardButton(lang, callback_data=f"{series_key}·{lang.lower().replace(' ', '')}·{user_id}") for lang in languages]
    buttons_chunked = chunk_buttons(buttons, chunk_size=2)
    buttons_chunked.append([InlineKeyboardButton("✨Latest Series✨", url="https://t.me/+7luzbTPly8NmMDU1")])
    reply_markup = InlineKeyboardMarkup(buttons_chunked)

    # wait a short moment for poster (fast path). If poster takes too long, use DEFAULT_POSTER.
    try:
        poster_url = await asyncio.wait_for(poster_task, timeout=2.0)
    except asyncio.TimeoutError:
        poster_url = None
    except Exception:
        poster_url = None

    try:
        if poster_url:
            etho = await message.reply_photo(photo=poster_url, caption=reply_text, reply_markup=reply_markup)
        else:
            etho = await message.reply_photo(photo=DEFAULT_POSTER, caption=reply_text, reply_markup=reply_markup)
        asyncio.create_task(DeleteMessage(etho))
    except Exception:
        # try text fallback
        try:
            etho = await message.reply_text(reply_text, reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML)
            asyncio.create_task(DeleteMessage(etho))
        except Exception:
            pass


# -------------------------
# Callback handler
# -------------------------
@Client.on_callback_query()
async def cb_handler(client: Client, query: CallbackQuery):
    data = query.data or ""
    user_id = str(query.from_user.id)
    parts = data.split("·")

    # basic commands
    if data == "close_data":
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    if data == "pages":
        await query.answer()
        return

    if data.startswith("gt:"):
        start_parameter = data.split(":", 1)[1]
        try:
            await query.answer(url=f"https://t.me/{temp.U_NAME}?start={start_parameter}")
        except Exception:
            await query.answer("Invalid URL provided.", show_alert=True)
        return

    if data.startswith("get:"):
        start_parameter = data.split(":", 1)[1]
        try:
            await query.answer(url=f"https://t.me/{temp.U_NAME}?start={start_parameter}")
        except Exception:
            await query.answer("Invalid URL provided.", show_alert=True)
        return

    # spellcheck flow (user pressed a matched title)
    if data.startswith("spellcheck·"):
        try:
            series_key = parts[1]
            query_user_id = parts[2]
        except Exception:
            await query.answer()
            return

        if query_user_id != user_id:
            await query.answer("Request Yourself", show_alert=True)
            return

        series = await _get_series_name_async(series_key)
        if not series:
            await query.message.edit_text(text="Series not found.", disable_web_page_preview=True, parse_mode=enums.ParseMode.HTML)
            return

        # fetch poster (but limit wait time)
        poster_task = asyncio.create_task(get_movie_poster(series_key))
        try:
            poster_url = await asyncio.wait_for(poster_task, timeout=2.0)
        except asyncio.TimeoutError:
            poster_url = None
        except Exception:
            poster_url = None

        languages = series.get("languages", [])
        reply_text = (
            f"○ <b>Title:</b> <code>{series['title']}</code>\n"
            f"○ <b>Released On:</b> <code>{series.get('released_on','Unknown')}</code>\n"
            f"○ <b>Genre:</b> <code>{series.get('genre','Unknown')}</code>\n"
            f"○ <b>Rating:</b> <code>{series.get('rating','N/A')}</code>\n\n"
            "Available Languages:\n"
        )
        buttons = [InlineKeyboardButton(lang, callback_data=f"{series_key}·{lang.lower().replace(' ', '')}·{user_id}") for lang in languages]
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        buttons_chunked.append([InlineKeyboardButton("Request Series", url="https://t.me/+WeBqY_ljwpc3ZjE1")])
        reply_markup = InlineKeyboardMarkup(buttons_chunked)

        # Use edit_media + edit_text carefully and separately to avoid MediaEmpty issues
        try:
            if poster_url:
                await query.message.edit_media(media=InputMediaPhoto(poster_url))
            else:
                await query.message.edit_media(media=InputMediaPhoto(DEFAULT_POSTER))
        except Exception:
            # notify admins if poster repeatedly fails
            try:
                await alert_admins(client, series_key)
            except Exception:
                pass

        try:
            await query.message.edit_text(text=reply_text, reply_markup=reply_markup)
        except Exception:
            try:
                await query.message.edit_text(text=reply_text)
            except Exception:
                pass
        return

    # other callback flows: language selection, season selection, quality selection
    # patterns:
    #  - "series_key·language·user_id"
    #  - "series_key·language·season·user_id"
    if len(parts) == 3:
        series_key, language, query_user_id = parts
        if query_user_id != user_id:
            await query.answer("Request Yourself", show_alert=True)
            return

        series = await _get_series_name_async(series_key)
        if not series:
            await query.answer("Series not found.", show_alert=True)
            return

        seasons = await _get_seasons_async(series['key'])
        if not seasons:
            await query.answer("No seasons found.", show_alert=True)
            return

        reply_text = (
            f"○ <b>Title:</b> <code>{series['title'].title()}</code>\n"
            f"○ <b>Released On:</b> <code>{series.get('released_on','Unknown')}</code>\n"
            f"○ <b>Genre:</b> <code>{series.get('genre','Unknown')}</code>\n"
            f"○ <b>Rating:</b> <code>{series.get('rating','N/A')}</code>\n"
            f"<blockquote>▪️<b>Language:</b> <code>{language.title()}</code></blockquote>\n"
            "Available Seasons:\n"
        )

        buttons = [InlineKeyboardButton(season, callback_data=f"{series_key}·{language}·{season.lower().replace(' ', '')}·{user_id}") for season in seasons]
        buttons_chunked = chunk_buttons(buttons)
        buttons_chunked.append([InlineKeyboardButton("Back", callback_data=f"spellcheck·{series_key}·{user_id}")])
        buttons_chunked.append([InlineKeyboardButton("Request Series", url="https://t.me/+WeBqY_ljwpc3ZjE1")])
        reply_markup = InlineKeyboardMarkup(buttons_chunked)

        try:
            await query.message.edit_text(text=reply_text, reply_markup=reply_markup)
        except Exception:
            try:
                await query.answer("Could not update message.", show_alert=True)
            except Exception:
                pass
        return

    if len(parts) == 4:
        series_key, language, season, query_user_id = parts
        if query_user_id != user_id:
            await query.answer("Request Yourself", show_alert=True)
            return

        series = await _get_series_name_async(series_key)
        if not series:
            await query.answer("Series not found.", show_alert=True)
            return

        links = await _get_links_async(f"{series_key.lower().replace(' ', '')}-{language}-{season}")
        if links:
            buttons = [
                InlineKeyboardButton(quality, callback_data=f"gt:{link}")
                for quality, link in links.items()
            ]
            buttons_chunked = chunk_buttons(buttons, chunk_size=2)
            buttons_chunked.append([InlineKeyboardButton("Back", callback_data=f"{series_key}·{language}·{user_id}")])
            buttons_chunked.append([InlineKeyboardButton("Request Series", url="https://t.me/+WeBqY_ljwpc3ZjE1")])
            reply_markup = InlineKeyboardMarkup(buttons_chunked)

            try:
                await query.message.edit_text(
                    text=(
                        f"○ <b>Title:</b> <code>{series['title'].title()}</code>\n"
                        f"○ <b>Released On:</b> <code>{series.get('released_on','Unknown')}</code>\n"
                        f"○ <b>Genre:</b> <code>{series.get('genre','Unknown')}</code>\n"
                        f"○ <b>Rating:</b> <code>{series.get('rating','N/A')}</code>\n"
                        f"<blockquote><b>▪️Language:</b> <code>{language.title()}</code></blockquote>\n"
                        f"<blockquote><b>▪️Season:</b> <code>{season.replace('-', ' ').title()}</code></blockquote>\n"
                        "Select the quality you need...!"
                    ),
                    reply_markup=reply_markup,
                    disable_web_page_preview=True,
                    parse_mode=enums.ParseMode.HTML
                )
            except Exception:
                try:
                    await query.answer("Could not display links.", show_alert=True)
                except Exception:
                    pass
        else:
            try:
                await query.message.edit_text(
                    text="No links found for the selected season and language.",
                    disable_web_page_preview=True,
                    parse_mode=enums.ParseMode.HTML
                )
            except Exception:
                pass
        return

    # unrecognized callback format — ignore safely
    try:
        await query.answer()
    except Exception:
        pass
