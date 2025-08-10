#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import re
import uuid
import logging
import os
import shutil
import requests
import copy
import io
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
    get_poster_file_id, update_poster_file_id, publish_series, get_series
)
from utils import get_message_id, get_messages_in_range, get_poster
from fuzzywuzzy import fuzz
from pyrogram.errors import MessageIdInvalid, FloodWait, MessageNotModified

logger = logging.getLogger(__name__)

# Global variables
temp_admin_data: Dict[int, Dict[str, Any]] = {}
imdb = Cinemagoer()
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

# Helper functions
async def DeleteMessage(msg):
    """Delete a message after a delay."""
    await asyncio.sleep(600)
    try:
        await msg.delete()
        logger.debug(f"Deleted message {msg.id} from chat {msg.chat.id}")
    except Exception as e:
        logger.warning(f"Failed to delete message {msg.id}: {e}")

def chunk_buttons(buttons, chunk_size=2):
    """Chunk buttons into rows."""
    return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]

# TMDB and helper functions
async def get_tmdb_info(query, bulk=False, tmdb_id=None, media_type=None):
    """Fetches movie/TV show information from TMDB."""
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
    """Downloads a poster (from URL or user-provided photo), uploads it to LOG_CHANNEL, and returns its file_id."""
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
    """Sends or edits the series selection message with TMDB/IMDb results."""
    logger.info(f"Sending series selection message to user {user_id}")
    text = f"**Select a series from below:**\n\nSearch query: `{query}`"
    
    buttons = []
    for item in results:
        unique_id = str(uuid.uuid4())
        temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
        temp_admin_data[user_id][unique_id] = {
            'id': item.get('tmdb_id') if item.get('source') == 'tmdb' else item.get('imdb_id'),
            'media_type': item.get('media_type'),
            'source': item.get('source'),
            'query': query
        }
        buttons.append([
            InlineKeyboardButton(
                text=f"{item.get('title', 'N/A')} ({item.get('year', 'N/A')}) - {item.get('source').upper()}",
                callback_data=f"newui_{item.get('source')}_select:{unique_id}"
            )
        ])
    
    buttons.append([InlineKeyboardButton("🔍 Search Again", callback_data="newui_search_again")])
    
    reply_markup = InlineKeyboardMarkup(buttons)

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
    """Sends or edits the series details message with edit options."""
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

    buttons = [
        [InlineKeyboardButton("✏️ Edit Details", callback_data=f"newui_edit_details:{series_key}")],
        [InlineKeyboardButton("🌐 Languages", callback_data=f"admin:{series_key}:l1")],
        [InlineKeyboardButton("🖼️ Change Poster", callback_data=f"newui_change_poster:{series_key}")],
        [InlineKeyboardButton("📤 Publish Series", callback_data=f"admin:{series_key}:publish")],
        [InlineKeyboardButton("⬅️ Back", callback_data="newui_back_to_search")]
    ]

    reply_markup = InlineKeyboardMarkup(buttons)

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

async def send_language_management_message(client: Client, user_id: int, series_key: str, message_id: int = None):
    """Sends or edits the language management message."""
    logger.info(f"Sending language management message to user {user_id}")
    series_data = get_series_by_key(series_key)
    if not series_data:
        logger.warning(f"Series not found for key: {series_key}")
        await client.send_message(user_id, "Series not found.")
        return

    languages = series_data.get("languages", [])
    
    text = f"**Series:** `{series_data.get('title', 'N/A')}`\n\n"
    text += "Select any Language group to add new Season/Part group inside them. Or click '+' button to add new Language group.\n\n"

    buttons = []
    for i, lang in enumerate(languages):
        buttons.append([
            InlineKeyboardButton(
                f"{lang['name']} ({len(lang.get('seasons', []))} Seasons)", 
                callback_data=f"admin:{series_key}:l1:{i}"
            )
        ])
    
    buttons.append([InlineKeyboardButton("+ Language", callback_data=f"admin:{series_key}:add_lang")])
    buttons.append([InlineKeyboardButton("⬅️ Back to Series", callback_data=f"admin:{series_key}:back")])

    reply_markup = InlineKeyboardMarkup(buttons)

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

async def send_season_management_message(client: Client, user_id: int, series_key: str, lang_index: int, message_id: int = None):
    """Sends or edits the season management message."""
    logger.info(f"Sending season management message to user {user_id}")
    series_data = get_series_by_key(series_key)
    if not series_data:
        logger.warning(f"Series not found for key: {series_key}")
        await client.send_message(user_id, "Series not found.")
        return

    languages = series_data.get("languages", [])
    if lang_index >= len(languages):
        logger.warning(f"Language index {lang_index} out of range")
        await client.send_message(user_id, "Language not found.")
        return

    current_lang = languages[lang_index]
    language_name = current_lang["name"]
    seasons = current_lang.get("seasons", [])
    
    text = (
        f"**Series:** `{series_data.get('title', 'N/A')}`\n"
        f"**Language:** `{language_name}`\n\n"
        "Select any Seasons group to add new Quality group into them. Or click '+' button to add new Seasons group.\n\n"
    )

    buttons = []
    for i, season in enumerate(seasons):
        buttons.append([
            InlineKeyboardButton(
                f"{season['name']} ({len(season.get('qualities', []))} Qualities)", 
                callback_data=f"admin:{series_key}:l2:{i}"
            )
        ])
    
    buttons.append([InlineKeyboardButton("+ Season", callback_data=f"admin:{series_key}:add_season")])
    buttons.append([InlineKeyboardButton("🖼️ Change Poster for this Language", callback_data=f"newui_change_language_poster:{series_key}:{lang_index}")])
    buttons.append([InlineKeyboardButton(f"🗑️ Delete '{language_name}' Group", callback_data=f"admin:{series_key}:delete_lang:{lang_index}")])
    buttons.append([InlineKeyboardButton("⬅️ Back to Languages", callback_data=f"admin:{series_key}:back")])

    reply_markup = InlineKeyboardMarkup(buttons)

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

async def send_quality_management_message(client: Client, user_id: int, series_key: str, lang_index: int, season_index: int, message_id: int = None):
    """Sends or edits the quality management message."""
    logger.info(f"Sending quality management message to user {user_id}")
    series_data = get_series_by_key(series_key)
    if not series_data:
        logger.warning(f"Series not found for key: {series_key}")
        await client.send_message(user_id, "Series not found.")
        return

    languages = series_data.get("languages", [])
    if lang_index >= len(languages):
        logger.warning(f"Language index {lang_index} out of range")
        await client.send_message(user_id, "Language not found.")
        return

    current_lang = languages[lang_index]
    seasons = current_lang.get("seasons", [])
    if season_index >= len(seasons):
        logger.warning(f"Season index {season_index} out of range")
        await client.send_message(user_id, "Season not found.")
        return

    current_season = seasons[season_index]
    season_name = current_season["name"]
    qualities = current_season.get("qualities", [])
    
    text = (
        f"**Series:** `{series_data.get('title', 'N/A')}`\n"
        f"**Language:** `{current_lang['name']}`\n"
        f"**Season:** `{season_name}`\n\n"
        "Select any Quality group to add new files into them. Or click '+' button to add new Quality group.\n\n"
    )

    buttons = []
    for i, quality in enumerate(qualities):
        buttons.append([
            InlineKeyboardButton(
                f"{quality['name']}", 
                callback_data=f"admin:{series_key}:l3:{i}"
            )
        ])
    
    buttons.append([InlineKeyboardButton("+ Quality", callback_data=f"admin:{series_key}:add_quality")])
    buttons.append([InlineKeyboardButton("🖼️ Change Poster for this Season", callback_data=f"newui_change_season_poster:{series_key}:{lang_index}:{season_index}")])
    buttons.append([InlineKeyboardButton(f"🗑️ Delete '{season_name}' Group", callback_data=f"admin:{series_key}:delete_season:{season_index}")])
    buttons.append([InlineKeyboardButton("⬅️ Back to Seasons", callback_data=f"admin:{series_key}:back")])

    reply_markup = InlineKeyboardMarkup(buttons)

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
async def new_series_ui_command(client: Client, message: Message):
    """Handle the /newseriesui command."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} started new series UI")
    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None

    if not query:
        await message.reply("Usage: `/newseriesui <series_title>`")
        return

    temp_msg = await message.reply_photo(
        photo=NO_POSTER_FOUND_IMG,
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

# Message handlers for admin UI
async def handle_admin_message(client: Client, message: Message):
    """Handle messages for admin UI."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    logger.info(f"Received message {message.id} from admin {user_id} in chat {chat_id}")
    
    if message.chat.type != enums.ChatType.PRIVATE:
        return
    
    if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
        logger.info(f"Admin {user_id} has active state, processing as admin UI")
        
        if message.text:
            await handle_admin_text_input(client, message)
        elif message.photo or message.video or message.document:
            await handle_admin_media_input(client, message)
        return
    
    logger.info(f"Admin {user_id} has no active state, ignoring message")

async def handle_admin_text_input(client: Client, message: Message):
    """Handle text input from admins."""
    user_id = message.from_user.id
    current_state = temp_admin_data.get(user_id, {}).get("state")
    logger.info(f"Processing admin text input in state: {current_state}")
    
    if current_state == "NEW_SERIES_UI_AWAITING_LANGUAGE_INPUT":
        await process_language_input(client, message, message.text.strip())
    elif current_state == "NEW_SERIES_UI_AWAITING_SEASON_INPUT":
        await process_season_input(client, message, message.text.strip())
    elif current_state == "NEW_SERIES_UI_AWAITING_QUALITY_INPUT":
        await process_quality_input(client, message, message.text.strip())
    elif current_state == "NEW_SERIES_UI_AWAITING_CODEC_INPUT":
        await process_codec_input(client, message, message.text.strip())
    elif current_state.startswith("NEW_SERIES_UI_EDITING_"):
        field = temp_admin_data[user_id].get("current_field")
        await process_field_edit(client, message, message.text.strip(), field)

async def handle_admin_media_input(client: Client, message: Message):
    """Handle media input from admins."""
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

# Callback handler for admin UI
async def handle_admin_callback(client: Client, callback_query: CallbackQuery):
    """Handle admin UI callbacks."""
    user_id = callback_query.from_user.id
    data = callback_query.data
    logger.info(f"Processing admin UI callback: {data}")
    
    if not data.startswith("admin:") and not data.startswith("newui_"):
        logger.warning(f"Non-admin callback received: {data}")
        return
    
    if user_id not in temp_admin_data and not data.startswith("newui_"):
        logger.warning(f"Admin {user_id} not in temp_admin_data")
        await callback_query.answer("Session expired. Please start again with /newseriesui.", show_alert=True)
        return
    
    main_message_id = temp_admin_data.get(user_id, {}).get("main_message_id")
    
    # Handle newui callbacks (for series selection and initial setup)
    if data.startswith("newui_"):
        if data == "newui_search_again":
            await callback_query.answer("Search again...")
            query = temp_admin_data[user_id].get("query")
            if not query:
                await callback_query.answer("No previous query found.", show_alert=True)
                return
            
            temp_msg = await callback_query.message.edit_caption(
                "Searching TMDB and IMDb, please wait..."
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
            
            temp_admin_data[user_id]["search_results"] = all_results
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SEARCH_RESULTS"
            temp_admin_data[user_id]["main_message_id"] = temp_msg.id
            
            await send_series_selection_message(client, user_id, query, all_results, temp_msg.id)
        
        elif data.startswith("newui_tmdb_select:") or data.startswith("newui_imdb_select:"):
            unique_id = data.split(":")[1]
            
            if unique_id not in temp_admin_data[user_id]:
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
        
        elif data == "newui_back_to_search":
            await callback_query.answer("Going back to search results...")
            query = temp_admin_data[user_id].get("query")
            search_results = temp_admin_data[user_id].get("search_results", [])
            
            if not query or not search_results:
                await callback_query.answer("No previous search data found.", show_alert=True)
                return
            
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SEARCH_RESULTS"
            await send_series_selection_message(client, user_id, query, search_results, main_message_id)
        
        elif data.startswith("newui_change_poster:"):
            series_key = data.split(":")[1]
            await callback_query.answer("Send a new poster...")
            
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_AWAITING_SERIES_POSTER"
            temp_admin_data[user_id]["current_series_key"] = series_key
            
            await client.send_message(
                user_id,
                "Please send a photo or video to use as the series poster:"
            )
        
        elif data.startswith("newui_change_language_poster:"):
            parts = data.split(":")
            series_key = parts[1]
            lang_index = int(parts[2])
            await callback_query.answer("Send a new poster...")
            
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_AWAITING_LANGUAGE_POSTER"
            temp_admin_data[user_id]["current_series_key"] = series_key
            temp_admin_data[user_id]["current_lang_index"] = lang_index
            
            await client.send_message(
                user_id,
                f"Please send a photo or video to use as the poster for the language:"
            )
        
        elif data.startswith("newui_change_season_poster:"):
            parts = data.split(":")
            series_key = parts[1]
            lang_index = int(parts[2])
            season_index = int(parts[3])
            await callback_query.answer("Send a new poster...")
            
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_AWAITING_SEASON_POSTER"
            temp_admin_data[user_id]["current_series_key"] = series_key
            temp_admin_data[user_id]["current_lang_index"] = lang_index
            temp_admin_data[user_id]["current_season_index"] = season_index
            
            await client.send_message(
                user_id,
                f"Please send a photo or video to use as the poster for the season:"
            )
        
        elif data.startswith("newui_edit_details:"):
            series_key = data.split(":")[1]
            await callback_query.answer("Editing series details...")
            
            series_data = get_series_by_key(series_key)
            if not series_data:
                await client.send_message(user_id, "Series not found.")
                return
            
            text = (
                f"**Current Series Details:**\n\n"
                f"**Title:** `{series_data.get('title', 'N/A')}`\n"
                f"**Released On:** `{series_data.get('released_on', 'N/A')}`\n"
                f"**Genre:** `{series_data.get('genre', 'N/A')}`\n"
                f"**Rating:** `{series_data.get('rating', 'N/A')}`\n\n"
                "Click on a field to edit it:"
            )
            
            buttons = [
                [InlineKeyboardButton("✏️ Title", callback_data=f"newui_edit_field:{series_key}:title")],
                [InlineKeyboardButton("✏️ Released On", callback_data=f"newui_edit_field:{series_key}:released_on")],
                [InlineKeyboardButton("✏️ Genre", callback_data=f"newui_edit_field:{series_key}:genre")],
                [InlineKeyboardButton("✏️ Rating", callback_data=f"newui_edit_field:{series_key}:rating")],
                [InlineKeyboardButton("⬅️ Back", callback_data=f"admin:{series_key}:back")]
            ]
            
            reply_markup = InlineKeyboardMarkup(buttons)
            
            try:
                await client.edit_message_caption(
                    chat_id=user_id,
                    message_id=main_message_id,
                    caption=text,
                    reply_markup=reply_markup
                )
                temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_EDITING_DETAILS"
            except Exception as e:
                logger.error(f"Error showing edit details: {e}")
                await client.send_message(user_id, "Error showing edit details. Please try again.")
        
        elif data.startswith("newui_edit_field:"):
            parts = data.split(":")
            series_key = parts[1]
            field = parts[2]
            await callback_query.answer(f"Editing {field}...")
            
            temp_admin_data[user_id]["state"] = f"NEW_SERIES_UI_EDITING_{field.upper()}"
            temp_admin_data[user_id]["current_series_key"] = series_key
            temp_admin_data[user_id]["current_field"] = field
            
            field_display = field.replace("_", " ").title()
            await client.send_message(
                user_id,
                f"Enter new value for {field_display}:"
            )
    
    # Handle admin callbacks (for navigation within a series)
    elif data.startswith("admin:"):
        parts = data.split(":")
        series_key = parts[1]
        action = parts[2] if len(parts) > 2 else None
        
        if action == "back":
            await callback_query.answer("Going back...")
            
            series_data = get_series_by_key(series_key)
            if series_data:
                await send_series_details_message(client, user_id, series_data, main_message_id)
                temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SERIES_DETAILS"
            else:
                await client.send_message(user_id, "Series not found.")
        
        elif action == "l1":  # Languages
            await callback_query.answer("Managing languages...")
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_LANGUAGES"
            await send_language_management_message(client, user_id, series_key, main_message_id)
        
        elif action == "add_lang":
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
        
        elif action == "delete_lang":
            lang_index = int(parts[3])
            await callback_query.answer("Deleting language...")
            
            series_data = get_series_by_key(series_key)
            if not series_data:
                await client.send_message(user_id, "Series not found.")
                return
            
            languages = series_data.get("languages", [])
            if lang_index >= len(languages):
                await client.send_message(user_id, "Language not found.")
                return
            
            language_name = languages[lang_index]["name"]
            
            if delete_language(series_key, language_name):
                await client.send_message(user_id, f"Language '{language_name}' deleted successfully.")
                await send_language_management_message(client, user_id, series_key, main_message_id)
            else:
                await client.send_message(user_id, f"Failed to delete language '{language_name}'.")
        
        elif action == "l2":  # Seasons
            lang_index = int(parts[3])
            await callback_query.answer("Managing seasons...")
            temp_admin_data[user_id]["current_lang_index"] = lang_index
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_SEASONS"
            await send_season_management_message(client, user_id, series_key, lang_index, main_message_id)
        
        elif action == "add_season":
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
        
        elif action == "delete_season":
            season_index = int(parts[3])
            await callback_query.answer("Deleting season...")
            
            series_data = get_series_by_key(series_key)
            if not series_data:
                await client.send_message(user_id, "Series not found.")
                return
            
            languages = series_data.get("languages", [])
            lang_index = temp_admin_data[user_id].get("current_lang_index", 0)
            if lang_index >= len(languages):
                await client.send_message(user_id, "Language not found.")
                return
            
            current_lang = languages[lang_index]
            seasons = current_lang.get("seasons", [])
            if season_index >= len(seasons):
                await client.send_message(user_id, "Season not found.")
                return
            
            season_name = seasons[season_index]["name"]
            language_name = current_lang["name"]
            
            if delete_season(series_key, language_name, season_name):
                await client.send_message(user_id, f"Season '{season_name}' deleted successfully.")
                await send_season_management_message(client, user_id, series_key, lang_index, main_message_id)
            else:
                await client.send_message(user_id, f"Failed to delete season '{season_name}'.")
        
        elif action == "l3":  # Qualities
            lang_index = temp_admin_data[user_id].get("current_lang_index", 0)
            season_index = int(parts[3])
            await callback_query.answer("Managing qualities...")
            temp_admin_data[user_id]["current_lang_index"] = lang_index
            temp_admin_data[user_id]["current_season_index"] = season_index
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_QUALITIES"
            await send_quality_management_message(client, user_id, series_key, lang_index, season_index, main_message_id)
        
        elif action == "add_quality":
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
        
        elif action == "publish":
            await callback_query.answer("Publishing series...")
            
            text = (
                "Do you want to publish this series?\n\n"
                "NOTE: Once you publish this series, you can't edit it anymore.\n"
                "All the empty groups will be removed automatically."
            )
            
            buttons = [
                [InlineKeyboardButton("✅ Yes", callback_data=f"admin:{series_key}:confirm_publish")],
                [InlineKeyboardButton("❌ No", callback_data=f"admin:{series_key}:cancel_publish")]
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
        
        elif action == "confirm_publish":
            await callback_query.answer("Publishing...")
            
            if publish_series(series_key):
                await client.edit_message_caption(
                    chat_id=user_id,
                    message_id=main_message_id,
                    caption="✅ Series published successfully!"
                )
                temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_PUBLISHED"
            else:
                await client.edit_message_caption(
                    chat_id=user_id,
                    message_id=main_message_id,
                    caption="❌ Failed to publish series. Please try again."
                )
        
        elif action == "cancel_publish":
            await callback_query.answer("Cancelling publish...")
            
            series_data = get_series_by_key(series_key)
            if series_data:
                await send_series_details_message(client, user_id, series_data, main_message_id)
            else:
                await client.send_message(user_id, "Series not found.")

# Process input functions
async def process_language_input(client: Client, message: Message, language_name: str):
    """Process language input from admin."""
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    ask_message_id = temp_admin_data[user_id].get("ask_message_id")
    logger.info(f"Processing language input: {language_name}")

    if not series_key:
        await message.reply("Error: Series key not found in session.")
        return

    try:
        if ask_message_id:
            await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
        await message.delete()
    except Exception as e:
        logger.warning(f"Could not delete prompt/user message: {e}")

    if add_or_update_language(series_key, language_name):
        confirmation_msg = await client.send_message(
            chat_id=user_id,
            text=f"Language '{language_name}' added/updated successfully.",
            reply_markup=ReplyKeyboardRemove()
        )
        asyncio.create_task(confirmation_msg.delete())

        await send_language_management_message(client, user_id, series_key, main_message_id)
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_LANGUAGES"
    else:
        await message.reply("Failed to add/update language.")

    temp_admin_data[user_id].pop("ask_message_id", None)

async def process_season_input(client: Client, message: Message, season_name: str):
    """Process season input from admin."""
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    lang_index = temp_admin_data[user_id].get("current_lang_index", 0)
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    ask_message_id = temp_admin_data[user_id].get("ask_message_id")
    logger.info(f"Processing season input: {season_name}")

    if not series_key:
        await message.reply("Error: Series key not found in session.")
        return

    try:
        if ask_message_id:
            await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
        await message.delete()
    except Exception as e:
        logger.warning(f"Could not delete prompt/user message: {e}")

    series_data = get_series_by_key(series_key)
    if not series_data:
        await message.reply("Error: Series not found.")
        return
    
    languages = series_data.get("languages", [])
    if lang_index >= len(languages):
        await message.reply("Error: Language not found.")
        return
    
    language_name = languages[lang_index]["name"]

    if add_or_update_season(series_key, language_name, season_name):
        confirmation_msg = await client.send_message(
            chat_id=user_id,
            text=f"Season '{season_name}' added/updated successfully.",
            reply_markup=ReplyKeyboardRemove()
        )
        asyncio.create_task(confirmation_msg.delete())

        await send_season_management_message(client, user_id, series_key, lang_index, main_message_id)
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_SEASONS"
    else:
        await message.reply("Failed to add/update season.")

    temp_admin_data[user_id].pop("ask_message_id", None)

async def process_quality_input(client: Client, message: Message, quality_name: str):
    """Process quality input from admin."""
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    lang_index = temp_admin_data[user_id].get("current_lang_index", 0)
    season_index = temp_admin_data[user_id].get("current_season_index", 0)
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    ask_message_id = temp_admin_data[user_id].get("ask_message_id")
    logger.info(f"Processing quality input: {quality_name}")

    if not all([series_key, lang_index, season_index]):
        await message.reply("Error: Missing data in session.")
        return

    try:
        if ask_message_id:
            await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
        await message.delete()
    except Exception as e:
        logger.warning(f"Could not delete prompt/user message: {e}")

    series_data = get_series_by_key(series_key)
    if not series_data:
        await message.reply("Error: Series not found.")
        return
    
    languages = series_data.get("languages", [])
    if lang_index >= len(languages):
        await message.reply("Error: Language not found.")
        return
    
    current_lang = languages[lang_index]
    seasons = current_lang.get("seasons", [])
    if season_index >= len(seasons):
        await message.reply("Error: Season not found.")
        return
    
    season_name = seasons[season_index]["name"]
    language_name = current_lang["name"]

    if add_or_update_quality(series_key, language_name, season_name, quality_name):
        confirmation_msg = await client.send_message(
            chat_id=user_id,
            text=f"Quality '{quality_name}' added/updated successfully.",
            reply_markup=ReplyKeyboardRemove()
        )
        asyncio.create_task(confirmation_msg.delete())

        await send_quality_management_message(client, user_id, series_key, lang_index, season_index, main_message_id)
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_QUALITIES"
    else:
        await message.reply("Failed to add/update quality.")

    temp_admin_data[user_id].pop("ask_message_id", None)

async def process_codec_input(client: Client, message: Message, codec: str):
    """Process codec input from admin."""
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    lang_index = temp_admin_data[user_id].get("current_lang_index", 0)
    season_index = temp_admin_data[user_id].get("current_season_index", 0)
    quality_index = temp_admin_data[user_id].get("current_quality_index", 0)
    first_file_id = temp_admin_data[user_id].get("first_file_id")
    last_file_id = temp_admin_data[user_id].get("last_file_id")
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    ask_message_id = temp_admin_data[user_id].get("ask_message_id")
    logger.info(f"Processing codec input: {codec}")

    if not all([series_key, lang_index, season_index, quality_index, first_file_id, last_file_id]):
        await message.reply("Error: Missing data in session.")
        return

    try:
        if ask_message_id:
            await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
        await message.delete()
    except Exception as e:
        logger.warning(f"Could not delete prompt/user message: {e}")

    series_data = get_series_by_key(series_key)
    if not series_data:
        await message.reply("Error: Series not found.")
        return
    
    languages = series_data.get("languages", [])
    if lang_index >= len(languages):
        await message.reply("Error: Language not found.")
        return
    
    current_lang = languages[lang_index]
    seasons = current_lang.get("seasons", [])
    if season_index >= len(seasons):
        await message.reply("Error: Season not found.")
        return
    
    current_season = seasons[season_index]
    qualities = current_season.get("qualities", [])
    if quality_index >= len(qualities):
        await message.reply("Error: Quality not found.")
        return
    
    quality_name = qualities[quality_index]["name"]
    season_name = current_season["name"]
    language_name = current_lang["name"]

    link_key = f"{first_file_id}_{last_file_id}"
    if add_or_update_quality(series_key, language_name, season_name, quality_name, link_key=link_key, codec=codec):
        confirmation_msg = await client.send_message(
            chat_id=user_id,
            text=f"Files added to database successfully for {language_name}-{season_name}-{quality_name}.",
            reply_markup=ReplyKeyboardRemove()
        )
        asyncio.create_task(confirmation_msg.delete())

        await send_quality_management_message(client, user_id, series_key, lang_index, season_index, main_message_id)
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_QUALITIES"
    else:
        await message.reply("Failed to add files to database.")

    temp_admin_data[user_id].pop("ask_message_id", None)
    temp_admin_data[user_id].pop("first_file_id", None)
    temp_admin_data[user_id].pop("last_file_id", None)

async def process_field_edit(client: Client, message: Message, new_value: str, field: str):
    """Process field edit from admin."""
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    logger.info(f"Processing field edit: {field} = {new_value}")

    if not series_key:
        await message.reply("Error: Series key not found in session.")
        return

    if update_series_field(series_key, field, new_value):
        confirmation_msg = await client.send_message(
            chat_id=user_id,
            text=f"Field '{field}' updated successfully.",
            reply_markup=ReplyKeyboardRemove()
        )
        asyncio.create_task(confirmation_msg.delete())

        series_data = get_series_by_key(series_key)
        if series_data:
            await send_series_details_message(client, user_id, series_data, main_message_id)
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SERIES_DETAILS"
        else:
            await client.send_message(user_id, "Series not found.")
    else:
        await message.reply(f"Failed to update field '{field}'.")

    temp_admin_data[user_id].pop("current_field", None)

async def process_poster_input(client: Client, message: Message, poster_type: str):
    """Process poster input from admin."""
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    logger.info(f"Processing poster input for type: {poster_type}")

    if not series_key:
        await message.reply("Error: Series key not found in session.")
        return

    poster_file_id = await download_and_upload_poster(client, message=message)
    if not poster_file_id:
        await message.reply("Failed to process the poster. Please try again.")
        return

    if poster_type == "series":
        if update_poster_file_id(series_key, poster_file_id):
            await message.reply("Series poster updated successfully.")
        else:
            await message.reply("Failed to update series poster.")
    elif poster_type == "language":
        lang_index = temp_admin_data[user_id].get("current_lang_index", 0)
        series_data = get_series_by_key(series_key)
        if series_data and lang_index < len(series_data.get("languages", [])):
            language_name = series_data["languages"][lang_index]["name"]
            if add_or_update_language(series_key, language_name, poster_file_id=poster_file_id):
                await message.reply(f"Language poster for '{language_name}' updated successfully.")
            else:
                await message.reply("Failed to update language poster.")
        else:
            await message.reply("Failed to update language poster.")
    elif poster_type == "season":
        lang_index = temp_admin_data[user_id].get("current_lang_index", 0)
        season_index = temp_admin_data[user_id].get("current_season_index", 0)
        series_data = get_series_by_key(series_key)
        if series_data and lang_index < len(series_data.get("languages", [])):
            current_lang = series_data["languages"][lang_index]
            if season_index < len(current_lang.get("seasons", [])):
                season_name = current_lang["seasons"][season_index]["name"]
                language_name = current_lang["name"]
                if add_or_update_season(series_key, language_name, season_name, poster_file_id=poster_file_id):
                    await message.reply(f"Season poster for '{language_name}-{season_name}' updated successfully.")
                else:
                    await message.reply("Failed to update season poster.")
            else:
                await message.reply("Failed to update season poster.")
        else:
            await message.reply("Failed to update season poster.")

    current_state = temp_admin_data[user_id].get("state")
    if current_state == "NEW_SERIES_UI_SERIES_DETAILS":
        series_data = get_series_by_key(series_key)
        if series_data:
            await send_series_details_message(client, user_id, series_data, main_message_id)
    elif current_state == "NEW_SERIES_UI_MANAGE_LANGUAGES":
        await send_language_management_message(client, user_id, series_key, main_message_id)
    elif current_state == "NEW_SERIES_UI_MANAGE_SEASONS":
        lang_index = temp_admin_data[user_id].get("current_lang_index", 0)
        await send_season_management_message(client, user_id, series_key, lang_index, main_message_id)
    elif current_state == "NEW_SERIES_UI_MANAGE_QUALITIES":
        lang_index = temp_admin_data[user_id].get("current_lang_index", 0)
        season_index = temp_admin_data[user_id].get("current_season_index", 0)
        await send_quality_management_message(client, user_id, series_key, lang_index, season_index, main_message_id)

async def process_first_file_input(client: Client, message: Message):
    """Process first file input from admin."""
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    lang_index = temp_admin_data[user_id].get("current_lang_index", 0)
    season_index = temp_admin_data[user_id].get("current_season_index", 0)
    quality_index = temp_admin_data[user_id].get("current_quality_index", 0)
    logger.info(f"Processing first file input")

    if not all([series_key, lang_index, season_index, quality_index]):
        await message.reply("Error: Missing data in session.")
        return

    series_data = get_series_by_key(series_key)
    if not series_data:
        await message.reply("Error: Series not found.")
        return
    
    languages = series_data.get("languages", [])
    if lang_index >= len(languages):
        await message.reply("Error: Language not found.")
        return
    
    current_lang = languages[lang_index]
    seasons = current_lang.get("seasons", [])
    if season_index >= len(seasons):
        await message.reply("Error: Season not found.")
        return
    
    current_season = seasons[season_index]
    qualities = current_season.get("qualities", [])
    if quality_index >= len(qualities):
        await message.reply("Error: Quality not found.")
        return
    
    quality_name = qualities[quality_index]["name"]
    season_name = current_season["name"]
    language_name = current_lang["name"]

    channel_id, msg_id = await get_message_id(client, message)
    if not channel_id or not msg_id:
        await message.reply("Invalid file. Please forward a file from a channel.")
        return

    temp_admin_data[user_id]["first_file_id"] = f"{channel_id}_{msg_id}"
    temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_AWAITING_LAST_FILE"

    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"Could not delete user message: {e}")

    await client.send_message(
        user_id,
        f"Forward me the last file (with tag) for {language_name}-{season_name}-{quality_name}\n"
        f"Go to first file: https://t.me/c/{str(channel_id).replace('-100', '')}/{msg_id}"
    )

async def process_last_file_input(client: Client, message: Message):
    """Process last file input from admin."""
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    lang_index = temp_admin_data[user_id].get("current_lang_index", 0)
    season_index = temp_admin_data[user_id].get("current_season_index", 0)
    quality_index = temp_admin_data[user_id].get("current_quality_index", 0)
    first_file_id = temp_admin_data[user_id].get("first_file_id")
    logger.info(f"Processing last file input")

    if not all([series_key, lang_index, season_index, quality_index, first_file_id]):
        await message.reply("Error: Missing data in session.")
        return

    series_data = get_series_by_key(series_key)
    if not series_data:
        await message.reply("Error: Series not found.")
        return
    
    languages = series_data.get("languages", [])
    if lang_index >= len(languages):
        await message.reply("Error: Language not found.")
        return
    
    current_lang = languages[lang_index]
    seasons = current_lang.get("seasons", [])
    if season_index >= len(seasons):
        await message.reply("Error: Season not found.")
        return
    
    current_season = seasons[season_index]
    qualities = current_season.get("qualities", [])
    if quality_index >= len(qualities):
        await message.reply("Error: Quality not found.")
        return
    
    quality_name = qualities[quality_index]["name"]
    season_name = current_season["name"]
    language_name = current_lang["name"]

    channel_id, msg_id = await get_message_id(client, message)
    if not channel_id or not msg_id:
        await message.reply("Invalid file. Please forward a file from a channel.")
        return

    last_file_id = f"{channel_id}_{msg_id}"
    temp_admin_data[user_id]["last_file_id"] = last_file_id
    temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_AWAITING_CODEC_INPUT"

    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"Could not delete user message: {e}")

    reply_keyboard = ReplyKeyboardMarkup(
        [
            [KeyboardButton("H.264"), KeyboardButton("H.265"), KeyboardButton("H.265 10bit")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    
    ask_msg = await client.send_message(
        user_id,
        f"Send me the codec field for {language_name}-{season_name}-{quality_name}:",
        reply_markup=reply_keyboard
    )
    temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
