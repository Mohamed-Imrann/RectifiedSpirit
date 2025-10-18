#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Light-weight series bot – APScheduler + LRU-cache + semaphore
"""
import asyncio
import re
import logging
import random
import time
from typing import Dict, Optional, List

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, 
    InputMediaPhoto
)
from info import SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG, ADMINS, CHANNELS
from database.crazy_db import (
    get_series, get_series_name, get_poster_manuel
)
from pyrogram.errors import MessageNotModified
from database.gfilters_mdb import (
    find_gfilter,
    get_gfilters
)
from utils import temp, get_links_for_quality
import imdb
import difflib
import aiohttp

import asyncio
import re
import random
import time
import logging
from functools import lru_cache
from typing import Dict, Optional, List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, InputMediaPhoto
)
from pyrogram.errors import MessageNotModified, FloodWait, BadRequest
import aiohttp
import difflib
import imdb
from bot import Bot
from info import SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG, ADMINS, CHANNELS
from database.crazy_db import get_series, get_series_name, get_poster_manuel, update_poster_file_id
from database.gfilters_mdb import find_gfilter, get_gfilters
from utils import temp

logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ia = imdb.IMDb()

# ---------------------------------------------
# In-memory session store (tiny!)
user_requestor: Dict[str, dict] = {}          # key -> {"series_key": str, "requested_user": int, "ts": float}

# APScheduler
scheduler = AsyncIOScheduler(timezone="UTC")
scheduler.start()

# Semaphore for poster downloads
POSTER_SEM = asyncio.Semaphore(4)

# ---------------------------------------------
# Helpers
# ---------------------------------------------
async def delete_message(msg: Message, delay: int = temp.AUTO_DELETE_TIME):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass

# ---------- LRU-cached DB/IMDb wrappers ----------
@lru_cache(maxsize=512)
def _cached_get_series_name(series_key: str):
    return get_series_name(series_key)

def _cached_get_series():
    return [s for s in get_series() if s.get("published")]

# ---------- Poster ----------
async def get_main_poster(client: Bot, series_key: str) -> str:
    """Return Telegram file_id for poster (download→upload only once)."""
    file_id = get_poster_manuel(series_key)
    if file_id:
        return file_id

    series = await asyncio.get_event_loop().run_in_executor(None, _cached_get_series_name, series_key)
    if not series:
        return NO_POSTER_FOUND_IMG[0]

    title = series["title"].strip()
    logger.info("Fetching IMDb poster for %s", title)

    movies = await asyncio.get_event_loop().run_in_executor(None, ia.search_movie, title)
    best = _find_most_similar(title, movies)
    if not best or not best.get("full-size cover url"):
        return NO_POSTER_FOUND_IMG[0]

    url = best["full-size cover url"]
    async with POSTER_SEM:
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url) as resp:
                    data = await resp.read()
            # upload once
            msg = await client.send_photo(chat_id=ADMINS[1], photo=data,
                                          caption=f"Poster for {title}")
            file_id = msg.photo.file_id
            update_poster_file_id(series_key, file_id)
            return file_id
        except Exception as e:
            logger.error("Poster upload failed: %s", e)
            return NO_POSTER_FOUND_IMG[0]

def _find_most_similar(query: str, movies):
    titles = [m.get("title", "").lower() for m in movies]
    match = difflib.get_close_matches(query.lower(), titles, n=1, cutoff=0.6)
    if match:
        target = match[0]
        for m in movies:
            if m.get("title", "").lower() == target:
                return m
    return None

# ---------- Layout builder ----------
def create_layout(items: List[str], pattern: List[int], cb_prefix: str,
                  add_back: bool = False, back_target: str = ""):
    layout, idx = [], 0
    for row_cnt in pattern:
        row = [InlineKeyboardButton(items[idx + i], callback_data=f"{cb_prefix}_{idx + i}")
               for i in range(row_cnt) if idx + i < len(items)]
        if row:
            layout.append(row)
        idx += row_cnt
    # fill remaining 2-per-row
    while idx < len(items):
        layout.append([InlineKeyboardButton(items[idx], callback_data=f"{cb_prefix}_{idx}"),
                     InlineKeyboardButton(items[idx + 1], callback_data=f"{cb_prefix}_{idx + 1}")])
        idx += 2
    if add_back:
        layout.append([InlineKeyboardButton("✨Latest Series✨", url="https://t.me/+7luzbTPly8NmMDU1")])
        layout.append([InlineKeyboardButton("⬅️ Back", callback_data=f"back_{back_target}")])
    return layout

# ---------- Global filters ----------
async def global_filters(client: Bot, msg: Message, text: str = ""):
    txt = text or msg.text
    for kw in reversed(sorted(await get_gfilters("gfilters"), key=len)):
        if re.search(rf"(^|\W){re.escape(kw)}($|\W)", txt, flags=re.I):
            txt, btn, alert, fid = await find_gfilter("gfilters", kw)
            if fid == "None":
                await msg.reply(txt or "", disable_web_page_preview=True,
                                reply_markup=InlineKeyboardMarkup(eval(btn)) if btn != "[]" else None)
            else:
                await msg.reply_cached_media(fid, caption=txt or "",
                                               reply_markup=InlineKeyboardMarkup(eval(btn)) if btn != "[]" else None)
            return True
    return False

# ---------- Series filter ----------
async def series_filter(client: Bot, msg: Message):
    text = msg.text.strip()
    all_series = await asyncio.get_event_loop().run_in_executor(None, _cached_get_series)
    keys = {s["_id"]: s for s in all_series}
    names = {s["title"].lower(): s for s in all_series}

    # exact key match
    if text.lower().replace(" ", "").replace("-", "") in keys:
        key = text.lower().replace(" ", "").replace("-", "")
        return await _send_language_menu(client, msg, key)

    # exact title match
    if text.lower() in names:
        return await _send_language_menu(client, msg, names[text.lower()]["_id"])

    # fuzzy
    close = difflib.get_close_matches(text, [s["title"] for s in all_series], n=3, cutoff=0.6)
    if not close:
        close = [s["title"] for s in all_series if s["title"].lower().startswith(text.split()[0].lower())][:3]

    if close:
        buttons = [[InlineKeyboardButton(t, callback_data=f"user_series>{keys[t.lower()]['_id']}")]
                   for t in close]
        buttons.append([InlineKeyboardButton("✨ Request Series ✨", url="https://t.me/+WeBqY_ljwpc3ZjE1")])
        m = await msg.reply_photo(random.choice(SPELL_CHECK_IMAGE),
                                  caption="<b>Choose Your Series:</b>",
                                  reply_markup=InlineKeyboardMarkup(buttons))
        _store_request(m, msg.from_user.id)
        return

async def _send_language_menu(client: Bot, msg: Message, series_key: str):
    series = await asyncio.get_event_loop().run_in_executor(None, _cached_get_series_name, series_key)
    if not series:
        return
    languages = series.get("languages", [])
    pattern = series.get("language_layout", [1] * len(languages))
    text = (f"○ **Title:** `{series['title']}`"
            f"○ **Released On:** `{series['released_on']}`"
            f"○ **Genre:** `{series['genre']}`"
            f"○ **Rating:** `{series['rating']}` Select the language you need...!")
    layout = create_layout([lang["name"] for lang in languages], pattern, "lang")
    if not layout:
        return await msg.reply("No languages available.")
    poster = await get_main_poster(client, series_key)
    m = await msg.reply_photo(poster or NO_POSTER_FOUND_IMG[0], caption=text,
                              reply_markup=InlineKeyboardMarkup(layout))
    _store_request(m, msg.from_user.id)

# ---------- Message handlers ----------
@Bot.on_message(filters.text & (filters.private | filters.group))
async def handle_message(client: Bot, msg: Message):
    user_id = msg.from_user.id if msg.from_user else msg.chat.id
    if msg.chat.type != enums.ChatType.PRIVATE and await global_filters(client, msg):
        return
    await series_filter(client, msg)

# ---------- Callback ----------
@Bot.on_callback_query()
async def cb_handler(client: Bot, q: CallbackQuery):
    data = q.data
    user_id = q.from_user.id
    chat_id = q.message.chat.id
    msg_id = q.message.id

    # start parameter helper
    if data.startswith("b:"):
        param = data.split(":", 1)[1]
        try:
            await q.answer(url=f"https://t.me/{temp.U_NAME}?start={param}")
        except Exception:
            await q.answer("Invalid link.", show_alert=True)
        return

    if data.startswith("user_series>"):
        await _handle_user_series(client, q)
        return
    if data.startswith(("lang_", "season_", "quality_", "back_")):
        await _handle_ui(client, q)
        return

# ---------- User-series callback ----------
async def _handle_user_series(client: Bot, q: CallbackQuery):
    series_key = q.data.split(">", 1)[1]
    chat_id, msg_id = q.message.chat.id, q.message.id
    if not _check_access(q, chat_id, msg_id):
        return
    await q.answer()
    series = await asyncio.get_event_loop().run_in_executor(None, _cached_get_series_name, series_key)
    if not series:
        return await q.message.edit_text("Series not found.")
    languages = series.get("languages", [])
    pattern = series.get("language_layout", [1] * len(languages))
    text = (f"○ **Title:** `{series['title']}`"
            f"○ **Released On:** `{series['released_on']}`"
            f"○ **Genre:** `{series['genre']}`"
            f"○ **Rating:** `{series['rating']}` Select the language you need...!")
    layout = create_layout([lang["name"] for lang in languages], pattern, "lang")
    if not layout:
        return await q.message.edit_text("No languages available.")
    poster = await get_main_poster(client, series_key)
    try:
        await q.message.edit_media(
            media=InputMediaPhoto(poster or NO_POSTER_FOUND_IMG[0], caption=text,
                                  parse_mode=enums.ParseMode.MARKDOWN),
            reply_markup=InlineKeyboardMarkup(layout))
    except MessageNotModified:
        pass
    _store_request(q.message, q.from_user.id, series_key=series_key)

# ---------- UI callback ----------
async def _handle_ui(client: Bot, q: CallbackQuery):
    data = q.data
    chat_id, msg_id = q.message.chat.id, q.message.id
    if not _check_access(q, chat_id, msg_id):
        return
    await q.answer()
    entry = _get_request_entry(f"{chat_id}•{msg_id}")
    if not entry:
        return await q.answer("Session expired. Search again.", show_alert=True)
    series_key = entry["series_key"]
    series = await asyncio.get_event_loop().run_in_executor(None, _cached_get_series_name, series_key)
    if not series:
        return await q.answer("Series not found.", show_alert=True)

    base = (f"○ **Title:** `{series['title']}`"
            f"○ **Released On:** `{series['released_on']}`"
            f"○ **Genre:** `{series['genre']}`"
            f"○ **Rating:** `{series['rating']}`")

    # back handler
    if data.startswith("back_"):
        target = data.split("_", 1)[1]
        if target == "language":
            await _replace_with_language(client, q, series, base)
        elif target == "season":
            lang_idx = entry.get("language_index")
            if lang_idx is None:
                return await q.answer("Session error.", show_alert=True)
            await _replace_with_season(client, q, series, base, lang_idx, entry.get("language_name"))
        return

    parts = data.split("_")
    try:
        idx = int(parts[1])
    except (ValueError, IndexError):
        return await q.answer("Invalid.", show_alert=True)

    # language selection
    if parts[0] == "lang":
        languages = series.get("languages", [])
        if not 0 <= idx < len(languages):
            return await q.answer("Invalid.", show_alert=True)
        lang_name = languages[idx]["name"]
        _update_request(chat_id, msg_id, language_index=idx, language_name=lang_name)
        await _replace_with_season(client, q, series, base, idx, lang_name)

    # season selection
    if parts[0] == "season":
        lang_idx = entry.get("language_index")
        if lang_idx is None:
            return await q.answer("Session error.", show_alert=True)
        seasons = series["languages"][lang_idx].get("seasons", [])
        if not 0 <= idx < len(seasons):
            return await q.answer("Invalid.", show_alert=True)
        season_name = seasons[idx]["name"]
        _update_request(chat_id, msg_id, season_index=idx, season_name=season_name)
        qualities = seasons[idx].get("qualities", [])
        layout = []
        for qual in qualities:
            if qual.get("link_key"):
                layout.append([InlineKeyboardButton(qual["name"], callback_data=f'b:{qual["link_key"]}')])
        layout.append([InlineKeyboardButton("⬅️ Back", callback_data="back_season")])
        text = base + f"○ **Language:** `{entry['language_name']}`○ **Season:** `{season_name}`Select the quality you need...!"
        try:
            await q.message.edit_caption(caption=text, parse_mode=enums.ParseMode.MARKDOWN,
                                         reply_markup=InlineKeyboardMarkup(layout))
        except MessageNotModified:
            pass

# ---------- small helpers ----------
def _store_request(msg: Message, user_id: int, series_key: Optional[str] = None):
    key = f"{msg.chat.id}•{msg.id}"
    user_requestor[key] = {"series_key": series_key, "requested_user": user_id, "ts": time.time()}

def _get_request_entry(key: str):
    entry = user_requestor.get(key)
    if entry and time.time() - entry["ts"] > 1800:
        user_requestor.pop(key, None)
        return None
    return entry

def _update_request(chat_id: int, msg_id: int, **kw):
    key = f"{chat_id}•{msg_id}"
    entry = user_requestor.get(key)
    if entry:
        entry.update(kw)

async def _replace_with_language(client: Bot, q: CallbackQuery, series, base_text: str):
    languages = series.get("languages", [])
    pattern = series.get("language_layout", [1] * len(languages))
    layout = create_layout([lang["name"] for lang in languages], pattern, "lang")
    if not layout:
        return await q.answer("No languages.", show_alert=True)
    text = base_text + "Select the language you need...!"
    poster = await get_main_poster(client, series["_id"])
    try:
        await q.message.edit_media(
            media=InputMediaPhoto(poster or NO_POSTER_FOUND_IMG[0], caption=text,
                                  parse_mode=enums.ParseMode.MARKDOWN),
            reply_markup=InlineKeyboardMarkup(layout))
    except MessageNotModified:
        pass
    _store_request(q.message, q.from_user.id, series_key=series["_id"])

async def _replace_with_season(client: Bot, q: CallbackQuery, series, base_text: str,
                               lang_idx: int, lang_name: str):
    seasons = series["languages"][lang_idx].get("seasons", [])
    pattern = series["languages"][lang_idx].get("season_layout", [1] * len(seasons))
    layout = create_layout([s["name"] for s in seasons], pattern, "season", add_back=True, back_target="language")
    if not layout:
        return await q.answer("No seasons.", show_alert=True)
    text = base_text + f"○ **Language:** `{lang_name}` Select the season you need...!"
    try:
        await q.message.edit_caption(caption=text, parse_mode=enums.ParseMode.MARKDOWN,
                                     reply_markup=InlineKeyboardMarkup(layout))
    except MessageNotModified:
        pass

def _check_access(q: CallbackQuery, chat_id: int, msg_id: int):
    entry = _get_request_entry(f"{chat_id}•{msg_id}")
    if chat_id < 0 and entry and q.from_user.id != entry["requested_user"]:
        asyncio.create_task(q.answer("Not your request!", show_alert=True))
        return False
    return True

# ---------- APScheduler purge ----------
async def _purge_old():
    now = time.time()
    to_pop = [k for k, v in user_requestor.items() if now - v["ts"] > 1800]
    for k in to_pop:
        user_requestor.pop(k, None)
    if to_pop:
        logger.info("Purged %d stale sessions", len(to_pop))

scheduler.add_job(_purge_old, "interval", minutes=15, max_instances=1)

# ---------- start ----------
async def start_scheduler():
    pass  # APScheduler already started globally
