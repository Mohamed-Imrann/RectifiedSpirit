# utils_poster.py
# TMDB auto poster fetch + IMGBB upload
# Usage:
#   from utils_poster import tmdb_get_poster, upload_imgbb
#   poster_url = await tmdb_get_poster("Breaking Bad", TMDB_API_KEY)
#   imgbb_url  = await upload_imgbb(photo_bytes, IMGBB_API_KEY)

import aiohttp
import base64
from typing import Optional

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG  = "https://image.tmdb.org/t/p/original"


def _tmdb_headers(tmdb_key: str) -> dict:
    # TMDB Read Access Token (Bearer)
    return {
        "Authorization": f"Bearer {tmdb_key}",
        "accept": "application/json",
    }


async def tmdb_search_tv(title: str, tmdb_key: str) -> Optional[dict]:
    title = (title or "").strip()
    if not title:
        return None

    try:
        async with aiohttp.ClientSession(headers=_tmdb_headers(tmdb_key)) as s:
            async with s.get(f"{TMDB_BASE}/search/tv", params={"query": title}) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                results = data.get("results") or []
                return results[0] if results else None
    except Exception:
        return None


async def tmdb_search_movie(title: str, tmdb_key: str) -> Optional[dict]:
    title = (title or "").strip()
    if not title:
        return None

    try:
        async with aiohttp.ClientSession(headers=_tmdb_headers(tmdb_key)) as s:
            async with s.get(f"{TMDB_BASE}/search/movie", params={"query": title}) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                results = data.get("results") or []
                return results[0] if results else None
    except Exception:
        return None


async def tmdb_get_poster(title: str, tmdb_key: str) -> Optional[str]:
    """
    Tries TV first, then Movie. Returns full poster URL or None.
    """
    tv = await tmdb_search_tv(title, tmdb_key)
    if tv and tv.get("poster_path"):
        return f"{TMDB_IMG}{tv['poster_path']}"

    mv = await tmdb_search_movie(title, tmdb_key)
    if mv and mv.get("poster_path"):
        return f"{TMDB_IMG}{mv['poster_path']}"

    return None


async def upload_imgbb(photo_bytes: bytes, imgbb_key: str) -> Optional[str]:
    """
    Upload raw bytes to imgbb. Returns hosted image URL or None.
    """
    if not photo_bytes:
        return None

    try:
        payload = {
            "key": imgbb_key,
            "image": base64.b64encode(photo_bytes).decode("utf-8"),
        }

        async with aiohttp.ClientSession() as s:
            async with s.post("https://api.imgbb.com/1/upload", data=payload) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                # data["data"]["url"] is public direct URL
                return (data.get("data") or {}).get("url")
    except Exception:
        return None
