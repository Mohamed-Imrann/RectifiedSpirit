import asyncio
import os
from io import BytesIO
from typing import Optional, Tuple, Dict

import aiohttp
from pyrogram.types import Message

# =========================
# AUTO DELETE
# =========================
DEFAULT_AUTO_DELETE_SECONDS = int(os.getenv("AUTO_DELETE_SECONDS", "0"))

async def auto_delete(msg, sec: int | None = None):
    if sec is None:
        sec = DEFAULT_AUTO_DELETE_SECONDS
    if not sec or sec <= 0:
        return
    await asyncio.sleep(sec)
    try:
        await msg.delete()
    except Exception:
        pass


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
                return obj
    return None


# =========================
# CUSTOM ASK/LISTEN (NO PYROMOD)
# =========================
# key: (chat_id, user_id)
_PENDING: Dict[tuple, asyncio.Future] = {}

def _key(chat_id: int, user_id: int) -> tuple:
    return (int(chat_id), int(user_id))

def resolve_pending(chat_id: int, user_id: int, message: Message) -> bool:
    """
    Called from plugins/_listener.py
    """
    k = _key(chat_id, user_id)
    fut = _PENDING.pop(k, None)
    if fut and not fut.done():
        fut.set_result(message)
        return True
    return False

async def wait_user_message(chat_id: int, user_id: int, timeout: int = 180) -> Message:
    """
    Waits next incoming message from user_id in chat_id (same loop safe).
    """
    k = _key(chat_id, user_id)

    # cancel existing waiter if any
    old = _PENDING.pop(k, None)
    if old and not old.done():
        old.cancel()

    fut = asyncio.get_running_loop().create_future()
    _PENDING[k] = fut
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

def _tmdb_headers():
    return {
        "Authorization": f"Bearer {TMDB_API_KEY}",
        "accept": "application/json",
    }

async def _http_get_json(url: str, params: dict | None = None) -> dict:
    if not TMDB_API_KEY:
        return {}
    async with aiohttp.ClientSession(headers=_tmdb_headers()) as s:
        async with s.get(url, params=params, timeout=25) as r:
            try:
                return await r.json()
            except Exception:
                return {}

async def _download_bytes(url: str) -> bytes:
    async with aiohttp.ClientSession() as s:
        async with s.get(url, timeout=25) as r:
            return await r.read()

async def tmdb_search_best(title: str) -> Optional[Tuple[str, dict]]:
    q = (title or "").strip()
    if not q or not TMDB_API_KEY:
        return None

    tv = await _http_get_json(f"{TMDB_BASE}/search/tv", {"query": q, "include_adult": "false"})
    if tv and tv.get("results"):
        return ("tv", tv["results"][0])

    mv = await _http_get_json(f"{TMDB_BASE}/search/movie", {"query": q, "include_adult": "false"})
    if mv and mv.get("results"):
        return ("movie", mv["results"][0])

    return None

async def tmdb_details(kind: str, tmdb_id: int) -> dict:
    if not TMDB_API_KEY:
        return {}
    return await _http_get_json(f"{TMDB_BASE}/{kind}/{tmdb_id}", {"language": "en-US"})

async def auto_fetch_and_set_poster_and_meta(client, series_id: int, title: str, chat_id: int) -> bool:
    if not TMDB_API_KEY:
        return False

    hit = await tmdb_search_best(title)
    if not hit:
        return False

    kind, item = hit
    tmdb_id = int(item.get("id") or 0)
    if not tmdb_id:
        return False

    det = await tmdb_details(kind, tmdb_id)

    poster_path = det.get("poster_path") or item.get("poster_path")
    overview = (det.get("overview") or "").strip()

    date_key = "first_air_date" if kind == "tv" else "release_date"
    year = ""
    if det.get(date_key):
        year = str(det[date_key])[:4]

    rating = float(det.get("vote_average") or 0)

    genres = ""
    if det.get("genres"):
        genres = ", ".join([g.get("name", "") for g in det["genres"] if g.get("name")]).strip()

    # meta save (optional)
    try:
        from database.series_sql import set_series_meta
        await set_series_meta(series_id, tmdb_id, year, rating, genres, overview)
    except Exception:
        pass

    # poster upload -> file_id
    if poster_path:
        try:
            from database.series_sql import set_series_poster
            img_url = f"{TMDB_IMG}{poster_path}"
            data = await _download_bytes(img_url)
            bio = BytesIO(data)
            bio.name = "poster.jpg"

            tmp = await client.send_photo(chat_id, photo=bio)
            file_id = tmp.photo.file_id if tmp.photo else None
            if file_id:
                await set_series_poster(series_id, file_id)
            try:
                await tmp.delete()
            except Exception:
                pass
        except Exception:
            pass

    return True
