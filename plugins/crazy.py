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
from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, TMDB_API_KEY, LOG_CHANNEL, DB_CHANNEL, RAW_DB_CHANNEL
from database.crazy_db import (
    add_series, get_series_by_key, update_series_field, add_or_update_language,
    get_languages, delete_language, add_or_update_season, get_seasons, delete_season,
    add_or_update_quality, get_qualities, get_quality_link, delete_quality,
    get_poster_file_id, update_poster_file_id, publish_series, get_series
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
NO_POSTER_FOUND_IMG = "https://envs.sh/EMw.jpg"  # Fixed URL

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
    
    # Create the layout
    layout = []
    current_row = []
    
    for code in layout_pattern:
        if code in item_dict:
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

def create_flexible_layout(buttons, layout_pattern):
    """
    Create a flexible button layout based on a pattern.
    
    Args:
        buttons: List of InlineKeyboardButton objects
        layout_pattern: List of strings representing the layout pattern
                       Each string is a comma-separated list of indices (0-based) for buttons in that row
                       Example: ["0,1", "2", "3,4,5"] would create:
                           Row 1: buttons[0], buttons[1]
                           Row 2: buttons[2]
                           Row 3: buttons[3], buttons[4], buttons[5]
    
    Returns:
        List of lists of InlineKeyboardButton objects
    """
    layout = []
    for row_pattern in layout_pattern:
        row = []
        indices = row_pattern.split(',')
        for idx in indices:
            try:
                button_index = int(idx.strip())
                if 0 <= button_index < len(buttons):
                    row.append(buttons[button_index])
            except ValueError:
                pass
        if row:
            layout.append(row)
    return layout

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
    
    # Create layout with single buttons per row
    layout = [[button] for button in buttons]
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

    # Define the layout pattern for series details - single buttons per row
    buttons = [
        InlineKeyboardButton("✏️ Edit Details", callback_data="edit_details"),
        InlineKeyboardButton("🌐 Languages", callback_data="manage_languages"),
        InlineKeyboardButton("🖼️ Change Poster", callback_data="change_poster"),
        InlineKeyboardButton("📤 Publish Series", callback_data="publish_series"),
        InlineKeyboardButton("⬅️ Back", callback_data="back_to_search")
    ]
    
    layout = [[button] for button in buttons]
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

async def send_language_management_message(client: Client, user_id: int, series_key: str, message_id: int):
    logger.info(f"Sending language management message to user {user_id}")
    series_data = get_series_by_key(series_key)
    if not series_data:
        logger.warning(f"Series not found for key: {series_key}")
        await client.send_message(user_id, "Series not found.")
        return

    languages = series_data.get("languages", [])
    
    text = f"**Series:** `{series_data.get('title', 'N/A')}`\n\n"
    text += "Select any Language group to manage. Or click '+' button to add new Language group.\n\n"

    # Create buttons for languages
    item_buttons = []
    for i, lang in enumerate(languages):
        item_buttons.append(InlineKeyboardButton(
            f"{lang['name']} ({len(lang.get('seasons', []))} Seasons)", 
            callback_data=f"lang_{i}"
        ))
    
    # Action buttons
    action_buttons = [
        InlineKeyboardButton("+ Add Language", callback_data="add_language"),
        InlineKeyboardButton("⬅️ Back to Series", callback_data="back_to_series")
    ]
    
    # Define flexible layout pattern for languages
    # Example: ["0,1", "2", "3,4,5"] would create:
    # Row 1: buttons[0], buttons[1]
    # Row 2: buttons[2]
    # Row 3: buttons[3], buttons[4], buttons[5]
    # Adjust this pattern to control button positions
    if len(item_buttons) >= 6:
        layout_pattern = ["0,1", "2,3", "4,5"]
    elif len(item_buttons) >= 4:
        layout_pattern = ["0,1", "2,3"]
    elif len(item_buttons) >= 2:
        layout_pattern = ["0,1"]
    else:
        layout_pattern = ["0"] if item_buttons else []
    
    # Create layout for item buttons
    layout = create_flexible_layout(item_buttons, layout_pattern)
    
    # Add action buttons as a new row
    if action_buttons:
        layout.append(action_buttons)
    
    reply_markup = InlineKeyboardMarkup(layout)

    poster_to_use = series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG

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

async def send_season_management_message(client: Client, user_id: int, series_key: str, language_name: str, message_id: int):
    logger.info(f"Sending season management message to user {user_id}")
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
    
    text = (
        f"**Series:** `{series_data.get('title', 'N/A')}`\n"
        f"**Language:** `{language_name}`\n\n"
        "Select any Seasons group to manage. Or click '+' button to add new Seasons group.\n\n"
    )

    # Create buttons for seasons
    item_buttons = []
    for i, season in enumerate(seasons):
        item_buttons.append(InlineKeyboardButton(
            f"{season['name']} ({len(season.get('qualities', []))} Qualities)", 
            callback_data=f"season_{i}"
        ))
    
    # Action buttons
    action_buttons = [
        InlineKeyboardButton("+ Add Season", callback_data="add_season"),
        InlineKeyboardButton("🖼️ Change Poster", callback_data="change_lang_poster"),
        InlineKeyboardButton(f"🗑️ Delete '{language_name}'", callback_data="delete_language"),
        InlineKeyboardButton("⬅️ Back to Languages", callback_data="back_to_languages")
    ]
    
    # Define flexible layout pattern for seasons
    if len(item_buttons) >= 6:
        layout_pattern = ["0,1", "2,3", "4,5"]
    elif len(item_buttons) >= 4:
        layout_pattern = ["0,1", "2,3"]
    elif len(item_buttons) >= 2:
        layout_pattern = ["0,1"]
    else:
        layout_pattern = ["0"] if item_buttons else []
    
    # Create layout for item buttons
    layout = create_flexible_layout(item_buttons, layout_pattern)
    
    # Add action buttons as a new row
    if action_buttons:
        layout.append(action_buttons)
    
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

async def send_quality_management_message(client: Client, user_id: int, series_key: str, language_name: str, season_name: str, message_id: int):
    logger.info(f"Sending quality management message to user {user_id}")
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
    
    text = (
        f"**Series:** `{series_data.get('title', 'N/A')}`\n"
        f"**Language:** `{language_name}`\n"
        f"**Season:** `{season_name}`\n\n"
        "Select any Quality group to manage. Or click '+' button to add new Quality group.\n\n"
    )

    # Create buttons for qualities
    item_buttons = []
    for i, quality in enumerate(qualities):
        item_buttons.append(InlineKeyboardButton(
            f"{quality['name']}", 
            callback_data=f"quality_{i}"
        ))
    
    # Action buttons
    action_buttons = [
        InlineKeyboardButton("+ Add Quality", callback_data="add_quality"),
        InlineKeyboardButton("🖼️ Change Poster", callback_data="change_season_poster"),
        InlineKeyboardButton(f"🗑️ Delete '{season_name}'", callback_data="delete_season"),
        InlineKeyboardButton("⬅️ Back to Seasons", callback_data="back_to_seasons")
    ]
    
    # Define flexible layout pattern for qualities
    if len(item_buttons) >= 6:
        layout_pattern = ["0,1", "2,3", "4,5"]
    elif len(item_buttons) >= 4:
        layout_pattern = ["0,1", "2,3"]
    elif len(item_buttons) >= 2:
        layout_pattern = ["0,1"]
    else:
        layout_pattern = ["0"] if item_buttons else []
    
    # Create layout for item buttons
    layout = create_flexible_layout(item_buttons, layout_pattern)
    
    # Add action buttons as a new row
    if action_buttons:
        layout.append(action_buttons)
    
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
        await message.reply_photo(
            photo=NO_POSTER_FOUND_IMG,
            caption="Usage: `/newseriesui <series_title>`",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 Search Again", callback_data="newseriesui_retry")]
            ])
        )
        return

    async with get_admin_lock(user_id):
        # Send initial message with fixed photo
        temp_msg = await message.reply_photo(
            photo=NO_POSTER_FOUND_IMG,
            caption="Searching TMDB and IMDb, please wait..."
        )
        
        # Fetch results
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
            await temp_msg.edit_caption(
                caption="No results found on TMDB or IMDb for the provided series name.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 Search Again", callback_data="newseriesui_retry")]
                ])
            )
            return

        # Store data in temp_admin_data
        temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
        temp_admin_data[user_id]["search_results"] = all_results
        temp_admin_data[user_id]["query"] = query
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SEARCH_RESULTS"
        temp_admin_data[user_id]["main_message_id"] = temp_msg.id

        # Edit message with results and single buttons per row
        await send_series_selection_message(client, user_id, query, all_results, temp_msg.id)

@Client.on_message(filters.command('editseries') & filters.user(ADMINS))
async def edit_series_command(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} started edit series UI")
    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None

    if not query:
        await message.reply_photo(
            photo=NO_POSTER_FOUND_IMG,
            caption="Usage: `/editseries <series_title>`",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 Search Again", callback_data="editseries_retry")]
            ])
        )
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
                # Create buttons for series details
                buttons = [
                    InlineKeyboardButton("✏️ Edit Details", callback_data="edit_details"),
                    InlineKeyboardButton("🌐 Languages", callback_data="manage_languages"),
                    InlineKeyboardButton("🖼️ Change Poster", callback_data="change_poster"),
                    InlineKeyboardButton("📤 Publish Series", callback_data="publish_series"),
                    InlineKeyboardButton("⬅️ Back", callback_data="editseries_retry")
                ]
                
                layout = [[button] for button in buttons]
                reply_markup = InlineKeyboardMarkup(layout)
                
                poster_file_id = get_poster_file_id(series_key) or NO_POSTER_FOUND_IMG
                
                text = (
                    f"**Title:** `{series_data.get('title', 'N/A')}`\n"
                    f"**Released On:** `{series_data.get('released_on', 'N/A')}`\n"
                    f"**Genre:** `{series_data.get('genre', 'N/A')}`\n"
                    f"**Rating:** `{series_data.get('rating', 'N/A')}`\n"
                    f"**TMDB ID:** `{series_data.get('tmdb_id', 'N/A')}`\n"
                    f"**Media Type:** `{series_data.get('media_type', 'N/A').upper()}`\n\n"
                )
                
                msg = await message.reply_photo(
                    photo=poster_file_id,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=enums.ParseMode.MARKDOWN
                )
                
                temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
                temp_admin_data[user_id]["current_series_key"] = series_key
                temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SERIES_DETAILS"
                temp_admin_data[user_id]["main_message_id"] = msg.id
                return
        
        # Try exact match by title
        for s_info in series_list:
            if s_info['title'].lower() == query.lower():
                series_key = s_info['_id']
                series_data = get_series_by_key(series_key)
                if series_data:
                    # Create buttons for series details
                    buttons = [
                        InlineKeyboardButton("✏️ Edit Details", callback_data="edit_details"),
                        InlineKeyboardButton("🌐 Languages", callback_data="manage_languages"),
                        InlineKeyboardButton("🖼️ Change Poster", callback_data="change_poster"),
                        InlineKeyboardButton("📤 Publish Series", callback_data="publish_series"),
                        InlineKeyboardButton("⬅️ Back", callback_data="editseries_retry")
                    ]
                    
                    layout = [[button] for button in buttons]
                    reply_markup = InlineKeyboardMarkup(layout)
                    
                    poster_file_id = get_poster_file_id(series_key) or NO_POSTER_FOUND_IMG
                    
                    text = (
                        f"**Title:** `{series_data.get('title', 'N/A')}`\n"
                        f"**Released On:** `{series_data.get('released_on', 'N/A')}`\n"
                        f"**Genre:** `{series_data.get('genre', 'N/A')}`\n"
                        f"**Rating:** `{series_data.get('rating', 'N/A')}`\n"
                        f"**TMDB ID:** `{series_data.get('tmdb_id', 'N/A')}`\n"
                        f"**IMDb ID:** `{series_data.get('imdb_id', 'N/A')}`\n"
                        f"**Media Type:** `{series_data.get('media_type', 'N/A').upper()}`\n\n"
                    )
                    
                    msg = await message.reply_photo(
                        photo=poster_file_id,
                        caption=text,
                        reply_markup=reply_markup,
                        parse_mode=enums.ParseMode.MARKDOWN
                    )
                    
                    temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
                    temp_admin_data[user_id]["current_series_key"] = series_key
                    temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SERIES_DETAILS"
                    temp_admin_data[user_id]["main_message_id"] = msg.id
                    return
        
        # If no exact match, show close matches
        close_matches = find_most_similar_title(query, series_names)
        if not close_matches:
            await message.reply_photo(
                photo=NO_POSTER_FOUND_IMG,
                caption="No series found with that name.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 Search Again", callback_data="editseries_retry")]
                ])
            )
            return
        
        buttons = []
        for match in close_matches[:5]:  # Limit to 5 matches
            s_info = next((s for s in series_list if s['title'] == match), None)
            if s_info:
                buttons.append(InlineKeyboardButton(match, callback_data=f"edit_sel_{s_info['_id']}"))
        
        buttons.append(InlineKeyboardButton("🔍 Search Again", callback_data="editseries_retry"))
        
        # Create layout with single buttons per row
        layout = [[button] for button in buttons]
        reply_markup = InlineKeyboardMarkup(layout)
        
        msg = await message.reply_photo(
            photo=NO_POSTER_FOUND_IMG,
            caption="Select a series to edit:",
            reply_markup=reply_markup
        )
        
        temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
        temp_admin_data[user_id]["state"] = "EDIT_SERIES_SELECTING"
        temp_admin_data[user_id]["main_message_id"] = msg.id

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
    
    if current_state == "NEW_SERIES_UI_AWAITING_LANGUAGE_INPUT":
        await process_language_input(client, message, message.text.strip())
    elif current_state == "NEW_SERIES_UI_AWAITING_SEASON_INPUT":
        await process_season_input(client, message, message.text.strip())
    elif current_state == "NEW_SERIES_UI_AWAITING_QUALITY_INPUT":
        await process_quality_input(client, message, message.text.strip())
    elif current_state.startswith("NEW_SERIES_UI_EDITING_"):
        field = temp_admin_data[user_id].get("current_field")
        await process_field_edit(client, message, message.text.strip(), field)

async def handle_admin_media_input(client: Client, message: Message):
    user_id = message.from_user.id
    current_state = temp_admin_data.get(user_id, {}).get("state")
    logger.info(f"Processing admin media input in state: {current_state}")
    
    if current_state == "NEW_SERIES_UI_AWAITING_SERIES_POSTER":
        await process_poster_input(client, message, "series")
    elif current_state == "NEW_SERIES_UI_AWAITING_LANGUAGE_POSTER":
        await process_poster_input(client, message, "language")
    elif current_state == "NEW_SERIES_UI_AWAITING_SEASON_POSTER":
        await process_poster_input(client, message, "season")
    elif current_state == "NEW_SERIES_UI_AWAITING_FIRST_FILE":
        await process_first_file_input(client, message)
    elif current_state == "NEW_SERIES_UI_AWAITING_LAST_FILE":
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
    
    # Handle series selection callbacks
    if data.startswith("sel_"):
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
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SERIES_DETAILS"
    
    # Handle edit series selection
    elif data.startswith("edit_sel_"):
        series_key = data.split("_", 1)[1]
        series_data = get_series_by_key(series_key)
        if not series_data:
            await callback_query.answer("Series not found.", show_alert=True)
            return
        
        await callback_query.answer("Loading series details...")
        temp_admin_data[user_id]["current_series_key"] = series_key
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SERIES_DETAILS"
        
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
    
    elif data == "back_to_series":
        series_key = temp_admin_data[user_id].get("current_series_key")
        series_data = get_series_by_key(series_key)
        if not series_data:
            await callback_query.answer("Series not found.", show_alert=True)
            return
        
        await callback_query.answer("Going back to series details...")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SERIES_DETAILS"
        await send_series_details_message(client, user_id, series_data, main_message_id)
    
    # Handle management callbacks
    elif data == "manage_languages":
        series_key = temp_admin_data[user_id].get("current_series_key")
        await callback_query.answer("Managing languages...")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_LANGUAGES"
        await send_language_management_message(client, user_id, series_key, main_message_id)
    
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
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_AWAITING_LANGUAGE_INPUT"
        temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
    
    elif data.startswith("lang_"):  # Language selection
        series_key = temp_admin_data[user_id].get("current_series_key")
        lang_index = int(data.split("_", 1)[1])
        languages = get_languages(series_key)
        
        if 0 <= lang_index < len(languages):
            language_name = languages[lang_index]["name"]
            await callback_query.answer(f"Selected: {language_name}")
            temp_admin_data[user_id]["current_language"] = language_name
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_SEASONS"
            await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
        else:
            await callback_query.answer("Invalid selection.", show_alert=True)
    
    elif data == "back_to_languages":
        series_key = temp_admin_data[user_id].get("current_series_key")
        await callback_query.answer("Going back to languages...")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_LANGUAGES"
        await send_language_management_message(client, user_id, series_key, main_message_id)
    
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
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_AWAITING_SEASON_INPUT"
        temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
    
    elif data.startswith("season_"):  # Season selection
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_index = int(data.split("_", 1)[1])
        seasons = get_seasons(series_key, language_name)
        
        if 0 <= season_index < len(seasons):
            season_name = seasons[season_index]["name"]
            await callback_query.answer(f"Selected: {season_name}")
            temp_admin_data[user_id]["current_season"] = season_name
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_QUALITIES"
            await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
        else:
            await callback_query.answer("Invalid selection.", show_alert=True)
    
    elif data == "back_to_seasons":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        await callback_query.answer("Going back to seasons...")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_SEASONS"
        await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
    
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
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_AWAITING_QUALITY_INPUT"
        temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
    
    elif data.startswith("quality_"):  # Quality selection
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        quality_index = int(data.split("_", 1)[1])
        qualities = get_qualities(series_key, language_name, season_name)
        
        if 0 <= quality_index < len(qualities):
            quality_name = qualities[quality_index]["name"]
            await callback_query.answer(f"Selected: {quality_name}")
            temp_admin_data[user_id]["current_quality"] = quality_name
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_AWAITING_FIRST_FILE"
            
            await client.send_message(
                user_id,
                f"Forward me the first file (with tag) for {language_name}-{season_name}-{quality_name}"
            )
        else:
            await callback_query.answer("Invalid selection.", show_alert=True)
    
    elif data == "change_poster":
        series_key = temp_admin_data[user_id].get("current_series_key")
        await callback_query.answer("Send a new poster...")
        
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_AWAITING_SERIES_POSTER"
        temp_admin_data[user_id]["current_series_key"] = series_key
        
        await client.send_message(
            user_id,
            "Please send a photo or video to use as the series poster:"
        )
    
    elif data == "change_lang_poster":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        await callback_query.answer("Send a new poster...")
        
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_AWAITING_LANGUAGE_POSTER"
        temp_admin_data[user_id]["current_series_key"] = series_key
        temp_admin_data[user_id]["current_language"] = language_name
        
        await client.send_message(
            user_id,
            f"Please send a photo or video to use as the poster for {language_name}:"
        )
    
    elif data == "change_season_poster":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        await callback_query.answer("Send a new poster...")
        
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_AWAITING_SEASON_POSTER"
        temp_admin_data[user_id]["current_series_key"] = series_key
        temp_admin_data[user_id]["current_language"] = language_name
        temp_admin_data[user_id]["current_season"] = season_name
        
        await client.send_message(
            user_id,
            f"Please send a photo or video to use as the poster for {language_name}-{season_name}:"
        )
    
    elif data == "delete_language":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        
        await callback_query.answer(f"Deleting {language_name}...")
        
        if delete_language(series_key, language_name):
            await callback_query.answer(f"Deleted {language_name} successfully.")
            await send_language_management_message(client, user_id, series_key, main_message_id)
        else:
            await callback_query.answer("Failed to delete language.", show_alert=True)
    
    elif data == "delete_season":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        
        await callback_query.answer(f"Deleting {season_name}...")
        
        if delete_season(series_key, language_name, season_name):
            await callback_query.answer(f"Deleted {season_name} successfully.")
            await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
        else:
            await callback_query.answer("Failed to delete season.", show_alert=True)
    
    elif data == "publish_series":
        series_key = temp_admin_data[user_id].get("current_series_key")
        series_data = get_series_by_key(series_key)
        
        if not series_data:
            await callback_query.answer("Series not found.", show_alert=True)
            return
        
        await callback_query.answer("Publishing series...")
        
        if publish_series(series_key):
            await callback_query.answer("Series published successfully.")
            # Update the series data to reflect published status
            series_data["published"] = True
            await send_series_details_message(client, user_id, series_data, main_message_id)
        else:
            await callback_query.answer("Failed to publish series.", show_alert=True)
    
    elif data == "edit_details":
        series_key = temp_admin_data[user_id].get("current_series_key")
        series_data = get_series_by_key(series_key)
        
        if not series_data:
            await callback_query.answer("Series not found.", show_alert=True)
            return
        
        await callback_query.answer("Editing series details...")
        
        # Create buttons for editable fields
        buttons = [
            InlineKeyboardButton("Title", callback_data="edit_field_title"),
            InlineKeyboardButton("Released On", callback_data="edit_field_released_on"),
            InlineKeyboardButton("Genre", callback_data="edit_field_genre"),
            InlineKeyboardButton("Rating", callback_data="edit_field_rating"),
            InlineKeyboardButton("TMDB ID", callback_data="edit_field_tmdb_id"),
            InlineKeyboardButton("IMDb ID", callback_data="edit_field_imdb_id"),
            InlineKeyboardButton("Media Type", callback_data="edit_field_media_type"),
            InlineKeyboardButton("⬅️ Back", callback_data="back_to_series")
        ]
        
        layout = [[button] for button in buttons]
        reply_markup = InlineKeyboardMarkup(layout)
        
        text = (
            f"**Current Series Details:**\n\n"
            f"**Title:** `{series_data.get('title', 'N/A')}`\n"
            f"**Released On:** `{series_data.get('released_on', 'N/A')}`\n"
            f"**Genre:** `{series_data.get('genre', 'N/A')}`\n"
            f"**Rating:** `{series_data.get('rating', 'N/A')}`\n"
            f"**TMDB ID:** `{series_data.get('tmdb_id', 'N/A')}`\n"
            f"**IMDb ID:** `{series_data.get('imdb_id', 'N/A')}`\n"
            f"**Media Type:** `{series_data.get('media_type', 'N/A').upper()}`\n\n"
            "Select a field to edit:"
        )
        
        poster_file_id = get_poster_file_id(series_key) or NO_POSTER_FOUND_IMG
        
        try:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=main_message_id,
                media=InputMediaPhoto(media=poster_file_id, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=reply_markup
            )
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_EDITING_DETAILS"
        except Exception as e:
            logger.error(f"Error editing series details: {e}")
            await callback_query.answer("Error editing series details.", show_alert=True)
    
    elif data.startswith("edit_field_"):
        field = data.split("_", 1)[1]
        series_key = temp_admin_data[user_id].get("current_series_key")
        series_data = get_series_by_key(series_key)
        
        if not series_data:
            await callback_query.answer("Series not found.", show_alert=True)
            return
        
        await callback_query.answer(f"Editing {field}...")
        
        temp_admin_data[user_id]["state"] = f"NEW_SERIES_UI_EDITING_{field.upper()}"
        temp_admin_data[user_id]["current_field"] = field
        
        field_value = series_data.get(field, 'N/A')
        
        await client.send_message(
            user_id,
            f"Current {field}: `{field_value}`\n\nEnter new value for {field}:"
        )
    
    # Handle retry callbacks
    elif data == "newseriesui_retry":
        await callback_query.answer("Starting new search...")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_INITIAL"
        await callback_query.message.delete()
        await client.send_message(
            user_id,
            "Please send the series name you want to add:",
            reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True)
        )
    
    elif data == "editseries_retry":
        await callback_query.answer("Starting new search...")
        temp_admin_data[user_id]["state"] = "EDIT_SERIES_INITIAL"
        await callback_query.message.delete()
        await client.send_message(
            user_id,
            "Please send the series name you want to edit:",
            reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True)
        )

# Process input functions
async def process_language_input(client: Client, message: Message, language_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    
    if not language_name:
        await message.reply("Language name cannot be empty.")
        return
    
    # Add or update language
    if add_or_update_language(series_key, language_name):
        await message.reply(f"Language '{language_name}' added/updated successfully.")
        
        # Delete the ask message if exists
        ask_msg_id = temp_admin_data[user_id].get("ask_message_id")
        if ask_msg_id:
            try:
                await client.delete_messages(user_id, ask_msg_id)
            except Exception as e:
                logger.warning(f"Failed to delete ask message: {e}")
        
        # Go back to language management
        main_message_id = temp_admin_data[user_id].get("main_message_id")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_LANGUAGES"
        await send_language_management_message(client, user_id, series_key, main_message_id)
    else:
        await message.reply("Failed to add/update language.")

async def process_season_input(client: Client, message: Message, season_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    
    if not season_name:
        await message.reply("Season name cannot be empty.")
        return
    
    # Add or update season
    if add_or_update_season(series_key, language_name, season_name):
        await message.reply(f"Season '{season_name}' added/updated successfully.")
        
        # Delete the ask message if exists
        ask_msg_id = temp_admin_data[user_id].get("ask_message_id")
        if ask_msg_id:
            try:
                await client.delete_messages(user_id, ask_msg_id)
            except Exception as e:
                logger.warning(f"Failed to delete ask message: {e}")
        
        # Go back to season management
        main_message_id = temp_admin_data[user_id].get("main_message_id")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_SEASONS"
        await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
    else:
        await message.reply("Failed to add/update season.")

async def process_quality_input(client: Client, message: Message, quality_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    
    if not quality_name:
        await message.reply("Quality name cannot be empty.")
        return
    
    # Add or update quality
    if add_or_update_quality(series_key, language_name, season_name, quality_name, ""):
        await message.reply(f"Quality '{quality_name}' added successfully. Now forward the first file.")
        
        # Delete the ask message if exists
        ask_msg_id = temp_admin_data[user_id].get("ask_message_id")
        if ask_msg_id:
            try:
                await client.delete_messages(user_id, ask_msg_id)
            except Exception as e:
                logger.warning(f"Failed to delete ask message: {e}")
        
        # Set state to wait for first file
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_AWAITING_FIRST_FILE"
        temp_admin_data[user_id]["current_quality"] = quality_name
    else:
        await message.reply("Failed to add quality.")

async def process_poster_input(client: Client, message: Message, poster_type: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    
    # Download and upload poster
    poster_file_id = await download_and_upload_poster(client, message=message)
    
    if not poster_file_id:
        await message.reply("Failed to process the poster. Please try again.")
        return
    
    if poster_type == "series":
        update_series_field(series_key, "poster_file_id", poster_file_id)
        await message.reply("Series poster updated successfully.")
    elif poster_type == "language":
        language_name = temp_admin_data[user_id].get("current_language")
        if add_or_update_language(series_key, language_name, poster_file_id=poster_file_id):
            await message.reply(f"Poster for {language_name} updated successfully.")
        else:
            await message.reply("Failed to update language poster.")
    elif poster_type == "season":
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        if add_or_update_season(series_key, language_name, season_name, poster_file_id=poster_file_id):
            await message.reply(f"Poster for {language_name}-{season_name} updated successfully.")
        else:
            await message.reply("Failed to update season poster.")
    
    # Go back to the previous screen
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    if poster_type == "series":
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SERIES_DETAILS"
        series_data = get_series_by_key(series_key)
        await send_series_details_message(client, user_id, series_data, main_message_id)
    elif poster_type == "language":
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_SEASONS"
        await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
    elif poster_type == "season":
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_QUALITIES"
        await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)

async def process_first_file_input(client: Client, message: Message):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    quality_name = temp_admin_data[user_id].get("current_quality")
    
    # Get the message ID of the forwarded file
    if message.forward_from:
        # If forwarded from a user, we need to get the original message ID
        original_chat_id = message.forward_from.id
        original_message_id = message.forward_from_message_id
        
        # Get the message from the original chat
        try:
            original_msg = await client.get_messages(original_chat_id, original_message_id)
            if original_msg:
                message_id = original_msg.id
            else:
                message_id = message.id
        except Exception:
            message_id = message.id
    else:
        message_id = message.id
    
    # Update the quality with the first file ID
    if add_or_update_quality(series_key, language_name, season_name, quality_name, str(message_id)):
        await message.reply(f"First file for {quality_name} added successfully. Now forward the last file.")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_AWAITING_LAST_FILE"
    else:
        await message.reply("Failed to add first file.")

async def process_last_file_input(client: Client, message: Message):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    quality_name = temp_admin_data[user_id].get("current_quality")
    
    # Get the message ID of the forwarded file
    if message.forward_from:
        # If forwarded from a user, we need to get the original message ID
        original_chat_id = message.forward_from.id
        original_message_id = message.forward_from_message_id
        
        # Get the message from the original chat
        try:
            original_msg = await client.get_messages(original_chat_id, original_message_id)
            if original_msg:
                message_id = original_msg.id
            else:
                message_id = message.id
        except Exception:
            message_id = message.id
    else:
        message_id = message.id
    
    # Get the current quality data
    quality_data = get_quality_link(series_key, language_name, season_name, quality_name)
    if not quality_data:
        await message.reply("Quality not found.")
        return
    
    first_file_id = quality_data.get("first_file_id")
    
    # Update the quality with the last file ID
    if add_or_update_quality(series_key, language_name, season_name, quality_name, first_file_id, str(message_id)):
        await message.reply(f"Last file for {quality_name} added successfully.")
        
        # Go back to quality management
        main_message_id = temp_admin_data[user_id].get("main_message_id")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_QUALITIES"
        await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
    else:
        await message.reply("Failed to add last file.")

async def process_field_edit(client: Client, message: Message, new_value: str, field: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    
    if not new_value:
        await message.reply("Value cannot be empty.")
        return
    
    # Update the field
    if update_series_field(series_key, field, new_value):
        await message.reply(f"{field} updated successfully.")
        
        # Go back to series details
        main_message_id = temp_admin_data[user_id].get("main_message_id")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SERIES_DETAILS"
        series_data = get_series_by_key(series_key)
        await send_series_details_message(client, user_id, series_data, main_message_id)
    else:
        await message.reply(f"Failed to update {field}.")