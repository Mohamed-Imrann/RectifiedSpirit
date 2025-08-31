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
from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, TMDB_API_KEY, LOG_CHANNEL, DB_CHANNEL, RAW_DB_CHANNEL, NO_POSTER_FOUND_IMG, Assigned
from database.crazy_db import (
    add_series, get_series_by_key, update_series_field, add_or_update_language,
    get_languages, delete_language, add_or_update_season, get_seasons, delete_season,
    add_or_update_quality, get_qualities, get_quality_link, delete_quality,
    get_poster_file_id, update_poster_file_id, publish_series, episodes_collection,
    add_admin_assignment, remove_admin_assignment, get_admin_assignments,
    update_language_poster, update_season_poster, update_language_season_layout,
    update_season_quality_layout, update_quality_codec, update_quality_link_key,
    get_quality_link_key
)
from utils import (
    get_message_id, get_messages, delete_messages_from_user_chat, 
    get_poster, find_most_similar_title, get_file_id
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
imdb = Cinemagoer()
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

# Helper function to check if admin is assigned
def is_admin_assigned(user_id):
    """Check if user is an assigned admin"""
    # Super admins always have permission
    if user_id in ADMINS:
        return True
    
    # Check if user is in Assigned dictionary
    return user_id in Assigned

# Helper functions
async def DeleteMessage(msg):
    await asyncio.sleep(600)
    try:
        await msg.delete()
        logger.debug(f"Deleted message {msg.id} from chat {msg.chat.id}")
    except Exception as e:
        logger.warning(f"Failed to delete message {msg.id}: {e}")

# Dynamic keyboard builder
def build_dynamic_keyboard(items, layout_pattern, category, add_buttons=None):
    """
    Build a dynamic inline keyboard with items and + buttons.
    
    Args:
        items: List of item dicts (each must have 'name')
        layout_pattern: List of integers representing the number of items in each row
        category: String to identify the category (e.g., 'language', 'season', 'quality')
        add_buttons: List of tuples (text, callback_data) for additional buttons
        
    Returns:
        InlineKeyboardMarkup
    """
    rows = []
    item_index = 0
    
    # Build rows according to layout_pattern
    for row_index, row_count in enumerate(layout_pattern):
        row = []
        # Add items for this row
        for i in range(row_count):
            if item_index < len(items):
                item = items[item_index]
                # Callback for removing this item
                callback_data = f"remove:{category}:{item_index}"
                row.append(InlineKeyboardButton(text=item['name'], callback_data=callback_data))
                item_index += 1
            else:
                break
        # Add a '+' button for this row
        callback_data = f"add:{category}:{row_index}"
        row.append(InlineKeyboardButton(text="+", callback_data=callback_data))
        rows.append(row)
    
    # If there are remaining items, add them in rows of up to 3
    while item_index < len(items):
        row = []
        # Add up to 3 items
        for i in range(3):
            if item_index < len(items):
                item = items[item_index]
                callback_data = f"remove:{category}:{item_index}"
                row.append(InlineKeyboardButton(text=item['name'], callback_data=callback_data))
                item_index += 1
            else:
                break
        # If we have less than 3 in this row, we can add the '+' here
        if len(row) < 3:
            callback_data = f"add:{category}:{len(rows)}"
            row.append(InlineKeyboardButton(text="+", callback_data=callback_data))
        else:
            # We have 3, so we need to put the '+' in a new row
            rows.append(row)
            row = [InlineKeyboardButton(text="+", callback_data=f"add:{category}:{len(rows)}")]
        rows.append(row)
    
    # Add a standalone '+' button for adding a new row
    callback_data = f"add:{category}:{len(rows)}"
    rows.append([InlineKeyboardButton(text="+", callback_data=callback_data)])
    
    # Add additional buttons
    if add_buttons:
        for button_text, callback_data in add_buttons:
            rows.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
    
    return InlineKeyboardMarkup(rows)

def create_user_layout_from_pattern(items: List[str], layout_pattern: List[int]) -> List[List[InlineKeyboardButton]]:
    """
    Create a user-facing layout without + buttons.
    
    Args:
        items: List of item names
        layout_pattern: List of integers representing buttons per row
    
    Returns:
        List of lists of InlineKeyboardButton objects
    """
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
    
    # Add remaining items
    while item_index < len(items):
        row = []
        for _ in range(min(2, len(items) - item_index)):  # Max 2 per row for remaining
            item_button = InlineKeyboardButton(items[item_index], callback_data=f"user_item_{item_index}")
            row.append(item_button)
            item_index += 1
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
            poster_url = f"{TMDB_IMAGE_BASE_URL}{poster_path}" if poster_path else NO_POSTER_FOUND_IMG[0]

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
        buttons.append(InlineKeyboardButton(button_text, callback_data=f"sel_{unique_id}"))
    
    buttons.append(InlineKeyboardButton("🔍 Search Again", callback_data="search_again"))
    
    # Create layout with 1 button per row for better readability
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
            logger.debug(f"Edited series selection message {message_id}")
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=NO_POSTER_FOUND_IMG[0],
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            logger.debug(f"Sent new series selection message {msg.id}")
            return msg.id
    except Exception as e:
        logger.error(f"Error sending series selection message: {e}")
        return None

async def send_series_details_message(client: Client, user_id: int, series_data: dict, message_id: int = None):
    logger.info(f"Sending series details message to user {user_id}")
    series_key = series_data['_id']
    poster_file_id = get_poster_file_id(series_key) or NO_POSTER_FOUND_IMG[0]

    text = (
        f"○ **Title:** `{series_data.get('title', 'N/A')}`\n"
        f"○ **Released On:** `{series_data.get('released_on', 'N/A')}`\n"
        f"○ **Genre:** `{series_data.get('genre', 'N/A')}`\n"
        f"○ **Rating:** `{series_data.get('rating', 'N/A')}`\n"
        f"○ **Media Type:** `{series_data.get('media_type', 'N/A').upper()}`\n\n"
    )

    buttons = [
        InlineKeyboardButton("🌐 Languages", callback_data="manage_languages"),
        InlineKeyboardButton("🖼️ Poster", callback_data="change_poster"),
        InlineKeyboardButton("📤 Publish", callback_data="publish_series")
    ]
    
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
    except Exception as e:
        logger.error(f"Error sending series details message: {e}")
        return None

async def send_language_management_message(client: Client, user_id: int, series_key: str, message_id: int):
    logger.info(f"Sending language management message to user {user_id}")
    series_data = get_series_by_key(series_key)
    if not series_data:
        logger.warning(f"Series not found for key: {series_key}")
        await client.send_message(user_id, "Series not found.")
        return

    languages = series_data.get("languages", [])
    language_layout = series_data.get("language_layout", [])
    
    text = f"**Series:** `{series_data.get('title', 'N/A')}`\n\n"
    text += "Select any Language group to add new Season/Part group inside them. Or click '+' button to add new Language group.\n\n"

    # Create dynamic layout with + buttons
    add_buttons = [
        ("⬅️ Back", "back_to_series")
    ]
    
    keyboard = build_dynamic_keyboard(
        items=languages,
        layout_pattern=language_layout,
        category="language",
        add_buttons=add_buttons
    )
    
    poster_to_use = series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG[0]

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=poster_to_use, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=keyboard
            )
            logger.debug(f"Edited language management message {message_id}")
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_to_use,
                caption=text,
                reply_markup=keyboard,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            logger.debug(f"Sent new language management message {msg.id}")
            return msg.id
    except Exception as e:
        logger.error(f"Error editing language management message: {e}")
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
    season_layout = current_lang.get("season_layout", [])
    
    text = (
        f"**Series:** `{series_data.get('title', 'N/A')}`\n"
        f"**Language:** `{language_name}`\n\n"
        "Select any Seasons group to add new Quality group into them. Or click '+' button to add new Seasons group.\n\n"
    )

    # Create dynamic layout with + buttons
    add_buttons = [
        ("🖼️ Change Poster for this Language", "change_lang_poster"),
        (f"🗑️ Delete '{language_name}' Group", "delete_language"),
        ("⬅️ Back", "back_to_languages")
    ]
    
    keyboard = build_dynamic_keyboard(
        items=seasons,
        layout_pattern=season_layout,
        category="season",
        add_buttons=add_buttons
    )
    
    poster_to_use = current_lang.get("poster_file_id") or series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG[0]

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=poster_to_use, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=keyboard
            )
            logger.debug(f"Edited season management message {message_id}")
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_to_use,
                caption=text,
                reply_markup=keyboard,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            logger.debug(f"Sent new season management message {msg.id}")
            return msg.id
    except Exception as e:
        logger.error(f"Error editing season management message: {e}")
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
    quality_layout = current_season.get("quality_layout", [])
    
    text = (
        f"**Series:** `{series_data.get('title', 'N/A')}`\n"
        f"**Language:** `{language_name}`\n"
        f"**Season:** `{season_name}`\n\n"
        "Select any Quality group to add new files into them. Or click '+' button to add new Quality group.\n\n"
    )

    # Create dynamic layout with + buttons
    add_buttons = [
        ("🖼️ Change Poster for this Season", "change_season_poster"),
        (f"🗑️ Delete '{season_name}' Group", "delete_season"),
        ("⬅️ Back", "back_to_seasons")
    ]
    
    keyboard = build_dynamic_keyboard(
        items=qualities,
        layout_pattern=quality_layout,
        category="quality",
        add_buttons=add_buttons
    )
    
    poster_to_use = current_season.get("poster_file_id") or current_lang.get("poster_file_id") or series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG[0]

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=poster_to_use, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=keyboard
            )
            logger.debug(f"Edited quality management message {message_id}")
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_to_use,
                caption=text,
                reply_markup=keyboard,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            logger.debug(f"Sent new quality management message {msg.id}")
            return msg.id
    except Exception as e:
        logger.error(f"Error editing quality management message: {e}")
        return None

# Command handlers
@Client.on_message(filters.command('newseriesui') & filters.user(ADMINS))
async def new_series_ui_command(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} started new series UI")
    
    # Check if admin is assigned
    if not is_admin_assigned(user_id):
        await message.reply("❌ You are not assigned to any channel. Contact the owner to get access.")
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

    await send_series_selection_message(client, user_id, query, all_results, temp_msg.id)

@Client.on_message(filters.command('assignadmin') & filters.user(ADMINS))
async def assign_admin_command(client: Client, message: Message):
    """Assign admin to channel"""
    if len(message.command) != 3:
        await message.reply("Usage: `/assignadmin <user_id> <channel_id>`")
        return
    
    try:
        user_id = int(message.command[1])
        channel_id = int(message.command[2])
    except ValueError:
        await message.reply("Invalid user_id or channel_id. Both must be integers.")
        return
    
    # Add to database
    if add_admin_assignment(user_id, channel_id):
        # Update global Assigned dictionary
        global Assigned
        Assigned[user_id] = channel_id
        
        await message.reply(f"✅ Admin {user_id} assigned to channel {channel_id}")
    else:
        await message.reply("❌ Failed to assign admin. Please try again.")

@Client.on_message(filters.command('unassignadmin') & filters.user(ADMINS))
async def unassign_admin_command(client: Client, message: Message):
    """Unassign admin"""
    if len(message.command) != 2:
        await message.reply("Usage: `/unassignadmin <user_id>`")
        return
    
    try:
        user_id = int(message.command[1])
    except ValueError:
        await message.reply("Invalid user_id. Must be an integer.")
        return
    
    # Remove from database
    if remove_admin_assignment(user_id):
        # Update global Assigned dictionary
        global Assigned
        if user_id in Assigned:
            del Assigned[user_id]
        
        await message.reply(f"✅ Admin {user_id} unassigned")
    else:
        await message.reply("❌ Failed to unassign admin. Please try again.")

@Client.on_message(filters.command('listadmins') & filters.user(ADMINS))
async def list_admins_command(client: Client, message: Message):
    """List all admin assignments"""
    admin_assignments = get_admin_assignments()
    
    if not admin_assignments:
        await message.reply("No admin assignments found.")
        return
    
    text = "**Admin Assignments:**\n\n"
    for user_id, channel_id in admin_assignments.items():
        text += f"• **User ID:** `{user_id}` → **Channel ID:** `{channel_id}`\n"
    
    await message.reply(text)

# Message handlers for admin UI
@Client.on_message(filters.text & filters.private & filters.user(ADMINS))
async def handle_admin_text_message(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Received admin text message {message.id} from user {user_id}")
    
    # Check if admin is assigned
    if not is_admin_assigned(user_id):
        await message.reply("❌ You are not assigned to any channel. Contact the owner to get access.")
        return
    
    if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
        await handle_admin_text_input(client, message)

@Client.on_message((filters.photo | filters.video | filters.document) & filters.private & filters.user(ADMINS))
async def handle_admin_media_message(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Received admin media message {message.id} from user {user_id}")
    
    # Check if admin is assigned
    if not is_admin_assigned(user_id):
        await message.reply("❌ You are not assigned to any channel. Contact the owner to get access.")
        return
    
    if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
        await handle_admin_media_input(client, message)

# Callback handlers for admin UI
@Client.on_callback_query(filters.user(ADMINS))
async def admin_ui_callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    logger.info(f"Received admin UI callback from user {user_id}: {data}")

    # Check if admin is assigned
    if not is_admin_assigned(user_id):
        await callback_query.answer("❌ You are not assigned to any channel.", show_alert=True)
        return
    
    await newui_callback_handler(client, callback_query)

# Process input functions
async def handle_admin_text_input(client: Client, message: Message):
    user_id = message.from_user.id
    current_state = temp_admin_data.get(user_id, {}).get("state")
    logger.info(f"Processing admin text input in state: {current_state}")
    
    if current_state == "AWAITING_LANGUAGE_INPUT":
        await process_add_input(client, message, "language")
    elif current_state == "AWAITING_SEASON_INPUT":
        await process_add_input(client, message, "season")
    elif current_state == "AWAITING_QUALITY_INPUT":
        await process_add_input(client, message, "quality")
    elif current_state == "AWAITING_CODEC_INPUT":
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
                'language_layout': [],
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
            update_series_field(series_key, "poster_file_id", NO_POSTER_FOUND_IMG[0])
            series_data["poster_file_id"] = NO_POSTER_FOUND_IMG[0]
        
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
        
        temp_admin_data[user_id]["state"] = "SEARCH_RESULTS"
        await send_series_selection_message(client, user_id, query, search_results, main_message_id)
    
    elif data == "back_to_series":
        series_key = temp_admin_data[user_id].get("current_series_key")
        series_data = get_series_by_key(series_key)
        if not series_data:
            await callback_query.answer("Series not found.", show_alert=True)
            return
        
        await callback_query.answer("Going back to series details...")
        temp_admin_data[user_id]["state"] = "SERIES_DETAILS"
        await send_series_details_message(client, user_id, series_data, main_message_id)
    
    # Handle management callbacks
    elif data == "manage_languages":
        series_key = temp_admin_data[user_id].get("current_series_key")
        await callback_query.answer("Managing languages...")
        temp_admin_data[user_id]["state"] = "MANAGE_LANGUAGES"
        await send_language_management_message(client, user_id, series_key, main_message_id)
    
    # Handle add and remove callbacks
    elif data.startswith("add:"):
        # Format: add:category:row_index
        parts = data.split(":")
        if len(parts) != 3:
            await callback_query.answer("Invalid add callback.", show_alert=True)
            return
        
        category = parts[1]
        try:
            row_index = int(parts[2])
        except ValueError:
            await callback_query.answer("Invalid row index.", show_alert=True)
            return
        
        # Set state to await input for this category and store the row_index
        user_id = callback_query.from_user.id
        temp_admin_data[user_id]["add_row_index"] = row_index
        temp_admin_data[user_id]["state"] = f"AWAITING_ADD_{category.upper()}"
        
        # Ask for the new value
        if category == "language":
            await client.send_message(user_id, "Enter the new language name:")
        elif category == "season":
            language_name = temp_admin_data[user_id].get("current_language")
            await client.send_message(user_id, f"Enter the new season name for {language_name}:")
        elif category == "quality":
            language_name = temp_admin_data[user_id].get("current_language")
            season_name = temp_admin_data[user_id].get("current_season")
            await client.send_message(user_id, f"Enter the new quality name for {language_name}-{season_name}:")
        
        await callback_query.answer()
    
    elif data.startswith("remove:"):
        # Format: remove:category:item_index
        parts = data.split(":")
        if len(parts) != 3:
            await callback_query.answer("Invalid remove callback.", show_alert=True)
            return
        
        category = parts[1]
        try:
            item_index = int(parts[2])
        except ValueError:
            await callback_query.answer("Invalid item index.", show_alert=True)
            return
        
        user_id = callback_query.from_user.id
        series_key = temp_admin_data[user_id].get("current_series_key")
        
        # Get the current data
        if category == "language":
            languages = get_languages(series_key)
            if 0 <= item_index < len(languages):
                language_name = languages[item_index]["name"]
                # Remove the language
                if delete_language(series_key, language_name):
                    await callback_query.answer(f"Language '{language_name}' removed.")
                    # Refresh the message
                    main_message_id = temp_admin_data[user_id].get("main_message_id")
                    await send_language_management_message(client, user_id, series_key, main_message_id)
                else:
                    await callback_query.answer("Failed to remove language.", show_alert=True)
            else:
                await callback_query.answer("Invalid language index.", show_alert=True)
        
        elif category == "season":
            language_name = temp_admin_data[user_id].get("current_language")
            seasons = get_seasons(series_key, language_name)
            if 0 <= item_index < len(seasons):
                season_name = seasons[item_index]["name"]
                if delete_season(series_key, language_name, season_name):
                    await callback_query.answer(f"Season '{season_name}' removed.")
                    main_message_id = temp_admin_data[user_id].get("main_message_id")
                    await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
                else:
                    await callback_query.answer("Failed to remove season.", show_alert=True)
            else:
                await callback_query.answer("Invalid season index.", show_alert=True)
        
        elif category == "quality":
            language_name = temp_admin_data[user_id].get("current_language")
            season_name = temp_admin_data[user_id].get("current_season")
            qualities = get_qualities(series_key, language_name, season_name)
            if 0 <= item_index < len(qualities):
                quality_name = qualities[item_index]["name"]
                if delete_quality(series_key, language_name, season_name, quality_name):
                    await callback_query.answer(f"Quality '{quality_name}' removed.")
                    main_message_id = temp_admin_data[user_id].get("main_message_id")
                    await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
                else:
                    await callback_query.answer("Failed to remove quality.", show_alert=True)
            else:
                await callback_query.answer("Invalid quality index.", show_alert=True)
    
    elif data.startswith("item_"):  # Item selection (for qualities)
        item_index = int(data.split("_")[1])
        current_state = temp_admin_data[user_id].get("state")
        
        if current_state == "MANAGE_QUALITIES":
            series_key = temp_admin_data[user_id].get("current_series_key")
            language_name = temp_admin_data[user_id].get("current_language")
            season_name = temp_admin_data[user_id].get("current_season")
            qualities = get_qualities(series_key, language_name, season_name)
            
            if 0 <= item_index < len(qualities):
                quality_name = qualities[item_index]["name"]
                await callback_query.answer(f"Selected: {quality_name}")
                temp_admin_data[user_id]["current_quality"] = quality_name
                temp_admin_data[user_id]["current_quality_index"] = item_index
                temp_admin_data[user_id]["state"] = "AWAITING_FIRST_FILE"
                
                await client.send_message(
                    user_id,
                    f"Forward the first file for {language_name}-{season_name}-{quality_name} from a channel where the bot is admin:"
                )
            else:
                await callback_query.answer("Invalid selection.", show_alert=True)
    
    elif data == "back_to_languages":
        series_key = temp_admin_data[user_id].get("current_series_key")
        await callback_query.answer("Going back to languages...")
        temp_admin_data[user_id]["state"] = "MANAGE_LANGUAGES"
        await send_language_management_message(client, user_id, series_key, main_message_id)
    
    elif data == "back_to_seasons":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        await callback_query.answer("Going back to seasons...")
        temp_admin_data[user_id]["state"] = "MANAGE_SEASONS"
        await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
    
    elif data == "change_poster":
        await callback_query.answer("Send a new poster...")
        temp_admin_data[user_id]["state"] = "AWAITING_SERIES_POSTER"
        await client.send_message(user_id, "Please send a photo or video to use as the series poster:")
    
    elif data == "change_lang_poster":
        await callback_query.answer("Send a new poster...")
        temp_admin_data[user_id]["state"] = "AWAITING_LANGUAGE_POSTER"
        language_name = temp_admin_data[user_id].get("current_language")
        await client.send_message(user_id, f"Please send a photo or video to use as the poster for {language_name}:")
    
    elif data == "change_season_poster":
        await callback_query.answer("Send a new poster...")
        temp_admin_data[user_id]["state"] = "AWAITING_SEASON_POSTER"
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        await client.send_message(user_id, f"Please send a photo or video to use as the poster for {language_name}-{season_name}:")
    
    elif data == "delete_language":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        await callback_query.answer(f"Deleting {language_name}...")
        
        if delete_language(series_key, language_name):
            await client.send_message(user_id, f"Language '{language_name}' deleted successfully.")
            await send_language_management_message(client, user_id, series_key, main_message_id)
        else:
            await client.send_message(user_id, f"Failed to delete language '{language_name}'.")
    
    elif data == "delete_season":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        await callback_query.answer(f"Deleting {season_name}...")
        
        if delete_season(series_key, language_name, season_name):
            await client.send_message(user_id, f"Season '{season_name}' deleted successfully.")
            await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
        else:
            await client.send_message(user_id, f"Failed to delete season '{season_name}'.")
    
    elif data == "publish_series":
        series_key = temp_admin_data[user_id].get("current_series_key")
        await callback_query.answer("Publishing series...")
        
        text = (
            "Do you want to publish this series?\n\n"
            "NOTE: Once you publish this series, you can't edit it anymore.\n"
            "All the empty groups will be removed automatically."
        )
        
        buttons = [
            [InlineKeyboardButton("✅ Yes", callback_data="confirm_publish")],
            [InlineKeyboardButton("❌ No", callback_data="cancel_publish")]
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
            await client.send_message(user_id, "Error showing publish confirmation. Please try again.")
    
    elif data == "confirm_publish":
        series_key = temp_admin_data[user_id].get("current_series_key")
        await callback_query.answer("Publishing...")
        
        if publish_series(series_key):
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption="✅ Published Successfully"
            )
            temp_admin_data[user_id]["state"] = "PUBLISHED"
        else:
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption="❌ Failed to publish series. Please try again."
            )
    
    elif data == "cancel_publish":
        series_key = temp_admin_data[user_id].get("current_series_key")
        await callback_query.answer("Cancelling publish...")
        
        series_data = get_series_by_key(series_key)
        if series_data:
            await send_series_details_message(client, user_id, series_data, main_message_id)
        else:
            await client.send_message(user_id, "Series not found.")

# Process input functions
async def process_add_input(client: Client, message: Message, category: str):
    user_id = message.from_user.id
    new_value = message.text.strip()
    series_key = temp_admin_data[user_id].get("current_series_key")
    row_index = temp_admin_data[user_id].get("add_row_index")
    
    # Remove keyboard
    await message.reply("Added successfully", reply_markup=ReplyKeyboardRemove())
    
    if category == "language":
        # Add the language
        if add_or_update_language(series_key, new_value):
            # Update the layout pattern
            series_data = get_series_by_key(series_key)
            language_layout = series_data.get("language_layout", [])
            
            # If row_index is within the current layout, increment that row
            if row_index < len(language_layout):
                language_layout[row_index] += 1
            else:
                # Adding to a new row
                language_layout.append(1)
            
            # Update the layout in the database
            update_series_field(series_key, "language_layout", language_layout)
            
            # Refresh the message
            main_message_id = temp_admin_data[user_id].get("main_message_id")
            await send_language_management_message(client, user_id, series_key, main_message_id)
        else:
            await message.reply(f"Failed to add language '{new_value}'.")
    
    elif category == "season":
        language_name = temp_admin_data[user_id].get("current_language")
        if add_or_update_season(series_key, language_name, new_value):
            # Update the layout pattern
            series_data = get_series_by_key(series_key)
            current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
            
            if current_lang:
                season_layout = current_lang.get("season_layout", [])
                
                if row_index < len(season_layout):
                    season_layout[row_index] += 1
                else:
                    season_layout.append(1)
                
                # Update the layout in the database
                update_language_season_layout(series_key, language_name, season_layout)
                
                # Refresh the message
                main_message_id = temp_admin_data[user_id].get("main_message_id")
                await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
            else:
                await message.reply("Language not found.")
        else:
            await message.reply(f"Failed to add season '{new_value}'.")
    
    elif category == "quality":
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        if add_or_update_quality(series_key, language_name, season_name, new_value):
            # Update the layout pattern
            series_data = get_series_by_key(series_key)
            current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
            
            if current_lang:
                current_season = next((s for s in current_lang.get("seasons", []) if s["name"].lower() == season_name.lower()), None)
                
                if current_season:
                    quality_layout = current_season.get("quality_layout", [])
                    
                    if row_index < len(quality_layout):
                        quality_layout[row_index] += 1
                    else:
                        quality_layout.append(1)
                    
                    # Update the layout in the database
                    update_season_quality_layout(series_key, language_name, season_name, quality_layout)
                    
                    # Refresh the message
                    main_message_id = temp_admin_data[user_id].get("main_message_id")
                    await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
                else:
                    await message.reply("Season not found.")
            else:
                await message.reply("Language not found.")
        else:
            await message.reply(f"Failed to add quality '{new_value}'.")
    
    # Reset state
    temp_admin_data[user_id]["state"] = f"MANAGE_{category.upper()}S"
    temp_admin_data[user_id].pop("add_row_index", None)

async def process_codec_input(client: Client, message: Message, codec_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    quality_name = temp_admin_data[user_id].get("current_quality")
    
    # Remove keyboard
    await message.reply("Codec Updated", reply_markup=ReplyKeyboardRemove())
    
    # Update codec in database
    if update_quality_codec(series_key, language_name, season_name, quality_name, codec_name):
        # Update the quality management view
        main_message_id = temp_admin_data[user_id].get("main_message_id")
        await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
        
        # Reset state
        temp_admin_data[user_id]["state"] = "MANAGE_QUALITIES"
    else:
        await message.reply(f"Failed to add codec '{codec_name}'.")

async def process_poster_input(client: Client, message: Message, poster_type: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    
    poster_file_id = await download_and_upload_poster(client, message=message)
    if not poster_file_id:
        await message.reply("Failed to process the poster. Please try again.")
        return
    
    if poster_type == "series":
        update_series_field(series_key, "poster_file_id", poster_file_id)
        series_data = get_series_by_key(series_key)
        series_data["poster_file_id"] = poster_file_id
        await send_series_details_message(client, user_id, series_data, temp_admin_data[user_id].get("main_message_id"))
        temp_admin_data[user_id]["state"] = "SERIES_DETAILS"
    
    elif poster_type == "language":
        language_name = temp_admin_data[user_id].get("current_language")
        update_language_poster(series_key, language_name, poster_file_id)
        await send_season_management_message(client, user_id, series_key, language_name, temp_admin_data[user_id].get("main_message_id"))
        temp_admin_data[user_id]["state"] = "MANAGE_SEASONS"
    
    elif poster_type == "season":
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        update_season_poster(series_key, language_name, season_name, poster_file_id)
        await send_quality_management_message(client, user_id, series_key, language_name, season_name, temp_admin_data[user_id].get("main_message_id"))
        temp_admin_data[user_id]["state"] = "MANAGE_QUALITIES"

async def process_first_file_input(client: Client, message: Message):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    quality_name = temp_admin_data[user_id].get("current_quality")
    
    # Get message ID from forwarded message
    channel_id, message_id = await get_message_id(message)
    if not channel_id or not message_id:
        await message.reply("Invalid forwarded message. Please forward a message from a channel.")
        return
    
    # Store the first message info
    temp_admin_data[user_id]["first_channel_id"] = channel_id
    temp_admin_data[user_id]["first_message_id"] = message_id
    
    await message.reply(f"First file received. Now forward me the last file for {language_name}-{season_name}-{quality_name}")
    temp_admin_data[user_id]["state"] = "AWAITING_LAST_FILE"

async def process_last_file_input(client: Client, message: Message):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    quality_name = temp_admin_data[user_id].get("current_quality")
    first_channel_id = temp_admin_data[user_id].get("first_channel_id")
    first_message_id = temp_admin_data[user_id].get("first_message_id")
    
    # Get message ID from forwarded message
    channel_id, message_id = await get_message_id(message)
    if not channel_id or not message_id:
        await message.reply("Invalid forwarded message. Please forward a message from a channel.")
        return
    
    # Check if both messages are from the same channel
    if channel_id != first_channel_id:
        await message.reply("Both files must be from the same channel.")
        return
    
    # Send processing message
    processing_msg = await message.reply("Processing...")
    
    # Generate the link string
    # Remove the -100 prefix from channel_id if present
    if str(channel_id).startswith("-100"):
        channel_id_str = str(channel_id)[4:]
    else:
        channel_id_str = str(channel_id)
    
    link_key = f"get_{channel_id_str}_{first_message_id}_{message_id}"
    
    # Update the quality with the link key
    if update_quality_link_key(series_key, language_name, season_name, quality_name, link_key):
        await processing_msg.edit_text("Done! Files saved successfully.")
    else:
        await processing_msg.edit_text("Failed to save files.")
        return
    
    # Return to quality management view
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
    temp_admin_data[user_id]["state"] = "MANAGE_QUALITIES"
    temp_admin_data[user_id].pop("first_channel_id", None)
    temp_admin_data[user_id].pop("first_message_id", None)
