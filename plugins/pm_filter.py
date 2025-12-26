# plugins/pmfilter.py
import logging
import asyncio
import random
from typing import List, Dict, Optional, Tuple

from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto
)

from info import ADMINS, POSTGRES_URI, REDIS_URL
from database.manager import db, get_pg, get_cache, init_databases
from utils import temp
from imdb import Cinemagoer

logger = logging.getLogger(__name__)

# Configuration
SPELL_CHECK_IMAGES = ['https://envs.sh/kJj.jpg']
DEFAULT_POSTER = "https://envs.sh/kJK.jpg"
AUTO_DELETE_DELAY = 600  # 10 minutes

# IMDb client with rate limiting
imdb_client = Cinemagoer()
imdb_semaphore = asyncio.Semaphore(3)


# ==================== HELPERS ====================

def chunk_buttons(buttons: List[InlineKeyboardButton], cols: int = 2) -> List[List[InlineKeyboardButton]]:
    """Split buttons into rows."""
    return [buttons[i:i + cols] for i in range(0, len(buttons), cols)]


async def auto_delete(message: Message, delay: int = AUTO_DELETE_DELAY):
    """Delete message after delay."""
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except:
        pass


async def ensure_db():
    """Ensure database is initialized."""
    if not db.is_ready:
        await init_databases(POSTGRES_URI, REDIS_URL)


# ==================== CACHED DATA ACCESS ====================

async def fetch_search_results(query: str, limit: int = 10, offset: int = 0) -> Tuple[List[Dict], int, int]:
    """Search with caching."""
    await ensure_db()
    cache = get_cache()
    pg = get_pg()
    
    # Check cache
    cached = await cache.get_search(query, offset)
    if cached:
        return cached
    
    # Query database
    results, next_offset, total = await pg.search_series(query, limit, offset)
    
    # Cache results
    await cache.set_search(query, results, next_offset, total, offset)
    
    return results, next_offset, total


async def fetch_series(key: str) -> Optional[Dict]:
    """Get series with caching."""
    await ensure_db()
    cache = get_cache()
    pg = get_pg()
    
    # Check cache
    cached = await cache.get_series(key)
    if cached:
        return cached
    
    # Query database
    series = await pg.get_series(key)
    if series:
        await cache.set_series(key, series)
    
    return series


async def fetch_suggestions(query: str, limit: int = 5) -> List[Dict]:
    """Get suggestions with caching."""
    await ensure_db()
    cache = get_cache()
    pg = get_pg()
    
    # Check cache
    cached = await cache.get_suggestions(query)
    if cached:
        return cached
    
    # Query database
    suggestions = await pg.get_suggestions(query, limit)
    if suggestions:
        await cache.set_suggestions(query, suggestions)
    
    return suggestions


async def fetch_links(series_key: str, language: str, season: str) -> Dict[str, str]:
    """Get links with caching."""
    await ensure_db()
    cache = get_cache()
    pg = get_pg()
    
    # Check cache
    cached = await cache.get_links(series_key, language, season)
    if cached:
        return cached
    
    # Query database
    links = await pg.get_links(series_key, language, season)
    if links:
        await cache.set_links(series_key, language, season, links)
    
    return links


async def fetch_seasons(key: str) -> List[str]:
    """Get seasons with caching."""
    await ensure_db()
    cache = get_cache()
    pg = get_pg()
    
    # Check cache
    cached = await cache.get_seasons(key)
    if cached:
        return cached
    
    # Query database
    seasons = await pg.get_seasons(key)
    if seasons:
        await cache.set_seasons(key, seasons)
    
    return seasons


async def fetch_poster(key: str, title: str = "") -> Optional[str]:
    """Get poster with caching and IMDb fallback."""
    await ensure_db()
    cache = get_cache()
    pg = get_pg()
    
    # Check cache
    cached = await cache.get_poster(key)
    if cached:
        return cached
    
    # Check database
    poster = await pg.get_poster(key)
    if poster:
        await cache.set_poster(key, poster)
        return poster
    
    # IMDb fallback
    if title:
        poster = await fetch_imdb_poster(title)
        if poster:
            # Save to database and cache
            await pg.upsert_poster(key, poster, source='imdb')
            await cache.set_poster(key, poster)
            return poster
    
    return None


async def fetch_imdb_poster(title: str) -> Optional[str]:
    """Fetch poster from IMDb."""
    if not title:
        return None
    
    async with imdb_semaphore:
        try:
            results = await asyncio.to_thread(imdb_client.search_movie, title, 3)
            for movie in results:
                url = movie.get('full-size cover url')
                if url:
                    return url
        except Exception as e:
            logger.error(f"IMDb error for '{title}': {e}")
    
    return None


# ==================== MESSAGE BUILDERS ====================

async def send_spell_check(message: Message, suggestions: List[Dict], user_id: str) -> Optional[Message]:
    """Send spell check / suggestions message."""
    if not suggestions:
        return None
    
    buttons = [
        InlineKeyboardButton(
            s.get('title', s.get('key', '')),
            callback_data=f"sc:{s['key']}:{user_id}"
        )
        for s in suggestions[:5]
    ]
    
    keyboard = chunk_buttons(buttons, 2)
    keyboard.append([
        InlineKeyboardButton("✨ Latest Series", url="https://t.me/+7luzbTPly8NmMDU1")
    ])
    
    try:
        msg = await message.reply_photo(
            photo=random.choice(SPELL_CHECK_IMAGES),
            caption="<b>🔍 Choose Your Series:</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=enums.ParseMode.HTML
        )
        asyncio.create_task(auto_delete(msg))
        return msg
    except Exception:
        try:
            msg = await message.reply_text(
                "<b>🔍 Choose Your Series:</b>",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=enums.ParseMode.HTML
            )
            asyncio.create_task(auto_delete(msg))
            return msg
        except:
            return None


async def send_series_info(
    message: Message, 
    series: Dict, 
    user_id: str, 
    poster_url: Optional[str] = None
) -> Optional[Message]:
    """Send series information with language selection."""
    
    languages = series.get('languages', [])
    key = series['key']
    title = series.get('title', '')
    
    caption = (
        f"○ <b>Title:</b> <code>{title}</code>\n"
        f"○ <b>Released:</b> <code>{series.get('released_on', 'Unknown')}</code>\n"
        f"○ <b>Genre:</b> <code>{series.get('genre', 'Unknown')}</code>\n"
        f"○ <b>Rating:</b> <code>{series.get('rating', 'N/A')}</code>\n\n"
        f"<b>🌐 Available Languages:</b>"
    )
    
    # Language buttons
    buttons = [
        InlineKeyboardButton(
            lang,
            callback_data=f"lang:{key}:{lang.lower().replace(' ', '')}:{user_id}"
        )
        for lang in languages
    ]
    
    keyboard = chunk_buttons(buttons, 2)
    keyboard.append([
        InlineKeyboardButton("📥 Request Series", url="https://t.me/+WeBqY_ljwpc3ZjE1")
    ])
    
    try:
        msg = await message.reply_photo(
            photo=poster_url or DEFAULT_POSTER,
            caption=caption,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=enums.ParseMode.HTML
        )
        asyncio.create_task(auto_delete(msg))
        return msg
    except Exception:
        try:
            msg = await message.reply_text(
                caption,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=enums.ParseMode.HTML
            )
            asyncio.create_task(auto_delete(msg))
            return msg
        except:
            return None


# ==================== MESSAGE HANDLER ====================

@Client.on_message(
    filters.text & 
    (filters.private | filters.group) & 
    ~filters.command([
        "start", "help", "migrate", "dbstats", "clearcache", 
        "invalidate", "logs", "restart", "settings"
    ])
)
async def series_search_handler(client: Client, message: Message):
    """Handle series search queries."""
    
    text = message.text.strip()
    user_id = str(message.from_user.id)
    
    # Skip empty or command-like messages
    if not text or text.startswith('/'):
        return
    
    try:
        # Search for series
        results, _, total = await fetch_search_results(text, limit=10)
        
        if not results:
            # Try fuzzy suggestions
            suggestions = await fetch_suggestions(text, limit=5)
            if suggestions:
                await send_spell_check(message, suggestions, user_id)
            return
        
        # Check for exact match
        query_normalized = text.lower().replace(' ', '')
        exact_match = None
        
        for r in results:
            if r['key'] == query_normalized or r.get('title', '').lower() == text.lower():
                exact_match = r
                break
        
        if exact_match:
            # Get poster with timeout
            try:
                poster = await asyncio.wait_for(
                    fetch_poster(exact_match['key'], exact_match.get('title', '')),
                    timeout=3.0
                )
            except asyncio.TimeoutError:
                poster = None
            
            await send_series_info(message, exact_match, user_id, poster)
        else:
            # Show suggestions
            await send_spell_check(message, results[:5], user_id)
    
    except Exception as e:
        logger.exception(f"Search handler error: {e}")


# ==================== CALLBACK HANDLER ====================

@Client.on_callback_query()
async def callback_handler(client: Client, query: CallbackQuery):
    """Handle all callback queries."""
    
    data = query.data or ""
    user_id = str(query.from_user.id)
    
    try:
        # ===== CLOSE BUTTON =====
        if data == "close":
            await query.message.delete()
            return
        
        # ===== PLACEHOLDER =====
        if data in ("pages", "back_home"):
            await query.answer()
            return
        
        # ===== GET FILE LINK =====
        if data.startswith(("gt:", "get:")):
            link = data.split(":", 1)[1]
            await query.answer(url=f"https://t.me/{temp.U_NAME}?start={link}")
            return
        
        # ===== SPELL CHECK SELECTION =====
        # Format: sc:series_key:user_id
        if data.startswith("sc:"):
            parts = data.split(":")
            if len(parts) != 3:
                return await query.answer("Invalid request")
            
            key, req_user = parts[1], parts[2]
            
            if req_user != user_id:
                return await query.answer("⚠️ This is not your request!", show_alert=True)
            
            series = await fetch_series(key)
            if not series:
                return await query.answer("Series not found!", show_alert=True)
            
            # Get poster
            try:
                poster = await asyncio.wait_for(
                    fetch_poster(key, series.get('title', '')),
                    timeout=3.0
                )
            except:
                poster = None
            
            languages = series.get('languages', [])
            
            caption = (
                f"○ <b>Title:</b> <code>{series.get('title', '')}</code>\n"
                f"○ <b>Released:</b> <code>{series.get('released_on', 'Unknown')}</code>\n"
                f"○ <b>Genre:</b> <code>{series.get('genre', 'Unknown')}</code>\n"
                f"○ <b>Rating:</b> <code>{series.get('rating', 'N/A')}</code>\n\n"
                f"<b>🌐 Available Languages:</b>"
            )
            
            buttons = [
                InlineKeyboardButton(
                    lang,
                    callback_data=f"lang:{key}:{lang.lower().replace(' ', '')}:{user_id}"
                )
                for lang in languages
            ]
            
            keyboard = chunk_buttons(buttons, 2)
            keyboard.append([
                InlineKeyboardButton("📥 Request Series", url="https://t.me/+WeBqY_ljwpc3ZjE1")
            ])
            
            try:
                await query.message.edit_media(
                    media=InputMediaPhoto(
                        poster or DEFAULT_POSTER,
                        caption=caption,
                        parse_mode=enums.ParseMode.HTML
                    ),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except:
                await query.message.edit_text(
                    caption,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=enums.ParseMode.HTML
                )
            return
        
        # ===== LANGUAGE SELECTION =====
        # Format: lang:series_key:language:user_id
        if data.startswith("lang:"):
            parts = data.split(":")
            if len(parts) != 4:
                return await query.answer("Invalid request")
            
            key, lang, req_user = parts[1], parts[2], parts[3]
            
            if req_user != user_id:
                return await query.answer("⚠️ This is not your request!", show_alert=True)
            
            series = await fetch_series(key)
            if not series:
                return await query.answer("Series not found!", show_alert=True)
            
            seasons = await fetch_seasons(key)
            if not seasons:
                return await query.answer("No seasons available!", show_alert=True)
            
            caption = (
                f"○ <b>Title:</b> <code>{series.get('title', '').title()}</code>\n"
                f"○ <b>Released:</b> <code>{series.get('released_on', 'Unknown')}</code>\n"
                f"○ <b>Genre:</b> <code>{series.get('genre', 'Unknown')}</code>\n"
                f"○ <b>Rating:</b> <code>{series.get('rating', 'N/A')}</code>\n"
                f"<blockquote>▪️ <b>Language:</b> <code>{lang.title()}</code></blockquote>\n\n"
                f"<b>📺 Available Seasons:</b>"
            )
            
            buttons = [
                InlineKeyboardButton(
                    s,
                    callback_data=f"ssn:{key}:{lang}:{s.lower().replace(' ', '')}:{user_id}"
                )
                for s in seasons
            ]
            
            keyboard = chunk_buttons(buttons, 3)
            keyboard.append([
                InlineKeyboardButton("🔙 Back", callback_data=f"sc:{key}:{user_id}")
            ])
            keyboard.append([
                InlineKeyboardButton("📥 Request Series", url="https://t.me/+WeBqY_ljwpc3ZjE1")
            ])
            
            await query.message.edit_text(
                caption,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=enums.ParseMode.HTML
            )
            return
        
        # ===== SEASON SELECTION =====
        # Format: ssn:series_key:language:season:user_id
        if data.startswith("ssn:"):
            parts = data.split(":")
            if len(parts) != 5:
                return await query.answer("Invalid request")
            
            key, lang, season, req_user = parts[1], parts[2], parts[3], parts[4]
            
            if req_user != user_id:
                return await query.answer("⚠️ This is not your request!", show_alert=True)
            
            series = await fetch_series(key)
            if not series:
                return await query.answer("Series not found!", show_alert=True)
            
            # Fetch links
            links = await fetch_links(key, lang, season)
            
            if not links:
                await query.message.edit_text(
                    "❌ <b>No download links available for this season.</b>",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Back", callback_data=f"lang:{key}:{lang}:{user_id}")]
                    ]),
                    parse_mode=enums.ParseMode.HTML
                )
                return
            
            caption = (
                f"○ <b>Title:</b> <code>{series.get('title', '').title()}</code>\n"
                f"○ <b>Released:</b> <code>{series.get('released_on', 'Unknown')}</code>\n"
                f"○ <b>Genre:</b> <code>{series.get('genre', 'Unknown')}</code>\n"
                f"○ <b>Rating:</b> <code>{series.get('rating', 'N/A')}</code>\n"
                f"<blockquote>▪️ <b>Language:</b> <code>{lang.title()}</code></blockquote>\n"
                f"<blockquote>▪️ <b>Season:</b> <code>{season.replace('-', ' ').title()}</code></blockquote>\n\n"
                f"<b>🎬 Select Quality:</b>"
            )
            
            buttons = [
                InlineKeyboardButton(quality, callback_data=f"gt:{link}")
                for quality, link in links.items()
            ]
            
            keyboard = chunk_buttons(buttons, 2)
            keyboard.append([
                InlineKeyboardButton("🔙 Back", callback_data=f"lang:{key}:{lang}:{user_id}")
            ])
            keyboard.append([
                InlineKeyboardButton("📥 Request Series", url="https://t.me/+WeBqY_ljwpc3ZjE1")
            ])
            
            await query.message.edit_text(
                caption,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=enums.ParseMode.HTML
            )
            return
        
        # ===== LEGACY CALLBACK FORMATS (backward compatibility) =====
        if "·" in data:
            parts = data.split("·")
            
            # spellcheck·key·user
            if parts[0] == "spellcheck" and len(parts) == 3:
                query.data = f"sc:{parts[1]}:{parts[2]}"
                return await callback_handler(client, query)
            
            # key·lang·user (language selection)
            if len(parts) == 3:
                query.data = f"lang:{parts[0]}:{parts[1]}:{parts[2]}"
                return await callback_handler(client, query)
            
            # key·lang·season·user (season selection)
            if len(parts) == 4:
                query.data = f"ssn:{parts[0]}:{parts[1]}:{parts[2]}:{parts[3]}"
                return await callback_handler(client, query)
        
        # Unknown callback
        await query.answer()
    
    except Exception as e:
        logger.exception(f"Callback error: {e}")
        await query.answer("An error occurred!", show_alert=True)
