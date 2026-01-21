import asyncio
import os
import logging
from io import BytesIO
from typing import Optional, Tuple, Dict

import aiohttp
from pyrogram.types import Message

# =========================
# LOGGING SETUP
# =========================
logger = logging.getLogger(__name__)

# =========================
# AUTO DELETE
# =========================
DEFAULT_AUTO_DELETE_SECONDS = int(os.getenv("AUTO_DELETE_SECONDS", "0"))

async def auto_delete(msg: Message, sec: Optional[int] = None) -> None:
    if sec is None:
        sec = DEFAULT_AUTO_DELETE_SECONDS
    if not sec or sec <= 0:
        return
    await asyncio.sleep(sec)
    try:
        await msg.delete()
        logger.debug(f"Deleted message {msg.id} after {sec}s")
    except Exception as e:
        logger.warning(f"Failed to delete message {msg.id}: {e}")


# =========================
# FILE ID EXTRACT
# =========================
def get_file_id(msg: Message):
    if msg.media:
        for message_type in (
            "photo",
            "animation",
            "audio",
            "document",
            "video",
            "video_note",
            "voice",
            "sticker",
        ):
            obj = getattr(msg, message_type, None)
            if obj:
                setattr(obj, "message_type", message_type)
                logger.debug(f"Extracted file_id from {message_type}")
                return obj
    logger.debug("No media found in message")
    return None


# =========================
# CUSTOM ASK/LISTEN (NO PYROMOD)
# =========================
_PENDING: Dict[Tuple[int, int], asyncio.Future] = {}

def _key(chat_id: int, user_id: int) -> Tuple[int, int]:
    return (int(chat_id), int(user_id))

def resolve_pending(chat_id: int, user_id: int, message: Message) -> bool:
    k = _key(chat_id, user_id)
    fut = _PENDING.pop(k, None)
    if fut and not fut.done():
        fut.set_result(message)
        logger.debug(f"Resolved pending waiter for chat {chat_id}, user {user_id}")
        return True
    return False

async def wait_user_message(chat_id: int, user_id: int, timeout: int = 180) -> Message:
    k = _key(chat_id, user_id)

    old = _PENDING.pop(k, None)
    if old and not old.done():
        old.cancel()
        logger.debug(f"Cancelled old waiter for chat {chat_id}, user {user_id}")

    fut = asyncio.get_running_loop().create_future()
    _PENDING[k] = fut
    logger.info(f"Waiting for message from user {user_id} in chat {chat_id} (timeout={timeout}s)")
    return await asyncio.wait_for(fut, timeout=timeout)


# =========================
# TMDB AUTO FETCH (Poster + Meta)
# =========================
try:
    from info import TMDB_API_KEY
except Exception:
    TMDB_API_KEY = ""

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/w500"

def _tmdb_headers() -> dict:
    return {
        "Authorization": f"Bearer {TMDB_API_KEY}",
        "accept": "application/json",
    }

async def _http_get_json(url: str, params: Optional[dict] = None) -> dict:
    if not TMDB_API_KEY:
        logger.warning("TMDB API key missing")
        return {}
    try:
        async with aiohttp.ClientSession(headers=_tmdb_headers()) as s:
            async with s.get(url, params=params, timeout=25) as r:
                return await r.json()
    except Exception as e:
        logger.error(f"HTTP GET failed for {url}: {e}")
        return {}

async def _download_bytes(url: str) -> bytes:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=25) as r:
                return await r.read()
    except Exception as e:
        logger.error(f"Download failed for {url}: {e}")
        return b""

async def tmdb_search_best(title: str) -> Optional[Tuple[str, dict]]:
    q = (title or "").strip()
    if not q or not TMDB_API_KEY:
        logger.warning("TMDB search skipped (empty title or missing API key)")
        return None

    tv = await _http_get_json(f"{TMDB_BASE}/search/tv", {"query": q, "include_adult": "false"})
    if tv and tv.get("results"):
        logger.info(f"TMDB TV search hit for '{q}'")
        return ("tv", tv["results"][0])

    mv = await _http_get_json(f"{TMDB_BASE}/search/movie", {"query": q, "include_adult": "false"})
    if mv and mv.get("results"):
        logger.info(f"TMDB Movie search hit for '{q}'")
        return ("movie", mv["results"][0])

    logger.info(f"No TMDB results for '{q}'")
    return None

async def tmdb_details(kind: str, tmdb_id: int) -> dict:
    if not TMDB_API_KEY:
        return {}
    logger.debug(f"Fetching TMDB details for {kind} id={tmdb_id}")
    return await _http_get_json(f"{TMDB_BASE}/{kind}/{tmdb_id}", {"language": "en-US"})

async def auto_fetch_and_set_poster_and_meta(client, series_id: int, title: str, chat_id: int) -> bool:
    if not TMDB_API_KEY:
        logger.warning("TMDB API key missing, skipping auto fetch")
        return False

    hit = await tmdb_search_best(title)
    if not hit:
        logger.info(f"No TMDB match for '{title}'")
        return False

    kind, item = hit
    tmdb_id = int(item.get("id") or 0)
    if not tmdb_id:
        logger.warning(f"Invalid TMDB id for '{title}'")
        return False

    det = await tmdb_details(kind, tmdb_id)

    poster_path = det.get("poster_path") or item.get("poster_path")
    overview = (det.get("overview") or "").strip()

    date_key = "first_air_date" if kind == "tv" else "release_date"
    year = str(det.get(date_key, ""))[:4] if det.get(date_key) else ""

    rating = float(det.get("vote_average") or 0)

    genres = ""
    if det.get("genres"):
        genres = ", ".join([g.get("name", "") for g in det["genres"] if g.get("name")]).strip()

    try:
        from database.series_sql import set_series_meta
        await set_series_meta(series_id, tmdb_id, year, rating, genres, overview)
        logger.info(f"Saved TMDB meta for series {series_id} ({title})")
    except Exception as e:
        logger.error(f"Failed to save TMDB meta for {series_id}: {e}")

    if poster_path:
        try:
            from database.series_sql import set_series_poster
            img_url = f"{TMDB_IMG}{poster_path}"
            data = await _download_bytes(img_url)
            if not data:
                logger.warning(f"Poster download failed for {img_url}")
                return True
            bio = BytesIO(data)
            bio.name = "poster.jpg"

            tmp = await client.send_photo(chat_id, photo=bio)
            file_id = tmp.photo.file_id if tmp.photo else None
            if file_id:
                await set_series_poster(series_id, file_id)
                logger.info(f"Poster set for series {series_id}")
            try:
                await tmp.delete()
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Poster upload failed for series {series_id}: {e}")

    return True
