#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Complete bot code with MessageIdInvalid protection.
"""

from bot import Bot
import asyncio
import re
import logging
import random
import time
from typing import Dict, Optional, List
from datetime import datetime, timedelta
import imdb
from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery,
    InputMediaPhoto
)
from pyrogram.errors import (
    MessageDeleteForbidden, FloodWait, BadRequest,
    MessageNotModified, MessageIdInvalid
)
from info import SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG, ADMINS, CHANNELS
from database.crazy_db import get_series, get_series_name, get_poster_manuel, update_poster_file_id
from database.gfilters_mdb import find_gfilter, get_gfilters
from utils import temp, get_links_for_quality
import difflib
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.base import JobLookupError
from cachetools import TTLCache

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Scheduler + Cache
# ------------------------------------------------------------------
cache = TTLCache(maxsize=10000, ttl=3600)
scheduler = AsyncIOScheduler()
if not scheduler.running:
    scheduler.start()
    logger.info("APScheduler started")

# ------------------------------------------------------------------
# Globals
# ------------------------------------------------------------------
user_requestor: Dict[str, Dict] = {}
request_timestamps: Dict[str, float] = {}

# ------------------------------------------------------------------
# IMDb
# ------------------------------------------------------------------
ia = imdb.IMDb()

# ------------------------------------------------------------------
# Safe edit helper
# ------------------------------------------------------------------
async def safe_edit(query: CallbackQuery,
                  text: str = None,
                  media=None,
                  reply_markup=None,
                  disable_web_page_preview=True):
    """
    Edit message attached to CallbackQuery.
    Swallows MessageIdInvalid (message deleted) and MessageNotModified.
    """
    try:
        if media:
            await query.message.edit_media(media=media, reply_markup=reply_markup)
        elif text is not None:
            await query.message.edit_text(
                text,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview,
                parse_mode=enums.ParseMode.MARKDOWN
            )
        else:  # only markup change
            await query.message.edit_reply_markup(reply_markup)
    except MessageNotModified:
        pass
    except MessageIdInvalid:
        pass  # message was deleted
    except Exception as e:
        logger.error("safe_edit failed: %s", e)

# ------------------------------------------------------------------
# Scheduler helpers
# ------------------------------------------------------------------
def cancel_delete_job(chat_id: int, message_id: int):
    """Cancel scheduled deletion job for this message."""
    job_id_prefix = f"delete_msg_{chat_id}_{message_id}_"
    for job in scheduler.get_jobs():
        if job.id.startswith(job_id_prefix):
            try:
                scheduler.remove_job(job.id)
            except JobLookupError:
                pass

async def delete_message_task(client: Client, chat_id: int, message_id: int):
    """Scheduled task: delete message."""
    try:
        await client.delete_messages(chat_id, [message_id])
        logger.info("Auto-deleted %s/%s", chat_id, message_id)
    except MessageDeleteForbidden:
        logger.error("No delete permission %s/%s", chat_id, message_id)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error("delete_message_task error: %s", e)

def schedule_message_deletion(client: Client, message: Message, delay: int = None):
    """Schedule message for auto-deletion via APScheduler."""
    if delay is None:
        delay = getattr(temp, 'AUTO_DELETE_TIME', 300)
    deletion_time = datetime.now() + timedelta(seconds=delay)
    job_id = f"delete_msg_{message.chat.id}_{message.id}_{int(time.time())}"
    scheduler.add_job(
        delete_message_task,
        'date',
        run_date=deletion_time,
        args=[client, message.chat.id, message.id],
        id=job_id,
        replace_existing=True
    )
    logger.debug("Scheduled deletion for %s/%s in %ss (job %s)",
                 message.chat.id, message.id, delay, job_id)

# ------------------------------------------------------------------
# Cleanup job
# ------------------------------------------------------------------
def clean_expired_user_requests():
    """Remove entries older than 30 min from user_requestor."""
    now = time.time()
    expired = [k for k, v in user_requestor.items()
               if (now - (v.get('timestamp') or 0)) > 1800]
    for k in expired:
        user_requestor.pop(k, None)
        request_timestamps.pop(k, None)
    if expired:
        logger.info("Cleaned %s expired user requests", len(expired))

scheduler.add_job(
    clean_expired_user_requests,
    'interval',
    minutes=10,
    id='clean_user_requests',
    replace_existing=True,
    next_run_time=datetime.now() + timedelta(minutes=1)
)

# ------------------------------------------------------------------
# Layout helper
# ------------------------------------------------------------------
def create_user_layout_from_pattern(items: List[str],
                                   layout_pattern: List[int],
                                   callback_prefix: str = "user_item",
                                   add_back_button: bool = False,
                                   back_target: str = "") -> List[List[InlineKeyboardButton]]:
    """Create inline keyboard layout from pattern."""
    if not items:
        return []
    layout, idx = [], 0
    for row_count in layout_pattern:
        if idx >= len(items):
            break
        row = []
        for _ in range(row_count):
            if idx < len(items):
                row.append(InlineKeyboardButton(items[idx],
                                               callback_data=f"{callback_prefix}_{idx}"))
                idx += 1
        if row:
            layout.append(row)
    while idx < len(items):
        row = []
        for _ in range(min(2, len(items) - idx)):
            row.append(InlineKeyboardButton(items[idx],
                                           callback_data=f"{callback_prefix}_{idx}"))
            idx += 1
        if row:
            layout.append(row)
    if add_back_button:
        layout.append([InlineKeyboardButton("✨Latest Series✨",
                                       url="https://t.me/+7luzbTPly8NmMDU1")])
        layout.append([InlineKeyboardButton("⬅️ Back",
                                       callback_data=f"back_{back_target}")])
    return layout

# ------------------------------------------------------------------
# IMDb helpers
# ------------------------------------------------------------------
def find_most_similar_title(query: str, search_results: list) -> dict:
    """Return the closest IMDb movie dict."""
    titles = [m.get('title', '').lower() for m in search_results]
    match = difflib.get_close_matches(query.lower(), titles, n=1, cutoff=0.6)
    if match:
        target = match[0]
        for movie in search_results:
            if movie.get('title', '').lower() == target:
                return movie
    return None

async def get_main_poster(client: Bot, series_key: str) -> str:
    """Return Telegram file_id for series poster (cached)."""
    # 1. DB cache
    file_id = get_poster_manuel(series_key)
    if file_id:
        return file_id

    # 2. IMDb fetch
    series = get_series_name(series_key)
    if not series or not series.get('title'):
        logger.warning("No title for key %s", series_key)
        return NO_POSTER_FOUND_IMG[0]

    title = series['title'].strip()
    logger.info("Fetching IMDb poster for '%s'", title)
    try:
        results = ia.search_movie(title, results=10)
        best = find_most_similar_title(title, results)
        if not best:
            return NO_POSTER_FOUND_IMG[0]

        url = best.get('full-size cover url') or best.get('cover url')
        if not url:
            return NO_POSTER_FOUND_IMG[0]

        # Upload to Telegram
        while True:
            try:
                msg = await client.send_photo(ADMINS[1], url,
                                            caption=f"Auto-fetched poster for {title}")
                break
            except FloodWait as fw:
                await asyncio.sleep(fw.value)
            except BadRequest:
                return NO_POSTER_FOUND_IMG[0]

        file_id = msg.photo.file_id
        update_poster_file_id(series_key, file_id)
        return file_id
    except Exception as e:
        logger.error("get_main_poster error: %s", e)
        return NO_POSTER_FOUND_IMG[0]

# ------------------------------------------------------------------
# Global filters
# ------------------------------------------------------------------
async def global_filters(client: Bot, message: Message, text: str = None) -> bool:
    """Apply global gfilter rules."""
    group_id = message.chat.id
    name = text or message.text
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id
    keywords = await get_gfilters("gfilters")

    for kw in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[\W])" + re.escape(kw) + r"( |$|[\W])"
        if not re.search(pattern, name, flags=re.IGNORECASE):
            continue

        logger.info("Global filter matched: %s", kw)
        reply_text, btn, alert, fileid = await find_gfilter("gfilters", kw)
        if reply_text:
            reply_text = reply_text.replace("\\n", " ").replace("\\t", "\t")

        try:
            if fileid == "None":
                if btn == "[]":
                    sent = await client.send_message(
                        group_id, reply_text,
                        disable_web_page_preview=True,
                        reply_to_message_id=reply_id
                    )
                else:
                    sent = await client.send_message(
                        group_id, reply_text,
                        disable_web_page_preview=True,
                        reply_markup=InlineKeyboardMarkup(eval(btn)),
                        reply_to_message_id=reply_id
                    )
            elif btn == "[]":
                sent = await client.send_cached_media(
                    group_id, fileid,
                    caption=reply_text or "",
                    reply_to_message_id=reply_id
                )
            else:
                sent = await message.reply_cached_media(
                    fileid,
                    caption=reply_text or "",
                    reply_markup=InlineKeyboardMarkup(eval(btn)),
                    reply_to_message_id=reply_id
                )
            schedule_message_deletion(client, sent)
            return True
        except Exception as e:
            logger.exception("Global filter kw=%s error: %s", kw, e)
    return False

# ------------------------------------------------------------------
# Series filter
# ------------------------------------------------------------------
async def series_filter(client: Bot, message: Message):
    """Handle series selection / language / season / quality."""
    text = message.text.strip()
    published = [s for s in get_series() if s.get('published')]
    keys = [s['_id'] for s in published]
    names = [s['title'] for s in published]

    series_key = None
    t = text.lower().replace(" ", "").replace("-", "")
    if t in keys:
        series_key = t
    else:
        for s in published:
            if s['title'].lower() == text.lower():
                series_key = s['_id']
                break
        if not series_key:
            close = difflib.get_close_matches(text, names, n=3, cutoff=0.6)
            if not close:
                first = text.split()[0]
                close = [n for n in names if n.lower().startswith(first.lower())]
            if close:
                buttons = []
                for name in close:
                    k = next(s['_id'] for s in published if s['title'] == name)
                    buttons.append(InlineKeyboardButton(name, callback_data=f"user_series>{k}"))
                layout = [[b] for b in buttons]
                layout.append([InlineKeyboardButton("✨ Request Series ✨",
                                                 url="https://t.me/+WeBqY_ljwpc3ZjE1")])
                etho = await message.reply_photo(
                    photo=random.choice(SPELL_CHECK_IMAGE),
                    caption="<b>Choose Your Series:</b>",
                    reply_markup=InlineKeyboardMarkup(layout)
                )
                store_user_request(etho)
                schedule_message_deletion(client, etho)
                return

    if not series_key:
        return

    series = get_series_name(series_key)
    if not series or not series.get('published'):
        return

    languages = series.get("languages", [])
    layout_pattern = series.get("language_layout", [1] * len(languages))
    lang_names = [lg['name'] for lg in languages]

    caption = (
        f"○ **Title:** `{series['title']}`"
        f"○ **Released On:** `{series['released_on']}`"
        f"○ **Genre:** `{series['genre']}`"
        f"○ **Rating:** `{series['rating']}`"
        "Select the language you need...!"
    )

    markup = InlineKeyboardMarkup(
        create_user_layout_from_pattern(lang_names, layout_pattern, "lang")
    )

    poster = await get_main_poster(client, series_key)
    etho = await message.reply_photo(
        photo=poster or NO_POSTER_FOUND_IMG[0],
        caption=caption,
        reply_markup=markup
    )
    store_user_request(etho, series_key=series_key, user_id=message.from_user.id)
    schedule_message_deletion(client, etho)

# ------------------------------------------------------------------
# Message handlers
# ------------------------------------------------------------------
@Bot.on_message(filters.text & (filters.private | filters.group))
async def handle_message(client: Bot, message: Message):
    """Entry point for every text message."""
    if message.from_user is None:
        return
    if message.chat.type != enums.ChatType.PRIVATE:
        if await global_filters(client, message) is False:
            await series_filter(client, message)
        return
    if message.from_user.id not in CHANNELS:
        if await global_filters(client, message) is False:
            await series_filter(client, message)

# ------------------------------------------------------------------
# Callback handlers
# ------------------------------------------------------------------
@Bot.on_callback_query()
async def callback_handler(client: Bot, query: CallbackQuery):
    """Route every callback to the right sub-handler."""
    data = query.data
    if data.startswith("b:"):
        param = data.split(":", 1)[1]
        try:
            await query.answer(url=f"https://t.me/{temp.U_NAME}?start={param}")
        except Exception as e:
            logger.error("b: callback error: %s", e)
            await query.answer("Invalid URL", show_alert=True)
        return

    if data.startswith("user_series>"):
        await user_series_callback_handler(client, query)
        return

    if data.startswith(("lang_", "season_", "quality_", "back_")):
        await user_interface_callback_handler(client, query)
        return

    logger.warning("Unknown callback: %s", data)

# ------------------------------------------------------------------
# User series choice
# ------------------------------------------------------------------
async def user_series_callback_handler(client: Bot, query: CallbackQuery):
    """Show language list after user picks a series."""
    await query.answer()
    parts = query.data.split(">")
    series_key = parts[1]

    # Cancel any auto-delete that might kill the message we are about to edit
    cancel_delete_job(query.message.chat.id, query.message.id)

    series = get_series_name(series_key)
    if not series or not series.get('published'):
        await safe_edit(query, text="Series not found or not available.")
        return

    # Update session
    store_user_request(query.message, series_key=series_key,
                      user_id=query.from_user.id)

    languages = series.get("languages", [])
    layout_pattern = series.get("language_layout", [1] * len(languages))
    lang_names = [lg['name'] for lg in languages]

    caption = (
        f"○ **Title:** `{series['title']}`"
        f"○ **Released On:** `{series['released_on']}`"
        f"○ **Genre:** `{series['genre']}`"
        f"○ **Rating:** `{series['rating']}`"
        "Select the language you need...!"
    )

    markup = InlineKeyboardMarkup(
        create_user_layout_from_pattern(lang_names, layout_pattern, "lang")
    )

    poster = await get_main_poster(client, series_key)
    if poster:
        media = InputMediaPhoto(poster, caption=caption,
                               parse_mode=enums.ParseMode.MARKDOWN)
        await safe_edit(query, media=media, reply_markup=markup)
    else:
        await safe_edit(query, text=caption, reply_markup=markup)

# ------------------------------------------------------------------
# Language / season / quality / back
# ------------------------------------------------------------------
async def user_interface_callback_handler(client: Bot, query: CallbackQuery):
    """Handle lang, season, quality, back buttons."""
    await query.answer()
    data = query.data
    chat_id = query.message.chat.id
    message_id = query.message.id

    # Cancel auto-delete job before we edit
    cancel_delete_job(chat_id, message_id)

    stored_data = get_stored_data(chat_id, message_id)
    if not stored_data:
        await query.answer("Session expired. Search again.", show_alert=True)
        return

    series_key = stored_data['series_key']
    requested_user = stored_data['requested_user']

    # Protect other users' sessions in groups
    if chat_id < 0 and requested_user != query.from_user.id:
        await query.answer("Not your request!", show_alert=True)
        return

    series = get_series_name(series_key)
    if not series or not series.get('published'):
        await query.answer("Series not available.", show_alert=True)
        return

    base_caption = (
        f"○ **Title:** `{series['title']}`"
        f"○ **Released On:** `{series['released_on']}`"
        f"○ **Genre:** `{series['genre']}`"
        f"○ **Rating:** `{series['rating']}`"
    )

    # Back buttons
    if data.startswith("back_"):
        target = data.split("_", 1)[1]
        if target == "language":
            # Show language list again
            languages = series.get("languages", [])
            layout_pattern = series.get("language_layout", [1] * len(languages))
            lang_names = [lg['name'] for lg in languages]

            caption = base_caption + "Select the language you need...!"
            markup = InlineKeyboardMarkup(
                create_user_layout_from_pattern(lang_names, layout_pattern, "lang")
            )

            poster = await get_main_poster(client, series_key)
            if poster:
                media = InputMediaPhoto(poster, caption=caption,
                                       parse_mode=enums.ParseMode.MARKDOWN)
                await safe_edit(query, media=media, reply_markup=markup)
            else:
                await safe_edit(query, text=caption, reply_markup=markup)

            # Update session
            store_user_request(query.message, series_key=series_key,
                              user_id=requested_user)
            return

        if target == "season":
            # Show season list again
            lang_idx = stored_data.get("language_index")
            lang_name = stored_data.get("language_name")

            if lang_idx is None:
                await query.answer("Session error.", show_alert=True)
                return

            languages = series.get("languages", [])
            seasons = languages[lang_idx].get("seasons", [])
            season_layout = languages[lang_idx].get("season_layout", [1] * len(seasons))
            season_names = [s['name'] for s in seasons]

            caption = (base_caption +
                      f"○ **Language:** `{lang_name}`"
                      "Select the season you need...!")
            markup = InlineKeyboardMarkup(
                create_user_layout_from_pattern(season_names, season_layout,
                                              "season", add_back_button=True,
                                              back_target="language")
            )

            # Same photo, only caption changed
            if query.message.photo:
                media = InputMediaPhoto(query.message.photo.file_id,
                                       caption=caption,
                                       parse_mode=enums.ParseMode.MARKDOWN)
                await safe_edit(query, media=media, reply_markup=markup)
            else:
                await safe_edit(query, text=caption, reply_markup=markup)

            store_user_request(query.message, series_key=series_key,
                              language_index=lang_idx,
                              language_name=lang_name,
                              user_id=requested_user)
            return

    # Lang / season / quality choice
    parts = data.split("_")
    if len(parts) < 2:
        return
    try:
        idx = int(parts[1])
    except ValueError:
        return

    if parts[0] == "lang":
        languages = series.get("languages", [])
        if not (0 <= idx < len(languages)):
            await query.answer("Invalid selection.", show_alert=True)
            return

        lang_name = languages[idx]['name']
        seasons = languages[idx].get("seasons", [])
        season_layout = languages[idx].get("season_layout", [1] * len(seasons))
        season_names = [s['name'] for s in seasons]

        caption = (base_caption +
                  f"○ **Language:** `{lang_name}`"
                  "Select the season you need...!")
        markup = InlineKeyboardMarkup(
            create_user_layout_from_pattern(season_names, season_layout,
                                          "season", add_back_button=True,
                                          back_target="language")
        )

        if query.message.photo:
            media = InputMediaPhoto(query.message.photo.file_id,
                                   caption=caption,
                                   parse_mode=enums.ParseMode.MARKDOWN)
            await safe_edit(query, media=media, reply_markup=markup)
        else:
            await safe_edit(query, text=caption, reply_markup=markup)

        store_user_request(query.message, series_key=series_key,
                          language_index=idx,
                          language_name=lang_name,
                          user_id=requested_user)

    elif parts[0] == "season":
        lang_idx = stored_data.get("language_index")
        if lang_idx is None:
            await query.answer("Session error.", show_alert=True)
            return

        languages = series.get("languages", [])
        seasons = languages[lang_idx].get("seasons", [])
        if not (0 <= idx < len(seasons)):
            await query.answer("Invalid selection.", show_alert=True)
            return

        season_name = seasons[idx]['name']
        qualities = seasons[idx].get("qualities", [])

        caption = (base_caption +
                  f"○ **Language:** `{stored_data['language_name']}`"
                  f"○ **Season:** `{season_name}`"
                  "Select the quality you need...!")

        layout = []
        for qual in qualities:
            if qual.get("link_key"):
                layout.append([InlineKeyboardButton(
                    qual['name'],
                    callback_data=f"b:{qual['link_key']}"
                )])

        layout.append([InlineKeyboardButton("⬅️ Back",
                                         callback_data="back_season")])
        markup = InlineKeyboardMarkup(layout)

        if query.message.photo:
            media = InputMediaPhoto(query.message.photo.file_id,
                                   caption=caption,
                                   parse_mode=enums.ParseMode.MARKDOWN)
            await safe_edit(query, media=media, reply_markup=markup)
        else:
            await safe_edit(query, text=caption, reply_markup=markup)

        store_user_request(query.message, series_key=series_key,
                          language_index=lang_idx,
                          language_name=stored_data['language_name'],
                          season_index=idx,
                          season_name=season_name,
                          user_id=requested_user)

# ------------------------------------------------------------------
# Session helpers
# ------------------------------------------------------------------
def store_user_request(message: Message,
                      series_key: str = None,
                      language_index: int = None,
                      language_name: str = None,
                      season_index: int = None,
                      season_name: str = None,
                      user_id: int = None):
    """Save session data to user_requestor dict."""
    key = f"{message.chat.id}•{message.id}"
    data = {"series_key": series_key, "requested_user": user_id}
    if language_index is not None:
        data.update(language_index=language_index,
                   language_name=language_name)
    if season_index is not None:
        data.update(season_index=season_index,
                   season_name=season_name)
    user_requestor[key] = {"data": data, "timestamp": time.time()}
    request_timestamps[key] = time.time()

def get_stored_data(chat_id: int, message_id: int) -> Optional[dict]:
    """Retrieve stored session data."""
    key = f"{chat_id}•{message_id}"
    entry = user_requestor.get(key, {})
    return entry.get("data") if isinstance(entry, dict) else None
