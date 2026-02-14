
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from bot import Bot
from pyrogram import Client, filters, enums
import asyncio
import re
import uuid
import logging
import os
import shutil
import requests
import json
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, 
    InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from pyrogram.errors import FloodWait, BadRequest, MessageIdInvalid, UserNotParticipant, ChatAdminRequired
from imdb import Cinemagoer
from fuzzywuzzy import fuzz

from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, TMDB_API_KEY, LOG_CHANNEL, DB_CHANNEL, RAW_DB_CHANNEL, NO_POSTER_FOUND_IMG
from database.crazy_db import (
    add_series, get_series_by_key, update_series_field, add_or_update_language,
    get_languages, delete_language, add_or_update_season, get_seasons, delete_season,
    add_or_update_quality, get_qualities, get_quality_link, delete_quality,
    get_poster_file_id, update_poster_file_id, publish_series, episodes_collection,
    get_series, get_poster_manuel, get_admin_channel, add_admin_assignment, 
    remove_admin_assignment, get_admin_assignments, series_collection
)
from utils import (
    get_message_id, get_messages, delete_messages_from_user_chat, 
    get_poster, find_most_similar_title, forward_messages_without_tag
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

temp_admin_data: Dict[int, Dict[str, Any]] = {}
imdb = Cinemagoer()
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

async def DeleteMessage(msg):
    await asyncio.sleep(600)
    try:
        await msg.delete()
    except Exception as e:
        logger.warning(f"Failed to delete message {msg.id}: {e}")

def create_dynamic_layout_from_pattern(items: List[str], layout_pattern: List[int], add_buttons: List[Tuple[str, str]] = None):
    """Create dynamic layout with add buttons for rows"""
    layout = []
    item_index = 0
    
    for row_index, row_count in enumerate(layout_pattern):
        if item_index >= len(items):
            break
        
        row = []
        items_in_this_row = 0
        for _ in range(row_count):
            if item_index < len(items):
                item_button = InlineKeyboardButton(items[item_index], callback_data=f"item_{item_index}")
                row.append(item_button)
                item_index += 1
                items_in_this_row += 1
        
        if items_in_this_row > 0:
            plus_button = InlineKeyboardButton("+", callback_data=f"add_to_row_{row_index}")
            row.append(plus_button)
            layout.append(row)
    
    while item_index < len(items):
        row = []
        item_button = InlineKeyboardButton(items[item_index], callback_data=f"item_{item_index}")
        row.append(item_button)
        plus_button = InlineKeyboardButton("+", callback_data=f"add_to_row_{len(layout)}")
        row.append(plus_button)
        layout.append(row)
        item_index += 1
    
    if items:
        next_row_index = len(layout)
        layout.append([InlineKeyboardButton("+ New Row", callback_data=f"add_to_row_{next_row_index}")])
    else:
        layout.append([InlineKeyboardButton("+ Add First Item", callback_data="add_to_row_0")])
    
    if add_buttons:
        for button_text, callback_data in add_buttons:
            layout.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
    
    return layout

def create_user_layout_from_pattern(items: List[str], layout_pattern: List[int]) -> List[List[InlineKeyboardButton]]:
    """Create user layout without add buttons"""
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
                item_button = InlineKeyboardButton(items[item_index], callback_data=f"user_item_{item_index}")
                row.append(item_button)
                item_index += 1
        
        if row:
            layout.append(row)
    
    while item_index < len(items):
        row = []
        for _ in range(min(2, len(items) - item_index)):
            item_button = InlineKeyboardButton(items[item_index], callback_data=f"user_item_{item_index}")
            row.append(item_button)
            item_index += 1
        layout.append(row)
    
    return layout

async def get_tmdb_info(query, bulk=False, tmdb_id=None, media_type=None):
    """Fetch information from TMDB API"""
    logger.info(f"Fetching TMDB info: query={query}, bulk={bulk}, tmdb_id={tmdb_id}, media_type={media_type}")
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {TMDB_API_KEY}"
    }

    try:
        if tmdb_id:
            url = f"{TMDB_BASE_URL}/{media_type}/{tmdb_id}"
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

            genres = [g['name'] for g in data.get('genres', [])][:3]
            poster_path = data.get('poster_path')
            poster_url = f"{TMDB_IMAGE_BASE_URL}{poster_path}" if poster_path else NO_POSTER_FOUND_IMG[0]

            if media_type == 'tv':
                title = data.get('name', 'N/A')
                year = f"{data.get('first_air_date', '').split('-')[0]} - {data.get('last_air_date', '').split('-')[0]}" if data.get('first_air_date') and data.get('last_air_date') else data.get('first_air_date', '').split('-')[0] if data.get('first_air_date') else 'N/A'
            else:
                title = data.get('title', 'N/A')
                year = data.get('release_date', '').split('-')[0] if data.get('release_date') else 'N/A'
            
            result = {
                'title': title,
                'year': year,
                'genres': ', '.join(genres) if genres else 'N/A',
                'rating': data.get('vote_average', 'N/A'),
                'poster_url': poster_url,
                'tmdb_id': data.get('id'),
                'media_type': media_type,
                'url': f'https://www.themoviedb.org/{media_type}/{data.get("id")}'
            }
            logger.info(f"Retrieved details for {title}")
            return result
        else:
            search_results = []
            
            # Search TV shows
            url_tv = f"{TMDB_BASE_URL}/search/tv"
            response_tv = requests.get(url_tv, headers=headers, params={"query": query})
            response_tv.raise_for_status()
            data_tv = response_tv.json()
            for item in data_tv.get('results', [])[:5]:
                if item.get('name'):
                    search_results.append({
                        'title': item.get('name'),
                        'year': item.get('first_air_date', '').split('-')[0] if item.get('first_air_date') else 'N/A',
                        'tmdb_id': item.get('id'),
                        'media_type': 'tv',
                        'source': 'tmdb'
                    })
            
            # Search movies
            url_movie = f"{TMDB_BASE_URL}/search/movie"
            response_movie = requests.get(url_movie, headers=headers, params={"query": query})
            response_movie.raise_for_status()
            data_movie = response_movie.json()
            for item in data_movie.get('results', [])[:5]:
                if item.get('title'):
                    search_results.append({
                        'title': item.get('title'),
                        'year': item.get('release_date', '').split('-')[0] if item.get('release_date') else 'N/A',
                        'tmdb_id': item.get('id'),
                        'media_type': 'movie',
                        'source': 'tmdb'
                    })
            
            logger.info(f"Found {len(search_results)} total results")
            return search_results[:10]

    except requests.exceptions.RequestException as e:
        logger.error(f"TMDB API error: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred with TMDB: {e}")
        return None

async def download_and_upload_poster(
    client: Bot,
    series_key: str,
    poster_url: str = None,
    message: Message = None,
    send_to_log_channel: bool = True
) -> Optional[str]:
    """Download, upload, and persist poster file_id"""
    logger.info("Downloading and uploading poster")
    temp_dir = os.path.join(TMP_DOWNLOAD_DIRECTORY, str(uuid.uuid4()))
    os.makedirs(temp_dir, exist_ok=True)
    file_id = None

    try:
        # --- Download logic (same as before) ---
        # ... [your existing download code here] ...

        # --- Upload ---
        if download_path:
            caption = "#MainPoster" if send_to_log_channel else "Series Poster"
            target_chat = LOG_CHANNEL if send_to_log_channel else ADMINS[0]

            sent_msg = await client.send_photo(
                chat_id=target_chat,
                photo=download_path,
                caption=caption
            )
            file_id = sent_msg.photo.file_id

            # Persist file_id in DB
            try:
                update_poster_file_id(series_key, file_id)
                logger.info(f"Poster file_id saved for series {series_key}")
            except Exception as e:
                logger.error(f"Failed to save poster file_id: {e}")

            # Clean up temp message
            try:
                await sent_msg.delete()
            except Exception:
                pass

    except Exception as e:
        logger.error(f"Poster handling failed: {e}")
        file_id = NO_POSTER_FOUND_IMG[0]

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return file_id or NO_POSTER_FOUND_IMG[0]

async def send_series_selection_message(client: Bot, user_id: int, query: str, results: list, message_id: int = None, mode: str = "new"):
    """Send series selection message"""
    logger.info(f"Sending series selection message to user {user_id} (mode: {mode})")
    prefix = "edit_" if mode == "edit" else ""
    text = f"**{'Select a series to edit:' if mode == 'edit' else 'Select a series from below:'}**Search query: `{query}`"
    
    buttons = []
    if mode == "edit":
        for series in results:
            button_text = f"{series.get('title', 'N/A')} ({series.get('released_on', 'N/A')})"
            callback_data = f"{prefix}sel_{series['_id']}"
            buttons.append(InlineKeyboardButton(button_text, callback_data=callback_data))
    else:
        for i, item in enumerate(results):
            unique_id = str(uuid.uuid4())
            temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
            temp_admin_data[user_id][unique_id] = {
                'id': item.get('tmdb_id') if item.get('source') == 'tmdb' else item.get('imdb_id'),
                'media_type': item.get('media_type'),
                'source': item.get('source'),
                'query': query
            }
            button_text = f"{item.get('title', 'N/A')} ({item.get('year', 'N/A')}) - {item.get('source', '').upper()}"
            buttons.append(InlineKeyboardButton(button_text, callback_data=f"{prefix}sel_{unique_id}"))
    
    buttons.append(InlineKeyboardButton("🔍 Search Again", callback_data=f"{prefix}search_again"))
    
    layout = [[button] for button in buttons]
    reply_markup = InlineKeyboardMarkup(layout)

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=NO_POSTER_FOUND_IMG[0], caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=reply_markup
            )
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=NO_POSTER_FOUND_IMG[0],
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            return msg.id
    except Exception as e:
        logger.error(f"Error sending series selection message: {e}")
        return None

async def send_series_details_message(client: Bot, user_id: int, series_data: dict, message_id: int = None, mode: str = "new"):
    """Send series details message with poster handling"""
    logger.info(f"Sending series details message to user {user_id} (mode: {mode})")
    prefix = "edit_" if mode == "edit" else ""
    series_key = series_data['_id']

    # Try to get stored poster
    poster_file_id = get_poster_file_id(series_key)
    if not poster_file_id:
        logger.warning("No poster file_id found, attempting to fetch again")
        poster_file_id = await download_and_upload_poster(
            client,
            poster_url=series_data.get("poster_url")
        ) or NO_POSTER_FOUND_IMG[0]

    text = (
        f"○ **Title:** `{series_data.get('title', 'N/A')}`\n"
        f"○ **Released On:** `{series_data.get('released_on', 'N/A')}`\n"
        f"○ **Genre:** `{series_data.get('genre', 'N/A')}`\n"
        f"○ **Rating:** `{series_data.get('rating', 'N/A')}`\n"
        f"○ **Media Type:** `{series_data.get('media_type', 'N/A').upper()}`"
    )

    if mode == "edit":
        text += f"\n○ **Published:** `{'✅' if series_data.get('published', False) else '❌'}`"

    buttons = [
        InlineKeyboardButton("🌐 Languages", callback_data=f"{prefix}manage_languages"),
        InlineKeyboardButton("🖼️ Poster", callback_data=f"{prefix}change_poster"),
    ]
    if mode == "edit":
        if not series_data.get('published', False):
            buttons.append(InlineKeyboardButton("📤 Publish", callback_data=f"{prefix}publish_series"))
        else:
            buttons.append(InlineKeyboardButton("📝 Update", callback_data=f"{prefix}update_series"))
    else:
        buttons.append(InlineKeyboardButton("📤 Publish", callback_data=f"{prefix}publish_series"))

    layout = [[buttons[0]], [buttons[1], buttons[2]]]
    reply_markup = InlineKeyboardMarkup(layout)

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=poster_file_id, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=reply_markup
            )
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_file_id,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            return msg.id
    except Exception as e:
        logger.error(f"Error sending series details message: {e}")
        return None

async def send_language_management_message(client: Bot, user_id: int, series_key: str, message_id: int, mode: str = "new"):
    """Send language management message"""
    logger.info(f"Sending language management message to user {user_id} (mode: {mode})")
    prefix = "edit_" if mode == "edit" else ""
    series_data = get_series_by_key(series_key)
    if not series_data:
        logger.warning(f"Series not found for key: {series_key}")
        await client.send_message(user_id, "Series not found.")
        return

    languages = series_data.get("languages", [])
    language_layout = series_data.get("language_layout", [])
    
    text = f"**Series:** `{series_data.get('title', 'N/A')}`"
    text += "Select any Language group to add new Season/Part group inside them. Or click '+' button to add new Language group."

    language_names = [lang['name'] for lang in languages]
    
    add_buttons = [
        ("⬅️ Back", f"{prefix}back_to_series")
    ]
    
    layout = create_dynamic_layout_from_pattern(language_names, language_layout, add_buttons)
    reply_markup = InlineKeyboardMarkup(layout)
    
    poster_to_use = series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG[0]

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=poster_to_use, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=reply_markup
            )
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_to_use,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            return msg.id
    except Exception as e:
        logger.error(f"Error sending language management message: {e}")
        return None

async def send_season_management_message(client: Bot, user_id: int, series_key: str, language_name: str, message_id: int, mode: str = "new"):
    """Send season management message"""
    logger.info(f"Sending season management message to user {user_id} (mode: {mode})")
    prefix = "edit_" if mode == "edit" else ""
    series_data = get_series_by_key(series_key)
    if not series_data:
        logger.warning(f"Series not found for key: {series_key}")
        await client.send_message(user_id, "Series not found.")
        return

    current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
    if not current_lang:
        await client.send_message(user_id, "Language not found.")
        return

    seasons = current_lang.get("seasons", [])
    season_layout = current_lang.get("season_layout", [])
    
    text = (
        f"**Series:** `{series_data.get('title', 'N/A')}`"        f"**Language:** `{language_name}`"
        "Select any Seasons group to add new Quality group into them. Or click '+' button to add new Seasons group."
    )

    season_names = [season['name'] for season in seasons]
    
    add_buttons = [
        ("🖼️ Change Poster for this Language", f"{prefix}change_lang_poster"),
        (f"🗑️ Delete '{language_name}' Group", f"{prefix}delete_language"),
        ("⬅️ Back", f"{prefix}back_to_languages")
    ]
    
    layout = create_dynamic_layout_from_pattern(season_names, season_layout, add_buttons)
    reply_markup = InlineKeyboardMarkup(layout)
    
    poster_to_use = current_lang.get("poster_file_id") or series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG[0]

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=poster_to_use, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=reply_markup
            )
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_to_use,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            return msg.id
    except Exception as e:
        logger.error(f"Error sending season management message: {e}")
        return None

async def send_quality_management_message(client: Bot, user_id: int, series_key: str, language_name: str, season_name: str, message_id: int, mode: str = "new"):
    """Send quality management message"""
    logger.info(f"Sending quality management message to user {user_id} (mode: {mode})")
    prefix = "edit_" if mode == "edit" else ""
    series_data = get_series_by_key(series_key)
    if not series_data:
        logger.warning(f"Series not found for key: {series_key}")
        await client.send_message(user_id, "Series not found.")
        return

    current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
    current_season = next((s for s in current_lang.get("seasons", []) if s["name"].lower() == season_name.lower()), None) if current_lang else None
    if not current_season:
        await client.send_message(user_id, "Season not found.")
        return

    qualities = current_season.get("qualities", [])
    quality_layout = current_season.get("quality_layout", [])
    
    text = (
        f"**Series:** `{series_data.get('title', 'N/A')}`"
        f"**Language:** `{language_name}`"
        f"**Season:** `{season_name}`"
        "Select any Quality group to add new files into them. Or click '+' button to add new Quality group."
    )

    quality_names = [quality['name'] for quality in qualities]
    
    add_buttons = [
        ("🖼️ Change Poster for this Season", f"{prefix}change_season_poster"),
        (f"🗑️ Delete '{season_name}' Group", f"{prefix}delete_season"),
        ("⬅️ Back", f"{prefix}back_to_seasons")
    ]
    
    layout = create_dynamic_layout_from_pattern(quality_names, quality_layout, add_buttons)
    reply_markup = InlineKeyboardMarkup(layout)
    
    poster_to_use = current_season.get("poster_file_id") or current_lang.get("poster_file_id") or series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG[0]

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=poster_to_use, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=reply_markup
            )
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_to_use,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            return msg.id
    except Exception as e:
        logger.error(f"Error sending quality management message: {e}")
        return None

async def forward_messages_without_tag_with_retry(
    client: Bot, 
    source_channel_id: int, 
    target_channel_id: int, 
    first_msg_id: int, 
    last_msg_id: int,
    progress_msg: Message = None
):
    """Forward messages without forward tag with comprehensive error handling"""
    new_message_ids = []
    total_messages = last_msg_id - first_msg_id + 1
    processed = 0
    failed = 0
    
    logger.info(f"Forwarding {total_messages} messages from {source_channel_id} to {target_channel_id}")
    
    for msg_id in range(first_msg_id, last_msg_id + 1):
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                try:
                    msg = await client.get_messages(source_channel_id, msg_id)
                except MessageIdInvalid:
                    logger.warning(f"Message {msg_id} is invalid, skipping")
                    failed += 1
                    break
                except Exception as e:
                    logger.error(f"Error getting message {msg_id}: {e}")
                    if retry_count < max_retries - 1:
                        retry_count += 1
                        await asyncio.sleep(2)
                        continue
                    else:
                        failed += 1
                        break
                
                if not msg or msg.empty:
                    logger.warning(f"Message {msg_id} is empty, skipping")
                    failed += 1
                    break
                
                try:
                    copied_msg = await msg.copy(
                        chat_id=target_channel_id,
                        caption=msg.caption if msg.caption else None,
                        parse_mode=enums.ParseMode.HTML if msg.caption else None
                    )
                    new_message_ids.append(copied_msg.id)
                    processed += 1
                    
                    if progress_msg and processed % 5 == 0:
                        try:
                            await progress_msg.edit_text(
                                f"⏳ Forwarding files... Progress: {processed}/{total_messages} ({failed} failed)"
                            )
                        except Exception:
                            pass
                    
                    await asyncio.sleep(0.5)
                    break
                    
                except FloodWait as e:
                    logger.warning(f"FloodWait encountered: {e.value} seconds")
                    if progress_msg:
                        try:
                            await progress_msg.edit_text(
                                f"⏳ Rate limit hit. Waiting {e.value} seconds... Progress: {processed}/{total_messages}"
                            )
                        except Exception:
                            pass
                    await asyncio.sleep(e.value)
                    retry_count += 1
                    
                except BadRequest as e:
                    logger.error(f"BadRequest copying message {msg_id}: {str(e)}")
                    if retry_count < max_retries - 1:
                        retry_count += 1
                        await asyncio.sleep(2)
                        continue
                    else:
                        failed += 1
                        break
                        
                except Exception as e:
                    logger.error(f"Error copying message {msg_id}: {str(e)}")
                    if retry_count < max_retries - 1:
                        retry_count += 1
                        await asyncio.sleep(2)
                        continue
                    else:
                        failed += 1
                        break
                        
            except Exception as e:
                logger.error(f"Unexpected error processing message {msg_id}: {str(e)}")
                if retry_count < max_retries - 1:
                    retry_count += 1
                    await asyncio.sleep(2)
                    continue
                else:
                    failed += 1
                    break
    
    if progress_msg:
        try:
            await progress_msg.edit_text(
                f"✅ Forwarding complete! Successfully forwarded: {processed}/{total_messages} Failed: {failed}"
            )
        except Exception:
            pass
    
    logger.info(f"Forwarding complete: {processed} successful, {failed} failed")
    return new_message_ids if new_message_ids else None

async def process_language_input(client: Client, message: Message, language_name: str, mode: str = "new"):
    """Process language input"""
    user_id = message.from_user.id
    prefix = "EDIT_" if mode == "edit" else ""
    series_key = temp_admin_data[user_id].get("current_series_key")
    target_row = temp_admin_data[user_id].get("target_row")
    
    if "ask_message_id" in temp_admin_data[user_id]:
        try:
            await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
        except Exception:
            pass
    
    confirm_msg = await message.reply("Language Added")
    
    series_data = get_series_by_key(series_key)
    if not series_data:
        await message.reply("Series not found.")
        return
    
    languages = series_data.get("languages", [])
    current_layout = series_data.get("language_layout", [])
    
    existing_language = next((lang for lang in languages if lang["name"].lower() == language_name.lower()), None)
    if existing_language:
        await message.reply(f"Language '{language_name}' already exists.")
        return
    
    while len(current_layout) <= target_row:
        current_layout.append(0)
    
    insertion_index = sum(current_layout[:target_row]) + current_layout[target_row]
    
    new_language = {"name": language_name, "seasons": [], "season_layout": []}
    languages.insert(insertion_index, new_language)
    current_layout[target_row] += 1
    
    try:
        result = series_collection.update_one(
            {"_id": series_key},
            {"$set": {"languages": languages, "language_layout": current_layout}}
        )
        if result.modified_count > 0:
            main_message_id = temp_admin_data[user_id].get("main_message_id")
            await send_language_management_message(client, user_id, series_key, main_message_id, mode)
            asyncio.create_task(DeleteMessage(confirm_msg))
        else:
            await message.reply("Failed to add language. Please try again.")
    except Exception as e:
        logger.error(f"Error adding language: {e}")
        await message.reply(f"Error adding language: {e}")

async def process_season_input(client: Bot, message: Message, season_name: str, mode: str = "new"):
    """Process season input"""
    user_id = message.from_user.id
    prefix = "EDIT_" if mode == "edit" else ""
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    target_row = temp_admin_data[user_id].get("target_row")
    
    if "ask_message_id" in temp_admin_data[user_id]:
        try:
            await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
        except Exception:
            pass
    
    confirm_msg = await message.reply("Season Added")
    
    series_data = get_series_by_key(series_key)
    if not series_data:
        await message.reply("Series not found.")
        return
    
    languages = series_data.get("languages", [])
    current_lang = next((lang for lang in languages if lang["name"].lower() == language_name.lower()), None)
    if not current_lang:
        await message.reply("Language not found.")
        return
    
    seasons = current_lang.get("seasons", [])
    current_layout = current_lang.get("season_layout", [])
    
    existing_season = next((s for s in seasons if s["name"].lower() == season_name.lower()), None)
    if existing_season:
        await message.reply(f"Season '{season_name}' already exists.")
        return
    
    while len(current_layout) <= target_row:
        current_layout.append(0)
    
    insertion_index = sum(current_layout[:target_row]) + current_layout[target_row]
    
    new_season = {"name": season_name, "qualities": [], "quality_layout": []}
    seasons.insert(insertion_index, new_season)
    current_layout[target_row] += 1
    
    try:
        result = series_collection.update_one(
            {"_id": series_key},
            {"$set": {"languages": languages}}
        )
        if result.modified_count > 0:
            main_message_id = temp_admin_data[user_id].get("main_message_id")
            await send_season_management_message(client, user_id, series_key, language_name, main_message_id, mode)
            asyncio.create_task(DeleteMessage(confirm_msg))
        else:
            await message.reply("Failed to add season. Please try again.")
    except Exception as e:
        logger.error(f"Error adding season: {e}")
        await message.reply(f"Error adding season: {e}")

async def process_quality_input(client: Bot, message: Message, quality_name: str, mode: str = "new"):
    """Process quality input"""
    user_id = message.from_user.id
    prefix = "EDIT_" if mode == "edit" else ""
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    target_row = temp_admin_data[user_id].get("target_row")
    
    if "ask_message_id" in temp_admin_data[user_id]:
        try:
            await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
        except Exception:
            pass
    
    confirm_msg = await message.reply("Quality Added")
    
    series_data = get_series_by_key(series_key)
    if not series_data:
        await message.reply("Series not found.")
        return
    
    languages = series_data.get("languages", [])
    current_lang = next((lang for lang in languages if lang["name"].lower() == language_name.lower()), None)
    if not current_lang:
        await message.reply("Language not found.")
        return
    
    seasons = current_lang.get("seasons", [])
    current_season = next((s for s in seasons if s["name"].lower() == season_name.lower()), None)
    if not current_season:
        await message.reply("Season not found.")
        return
    
    qualities = current_season.get("qualities", [])
    current_layout = current_season.get("quality_layout", [])
    
    existing_quality = next((q for q in qualities if q["name"].lower() == quality_name.lower()), None)
    if existing_quality:
        await message.reply(f"Quality '{quality_name}' already exists.")
        return
    
    while len(current_layout) <= target_row:
        current_layout.append(0)
    
    insertion_index = sum(current_layout[:target_row]) + current_layout[target_row]
    
    new_quality = {"name": quality_name}
    qualities.insert(insertion_index, new_quality)
    current_layout[target_row] += 1
    
    try:
        result = series_collection.update_one(
            {"_id": series_key},
            {"$set": {"languages": languages}}
        )
        if result.modified_count > 0:
            main_message_id = temp_admin_data[user_id].get("main_message_id")
            await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id, mode)
            asyncio.create_task(DeleteMessage(confirm_msg))
        else:
            await message.reply("Failed to add quality. Please try again.")
    except Exception as e:
        logger.error(f"Error adding quality: {e}")
        await message.reply(f"Error adding quality: {e}")

async def process_poster_input(client: Bot, message: Message, poster_type: str, mode: str = "new"):
    """Process poster input"""
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    
    poster_file_id = await download_and_upload_poster(client, message=message, send_to_log_channel=(poster_type == "series"))
    
    if not poster_file_id:
        await message.reply("Failed to process the poster. Please try again.")
        return
    
    if poster_type == "series":
        if update_poster_file_id(series_key, poster_file_id):
            await message.reply("Series poster updated successfully.")
        else:
            await message.reply("Failed to update series poster. Please try again.")
    elif poster_type == "language":
        if add_or_update_language(series_key, language_name, poster_file_id):
            await message.reply("Language poster updated successfully.")
        else:
            await message.reply("Failed to update language poster. Please try again.")
    elif poster_type == "season":
        if add_or_update_season(series_key, language_name, season_name, poster_file_id):
            await message.reply("Season poster updated successfully.")
        else:
            await message.reply("Failed to update season poster. Please try again.")
    
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    if poster_type == "series":
        await send_series_details_message(client, user_id, get_series_by_key(series_key), main_message_id, mode)
    elif poster_type == "language":
        await send_season_management_message(client, user_id, series_key, language_name, main_message_id, mode)
    elif poster_type == "season":
        await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id, mode)

async def process_first_file_input(client: Bot, message: Message, mode: str = "new"):
    """Process first file input"""
    user_id = message.from_user.id
    channel_id, msg_id = await get_message_id(client, message)
    if channel_id == 0 or msg_id == 0:
        await message.reply("Invalid message. Please forward a message from a channel.")
        return

    temp_admin_data[user_id]["source_channel_id"] = channel_id
    temp_admin_data[user_id]["source_first_msg_id"] = msg_id

    if "ask_message_id" in temp_admin_data[user_id]:
        try:
            await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
        except Exception:
            pass

    ask_msg = await client.send_message(
        user_id,
        "Forward me the last file (with tag) for this quality:"
    )
    state_prefix = "EDIT_" if mode == "edit" else ""
    temp_admin_data[user_id]["state"] = f"{state_prefix}AWAITING_LAST_FILE"
    temp_admin_data[user_id]["ask_message_id"] = ask_msg.id

async def process_last_file_input(client: Bot, message: Message, mode: str = "new"):
    """Process last file input"""
    user_id = message.from_user.id
    channel_id, msg_id = await get_message_id(client, message)
    if channel_id == 0 or msg_id == 0:
        await message.reply("Invalid message. Please forward a message from a channel.")
        return

    source_channel_id = temp_admin_data[user_id].get("source_channel_id")
    source_first_msg_id = temp_admin_data[user_id].get("source_first_msg_id")

    if not source_channel_id or not source_first_msg_id:
        await message.reply("First file information not found. Please start over.")
        return

    if channel_id != source_channel_id:
        await message.reply("The first and last files must be from the same channel.")
        return

    assigned_channel_id = get_admin_channel(user_id)
    if not assigned_channel_id:
        await message.reply("You don't have an assigned channel. Please contact the bot owner.")
        return

    progress_msg = await message.reply("⏳ Forwarding files to assigned channel. Please wait...")
    
    try:
        new_message_ids = await forward_messages_without_tag_with_retry(
            client, source_channel_id, assigned_channel_id, source_first_msg_id, msg_id, progress_msg
        )

        if not new_message_ids:
            await progress_msg.edit_text("❌ Failed to forward files. Please try again.")
            return

        new_first_msg_id = new_message_ids[0]
        new_last_msg_id = new_message_ids[-1]

        channel_id_str = str(assigned_channel_id)
        clean_channel_id = channel_id_str[4:] if channel_id_str.startswith("-100") else channel_id_str
        link_key = f"get_{clean_channel_id}_{new_first_msg_id}_{new_last_msg_id}"

        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        quality_name = temp_admin_data[user_id].get("current_quality")

        if not all([series_key, language_name, season_name, quality_name]):
            await progress_msg.edit_text("❌ Session expired. Please start over.")
            return

        max_retries = 3
        for attempt in range(max_retries):
            try:
                if add_or_update_quality(series_key, language_name, season_name, quality_name, link_key):
                    await progress_msg.edit_text(f"✅ Quality '{quality_name}' updated successfully with {len(new_message_ids)} files.")
                    main_message_id = temp_admin_data[user_id].get("main_message_id")
                    await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id, mode)
                    break
                else:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2)
                        continue
                    else:
                        await progress_msg.edit_text("❌ Failed to update quality after multiple attempts. Please try again.")
            except Exception as e:
                logger.error(f"Error updating quality (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                    continue
                else:
                    await progress_msg.edit_text(f"❌ Error updating quality: {str(e)}")
                    
    except FloodWait as e:
        logger.warning(f"FloodWait encountered in process_last_file_input: {e.value} seconds")
        await progress_msg.edit_text(f"⏳ Telegram rate limit hit. Waiting {e.value} seconds...")
        await asyncio.sleep(e.value)
        await progress_msg.edit_text("🔄 Retrying operation...")
        await process_last_file_input(client, message, mode)
    except Exception as e:
        logger.error(f"Unexpected error in process_last_file_input: {e}")
        await progress_msg.edit_text(f"❌ An unexpected error occurred: {str(e)}")

async def unified_callback_handler(client: Bot, callback_query: CallbackQuery):
    """Unified callback handler for both new and edit modes"""
    user_id = callback_query.from_user.id
    data = callback_query.data
    logger.info(f"Processing callback: {data}")
    
    # Determine mode from callback prefix
    mode = "edit" if data.startswith("edit_") else "new"
    prefix = "edit_" if mode == "edit" else ""
    
    if user_id not in temp_admin_data:
        logger.warning(f"Admin {user_id} not in temp_admin_data")
        try:
            await callback_query.answer("Session expired. Please start again.", show_alert=True)
        except:
            pass
        return
    
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    
    try:
        await callback_query.answer()
    except Exception as e:
        logger.warning(f"Failed to acknowledge callback: {e}")
    
    # Handle series selection
    if data.startswith(f"{prefix}sel_"):
        if mode == "edit":
            series_key = data.split("_", 2)[2]
            series_data = get_series_by_key(series_key)
            if not series_data:
                try:
                    await callback_query.answer("Series not found.", show_alert=True)
                except:
                    pass
                return
            temp_admin_data[user_id]["current_series_key"] = series_key
            temp_admin_data[user_id]["state"] = f"{prefix.upper()}SERIES_DETAILS"
            await send_series_details_message(client, user_id, series_data, main_message_id, mode)
        else:
            unique_id = data.split("_", 1)[1]
            if unique_id not in temp_admin_data[user_id]:
                try:
                    await callback_query.answer("Invalid selection.", show_alert=True)
                except:
                    pass
                return
            
            stored_data = temp_admin_data[user_id].pop(unique_id)
            media_id = stored_data['id']
            media_type = stored_data['media_type']
            source = stored_data['source']
            query = stored_data['query']
            
            movie_details = None
            if source == 'tmdb':
                movie_details = await get_tmdb_info(query=None, tmdb_id=media_id, media_type=media_type)
            elif source == 'imdb':
                movie_details = await get_poster(media_id, id=True)
            
            if not movie_details:
                try:
                    await client.edit_message_caption(
                        chat_id=user_id,
                        message_id=main_message_id,
                        caption=f"Failed to retrieve {source.upper()} data. Please try again."
                    )
                except Exception as e:
                    logger.error(f"Failed to edit message: {e}")
                return
            
            series_key = movie_details.get('title', 'N/A').lower().replace(" ", "").replace("-", "")
            
            existing_series = get_series_by_key(series_key)
            if existing_series:
                series_data = existing_series
                try:
                    await callback_query.answer("Series already exists. Loading for editing.", show_alert=True)
                except:
                    pass
            else:
                poster_file_id = None
                if movie_details.get('poster_url'):
                    poster_file_id = await download_and_upload_poster(client, poster_url=movie_details.get('poster_url'))
                
                series_data = {
                    '_id': series_key,
                    'title': movie_details.get('title', 'N/A'),
                    'released_on': movie_details.get('year', 'N/A'),
                    'genre': movie_details.get('genres', 'N/A'),
                    'rating': movie_details.get('rating', 'N/A'),
                    'tmdb_id': movie_details.get('tmdb_id') if source == 'tmdb' else None,
                    'imdb_id': movie_details.get('imdb_id') if source == 'imdb' else None,
                    'media_type': media_type,
                    'poster_file_id': poster_file_id,
                    'languages': [],
                    'language_layout': [],
                    'published': False
                }
                if not add_series(series_data):
                    try:
                        await callback_query.answer("Failed to add new series. Loading existing series.", show_alert=True)
                    except:
                        pass
                    series_data = get_series_by_key(series_key)
                    if not series_data:
                        try:
                            await client.edit_message_caption(
                                chat_id=user_id,
                                message_id=main_message_id,
                                caption="Failed to create or load series. Please try again."
                            )
                        except Exception as e:
                            logger.error(f"Failed to edit message: {e}")
                        return
            
            series_data = get_series_by_key(series_key)
            if not series_data:
                try:
                    await client.edit_message_caption(
                        chat_id=user_id,
                        message_id=main_message_id,
                        caption="Failed to retrieve series data. Please try again."
                    )
                except Exception as e:
                    logger.error(f"Failed to edit message: {e}")
                return
            
            temp_admin_data[user_id]["current_series_key"] = series_key
            temp_admin_data[user_id]["state"] = "SERIES_DETAILS"
            await send_series_details_message(client, user_id, series_data, main_message_id, mode)
    
    # Handle navigation
    elif data == f"{prefix}search_again":
        query = temp_admin_data[user_id].get("query")
        if mode == "edit":
            all_series = get_series()
            matches = []
            if all_series and query:
                for series in all_series:
                    title = series.get('title', '')
                    similarity = fuzz.partial_ratio(query.lower(), title.lower())
                    if similarity > 70:
                        matches.append((series, similarity))
                matches.sort(key=lambda x: x[1], reverse=True)
                matched_series = [match[0] for match in matches[:10]]
            else:
                matched_series = all_series[:10] if all_series else []
            
            if matched_series:
                await send_series_selection_message(client, user_id, query, matched_series, main_message_id, mode)
            else:
                await callback_query.answer("No matching series found.", show_alert=True)
        else:
            search_results = temp_admin_data[user_id].get("search_results", [])
            if query and search_results:
                await send_series_selection_message(client, user_id, query, search_results, main_message_id, mode)
            else:
                await callback_query.answer("No previous search data found.", show_alert=True)
    
    elif data == f"{prefix}back_to_series":
        series_key = temp_admin_data[user_id].get("current_series_key")
        series_data = get_series_by_key(series_key)
        if series_data:
            temp_admin_data[user_id]["state"] = f"{prefix.upper()}SERIES_DETAILS"
            await send_series_details_message(client, user_id, series_data, main_message_id, mode)
    
    elif data == f"{prefix}manage_languages":
        series_key = temp_admin_data[user_id].get("current_series_key")
        temp_admin_data[user_id]["state"] = f"{prefix.upper()}MANAGE_LANGUAGES"
        await send_language_management_message(client, user_id, series_key, main_message_id, mode)
    
    elif data.startswith(f"{prefix}add_to_row_"):
        row_index = int(data.split("_")[-1])
        current_state = temp_admin_data[user_id].get("state")
        
        if "MANAGE_LANGUAGES" in current_state:
            temp_admin_data[user_id]["target_row"] = row_index
            
            if "ask_message_id" in temp_admin_data[user_id]:
                try:
                    await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
                except Exception:
                    pass
            
            ask_msg = await client.send_message(
                user_id,
                f"Send language name to add to row {row_index + 1}:"
            )
            temp_admin_data[user_id]["state"] = f"{prefix.upper()}AWAITING_LANGUAGE_INPUT"
            temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
            
        elif "MANAGE_SEASONS" in current_state:
            temp_admin_data[user_id]["target_row"] = row_index
            
            if "ask_message_id" in temp_admin_data[user_id]:
                try:
                    await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
                except Exception:
                    pass
            
            ask_msg = await client.send_message(
                user_id,
                f"Send season name to add to row {row_index + 1}:"
            )
            temp_admin_data[user_id]["state"] = f"{prefix.upper()}AWAITING_SEASON_INPUT"
            temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
            
        elif "MANAGE_QUALITIES" in current_state:
            temp_admin_data[user_id]["target_row"] = row_index
            
            if "ask_message_id" in temp_admin_data[user_id]:
                try:
                    await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
                except Exception:
                    pass
            
            ask_msg = await client.send_message(
                user_id,
                f"Send quality name to add to row {row_index + 1}:"
            )
            temp_admin_data[user_id]["state"] = f"{prefix.upper()}AWAITING_QUALITY_INPUT"
            temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
    
    elif data.startswith(f"{prefix}item_"):
        item_index = int(data.split("_")[1])
        current_state = temp_admin_data[user_id].get("state")
        
        if "MANAGE_LANGUAGES" in current_state:
            series_key = temp_admin_data[user_id].get("current_series_key")
            languages = get_languages(series_key)
            
            if 0 <= item_index < len(languages):
                language_name = languages[item_index]["name"]
                temp_admin_data[user_id]["current_language"] = language_name
                temp_admin_data[user_id]["current_language_index"] = item_index
                temp_admin_data[user_id]["state"] = f"{prefix.upper()}MANAGE_SEASONS"
                await send_season_management_message(client, user_id, series_key, language_name, main_message_id, mode)
                
        elif "MANAGE_SEASONS" in current_state:
            series_key = temp_admin_data[user_id].get("current_series_key")
            language_name = temp_admin_data[user_id].get("current_language")
            seasons = get_seasons(series_key, language_name)
            
            if 0 <= item_index < len(seasons):
                season_name = seasons[item_index]["name"]
                temp_admin_data[user_id]["current_season"] = season_name
                temp_admin_data[user_id]["current_season_index"] = item_index
                temp_admin_data[user_id]["state"] = f"{prefix.upper()}MANAGE_QUALITIES"
                await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id, mode)
                
        elif "MANAGE_QUALITIES" in current_state:
            series_key = temp_admin_data[user_id].get("current_series_key")
            language_name = temp_admin_data[user_id].get("current_language")
            season_name = temp_admin_data[user_id].get("current_season")
            qualities = get_qualities(series_key, language_name, season_name)
            
            if 0 <= item_index < len(qualities):
                quality_name = qualities[item_index]["name"]
                link_key = qualities[item_index].get("link_key")
                
                if link_key:
                    temp_admin_data[user_id]["current_quality"] = quality_name
                    temp_admin_data[user_id]["current_quality_index"] = item_index
                    temp_admin_data[user_id]["state"] = f"{prefix.upper()}QUALITY_OPTIONS"
                    
                    text = f"Quality '{quality_name}' already has files. What would you like to do?"
                    buttons = [
                        [InlineKeyboardButton("🔄 Re-Add Files", callback_data=f"{prefix}readd_quality")],
                        [InlineKeyboardButton("🗑️ Delete Quality", callback_data=f"{prefix}delete_quality")],
                        [InlineKeyboardButton("❌ Cancel", callback_data=f"{prefix}cancel_quality")]
                    ]
                    reply_markup = InlineKeyboardMarkup(buttons)
                    
                    try:
                        await client.edit_message_caption(
                            chat_id=user_id,
                            message_id=main_message_id,
                            caption=text,
                            reply_markup=reply_markup
                        )
                    except Exception as e:
                        logger.error(f"Error showing quality options: {e}")
                else:
                    temp_admin_data[user_id]["current_quality"] = quality_name
                    temp_admin_data[user_id]["current_quality_index"] = item_index
                    temp_admin_data[user_id]["state"] = f"{prefix.upper()}AWAITING_FIRST_FILE"
                    
                    if "ask_message_id" in temp_admin_data[user_id]:
                        try:
                            await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
                        except Exception:
                            pass
                    
                    ask_msg = await client.send_message(
                        user_id,
                        f"Forward me the first file (with tag) for {language_name}-{season_name}-{quality_name}"
                    )
                    temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
    
    elif data == f"{prefix}back_to_languages":
        series_key = temp_admin_data[user_id].get("current_series_key")
        temp_admin_data[user_id]["state"] = f"{prefix.upper()}MANAGE_LANGUAGES"
        await send_language_management_message(client, user_id, series_key, main_message_id, mode)
    
    elif data == f"{prefix}back_to_seasons":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        temp_admin_data[user_id]["state"] = f"{prefix.upper()}MANAGE_SEASONS"
        await send_season_management_message(client, user_id, series_key, language_name, main_message_id, mode)
    
    elif data == f"{prefix}change_poster":
        temp_admin_data[user_id]["state"] = f"{prefix.upper()}AWAITING_SERIES_POSTER"
        await client.send_message(user_id, "Please send a photo or video to use as the series poster:")
    
    elif data == f"{prefix}change_lang_poster":
        language_name = temp_admin_data[user_id].get("current_language")
        temp_admin_data[user_id]["state"] = f"{prefix.upper()}AWAITING_LANGUAGE_POSTER"
        await client.send_message(user_id, f"Please send a photo or video to use as the poster for {language_name}:")
    
    elif data == f"{prefix}change_season_poster":
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        temp_admin_data[user_id]["state"] = f"{prefix.upper()}AWAITING_SEASON_POSTER"
        await client.send_message(user_id, f"Please send a photo or video to use as the poster for {language_name}-{season_name}:")
    
    elif data == f"{prefix}delete_language":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        
        if delete_language(series_key, language_name):
            await client.send_message(user_id, f"Language '{language_name}' deleted successfully.")
            await send_language_management_message(client, user_id, series_key, main_message_id, mode)
        else:
            await client.send_message(user_id, f"Failed to delete language '{language_name}'.")
    
    elif data == f"{prefix}delete_season":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        
        if delete_season(series_key, language_name, season_name):
            await client.send_message(user_id, f"Season '{season_name}' deleted successfully.")
            await send_season_management_message(client, user_id, series_key, language_name, main_message_id, mode)
        else:
            await client.send_message(user_id, f"Failed to delete season '{season_name}'.")
    
    # Handle publish/update
    elif data == f"{prefix}publish_series":
        series_key = temp_admin_data[user_id].get("current_series_key")
        
        if mode == "edit":
            text = (
                "Do you want to publish this series?"
                "NOTE: Once published, it will be visible to users."
            )
        else:
            text = (
                "Do you want to publish this series?"
                "NOTE: Once you publish this series, you can't edit it anymore."
                "All the empty groups will be removed automatically."
            )
        
        buttons = [
            [InlineKeyboardButton("✅ Yes", callback_data=f"{prefix}confirm_publish")],
            [InlineKeyboardButton("❌ No", callback_data=f"{prefix}cancel_publish")]
        ]
        
        reply_markup = InlineKeyboardMarkup(buttons)
        
        try:
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption=text,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error showing publish confirmation: {e}")
    
    elif data == f"{prefix}update_series":
        series_key = temp_admin_data[user_id].get("current_series_key")
        
        text = (
            "Do you want to update this series' metadata?"
            "NOTE: This will only update the metadata (title, poster, etc.) "
            "without affecting the published status or file links."
        )
        
        buttons = [
            [InlineKeyboardButton("✅ Yes, Update", callback_data=f"{prefix}confirm_update")],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"{prefix}cancel_update")]
        ]
        
        reply_markup = InlineKeyboardMarkup(buttons)
        
        try:
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption=text,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error showing update confirmation: {e}")
    
    elif data == f"{prefix}confirm_publish":
        series_key = temp_admin_data[user_id].get("current_series_key")
        
        if mode == "edit":
            # For edit mode, clean up empty groups but keep all file links
            series = series_collection.find_one({"_id": series_key})
            if not series:
                await callback_query.message.edit_caption("❌ Series not found.")
                return

            cleaned_languages = []
            for lang in series.get("languages", []):
                cleaned_seasons = []
                for season in lang.get("seasons", []):
                    cleaned_qualities = []
                    for quality in season.get("qualities", []):
                        if quality.get("link_key"):
                            cleaned_qualities.append(quality)
                    if cleaned_qualities:
                        season["qualities"] = cleaned_qualities
                        cleaned_seasons.append(season)
                if cleaned_seasons:
                    lang["seasons"] = cleaned_seasons
                    cleaned_languages.append(lang)
            
            try:
                result = series_collection.update_one(
                    {"_id": series_key},
                    {"$set": {
                        "languages": cleaned_languages,
                        "published": True
                    }}
                )
                if result.modified_count > 0:
                    await callback_query.message.edit_caption("✅ Published Successfully")
                    series_data = get_series_by_key(series_key)
                    await send_series_details_message(client, user_id, series_data, main_message_id, mode)
                else:
                    await callback_query.message.edit_caption("❌ Failed to publish series. Please try again.")
            except Exception as e:
                logger.error(f"Error publishing series: {e}")
                await callback_query.message.edit_caption(f"❌ Error: {str(e)}")
        else:
            # For new mode, just publish
            if publish_series(series_key):
                try:
                    await client.edit_message_caption(
                        chat_id=user_id,
                        message_id=main_message_id,
                        caption="✅ Published Successfully"
                    )
                except Exception as e:
                    logger.error(f"Failed to edit message: {e}")
                temp_admin_data[user_id]["state"] = "PUBLISHED"
            else:
                try:
                    await client.edit_message_caption(
                        chat_id=user_id,
                        message_id=main_message_id,
                        caption="❌ Failed to publish series. Please try again."
                    )
                except Exception as e:
                    logger.error(f"Failed to edit message: {e}")
    
    elif data == f"{prefix}confirm_update":
        series_key = temp_admin_data[user_id].get("current_series_key")
        
        series_data = get_series_by_key(series_key)
        if series_data:
            await callback_query.message.edit_caption("✅ Metadata Updated Successfully")
            await send_series_details_message(client, user_id, series_data, main_message_id, mode)
        else:
            await callback_query.message.edit_caption("❌ Series not found.")

    elif data in [f"{prefix}cancel_publish", f"{prefix}cancel_update"]:
        series_key = temp_admin_data[user_id].get("current_series_key")
        
        series_data = get_series_by_key(series_key)
        if series_data:
            await send_series_details_message(client, user_id, series_data, main_message_id, mode)
        else:
            await callback_query.message.edit_caption("❌ Series not found.")
    
    # Quality options handlers
    elif data == f"{prefix}readd_quality":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        quality_name = temp_admin_data[user_id].get("current_quality")
        
        temp_admin_data[user_id]["state"] = f"{prefix.upper()}AWAITING_FIRST_FILE"
        
        if "ask_message_id" in temp_admin_data[user_id]:
            try:
                await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
            except Exception:
                pass
        
        ask_msg = await client.send_message(
            user_id,
            f"Forward me the first file (with tag) for {language_name}-{season_name}-{quality_name}"
        )
        temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
        
    elif data == f"{prefix}delete_quality":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        quality_name = temp_admin_data[user_id].get("current_quality")
        
        if add_or_update_quality(series_key, language_name, season_name, quality_name, None):
            await client.send_message(user_id, f"Quality '{quality_name}' files removed.")
            await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id, mode)
        else:
            await client.send_message(user_id, "Failed to remove quality files. Please try again.")
        
    elif data == f"{prefix}cancel_quality":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        
        await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id, mode)

# Command handlers
@Bot.on_message(filters.command('newseriesui') & filters.user(ADMINS))
async def new_series_ui_command(client: Client, message: Message):
    """Handle new series UI command"""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} started new series UI")
    
    assigned_channel = get_admin_channel(user_id)
    if not assigned_channel:
        await message.reply("You don't have an assigned channel. Please contact the bot owner.")
        return
    
    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None

    if not query:
        await message.reply("Usage: `/newseriesui <series_title>`")
        return

    temp_msg = await message.reply_photo(
        photo="https://envs.sh/EMw.jpg",
        caption="Searching TMDB and IMDb, please wait..."
    )
    
    tmdb_results = await get_tmdb_info(query, bulk=True)
    imdb_results = await get_poster(query, bulk=True)

    all_results = []
    if tmdb_results:
        for item in tmdb_results:
            item['source'] = 'tmdb'
            all_results.append(item)
    if imdb_results:
        for item in imdb_results:
            all_results.append({
                'title': item.get('title'),
                'year': item.get('year'),
                'imdb_id': item.get('imdb_id'),
                'media_type': item.get('media_type'),
                'source': 'imdb',
                'poster_url': item.get('poster_url')
            })

    if not all_results:
        await temp_msg.edit_caption("No results found on TMDB or IMDb for the provided series name.")
        return

    temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
    temp_admin_data[user_id]["search_results"] = all_results
    temp_admin_data[user_id]["query"] = query
    temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SEARCH_RESULTS"
    temp_admin_data[user_id]["main_message_id"] = temp_msg.id

    await send_series_selection_message(client, user_id, query, all_results, temp_msg.id, "new")

@Bot.on_message(filters.command('editseries') & filters.user(ADMINS))
async def edit_series_command(client: Client, message: Message):
    """Handle edit series command"""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} started edit series UI")
    
    assigned_channel = get_admin_channel(user_id)
    if not assigned_channel:
        await message.reply("You don't have an assigned channel. Please contact the bot owner.")
        return
    
    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None

    if not query:
        await message.reply("Usage: `/editseries <series_title>`")
        return

    all_series = get_series()
    if not all_series:
        await message.reply("No series found in database.")
        return

    matches = []
    for series in all_series:
        title = series.get('title', '')
        similarity = fuzz.partial_ratio(query.lower(), title.lower())
        if similarity > 70:
            matches.append((series, similarity))

    matches.sort(key=lambda x: x[1], reverse=True)
    matched_series = [match[0] for match in matches[:10]]

    if not matched_series:
        await message.reply("No matching series found in database.")
        return

    try:
        temp_msg = await message.reply_photo(
            photo=NO_POSTER_FOUND_IMG[0],
            caption=f"**Select a series to edit:**Search query: `{query}`",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{s.get('title', 'N/A')} ({s.get('released_on', 'N/A')})", callback_data=f"edit_sel_{s['_id']}")]
                for s in matched_series
            ] + [[InlineKeyboardButton("🔍 Search Again", callback_data="edit_search_again")]]),
            parse_mode=enums.ParseMode.MARKDOWN
        )
        temp_admin_data[user_id] = {
            "state": "EDIT_SERIES_SELECTION",
            "main_message_id": temp_msg.id,
            "query": query
        }
    except Exception as e:
        logger.error(f"Error sending series selection message: {e}")
        await message.reply("Failed to show series selection. Please try again.")

@Bot.on_message(filters.command('assign') & filters.user(ADMINS))
async def assign_command(client: Client, message: Message):
    """Handle admin channel assignment"""
    if len(message.command) != 3:
        await message.reply("Usage: `/assign userid channel_id`")
        return
    
    try:
        user_id = int(message.command[1])
        channel_id = int(message.command[2])
    except ValueError:
        await message.reply("Invalid user ID or channel ID. Both must be integers.")
        return
    
    if add_admin_assignment(user_id, channel_id):
        await message.reply(f"Successfully assigned channel {channel_id} to admin {user_id}.")
    else:
        await message.reply("Failed to assign channel. Please try again.")

@Bot.on_message(filters.command('unassign') & filters.user(ADMINS))
async def unassign_command(client: Client, message: Message):
    """Handle admin channel unassignment"""
    if len(message.command) != 2:
        await message.reply("Usage: `/unassign userid`")
        return
    
    try:
        user_id = int(message.command[1])
    except ValueError:
        await message.reply("Invalid user ID. Must be an integer.")
        return
    
    if remove_admin_assignment(user_id):
        await message.reply(f"Successfully removed assignment for admin {user_id}.")
    else:
        await message.reply("Failed to remove assignment. Please try again.")

@Bot.on_message(filters.command('listadmins') & filters.user(ADMINS))
async def listadmins_command(client: Client, message: Message):
    """List all admin assignments"""
    assignments = get_admin_assignments()
    
    if not assignments:
        await message.reply("No admin assignments found.")
        return
    
    text = "**Admin Assignments:**"
    for user_id, channel_id in assignments.items():
        text += f"• Admin: `{user_id}` → Channel: `{channel_id}`"
    
    await message.reply(text)

# Message handlers
@Bot.on_message(filters.text & filters.private & filters.user(ADMINS))
async def handle_admin_text_message(client: Bot, message: Message):
    """Handle admin text messages"""
    user_id = message.from_user.id
    logger.info(f"Received admin text message {message.id} from user {user_id}")
    
    if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
        current_state = temp_admin_data[user_id].get("state")
        mode = "edit" if current_state.startswith("EDIT_") else "new"
        
        if current_state.endswith("AWAITING_LANGUAGE_INPUT"):
            await process_language_input(client, message, message.text.strip(), mode)
        elif current_state.endswith("AWAITING_SEASON_INPUT"):
            await process_season_input(client, message, message.text.strip(), mode)
        elif current_state.endswith("AWAITING_QUALITY_INPUT"):
            await process_quality_input(client, message, message.text.strip(), mode)
        elif current_state.endswith("AWAITING_CODEC_INPUT"):
            # Handle codec input if needed
            pass

@Bot.on_message((filters.photo | filters.video | filters.document) & filters.private & filters.user(ADMINS))
async def handle_admin_media_message(client: Bot, message: Message):
    """Handle admin media messages"""
    user_id = message.from_user.id
    logger.info(f"Received admin media message {message.id} from user {user_id}")
    
    if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
        current_state = temp_admin_data[user_id].get("state")
        mode = "edit" if current_state.startswith("EDIT_") else "new"
        
        if current_state.endswith("AWAITING_SERIES_POSTER"):
            await process_poster_input(client, message, "series", mode)
        elif current_state.endswith("AWAITING_LANGUAGE_POSTER"):
            await process_poster_input(client, message, "language", mode)
        elif current_state.endswith("AWAITING_SEASON_POSTER"):
            await process_poster_input(client, message, "season", mode)
        elif current_state.endswith("AWAITING_FIRST_FILE"):
            await process_first_file_input(client, message, mode)
        elif current_state.endswith("AWAITING_LAST_FILE"):
            await process_last_file_input(client, message, mode)

# Callback handler
@Bot.on_callback_query(filters.user(ADMINS))
async def callback_handler(client: Bot, callback_query: CallbackQuery):
    """Main callback handler"""
    await unified_callback_handler(client, callback_query)
