
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pyrogram.types import ChatJoinRequest
from pyrogram.errors import PeerIdInvalid, UserIsBlocked
from bot import Bot
import asyncio
import re
import logging
import random
import time
import os
from typing import Dict, List

from pyrogram import filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery,
    InputMediaPhoto
)
from pyrogram.errors import MessageNotModified, FloodWait
from pymongo import MongoClient

from info import SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG, ADMINS, CHANNELS, DATABASE_URI, PROTECT_CONTENT, RAW_DB_CHANNEL
from database.crazy_db import get_series, get_series_name, get_poster_manuel
from database.gfilters_mdb import find_gfilter, get_gfilters
from utils import temp, get_links_for_quality
from database.join_reqs import JoinReqs

# ✅ NEW FSUB system (STRICT JOIN + AUTO STEP ADVANCE)
from plugins.request_forcesub import (
    create_request_forcesub_buttons,
    get_required_fsub_chat,
    check_and_advance_if_joined,   # ✅ ADD THIS
)
# ✅ Pending system (JOIN REQUEST => auto send files without clicking again)
# If you don't have these functions yet, add them in database/request_forcesub_db.py
# (I’m assuming you will add them. If you already added, this import works.)
from database.request_forcesub_db import (
    set_pending,
    get_pending,
    clear_pending,
    advance_user_step,   # ✅ we will advance after sending files
    create_temp_token,
    get_link_key_by_token,
    delete_temp_token,
)

BOT_USERNAME = "Spidy_Series_Bot"   # ✅ set this (without @)

# ----------------------------
# ✅ Helper: Resolve tk:token -> real link_key
# ----------------------------
async def resolve_send_key(user_id: int, key: str):
    """Resolve key used for sendseries.

    - If key is 'tk:<token>' -> fetch real link_key from DB using get_link_key_by_token()
      (only if token belongs to this user and not expired).
    - Else -> return the same key.
    """
    if not key:
        return key

    if isinstance(key, str) and key.startswith("tk:"):
        token = key.split(":", 1)[1].strip()
        try:
            # ✅ from database.request_forcesub_db import get_link_key_by_token
            link_key = await get_link_key_by_token(int(user_id), token)
            return link_key or key
        except Exception as e:
            logger.error(f"resolve_send_key error: {e}")
            return key

    return key
import json

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
dbj = JoinReqs()

mongo_client = MongoClient(DATABASE_URI)
edb = mongo_client["file_database"]
ecollection = edb["episodes"]
BATCH_FILES = {}


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


async def _all_required_chats() -> list:
    chats = []
    try:
        c1 = await dbj.get_fsub_chat1()
        if c1 and c1.get("chat_id"):
            chats.append(int(c1["chat_id"]))
    except Exception:
        pass
    try:
        c2 = await dbj.get_fsub_chat2()
        if c2 and c2.get("chat_id"):
            chats.append(int(c2["chat_id"]))
    except Exception:
        pass
    if hasattr(dbj, "get_fsub_chat3"):
        try:
            c3 = await dbj.get_fsub_chat3()
            if c3 and c3.get("chat_id"):
                chats.append(int(c3["chat_id"]))
        except Exception:
            pass

    uniq = []
    for chat_id in chats:
        if chat_id not in uniq:
            uniq.append(chat_id)
    return uniq


async def _resolve_link_key(user_id: int, key_or_token: str):
    if not key_or_token:
        return None
    if key_or_token.startswith("tk:"):
        token = key_or_token.split(":", 1)[1]
        return await get_link_key_by_token(int(user_id), token)
    return key_or_token


async def sendseries(client: Bot, user_token: str, key: str):
    """
    user_token format: "<user_id>:<token>"
    key can be:
      - "tk:<token>"  (preferred temp-token key)
      - deep-link key (get_/e_/B-/legacy)
    """
    try:
        uid, token = user_token.split(":", 1)
        user_id = int(uid)
    except Exception:
        return False

    link_key = await _resolve_link_key(user_id, key)
    if not link_key:
        return False

    if link_key.startswith("e_"):
        args = link_key.split("_")
        if len(args) < 2:
            return False
        series_name = args[1]
        series_data = ecollection.find_one({"series": series_name})
        if not series_data or not series_data.get("files"):
            return False

        sent = 0
        for entry in series_data["files"]:
            try:
                await client.send_cached_media(
                    user_id,
                    entry["file_id"],
                    caption=entry.get("caption", ""),
                    protect_content=PROTECT_CONTENT
                )
                sent += 1
                await asyncio.sleep(1)
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception:
                continue
        return sent > 0

    if link_key.startswith("B-"):
        file_id = link_key.split("-", 1)[1]
        msgs = BATCH_FILES.get(file_id)
        if not msgs:
            file = await client.download_media(file_id)
            try:
                with open(file) as file_data:
                    msgs = json.loads(file_data.read())
            except Exception:
                return False
            finally:
                try:
                    os.remove(file)
                except Exception:
                    pass
            BATCH_FILES[file_id] = msgs

        sent = 0
        for msg in msgs:
            try:
                await client.send_cached_media(
                    chat_id=user_id,
                    file_id=msg.get("file_id"),
                    caption=msg.get("caption", ""),
                    protect_content=msg.get("protect", PROTECT_CONTENT)
                )
                sent += 1
                await asyncio.sleep(0.6)
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception:
                continue
        return sent > 0

    if link_key.startswith("get_"):
        parts = link_key.split("_")
        if len(parts) == 4:
            try:
                channel_id = int(parts[1])
                if channel_id not in RAW_DB_CHANNEL:
                    return False
            except Exception:
                return False

    files_to_send, *_ = await get_links_for_quality(client, link_key)
    if not files_to_send:
        return False

    sent = 0
    for item in files_to_send:
        file_id = item.get("file_id")
        caption = item.get("caption") or ""
        if not file_id:
            continue
        try:
            await client.send_cached_media(chat_id=user_id, file_id=file_id, caption=caption)
            sent += 1
            await asyncio.sleep(0.2)
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception:
            continue

    if sent > 0 and key.startswith("tk:"):
        try:
            key_token = key.split(":", 1)[1]
            await delete_temp_token(user_id, key_token)
        except Exception:
            pass
    return sent > 0


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
        layout.append([InlineKeyboardButton("✨Latest Series✨", url="https://t.me/+GA7Fk5i4kxViZTY1")])
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
                poster_file_id = uploaded.photo.file_id
                break
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception:
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
                    layout.append([InlineKeyboardButton("✨Latest Series✨", url="https://t.me/+GA7Fk5i4kxViZTY1")])

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
# ✅ START HANDLER (Deep-link token => FSUB => send)
# ----------------------------
@Bot.on_message(filters.private & filters.command("start"))
async def start_handler(client: Bot, message: Message):
    user_id = int(message.from_user.id) if message.from_user else int(message.chat.id)
    parts = (message.text or "").split(maxsplit=1)

    # Normal /start without payload -> keep it simple (other handlers may answer)
    if len(parts) == 1:
        return

    payload = parts[1].strip()
    # Deep link sends token only -> rebuild tk:
    temp_key = f"tk:{payload}"

    # ForceSub check (same logic as PM click)
    try:
        required_chat_id, total, step = await get_required_fsub_chat(client, user_id)
    except Exception as e:
        logger.error(f"get_required_fsub_chat error (start): {e}")
        required_chat_id, total, step = None, 0, 0

    btn = await create_request_forcesub_buttons(client, int(user_id))

    if btn:
        try:
            await set_pending(
                int(user_id),
                temp_key,
                int(required_chat_id) if required_chat_id else 0,
                int(step) if step else 0,
                int(total) if total else 1
            )
        except Exception as e:
            logger.error(f"set_pending error (start): {e}")

        try:
            await message.reply_text(
                "<b>🔒 Please join this channel to continue</b>\n\n✅ After join-request, files will come automatically.",
                reply_markup=InlineKeyboardMarkup(btn),
                parse_mode=enums.ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Failed to send fsub button in PM (start): {e}")
        return

    # Already joined -> send
    try:
        await message.reply_text("✅ Sending files...")
    except Exception:
        pass

    try:
        temp_key = await resolve_send_key(int(user_id), temp_key)
        sent = await sendseries(client, f"{user_id}:start", temp_key)
        if sent:
            try:
                await clear_pending(int(user_id))
            except Exception:
                pass

            if required_chat_id and total:
                try:
                    await advance_user_step(int(user_id), int(total))
                except Exception:
                    pass

            try:
                await message.reply_text("✅ Sent!")
            except Exception:
                pass
        else:
            try:
                await message.reply_text("❌ No files found!")
            except Exception:
                pass
    except Exception as e:
        logger.error(f"start sendseries error: {e}", exc_info=True)
        try:
            await message.reply_text("❌ Failed to send files.")
        except Exception:
            pass

# ----------------------------
# ✅ JOIN REQUEST HANDLER (KEEP ONLY THIS ONE)
# ----------------------------
@Bot.on_chat_join_request()
async def on_join_request(client, join_request: ChatJoinRequest):
    try:
        user_id = int(join_request.from_user.id)
        chat_id = int(join_request.chat.id)

        logger.info(f"[JOIN_REQ] got request user={user_id} chat={chat_id}")

        pending = await get_pending(user_id)
        if not pending:
            logger.info(f"[JOIN_REQ] no pending for user={user_id}")
            return

        # ✅ required chats normalize (support both -100.. and plain)
        required_chats = await _all_required_chats()
        required_plain = set(int(str(x).replace("-100", "")) if str(x).startswith("-100") else int(x) for x in required_chats)
        chat_plain = int(str(chat_id).replace("-100", "")) if str(chat_id).startswith("-100") else int(chat_id)

        if chat_id not in required_chats and chat_plain not in required_plain:
            logger.info(f"[JOIN_REQ] chat {chat_id} not required -> ignore")
            return

        # optional save
        try:
            await dbj.add_user(chat_id, user_id)
        except Exception as e:
            logger.error(f"[JOIN_REQ] failed to save user in fsub chat collection: {e}")

        pending_key = (
            pending.get("link_key")
            or pending.get("key")
            or pending.get("temp_key")
            or pending.get("pending_key")
            or pending.get("data_key")
        )
        total = int(pending.get("total", 1))

        if not pending_key:
            logger.error(f"[JOIN_REQ] link key missing user={user_id} -> KEEP pending. pending={pending}")
            return

        # ✅ PM must be open
        try:
            await client.send_message(user_id, "✅ Join request received. Sending files...")
        except FloodWait as e:
            await asyncio.sleep(e.value)
            try:
                await client.send_message(user_id, "✅ Join request received. Sending files...")
            except Exception as e2:
                logger.error(f"[JOIN_REQ] cannot PM user={user_id} after floodwait: {e2}. KEEP pending.")
                return
        except (PeerIdInvalid, UserIsBlocked) as e:
            logger.error(f"[JOIN_REQ] cannot PM user={user_id} ({e}). User must /start bot. KEEP pending.")
            return
        except Exception as e:
            logger.error(f"[JOIN_REQ] send_message error user={user_id}: {e}. KEEP pending.")
            return

        # ✅ resolve key
        logger.error(f"[JOIN_REQ] pending_key BEFORE resolve = {pending_key}")
        try:
            pending_key = await resolve_send_key(int(user_id), str(pending_key))
        except Exception as e:
            logger.error(f"[JOIN_REQ] resolve_send_key error user={user_id}: {e}", exc_info=True)

        logger.error(f"[JOIN_REQ] pending_key AFTER  resolve = {pending_key}")

        # ✅ send with timeout to prevent hanging forever
        sent = False
        try:
            sent = await asyncio.wait_for(
                sendseries(client, f"{user_id}:click", pending_key),
                timeout=180
            )
        except asyncio.TimeoutError:
            logger.error(f"[JOIN_REQ] sendseries TIMEOUT user={user_id} key={pending_key}")
            sent = False
        except FloodWait as e:
            await asyncio.sleep(e.value)
            try:
                sent = await asyncio.wait_for(
                    sendseries(client, f"{user_id}:click", pending_key),
                    timeout=180
                )
            except Exception as e2:
                logger.error(f"[JOIN_REQ] sendseries failed after floodwait user={user_id}: {e2}", exc_info=True)
                sent = False
        except (PeerIdInvalid, UserIsBlocked) as e:
            logger.error(f"[JOIN_REQ] user blocked/invalid user={user_id}: {e}. STOP. KEEP pending.")
            return
        except Exception as e:
            logger.error(f"[JOIN_REQ] sendseries failed user={user_id}: {e}", exc_info=True)
            sent = False

        if sent:
            try:
                await advance_user_step(user_id, total)
            except Exception as e:
                logger.error(f"[JOIN_REQ] advance_user_step error user={user_id}: {e}")

            try:
                await clear_pending(user_id)
            except Exception as e:
                logger.error(f"[JOIN_REQ] clear_pending error user={user_id}: {e}")

            logger.info(f"[JOIN_REQ] done user={user_id} cleared pending")
        else:
            logger.error(f"[JOIN_REQ] send failed user={user_id}. KEEP pending (not cleared).")

    except Exception as e:
        logger.error(f"[JOIN_REQ] handler crashed: {e}", exc_info=True)

# ----------------------------
# Callback handler
# ----------------------------

@Bot.on_callback_query()
async def callback_handler(client: Bot, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data

    # ✅ QUALITY BUTTON HANDLER (b:) + TOKEN RETRY HANDLER (btk:)
    if data.startswith("b:") or data.startswith("btk:"):
        link_key = None
        temp_key = None

        if data.startswith("btk:"):
            raw = data.split(":", 1)[1]
            parts = raw.split(":", 1)
            if len(parts) != 2:
                try:
                    await callback_query.answer("Invalid token data.", show_alert=True)
                except Exception:
                    pass
                return

            token_user_id = int(parts[0])
            token = parts[1]
            if token_user_id != user_id:
                try:
                    await callback_query.answer("This button is not for you.", show_alert=True)
                except Exception:
                    pass
                return

            temp_key = f"tk:{token}"
        else:
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
            except Exception:
                pass
            return

        # =========================================================
        # ✅ NEW FIX: GROUP click -> OPEN BOT PM FIRST (NO FSUB POPUP)
        # =========================================================
        if origin_chat_id < 0:
            try:
                # ✅ make token from link_key if needed
                if not temp_key and link_key:
                    token = await create_temp_token(int(user_id), link_key, ttl_seconds=600)
                    temp_key = f"tk:{token}"

                # deep-link param (you can parse in /start)
                # send only token value (without "tk:")
                start_token = temp_key.split(":", 1)[1] if temp_key and temp_key.startswith("tk:") else ""
                url = f"https://t.me/{BOT_USERNAME}?start={start_token}"

                # ✅ opens bot directly
                await callback_query.answer("Opening bot…", url=url)
            except Exception as e:
                logger.error(f"Open bot deep-link failed: {e}")
                try:
                    await callback_query.answer("❌ Unable to open bot. Check BOT_USERNAME.", show_alert=True)
                except Exception:
                    pass
            return

        # =========================================================
        # ✅ FROM HERE: ONLY PM clicks (origin_chat_id > 0)
        # Your existing FSUB + send logic 그대로
        # =========================================================

        # ✅ GET REQUIRED FSUB CHAT
        # ✅ STRICT CHECK (NOT JOINED => save pending + show join btn, DO NOT send files)
        try:
            required_chat_id, total, step = await get_required_fsub_chat(client, user_id)
        except Exception as e:
            logger.error(f"get_required_fsub_chat error: {e}")
            required_chat_id, total, step = None, 0, 0

        # ✅ show ONLY required channel button when user is not joined
        btn = await create_request_forcesub_buttons(client, int(user_id))

        if btn:
            try:
                # keep token only for retry buttons (optional)
                if not temp_key and link_key:
                    token = await create_temp_token(int(user_id), link_key, ttl_seconds=600)
                    temp_key = f"tk:{token}"

                # ✅ store REAL link_key for join-request auto send
                key_to_store = link_key if link_key else temp_key

                await set_pending(
                    int(user_id),
                    key_to_store,
                    int(required_chat_id) if required_chat_id else 0,
                    int(step) if step else 0,
                    int(total) if total else 1
                )
            except Exception as e:
                logger.error(f"set_pending error: {e}")

            # ❌ popup venam -> show_alert=False
            try:
                await callback_query.answer("Join the channel first!", show_alert=False)
            except Exception:
                pass

            try:
                await client.send_message(
                    chat_id=user_id,
                    text="<b>🔒 Please join this channel to continue</b>\n\n✅ After join-request, files will come automatically.",
                    reply_markup=InlineKeyboardMarkup(btn),
                    parse_mode=enums.ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Failed to send fsub button in PM: {e}")
                try:
                    await callback_query.answer("Open bot PM and press /start first!", show_alert=True)
                except Exception:
                    pass
            return

        # ✅ ALREADY JOINED → SEND FILES
        try:
            await callback_query.answer("Sending files in PM...", show_alert=False)
        except Exception:
            pass

        try:
            send_key = temp_key if temp_key else link_key
            send_key = await resolve_send_key(int(user_id), send_key)
            sent = await sendseries(client, f"{user_id}:click", send_key)

            if not sent:
                try:
                    await callback_query.answer("❌ No files found!", show_alert=True)
                except Exception:
                    pass
                return

            try:
                await clear_pending(int(user_id))
            except Exception:
                pass

            if required_chat_id and total:
                try:
                    await advance_user_step(int(user_id), int(total))
                except Exception:
                    pass

            try:
                await callback_query.answer("✅ Sent in PM!", show_alert=False)
            except Exception:
                pass

        except Exception as e:
            logger.error(f"b: send error for key={link_key}: {e}", exc_info=True)
            try:
                await callback_query.answer("❌ Failed to send files.", show_alert=True)
            except Exception:
                pass

        return

    # ✅ SERIES BUTTON
    if data.startswith("user_series>"):
        await user_series_callback_handler(client, callback_query)
        return

    # ✅ UI BUTTONS
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

        stored_data.update({
            "season_name": season_name,
            "season_index": cb_index
        })

        user_requestor[f"{chat_id}•{message_id}"] = {
            "data": stored_data,
            "timestamp": time.time()
        }

        request_timestamps[f"{chat_id}•{message_id}"] = time.time()

        text = (
            base_text
            + f"○ **Language:** `{stored_data.get('language_name')}`\n"
            + f"○ **Season:** `{season_name}`\n"
            + "Select the quality you need...!"
        )

        # Deep link for PM redirect
        me = await client.get_me()
        bot_username = me.username

        layout = []
        for q in qualities:
            link_key = q.get("link_key")
            if not link_key:
                continue

            layout.append([
                InlineKeyboardButton(
                    q["name"],
                    callback_data=f"b:{link_key}"
                )
            ])

        layout.append([
            InlineKeyboardButton("⬅️ Back", callback_data="back_season")
        ])

        try:
            await query.message.edit_media(
                media=InputMediaPhoto(
                    media=query.message.photo.file_id,
                    caption=text,
                    parse_mode=enums.ParseMode.MARKDOWN
                ),
                reply_markup=InlineKeyboardMarkup(layout)
            )
        except Exception:
            pass

        return
