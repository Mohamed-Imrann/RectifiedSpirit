#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from bot import Bot
import asyncio
import re
import logging
import random
import time
from typing import Dict, List

from pyrogram import filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery,
    InputMediaPhoto
)
from pyrogram.errors import MessageNotModified, FloodWait

from info import SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG, ADMINS, CHANNELS
from database.crazy_db import get_series, get_series_name, get_poster_manuel
from database.gfilters_mdb import find_gfilter, get_gfilters
from utils import temp, get_links_for_quality

# ✅ NEW FSUB system (STRICT JOIN + AUTO STEP ADVANCE)
from plugins.request_forcesub import (
    create_request_forcesub_buttons,
    get_required_fsub_chat,   # ✅ needed for pending save
)

# ✅ Pending system (JOIN REQUEST => auto send files without clicking again)
# If you don't have these functions yet, add them in database/request_forcesub_db.py
# (I’m assuming you will add them. If you already added, this import works.)
from database.request_forcesub_db import (
    set_pending,
    get_pending,
    clear_pending,
    advance_user_step,   # ✅ we will advance after sending files
)

import imdb
import difflib

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

user_requestor: Dict[str, Dict] = {}
request_timestamps: Dict[str, float] = {}

ia = imdb.IMDb()


# ----------------------------
# Helpers
# ----------------------------
async def DeleteMessage(msg):
    await asyncio.sleep(temp.AUTO_DELETE_TIME)
    try:
        await msg.delete()
    except Exception:
        pass


async def clean_expired_requests():
    while True:
        await asyncio.sleep(600)
        now = time.time()
        expired = [k for k, ts in request_timestamps.items() if now - ts > 1800]
        for k in expired:
            user_requestor.pop(k, None)
            request_timestamps.pop(k, None)


def create_user_layout_from_pattern(
    items: List[str],
    layout_pattern: List[int],
    callback_prefix: str = "user_item",
    add_back_button: bool = False,
    back_target: str = ""
) -> List[List[InlineKeyboardButton]]:
    if not items:
        return []

    layout = []
    i = 0

    for row_count in layout_pattern:
        if i >= len(items):
            break
        row = []
        for _ in range(row_count):
            if i < len(items):
                row.append(InlineKeyboardButton(items[i], callback_data=f"{callback_prefix}_{i}"))
                i += 1
        if row:
            layout.append(row)

    while i < len(items):
        row = []
        for _ in range(min(2, len(items) - i)):
            row.append(InlineKeyboardButton(items[i], callback_data=f"{callback_prefix}_{i}"))
            i += 1
        if row:
            layout.append(row)

    if add_back_button:
        layout.append([InlineKeyboardButton("✨Latest Series✨", url="https://t.me/+yKtGXrUgchswYjZl")])
        layout.append([InlineKeyboardButton("✨ Request Series ✨", url="https://t.me/+WeBqY_ljwpc3ZjE1")])
        layout.append([InlineKeyboardButton("⬅️ Back", callback_data=f"back_{back_target}")])

    return layout


def find_close_matches(query, possibilities, n=3, cutoff=0.6):
    return difflib.get_close_matches(query, possibilities, n, cutoff)


def find_most_similar_title(query: str, search_results: list):
    titles = [movie.get('title', '').lower() for movie in search_results]
    matches = difflib.get_close_matches(query.lower(), titles, n=1, cutoff=0.6)
    if matches:
        target = matches[0]
        for movie in search_results:
            if movie.get('title', '').lower() == target:
                return movie
    return None


async def get_main_poster(client: Bot, series_key: str) -> str:
    poster_file_id = get_poster_manuel(series_key)
    if poster_file_id:
        return poster_file_id

    series = get_series_name(series_key)
    if not series or not series.get('title'):
        return NO_POSTER_FOUND_IMG[0]

    title = series['title'].strip()

    try:
        search_results = ia.search_movie(title, results=10)
        if not search_results:
            return NO_POSTER_FOUND_IMG[0]

        best_match = find_most_similar_title(title, search_results)
        if not best_match:
            return NO_POSTER_FOUND_IMG[0]

        poster_url = best_match.get('full-size cover url') or best_match.get('cover url')
        if not poster_url:
            return NO_POSTER_FOUND_IMG[0]

        while True:
            try:
                uploaded = await client.send_photo(
                    chat_id=ADMINS[1],
                    photo=poster_url,
                    caption=f"Auto-fetched poster for {title}"
                )

                # ✅ FIX: photo is a LIST
                poster_file_id = uploaded.photo[-1].file_id if uploaded.photo else None
                if not poster_file_id:
                    return NO_POSTER_FOUND_IMG[0]

                break

            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception as e:
                # optional: logger.error(f"send_photo poster error: {e}")
                return NO_POSTER_FOUND_IMG[0]

        try:
            from database.crazy_db import update_poster_file_id
            update_poster_file_id(series_key, poster_file_id)
        except Exception:
            pass

        return poster_file_id

    except Exception:
        return NO_POSTER_FOUND_IMG[0]


# ----------------------------
# Global filters
# ----------------------------
async def global_filters(client: Bot, message: Message, text=False) -> bool:
    group_id = message.chat.id
    name = text or message.text
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id
    keywords = await get_gfilters("gfilters")

    for keyword in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[\W])" + re.escape(keyword) + r"( |$|[\W])"
        if re.search(pattern, name, flags=re.IGNORECASE):
            reply_text, btn, alert, fileid = await find_gfilter("gfilters", keyword)
            if reply_text:
                reply_text = reply_text.replace("\\n", " ").replace("\\t", "\t")

            try:
                if fileid == "None":
                    if btn == "[]":
                        await client.send_message(group_id, reply_text, disable_web_page_preview=True, reply_to_message_id=reply_id)
                    else:
                        button = eval(btn)
                        await client.send_message(group_id, reply_text, disable_web_page_preview=True, reply_markup=InlineKeyboardMarkup(button), reply_to_message_id=reply_id)
                elif btn == "[]":
                    await client.send_cached_media(group_id, fileid, caption=reply_text or "", reply_to_message_id=reply_id)
                else:
                    button = eval(btn)
                    await message.reply_cached_media(fileid, caption=reply_text or "", reply_markup=InlineKeyboardMarkup(button), reply_to_message_id=reply_id)
                return True
            except Exception:
                pass

    return False


# ----------------------------
# Series filter
# ----------------------------
async def series_filter(client: Bot, message: Message):
    text = (message.text or "").strip()
    series_infos = get_series()
    published_series = [s for s in series_infos if s.get('published', False)]

    series_keys = [series['_id'] for series in published_series]
    series_names = [series['title'] for series in published_series]

    series_key = None

    if text.lower().replace(" ", "").replace("-", "") in series_keys:
        series_key = text.lower().replace(" ", "").replace("-", "")
    else:
        for s_info in published_series:
            if s_info['title'].lower() == text.lower():
                series_key = s_info['_id']
                break

        if not series_key:
            close_matches = find_close_matches(text, series_names)
            if not close_matches and text:
                first_word = text.split()[0]
                close_matches = [name for name in series_names if name.lower().startswith(first_word.lower())]

            if close_matches:
                buttons = []
                for match in close_matches:
                    s_info = next((s for s in published_series if s['title'] == match), None)
                    if s_info:
                        buttons.append(InlineKeyboardButton(match, callback_data=f"user_series>{s_info['_id']}"))

                if buttons:
                    layout = [[b] for b in buttons]
                    layout.append([InlineKeyboardButton("✨ Request Series ✨", url="https://t.me/+WeBqY_ljwpc3ZjE1")])
                    layout.append([InlineKeyboardButton("✨Latest Series✨", url="https://t.me/+yKtGXrUgchswYjZl")])

                    etho = await message.reply_photo(
                        photo=random.choice(SPELL_CHECK_IMAGE),
                        caption="<b>Choose Your Series:</b>",
                        reply_markup=InlineKeyboardMarkup(layout)
                    )

                    reply_user = etho.reply_to_message.from_user.id if etho.reply_to_message and etho.reply_to_message.from_user else None
                    user_requestor[f"{etho.chat.id}•{etho.id}"] = {"data": reply_user, "timestamp": time.time()}
                    request_timestamps[f"{etho.chat.id}•{etho.id}"] = time.time()
                    return

    if series_key:
        series = get_series_name(series_key)
        if not series or not series.get('published', False):
            return

        languages = series.get("languages", [])
        language_layout = series.get("language_layout", [1] * len(languages))

        reply_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n\n"
            "Select the language you need...!"
        )

        poster_url = await get_main_poster(client, series_key)
        language_names = [lang['name'] for lang in languages]
        layout = create_user_layout_from_pattern(language_names, language_layout, "lang")
        if not layout:
            await message.reply("No languages available for this series.")
            return

        etho = await message.reply_photo(
            photo=poster_url if poster_url else NO_POSTER_FOUND_IMG[0],
            caption=reply_text,
            reply_markup=InlineKeyboardMarkup(layout)
        )

        req_user = etho.reply_to_message.from_user.id if etho.reply_to_message and etho.reply_to_message.from_user else message.chat.id
        user_requestor[f"{etho.chat.id}•{etho.id}"] = {
            "data": {"series_key": series_key, "requested_user": req_user},
            "timestamp": time.time()
        }
        request_timestamps[f"{etho.chat.id}•{etho.id}"] = time.time()


# ----------------------------
# Message handlers
# ----------------------------
@Bot.on_message(filters.text & (filters.private | filters.group))
async def handle_message(client: Bot, message: Message):
    if message.from_user is None:
        if message.chat.type != enums.ChatType.PRIVATE:
            return
        user_id = message.chat.id
    else:
        user_id = message.from_user.id

    if message.chat.type != enums.ChatType.PRIVATE:
        glob = await global_filters(client, message)
        if glob is False:
            await series_filter(client, message)
        return

    if user_id not in CHANNELS:
        glob = await global_filters(client, message)
        if glob is False:
            await series_filter(client, message)


async def start_scheduler():
    asyncio.create_task(clean_expired_requests())


# ----------------------------
# ✅ JOIN REQUEST HANDLER
# User presses quality -> bot asks "Join Channel"
# User sends join request -> bot auto sends files in PM (NO need click again)
# ----------------------------
@Bot.on_chat_join_request()
async def on_join_request_handler(client: Bot, join_request):
    try:
        user_id = join_request.from_user.id
        chat_id = join_request.chat.id

        pending = await get_pending(int(user_id))
        if not pending:
            return

        required_chat_id = int(pending.get("required_chat_id", 0))
        if required_chat_id != int(chat_id):
            return

        link_key = pending.get("link_key")
        total = int(pending.get("total", 1))

        if not link_key:
            await clear_pending(int(user_id))
            return

        # Send files now (auto)
        files_to_send, *_ = await get_links_for_quality(client, link_key)
        if not files_to_send:
            await clear_pending(int(user_id))
            return

        for item in files_to_send:
            file_id = item.get("file_id")
            caption = item.get("caption") or ""
            if not file_id:
                continue
            try:
                await client.send_cached_media(chat_id=user_id, file_id=file_id, caption=caption)
                await asyncio.sleep(0.2)
            except Exception:
                pass

        # ✅ advance step for next request (we assume user requested join)
        try:
            await advance_user_step(int(user_id), total)
        except Exception:
            pass

        await clear_pending(int(user_id))

    except Exception as e:
        logger.error(f"on_join_request_handler error: {e}")


# ----------------------------
# Callback handler
# ----------------------------
@Bot.on_callback_query()
async def callback_handler(client: Bot, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data

    # ✅ QUALITY BUTTON HANDLER (b:)
    if data.startswith("b:"):
        link_key = data.split(":", 1)[1]
        origin_chat_id = callback_query.message.chat.id
        origin_msg_id = callback_query.message.id

        # ownership check for group clicks
        stored_entry = user_requestor.get(f"{origin_chat_id}•{origin_msg_id}", {})
        stored_data = stored_entry.get("data") if isinstance(stored_entry, dict) else None
        requested_user = stored_data.get("requested_user") if isinstance(stored_data, dict) else None

        if origin_chat_id < 0 and requested_user and user_id != requested_user:
            try:
                await callback_query.answer("Not your request!", show_alert=True)
            except:
                pass
            return

        # ✅ STRICT CHECK (NOT JOINED => save pending + show join btn, DO NOT send files)
        try:
            required_chat_id, total, step = await get_required_fsub_chat(client, user_id)
        except Exception as e:
            logger.error(f"get_required_fsub_chat error: {e}")
            required_chat_id, total, step = None, 0, 0

        # ask join button if user not joined
        try:
            btn = await create_request_forcesub_buttons(client, user_id)  # returns [[button]] or None
        except Exception as e:
            logger.error(f"create_request_forcesub_buttons error: {e}")
            btn = None

        if btn:
            # ✅ save pending so join-request triggers auto-send
            if required_chat_id:
                try:
                    await set_pending(
                        int(user_id),
                        link_key,
                        int(required_chat_id),
                        int(step),
                        int(total) if total else 1
                    )
                except Exception as e:
                    logger.error(f"set_pending error: {e}")

            try:
                await callback_query.answer("⚠️ Join the channel first!", show_alert=True)
            except:
                pass

            try:
                await client.send_message(
                    chat_id=user_id,
                    text="<b>🔒 Please join this channel to continue</b>\n\n✅ After join-request, files will come automatically.",
                    reply_markup=InlineKeyboardMarkup(btn),
                    parse_mode=enums.ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Failed to send fsub buttons in PM: {e}")
            return  # ✅ STOP HERE

        # ✅ If no fsub configured OR already joined => send files in PM
        try:
            await callback_query.answer("Sending files in PM...", show_alert=False)
        except:
            pass

        try:
            files_to_send, channel_id, first_msg_id, last_msg_id = await get_links_for_quality(client, link_key)

            if not files_to_send:
                try:
                    await callback_query.answer("❌ No files found!", show_alert=True)
                except:
                    pass
                return

            for item in files_to_send:
                file_id = item.get("file_id")
                caption = item.get("caption") or ""
                if not file_id:
                    continue

                try:
                    await client.send_cached_media(
                        chat_id=user_id,   # ✅ ALWAYS PM
                        file_id=file_id,
                        caption=caption
                    )
                    await asyncio.sleep(0.2)
                except FloodWait as e:
                    await asyncio.sleep(e.x)
                except Exception as e:
                    logger.error(f"send_cached_media error: {e}")

            # if user was pending from earlier, clear it
            try:
                await clear_pending(int(user_id))
            except Exception:
                pass

            # ✅ advance after successful send (not before)
            if required_chat_id and total:
                try:
                    await advance_user_step(int(user_id), int(total))
                except Exception:
                    pass

            try:
                await callback_query.answer("✅ Sent in PM!", show_alert=False)
            except:
                pass

        except Exception as e:
            logger.error(f"b: send error for key={link_key}: {e}")
            try:
                await callback_query.answer("❌ Failed to send files.", show_alert=True)
            except:
                pass

        return

    # ✅ SERIES BUTTON
    if data.startswith("user_series>"):
        await user_series_callback_handler(client, callback_query)
        return

    # ✅ UI BUTTONS (language/season/back)
    if data.startswith("lang_") or data.startswith("season_") or data.startswith("quality_") or data.startswith("back_"):
        await user_interface_callback_handler(client, callback_query)
        return


# ----------------------------
# Series Callback
# ----------------------------
async def user_series_callback_handler(client: Bot, query: CallbackQuery):
    data = query.data
    parts = data.split(">")
    clicked_user = query.from_user.id
    chat_id = query.message.chat.id
    message_id = query.message.id

    try:
        await query.answer()
    except Exception:
        pass

    reply_msg = query.message.reply_to_message
    if reply_msg and reply_msg.from_user:
        requested_user = reply_msg.from_user.id
    else:
        stored_data = user_requestor.get(f"{chat_id}•{message_id}", {}).get("data")
        requested_user = stored_data.get("requested_user") if isinstance(stored_data, dict) else stored_data

    if chat_id < 0 and requested_user and clicked_user != requested_user:
        try:
            await query.answer("Not your request!", show_alert=True)
        except:
            pass
        return

    if data.startswith("user_series>"):
        series_key = parts[1]
        series = get_series_name(series_key)
        if not series or not series.get('published', False):
            try:
                await query.message.edit_text("Series not found or not available.", parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass
            return

        user_requestor[f"{chat_id}•{message_id}"] = {
            "data": {"series_key": series_key, "requested_user": clicked_user},
            "timestamp": time.time()
        }
        request_timestamps[f"{chat_id}•{message_id}"] = time.time()

        languages = series.get("languages", [])
        language_layout = series.get("language_layout", [1] * len(languages))

        base_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n\n"
        )

        language_names = [lang['name'] for lang in languages]
        text = base_text + "Select the language you need...!"

        layout = create_user_layout_from_pattern(language_names, language_layout, "lang")
        if not layout:
            try:
                await query.message.edit_text("No languages available for this series.")
            except Exception:
                pass
            return

        poster = await get_main_poster(client, series_key)

        try:
            await query.message.edit_media(
                media=InputMediaPhoto(media=poster, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=InlineKeyboardMarkup(layout)
            )
        except MessageNotModified:
            pass
        except Exception:
            try:
                await query.message.edit_text(text=text, reply_markup=InlineKeyboardMarkup(layout), parse_mode=enums.ParseMode.MARKDOWN)
            except Exception:
                pass


# ----------------------------
# UI Callback Handler
# ----------------------------
async def user_interface_callback_handler(client: Bot, query: CallbackQuery):
    user_id = query.from_user.id
    chat_id = query.message.chat.id
    message_id = query.message.id
    data = query.data

    try:
        await query.answer()
    except Exception:
        pass

    stored_entry = user_requestor.get(f"{chat_id}•{message_id}", {})
    stored_data = stored_entry.get("data") if isinstance(stored_entry, dict) else None

    if not stored_data or not isinstance(stored_data, dict):
        try:
            await query.answer("Session expired. Please search again.", show_alert=True)
        except:
            pass
        return

    series_key = stored_data.get("series_key")
    requested_user = stored_data.get("requested_user")

    if chat_id < 0 and requested_user and user_id != requested_user:
        try:
            await query.answer("Not your request!", show_alert=True)
        except:
            pass
        return

    series = get_series_name(series_key)
    if not series or not series.get('published', False):
        try:
            await query.answer("Series not found or not available.", show_alert=True)
        except:
            pass
        return

    base_text = (
        f"○ **Title:** `{series['title']}`\n"
        f"○ **Released On:** `{series['released_on']}`\n"
        f"○ **Genre:** `{series['genre']}`\n"
        f"○ **Rating:** `{series['rating']}`\n\n"
    )

    # Back handling
    if data.startswith("back_"):
        target = data.split("_", 1)[1]

        if target == "language":
            languages = series.get("languages", [])
            language_layout = series.get("language_layout", [1] * len(languages))
            language_names = [lang['name'] for lang in languages]

            text = base_text + "Select the language you need...!"
            layout = create_user_layout_from_pattern(language_names, language_layout, "lang")
            poster = await get_main_poster(client, series_key)

            try:
                await query.message.edit_media(
                    media=InputMediaPhoto(media=poster, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                    reply_markup=InlineKeyboardMarkup(layout)
                )
            except Exception:
                pass
            return

        if target == "season":
            language_index = stored_data.get("language_index")
            language_name = stored_data.get("language_name")

            languages = series.get("languages", [])
            seasons = languages[language_index].get("seasons", [])
            season_layout = languages[language_index].get("season_layout", [1] * len(seasons))
            season_names = [season['name'] for season in seasons]

            text = base_text + f"○ **Language:** `{language_name}`\n\nSelect the season you need...!"
            layout = create_user_layout_from_pattern(season_names, season_layout, "season", add_back_button=True, back_target="language")

            try:
                await query.message.edit_media(
                    media=InputMediaPhoto(media=query.message.photo.file_id, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                    reply_markup=InlineKeyboardMarkup(layout)
                )
            except Exception:
                pass
            return

    # Parse callback
    parts = data.split("_", 1)
    if len(parts) != 2:
        return

    cb_type = parts[0]
    try:
        cb_index = int(parts[1])
    except ValueError:
        return

    # Language click
    if cb_type == "lang":
        languages = series.get("languages", [])
        if not (0 <= cb_index < len(languages)):
            return

        language_name = languages[cb_index]["name"]
        seasons = languages[cb_index].get("seasons", [])
        season_layout = languages[cb_index].get("season_layout", [1] * len(seasons))
        season_names = [season['name'] for season in seasons]

        stored_data.update({"language_name": language_name, "language_index": cb_index})
        user_requestor[f"{chat_id}•{message_id}"] = {"data": stored_data, "timestamp": time.time()}
        request_timestamps[f"{chat_id}•{message_id}"] = time.time()

        text = base_text + f"○ **Language:** `{language_name}`\nSelect the season you need...!"
        layout = create_user_layout_from_pattern(season_names, season_layout, "season", add_back_button=True, back_target="language")

        try:
            await query.message.edit_media(
                media=InputMediaPhoto(media=query.message.photo.file_id, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=InlineKeyboardMarkup(layout)
            )
        except Exception:
            pass
        return

    # Season click
    if cb_type == "season":
        language_index = stored_data.get("language_index")
        languages = series.get("languages", [])
        seasons = languages[language_index].get("seasons", [])
        if not (0 <= cb_index < len(seasons)):
            return

        season_name = seasons[cb_index]["name"]
        qualities = seasons[cb_index].get("qualities", [])

        stored_data.update({"season_name": season_name, "season_index": cb_index})
        user_requestor[f"{chat_id}•{message_id}"] = {"data": stored_data, "timestamp": time.time()}
        request_timestamps[f"{chat_id}•{message_id}"] = time.time()

        text = (
            base_text
            + f"○ **Language:** `{stored_data.get('language_name')}`\n"
            + f"○ **Season:** `{season_name}`\n"
            + "Select the quality you need...!"
        )

        layout = []
        for q in qualities:
            if q.get("link_key"):
                layout.append([InlineKeyboardButton(q["name"], callback_data=f"b:{q['link_key']}")])

        layout.append([InlineKeyboardButton("⬅️ Back", callback_data="back_season")])

        try:
            await query.message.edit_media(
                media=InputMediaPhoto(media=query.message.photo.file_id, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=InlineKeyboardMarkup(layout)
            )
        except Exception:
            pass
        return
