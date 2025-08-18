#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, 
    InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from imdb import Cinemagoer
from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, TMDB_API_KEY, LOG_CHANNEL, DB_CHANNEL, RAW_DB_CHANNEL, NO_POSTER_FOUND_IMG
from database.crazy_db import (
    add_series, get_series_by_key, update_series_field, add_or_update_language,
    get_languages, delete_language, add_or_update_season, get_seasons, delete_season,
    add_or_update_quality, get_qualities, get_quality_link, delete_quality,
    get_poster_file_id, update_poster_file_id, publish_series
)
from utils import (
    get_message_id, get_messages, delete_messages_from_user_chat, 
    get_poster, find_most_similar_title
)
from fuzzywuzzy import fuzz
from pyrogram.errors import MessageIdInvalid, FloodWait

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global variables
temp_admin_data: Dict[int, Dict[str, Any]] = {}
admin_locks: Dict[int, asyncio.Lock] = {}
imdb = Cinemagoer()
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

# Helper functions
def get_admin_lock(user_id: int) -> asyncio.Lock:
    if user_id not in admin_locks:
        admin_locks[user_id] = asyncio.Lock()
        logger.info(f"Created new lock for admin user {user_id}")
    return admin_locks[user_id]

async def DeleteMessage(msg):
    await asyncio.sleep(600)
    try:
        await msg.delete()
        logger.debug(f"Deleted message {msg.id} from chat {msg.chat.id}")
    except Exception as e:
        logger.warning(f"Failed to delete message {msg.id}: {e}")

def create_dynamic_layout(items, layout_pattern):
    """
    Create a dynamic button layout based on a pattern.
    
    Args:
        items: List of items to display
        layout_pattern: List of strings representing the layout pattern
                       Each string contains the type and position (e.g., "la1", "lb2", "sa3")
    
    Returns:
        List of lists of InlineKeyboardButton objects
    """
    # Create a dictionary to map layout codes to items
    item_dict = {}
    for i, item in enumerate(items, 1):
        item_dict[f"l{i}"] = item
    
    # Add special case for back button
    item_dict["back"] = "⬅️ Back"
    
    # Create the layout
    layout = []
    current_row = []
    
    for code in layout_pattern:
        if code in item_dict:
            if code == "back":
                # Back button gets its own row
                if current_row:
                    layout.append(current_row)
                    current_row = []
                layout.append([InlineKeyboardButton(
                    text=item_dict[code],
                    callback_data=code
                )])
            else:
                current_row.append(InlineKeyboardButton(
                    text=item_dict[code],
                    callback_data=code
                ))
        
        # Add row to layout if it has 3 buttons or is the last item
        if len(current_row) == 3 or code == layout_pattern[-1]:
            if current_row:
                layout.append(current_row)
                current_row = []
    
    return layout

def create_hierarchical_layout(items, level=0):
    """
    Create a hierarchical button layout based on the level.
    
    Args:
        items: List of items to display
        level: Current hierarchy level (0=language, 1=season, 2=quality)
    
    Returns:
        List of lists of InlineKeyboardButton objects
    """
    layout = []
    
    # Add items with edit buttons
    for i, item in enumerate(items, 1):
        row = []
        # Item button
        row.append(InlineKeyboardButton(
            text=item,
            callback_data=f"level{level}_item_{i-1}"
        ))
        # Add button (same level)
        row.append(InlineKeyboardButton(
            text="+",
            callback_data=f"level{level}_add_{i-1}"
        ))
        layout.append(row)
    
    # Add new item button at the bottom
    layout.append([
        InlineKeyboardButton(
            text=f"+ Add New",
            callback_data=f"level{level}_add_new"
        )
    ])
    
    # Add back button if not at the top level
    if level > 0:
        layout.append([
            InlineKeyboardButton(
                text="⬅️ Back",
                callback_data=f"level{level}_back"
            )
        ])
    
    return layout

async def process_poster_update(client: Client, user_id: int, series_key: str, 
                               language_name: str = None, season_name: str = None,
                               poster_type: str = "series"):
    """
    Process poster update for series, language, or season.
    
    Args:
        client: Pyrogram client
        user_id: User ID
        series_key: Series key
        language_name: Language name (optional)
        season_name: Season name (optional)
        poster_type: Type of poster to update ("series", "language", "season")
    """
    temp_admin_data[user_id]["state"] = f"AWAITING_{poster_type.upper()}_POSTER"
    temp_admin_data[user_id]["poster_type"] = poster_type
    
    if language_name:
        temp_admin_data[user_id]["current_language"] = language_name
    if season_name:
        temp_admin_data[user_id]["current_season"] = season_name
    
    await client.send_message(
        user_id,
        f"Please send a photo or video to use as the {poster_type} poster:"
    )

# TMDB and helper functions
async def get_tmdb_info(query, bulk=False, tmdb_id=None, media_type=None):
    logger.info(f"Fetching TMDB info: query={query}, bulk={bulk}, tmdb_id={tmdb_id}, media_type={media_type}")
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {TMDB_API_KEY}"
    }

    try:
        if tmdb_id:
            url = f"{TMDB_BASE_URL}/{media_type}/{tmdb_id}"
            logger.info(f"Fetching details from {url}")
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

            genres = [g['name'] for g in data.get('genres', [])][:3]
            poster_path = data.get('poster_path')
            poster_url = f"{TMDB_IMAGE_BASE_URL}{poster_path}" if poster_path else NO_POSTER_FOUND_IMG

            if media_type == 'tv':
                title = data.get('name', 'N/A')
                year = f"{data.get('first_air_date', '').split('-')[0]} - {data.get('last_air_date', '').split('-')[0]}" if data.get('first_air_date') and data.get('last_air_date') else data.get('first_air_date', '').split('-')[0] if data.get('first_air_date') else 'N/A'
            else: # movie
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
            logger.info(f"Searching TV shows at {url_tv} with query: {query}")
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
            
            # Search Movies
            url_movie = f"{TMDB_BASE_URL}/search/movie"
            logger.info(f"Searching movies at {url_movie} with query: {query}")
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

async def download_and_upload_poster(client: Client, poster_url: str = None, message: Message = None):
    logger.info("Downloading and uploading poster")
    temp_dir = os.path.join(TMP_DOWNLOAD_DIRECTORY, str(uuid.uuid4()))
    os.makedirs(temp_dir, exist_ok=True)
    download_path = None
    file_id = None

    try:
        if poster_url:
            logger.info(f"Downloading poster from URL: {poster_url}")
            response = requests.get(poster_url, stream=True)
            response.raise_for_status()
            download_path = os.path.join(temp_dir, "poster.jpg")
            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        elif message and message.photo and message.photo.file_id:
            logger.info("Downloading user-provided photo")
            download_path = await client.download_media(message.photo.file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        elif message and message.video and message.video.thumbs and message.video.thumbs[0].file_id:
            logger.info("Downloading user-provided video thumbnail")
            download_path = await client.download_media(message.video.thumbs[0].file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        else:
            logger.warning("No valid poster source provided")
            return None

        if download_path:
            logger.info("Uploading poster to LOG_CHANNEL")
            sent_msg = await client.send_photo(LOG_CHANNEL, photo=download_path, caption="Series Poster")
            file_id = sent_msg.photo.file_id
            try:
                await sent_msg.delete()
                logger.debug("Deleted temporary poster from LOG_CHANNEL")
            except Exception as e:
                logger.warning(f"Could not delete temporary poster message from LOG_CHANNEL: {e}")
    except Exception as e:
        logger.error(f"Error downloading/uploading poster: {e}")
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            logger.debug(f"Cleaned up temporary directory: {temp_dir}")
    return file_id

# Admin UI message sending functions
async def send_series_selection_message(client: Client, user_id: int, query: str, results: list, message_id: int = None):
    logger.info(f"Sending series selection message to user {user_id}")
    text = f"**Select a series from below:**\n\nSearch query: `{query}`"
    
    buttons = []
    for i, item in enumerate(results, 1):
        unique_id = str(uuid.uuid4())
        temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
        temp_admin_data[user_id][unique_id] = {
            'id': item.get('tmdb_id') if item.get('source') == 'tmdb' else item.get('imdb_id'),
            'media_type': item.get('media_type'),
            'source': item.get('source'),
            'query': query
        }
        buttons.append(InlineKeyboardButton(
            text=f"{item.get('title', 'N/A')} ({item.get('year', 'N/A')}) - {item.get('source').upper()}",
            callback_data=f"sel_{unique_id}"
        ))
    
    buttons.append(InlineKeyboardButton("🔍 Search Again", callback_data="search_again"))
    
    # Create dynamic layout
    layout_pattern = [f"la{i}" for i in range(1, len(buttons) + 1)]
    layout = create_dynamic_layout(buttons, layout_pattern)
    reply_markup = InlineKeyboardMarkup(layout)

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=NO_POSTER_FOUND_IMG, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=reply_markup
            )
            logger.debug(f"Edited series selection message {message_id}")
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=NO_POSTER_FOUND_IMG,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            logger.debug(f"Sent new series selection message {msg.id}")
            return msg.id
    except (MessageIdInvalid, FloodWait) as e:
        logger.warning(f"Failed to edit series selection message (ID: {message_id}): {e}. Attempting to send a new message.")
        new_msg = await client.send_photo(
            chat_id=user_id,
            photo=NO_POSTER_FOUND_IMG,
            caption=text,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.MARKDOWN
        )
        temp_admin_data[user_id]["main_message_id"] = new_msg.id
        return new_msg.id
    except Exception as e:
        logger.error(f"An unexpected error occurred sending series selection message: {e}")
        return None

async def send_series_details_message(client: Client, user_id: int, series_data: dict, message_id: int = None):
    logger.info(f"Sending series details message to user {user_id}")
    series_key = series_data['_id']
    poster_file_id = get_poster_file_id(series_key) or NO_POSTER_FOUND_IMG

    text = (
        f"**Title:** `{series_data.get('title', 'N/A')}`\n"
        f"**Released On:** `{series_data.get('released_on', 'N/A')}`\n"
        f"**Genre:** `{series_data.get('genre', 'N/A')}`\n"
        f"**Rating:** `{series_data.get('rating', 'N/A')}`\n"
        f"**TMDB ID:** `{series_data.get('tmdb_id', 'N/A')}`\n"
        f"**Media Type:** `{series_data.get('media_type', 'N/A').upper()}`\n\n"
    )

    # Get languages for display
    languages = series_data.get("languages", [])
    language_names = [lang["name"] for lang in languages]
    
    # Create hierarchical layout
    layout = []
    for lang_name in language_names:
        layout.append([
            InlineKeyboardButton(
                text=lang_name,
                callback_data=f"lang_select_{lang_name}"
            ),
            InlineKeyboardButton(
                text="+",
                callback_data=f"lang_add_{lang_name}"
            )
        ])
    
    # Add new language button
    layout.append([
        InlineKeyboardButton(
            text="+ Add Language",
            callback_data="add_language"
        )
    ])
    
    # Add action buttons
    layout.extend([
        [
            InlineKeyboardButton("🖼️ Change Poster", callback_data="change_series_poster"),
            InlineKeyboardButton("📤 Publish Series", callback_data="publish_series")
        ],
        [
            InlineKeyboardButton("⬅️ Back to Search", callback_data="back_to_search")
        ]
    ])
    
    reply_markup = InlineKeyboardMarkup(layout)

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=poster_file_id, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=reply_markup
            )
            logger.debug(f"Edited series details message {message_id}")
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_file_id,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            logger.debug(f"Sent new series details message {msg.id}")
            return msg.id
    except (MessageIdInvalid, FloodWait) as e:
        logger.warning(f"Failed to edit series details message (ID: {message_id}): {e}. Attempting to send a new message.")
        new_msg = await client.send_photo(
            chat_id=user_id,
            photo=poster_file_id,
            caption=text,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.MARKDOWN
        )
        temp_admin_data[user_id]["main_message_id"] = new_msg.id
        return new_msg.id
    except Exception as e:
        logger.error(f"An unexpected error occurred sending series details message: {e}")
        return None

async def send_language_management_message(client: Client, user_id: int, series_key: str, language_name: str, message_id: int):
    logger.info(f"Sending language management message to user {user_id}")
    series_data = get_series_by_key(series_key)
    if not series_data:
        logger.warning(f"Series not found for key: {series_key}")
        await client.send_message(user_id, "Series not found.")
        return

    current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
    if not current_lang:
        logger.warning(f"Language not found: {language_name}")
        await client.send_message(user_id, "Language not found.")
        return

    seasons = current_lang.get("seasons", [])
    season_names = [season["name"] for season in seasons]
    
    text = (
        f"**Series:** `{series_data.get('title', 'N/A')}`\n"
        f"**Language:** `{language_name}`\n\n"
        "Select any Seasons group to manage. Or click '+' button to add new Seasons group.\n\n"
    )

    # Create hierarchical layout
    layout = []
    for season_name in season_names:
        layout.append([
            InlineKeyboardButton(
                text=season_name,
                callback_data=f"season_select_{season_name}"
            ),
            InlineKeyboardButton(
                text="+",
                callback_data=f"season_add_{season_name}"
            )
        ])
    
    # Add new season button
    layout.append([
        InlineKeyboardButton(
            text="+ Add Season",
            callback_data="add_season"
        )
    ])
    
    # Add action buttons
    layout.extend([
        [
            InlineKeyboardButton("🖼️ Change Language Poster", callback_data="change_language_poster"),
            InlineKeyboardButton(f"🗑️ Delete '{language_name}' Group", callback_data="delete_language")
        ],
        [
            InlineKeyboardButton("⬅️ Back to Series", callback_data="back_to_series")
        ]
    ])
    
    reply_markup = InlineKeyboardMarkup(layout)

    poster_to_use = current_lang.get("poster_file_id") or series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=poster_to_use, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=reply_markup
            )
            logger.debug(f"Edited language management message {message_id}")
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_to_use,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            logger.debug(f"Sent new language management message {msg.id}")
            return msg.id
    except (MessageIdInvalid, FloodWait) as e:
        logger.warning(f"Failed to edit language management message (ID: {message_id}): {e}. Attempting to send a new message.")
        new_msg = await client.send_photo(
            chat_id=user_id,
            photo=poster_to_use,
            caption=text,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.MARKDOWN
        )
        temp_admin_data[user_id]["main_message_id"] = new_msg.id
        return new_msg.id
    except Exception as e:
        logger.error(f"An unexpected error occurred editing language management message: {e}")
        await client.send_message(user_id, "Error updating language management display. Please try again.")
        return None

async def send_season_management_message(client: Client, user_id: int, series_key: str, language_name: str, season_name: str, message_id: int):
    logger.info(f"Sending season management message to user {user_id}")
    series_data = get_series_by_key(series_key)
    if not series_data:
        logger.warning(f"Series not found for key: {series_key}")
        await client.send_message(user_id, "Series not found.")
        return

    current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
    current_season = next((s for s in current_lang.get("seasons", []) if s["name"].lower() == season_name.lower()), None) if current_lang else None
    if not current_season:
        logger.warning(f"Season not found: {season_name}")
        await client.send_message(user_id, "Season not found.")
        return

    qualities = current_season.get("qualities", [])
    quality_names = [quality["name"] for quality in qualities]
    
    text = (
        f"**Series:** `{series_data.get('title', 'N/A')}`\n"
        f"**Language:** `{language_name}`\n"
        f"**Season:** `{season_name}`\n\n"
        "Select any Quality group to manage. Or click '+' button to add new Quality group.\n\n"
    )

    # Create hierarchical layout
    layout = []
    for quality_name in quality_names:
        layout.append([
            InlineKeyboardButton(
                text=quality_name,
                callback_data=f"quality_select_{quality_name}"
            ),
            InlineKeyboardButton(
                text="+",
                callback_data=f"quality_add_{quality_name}"
            )
        ])
    
    # Add new quality button
    layout.append([
        InlineKeyboardButton(
            text="+ Add Quality",
            callback_data="add_quality"
        )
    ])
    
    # Add action buttons
    layout.extend([
        [
            InlineKeyboardButton("🖼️ Change Season Poster", callback_data="change_season_poster"),
            InlineKeyboardButton(f"🗑️ Delete '{season_name}' Group", callback_data="delete_season")
        ],
        [
            InlineKeyboardButton("⬅️ Back to Language", callback_data="back_to_language")
        ]
    ])
    
    reply_markup = InlineKeyboardMarkup(layout)

    poster_to_use = current_season.get("poster_file_id") or current_lang.get("poster_file_id") or series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=poster_to_use, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=reply_markup
            )
            logger.debug(f"Edited season management message {message_id}")
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_to_use,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            logger.debug(f"Sent new season management message {msg.id}")
            return msg.id
    except (MessageIdInvalid, FloodWait) as e:
        logger.warning(f"Failed to edit season management message (ID: {message_id}): {e}. Attempting to send a new message.")
        new_msg = await client.send_photo(
            chat_id=user_id,
            photo=poster_to_use,
            caption=text,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.MARKDOWN
        )
        temp_admin_data[user_id]["main_message_id"] = new_msg.id
        return new_msg.id
    except Exception as e:
        logger.error(f"An unexpected error occurred editing season management message: {e}")
        await client.send_message(user_id, "Error updating season management display. Please try again.")
        return None

async def send_quality_management_message(client: Client, user_id: int, series_key: str, language_name: str, season_name: str, quality_name: str, message_id: int):
    logger.info(f"Sending quality management message to user {user_id}")
    series_data = get_series_by_key(series_key)
    if not series_data:
        logger.warning(f"Series not found for key: {series_key}")
        await client.send_message(user_id, "Series not found.")
        return

    current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
    current_season = next((s for s in current_lang.get("seasons", []) if s["name"].lower() == season_name.lower()), None) if current_lang else None
    current_quality = next((q for q in current_season.get("qualities", []) if q["name"].lower() == quality_name.lower()), None) if current_season else None
    
    if not current_quality:
        logger.warning(f"Quality not found: {quality_name}")
        await client.send_message(user_id, "Quality not found.")
        return

    link_key = current_quality.get("link_key")
    has_files = link_key is not None and link_key != "PENDING_LINK"
    
    text = (
        f"**Series:** `{series_data.get('title', 'N/A')}`\n"
        f"**Language:** `{language_name}`\n"
        f"**Season:** `{season_name}`\n"
        f"**Quality:** `{quality_name}`\n\n"
    )

    if has_files:
        text += "Files have been added to this quality.\n\n"
    else:
        text += "No files have been added to this quality yet.\n\n"

    # Create layout
    layout = []
    
    if not has_files:
        layout.append([
            InlineKeyboardButton("📁 Add Files", callback_data="add_files")
        ])
    else:
        layout.append([
            InlineKeyboardButton("🔄 Replace Files", callback_data="replace_files")
        ])
    
    # Add action buttons
    layout.extend([
        [
            InlineKeyboardButton(f"🗑️ Delete '{quality_name}' Group", callback_data="delete_quality")
        ],
        [
            InlineKeyboardButton("⬅️ Back to Season", callback_data="back_to_season")
        ]
    ])
    
    reply_markup = InlineKeyboardMarkup(layout)

    poster_to_use = current_season.get("poster_file_id") or current_lang.get("poster_file_id") or series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=poster_to_use, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=reply_markup
            )
            logger.debug(f"Edited quality management message {message_id}")
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_to_use,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            logger.debug(f"Sent new quality management message {msg.id}")
            return msg.id
    except (MessageIdInvalid, FloodWait) as e:
        logger.warning(f"Failed to edit quality management message (ID: {message_id}): {e}. Attempting to send a new message.")
        new_msg = await client.send_photo(
            chat_id=user_id,
            photo=poster_to_use,
            caption=text,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.MARKDOWN
        )
        temp_admin_data[user_id]["main_message_id"] = new_msg.id
        return new_msg.id
    except Exception as e:
        logger.error(f"An unexpected error occurred editing quality management message: {e}")
        await client.send_message(user_id, "Error updating quality management display. Please try again.")
        return None

# Command handlers
@Client.on_message(filters.command('newseriesui') & filters.user(ADMINS))
async def new_series_ui_command(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} started new series UI")
    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None

    if not query:
        await message.reply("Usage: `/newseriesui <series_title>`")
        return

    async with get_admin_lock(user_id):
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

        await send_series_selection_message(client, user_id, query, all_results, temp_msg.id)

@Client.on_message(filters.command('editseries') & filters.user(ADMINS))
async def edit_series_command(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} started edit series UI")
    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None

    if not query:
        await message.reply("Usage: `/editseries <series_title>`")
        return

    async with get_admin_lock(user_id):
        # Search for existing series
        series_list = get_series()
        series_keys = [series['_id'] for series in series_list]
        series_names = [series['title'] for series in series_list]
        
        # Try exact match by key first
        if query.lower().replace(" ", "").replace("-", "") in series_keys:
            series_key = query.lower().replace(" ", "").replace("-", "")
            series_data = get_series_by_key(series_key)
            if series_data:
                temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
                temp_admin_data[user_id]["current_series_key"] = series_key
                temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SERIES_DETAILS"
                
                temp_msg = await message.reply_photo(
                    photo=get_poster_file_id(series_key) or NO_POSTER_FOUND_IMG,
                    caption="Loading series details..."
                )
                
                await send_series_details_message(client, user_id, series_data, temp_msg.id)
                return
        
        # Try exact match by title
        for s_info in series_list:
            if s_info['title'].lower() == query.lower():
                series_key = s_info['_id']
                series_data = get_series_by_key(series_key)
                if series_data:
                    temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
                    temp_admin_data[user_id]["current_series_key"] = series_key
                    temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SERIES_DETAILS"
                    
                    temp_msg = await message.reply_photo(
                        photo=get_poster_file_id(series_key) or NO_POSTER_FOUND_IMG,
                        caption="Loading series details..."
                    )
                    
                    await send_series_details_message(client, user_id, series_data, temp_msg.id)
                    return
        
        # If no exact match, show close matches
        close_matches = find_most_similar_title(query, series_names)
        if not close_matches:
            await message.reply("No series found with that name.")
            return
        
        buttons = []
        for match in close_matches[:5]:  # Limit to 5 matches
            s_info = next((s for s in series_list if s['title'] == match), None)
            if s_info:
                buttons.append(InlineKeyboardButton(match, callback_data=f"edit_sel_{s_info['_id']}"))
        
        if buttons:
            # Define the layout pattern
            layout_pattern = [f"la{i}" for i in range(1, len(buttons) + 1)]
            layout = create_dynamic_layout(buttons, layout_pattern)
            reply_markup = InlineKeyboardMarkup(layout)
            
            await message.reply_photo(
                photo=NO_POSTER_FOUND_IMG,
                caption="Select a series to edit:",
                reply_markup=reply_markup
            )

# Message handlers for admin UI
@Client.on_message(filters.text & filters.private & filters.user(ADMINS))
async def handle_admin_text_message(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Received admin text message {message.id} from user {user_id}")
    
    if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
        logger.info(f"Admin {user_id} has active state, acquiring lock")
        async with get_admin_lock(user_id):
            await handle_admin_text_input(client, message)
        return

@Client.on_message((filters.photo | filters.video | filters.document) & filters.private & filters.user(ADMINS))
async def handle_admin_media_message(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Received admin media message {message.id} from user {user_id}")
    
    if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
        logger.info(f"Admin {user_id} has active state, acquiring lock for media")
        async with get_admin_lock(user_id):
            await handle_admin_media_input(client, message)
        return

# Callback handlers for admin UI
@Client.on_callback_query(filters.user(ADMINS))
async def admin_ui_callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    logger.info(f"Received admin UI callback from user {user_id}: {data}")

    async with get_admin_lock(user_id):
        await newui_callback_handler(client, callback_query)

# Process input functions
async def handle_admin_text_input(client: Client, message: Message):
    user_id = message.from_user.id
    current_state = temp_admin_data.get(user_id, {}).get("state")
    logger.info(f"Processing admin text input in state: {current_state}")
    
    if current_state == "AWAITING_LANGUAGE_INPUT":
        await process_language_input(client, message, message.text.strip())
    elif current_state == "AWAITING_SEASON_INPUT":
        await process_season_input(client, message, message.text.strip())
    elif current_state == "AWAITING_QUALITY_INPUT":
        await process_quality_input(client, message, message.text.strip())
    elif current_state.startswith("AWAITING_CODEC_INPUT"):
        await process_codec_input(client, message, message.text.strip())

async def handle_admin_media_input(client: Client, message: Message):
    user_id = message.from_user.id
    current_state = temp_admin_data.get(user_id, {}).get("state")
    logger.info(f"Processing admin media input in state: {current_state}")
    
    if current_state == "AWAITING_SERIES_POSTER":
        await process_poster_input(client, message, "series")
    elif current_state == "AWAITING_LANGUAGE_POSTER":
        await process_poster_input(client, message, "language")
    elif current_state == "AWAITING_SEASON_POSTER":
        await process_poster_input(client, message, "season")
    elif current_state == "AWAITING_FIRST_FILE":
        await process_first_file_input(client, message)
    elif current_state == "AWAITING_LAST_FILE":
        await process_last_file_input(client, message)

async def newui_callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    logger.info(f"Processing admin UI callback: {data}")
    
    if user_id not in temp_admin_data:
        logger.warning(f"Admin {user_id} not in temp_admin_data")
        await callback_query.answer("Session expired. Please start again with /newseriesui.", show_alert=True)
        return
    
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    
    # Handle language selection
    if data.startswith("lang_select_"):
        language_name = data.split("_", 2)[2]
        series_key = temp_admin_data[user_id].get("current_series_key")
        
        await callback_query.answer(f"Selected: {language_name}")
        temp_admin_data[user_id]["current_language"] = language_name
        temp_admin_data[user_id]["state"] = "MANAGE_LANGUAGE"
        
        await send_language_management_message(client, user_id, series_key, language_name, main_message_id)
    
    # Handle language add button
    elif data.startswith("lang_add_"):
        language_name = data.split("_", 2)[2]
        series_key = temp_admin_data[user_id].get("current_series_key")
        
        await callback_query.answer("Enter new language name...")
        
        reply_keyboard = ReplyKeyboardMarkup(
            [
                [KeyboardButton("English"), KeyboardButton("Spanish")],
                [KeyboardButton("Japanese"), KeyboardButton("Korean")],
                [KeyboardButton("French"), KeyboardButton("German")],
                [KeyboardButton("Multi Audio")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        ask_msg = await client.send_message(
            user_id,
            "Enter language name (e.g., 'English', 'Multi Audio (Ger + Eng)'):",
            reply_markup=reply_keyboard
        )
        temp_admin_data[user_id]["state"] = "AWAITING_LANGUAGE_INPUT"
        temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
        temp_admin_data[user_id]["after_language"] = language_name  # Language to add after
    
    # Handle season selection
    elif data.startswith("season_select_"):
        season_name = data.split("_", 2)[2]
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        
        await callback_query.answer(f"Selected: {season_name}")
        temp_admin_data[user_id]["current_season"] = season_name
        temp_admin_data[user_id]["state"] = "MANAGE_SEASON"
        
        await send_season_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
    
    # Handle season add button
    elif data.startswith("season_add_"):
        season_name = data.split("_", 2)[2]
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        
        await callback_query.answer("Enter new season name...")
        
        reply_keyboard = ReplyKeyboardMarkup(
            [
                [KeyboardButton("Season 1"), KeyboardButton("Season 2")],
                [KeyboardButton("Season 3"), KeyboardButton("Season 4")],
                [KeyboardButton("Season 5"), KeyboardButton("Season 6")],
                [KeyboardButton("Part 1"), KeyboardButton("Part 2")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        ask_msg = await client.send_message(
            user_id,
            "Enter season name (e.g., 'Season 1', 'Part 2'):",
            reply_markup=reply_keyboard
        )
        temp_admin_data[user_id]["state"] = "AWAITING_SEASON_INPUT"
        temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
        temp_admin_data[user_id]["after_season"] = season_name  # Season to add after
    
    # Handle quality selection
    elif data.startswith("quality_select_"):
        quality_name = data.split("_", 2)[2]
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        
        await callback_query.answer(f"Selected: {quality_name}")
        temp_admin_data[user_id]["current_quality"] = quality_name
        temp_admin_data[user_id]["state"] = "MANAGE_QUALITY"
        
        await send_quality_management_message(client, user_id, series_key, language_name, season_name, quality_name, main_message_id)
    
    # Handle quality add button
    elif data.startswith("quality_add_"):
        quality_name = data.split("_", 2)[2]
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        
        await callback_query.answer("Enter new quality name...")
        
        reply_keyboard = ReplyKeyboardMarkup(
            [
                [KeyboardButton("360p"), KeyboardButton("480p"), KeyboardButton("720p")],
                [KeyboardButton("1080p"), KeyboardButton("2160p"), KeyboardButton("H.265")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        ask_msg = await client.send_message(
            user_id,
            "Enter quality name (e.g., '720p', '1080p'):",
            reply_markup=reply_keyboard
        )
        temp_admin_data[user_id]["state"] = "AWAITING_QUALITY_INPUT"
        temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
        temp_admin_data[user_id]["after_quality"] = quality_name  # Quality to add after
    
    # Handle add files button
    elif data == "add_files" or data == "replace_files":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        quality_name = temp_admin_data[user_id].get("current_quality")
        
        await callback_query.answer("Forward the first file...")
        
        temp_admin_data[user_id]["state"] = "AWAITING_FIRST_FILE"
        temp_admin_data[user_id]["replace_files"] = (data == "replace_files")
        
        await client.send_message(
            user_id,
            f"Forward me the first file (with tag) for {language_name}-{season_name}-{quality_name}"
        )
    
    # Handle poster changes
    elif data == "change_series_poster":
        series_key = temp_admin_data[user_id].get("current_series_key")
        await process_poster_update(client, user_id, series_key, poster_type="series")
        await callback_query.answer("Send a new poster...")
    
    elif data == "change_language_poster":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        await process_poster_update(client, user_id, series_key, language_name, poster_type="language")
        await callback_query.answer("Send a new poster...")
    
    elif data == "change_season_poster":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        await process_poster_update(client, user_id, series_key, language_name, season_name, poster_type="season")
        await callback_query.answer("Send a new poster...")
    
    # Handle delete operations
    elif data == "delete_language":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        
        await callback_query.answer(f"Deleting {language_name}...")
        
        if delete_language(series_key, language_name):
            await client.send_message(user_id, f"Language '{language_name}' deleted successfully.")
            # Go back to series details
            series_data = get_series_by_key(series_key)
            await send_series_details_message(client, user_id, series_data, main_message_id)
        else:
            await client.send_message(user_id, "Failed to delete language.")
    
    elif data == "delete_season":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        
        await callback_query.answer(f"Deleting {season_name}...")
        
        if delete_season(series_key, language_name, season_name):
            await client.send_message(user_id, f"Season '{season_name}' deleted successfully.")
            # Go back to language management
            await send_language_management_message(client, user_id, series_key, language_name, main_message_id)
        else:
            await client.send_message(user_id, "Failed to delete season.")
    
    elif data == "delete_quality":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        quality_name = temp_admin_data[user_id].get("current_quality")
        
        await callback_query.answer(f"Deleting {quality_name}...")
        
        if delete_quality(series_key, language_name, season_name, quality_name):
            await client.send_message(user_id, f"Quality '{quality_name}' deleted successfully.")
            # Go back to season management
            await send_season_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
        else:
            await client.send_message(user_id, "Failed to delete quality.")
    
    # Handle navigation
    elif data == "back_to_series":
        series_key = temp_admin_data[user_id].get("current_series_key")
        series_data = get_series_by_key(series_key)
        
        await callback_query.answer("Going back to series details...")
        temp_admin_data[user_id]["state"] = "SERIES_DETAILS"
        
        await send_series_details_message(client, user_id, series_data, main_message_id)
    
    elif data == "back_to_language":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        
        await callback_query.answer("Going back to language management...")
        temp_admin_data[user_id]["state"] = "MANAGE_LANGUAGE"
        
        await send_language_management_message(client, user_id, series_key, language_name, main_message_id)
    
    elif data == "back_to_season":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        
        await callback_query.answer("Going back to season management...")
        temp_admin_data[user_id]["state"] = "MANAGE_SEASON"
        
        await send_season_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
    
    # Handle adding new items
    elif data == "add_language":
        series_key = temp_admin_data[user_id].get("current_series_key")
        
        await callback_query.answer("Enter language name...")
        
        reply_keyboard = ReplyKeyboardMarkup(
            [
                [KeyboardButton("English"), KeyboardButton("Spanish")],
                [KeyboardButton("Japanese"), KeyboardButton("Korean")],
                [KeyboardButton("French"), KeyboardButton("German")],
                [KeyboardButton("Multi Audio")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        ask_msg = await client.send_message(
            user_id,
            "Enter language name (e.g., 'English', 'Multi Audio (Ger + Eng)'):",
            reply_markup=reply_keyboard
        )
        temp_admin_data[user_id]["state"] = "AWAITING_LANGUAGE_INPUT"
        temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
        temp_admin_data[user_id]["after_language"] = None  # Adding at the end
    
    elif data == "add_season":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        
        await callback_query.answer("Enter season name...")
        
        reply_keyboard = ReplyKeyboardMarkup(
            [
                [KeyboardButton("Season 1"), KeyboardButton("Season 2")],
                [KeyboardButton("Season 3"), KeyboardButton("Season 4")],
                [KeyboardButton("Season 5"), KeyboardButton("Season 6")],
                [KeyboardButton("Part 1"), KeyboardButton("Part 2")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        ask_msg = await client.send_message(
            user_id,
            "Enter season name (e.g., 'Season 1', 'Part 2'):",
            reply_markup=reply_keyboard
        )
        temp_admin_data[user_id]["state"] = "AWAITING_SEASON_INPUT"
        temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
        temp_admin_data[user_id]["after_season"] = None  # Adding at the end
    
    elif data == "add_quality":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        
        await callback_query.answer("Enter quality name...")
        
        reply_keyboard = ReplyKeyboardMarkup(
            [
                [KeyboardButton("360p"), KeyboardButton("480p"), KeyboardButton("720p")],
                [KeyboardButton("1080p"), KeyboardButton("2160p"), KeyboardButton("H.265")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        ask_msg = await client.send_message(
            user_id,
            "Enter quality name (e.g., '720p', '1080p'):",
            reply_markup=reply_keyboard
        )
        temp_admin_data[user_id]["state"] = "AWAITING_QUALITY_INPUT"
        temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
        temp_admin_data[user_id]["after_quality"] = None  # Adding at the end
    
    # Handle publishing
    elif data == "publish_series":
        series_key = temp_admin_data[user_id].get("current_series_key")
        
        await callback_query.answer("Preparing to publish...")
        
        # Create confirmation message
        text = "Do you want to publish this series?\n\nNOTE: Once you publish this series, you can't edit it anymore.\nAll the empty groups will be removed automatically."
        
        layout = [
            [
                InlineKeyboardButton("Yes", callback_data="confirm_publish"),
                InlineKeyboardButton("No", callback_data="cancel_publish")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(layout)
        
        try:
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption=text,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error editing message for publish confirmation: {e}")
            await client.send_message(user_id, "Error preparing publish confirmation. Please try again.")
    
    # Handle publish confirmation
    elif data == "confirm_publish":
        series_key = temp_admin_data[user_id].get("current_series_key")
        
        await callback_query.answer("Publishing series...")
        
        if publish_series(series_key):
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption="Published Successfully!"
            )
        else:
            await client.send_message(user_id, "Failed to publish series.")
    
    # Handle publish cancellation
    elif data == "cancel_publish":
        series_key = temp_admin_data[user_id].get("current_series_key")
        series_data = get_series_by_key(series_key)
        
        await callback_query.answer("Publish cancelled.")
        
        await send_series_details_message(client, user_id, series_data, main_message_id)
    
    # Handle other existing callbacks
    elif data.startswith("sel_"):
        unique_id = data.split("_", 1)[1]
        if unique_id not in temp_admin_data[user_id]:
            logger.warning(f"Invalid selection from admin {user_id}: {unique_id}")
            await callback_query.answer("Invalid selection.", show_alert=True)
            return
        
        stored_data = temp_admin_data[user_id].pop(unique_id)
        media_id = stored_data['id']
        media_type = stored_data['media_type']
        source = stored_data['source']
        query = stored_data['query']
        
        await callback_query.answer(f"Fetching details from {source.upper()}...")
        
        movie_details = None
        if source == 'tmdb':
            movie_details = await get_tmdb_info(query=None, tmdb_id=media_id, media_type=media_type)
        elif source == 'imdb':
            movie_details = await get_poster(media_id, id=True)
        
        if not movie_details:
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption=f"Failed to retrieve {source.upper()} data. Please try again."
            )
            return
        
        series_key = movie_details.get('title', 'N/A').lower().replace(" ", "").replace("-", "")
        
        existing_series = get_series_by_key(series_key)
        if existing_series:
            series_data = existing_series
            await callback_query.answer("Series already exists. Loading for editing.", show_alert=True)
        else:
            series_data = {
                '_id': series_key,
                'title': movie_details.get('title', 'N/A'),
                'released_on': movie_details.get('year', 'N/A'),
                'genre': movie_details.get('genres', 'N/A'),
                'rating': movie_details.get('rating', 'N/A'),
                'tmdb_id': movie_details.get('tmdb_id') if source == 'tmdb' else None,
                'imdb_id': movie_details.get('imdb_id') if source == 'imdb' else None,
                'media_type': media_type,
                'poster_file_id': None,
                'languages': [],
                'published': False
            }
            if not add_series(series_data):
                await callback_query.answer("Failed to add new series (might already exist). Loading existing series.", show_alert=True)
                series_data = get_series_by_key(series_key)
                if not series_data:
                    await client.edit_message_caption(
                        chat_id=user_id,
                        message_id=main_message_id,
                        caption="Failed to create or load series. Please try again."
                    )
                    return
        
        series_data = get_series_by_key(series_key)
        if not series_data:
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption="Failed to retrieve series data after initial setup. Please try again."
            )
            return
        
        poster_file_id = await download_and_upload_poster(client, poster_url=movie_details.get('poster_url') or movie_details.get('poster'))
        if poster_file_id:
            update_series_field(series_key, "poster_file_id", poster_file_id)
            series_data["poster_file_id"] = poster_file_id
        else:
            await client.send_message(user_id, "Failed to download/upload poster. Using placeholder.")
            update_series_field(series_key, "poster_file_id", NO_POSTER_FOUND_IMG)
            series_data["poster_file_id"] = NO_POSTER_FOUND_IMG
        
        new_main_msg_id = await send_series_details_message(client, user_id, series_data, main_message_id)
        if new_main_msg_id:
            temp_admin_data[user_id]["main_message_id"] = new_main_msg_id
            temp_admin_data[user_id]["current_series_key"] = series_key
            temp_admin_data[user_id]["state"] = "SERIES_DETAILS"
    
    # Handle edit series selection
    elif data.startswith("edit_sel_"):
        series_key = data.split("_", 1)[1]
        series_data = get_series_by_key(series_key)
        if not series_data:
            await callback_query.answer("Series not found.", show_alert=True)
            return
        
        await callback_query.answer("Loading series details...")
        temp_admin_data[user_id]["current_series_key"] = series_key
        temp_admin_data[user_id]["state"] = "SERIES_DETAILS"
        
        await send_series_details_message(client, user_id, series_data, main_message_id)
    
    # Handle navigation callbacks
    elif data == "search_again":
        await callback_query.answer("Search again...")
        query = temp_admin_data[user_id].get("query")
        search_results = temp_admin_data[user_id].get("search_results", [])
        
        if not query or not search_results:
            await callback_query.answer("No previous search data found.", show_alert=True)
            return
        
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SEARCH_RESULTS"
        await send_series_selection_message(client, user_id, query, search_results, main_message_id)
    
    elif data == "back_to_search":
        await callback_query.answer("Going back to search results...")
        query = temp_admin_data[user_id].get("query")
        search_results = temp_admin_data[user_id].get("search_results", [])
        
        if not query or not search_results:
            await callback_query.answer("No previous search data found.", show_alert=True)
            return
        
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SEARCH_RESULTS"
        await send_series_selection_message(client, user_id, query, search_results, main_message_id)

async def process_language_input(client: Client, message: Message, language_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    after_language = temp_admin_data[user_id].get("after_language")
    ask_message_id = temp_admin_data[user_id].get("ask_message_id")
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    
    # Delete the ask message
    try:
        await client.delete_messages(user_id, ask_message_id)
    except Exception as e:
        logger.warning(f"Failed to delete ask message: {e}")
    
    # Add or update the language
    if add_or_update_language(series_key, language_name):
        await message.reply(f"Language '{language_name}' added/updated successfully.")
        
        # If adding after a specific language, we need to reorder
        if after_language:
            series_data = get_series_by_key(series_key)
            languages = series_data.get("languages", [])
            
            # Find the index of the language to add after
            after_index = -1
            for i, lang in enumerate(languages):
                if lang["name"].lower() == after_language.lower():
                    after_index = i
                    break
            
            if after_index >= 0:
                # Remove the language we just added
                languages = [lang for lang in languages if lang["name"].lower() != language_name.lower()]
                
                # Insert it after the specified language
                languages.insert(after_index + 1, {"name": language_name, "seasons": []})
                
                # Update the series
                update_series_field(series_key, "languages", languages)
        
        # Go back to series details
        series_data = get_series_by_key(series_key)
        temp_admin_data[user_id]["state"] = "SERIES_DETAILS"
        await send_series_details_message(client, user_id, series_data, main_message_id)
    else:
        await message.reply("Failed to add/update language.")

async def process_season_input(client: Client, message: Message, season_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    after_season = temp_admin_data[user_id].get("after_season")
    ask_message_id = temp_admin_data[user_id].get("ask_message_id")
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    
    # Delete the ask message
    try:
        await client.delete_messages(user_id, ask_message_id)
    except Exception as e:
        logger.warning(f"Failed to delete ask message: {e}")
    
    # Add or update the season
    if add_or_update_season(series_key, language_name, season_name):
        await message.reply(f"Season '{season_name}' added/updated successfully.")
        
        # If adding after a specific season, we need to reorder
        if after_season:
            series_data = get_series_by_key(series_key)
            languages = series_data.get("languages", [])
            
            # Find the language
            for lang in languages:
                if lang["name"].lower() == language_name.lower():
                    seasons = lang.get("seasons", [])
                    
                    # Find the index of the season to add after
                    after_index = -1
                    for i, season in enumerate(seasons):
                        if season["name"].lower() == after_season.lower():
                            after_index = i
                            break
                    
                    if after_index >= 0:
                        # Remove the season we just added
                        seasons = [season for season in seasons if season["name"].lower() != season_name.lower()]
                        
                        # Insert it after the specified season
                        seasons.insert(after_index + 1, {"name": season_name, "qualities": []})
                        
                        # Update the language
                        lang["seasons"] = seasons
                        
                        # Update the series
                        update_series_field(series_key, "languages", languages)
                    break
        
        # Go back to language management
        temp_admin_data[user_id]["state"] = "MANAGE_LANGUAGE"
        await send_language_management_message(client, user_id, series_key, language_name, main_message_id)
    else:
        await message.reply("Failed to add/update season.")

async def process_quality_input(client: Client, message: Message, quality_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    after_quality = temp_admin_data[user_id].get("after_quality")
    ask_message_id = temp_admin_data[user_id].get("ask_message_id")
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    
    # Delete the ask message
    try:
        await client.delete_messages(user_id, ask_message_id)
    except Exception as e:
        logger.warning(f"Failed to delete ask message: {e}")
    
    # Add or update the quality
    if add_or_update_quality(series_key, language_name, season_name, quality_name):
        await message.reply(f"Quality '{quality_name}' added/updated successfully.")
        
        # If adding after a specific quality, we need to reorder
        if after_quality:
            series_data = get_series_by_key(series_key)
            languages = series_data.get("languages", [])
            
            # Find the language and season
            for lang in languages:
                if lang["name"].lower() == language_name.lower():
                    for season in lang.get("seasons", []):
                        if season["name"].lower() == season_name.lower():
                            qualities = season.get("qualities", [])
                            
                            # Find the index of the quality to add after
                            after_index = -1
                            for i, quality in enumerate(qualities):
                                if quality["name"].lower() == after_quality.lower():
                                    after_index = i
                                    break
                            
                            if after_index >= 0:
                                # Remove the quality we just added
                                qualities = [quality for quality in qualities if quality["name"].lower() != quality_name.lower()]
                                
                                # Insert it after the specified quality
                                qualities.insert(after_index + 1, {"name": quality_name})
                                
                                # Update the season
                                season["qualities"] = qualities
                                
                                # Update the series
                                update_series_field(series_key, "languages", languages)
                            break
                    break
        
        # Go back to season management
        temp_admin_data[user_id]["state"] = "MANAGE_SEASON"
        await send_season_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
    else:
        await message.reply("Failed to add/update quality.")

async def process_codec_input(client: Client, message: Message, codec: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    quality_name = temp_admin_data[user_id].get("current_quality")
    first_file_id = temp_admin_data[user_id].get("first_file_id")
    last_file_id = temp_admin_data[user_id].get("last_file_id")
    channel_id = temp_admin_data[user_id].get("channel_id")
    ask_message_id = temp_admin_data[user_id].get("ask_message_id")
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    
    # Delete the ask message
    try:
        await client.delete_messages(user_id, ask_message_id)
    except Exception as e:
        logger.warning(f"Failed to delete ask message: {e}")
    
    # Create a unique link key
    link_key = f"{channel_id}_{first_file_id}_{last_file_id}"
    
    # Update the quality with the link key
    if add_or_update_quality(series_key, language_name, season_name, quality_name, link_key):
        # Send processing message
        processing_msg = await message.reply("Processing files...")
        
        try:
            # Get all messages between first and last
            messages = await get_messages(client, channel_id, range(int(first_file_id), int(last_file_id) + 1))
            
            # Prepare files data for storage
            files_data = []
            for msg in messages:
                file_info = get_file_id(msg)
                if file_info:
                    files_data.append({
                        "file_id": file_info.file_id,
                        "caption": msg.caption or "",
                        "codec": codec
                    })
            
            # Store files in episodes collection
            episodes_collection.update_one(
                {"file_link_key": link_key},
                {"$set": {"files": files_data, "codec": codec}},
                upsert=True
            )
            
            # Update processing message
            await processing_msg.edit_text("Files added to Database Successfully")
            
            # Go back to quality management
            temp_admin_data[user_id]["state"] = "MANAGE_QUALITY"
            await send_quality_management_message(client, user_id, series_key, language_name, season_name, quality_name, main_message_id)
        except Exception as e:
            logger.error(f"Error processing files: {e}")
            await processing_msg.edit_text(f"Error processing files: {e}")
    else:
        await message.reply("Failed to add/update quality.")

async def process_poster_input(client: Client, message: Message, poster_type: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    
    # Download and upload poster
    poster_file_id = await download_and_upload_poster(client, message=message)
    
    if poster_file_id:
        # Update the appropriate poster
        if poster_type == "series":
            update_series_field(series_key, "poster_file_id", poster_file_id)
            await message.reply("Series poster updated successfully.")
            
            # Refresh series details
            series_data = get_series_by_key(series_key)
            await send_series_details_message(client, user_id, series_data, main_message_id)
        elif poster_type == "language":
            add_or_update_language(series_key, language_name, poster_file_id)
            await message.reply("Language poster updated successfully.")
            
            # Refresh language management
            await send_language_management_message(client, user_id, series_key, language_name, main_message_id)
        elif poster_type == "season":
            add_or_update_season(series_key, language_name, season_name, poster_file_id)
            await message.reply("Season poster updated successfully.")
            
            # Refresh season management
            await send_season_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
    else:
        await message.reply("Failed to update poster. Please try again.")

async def process_first_file_input(client: Client, message: Message):
    user_id = message.from_user.id
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    
    # Get message ID and channel ID
    channel_id, message_id = await get_message_id(client, message)
    
    if channel_id and message_id:
        temp_admin_data[user_id]["first_file_id"] = message_id
        temp_admin_data[user_id]["channel_id"] = channel_id
        
        # Delete the forwarded message
        try:
            await message.delete()
        except Exception as e:
            logger.warning(f"Failed to delete forwarded message: {e}")
        
        # Ask for last file
        ask_msg = await client.send_message(
            user_id,
            f"Forward me the last file (with tag) for {temp_admin_data[user_id].get('current_language')}-{temp_admin_data[user_id].get('current_season')}-{temp_admin_data[user_id].get('current_quality')}\nGo to first file: https://t.me/c/{str(channel_id).replace('-100', '')}/{message_id}"
        )
        
        temp_admin_data[user_id]["state"] = "AWAITING_LAST_FILE"
        temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
    else:
        await message.reply("Invalid file. Please forward a valid file from a channel.")

async def process_last_file_input(client: Client, message: Message):
    user_id = message.from_user.id
    first_file_id = temp_admin_data[user_id].get("first_file_id")
    channel_id = temp_admin_data[user_id].get("channel_id")
    ask_message_id = temp_admin_data[user_id].get("ask_message_id")
    
    # Get message ID
    _, last_file_id = await get_message_id(client, message)
    
    if last_file_id:
        temp_admin_data[user_id]["last_file_id"] = last_file_id
        
        # Delete the forwarded message and ask message
        try:
            await message.delete()
            await client.delete_messages(user_id, ask_message_id)
        except Exception as e:
            logger.warning(f"Failed to delete messages: {e}")
        
        # Ask for codec
        reply_keyboard = ReplyKeyboardMarkup(
            [
                [KeyboardButton("H.264"), KeyboardButton("H.265")],
                [KeyboardButton("H.265 10bit")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        ask_msg = await client.send_message(
            user_id,
            f"Send me the codec field for {temp_admin_data[user_id].get('current_language')}-{temp_admin_data[user_id].get('current_season')}-{temp_admin_data[user_id].get('current_quality')}",
            reply_markup=reply_keyboard
        )
        
        temp_admin_data[user_id]["state"] = "AWAITING_CODEC_INPUT"
        temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
    else:
        await message.reply("Invalid file. Please forward a valid file from a channel.")
