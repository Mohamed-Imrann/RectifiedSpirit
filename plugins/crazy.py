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
    get_poster_file_id, update_poster_file_id, publish_series, episodes_collection,
    get_series, get_poster_manuel
)
from utils import (
    get_message_id, get_messages, delete_messages_from_user_chat, 
    get_poster, find_most_similar_title
)
from fuzzywuzzy import fuzz
from pyrogram.errors import MessageIdInvalid, FloodWait

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

def create_dynamic_layout_from_pattern(items: List[str], layout_pattern: List[int], add_buttons: List[str] = None):
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

    language_names = [lang['name'] for lang in languages]
    
    add_buttons = [
        ("⬅️ Back", "back_to_series")
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

    season_names = [season['name'] for season in seasons]
    
    add_buttons = [
        ("🖼️ Change Poster for this Language", "change_lang_poster"),
        (f"🗑️ Delete '{language_name}' Group", "delete_language"),
        ("⬅️ Back", "back_to_languages")
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

    quality_names = [quality['name'] for quality in qualities]
    
    add_buttons = [
        ("🖼️ Change Poster for this Season", "change_season_poster"),
        (f"🗑️ Delete '{season_name}' Group", "delete_season"),
        ("⬅️ Back", "back_to_seasons")
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
    except Exception as e:
        logger.error(f"Error editing quality management message: {e}")
        return None

@Client.on_message(filters.command('newseriesui') & filters.user(ADMINS))
async def new_series_ui_command(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} started new series UI")
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

@Client.on_message(filters.text & filters.private & filters.user(ADMINS))
async def handle_admin_text_message(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Received admin text message {message.id} from user {user_id}")
    
    if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
        await handle_admin_text_input(client, message)

@Client.on_message((filters.photo | filters.video | filters.document) & filters.private & filters.user(ADMINS))
async def handle_admin_media_message(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Received admin media message {message.id} from user {user_id}")
    
    if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
        await handle_admin_media_input(client, message)

@Client.on_callback_query(filters.user(ADMINS))
async def admin_ui_callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    logger.info(f"Received admin UI callback from user {user_id}: {data}")

    await newui_callback_handler(client, callback_query)

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
    
    elif data == "manage_languages":
        series_key = temp_admin_data[user_id].get("current_series_key")
        await callback_query.answer("Managing languages...")
        temp_admin_data[user_id]["state"] = "MANAGE_LANGUAGES"
        await send_language_management_message(client, user_id, series_key, main_message_id)
    
    elif data.startswith("add_to_row_"):
        row_index = int(data.split("_")[-1])
        current_state = temp_admin_data[user_id].get("state")
        
        if current_state == "MANAGE_LANGUAGES":
            await callback_query.answer(f"Adding language to row {row_index + 1}...")
            temp_admin_data[user_id]["target_row"] = row_index
            
            reply_keyboard = ReplyKeyboardMarkup(
                [
                    [KeyboardButton("English"), KeyboardButton("Spanish"), KeyboardButton("Japanese")],
                    [KeyboardButton("Korean"), KeyboardButton("French"), KeyboardButton("German")]
                ],
                resize_keyboard=True,
                one_time_keyboard=True
            )
            
            ask_msg = await client.send_message(
                user_id,
                f"Enter language name to add to row {row_index + 1}:",
                reply_markup=reply_keyboard
            )
            temp_admin_data[user_id]["state"] = "AWAITING_LANGUAGE_INPUT"
            temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
            
        elif current_state == "MANAGE_SEASONS":
            await callback_query.answer(f"Adding season to row {row_index + 1}...")
            temp_admin_data[user_id]["target_row"] = row_index
            
            reply_keyboard = ReplyKeyboardMarkup(
                [
                    [KeyboardButton("Season 1"), KeyboardButton("Season 2"), KeyboardButton("Season 3")],
                    [KeyboardButton("Season 4"), KeyboardButton("Season 5"), KeyboardButton("Season 6")],
                    [KeyboardButton("Part 1"), KeyboardButton("Part 2")]
                ],
                resize_keyboard=True,
                one_time_keyboard=True
            )
            
            ask_msg = await client.send_message(
                user_id,
                f"Enter season name to add to row {row_index + 1}:",
                reply_markup=reply_keyboard
            )
            temp_admin_data[user_id]["state"] = "AWAITING_SEASON_INPUT"
            temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
            
        elif current_state == "MANAGE_QUALITIES":
            await callback_query.answer(f"Adding quality to row {row_index + 1}...")
            temp_admin_data[user_id]["target_row"] = row_index
            
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
                f"Enter quality name to add to row {row_index + 1}:",
                reply_markup=reply_keyboard
            )
            temp_admin_data[user_id]["state"] = "AWAITING_QUALITY_INPUT"
            temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
    
    elif data.startswith("item_"):
        item_index = int(data.split("_")[1])
        current_state = temp_admin_data[user_id].get("state")
        
        if current_state == "MANAGE_LANGUAGES":
            series_key = temp_admin_data[user_id].get("current_series_key")
            languages = get_languages(series_key)
            
            if 0 <= item_index < len(languages):
                language_name = languages[item_index]["name"]
                await callback_query.answer(f"Selected: {language_name}")
                temp_admin_data[user_id]["current_language"] = language_name
                temp_admin_data[user_id]["current_language_index"] = item_index
                temp_admin_data[user_id]["state"] = "MANAGE_SEASONS"
                await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
            else:
                await callback_query.answer("Invalid selection.", show_alert=True)
                
        elif current_state == "MANAGE_SEASONS":
            series_key = temp_admin_data[user_id].get("current_series_key")
            language_name = temp_admin_data[user_id].get("current_language")
            seasons = get_seasons(series_key, language_name)
            
            if 0 <= item_index < len(seasons):
                season_name = seasons[item_index]["name"]
                await callback_query.answer(f"Selected: {season_name}")
                temp_admin_data[user_id]["current_season"] = season_name
                temp_admin_data[user_id]["current_season_index"] = item_index
                temp_admin_data[user_id]["state"] = "MANAGE_QUALITIES"
                await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
            else:
                await callback_query.answer("Invalid selection.", show_alert=True)
                
        elif current_state == "MANAGE_QUALITIES":
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
                    f"Add me to the channel as admin and forward me the first file (with tag) for {language_name}-{season_name}-{quality_name}"
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

async def process_language_input(client: Client, message: Message, language_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    target_row = temp_admin_data[user_id].get("target_row")
    
    await message.reply("Language Updated", reply_markup=ReplyKeyboardRemove())
    
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
            await send_language_management_message(client, user_id, series_key, main_message_id)
            
            temp_admin_data[user_id]["state"] = "MANAGE_LANGUAGES"
            temp_admin_data[user_id].pop("target_row", None)
        else:
            await message.reply(f"Failed to add language.")
    except Exception as e:
        logger.error(f"Error updating series: {e}")
        await message.reply(f"Failed to add language.")

async def process_season_input(client: Client, message: Message, season_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    target_row = temp_admin_data[user_id].get("target_row")
    
    await message.reply("Season Updated", reply_markup=ReplyKeyboardRemove())
    
    series_data = get_series_by_key(series_key)
    if not series_data:
        await message.reply("Series not found.")
        return
    
    current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
    if not current_lang:
        await message.reply("Language not found.")
        return
    
    seasons = current_lang.get("seasons", [])
    current_layout = current_lang.get("season_layout", [])
    
    existing_season = next((s for s in seasons if s["name"].lower() == season_name.lower()), None)
    if existing_season:
        await message.reply(f"Season '{season_name}' already exists in {language_name}.")
        return
    
    while len(current_layout) <= target_row:
        current_layout.append(0)
    
    insertion_index = sum(current_layout[:target_row]) + current_layout[target_row]
    
    new_season = {"name": season_name, "qualities": [], "quality_layout": []}
    
    seasons.insert(insertion_index, new_season)
    
    current_layout[target_row] += 1
    
    try:
        result = series_collection.update_one(
            {"_id": series_key, "languages.name": language_name},
            {"$set": {
                "languages.$.seasons": seasons,
                "languages.$.season_layout": current_layout
            }}
        )
        if result.modified_count > 0:
            main_message_id = temp_admin_data[user_id].get("main_message_id")
            await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
            
            temp_admin_data[user_id]["state"] = "MANAGE_SEASONS"
            temp_admin_data[user_id].pop("target_row", None)
        else:
            await message.reply(f"Failed to add season.")
    except Exception as e:
        logger.error(f"Error updating series: {e}")
        await message.reply(f"Failed to add season.")

async def process_quality_input(client: Client, message: Message, quality_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    target_row = temp_admin_data[user_id].get("target_row")
    
    await message.reply("Quality Updated", reply_markup=ReplyKeyboardRemove())
    
    series_data = get_series_by_key(series_key)
    if not series_data:
        await message.reply("Series not found.")
        return
    
    current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
    if not current_lang:
        await message.reply("Language not found.")
        return
    
    current_season = next((s for s in current_lang.get("seasons", []) if s["name"].lower() == season_name.lower()), None)
    if not current_season:
        await message.reply("Season not found.")
        return
    
    qualities = current_season.get("qualities", [])
    current_layout = current_season.get("quality_layout", [])
    
    existing_quality = next((q for q in qualities if q["name"].lower() == quality_name.lower()), None)
    if existing_quality:
        await message.reply(f"Quality '{quality_name}' already exists in {language_name}-{season_name}.")
        return
    
    while len(current_layout) <= target_row:
        current_layout.append(0)
    
    insertion_index = sum(current_layout[:target_row]) + current_layout[target_row]
    
    new_quality = {"name": quality_name}
    
    qualities.insert(insertion_index, new_quality)
    
    current_layout[target_row] += 1
    
    try:
        result = series_collection.update_one(
            {"_id": series_key, "languages.name": language_name, "languages.seasons.name": season_name},
            {"$set": {
                "languages.$.seasons.$[season].qualities": qualities,
                "languages.$.seasons.$[season].quality_layout": current_layout
            }},
            array_filters=[{"season.name": season_name}]
        )
        if result.modified_count > 0:
            main_message_id = temp_admin_data[user_id].get("main_message_id")
            await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
            
            temp_admin_data[user_id]["state"] = "MANAGE_QUALITIES"
            temp_admin_data[user_id].pop("target_row", None)
        else:
            await message.reply(f"Failed to add quality.")
    except Exception as e:
        logger.error(f"Error updating series: {e}")
        await message.reply(f"Failed to add quality.")

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
        await send_series_details_message(client, user_id, series_data, temp_admin_data[user_id].get("main_message_id"))
    elif poster_type == "language":
        language_name = temp_admin_data[user_id].get("current_language")
        add_or_update_language(series_key, language_name, poster_file_id)
        await send_season_management_message(client, user_id, series_key, language_name, temp_admin_data[user_id].get("main_message_id"))
    elif poster_type == "season":
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        add_or_update_season(series_key, language_name, season_name, poster_file_id)
        await send_quality_management_message(client, user_id, series_key, language_name, season_name, temp_admin_data[user_id].get("main_message_id"))
    
    temp_admin_data[user_id]["state"] = "SERIES_DETAILS"

async def process_first_file_input(client: Client, message: Message):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    quality_name = temp_admin_data[user_id].get("current_quality")
    
    channel_id, msg_id = await get_message_id(client, message)
    if not channel_id or not msg_id:
        await message.reply("Invalid message format. Please forward a message from a channel.")
        return
    
    if channel_id not in DB_CHANNEL:
        await message.reply("This file is not from a valid channel.")
        return
    
    temp_admin_data[user_id]["first_file"] = {
        "channel_id": channel_id,
        "message_id": msg_id
    }
    temp_admin_data[user_id]["state"] = "AWAITING_LAST_FILE"
    
    await message.reply(f"Now forward me the last file (with tag) for {language_name}-{season_name}-{quality_name}")

async def process_last_file_input(client: Client, message: Message):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    quality_name = temp_admin_data[user_id].get("current_quality")
    
    channel_id, msg_id = await get_message_id(client, message)
    if not channel_id or not msg_id:
        await message.reply("Invalid message format. Please forward a message from a channel.")
        return
    
    if channel_id not in DB_CHANNEL:
        await message.reply("This file is not from a valid channel.")
        return
    
    first_file = temp_admin_data[user_id].get("first_file")
    if not first_file:
        await message.reply("First file not found. Please start over.")
        return
    
    first_msg_id = first_file["message_id"]
    last_msg_id = msg_id
    
    if first_msg_id > last_msg_id:
        first_msg_id, last_msg_id = last_msg_id, first_msg_id
    
    link_key = str(uuid.uuid4())
    
    messages = await get_messages(client, channel_id, range(first_msg_id, last_msg_id + 1))
    if not messages:
        await message.reply("No messages found in the specified range.")
        return
    
    files_data = []
    for msg in messages:
        file_info = get_file_id(msg)
        if file_info:
            files_data.append({
                "file_id": file_info.file_id,
                "caption": msg.caption or ""
            })
    
    if not files_data:
        await message.reply("No files found in the specified range.")
        return
    
    episodes_collection.insert_one({
        "file_link_key": link_key,
        "files": files_data,
        "channel_id": channel_id,
        "first_msg_id": first_msg_id,
        "last_msg_id": last_msg_id
    })
    
    add_or_update_quality(series_key, language_name, season_name, quality_name, link_key)
    
    await message.reply(f"Successfully added {len(files_data)} files to {language_name}-{season_name}-{quality_name}")
    
    temp_admin_data[user_id].pop("first_file", None)
    temp_admin_data[user_id]["state"] = "MANAGE_QUALITIES"
    
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)

async def process_codec_input(client: Client, message: Message, codec_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    quality_name = temp_admin_data[user_id].get("current_quality")
    
    await message.reply("Codec Updated", reply_markup=ReplyKeyboardRemove())
    
    series_data = get_series_by_key(series_key)
    if not series_data:
        await message.reply("Series not found.")
        return
    
    current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
    if not current_lang:
        await message.reply("Language not found.")
        return
    
    current_season = next((s for s in current_lang.get("seasons", []) if s["name"].lower() == season_name.lower()), None)
    if not current_season:
        await message.reply("Season not found.")
        return
    
    current_quality = next((q for q in current_season.get("qualities", []) if q["name"].lower() == quality_name.lower()), None)
    if not current_quality:
        await message.reply("Quality not found.")
        return
    
    current_quality["codec"] = codec_name
    
    try:
        result = series_collection.update_one(
            {"_id": series_key, "languages.name": language_name, "languages.seasons.name": season_name},
            {"$set": {
                "languages.$.seasons.$[season].qualities.$[quality].codec": codec_name
            }},
            array_filters=[
                {"season.name": season_name},
                {"quality.name": quality_name}
            ]
        )
        if result.modified_count > 0:
            main_message_id = temp_admin_data[user_id].get("main_message_id")
            await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
            
            temp_admin_data[user_id]["state"] = "MANAGE_QUALITIES"
        else:
            await message.reply(f"Failed to update codec.")
    except Exception as e:
        logger.error(f"Error updating series: {e}")
        await message.reply(f"Failed to update codec.")
