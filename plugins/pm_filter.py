# plugins/series_filter.py

import logging
import asyncio
import random
from typing import List, Dict, Tuple, Optional

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    InputMediaPhoto,
)

from info import ADMINS
from database.manager import get_pg, get_cache
from utils import temp
from imdb import Cinemagoer

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

SPELL_IMAGES = [
    'https://envs.sh/kJj.jpg'
]

imdb = Cinemagoer()

# Configuration
IMDB_CONCURRENCY = 3
MAX_SUGGESTIONS = 8
DEFAULT_POSTER = "https://envs.sh/kJK.jpg"

# Cache TTLs (in seconds)
TTL_SERIES_ACCESSED = 7200      # 2 hours - for user-accessed series
TTL_SEARCH_RESULTS = 300        # 5 minutes - for search results
TTL_POSTER = 86400              # 24 hours - for posters
TTL_LINKS = 3600                # 1 hour - for episode links
TTL_SEASONS = 3600              # 1 hour - for seasons

# Cache key prefixes
PREFIX_SERIES = "series:accessed"
PREFIX_SEARCH = "search:query"
PREFIX_POSTER = "poster"
PREFIX_LINKS = "links"
PREFIX_SEASONS = "seasons"

_imdb_semaphore = asyncio.Semaphore(IMDB_CONCURRENCY)


# -------------------------
# Cache Key Generators
# -------------------------
def _series_key(series_key: str) -> str:
    """Generate cache key for accessed series."""
    return f"{PREFIX_SERIES}:{series_key.lower().replace(' ', '')}"


def _search_key(query: str) -> str:
    """Generate cache key for search results."""
    import hashlib
    q_hash = hashlib.md5(query.lower().strip().encode()).hexdigest()[:12]
    return f"{PREFIX_SEARCH}:{q_hash}"


def _poster_key(series_key: str) -> str:
    """Generate cache key for poster."""
    return f"{PREFIX_POSTER}:{series_key.lower().replace(' ', '')}"


def _links_key(series_key: str, language: str, season: str) -> str:
    """Generate cache key for links."""
    return f"{PREFIX_LINKS}:{series_key.lower()}:{language.lower()}:{season.lower()}"


def _seasons_key(series_key: str) -> str:
    """Generate cache key for seasons."""
    return f"{PREFIX_SEASONS}:{series_key.lower().replace(' ', '')}"


# -------------------------
# Smart Cache Operations
# -------------------------
async def get_series_smart(series_key: str) -> Optional[Dict]:
    """
    Get series with smart caching:
    1. Check Redis cache first
    2. If found, refresh TTL (extend to 2 hours)
    3. If not found, fetch from PostgreSQL and cache
    """
    cache = get_cache()
    pg = get_pg()
    
    normalized_key = series_key.lower().replace(' ', '')
    cache_key = _series_key(normalized_key)
    
    try:
        # Check cache
        cached = await cache.get(cache_key)
        if cached:
            # Refresh TTL on access - extend to 2 hours
            await cache.set(cache_key, cached, ttl=TTL_SERIES_ACCESSED)
            logger.debug(f"Cache HIT for series: {normalized_key}, TTL refreshed")
            return cached
        
        # Cache miss - fetch from PostgreSQL
        series = await pg.get_series(normalized_key)
        if series:
            # Cache the accessed series for 2 hours
            await cache.set(cache_key, series, ttl=TTL_SERIES_ACCESSED)
            logger.debug(f"Cache MISS for series: {normalized_key}, fetched from DB and cached")
        
        return series
    except Exception as e:
        logger.exception(f"Error getting series {series_key}: {e}")
        # Fallback to direct DB query
        return await pg.get_series(normalized_key)


async def search_series_direct(query: str, limit: int = MAX_SUGGESTIONS) -> Tuple[List[Dict], int]:
    """
    Search series directly in PostgreSQL with short-term result caching.
    Returns: (results, total_count)
    """
    cache = get_cache()
    pg = get_pg()
    
    cache_key = _search_key(query)
    
    try:
        # Check short-term cache for repeated searches
        cached = await cache.get(cache_key)
        if cached and isinstance(cached, dict):
            return cached.get('results', []), cached.get('total', 0)
        
        # Search in PostgreSQL
        results, next_offset, total = await pg.search_series(query, limit=limit, offset=0)
        
        # Cache search results for short period (5 minutes)
        if results:
            await cache.set(cache_key, {'results': results, 'total': total}, ttl=TTL_SEARCH_RESULTS)
        
        return results, total
    except Exception as e:
        logger.exception(f"Error searching for '{query}': {e}")
        return [], 0


async def get_exact_series(query: str) -> Optional[Dict]:
    """
    Try to find exact match by key or title.
    First checks cache, then PostgreSQL.
    """
    pg = get_pg()
    normalized = query.lower().replace(' ', '')
    
    # Try cache first (in case user accessed this before)
    cached = await get_series_smart(normalized)
    if cached:
        return cached
    
    # Try exact key match in PostgreSQL
    try:
        series = await pg.get_series(normalized)
        if series:
            # Cache it since user is accessing it
            cache = get_cache()
            await cache.set(_series_key(normalized), series, ttl=TTL_SERIES_ACCESSED)
            return series
    except Exception as e:
        logger.exception(f"Error fetching exact series: {e}")
    
    return None


async def get_seasons_smart(series_key: str) -> List[str]:
    """Get seasons with smart caching."""
    cache = get_cache()
    pg = get_pg()
    
    cache_key = _seasons_key(series_key)
    
    try:
        # Check cache
        cached = await cache.get(cache_key)
        if cached:
            # Refresh TTL
            await cache.set(cache_key, cached, ttl=TTL_SEASONS)
            return cached
        
        # Get from series data
        series = await get_series_smart(series_key)
        if series and series.get('seasons'):
            seasons_data = series['seasons']
            
            if isinstance(seasons_data, dict):
                seasons = list(seasons_data.keys())
            elif isinstance(seasons_data, list):
                seasons = seasons_data
            else:
                seasons = []
            
            if seasons:
                await cache.set(cache_key, seasons, ttl=TTL_SEASONS)
            return seasons
    except Exception as e:
        logger.exception(f"Error getting seasons for {series_key}: {e}")
    
    return []


async def get_links_smart(series_key: str, language: str, season: str) -> Dict[str, str]:
    """Get links with smart caching."""
    cache = get_cache()
    pg = get_pg()
    
    cache_key = _links_key(series_key, language, season)
    
    try:
        # Check cache
        cached = await cache.get(cache_key)
        if cached:
            # Refresh TTL
            await cache.set(cache_key, cached, ttl=TTL_LINKS)
            return cached
        
        # Fetch from PostgreSQL
        links = await pg.get_links(series_key, language, season)
        if links:
            await cache.set(cache_key, links, ttl=TTL_LINKS)
        return links or {}
    except Exception as e:
        logger.exception(f"Error getting links: {e}")
        return {}


async def get_poster_smart(series_key: str) -> Optional[str]:
    """Get poster with smart caching and IMDb fallback."""
    cache = get_cache()
    pg = get_pg()
    
    cache_key = _poster_key(series_key)
    
    try:
        # Check cache
        cached = await cache.get(cache_key)
        if cached:
            return cached
        
        # Try database
        poster_url = await pg.get_poster(series_key)
        if poster_url:
            await cache.set(cache_key, poster_url, ttl=TTL_POSTER)
            return poster_url
        
        # Fallback to IMDb
        series = await get_series_smart(series_key)
        if series and series.get('title'):
            poster_url = await _fetch_imdb_poster(series['title'])
            if poster_url:
                await cache.set(cache_key, poster_url, ttl=TTL_POSTER)
                # Save to DB for persistence
                try:
                    await pg.upsert_poster(series_key, poster_url, source='imdb')
                except Exception:
                    pass
                return poster_url
    except Exception as e:
        logger.exception(f"Error getting poster for {series_key}: {e}")
    
    return None


async def _fetch_imdb_poster(title: str) -> Optional[str]:
    """Fetch poster from IMDb with concurrency limiting."""
    import difflib
    
    async with _imdb_semaphore:
        try:
            search_results = await asyncio.to_thread(imdb.search_movie, title.lower(), 6)
            if search_results:
                # Find best match
                titles = [m.get("title", "").lower() for m in search_results]
                matches = difflib.get_close_matches(title.lower(), titles, n=1, cutoff=0.6)
                if matches:
                    for movie in search_results:
                        if movie.get("title", "").lower() == matches[0]:
                            return movie.get("full-size cover url")
        except Exception:
            logger.exception(f"IMDb poster lookup failed for {title}")
    return None


# -------------------------
# Utility functions
# -------------------------
def chunk_buttons(buttons: List[InlineKeyboardButton], chunk_size: int = 3) -> List[List[InlineKeyboardButton]]:
    """Split buttons into rows."""
    return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]


def normalize_key(text: str) -> str:
    """Normalize text to key format."""
    return text.lower().replace(' ', '')


async def alert_admins(client: Client, series_key: str, error_type: str = "poster"):
    """Alert admins about issues."""
    alert_message = f"⚠️ Failed to fetch {error_type} for series: <code>{series_key}</code>"
    for admin_id in ADMINS:
        try:
            await client.send_message(chat_id=admin_id, text=alert_message, parse_mode=enums.ParseMode.HTML)
        except Exception:
            pass


async def delete_message_later(msg, delay: int = 600):
    """Delete message after delay."""
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass


# -------------------------
# Response Builders
# -------------------------
def build_series_caption(series: Dict) -> str:
    """Build series info caption."""
    return (
        f"○ <b>Title:</b> <code>{series.get('title', 'Unknown')}</code>\n"
        f"○ <b>Released On:</b> <code>{series.get('released_on', 'Unknown')}</code>\n"
        f"○ <b>Genre:</b> <code>{series.get('genre', 'Unknown')}</code>\n"
        f"○ <b>Rating:</b> <code>{series.get('rating', 'N/A')}</code>\n\n"
        "<b>Available Languages:</b>"
    )


def build_language_buttons(series_key: str, languages: List[str], user_id: str) -> InlineKeyboardMarkup:
    """Build language selection buttons."""
    buttons = [
        InlineKeyboardButton(
            lang,
            callback_data=f"{series_key}·{normalize_key(lang)}·{user_id}"
        )
        for lang in languages
    ]
    rows = chunk_buttons(buttons, chunk_size=2)
    rows.append([InlineKeyboardButton("✨Latest Series✨", url="https://t.me/+7luzbTPly8NmMDU1")])
    return InlineKeyboardMarkup(rows)


def build_suggestion_buttons(suggestions: List[Dict], user_id: str) -> InlineKeyboardMarkup:
    """Build spell check suggestion buttons."""
    buttons = [
        InlineKeyboardButton(
            s.get('title', s.get('key', 'Unknown')),
            callback_data=f"spellcheck·{s.get('key', '')}·{user_id}"
        )
        for s in suggestions[:MAX_SUGGESTIONS]
    ]
    rows = chunk_buttons(buttons, chunk_size=2)
    rows.append([InlineKeyboardButton("✨Latest Series✨", url="https://t.me/+7luzbTPly8NmMDU1")])
    return InlineKeyboardMarkup(rows)


# -------------------------
# Message Handler
# -------------------------
@Client.on_message(filters.text & (filters.private | filters.group))
async def handle_series_message(client: Client, message):
    """Main message handler for series search."""
    try:
        text = message.text.strip()
        
        # Skip commands and empty messages
        if not text or text.startswith('/'):
            return
        
        user_id = str(message.from_user.id)
        
        # Step 1: Try exact match first (fast path for cached/known series)
        series = await get_exact_series(text)
        
        if series:
            await send_series_response(client, message, series, user_id)
            return
        
        # Step 2: Search PostgreSQL for close matches
        suggestions, total = await search_series_direct(text, limit=MAX_SUGGESTIONS)
        
        if not suggestions:
            # No matches found at all
            return
        
        # Step 3: Check if any suggestion is an exact title match
        text_lower = text.lower()
        exact_match = None
        for s in suggestions:
            if s.get('title', '').lower() == text_lower:
                exact_match = s
                break
        
        if exact_match:
            # Found exact title match - cache it and show
            cache = get_cache()
            await cache.set(_series_key(exact_match['key']), exact_match, ttl=TTL_SERIES_ACCESSED)
            await send_series_response(client, message, exact_match, user_id)
            return
        
        # Step 4: Single suggestion - use it directly
        if len(suggestions) == 1:
            series = suggestions[0]
            cache = get_cache()
            await cache.set(_series_key(series['key']), series, ttl=TTL_SERIES_ACCESSED)
            await send_series_response(client, message, series, user_id)
            return
        
        # Step 5: Multiple suggestions - show spell check options
        await send_suggestions_response(client, message, suggestions, user_id)
        
    except Exception as e:
        logger.exception(f"Error in handle_series_message: {e}")


async def send_series_response(client: Client, message, series: Dict, user_id: str):
    """Send series details with language selection."""
    series_key = series.get('key', '')
    languages = series.get('languages', [])
    
    if not languages:
        return
    
    caption = build_series_caption(series)
    reply_markup = build_language_buttons(series_key, languages, user_id)
    
    # Fetch poster with timeout
    try:
        poster_url = await asyncio.wait_for(get_poster_smart(series_key), timeout=3.0)
    except asyncio.TimeoutError:
        poster_url = None
    
    try:
        sent_msg = await message.reply_photo(
            photo=poster_url or DEFAULT_POSTER,
            caption=caption,
            reply_markup=reply_markup
        )
        asyncio.create_task(delete_message_later(sent_msg))
    except Exception:
        # Fallback to text
        try:
            sent_msg = await message.reply_text(
                caption,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML
            )
            asyncio.create_task(delete_message_later(sent_msg))
        except Exception:
            pass


async def send_suggestions_response(client: Client, message, suggestions: List[Dict], user_id: str):
    """Send spell check suggestions."""
    reply_markup = build_suggestion_buttons(suggestions, user_id)
    
    try:
        sent_msg = await message.reply_photo(
            photo=random.choice(SPELL_IMAGES),
            caption="<b>Choose Your Series:</b>",
            reply_markup=reply_markup
        )
        asyncio.create_task(delete_message_later(sent_msg))
    except Exception:
        try:
            sent_msg = await message.reply_text(
                "<b>Choose Your Series:</b>",
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML
            )
            asyncio.create_task(delete_message_later(sent_msg))
        except Exception:
            pass


# -------------------------
# Callback Handler
# -------------------------
@Client.on_callback_query()
async def handle_series_callback(client: Client, query: CallbackQuery):
    """Handle all series-related callbacks."""
    data = query.data or ""
    user_id = str(query.from_user.id)
    parts = data.split("·")

    # Basic commands
    if data == "close_data":
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    if data == "pages":
        await query.answer()
        return

    # URL redirects
    if data.startswith(("gt:", "get:")):
        start_parameter = data.split(":", 1)[1]
        try:
            await query.answer(url=f"https://t.me/{temp.U_NAME}?start={start_parameter}")
        except Exception:
            await query.answer("Invalid URL provided.", show_alert=True)
        return

    # Spellcheck selection
    if data.startswith("spellcheck·"):
        await handle_spellcheck_selection(client, query, parts, user_id)
        return

    # Language selection (3 parts)
    if len(parts) == 3:
        await handle_language_selection(client, query, parts, user_id)
        return

    # Season selection (4 parts)
    if len(parts) == 4:
        await handle_season_selection(client, query, parts, user_id)
        return

    await query.answer()


async def handle_spellcheck_selection(client: Client, query: CallbackQuery, parts: List[str], user_id: str):
    """Handle when user selects a series from suggestions."""
    try:
        series_key = parts[1]
        query_user_id = parts[2]
    except (IndexError, ValueError):
        await query.answer("Invalid selection.", show_alert=True)
        return

    if query_user_id != user_id:
        await query.answer("This is not your request!", show_alert=True)
        return

    # Fetch series (this will cache it since user selected it)
    series = await get_series_smart(series_key)
    if not series:
        await query.message.edit_text("Series not found.")
        return

    languages = series.get("languages", [])
    if not languages:
        await query.message.edit_text("No languages available for this series.")
        return

    caption = build_series_caption(series)
    reply_markup = build_language_buttons(series_key, languages, user_id)

    # Fetch poster
    try:
        poster_url = await asyncio.wait_for(get_poster_smart(series_key), timeout=3.0)
    except asyncio.TimeoutError:
        poster_url = None

    # Update message
    try:
        await query.message.edit_media(
            media=InputMediaPhoto(poster_url or DEFAULT_POSTER, caption=caption)
        )
        await query.message.edit_reply_markup(reply_markup=reply_markup)
    except Exception:
        try:
            await query.message.edit_text(text=caption, reply_markup=reply_markup)
        except Exception:
            await query.answer("Failed to update message.", show_alert=True)


async def handle_language_selection(client: Client, query: CallbackQuery, parts: List[str], user_id: str):
    """Handle language selection - show seasons."""
    series_key, language, query_user_id = parts

    if query_user_id != user_id:
        await query.answer("This is not your request!", show_alert=True)
        return

    series = await get_series_smart(series_key)
    if not series:
        await query.answer("Series not found.", show_alert=True)
        return

    seasons = await get_seasons_smart(series_key)
    if not seasons:
        await query.answer("No seasons found.", show_alert=True)
        return

    caption = (
        f"○ <b>Title:</b> <code>{series.get('title', 'Unknown').title()}</code>\n"
        f"○ <b>Released On:</b> <code>{series.get('released_on', 'Unknown')}</code>\n"
        f"○ <b>Genre:</b> <code>{series.get('genre', 'Unknown')}</code>\n"
        f"○ <b>Rating:</b> <code>{series.get('rating', 'N/A')}</code>\n"
        f"<blockquote>▪️<b>Language:</b> <code>{language.title()}</code></blockquote>\n\n"
        "<b>Available Seasons:</b>"
    )

    buttons = [
        InlineKeyboardButton(
            season,
            callback_data=f"{series_key}·{language}·{normalize_key(season)}·{user_id}"
        )
        for season in seasons
    ]
    rows = chunk_buttons(buttons)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"spellcheck·{series_key}·{user_id}")])
    rows.append([InlineKeyboardButton("📝 Request Series", url="https://t.me/+WeBqY_ljwpc3ZjE1")])
    reply_markup = InlineKeyboardMarkup(rows)

    try:
        await query.message.edit_text(text=caption, reply_markup=reply_markup)
    except Exception:
        await query.answer("Failed to update message.", show_alert=True)


async def handle_season_selection(client: Client, query: CallbackQuery, parts: List[str], user_id: str):
    """Handle season selection - show quality/episode links."""
    series_key, language, season, query_user_id = parts

    if query_user_id != user_id:
        await query.answer("This is not your request!", show_alert=True)
        return

    series = await get_series_smart(series_key)
    if not series:
        await query.answer("Series not found.", show_alert=True)
        return

    links = await get_links_smart(series_key, language, season)
    
    if not links:
        await query.message.edit_text(
            "No links found for the selected season and language.",
            parse_mode=enums.ParseMode.HTML
        )
        return

    caption = (
        f"○ <b>Title:</b> <code>{series.get('title', 'Unknown').title()}</code>\n"
        f"○ <b>Released On:</b> <code>{series.get('released_on', 'Unknown')}</code>\n"
        f"○ <b>Genre:</b> <code>{series.get('genre', 'Unknown')}</code>\n"
        f"○ <b>Rating:</b> <code>{series.get('rating', 'N/A')}</code>\n"
        f"<blockquote><b>▪️Language:</b> <code>{language.title()}</code></blockquote>\n"
        f"<blockquote><b>▪️Season:</b> <code>{season.replace('-', ' ').title()}</code></blockquote>\n\n"
        "<b>Select Quality:</b>"
    )

    buttons = [
        InlineKeyboardButton(quality, callback_data=f"gt:{link}")
        for quality, link in links.items()
    ]
    rows = chunk_buttons(buttons, chunk_size=2)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"{series_key}·{language}·{user_id}")])
    rows.append([InlineKeyboardButton("📝 Request Series", url="https://t.me/+WeBqY_ljwpc3ZjE1")])
    reply_markup = InlineKeyboardMarkup(rows)

    try:
        await query.message.edit_text(
            text=caption,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML
        )
    except Exception:
        await query.answer("Failed to display links.", show_alert=True)
