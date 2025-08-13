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
        logger.error(f"An unexpected error occurred sending series details