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
from typing import Dict, Any, List, Tuple, Optional, Union, Callable

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

# Keyboard Builder Class
class Key:
    """Key class for creating buttons with custom callback data"""
    @staticmethod
    def callback(text: str, callback_data: str):
        return InlineKeyboardButton(text=text, callback_data=callback_data)

class KeyboardBuilder:
    """Keyboard builder for creating flexible inline keyboards"""
    def __init__(self, buttons: List[InlineKeyboardButton] = None):
        self.buttons = buttons or []
        self.pattern = None
        self.columns = None
        self.wrap_fn = None
        self.filter_fn = None
        self.flat = False
        self.filter_after_build = False
    
    @classmethod
    def make(cls, buttons: Union[List[InlineKeyboardButton], List[List[InlineKeyboardButton]], Callable] = None, **options):
        """Create a new keyboard builder"""
        if callable(buttons):
            # For construct function
            return cls(buttons=buttons)
        
        if buttons and isinstance(buttons[0], list):
            # If buttons are already in rows
            flat_buttons = []
            for row in buttons:
                flat_buttons.extend(row)
            builder = cls(flat_buttons)
        else:
            builder = cls(buttons)
        
        # Apply options
        if 'pattern' in options:
            builder.set_pattern(options['pattern'])
        if 'columns' in options:
            builder.set_columns(options['columns'])
        if 'wrap' in options:
            builder.set_wrap(options['wrap'])
        if 'filter' in options:
            builder.set_filter(options['filter'])
        if 'flat' in options:
            builder.set_flat(options['flat'])
        if 'filter_after_build' in options:
            builder.set_filter_after_build(options['filter_after_build'])
        
        return builder
    
    def set_pattern(self, pattern: List[int]):
        """Set pattern for keyboard layout"""
        self.pattern = pattern
        return self
    
    def set_columns(self, columns: int):
        """Set fixed columns for keyboard layout"""
        self.columns = columns
        return self
    
    def set_wrap(self, wrap_fn: Callable):
        """Set wrap function for dynamic layout"""
        self.wrap_fn = wrap_fn
        return self
    
    def set_filter(self, filter_fn: Callable):
        """Set filter function for buttons"""
        self.filter_fn = filter_fn
        return self
    
    def set_flat(self, flat: bool):
        """Set flat option"""
        self.flat = flat
        return self
    
    def set_filter_after_build(self, filter_after_build: bool):
        """Set filter after build option"""
        self.filter_after_build = filter_after_build
        return self
    
    def build(self, *args, **kwargs) -> List[List[InlineKeyboardButton]]:
        """Build the keyboard"""
        # If buttons is a function (for construct), call it
        if callable(self.buttons):
            buttons = self.buttons(*args, **kwargs)
            if isinstance(buttons, KeyboardBuilder):
                return buttons.build(*args, **kwargs)
            return buttons
        
        # Apply filter if set and not filter_after_build
        if self.filter_fn and not self.filter_after_build:
            self.buttons = [btn for btn in self.buttons if self.filter_fn(btn)]
        
        # If flat is True and buttons are nested, flatten them
        if self.flat and self.buttons and isinstance(self.buttons[0], list):
            flat_buttons = []
            for row in self.buttons:
                flat_buttons.extend(row)
            self.buttons = flat_buttons
        
        # Build layout based on options
        if self.pattern:
            layout = self._build_by_pattern()
        elif self.columns:
            layout = self._build_by_columns()
        elif self.wrap_fn:
            layout = self._build_by_wrap()
        else:
            # Default: one button per row
            layout = [[btn] for btn in self.buttons]
        
        # Apply filter if set and filter_after_build
        if self.filter_fn and self.filter_after_build:
            layout = [[btn for btn in row if self.filter_fn(btn)] for row in layout]
            # Remove empty rows
            layout = [row for row in layout if row]
        
        return layout
    
    def _build_by_pattern(self) -> List[List[InlineKeyboardButton]]:
        """Build keyboard by pattern"""
        layout = []
        buttons = self.buttons.copy()
        
        # Apply pattern
        for count in self.pattern:
            if not buttons:
                break
            row = buttons[:count]
            layout.append(row)
            buttons = buttons[count:]
        
        # Add remaining buttons
        if buttons:
            layout.append(buttons)
        
        return layout
    
    def _build_by_columns(self) -> List[List[InlineKeyboardButton]]:
        """Build keyboard by columns"""
        layout = []
        row = []
        
        for i, button in enumerate(self.buttons):
            row.append(button)
            if len(row) == self.columns or i == len(self.buttons) - 1:
                layout.append(row)
                row = []
        
        return layout
    
    def _build_by_wrap(self) -> List[List[InlineKeyboardButton]]:
        """Build keyboard by wrap function"""
        layout = []
        row = []
        
        for i, button in enumerate(self.buttons):
            if row and self.wrap_fn(row, i, button):
                layout.append(row)
                row = []
            row.append(button)
        
        if row:
            layout.append(row)
        
        return layout
    
    def inline(self, *args, **kwargs) -> InlineKeyboardMarkup:
        """Get inline keyboard markup"""
        layout = self.build(*args, **kwargs)
        return InlineKeyboardMarkup(layout)
    
    def construct(self, *args, **kwargs):
        """Construct keyboard with arguments (for callable buttons)"""
        return self.build(*args, **kwargs)
    
    @staticmethod
    def combine(*keyboards) -> 'KeyboardBuilder':
        """Combine multiple keyboards"""
        combined_buttons = []
        for kb in keyboards:
            if isinstance(kb, KeyboardBuilder):
                combined_buttons.extend(kb.buttons)
            else:
                combined_buttons.extend(kb)
        return KeyboardBuilder(combined_buttons)

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

# New Series UI Functions
async def send_new_series_selection(client: Client, user_id: int, query: str, results: list, message_id: int = None):
    logger.info(f"Sending new series selection message to user {user_id}")
    text = f"**Select a series from below:**\n\nSearch query: `{query}`"
    
    buttons = []
    for i, item in enumerate(results, 1):
        unique_id = str(uuid.uuid4())
        temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
        temp_admin_data[user_id][unique_id] = {
            'id': item.get('tmdb_id'),
            'media_type': item.get('media_type'),
            'source': 'tmdb',
            'query': query,
            'data': item
        }
        buttons.append(Key.callback(
            text=f"{item.get('title', 'N/A')} ({item.get('year', 'N/A')})",
            callback_data=f"sel_{unique_id}"
        ))
    
    buttons.append(Key.callback("🔍 Search Again", callback_data="search_again"))
    
    # Create layout with single buttons per row
    keyboard = KeyboardBuilder.make(buttons).inline()
    
    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=NO_POSTER_FOUND_IMG, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=keyboard
            )
            logger.debug(f"Edited series selection message {message_id}")
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=NO_POSTER_FOUND_IMG,
                caption=text,
                reply_markup=keyboard,
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
            reply_markup=keyboard,
            parse_mode=enums.ParseMode.MARKDOWN
        )
        temp_admin_data[user_id]["main_message_id"] = new_msg.id
        return new_msg.id
    except Exception as e:
        logger.error(f"An unexpected error occurred sending series selection message: {e}")
        return None

async def send_new_series_details(client: Client, user_id: int, series_data: dict, message_id: int = None):
    logger.info(f"Sending new series details message to user {user_id}")
    
    poster_file_id = series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG
    
    # Format the release date
    released_on = series_data.get('released_on', 'N/A')
    if released_on != 'N/A':
        try:
            # Try to parse and format the date
            if '-' in released_on:
                parts = released_on.split('-')
                if len(parts) >= 3:
                    year, month, day = parts[0], parts[1], parts[2]
                    from datetime import datetime
                    date_obj = datetime(int(year), int(month), int(day))
                    released_on = date_obj.strftime("%d %b %Y")
        except:
            pass
    
    text = (
        f"**Title:** `{series_data.get('title', 'N/A')}`\n"
        f"**Released On:** `{released_on}`\n"
        f"**Genre:** `{series_data.get('genre', 'N/A')}`\n"
        f"**Rating:** `{series_data.get('rating', 'N/A')}`\n"
        f"**TMDB ID:** `{series_data.get('tmdb_id', 'N/A')}`\n"
        f"**Media Type:** `{series_data.get('media_type', 'N/A').upper()}`\n\n"
    )

    # Define buttons for series details
    buttons = [
        Key.callback("✏️ Edit", callback_data="edit_series"),
        Key.callback("⬅️ Back", callback_data="back_to_search")
    ]
    
    keyboard = KeyboardBuilder.make(buttons).inline()

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=poster_file_id, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=keyboard
            )
            logger.debug(f"Edited series details message {message_id}")
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_file_id,
                caption=text,
                reply_markup=keyboard,
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
            reply_markup=keyboard,
            parse_mode=enums.ParseMode.MARKDOWN
        )
        temp_admin_data[user_id]["main_message_id"] = new_msg.id
        return new_msg.id
    except Exception as e:
        logger.error(f"An unexpected error occurred sending series details message: {e}")
        return None

async def send_new_series_editing_main(client: Client, user_id: int, series_key: str, message_id: int = None):
    logger.info(f"Sending new series editing main message to user {user_id}")
    series_data = get_series_by_key(series_key)
    if not series_data:
        logger.warning(f"Series not found for key: {series_key}")
        await client.send_message(user_id, "Series not found.")
        return

    poster_file_id = series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG
    
    # Format the release date
    released_on = series_data.get('released_on', 'N/A')
    if released_on != 'N/A':
        try:
            # Try to parse and format the date
            if '-' in released_on:
                parts = released_on.split('-')
                if len(parts) >= 3:
                    year, month, day = parts[0], parts[1], parts[2]
                    from datetime import datetime
                    date_obj = datetime(int(year), int(month), int(day))
                    released_on = date_obj.strftime("%d %b %Y")
        except:
            pass
    
    text = (
        f"**Title:** `{series_data.get('title', 'N/A')}`\n"
        f"**Released On:** `{released_on}`\n"
        f"**Genre:** `{series_data.get('genre', 'N/A')}`\n"
        f"**Rating:** `{series_data.get('rating', 'N/A')}`\n"
        f"**TMDB ID:** `{series_data.get('tmdb_id', 'N/A')}`\n"
        f"**Media Type:** `{series_data.get('media_type', 'N/A').upper()}`\n\n"
    )

    # Define buttons for series editing
    buttons = [
        Key.callback("🌐 Languages", callback_data="edit_languages"),
        Key.callback("🖼️ Poster", callback_data="edit_poster"),
        Key.callback("📤 Publish", callback_data="publish_series"),
        Key.callback("⬅️ Back", callback_data="back_to_details")
    ]
    
    keyboard = KeyboardBuilder.make(buttons).inline()

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=poster_file_id, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=keyboard
            )
            logger.debug(f"Edited series editing main message {message_id}")
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_file_id,
                caption=text,
                reply_markup=keyboard,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            logger.debug(f"Sent new series editing main message {msg.id}")
            return msg.id
    except (MessageIdInvalid, FloodWait) as e:
        logger.warning(f"Failed to edit series editing main message (ID: {message_id}): {e}. Attempting to send a new message.")
        new_msg = await client.send_photo(
            chat_id=user_id,
            photo=poster_file_id,
            caption=text,
            reply_markup=keyboard,
            parse_mode=enums.ParseMode.MARKDOWN
        )
        temp_admin_data[user_id]["main_message_id"] = new_msg.id
        return new_msg.id
    except Exception as e:
        logger.error(f"An unexpected error occurred sending series editing main message: {e}")
        return None

async def send_language_management(client: Client, user_id: int, series_key: str, message_id: int):
    logger.info(f"Sending language management message to user {user_id}")
    series_data = get_series_by_key(series_key)
    if not series_data:
        logger.warning(f"Series not found for key: {series_key}")
        await client.send_message(user_id, "Series not found.")
        return

    languages = series_data.get("languages", [])
    
    text = "Select any Language group to add new Season/Part group inside them.\n\nOr click '+' button to add new Language group.\n\n"

    # Create buttons for languages
    item_buttons = []
    for i, lang in enumerate(languages):
        item_buttons.append(Key.callback(
            f"{lang['name']}", 
            callback_data=f"lang_{i}"
        ))
    
    # Action buttons
    action_buttons = [
        Key.callback("+ Language", callback_data="add_language"),
        Key.callback("⬅️ Back", callback_data="back_to_editing")
    ]
    
    # Create keyboard with flexible layout
    if len(item_buttons) >= 4:
        item_keyboard = KeyboardBuilder.make(item_buttons, pattern=[2, 2]).build()
    elif len(item_buttons) >= 2:
        item_keyboard = KeyboardBuilder.make(item_buttons, pattern=[2]).build()
    else:
        item_keyboard = KeyboardBuilder.make(item_buttons).build()
    
    # Add action buttons as separate rows
    for button in action_buttons:
        item_keyboard.append([button])
    
    reply_markup = InlineKeyboardMarkup(item_keyboard)

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

async def send_season_management(client: Client, user_id: int, series_key: str, language_name: str, message_id: int):
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
    
    text = "Select any Seasons group to add new Quality group into them.\n\nOr click '+' button to add new Seasons group.\n\n"

    # Create buttons for seasons
    item_buttons = []
    for i, season in enumerate(seasons):
        item_buttons.append(Key.callback(
            f"{season['name']}", 
            callback_data=f"season_{i}"
        ))
    
    # Action buttons
    action_buttons = [
        Key.callback("+ Seasons", callback_data="add_season"),
        Key.callback("🖼️ Change Poster", callback_data="change_lang_poster"),
        Key.callback(f"🗑️ Delete '{language_name}' Group", callback_data="delete_language"),
        Key.callback("⬅️ Back", callback_data="back_to_languages")
    ]
    
    # Create keyboard with flexible layout
    if len(item_buttons) >= 4:
        item_keyboard = KeyboardBuilder.make(item_buttons, pattern=[2, 2]).build()
    elif len(item_buttons) >= 2:
        item_keyboard = KeyboardBuilder.make(item_buttons, pattern=[2]).build()
    else:
        item_keyboard = KeyboardBuilder.make(item_buttons).build()
    
    # Add action buttons as separate rows
    for button in action_buttons:
        item_keyboard.append([button])
    
    reply_markup = InlineKeyboardMarkup(item_keyboard)

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

async def send_quality_management(client: Client, user_id: int, series_key: str, language_name: str, season_name: str, message_id: int):
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
    
    text = "Select any Quality group to add new files into them.\n\nOr click '+' button to add new Quality group.\n\n"

    # Create buttons for qualities
    item_buttons = []
    for i, quality in enumerate(qualities):
        item_buttons.append(Key.callback(
            f"{quality['name']}", 
            callback_data=f"quality_{i}"
        ))
    
    # Action buttons
    action_buttons = [
        Key.callback("+ Quality", callback_data="add_quality"),
        Key.callback("🖼️ Change Poster", callback_data="change_season_poster"),
        Key.callback(f"🗑️ Delete '{season_name}' Group", callback_data="delete_season"),
        Key.callback("⬅️ Back", callback_data="back_to_seasons")
    ]
    
    # Create keyboard with flexible layout
    if len(item_buttons) >= 4:
        item_keyboard = KeyboardBuilder.make(item_buttons, pattern=[2, 2]).build()
    elif len(item_buttons) >= 2:
        item_keyboard = KeyboardBuilder.make(item_buttons, pattern=[2]).build()
    else:
        item_keyboard = KeyboardBuilder.make(item_buttons).build()
    
    # Add action buttons as separate rows
    for button in action_buttons:
        item_keyboard.append([button])
    
    reply_markup = InlineKeyboardMarkup(item_keyboard)

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

async def send_publish_confirmation(client: Client, user_id: int, series_key: str, message_id: int):
    logger.info(f"Sending publish confirmation message to user {user_id}")
    series_data = get_series_by_key(series_key)
    if not series_data:
        logger.warning(f"Series not found for key: {series_key}")
        await client.send_message(user_id, "Series not found.")
        return

    poster_file_id = series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG
    
    text = (
        "Do you want to publish this series?\n\n"
        "NOTE: Once you publish this series, you can't edit it anymore.\n"
        "All the empty groups will be removed automatically."
    )

    # Define buttons for publish confirmation
    buttons = [
        Key.callback("✅ Yes", callback_data="confirm_publish"),
        Key.callback("❌ No", callback_data="cancel_publish")
    ]
    
    keyboard = KeyboardBuilder.make(buttons).inline()

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=poster_file_id, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=keyboard
            )
            logger.debug(f"Edited publish confirmation message {message_id}")
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_file_id,
                caption=text,
                reply_markup=keyboard,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            logger.debug(f"Sent new publish confirmation message {msg.id}")
            return msg.id
    except (MessageIdInvalid, FloodWait) as e:
        logger.warning(f"Failed to edit publish confirmation message (ID: {message_id}): {e}. Attempting to send a new message.")
        new_msg = await client.send_photo(
            chat_id=user_id,
            photo=poster_file_id,
            caption=text,
            reply_markup=keyboard,
            parse_mode=enums.ParseMode.MARKDOWN
        )
        temp_admin_data[user_id]["main_message_id"] = new_msg.id
        return new_msg.id
    except Exception as e:
        logger.error(f"An unexpected error occurred sending publish confirmation message: {e}")
        return None

# Command handlers
@Client.on_message(filters.command('newseries') & filters.user(ADMINS))
async def new_series_command(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} started new series command")
    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None

    if not query:
        await message.reply("Usage: `/newseries <series_title>`")
        return

    async with get_admin_lock(user_id):
        # Send initial message with fixed photo
        temp_msg = await message.reply_photo(
            photo=NO_POSTER_FOUND_IMG,
            caption="Searching TMDB, please wait..."
        )
        
        # Fetch results
        tmdb_results = await get_tmdb_info(query, bulk=True)

        if not tmdb_results:
            await temp_msg.edit_caption(
                caption="No results found on TMDB for the provided series name.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 Search Again", callback_data="newseries_retry")]
                ])
            )
            return

        # Store data in temp_admin_data
        temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
        temp_admin_data[user_id]["search_results"] = tmdb_results
        temp_admin_data[user_id]["query"] = query
        temp_admin_data[user_id]["state"] = "NEW_SERIES_SELECTING"
        temp_admin_data[user_id]["main_message_id"] = temp_msg.id

        # Edit message with results and single buttons per row
        await send_new_series_selection(client, user_id, query, tmdb_results, temp_msg.id)

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
    
    if current_state == "NEW_SERIES_ADDING_LANGUAGE":
        await process_language_input(client, message, message.text.strip())
    elif current_state == "NEW_SERIES_ADDING_SEASON":
        await process_season_input(client, message, message.text.strip())
    elif current_state == "NEW_SERIES_ADDING_QUALITY":
        await process_quality_input(client, message, message.text.strip())
    elif current_state == "NEW_SERIES_ADDING_FIRST_FILE":
        await process_first_file_input(client, message)
    elif current_state == "NEW_SERIES_ADDING_LAST_FILE":
        await process_last_file_input(client, message)
    elif current_state == "NEW_SERIES_ADDING_CODEC":
        await process_codec_input(client, message, message.text.strip())

async def handle_admin_media_input(client: Client, message: Message):
    user_id = message.from_user.id
    current_state = temp_admin_data.get(user_id, {}).get("state")
    logger.info(f"Processing admin media input in state: {current_state}")
    
    if current_state == "NEW_SERIES_EDITING_POSTER":
        await process_poster_input(client, message)
    elif current_state == "NEW_SERIES_EDITING_LANG_POSTER":
        await process_lang_poster_input(client, message)
    elif current_state == "NEW_SERIES_EDITING_SEASON_POSTER":
        await process_season_poster_input(client, message)

async def newui_callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    logger.info(f"Processing admin UI callback: {data}")
    
    if user_id not in temp_admin_data:
        logger.warning(f"Admin {user_id} not in temp_admin_data")
        await callback_query.answer("Session expired. Please start again with /newseries.", show_alert=True)
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
        tmdb_data = stored_data['data']
        
        await callback_query.answer(f"Fetching details from {source.upper()}...")
        
        # Create series key from title
        series_key = tmdb_data.get('title', 'N/A').lower().replace(" ", "").replace("-", "")
        
        # Check if series already exists
        existing_series = get_series_by_key(series_key)
        if existing_series:
            await callback_query.answer("Series already exists. Loading for editing.", show_alert=True)
            series_data = existing_series
        else:
            # Create new series data
            series_data = {
                '_id': series_key,
                'title': tmdb_data.get('title', 'N/A'),
                'released_on': tmdb_data.get('year', 'N/A'),
                'genre': tmdb_data.get('genres', 'N/A'),
                'rating': tmdb_data.get('rating', 'N/A'),
                'tmdb_id': tmdb_data.get('tmdb_id'),
                'media_type': media_type,
                'poster_file_id': None,
                'languages': [],
                'published': False
            }
            
            # Add series to database
            if not add_series(series_data):
                await callback_query.answer("Failed to add new series. Please try again.", show_alert=True)
                return
            
            # Get the series data from database
            series_data = get_series_by_key(series_key)
            if not series_data:
                await client.edit_message_caption(
                    chat_id=user_id,
                    message_id=main_message_id,
                    caption="Failed to create series. Please try again."
                )
                return
        
        # Download and upload poster
        poster_file_id = await download_and_upload_poster(client, poster_url=tmdb_data.get('poster_url'))
        if poster_file_id:
            update_series_field(series_key, "poster_file_id", poster_file_id)
            series_data["poster_file_id"] = poster_file_id
        else:
            await client.send_message(user_id, "Failed to download/upload poster. Using placeholder.")
            update_series_field(series_key, "poster_file_id", NO_POSTER_FOUND_IMG)
            series_data["poster_file_id"] = NO_POSTER_FOUND_IMG
        
        # Update temp_admin_data
        temp_admin_data[user_id]["current_series_key"] = series_key
        temp_admin_data[user_id]["state"] = "NEW_SERIES_DETAILS"
        
        # Send series details message
        await send_new_series_details(client, user_id, series_data, main_message_id)
    
    # Handle navigation callbacks
    elif data == "search_again":
        await callback_query.answer("Search again...")
        query = temp_admin_data[user_id].get("query")
        search_results = temp_admin_data[user_id].get("search_results", [])
        
        if not query or not search_results:
            await callback_query.answer("No previous search data found.", show_alert=True)
            return
        
        temp_admin_data[user_id]["state"] = "NEW_SERIES_SELECTING"
        await send_new_series_selection(client, user_id, query, search_results, main_message_id)
    
    elif data == "back_to_search":
        await callback_query.answer("Going back to search results...")
        query = temp_admin_data[user_id].get("query")
        search_results = temp_admin_data[user_id].get("search_results", [])
        
        if not query or not search_results:
            await callback_query.answer("No previous search data found.", show_alert=True)
            return
        
        temp_admin_data[user_id]["state"] = "NEW_SERIES_SELECTING"
        await send_new_series_selection(client, user_id, query, search_results, main_message_id)
    
    elif data == "back_to_details":
        series_key = temp_admin_data[user_id].get("current_series_key")
        series_data = get_series_by_key(series_key)
        if not series_data:
            await callback_query.answer("Series not found.", show_alert=True)
            return
        
        await callback_query.answer("Going back to series details...")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_DETAILS"
        await send_new_series_details(client, user_id, series_data, main_message_id)
    
    elif data == "back_to_editing":
        series_key = temp_admin_data[user_id].get("current_series_key")
        await callback_query.answer("Going back to editing...")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_EDITING_MAIN"
        await send_new_series_editing_main(client, user_id, series_key, main_message_id)
    
    elif data == "edit_series":
        series_key = temp_admin_data[user_id].get("current_series_key")
        await callback_query.answer("Editing series...")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_EDITING_MAIN"
        await send_new_series_editing_main(client, user_id, series_key, main_message_id)
    
    elif data == "edit_languages":
        series_key = temp_admin_data[user_id].get("current_series_key")
        await callback_query.answer("Managing languages...")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_MANAGING_LANGUAGES"
        await send_language_management(client, user_id, series_key, main_message_id)
    
    elif data == "edit_poster":
        series_key = temp_admin_data[user_id].get("current_series_key")
        await callback_query.answer("Send a new poster...")
        
        temp_admin_data[user_id]["state"] = "NEW_SERIES_EDITING_POSTER"
        temp_admin_data[user_id]["current_series_key"] = series_key
        
        await client.send_message(
            user_id,
            "Please send a photo or video to use as the series poster:"
        )
    
    elif data == "publish_series":
        series_key = temp_admin_data[user_id].get("current_series_key")
        await callback_query.answer("Publishing series...")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_PUBLISHING"
        await send_publish_confirmation(client, user_id, series_key, main_message_id)
    
    elif data == "confirm_publish":
        series_key = temp_admin_data[user_id].get("current_series_key")
        series_data = get_series_by_key(series_key)
        
        if not series_data:
            await callback_query.answer("Series not found.", show_alert=True)
            return
        
        await callback_query.answer("Publishing series...")
        
        if publish_series(series_key):
            await callback_query.answer("Series published successfully.")
            
            # Send success message
            await client.send_message(
                user_id,
                "Published Successfully"
            )
            
            # Delete the main message
            try:
                await client.delete_messages(user_id, main_message_id)
            except Exception as e:
                logger.warning(f"Failed to delete main message: {e}")
            
            # Clear temp data
            if user_id in temp_admin_data:
                del temp_admin_data[user_id]
        else:
            await callback_query.answer("Failed to publish series.", show_alert=True)
    
    elif data == "cancel_publish":
        series_key = temp_admin_data[user_id].get("current_series_key")
        series_data = get_series_by_key(series_key)
        if not series_data:
            await callback_query.answer("Series not found.", show_alert=True)
            return
        
        await callback_query.answer("Cancelled publishing.")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_EDITING_MAIN"
        await send_new_series_editing_main(client, user_id, series_key, main_message_id)
    
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
        temp_admin_data[user_id]["state"] = "NEW_SERIES_ADDING_LANGUAGE"
        temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
    
    elif data.startswith("lang_"):
        series_key = temp_admin_data[user_id].get("current_series_key")
        lang_index = int(data.split("_", 1)[1])
        languages = get_languages(series_key)
        
        if 0 <= lang_index < len(languages):
            language_name = languages[lang_index]["name"]
            await callback_query.answer(f"Selected: {language_name}")
            temp_admin_data[user_id]["current_language"] = language_name
            temp_admin_data[user_id]["state"] = "NEW_SERIES_MANAGING_SEASONS"
            await send_season_management(client, user_id, series_key, language_name, main_message_id)
        else:
            await callback_query.answer("Invalid selection.", show_alert=True)
    
    elif data == "back_to_languages":
        series_key = temp_admin_data[user_id].get("current_series_key")
        await callback_query.answer("Going back to languages...")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_MANAGING_LANGUAGES"
        await send_language_management(client, user_id, series_key, main_message_id)
    
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
        temp_admin_data[user_id]["state"] = "NEW_SERIES_ADDING_SEASON"
        temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
    
    elif data.startswith("season_"):
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_index = int(data.split("_", 1)[1])
        seasons = get_seasons(series_key, language_name)
        
        if 0 <= season_index < len(seasons):
            season_name = seasons[season_index]["name"]
            await callback_query.answer(f"Selected: {season_name}")
            temp_admin_data[user_id]["current_season"] = season_name
            temp_admin_data[user_id]["state"] = "NEW_SERIES_MANAGING_QUALITIES"
            await send_quality_management(client, user_id, series_key, language_name, season_name, main_message_id)
        else:
            await callback_query.answer("Invalid selection.", show_alert=True)
    
    elif data == "back_to_seasons":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        await callback_query.answer("Going back to seasons...")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_MANAGING_SEASONS"
        await send_season_management(client, user_id, series_key, language_name, main_message_id)
    
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
        temp_admin_data[user_id]["state"] = "NEW_SERIES_ADDING_QUALITY"
        temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
    
    elif data.startswith("quality_"):
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        quality_index = int(data.split("_", 1)[1])
        qualities = get_qualities(series_key, language_name, season_name)
        
        if 0 <= quality_index < len(qualities):
            quality_name = qualities[quality_index]["name"]
            await callback_query.answer(f"Selected: {quality_name}")
            temp_admin_data[user_id]["current_quality"] = quality_name
            temp_admin_data[user_id]["state"] = "NEW_SERIES_ADDING_FIRST_FILE"
            
            await client.send_message(
                user_id,
                f"Add me to the channel as admin and forward me the first file (with tag) for {language_name}-{season_name}-{quality_name}"
            )
        else:
            await callback_query.answer("Invalid selection.", show_alert=True)
    
    elif data == "back_to_qualities":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        await callback_query.answer("Going back to qualities...")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_MANAGING_QUALITIES"
        await send_quality_management(client, user_id, series_key, language_name, season_name, main_message_id)
    
    elif data == "change_lang_poster":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        await callback_query.answer("Send a new poster...")
        
        temp_admin_data[user_id]["state"] = "NEW_SERIES_EDITING_LANG_POSTER"
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
        
        temp_admin_data[user_id]["state"] = "NEW_SERIES_EDITING_SEASON_POSTER"
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
            await send_language_management(client, user_id, series_key, main_message_id)
        else:
            await callback_query.answer("Failed to delete language.", show_alert=True)
    
    elif data == "delete_season":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        
        await callback_query.answer(f"Deleting {season_name}...")
        
        if delete_season(series_key, language_name, season_name):
            await callback_query.answer(f"Deleted {season_name} successfully.")
            await send_season_management(client, user_id, series_key, language_name, main_message_id)
        else:
            await callback_query.answer("Failed to delete season.", show_alert=True)
    
    elif data == "newseries_retry":
        await callback_query.answer("Starting new search...")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_INITIAL"
        await callback_query.message.delete()
        await client.send_message(
            user_id,
            "Please send the series name you want to add:",
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
        # Update the ask message
        ask_msg_id = temp_admin_data[user_id].get("ask_message_id")
        if ask_msg_id:
            try:
                await client.edit_message_text(
                    chat_id=user_id,
                    message_id=ask_msg_id,
                    text="Language Updated"
                )
            except Exception as e:
                logger.warning(f"Failed to edit ask message: {e}")
        
        # Go back to language management
        main_message_id = temp_admin_data[user_id].get("main_message_id")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_MANAGING_LANGUAGES"
        await send_language_management(client, user_id, series_key, main_message_id)
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
        # Update the ask message
        ask_msg_id = temp_admin_data[user_id].get("ask_message_id")
        if ask_msg_id:
            try:
                await client.edit_message_text(
                    chat_id=user_id,
                    message_id=ask_msg_id,
                    text="Season Updated"
                )
            except Exception as e:
                logger.warning(f"Failed to edit ask message: {e}")
        
        # Go back to season management
        main_message_id = temp_admin_data[user_id].get("main_message_id")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_MANAGING_SEASONS"
        await send_season_management(client, user_id, series_key, language_name, main_message_id)
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
        # Update the ask message
        ask_msg_id = temp_admin_data[user_id].get("ask_message_id")
        if ask_msg_id:
            try:
                await client.edit_message_text(
                    chat_id=user_id,
                    message_id=ask_msg_id,
                    text="Quality Updated"
                )
            except Exception as e:
                logger.warning(f"Failed to edit ask message: {e}")
        
        # Go back to quality management
        main_message_id = temp_admin_data[user_id].get("main_message_id")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_MANAGING_QUALITIES"
        await send_quality_management(client, user_id, series_key, language_name, season_name, main_message_id)
    else:
        await message.reply("Failed to add quality.")

async def process_poster_input(client: Client, message: Message):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    
    # Download and upload poster
    poster_file_id = await download_and_upload_poster(client, message=message)
    
    if not poster_file_id:
        await message.reply("Failed to process the poster. Please try again.")
        return
    
    # Update series poster
    update_series_field(series_key, "poster_file_id", poster_file_id)
    
    # Update the main message
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    series_data = get_series_by_key(series_key)
    if series_data:
        await send_new_series_editing_main(client, user_id, series_key, main_message_id)
    
    # Reply to the main message
    await message.reply("Poster updated successfully")

async def process_lang_poster_input(client: Client, message: Message):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    
    # Download and upload poster
    poster_file_id = await download_and_upload_poster(client, message=message)
    
    if not poster_file_id:
        await message.reply("Failed to process the poster. Please try again.")
        return
    
    # Update language poster
    add_or_update_language(series_key, language_name, poster_file_id=poster_file_id)
    
    # Update the main message
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    await send_season_management(client, user_id, series_key, language_name, main_message_id)
    
    # Reply to the main message
    await message.reply("Poster updated successfully")

async def process_season_poster_input(client: Client, message: Message):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    
    # Download and upload poster
    poster_file_id = await download_and_upload_poster(client, message=message)
    
    if not poster_file_id:
        await message.reply("Failed to process the poster. Please try again.")
        return
    
    # Update season poster
    add_or_update_season(series_key, language_name, season_name, poster_file_id=poster_file_id)
    
    # Update the main message
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    await send_quality_management(client, user_id, series_key, language_name, season_name, main_message_id)
    
    # Reply to the main message
    await message.reply("Poster updated successfully")

async def process_first_file_input(client: Client, message: Message):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    quality_name = temp_admin_data[user_id].get("current_quality")
    
    # Get the message ID of the forwarded file
    if message.forward_from_chat:
        # If forwarded from a channel
        channel_id = message.forward_from_chat.id
        message_id = message.forward_from_message_id
        
        # Store the first file info
        temp_admin_data[user_id]["first_file_info"] = {
            "channel_id": channel_id,
            "message_id": message_id
        }
        
        # Update the ask message
        ask_msg_id = temp_admin_data[user_id].get("ask_message_id")
        if ask_msg_id:
            try:
                await client.edit_message_text(
                    chat_id=user_id,
                    message_id=ask_msg_id,
                    text=f"Forward me the last file (with tag) for {language_name}-{season_name}-{quality_name}\n\nGo to first file [{channel_id}/{message_id}]"
                )
            except Exception as e:
                logger.warning(f"Failed to edit ask message: {e}")
        
        # Set state to wait for last file
        temp_admin_data[user_id]["state"] = "NEW_SERIES_ADDING_LAST_FILE"
    else:
        await message.reply("Please forward a file from a channel.")

async def process_last_file_input(client: Client, message: Message):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    quality_name = temp_admin_data[user_id].get("current_quality")
    
    # Get the message ID of the forwarded file
    if message.forward_from_chat:
        # If forwarded from a channel
        channel_id = message.forward_from_chat.id
        message_id = message.forward_from_message_id
        
        # Get the first file info
        first_file_info = temp_admin_data[user_id].get("first_file_info", {})
        first_channel_id = first_file_info.get("channel_id")
        first_message_id = first_file_info.get("message_id")
        
        if not first_channel_id or not first_message_id:
            await message.reply("First file info not found. Please start over.")
            return
        
        # Update the ask message
        ask_msg_id = temp_admin_data[user_id].get("ask_message_id")
        if ask_msg_id:
            try:
                await client.edit_message_text(
                    chat_id=user_id,
                    message_id=ask_msg_id,
                    text="Send me the codec field"
                )
            except Exception as e:
                logger.warning(f"Failed to edit ask message: {e}")
        
        # Store the last file info
        temp_admin_data[user_id]["last_file_info"] = {
            "channel_id": channel_id,
            "message_id": message_id
        }
        
        # Set state to wait for codec
        temp_admin_data[user_id]["state"] = "NEW_SERIES_ADDING_CODEC"
    else:
        await message.reply("Please forward a file from a channel.")

async def process_codec_input(client: Client, message: Message, codec: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    quality_name = temp_admin_data[user_id].get("current_quality")
    
    # Get file info
    first_file_info = temp_admin_data[user_id].get("first_file_info", {})
    last_file_info = temp_admin_data[user_id].get("last_file_info", {})
    
    first_channel_id = first_file_info.get("channel_id")
    first_message_id = first_file_info.get("message_id")
    last_channel_id = last_file_info.get("channel_id")
    last_message_id = last_file_info.get("message_id")
    
    if not first_channel_id or not first_message_id or not last_channel_id or not last_message_id:
        await message.reply("File info not found. Please start over.")
        return
    
    # Update the ask message
    ask_msg_id = temp_admin_data[user_id].get("ask_message_id")
    if ask_msg_id:
        try:
            await client.edit_message_text(
                chat_id=user_id,
                message_id=ask_msg_id,
                text="Processing..."
            )
        except Exception as e:
            logger.warning(f"Failed to edit ask message: {e}")
    
    # Create link key
    link_key = f"{first_channel_id}_{first_message_id}_{last_message_id}"
    
    # Update quality with link key
    if add_or_update_quality(series_key, language_name, season_name, quality_name, link_key):
        # Update the ask message
        if ask_msg_id:
            try:
                await client.edit_message_text(
                    chat_id=user_id,
                    message_id=ask_msg_id,
                    text="Files added to Database Successfully"
                )
            except Exception as e:
                logger.warning(f"Failed to edit ask message: {e}")
        
        # Go back to quality management
        main_message_id = temp_admin_data[user_id].get("main_message_id")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_MANAGING_QUALITIES"
        await send_quality_management(client, user_id, series_key, language_name, season_name, main_message_id)
    else:
        await message.reply("Failed to add quality.")
