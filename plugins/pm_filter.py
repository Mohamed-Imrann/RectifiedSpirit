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
from info import SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG, ADMINS, CHANNELS

# ✅ NOW POSTGRES BACKEND (same module names, rewritten)
from database.crazy_db import (
    get_series, get_series_name, get_poster_manuel, update_poster_file_id
)
from pyrogram.errors import MessageNotModified, FloodWait, BadRequest
from database.gfilters_mdb import (
    find_gfilter,
    get_gfilters
)

from utils import temp
import imdb
import difflib

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global variables
user_requestor: Dict[str, Dict] = {}
request_timestamps: Dict[str, float] = {}

# IMDb setup
ia = imdb.IMDb()


async def DeleteMessage(msg):
    await asyncio.sleep(temp.AUTO_DELETE_TIME)
    try:
        await msg.delete()
        logger.debug(f"Deleted message {msg.id} from chat {msg.chat.id}")
    except Exception as e:
        logger.warning(f"Failed to delete message {msg.id}: {e}")


async def clean_expired_requests():
    """Clean up user_requestor entries older than 30 minutes"""
    while True:
        await asyncio.sleep(600)
        current_time = time.time()
        expired_keys = []

        for key, timestamp in request_timestamps.items():
            if current_time - timestamp > 1800:
                expired_keys.append(key)

        for key in expired_keys:
            user_requestor.pop(key, None)
            request_timestamps.pop(key, None)

        if expired_keys:
            logger.info(f"Cleaned {len(expired_keys)} expired requests")


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
    item_index = 0

    for row_count in layout_pattern:
        if item_index >= len(items):
            break

        row = []
        for _ in range(row_count):
            if item_index < len(items):
                row.append(
                    InlineKeyboardButton(
                        items[item_index],
                        callback_data=f"{callback_prefix}_{item_index}"
                    )
                )
                item_index += 1

        if row:
            layout.append(row)

    while item_index < len(items):
        row = []
        for _ in range(min(2, len(items) - item_index)):
            row.append(
                InlineKeyboardButton(
                    items[item_index],
                    callback_data=f"{callback_prefix}_{item_index}"
                )
            )
            item_index += 1
        if row:
            layout.append(row)

    if add_back_button:
        layout.append([InlineKeyboardButton("✨Latest Series✨", url="https://t.me/+yKtGXrUgchswYjZl")])
        layout.append([InlineKeyboardButton("✨ Request Series ✨", url="https://t.me/+WeBqY_ljwpc3ZjE1")])
        layout.append([InlineKeyboardButton("⬅️ Back", callback_data=f"back_{back_target}")])

    return layout


def find_close_matches(query, possibilities, n=3, cutoff=0.6):
    return difflib.get_close_matches(query, possibilities, n, cutoff)


def find_most_similar_title(query: str, search_results: list) -> dict:
    titles = [movie.get('title', '').lower() for movie in search_results]
    matches = difflib.get_close_matches(query.lower(), titles, n=1, cutoff=0.6)
    if matches:
        target = matches[0]
        for movie in search_results:
            if movie.get('title', '').lower() == target:
                return movie
    return None


async def get_main_poster(client: Bot, series_key: str) -> str:
    """
    Get poster as Telegram file_id.
    1. Check DB (poster_file_id)
    2. Fallback to IMDb → upload to Telegram → cache file_id
    """
    poster_file_id = await get_poster_manuel(series_key)
    if poster_file_id:
        return poster_file_id

    series = await get_series_name(series_key)
    if not series or not series.get('title'):
        logger.warning(f"No title found for series key: {series_key}")
        return NO_POSTER_FOUND_IMG[0]

    title = series['title'].strip()
    logger.info(f"Fetching poster for '{title}' (key: {series_key}) via IMDb")

    try:
        search_results = ia.search_movie(title, results=10)
        if not search_results:
            logger.warning(f"No IMDb results for '{title}'")
            return NO_POSTER_FOUND_IMG[0]

        best_match = find_most_similar_title(title, search_results)
        if not best_match:
            logger.warning(f"No close match on IMDb for '{title}'")
            return NO_POSTER_FOUND_IMG[0]

        poster_url = best_match.get('full-size cover url') or best_match.get('cover url')
        if not poster_url:
            logger.warning(f"No poster URL for IMDb match: {best_match.get('title')}")
            return NO_POSTER_FOUND_IMG[0]

        logger.debug(f"Found IMDb poster URL: {poster_url}")

        uploaded = None
        while True:
            try:
                uploaded = await client.send_photo(
                    chat_id=ADMINS[1],
                    photo=poster_url,
                    caption=f"Auto-fetched poster for {title}"
                )
                break
            except FloodWait as e:
                logger.warning(f"FloodWait encountered: sleeping for {e.value} seconds")
                await asyncio.sleep(e.value)
            except BadRequest as e:
                logger.error(f"BadRequest uploading poster: {str(e)}")
                return NO_POSTER_FOUND_IMG[0]
            except Exception as e:
                logger.error(f"Error uploading poster to Telegram: {e}")
                return NO_POSTER_FOUND_IMG[0]

        poster_file_id = uploaded.photo.file_id

        try:
            await update_poster_file_id(series_key, poster_file_id)
            logger.info(f"Cached poster file_id for {series_key}")
        except Exception as e:
            logger.error(f"Failed to save poster file_id to DB: {e}")

        return poster_file_id

    except Exception as e:
        logger.exception(f"Error in get_main_poster for '{title}': {e}")
        return NO_POSTER_FOUND_IMG[0]


async def global_filters(client: Bot, message: Message, text=False) -> bool:
    logger.info(f"Applying global filters to message {message.id} from user {message.from_user.id}")
    group_id = message.chat.id
    name = text or message.text
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id
    keywords = await get_gfilters("gfilters")

    for keyword in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[\W])" + re.escape(keyword) + r"( |$|[\W])"
        if re.search(pattern, name, flags=re.IGNORECASE):
            logger.info(f"Global filter matched keyword: {keyword}")
            reply_text, btn, alert, fileid = await find_gfilter("gfilters", keyword)
            if reply_text:
                reply_text = reply_text.replace("\\n", " ").replace("\\t", "\t")

            try:
                # NOTE: your original logic uses "None" string. We keep it compatible.
                if fileid == "None" or fileid is None:
                    if btn == "[]":
                        await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_to_message_id=reply_id
                        )
                    else:
                        button = eval(btn)  # same as your original (be careful who can edit DB)
                        await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_markup=InlineKeyboardMarkup(button),
                            reply_to_message_id=reply_id
                        )
                elif btn == "[]":
                    await client.send_cached_media(
                        group_id,
                        fileid,
                        caption=reply_text or "",
                        reply_to_message_id=reply_id
                    )
                else:
                    button = eval(btn)
                    await message.reply_cached_media(
                        fileid,
                        caption=reply_text or "",
                        reply_markup=InlineKeyboardMarkup(button),
                        reply_to_message_id=reply_id
                    )

                logger.info(f"Successfully sent global filter response for keyword: {keyword}")
                return True

            except Exception as e:
                logger.exception(f"Error in global filter for keyword {keyword}: {e}")

    logger.info("No global filters matched")
    return False


async def series_filter(client: Bot, message: Message):
    logger.info(f"Applying series filter to message {message.id} from user {message.from_user.id}")
    text = message.text.strip()

    series_infos = await get_series()
    published_series = [s for s in series_infos if s.get('published', False)]

    series_keys = [series['_id'] for series in published_series]
    series_names = [series['title'] for series in published_series]

    series_key = None
    normalized = text.lower().replace(" ", "").replace("-", "")

    if normalized in series_keys:
        series_key = normalized
        logger.info(f"Found exact key match: {series_key}")
    else:
        for s_info in published_series:
            if s_info['title'].lower() == text.lower():
                series_key = s_info['_id']
                logger.info(f"Found exact title match: {series_key}")
                break

        if not series_key:
            close_matches = find_close_matches(text, series_names)
            if not close_matches and text.split():
                first_word = text.split()[0]
                close_matches = [name for name in series_names if name.lower().startswith(first_word.lower())]

            if close_matches:
                logger.info(f"Found {len(close_matches)} close matches: {close_matches}")
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
                        reply_markup=InlineKeyboardMarkup(layout),
                        parse_mode=enums.ParseMode.HTML
                    )
                    reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else None
                    user_requestor[f"{etho.chat.id}•{etho.id}"] = {"data": reply_etho_user_id, "timestamp": time.time()}
                    request_timestamps[f"{etho.chat.id}•{etho.id}"] = time.time()
                    logger.info(f"Sent series selection message with {len(buttons)} options")
                    return

    if series_key:
        logger.info(f"Processing series with key: {series_key}")
        series = await get_series_name(series_key)
        if not series or not series.get('published', False):
            logger.warning(f"Series not found or not published for key: {series_key}")
            return

        languages = series.get("languages", [])
        language_layout = series.get("language_layout", [1] * len(languages))

        reply_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series.get('released_on', '')}`\n"
            f"○ **Genre:** `{series.get('genre', '')}`\n"
            f"○ **Rating:** `{series.get('rating', '')}`\n\n"
            "Select the language you need...!"
        )

        poster_url = await get_main_poster(client, series_key)
        language_names = [lang['name'] for lang in languages]
        layout = create_user_layout_from_pattern(language_names, language_layout, "lang")

        if not layout:
            await message.reply("No languages available for this series.")
            return

        try:
            etho = await message.reply_photo(
                photo=poster_url or NO_POSTER_FOUND_IMG[0],
                caption=reply_text,
                reply_markup=InlineKeyboardMarkup(layout),
                parse_mode=enums.ParseMode.MARKDOWN
            )

            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            user_requestor[f"{etho.chat.id}•{etho.id}"] = {
                "data": {"series_key": series_key, "requested_user": reply_etho_user_id},
                "timestamp": time.time()
            }
            request_timestamps[f"{etho.chat.id}•{etho.id}"] = time.time()
            logger.info(f"Sent series filter response for {series['title']}")
        except Exception as e:
            logger.error(f"Error sending series filter message: {e}")


@Bot.on_message(filters.text & (filters.private | filters.group))
async def handle_message(client: Bot, message: Message):
    if message.from_user is None:
        if message.chat.type == enums.ChatType.PRIVATE:
            logger.debug("Using chat.id as user_id for private message")
        else:
            logger.warning("Message in group has no from_user; skipping")
            return
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


@Bot.on_callback_query()
async def callback_handler(client: Bot, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    logger.info(f"Received callback query from user {user_id}: {data}")

    if data.startswith("b:"):
        start_parameter = data.split(":", 1)[1]
        try:
            await callback_query.answer(url=f"https://t.me/{temp.U_NAME}?start={start_parameter}")
        except Exception as e:
            logger.error(f"Error in b: callback: {e}")
            await callback_query.answer("Invalid URL provided.", show_alert=True)
        return

    if data.startswith("user_series>"):
        await user_series_callback_handler(client, callback_query)
        return

    if data.startswith(("lang_", "season_", "quality_", "back_")):
        await user_interface_callback_handler(client, callback_query)
        return

    logger.warning(f"Unknown callback type from user {user_id}: {data}")


async def user_series_callback_handler(client: Bot, query: CallbackQuery):
    data = query.data
    parts = data.split(">")
    clicked_user = query.from_user.id
    chat_id = query.message.chat.id
    message_id = query.message.id
    logger.info(f"Processing user series callback: {data}")

    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"Failed to acknowledge callback: {e}")

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

    if data == "pages":
        return

    if data.startswith("user_series>"):
        series_key = parts[1]
        logger.info(f"Processing series with key: {series_key}")

        series = await get_series_name(series_key)
        if not series or not series.get('published', False):
            try:
                await query.message.edit_text("Series not found or not available.", parse_mode=enums.ParseMode.HTML)
            except Exception as e:
                logger.error(f"Failed to edit message: {e}")
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
            f"○ **Released On:** `{series.get('released_on', '')}`\n"
            f"○ **Genre:** `{series.get('genre', '')}`\n"
            f"○ **Rating:** `{series.get('rating', '')}`\n\n"
        )

        language_names = [lang['name'] for lang in languages]
        text = base_text + "Select the language you need...!"
        layout = create_user_layout_from_pattern(language_names, language_layout, "lang")

        if not layout:
            try:
                await query.message.edit_text("No languages available for this series.")
            except Exception as e:
                logger.error(f"Failed to edit message: {e}")
            return

        poster = await get_main_poster(client, series_key)
        try:
            await query.message.edit_media(
                media=InputMediaPhoto(media=poster, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=InlineKeyboardMarkup(layout)
            )
        except MessageNotModified:
            pass
        except Exception as e:
            logger.error(f"Error editing message: {e}")
            try:
                await query.answer("An error occurred. Please try again.", show_alert=True)
            except:
                pass


async def user_interface_callback_handler(client: Bot, query: CallbackQuery):
    user_id = query.from_user.id
    chat_id = query.message.chat.id
    message_id = query.message.id
    data = query.data
    logger.info(f"Processing user interface callback: {data}")

    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"Failed to acknowledge callback: {e}")

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

    series = await get_series_name(series_key)
    if not series or not series.get('published', False):
        try:
            await query.answer("Series not found or not available.", show_alert=True)
        except:
            pass
        return

    base_text = (
        f"○ **Title:** `{series['title']}`\n"
        f"○ **Released On:** `{series.get('released_on', '')}`\n"
        f"○ **Genre:** `{series.get('genre', '')}`\n"
        f"○ **Rating:** `{series.get('rating', '')}`\n\n"
    )

    # BACK buttons
    if data.startswith("back_"):
        target = data.split("_")[1]

        if target == "language":
            languages = series.get("languages", [])
            language_layout = series.get("language_layout", [1] * len(languages))
            language_names = [lang['name'] for lang in languages]
            text = base_text + "Select the language you need...!"
            layout = create_user_layout_from_pattern(language_names, language_layout, "lang")

            if not layout:
                try:
                    await query.answer("No languages available for this series.", show_alert=True)
                except:
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
            except Exception as e:
                logger.error(f"Error editing message: {e}")
            return

        if target == "season":
            language_index = stored_data.get("language_index")
            language_name = stored_data.get("language_name")

            if language_index is None:
                try:
                    await query.answer("Session error. Please start again.", show_alert=True)
                except:
                    pass
                return

            languages = series.get("languages", [])
            if language_index >= len(languages):
                try:
                    await query.answer("Language not found.", show_alert=True)
                except:
                    pass
                return

            seasons = languages[language_index].get("seasons", [])
            season_layout = languages[language_index].get("season_layout", [1] * len(seasons))
            season_names = [season['name'] for season in seasons]
            text = base_text + f"○ **Language:** `{language_name}`\n\nSelect the season you need...!"
            layout = create_user_layout_from_pattern(season_names, season_layout, "season", add_back_button=True, back_target="language")

            try:
                if query.message.photo:
                    await query.message.edit_media(
                        media=InputMediaPhoto(media=query.message.photo.file_id, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                        reply_markup=InlineKeyboardMarkup(layout)
                    )
                else:
                    await query.message.edit_text(text=text, reply_markup=InlineKeyboardMarkup(layout), parse_mode=enums.ParseMode.MARKDOWN)
            except MessageNotModified:
                pass
            except Exception as e:
                logger.error(f"Error editing message: {e}")
            return

    # NORMAL clicks
    callback_parts = data.split("_")
    callback_type = callback_parts[0]
    try:
        callback_index = int(callback_parts[1])
    except (IndexError, ValueError):
        try:
            await query.answer("Invalid callback data.", show_alert=True)
        except:
            pass
        return

    if callback_type == "lang":
        languages = series.get("languages", [])
        if 0 <= callback_index < len(languages):
            language_name = languages[callback_index]["name"]

            user_requestor[f"{chat_id}•{message_id}"] = {
                "data": {
                    "series_key": series_key,
                    "language_name": language_name,
                    "language_index": callback_index,
                    "requested_user": requested_user
                },
                "timestamp": time.time()
            }
            request_timestamps[f"{chat_id}•{message_id}"] = time.time()

            seasons = languages[callback_index].get("seasons", [])
            season_layout = languages[callback_index].get("season_layout", [1] * len(seasons))
            season_names = [season['name'] for season in seasons]

            text = base_text + f"○ **Language:** `{language_name}`\nSelect the season you need...!"
            layout = create_user_layout_from_pattern(season_names, season_layout, "season", add_back_button=True, back_target="language")

            try:
                if query.message.photo:
                    await query.message.edit_media(
                        media=InputMediaPhoto(media=query.message.photo.file_id, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                        reply_markup=InlineKeyboardMarkup(layout)
                    )
                else:
                    await query.message.edit_text(text=text, reply_markup=InlineKeyboardMarkup(layout), parse_mode=enums.ParseMode.MARKDOWN)
            except MessageNotModified:
                pass
            except Exception as e:
                logger.error(f"Error editing message: {e}")
        else:
            try:
                await query.answer("Invalid selection.", show_alert=True)
            except:
                pass

    elif callback_type == "season":
        language_index = stored_data.get("language_index")
        if language_index is None:
            try:
                await query.answer("Session error. Please start again.", show_alert=True)
            except:
                pass
            return

        languages = series.get("languages", [])
        if language_index >= len(languages):
            try:
                await query.answer("Language not found.", show_alert=True)
            except:
                pass
            return

        seasons = languages[language_index].get("seasons", [])
        if 0 <= callback_index < len(seasons):
            season_name = seasons[callback_index]["name"]

            user_requestor[f"{chat_id}•{message_id}"] = {
                "data": {
                    "series_key": series_key,
                    "language_name": stored_data.get("language_name"),
                    "language_index": language_index,
                    "season_name": season_name,
                    "season_index": callback_index,
                    "requested_user": requested_user
                },
                "timestamp": time.time()
            }
            request_timestamps[f"{chat_id}•{message_id}"] = time.time()

            qualities = seasons[callback_index].get("qualities", [])
            text = base_text + f"○ **Language:** `{stored_data.get('language_name')}`\n○ **Season:** `{season_name}`\nSelect the quality you need...!"

            layout = []
            for quality in qualities:
                if quality.get("link_key"):
                    layout.append([InlineKeyboardButton(quality['name'], callback_data=f"b:{quality['link_key']}")])

            layout.append([InlineKeyboardButton("⬅️ Back", callback_data="back_season")])

            try:
                if query.message.photo:
                    await query.message.edit_media(
                        media=InputMediaPhoto(media=query.message.photo.file_id, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                        reply_markup=InlineKeyboardMarkup(layout)
                    )
                else:
                    await query.message.edit_text(text=text, reply_markup=InlineKeyboardMarkup(layout), parse_mode=enums.ParseMode.MARKDOWN)
            except MessageNotModified:
                pass
            except Exception as e:
                logger.error(f"Error editing message: {e}")
        else:
            try:
                await query.answer("Invalid selection.", show_alert=True)
            except:
                pass
