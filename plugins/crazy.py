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
from pyrogram.errors import FloodWait, BadRequest, MessageIdInvalid, UserNotParticipant, ChatAdminRequired
from imdb import Cinemagoer
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
from fuzzywuzzy import fuzz
from pyrogram.errors import MessageIdInvalid, FloodWait, UserNotParticipant, ChatAdminRequired

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

async def download_and_upload_poster(client: Client, poster_url: str = None, message: Message = None, send_to_log_channel: bool = True):
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
            if send_to_log_channel:
                logger.info("Uploading poster to LOG_CHANNEL")
                sent_msg = await client.send_photo(LOG_CHANNEL, photo=download_path, caption="#MainPoster")
                file_id = sent_msg.photo.file_id
                try:
                    await sent_msg.delete()
                    logger.debug("Deleted temporary poster from LOG_CHANNEL")
                except Exception as e:
                    logger.warning(f"Could not delete temporary poster message from LOG_CHANNEL: {e}")
            else:
                # For admin posters, don't send to LOG_CHANNEL
                logger.info("Uploading poster without sending to LOG_CHANNEL")
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
    
    # Check if user has an assigned channel
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

    await send_series_selection_message(client, user_id, query, all_results, temp_msg.id)

@Client.on_message(filters.command('assign') & filters.user(ADMINS))
async def assign_command(client: Client, message: Message):
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

@Client.on_message(filters.command('unassign') & filters.user(ADMINS))
async def unassign_command(client: Client, message: Message):
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

@Client.on_message(filters.command('listadmins') & filters.user(ADMINS))
async def listadmins_command(client: Client, message: Message):
    assignments = get_admin_assignments()
    
    if not assignments:
        await message.reply("No admin assignments found.")
        return
    
    text = "**Admin Assignments:**\n\n"
    for user_id, channel_id in assignments.items():
        text += f"• Admin: `{user_id}` → Channel: `{channel_id}`\n"
    
    await message.reply(text)

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

    try:
        await callback_query.answer()
    except Exception as e:
        logger.warning(f"Failed to acknowledge callback: {e}")

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

async def process_language_input(client: Client, message: Message, language_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    target_row = temp_admin_data[user_id].get("target_row")
    
    # Delete the prompt message
    if "ask_message_id" in temp_admin_data[user_id]:
        try:
            await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
        except Exception:
            pass
    
    # Send confirmation message
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
            await send_language_management_message(client, user_id, series_key, main_message_id)
            
            # Delete confirmation message after a delay
            asyncio.create_task(DeleteMessage(confirm_msg))
        else:
            await message.reply("Failed to add language. Please try again.")
    except Exception as e:
        logger.error(f"Error adding language: {e}")
        await message.reply(f"Error adding language: {e}")

async def process_season_input(client: Client, message: Message, season_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    target_row = temp_admin_data[user_id].get("target_row")
    
    # Delete the prompt message
    if "ask_message_id" in temp_admin_data[user_id]:
        try:
            await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
        except Exception:
            pass
    
    # Send confirmation message
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
            await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
            
            # Delete confirmation message after a delay
            asyncio.create_task(DeleteMessage(confirm_msg))
        else:
            await message.reply("Failed to add season. Please try again.")
    except Exception as e:
        logger.error(f"Error adding season: {e}")
        await message.reply(f"Error adding season: {e}")

async def process_quality_input(client: Client, message: Message, quality_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    target_row = temp_admin_data[user_id].get("target_row")
    
    # Delete the prompt message
    if "ask_message_id" in temp_admin_data[user_id]:
        try:
            await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
        except Exception:
            pass
    
    # Send confirmation message
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
            await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
            
            # Delete confirmation message after a delay
            asyncio.create_task(DeleteMessage(confirm_msg))
        else:
            await message.reply("Failed to add quality. Please try again.")
    except Exception as e:
        logger.error(f"Error adding quality: {e}")
        await message.reply(f"Error adding quality: {e}")

async def process_codec_input(client: Client, message: Message, codec_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    quality_name = temp_admin_data[user_id].get("current_quality")
    
    # Delete the prompt message
    if "ask_message_id" in temp_admin_data[user_id]:
        try:
            await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
        except Exception:
            pass
    
    # Send confirmation message
    confirm_msg = await message.reply("Codec Added")
    
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
    current_quality = next((q for q in qualities if q["name"].lower() == quality_name.lower()), None)
    if not current_quality:
        await message.reply("Quality not found.")
        return
    
    codecs = current_quality.get("codecs", [])
    
    if codec_name.lower() in [c.lower() for c in codecs]:
        await message.reply(f"Codec '{codec_name}' already exists.")
        return
    
    codecs.append(codec_name)
    
    try:
        result = series_collection.update_one(
            {"_id": series_key},
            {"$set": {"languages": languages}}
        )
        if result.modified_count > 0:
            main_message_id = temp_admin_data[user_id].get("main_message_id")
            await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
            
            # Delete confirmation message after a delay
            asyncio.create_task(DeleteMessage(confirm_msg))
        else:
            await message.reply("Failed to add codec. Please try again.")
    except Exception as e:
        logger.error(f"Error adding codec: {e}")
        await message.reply(f"Error adding codec: {e}")

async def process_poster_input(client: Client, message: Message, poster_type: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    
    # Download and upload the poster
    poster_file_id = await download_and_upload_poster(client, message=message, send_to_log_channel=(poster_type == "series"))
    
    if not poster_file_id:
        await message.reply("Failed to process the poster. Please try again.")
        return
    
    # Update the appropriate poster
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
    
    # Return to the appropriate screen
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    if poster_type == "series":
        await send_series_details_message(client, user_id, get_series_by_key(series_key), main_message_id)
    elif poster_type == "language":
        await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
    elif poster_type == "season":
        await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)

async def process_first_file_input(client: Client, message: Message):
    user_id = message.from_user.id
    # Get the channel_id and message_id from the forwarded message
    channel_id, msg_id = await get_message_id(client, message)
    if channel_id == 0 or msg_id == 0:
        await message.reply("Invalid message. Please forward a message from a channel.")
        return

    # Store the source channel and first message info
    temp_admin_data[user_id]["source_channel_id"] = channel_id
    temp_admin_data[user_id]["source_first_msg_id"] = msg_id

    # Delete the previous prompt if exists
    if "ask_message_id" in temp_admin_data[user_id]:
        try:
            await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
        except Exception:
            pass

    # Ask for the last file
    ask_msg = await client.send_message(
        user_id,
        "Forward me the last file (with tag) for this quality:"
    )
    temp_admin_data[user_id]["state"] = "AWAITING_LAST_FILE"
    temp_admin_data[user_id]["ask_message_id"] = ask_msg.id

async def process_last_file_input(client: Client, message: Message):
    user_id = message.from_user.id
    # Get the channel_id and message_id from the forwarded message
    channel_id, msg_id = await get_message_id(client, message)
    if channel_id == 0 or msg_id == 0:
        await message.reply("Invalid message. Please forward a message from a channel.")
        return

    # Get the stored source channel and first message info
    source_channel_id = temp_admin_data[user_id].get("source_channel_id")
    source_first_msg_id = temp_admin_data[user_id].get("source_first_msg_id")

    if not source_channel_id or not source_first_msg_id:
        await message.reply("First file information not found. Please start over.")
        return

    # Check if the messages are from the same source channel
    if channel_id != source_channel_id:
        await message.reply("The first and last files must be from the same channel.")
        return

    # Get the assigned channel for this admin
    assigned_channel_id = get_admin_channel(user_id)
    if not assigned_channel_id:
        await message.reply("You don't have an assigned channel. Please contact the bot owner.")
        return

    # Forward the range of messages to the assigned channel without forward tag
    progress_msg = await message.reply("⏳ Forwarding files to assigned channel. Please wait...")
    
    try:
        new_message_ids = await forward_messages_without_tag_with_retry(
            client, source_channel_id, assigned_channel_id, source_first_msg_id, msg_id, progress_msg
        )

        if not new_message_ids:
            await progress_msg.edit_text("❌ Failed to forward files. Please try again.")
            return

        # The new first and last message IDs in the assigned channel
        new_first_msg_id = new_message_ids[0]
        new_last_msg_id = new_message_ids[-1]

        # Form the link_key string
        channel_id_str = str(assigned_channel_id)
        if channel_id_str.startswith("-100"):
            clean_channel_id = channel_id_str[4:]  # Remove -100 prefix
        else:
            clean_channel_id = channel_id_str

        # Form the link_key string without -100 prefix
        link_key = f"get_{clean_channel_id}_{new_first_msg_id}_{new_last_msg_id}"

        # Update the quality with the new link_key
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        quality_name = temp_admin_data[user_id].get("current_quality")

        if not all([series_key, language_name, season_name, quality_name]):
            await progress_msg.edit_text("❌ Session expired. Please start over.")
            return

        # Update the quality with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if add_or_update_quality(series_key, language_name, season_name, quality_name, link_key):
                    await progress_msg.edit_text(f"✅ Quality '{quality_name}' updated successfully with {len(new_message_ids)} files.")
                    # Go back to the quality management screen
                    main_message_id = temp_admin_data[user_id].get("main_message_id")
                    await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
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
        # Retry the operation
        await process_last_file_input(client, message)
    except Exception as e:
        logger.error(f"Unexpected error in process_last_file_input: {e}")
        await progress_msg.edit_text(f"❌ An unexpected error occurred: {str(e)}")


async def forward_messages_without_tag_with_retry(
    client: Client, 
    source_channel_id: int, 
    target_channel_id: int, 
    first_msg_id: int, 
    last_msg_id: int,
    progress_msg: Message = None
):
    """
    Forward messages without forward tag with comprehensive error handling
    """
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
                # Get the message from source
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
                
                # Copy the message to target channel
                try:
                    copied_msg = await msg.copy(
                        chat_id=target_channel_id,
                        caption=msg.caption if msg.caption else None,
                        parse_mode=enums.ParseMode.HTML if msg.caption else None
                    )
                    new_message_ids.append(copied_msg.id)
                    processed += 1
                    
                    # Update progress every 5 messages
                    if progress_msg and processed % 5 == 0:
                        try:
                            await progress_msg.edit_text(
                                f"⏳ Forwarding files..."
                                f"Progress: {processed}/{total_messages} ({failed} failed)"
                            )
                        except Exception:
                            pass
                    
                    # Small delay to avoid rate limits
                    await asyncio.sleep(0.5)
                    break
                    
                except FloodWait as e:
                    logger.warning(f"FloodWait encountered: {e.value} seconds")
                    if progress_msg:
                        try:
                            await progress_msg.edit_text(
                                f"⏳ Rate limit hit. Waiting {e.value} seconds..."
                                f"Progress: {processed}/{total_messages}"
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
                f"✅ Forwarding complete!"
                f"Successfully forwarded: {processed}/{total_messages}"
                f"Failed: {failed}"
            )
        except Exception:
            pass
    
    logger.info(f"Forwarding complete: {processed} successful, {failed} failed")
    return new_message_ids if new_message_ids else None

async def newui_callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    logger.info(f"Processing admin UI callback: {data}")
    
    if user_id not in temp_admin_data:
        logger.warning(f"Admin {user_id} not in temp_admin_data")
        try:
            await callback_query.answer("Session expired. Please start again with /newseriesui.", show_alert=True)
        except:
            pass
        return
    
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    
    if data.startswith("sel_"):
        unique_id = data.split("_", 1)[1]
        if unique_id not in temp_admin_data[user_id]:
            logger.warning(f"Invalid selection from admin {user_id}: {unique_id}")
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
        
        try:
            await callback_query.answer(f"Fetching details from {source.upper()}...")
        except:
            pass
        
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
            # Download and upload poster to LOG_CHANNEL with #MainPoster caption
            poster_file_id = None
            if movie_details.get('poster_url'):
                poster_file_id = await download_and_upload_poster(client, poster_url=movie_details.get('poster_url'))
                if poster_file_id:
                    logger.info(f"Got main poster file_id: {poster_file_id}")
                else:
                    logger.warning("Failed to get main poster file_id")
            else:
                logger.info("No poster URL available")
            
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
                    await callback_query.answer("Failed to add new series (might already exist). Loading existing series.", show_alert=True)
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
                    caption="Failed to retrieve series data after initial setup. Please try again."
                )
            except Exception as e:
                logger.error(f"Failed to edit message: {e}")
            return
        
        temp_admin_data[user_id]["current_series_key"] = series_key
        temp_admin_data[user_id]["state"] = "SERIES_DETAILS"
        
        await send_series_details_message(client, user_id, series_data, main_message_id)
    
    elif data == "search_again":
        try:
            await callback_query.answer("Search again...")
        except:
            pass
        query = temp_admin_data[user_id].get("query")
        search_results = temp_admin_data[user_id].get("search_results", [])
        
        if not query or not search_results:
            try:
                await callback_query.answer("No previous search data found.", show_alert=True)
            except:
                pass
            return
        
        temp_admin_data[user_id]["state"] = "SEARCH_RESULTS"
        await send_series_selection_message(client, user_id, query, search_results, main_message_id)
    
    elif data == "back_to_series":
        series_key = temp_admin_data[user_id].get("current_series_key")
        series_data = get_series_by_key(series_key)
        if not series_data:
            try:
                await callback_query.answer("Series not found.", show_alert=True)
            except:
                pass
            return
        
        try:
            await callback_query.answer("Going back to series details...")
        except:
            pass
        temp_admin_data[user_id]["state"] = "SERIES_DETAILS"
        await send_series_details_message(client, user_id, series_data, main_message_id)
    
    elif data == "manage_languages":
        series_key = temp_admin_data[user_id].get("current_series_key")
        try:
            await callback_query.answer("Managing languages...")
        except:
            pass
        temp_admin_data[user_id]["state"] = "MANAGE_LANGUAGES"
        await send_language_management_message(client, user_id, series_key, main_message_id)
    
    elif data.startswith("add_to_row_"):
        row_index = int(data.split("_")[-1])
        current_state = temp_admin_data[user_id].get("state")
        
        if current_state == "MANAGE_LANGUAGES":
            try:
                await callback_query.answer(f"Adding language to row {row_index + 1}...")
            except:
                pass
            temp_admin_data[user_id]["target_row"] = row_index
            
            # Delete previous prompt if exists
            if "ask_message_id" in temp_admin_data[user_id]:
                try:
                    await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
                except Exception:
                    pass
            
            ask_msg = await client.send_message(
                user_id,
                f"Send language name to add to row {row_index + 1}:"
            )
            temp_admin_data[user_id]["state"] = "AWAITING_LANGUAGE_INPUT"
            temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
            
        elif current_state == "MANAGE_SEASONS":
            try:
                await callback_query.answer(f"Adding season to row {row_index + 1}...")
            except:
                pass
            temp_admin_data[user_id]["target_row"] = row_index
            
            # Delete previous prompt if exists
            if "ask_message_id" in temp_admin_data[user_id]:
                try:
                    await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
                except Exception:
                    pass
            
            ask_msg = await client.send_message(
                user_id,
                f"Send season name to add to row {row_index + 1}:"
            )
            temp_admin_data[user_id]["state"] = "AWAITING_SEASON_INPUT"
            temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
            
        elif current_state == "MANAGE_QUALITIES":
            try:
                await callback_query.answer(f"Adding quality to row {row_index + 1}...")
            except:
                pass
            temp_admin_data[user_id]["target_row"] = row_index
            
            # Delete previous prompt if exists
            if "ask_message_id" in temp_admin_data[user_id]:
                try:
                    await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
                except Exception:
                    pass
            
            ask_msg = await client.send_message(
                user_id,
                f"Send quality name to add to row {row_index + 1}:"
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
                try:
                    await callback_query.answer(f"Selected: {language_name}")
                except:
                    pass
                temp_admin_data[user_id]["current_language"] = language_name
                temp_admin_data[user_id]["current_language_index"] = item_index
                temp_admin_data[user_id]["state"] = "MANAGE_SEASONS"
                await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
            else:
                try:
                    await callback_query.answer("Invalid selection.", show_alert=True)
                except:
                    pass
                
        elif current_state == "MANAGE_SEASONS":
            series_key = temp_admin_data[user_id].get("current_series_key")
            language_name = temp_admin_data[user_id].get("current_language")
            seasons = get_seasons(series_key, language_name)
            
            if 0 <= item_index < len(seasons):
                season_name = seasons[item_index]["name"]
                try:
                    await callback_query.answer(f"Selected: {season_name}")
                except:
                    pass
                temp_admin_data[user_id]["current_season"] = season_name
                temp_admin_data[user_id]["current_season_index"] = item_index
                temp_admin_data[user_id]["state"] = "MANAGE_QUALITIES"
                await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
            else:
                try:
                    await callback_query.answer("Invalid selection.", show_alert=True)
                except:
                    pass
                
        elif current_state == "MANAGE_QUALITIES":
            series_key = temp_admin_data[user_id].get("current_series_key")
            language_name = temp_admin_data[user_id].get("current_language")
            season_name = temp_admin_data[user_id].get("current_season")
            qualities = get_qualities(series_key, language_name, season_name)
            
            if 0 <= item_index < len(qualities):
                quality_name = qualities[item_index]["name"]
                link_key = qualities[item_index].get("link_key")
                
                if link_key:
                    # This quality already has files, show options
                    try:
                        await callback_query.answer(f"Options for: {quality_name}")
                    except:
                        pass
                    temp_admin_data[user_id]["current_quality"] = quality_name
                    temp_admin_data[user_id]["current_quality_index"] = item_index
                    temp_admin_data[user_id]["state"] = "QUALITY_OPTIONS"
                    
                    # Show options message
                    text = f"Quality '{quality_name}' already has files. What would you like to do?"
                    buttons = [
                        [InlineKeyboardButton("🔄 Re-Add Files", callback_data="readd_quality")],
                        [InlineKeyboardButton("🗑️ Delete Quality", callback_data="delete_quality")],
                        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_quality")]
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
                    # No existing files, proceed to add files
                    try:
                        await callback_query.answer(f"Selected: {quality_name}")
                    except:
                        pass
                    temp_admin_data[user_id]["current_quality"] = quality_name
                    temp_admin_data[user_id]["current_quality_index"] = item_index
                    temp_admin_data[user_id]["state"] = "AWAITING_FIRST_FILE"
                    
                    # Delete previous prompt if exists
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
            else:
                try:
                    await callback_query.answer("Invalid selection.", show_alert=True)
                except:
                    pass
    
    elif data == "back_to_languages":
        series_key = temp_admin_data[user_id].get("current_series_key")
        try:
            await callback_query.answer("Going back to languages...")
        except:
            pass
        temp_admin_data[user_id]["state"] = "MANAGE_LANGUAGES"
        await send_language_management_message(client, user_id, series_key, main_message_id)
    
    elif data == "back_to_seasons":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        try:
            await callback_query.answer("Going back to seasons...")
        except:
            pass
        temp_admin_data[user_id]["state"] = "MANAGE_SEASONS"
        await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
    
    elif data == "change_poster":
        try:
            await callback_query.answer("Send a new poster...")
        except:
            pass
        temp_admin_data[user_id]["state"] = "AWAITING_SERIES_POSTER"
        await client.send_message(user_id, "Please send a photo or video to use as the series poster:")
    
    elif data == "change_lang_poster":
        try:
            await callback_query.answer("Send a new poster...")
        except:
            pass
        temp_admin_data[user_id]["state"] = "AWAITING_LANGUAGE_POSTER"
        language_name = temp_admin_data[user_id].get("current_language")
        await client.send_message(user_id, f"Please send a photo or video to use as the poster for {language_name}:")
    
    elif data == "change_season_poster":
        try:
            await callback_query.answer("Send a new poster...")
        except:
            pass
        temp_admin_data[user_id]["state"] = "AWAITING_SEASON_POSTER"
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        await client.send_message(user_id, f"Please send a photo or video to use as the poster for {language_name}-{season_name}:")
    
    elif data == "delete_language":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        try:
            await callback_query.answer(f"Deleting {language_name}...")
        except:
            pass
        
        if delete_language(series_key, language_name):
            await client.send_message(user_id, f"Language '{language_name}' deleted successfully.")
            await send_language_management_message(client, user_id, series_key, main_message_id)
        else:
            await client.send_message(user_id, f"Failed to delete language '{language_name}'.")
    
    elif data == "delete_season":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        try:
            await callback_query.answer(f"Deleting {season_name}...")
        except:
            pass
        
        if delete_season(series_key, language_name, season_name):
            await client.send_message(user_id, f"Season '{season_name}' deleted successfully.")
            await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
        else:
            await client.send_message(user_id, f"Failed to delete season '{season_name}'.")
    
    elif data == "publish_series":
        series_key = temp_admin_data[user_id].get("current_series_key")
        try:
            await callback_query.answer("Publishing series...")
        except:
            pass
        
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
        try:
            await callback_query.answer("Publishing...")
        except:
            pass
        
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
    
    elif data == "cancel_publish":
        series_key = temp_admin_data[user_id].get("current_series_key")
        try:
            await callback_query.answer("Cancelling publish...")
        except:
            pass
        
        series_data = get_series_by_key(series_key)
        if series_data:
            await send_series_details_message(client, user_id, series_data, main_message_id)
        else:
            await client.send_message(user_id, "Series not found.")
    
    # Quality options handlers
    elif data == "readd_quality":
        # Re-add files for the quality
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        quality_name = temp_admin_data[user_id].get("current_quality")
        
        try:
            await callback_query.answer("Re-adding files...")
        except:
            pass
        
        # Set state to await first file
        temp_admin_data[user_id]["state"] = "AWAITING_FIRST_FILE"
        
        # Delete previous prompt if exists
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
        
    elif data == "delete_quality":
        # Delete the quality (remove the link_key)
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        quality_name = temp_admin_data[user_id].get("current_quality")
        
        try:
            await callback_query.answer("Deleting quality...")
        except:
            pass
        
        # Remove the link_key from the quality
        if add_or_update_quality(series_key, language_name, season_name, quality_name, None):
            await client.send_message(user_id, f"Quality '{quality_name}' files removed.")
            # Go back to the quality management screen
            main_message_id = temp_admin_data[user_id].get("main_message_id")
            await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
        else:
            await client.send_message(user_id, "Failed to remove quality files. Please try again.")
        
    elif data == "cancel_quality":
        # Cancel and go back to quality management
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        
        try:
            await callback_query.answer("Cancelled.")
        except:
            pass
        
        # Go back to the quality management screen
        main_message_id = temp_admin_data[user_id].get("main_message_id")
        await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)


from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
import os
from datetime import datetime
from database.crazy_db import series_collection, admin_assignments_collection
from database.users_chats_db import db
import html
import json
from info import ADMINS, TMP_DOWNLOAD_DIRECTORY
from utils import get_poster
from database.temp_db import temp_db

# Add to your existing imports
import asyncio
import math
from typing import List, Dict, Any

# ==================== STATS COMMAND WITH REFRESH ====================

@Client.on_message(filters.command('stats') & filters.user(ADMINS))
async def get_stats(bot: Client, message: Message):
    try:
        stats_msg = await message.reply("📊 Gathering statistics...")
        stats_data = await collect_stats_data()
        html_content = generate_html_report(stats_data)
        
        filename = f"stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        filepath = os.path.join(TMP_DOWNLOAD_DIRECTORY, filename)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        await stats_msg.delete()
        
        msg = await message.reply_document(
            document=filepath,
            caption="📊 <b>Comprehensive System Statistics Report</b>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_stats")]
            ])
        )
        
        # Store message ID for refresh functionality
        temp_db.set("stats_message", {
            "message_id": msg.id,
            "chat_id": msg.chat.id,
            "filepath": filepath
        })
        
    except Exception as e:
        await message.reply(f"Error generating stats: {str(e)}")

async def collect_stats_data():
    """Collect all statistics data"""
    stats_data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "series": {},
        "users": {},
        "groups": {},
        "admin_assignments": {},
        "file_database": {}
    }

    # Get series statistics
    stats_data["series"]["total"] = await series_collection.count_documents({})
    stats_data["series"]["published"] = await series_collection.count_documents({"published": True})
    stats_data["series"]["unpublished"] = await series_collection.count_documents({"published": False})

    # Get unpublished series details
    unpublished = []
    async for series in series_collection.find({"published": False}):
        unpublished.append({
            "key": series["_id"],
            "title": series.get("title", "N/A"),
            "languages": len(series.get("languages", [])),
            "created_by": series.get("created_by", "Unknown"),
            "created_at": series.get("created_at", "Unknown")
        })
    stats_data["series"]["unpublished_details"] = unpublished

    # Get users statistics
    stats_data["users"]["total"] = await db.total_users_count()
    stats_data["users"]["banned"] = len(await db.get_banned()[0])
    
    # Get groups statistics
    stats_data["groups"]["total"] = await db.total_chat_count()
    stats_data["groups"]["disabled"] = len(await db.get_banned()[1])
    
    # Get admin assignments
    assignments = {}
    async for doc in admin_assignments_collection.find({}):
        assignments[str(doc["user_id"])] = doc["channel_id"]
    stats_data["admin_assignments"] = assignments

    return stats_data

@Client.on_callback_query(filters.regex(r'^refresh_stats$') & filters.user(ADMINS))
async def refresh_stats(bot: Client, callback_query: CallbackQuery):
    try:
        await callback_query.answer("Refreshing statistics...")
        stats_data = await collect_stats_data()
        html_content = generate_html_report(stats_data)
        
        stats_msg = temp_db.get("stats_message")
        if not stats_msg:
            await callback_query.message.reply("Stats message not found in cache.")
            return
            
        filepath = stats_msg["filepath"]
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        # Delete old message
        try:
            await bot.delete_messages(
                chat_id=stats_msg["chat_id"],
                message_ids=stats_msg["message_id"]
            )
        except:
            pass
            
        # Send updated stats
        msg = await bot.send_document(
            chat_id=stats_msg["chat_id"],
            document=filepath,
            caption=f"📊 <b>Updated Statistics Report</b>
Last refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_stats")]
            ])
        )
        
        # Update stored message info
        temp_db.set("stats_message", {
            "message_id": msg.id,
            "chat_id": msg.chat.id,
            "filepath": filepath
        })
        
    except Exception as e:
        await callback_query.message.reply(f"Error refreshing stats: {str(e)}")


def generate_html_report(data):
    """Generate a complete HTML report with CSS and JavaScript"""
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>System Statistics Report</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        h1, h2, h3 {{
            color: #2c3e50;
        }}
        .report-header {{
            background-color: #3498db;
            color: white;
            padding: 20px;
            border-radius: 5px;
            margin-bottom: 20px;
            text-align: center;
        }}
        .section {{
            background-color: white;
            border-radius: 5px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        .card {{
            background-color: #f8f9fa;
            border-left: 4px solid #3498db;
            padding: 15px;
            margin-bottom: 15px;
            border-radius: 3px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background-color: #3498db;
            color: white;
        }}
        tr:nth-child(even) {{
            background-color: #f2f2f2;
        }}
        .badge {{
            display: inline-block;
            padding: 3px 7px;
            font-size: 12px;
            font-weight: bold;
            line-height: 1;
            color: white;
            text-align: center;
            white-space: nowrap;
            vertical-align: middle;
            border-radius: 10px;
        }}
        .badge-primary {{
            background-color: #3498db;
        }}
        .badge-success {{
            background-color: #2ecc71;
        }}
        .badge-danger {{
            background-color: #e74c3c;
        }}
        .badge-warning {{
            background-color: #f39c12;
        }}
        .json-viewer {{
            background-color: #f8f9fa;
            border: 1px solid #ddd;
            border-radius: 4px;
            padding: 10px;
            font-family: monospace;
            max-height: 300px;
            overflow-y: auto;
        }}
        .toggle-btn {{
            background-color: #3498db;
            color: white;
            border: none;
            padding: 5px 10px;
            border-radius: 3px;
            cursor: pointer;
            margin-bottom: 10px;
        }}
        .hidden {{
            display: none;
        }}
    </style>
</head>
<body>
    <div class="report-header">
        <h1>System Statistics Report</h1>
        <p>Generated on {data['timestamp']}</p>
    </div>

    <div class="section">
        <h2>📺 Series Statistics</h2>
        <div class="card">
            <div>Total Series: <span class="badge badge-primary">{data['series']['total']}</span></div>
            <div>Published Series: <span class="badge badge-success">{data['series']['published']}</span></div>
            <div>Unpublished Series: <span class="badge badge-warning">{data['series']['unpublished']}</span></div>
        </div>

        <h3>Unpublished Series Details</h3>
        {generate_unpublished_series_table(data['series']['unpublished_details'])}
    </div>

    <div class="section">
        <h2>👥 User Statistics</h2>
        <div class="card">
            <div>Total Users: <span class="badge badge-primary">{data['users']['total']}</span></div>
            <div>Banned Users: <span class="badge badge-danger">{data['users']['banned']}</span></div>
        </div>
    </div>

    <div class="section">
        <h2>👥 Group Statistics</h2>
        <div class="card">
            <div>Total Groups: <span class="badge badge-primary">{data['groups']['total']}</span></div>
            <div>Disabled Groups: <span class="badge badge-danger">{data['groups']['disabled']}</span></div>
        </div>
    </div>

    <div class="section">
        <h2>👑 Admin Assignments</h2>
        <div class="card">
            <div>Total Assignments: <span class="badge badge-primary">{len(data['admin_assignments'])}</span></div>
        </div>
        
        <button class="toggle-btn" onclick="toggleJsonViewer('adminAssignmentsJson')">Toggle JSON View</button>
        <div id="adminAssignmentsJson" class="json-viewer hidden">
            <pre>{json.dumps(data['admin_assignments'], indent=4)}</pre>
        </div>
    </div>

    <div class="section">
        <h2>📊 Full Data</h2>
        <button class="toggle-btn" onclick="toggleJsonViewer('fullDataJson')">Toggle Full JSON View</button>
        <div id="fullDataJson" class="json-viewer hidden">
            <pre>{json.dumps(data, indent=4)}</pre>
        </div>
    </div>

    <script>
        function toggleJsonViewer(id) {{
            const element = document.getElementById(id);
            element.classList.toggle('hidden');
        }}
    </script>
</body>
</html>
"""

def generate_unpublished_series_table(series_list):
    if not series_list:
        return "<p>No unpublished series found.</p>"
    
    rows = ""
    for series in series_list:
        rows += f"""
        <tr>
            <td>{html.escape(series['key'])}</td>
            <td>{html.escape(series['title'])}</td>
            <td>{series['languages']}</td>
            <td>{html.escape(str(series['created_by']))}</td>
            <td>{html.escape(str(series['created_at']))}</td>
        </tr>
        """
    
    return f"""
    <table>
        <thead>
            <tr>
                <th>Key</th>
                <th>Title</th>
                <th>Languages</th>
                <th>Created By</th>
                <th>Created At</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
    """

# ==================== EDIT SERIES COMMAND ====================

# Add to your existing imports
import math
from typing import Optional, Dict, Any
from info import NO_POSTER_FOUND_IMG
from pyrogram.types import InputMediaPhoto

# ==================== EDIT SERIES CORE FUNCTIONALITY ====================

@Client.on_message(filters.command('editseries') & filters.user(ADMINS))
async def edit_series_command(client: Client, message: Message):
    """Handle /editseries command - show paginated list of series for editing"""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} initiated series edit")

    all_series = []
    async for series in series_collection.find({}):
        all_series.append({
            "key": series["_id"],
            "title": series.get("title", "N/A"),
            "published": series.get("published", False),
            "poster_file_id": series.get("poster_file_id")
        })

    if not all_series:
        await message.reply("No series found in database.")
        return

    temp_admin_data[user_id] = {
        "state": "EDIT_SERIES_LIST",
        "all_series": all_series,
        "page": 1,
        "total_pages": math.ceil(len(all_series) / 6),
        "main_message_id": None
    }

    await send_series_list_page(client, user_id, message.chat.id, 1)

async def send_series_list_page(client: Client, user_id: int, chat_id: int, page: int):
    """Send a paginated list of series for editing"""
    user_data = temp_admin_data.get(user_id, {})
    if not user_data or user_data.get("state") != "EDIT_SERIES_LIST":
        await client.send_message(chat_id, "Session expired. Please use /editseries again.")
        return

    all_series = user_data.get("all_series", [])
    total_pages = user_data.get("total_pages", 1)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * 6
    page_series = all_series[start_idx : start_idx + 6]

    buttons = []
    for i in range(0, len(page_series), 2):
        row = []
        if i < len(page_series):
            series = page_series[i]
            btn_text = f"{series['title'][:15]}...{'✅' if series['published'] else '❌'}"
            row.append(InlineKeyboardButton(btn_text, callback_data=f"edit_select_{series['key']}"))
        if i + 1 < len(page_series):
            series = page_series[i + 1]
            btn_text = f"{series['title'][:15]}...{'✅' if series['published'] else '❌'}"
            row.append(InlineKeyboardButton(btn_text, callback_data=f"edit_select_{series['key']}"))
        if row:
            buttons.append(row)

    # Pagination controls
    pagination = []
    if page > 1:
        pagination.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"edit_page_{page-1}"))
    pagination.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        pagination.append(InlineKeyboardButton("Next ➡️", callback_data=f"edit_page_{page+1}"))
    
    if pagination:
        buttons.append(pagination)

    text = "📝 <b>Select Series to Edit</b>
✅ - Published
❌ - Unpublished"
    poster = NO_POSTER_FOUND_IMG[0]

    try:
        if user_data.get("main_message_id"):
            await client.edit_message_media(
                chat_id=chat_id,
                message_id=user_data["main_message_id"],
                media=InputMediaPhoto(media=poster, caption=text, parse_mode=enums.ParseMode.HTML),
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            msg = await client.send_photo(
                chat_id=chat_id,
                photo=poster,
                caption=text,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            temp_admin_data[user_id]["main_message_id"] = msg.id
    except Exception as e:
        logger.error(f"Error sending series list: {e}")
        await client.send_message(chat_id, "Error displaying series list. Please try again.")

# In your existing code, modify the show_series_edit_ui function:
async def show_series_edit_ui(client: Client, user_id: int, chat_id: int):
    """Show the edit UI with publish toggle"""
    user_data = temp_admin_data.get(user_id, {})
    if not user_data or user_data.get("state") != "EDIT_SERIES":
        await client.send_message(chat_id, "Session expired. Please start over.")
        return

    series_data = user_data["working_series"]
    is_published = series_data.get("published", False)
    poster_file_id = series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG[0]

    text = (
        f"○ <b>Editing:</b> <code>{series_data.get('title', 'N/A')}</code>"
        f"○ <b>Status:</b> {'<b style=\"color:green\">PUBLISHED</b>' if is_published else '<b style=\"color:red\">UNPUBLISHED</b>'}"
        f"○ <b>Released On:</b> <code>{series_data.get('released_on', 'N/A')}</code>"
        f"○ <b>Genre:</b> <code>{series_data.get('genre', 'N/A')}</code>"
        f"○ <b>Rating:</b> <code>{series_data.get('rating', 'N/A')}</code>"
        f"○ <b>Media Type:</b> <code>{series_data.get('media_type', 'N/A').upper()}</code>"
    )

    buttons = [
        [InlineKeyboardButton("🌐 Languages", callback_data="manage_languages")],
        [InlineKeyboardButton("🖼️ Change Poster", callback_data="change_poster")],
        [InlineKeyboardButton(
            "✅ Publish" if not is_published else "❌ Unpublish", 
            callback_data="toggle_publish"
        )],
        [InlineKeyboardButton("💾 Save Changes", callback_data="save_series_changes"),
         InlineKeyboardButton("❌ Discard", callback_data="discard_series_changes")],
        [InlineKeyboardButton("⬅️ Back to List", callback_data="back_to_series_list")]
    ]

    try:
        await client.edit_message_media(
            chat_id=chat_id,
            message_id=user_data["main_message_id"],
            media=InputMediaPhoto(media=poster_file_id, caption=text, parse_mode=enums.ParseMode.HTML),
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        logger.error(f"Error showing edit UI: {e}")
        await client.send_message(chat_id, "Error loading edit interface. Please try again.")

# Add this new handler for publish toggle
@Client.on_callback_query(filters.regex(r'^toggle_publish$') & filters.user(ADMINS))
async def toggle_publish_status(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    user_data = temp_admin_data.get(user_id, {})
    if not user_data or user_data.get("state") != "EDIT_SERIES":
        await callback_query.answer("Session expired.", show_alert=True)
        return

    # Toggle the published status in working copy
    current_status = user_data["working_series"].get("published", False)
    user_data["working_series"]["published"] = not current_status
    
    # Show confirmation and refresh UI
    await callback_query.answer(f"Status changed to {'PUBLISHED' if not current_status else 'UNPUBLISHED'}!", show_alert=True)
    await show_series_edit_ui(client, user_id, callback_query.message.chat.id)

# Modify the save handler to handle publish status changes
@Client.on_callback_query(filters.regex(r'^save_series_changes$') & filters.user(ADMINS))
async def save_series_changes(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    user_data = temp_admin_data.get(user_id, {})
    if not user_data or user_data.get("state") != "EDIT_SERIES":
        await callback_query.answer("Session expired.", show_alert=True)
        return

    series_key = user_data.get("series_key")
    working_series = user_data.get("working_series")
    original_series = user_data.get("original_series")
    
    try:
        # Handle publish/unpublish consequences
        if working_series.get("published") and not original_series.get("published"):
            # Newly published - validate all required fields
            if not validate_series_for_publishing(working_series):
                await callback_query.answer("Cannot publish - missing required fields!", show_alert=True)
                return
        
        result = await series_collection.replace_one(
            {"_id": series_key},
            working_series
        )
        
        if result.modified_count > 0:
            await callback_query.answer("✅ Changes saved successfully!", show_alert=True)
            # Update original data
            updated_series = await series_collection.find_one({"_id": series_key})
            temp_admin_data[user_id]["original_series"] = updated_series
            temp_admin_data[user_id]["working_series"] = updated_series.copy()
            
            await show_series_edit_ui(client, user_id, callback_query.message.chat.id)
        else:
            await callback_query.answer("No changes were made.", show_alert=True)
            
    except Exception as e:
        logger.error(f"Error saving series changes: {e}")
        await callback_query.answer("❌ Failed to save changes!", show_alert=True)

def validate_series_for_publishing(series_data: dict) -> bool:
    """Validate that a series has all required fields for publishing"""
    required = [
        'title',
        'poster_file_id',
        'languages'
    ]
    
    for field in required:
        if not series_data.get(field):
            return False
            
    # Check at least one language has seasons with qualities
    for lang in series_data.get("languages", []):
        for season in lang.get("seasons", []):
            if any(q.get("link_key") for q in season.get("qualities", [])):
                return True
    return False
# ==================== CALLBACK HANDLERS ====================

@Client.on_callback_query(filters.regex(r'^edit_page_(\d+)$') & filters.user(ADMINS))
async def edit_series_page_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    page = int(callback_query.data.split("_")[-1])
    await callback_query.answer()
    await send_series_list_page(client, user_id, callback_query.message.chat.id, page)

@Client.on_callback_query(filters.regex(r'^edit_select_') & filters.user(ADMINS))
async def edit_select_series(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    series_key = callback_query.data.split("_")[-1]
    await callback_query.answer("Loading series...")

    series_data = await series_collection.find_one({"_id": series_key})
    if not series_data:
        await callback_query.message.reply("Series not found!")
        return

    temp_admin_data[user_id] = {
        "state": "EDIT_SERIES",
        "original_series": series_data,
        "working_series": series_data.copy(),
        "main_message_id": callback_query.message.id,
        "series_key": series_key
    }

    await show_series_edit_ui(client, user_id, callback_query.message.chat.id)

@Client.on_callback_query(filters.regex(r'^save_series_changes$') & filters.user(ADMINS))
async def save_series_changes(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    user_data = temp_admin_data.get(user_id, {})
    if not user_data or user_data.get("state") != "EDIT_SERIES":
        await callback_query.answer("Session expired.", show_alert=True)
        return

    series_key = user_data.get("series_key")
    working_series = user_data.get("working_series")
    
    try:
        result = await series_collection.replace_one({"_id": series_key}, working_series)
        
        if result.modified_count > 0:
            await callback_query.answer("✅ Changes saved successfully!", show_alert=True)
            
            # Update the working copy with the saved data
            updated_series = await series_collection.find_one({"_id": series_key})
            temp_admin_data[user_id]["original_series"] = updated_series
            temp_admin_data[user_id]["working_series"] = updated_series.copy()
            
            await show_series_edit_ui(client, user_id, callback_query.message.chat.id)
        else:
            await callback_query.answer("No changes were made.", show_alert=True)
            
    except Exception as e:
        logger.error(f"Error saving series changes: {e}")
        await callback_query.answer("❌ Failed to save changes!", show_alert=True)

@Client.on_callback_query(filters.regex(r'^discard_series_changes$') & filters.user(ADMINS))
async def discard_series_changes(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    user_data = temp_admin_data.get(user_id, {})
    if not user_data or user_data.get("state") != "EDIT_SERIES":
        await callback_query.answer("Session expired.", show_alert=True)
        return

    original_series = user_data.get("original_series")
    temp_admin_data[user_id]["working_series"] = original_series.copy()
    await callback_query.answer("Changes discarded.", show_alert=True)
    await show_series_edit_ui(client, user_id, callback_query.message.chat.id)

@Client.on_callback_query(filters.regex(r'^back_to_series_list$') & filters.user(ADMINS))
async def back_to_series_list(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    user_data = temp_admin_data.get(user_id, {})
    if user_data and user_data.get("state") == "EDIT_SERIES":
        # Switch back to list view
        temp_admin_data[user_id] = {
            "state": "EDIT_SERIES_LIST",
            "all_series": temp_admin_data[user_id].get("all_series", []),
            "page": temp_admin_data[user_id].get("page", 1),
            "total_pages": temp_admin_data[user_id].get("total_pages", 1),
            "main_message_id": callback_query.message.id
        }
        await callback_query.answer()
        await send_series_list_page(client, user_id, callback_query.message.chat.id, 
                                  temp_admin_data[user_id]["page"])
    else:
        await callback_query.answer("Invalid state.", show_alert=True)

# ==================== MODIFIED EXISTING HANDLERS ====================

async def send_language_management_message(client: Client, user_id: int, series_key: str, message_id: int):
    """Modified to work with both editing and creation modes"""
    user_data = temp_admin_data.get(user_id, {})
    
    # Determine source of series data
    if user_data.get("state") == "EDIT_SERIES":
        series_data = user_data["working_series"]
    else:
        series_data = await series_collection.find_one({"_id": series_key})
    
    if not series_data:
        await client.send_message(user_id, "Series not found.")
        return

    languages = series_data.get("languages", [])
    language_layout = series_data.get("language_layout", [])
    
    text = f"<b>Series:</b> <code>{series_data.get('title', 'N/A')}</code>"
    text += "Select any Language group to add new Season/Part group inside them. Or click '+' button to add new Language group."

    language_names = [lang['name'] for lang in languages]
    
    # Determine correct back button based on mode
    back_callback = "back_to_series_edit" if user_data.get("state") == "EDIT_SERIES" else "back_to_series"
    add_buttons = [("⬅️ Back", back_callback)]
    
    layout = create_dynamic_layout_from_pattern(language_names, language_layout, add_buttons)
    reply_markup = InlineKeyboardMarkup(layout)
    
    poster_to_use = series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG[0]

    try:
        await client.edit_message_media(
            chat_id=user_id,
            message_id=message_id,
            media=InputMediaPhoto(media=poster_to_use, caption=text, parse_mode=enums.ParseMode.HTML),
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error in language management UI: {e}")
        raise

# ==================== SEASON MANAGEMENT HANDLERS ====================

async def send_season_management_message(client: Client, user_id: int, series_key: str, language_name: str, message_id: int):
    """Show season management UI - works for both edit and create modes"""
    user_data = temp_admin_data.get(user_id, {})
    
    # Get series data from appropriate source
    if user_data.get("state") == "EDIT_SERIES":
        series_data = user_data["working_series"]
    else:
        series_data = await series_collection.find_one({"_id": series_key})
    
    if not series_data:
        await client.send_message(user_id, "Series not found.")
        return

    # Find the specific language
    current_lang = next((lang for lang in series_data.get("languages", []) 
                        if lang["name"].lower() == language_name.lower()), None)
    if not current_lang:
        await client.send_message(user_id, "Language not found.")
        return

    seasons = current_lang.get("seasons", [])
    season_layout = current_lang.get("season_layout", [])
    
    text = (
        f"<b>Series:</b> <code>{series_data.get('title', 'N/A')}</code>"
        f"<b>Language:</b> <code>{language_name}</code>"
        "Select any Season group to add new Quality group inside them. "
        "Or click '+' button to add new Season group."
    )

    season_names = [season['name'] for season in seasons]
    
    # Determine correct back button based on mode
    back_callback = "back_to_languages_edit" if user_data.get("state") == "EDIT_SERIES" else "back_to_languages"
    
    add_buttons = [
        ("🖼️ Change Poster", f"change_lang_poster_{language_name}"),
        ("⬅️ Back", back_callback)
    ]
    
    layout = create_dynamic_layout_from_pattern(season_names, season_layout, add_buttons)
    reply_markup = InlineKeyboardMarkup(layout)
    
    # Use language-specific poster if available, else series poster
    poster_to_use = current_lang.get("poster_file_id") or series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG[0]

    try:
        await client.edit_message_media(
            chat_id=user_id,
            message_id=message_id,
            media=InputMediaPhoto(media=poster_to_use, caption=text, parse_mode=enums.ParseMode.HTML),
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error in season management UI: {e}")
        await client.send_message(user_id, "Error loading season management. Please try again.")

@Client.on_callback_query(filters.regex(r'^back_to_languages_edit$') & filters.user(ADMINS))
async def back_to_languages_from_seasons_edit(client: Client, callback_query: CallbackQuery):
    """Handle back navigation from seasons to languages in edit mode"""
    user_id = callback_query.from_user.id
    user_data = temp_admin_data.get(user_id, {})
    
    if user_data.get("state") == "EDIT_SERIES":
        # Return to series edit UI which will show languages
        await show_series_edit_ui(client, user_id, callback_query.message.chat.id)
    else:
        await callback_query.answer("Invalid state", show_alert=True)

# ==================== QUALITY MANAGEMENT HANDLERS ====================

async def send_quality_management_message(
    client: Client, 
    user_id: int, 
    series_key: str, 
    language_name: str, 
    season_name: str, 
    message_id: int
):
    """Show quality management UI - works for both edit and create modes"""
    user_data = temp_admin_data.get(user_id, {})
    
    # Get series data from appropriate source
    if user_data.get("state") == "EDIT_SERIES":
        series_data = user_data["working_series"]
    else:
        series_data = await series_collection.find_one({"_id": series_key})
    
    if not series_data:
        await client.send_message(user_id, "Series not found.")
        return

    # Find the specific language and season
    current_lang = next((lang for lang in series_data.get("languages", []) 
                        if lang["name"].lower() == language_name.lower()), None)
    if not current_lang:
        await client.send_message(user_id, "Language not found.")
        return

    current_season = next((s for s in current_lang.get("seasons", []) 
                          if s["name"].lower() == season_name.lower()), None)
    if not current_season:
        await client.send_message(user_id, "Season not found.")
        return

    qualities = current_season.get("qualities", [])
    quality_layout = current_season.get("quality_layout", [])
    
    text = (
        f"<b>Series:</b> <code>{series_data.get('title', 'N/A')}</code>"
        f"<b>Language:</b> <code>{language_name}</code>"
        f"<b>Season:</b> <code>{season_name}</code>"
        "Select any Quality group to manage files. "
        "Or click '+' button to add new Quality group."
    )

    quality_names = [quality['name'] for quality in qualities]
    
    # Determine correct back button based on mode
    back_callback = "back_to_seasons_edit" if user_data.get("state") == "EDIT_SERIES" else "back_to_seasons"
    
    add_buttons = [
        ("🖼️ Change Poster", f"change_season_poster_{language_name}_{season_name}"),
        ("⬅️ Back", back_callback)
    ]
    
    layout = create_dynamic_layout_from_pattern(quality_names, quality_layout, add_buttons)
    reply_markup = InlineKeyboardMarkup(layout)
    
    # Use season-specific poster if available, then language, then series
    poster_to_use = (
        current_season.get("poster_file_id") or 
        current_lang.get("poster_file_id") or 
        series_data.get("poster_file_id") or 
        NO_POSTER_FOUND_IMG[0]
    )

    try:
        await client.edit_message_media(
            chat_id=user_id,
            message_id=message_id,
            media=InputMediaPhoto(media=poster_to_use, caption=text, parse_mode=enums.ParseMode.HTML),
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error in quality management UI: {e}")
        await client.send_message(user_id, "Error loading quality management. Please try again.")

@Client.on_callback_query(filters.regex(r'^back_to_seasons_edit$') & filters.user(ADMINS))
async def back_to_seasons_from_quality_edit(client: Client, callback_query: CallbackQuery):
    """Handle back navigation from qualities to seasons in edit mode"""
    user_id = callback_query.from_user.id
    user_data = temp_admin_data.get(user_id, {})
    
    if user_data.get("state") == "EDIT_SERIES":
        # Need to get language name from callback or temp data
        # This would depend on how you store the context
        language_name = user_data.get("current_language")
        if language_name:
            await send_season_management_message(
                client,
                user_id,
                user_data["series_key"],
                language_name,
                callback_query.message.id
            )
        else:
            await callback_query.answer("Language context missing", show_alert=True)
    else:
        await callback_query.answer("Invalid state", show_alert=True)

# ==================== INTEGRATED CALLBACK DISPATCHER ====================

@Client.on_callback_query(filters.user(ADMINS))
async def integrated_callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    try:
        await callback_query.answer()
        
        # Edit series specific handlers
        if data.startswith("edit_"):
            if data.startswith("edit_page_"):
                await edit_series_page_callback(client, callback_query)
            elif data.startswith("edit_select_"):
                await edit_select_series(client, callback_query)
                
        # Season management handlers
        elif data.startswith("season_"):
            season_name = data.split("_")[1]
            user_data = temp_admin_data.get(user_id, {})
            await send_quality_management_message(
                client,
                user_id,
                user_data["series_key"],
                user_data["current_language"],
                season_name,
                callback_query.message.id
            )
                
        # Quality management handlers
        elif data.startswith("quality_"):
            quality_name = data.split("_")[1]
            user_data = temp_admin_data.get(user_id, {})
            # Handle quality selection - would show files interface
            await handle_quality_selection(client, callback_query, quality_name)
                
        # Navigation handlers
        elif data == "back_to_series_list":
            await back_to_series_list(client, callback_query)
        elif data == "back_to_series_edit":
            await show_series_edit_ui(client, user_id, callback_query.message.chat.id)
        elif data == "back_to_languages_edit":
            await back_to_languages_from_seasons_edit(client, callback_query)
        elif data == "back_to_seasons_edit":
            await back_to_seasons_from_quality_edit(client, callback_query)
                
        # Action handlers
        elif data == "save_series_changes":
            await save_series_changes(client, callback_query)
        elif data == "discard_series_changes":
            await discard_series_changes(client, callback_query)
        elif data == "toggle_publish":
            await toggle_publish_status(client, callback_query)
            
        else:
            # Pass through to original handler
            await admin_ui_callback_handler(client, callback_query)
            
    except Exception as e:
        logger.error(f"Error in integrated callback handler: {e}")
        await callback_query.message.reply("An error occurred. Please try again.")
