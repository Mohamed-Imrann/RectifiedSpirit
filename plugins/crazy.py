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
from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, TMDB_API_KEY, LOG_CHANNEL, DB_CHANNEL, RAW_DB_CHANNEL, NO_POSTER_FOUND_IMG, Assigned, TVDB_API_KEY, OMDB_API_KEY
from database.crazy_db import (
    add_series, get_series_by_key, update_series_field, add_or_update_language,
    get_languages, delete_language, add_or_update_season, get_seasons, delete_season,
    add_or_update_quality, get_qualities, get_quality_link, delete_quality,
    get_poster_file_id, update_poster_file_id, publish_series, episodes_collection,
    add_admin_assignment, remove_admin_assignment, write_admin_assignments_to_env,
    track_series_edit
)
from utils import (
    get_message_id, get_messages, delete_messages_from_user_chat, 
    get_poster, find_most_similar_title, get_comprehensive_series_info,
    send_poster_to_admin_channel, format_release_date
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

# Helper functions
async def DeleteMessage(msg):
    await asyncio.sleep(600)
    try:
        await msg.delete()
        logger.debug(f"Deleted message {msg.id} from chat {msg.chat.id}")
    except Exception as e:
        logger.warning(f"Failed to delete message {msg.id}: {e}")

def create_dynamic_layout_from_pattern(items: List[str], layout_pattern: List[int], add_buttons: List[str] = None) -> List[List[InlineKeyboardButton]]:
    """
    Create a dynamic button layout with unique + callbacks for each position.
    """
    layout = []
    item_index = 0
    
    # Create rows based on pattern
    for row_index, row_count in enumerate(layout_pattern):
        if item_index >= len(items):
            break
        
        row = []
        # Add items for this row
        items_in_this_row = 0
        for _ in range(row_count):
            if item_index < len(items):
                item_button = InlineKeyboardButton(items[item_index], callback_data=f"item_{item_index}")
                row.append(item_button)
                item_index += 1
                items_in_this_row += 1
        
        # Add + button for this row with unique callback
        if items_in_this_row > 0:
            plus_button = InlineKeyboardButton("+", callback_data=f"add_to_row_{row_index}")
            row.append(plus_button)
            layout.append(row)
    
    # Add remaining items if any (shouldn't happen with proper pattern management)
    while item_index < len(items):
        row = []
        item_button = InlineKeyboardButton(items[item_index], callback_data=f"item_{item_index}")
        row.append(item_button)
        # Add + for this new row
        plus_button = InlineKeyboardButton("+", callback_data=f"add_to_row_{len(layout)}")
        row.append(plus_button)
        layout.append(row)
        item_index += 1
    
    # Add a final + button for creating new row if we have items
    if items:
        next_row_index = len(layout)
        layout.append([InlineKeyboardButton("+ New Row", callback_data=f"add_to_row_{next_row_index}")])
    else:
        # If no items, add first + button
        layout.append([InlineKeyboardButton("+ Add First Item", callback_data="add_to_row_0")])
    
    # Add control buttons
    if add_buttons:
        for button_text, callback_data in add_buttons:
            layout.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
    
    return layout

def create_user_layout_from_pattern(items: List[str], layout_pattern: List[int]) -> List[List[InlineKeyboardButton]]:
    """
    Create a user-facing layout without + buttons.
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
            poster_url = f"{TMDB_IMAGE_BASE_URL}{poster_path}" if poster_path else None

            if media_type == 'tv':
                title = data.get('name', 'N/A')
                year = f"{data.get('first_air_date', '').split('-')[0]} - {data.get('last_air_date', '').split('-')[0]}" if data.get('first_air_date') and data.get('last_air_date') else data.get('first_air_date', '').split('-')[0] if data.get('first_air_date') else 'N/A'
            else: # movie
                title = data.get('title', 'N/A')
                year = data.get('release_date', '').split('-')[0] if data.get('release_date') else 'N/A'
            
            result = {
                'title': title,
                'year': year,
                'genres': ', '.join(genres) if genres else None,
                'rating': data.get('vote_average'),
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

async def get_tvdb_info(query, tvdb_id=None):
    """Fetch TV show information from TVDB API"""
    headers = {
        "Authorization": f"Bearer {TVDB_API_KEY}",
        "Accept": "application/json"
    }
    
    try:
        if tvdb_id:
            # Get specific series by ID
            url = f"https://api.thetvdb.com/series/{tvdb_id}"
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json().get('data', {})
            
            # Extract the needed information
            return {
                'title': data.get('seriesName'),
                'released_on': data.get('firstAired', '').split('-')[0] if data.get('firstAired') else 'N/A',
                'rating': data.get('siteRating'),
                'genre': ', '.join([genre for genre in data.get('genre', []) if genre]) if data.get('genre') else 'N/A',
                'poster_url': f"https://thetvdb.com/banners/{data.get('poster')}" if data.get('poster') else None,
                'tvdb_id': data.get('id'),
                'media_type': 'tv'
            }
        else:
            # Search for the series
            url = f"https://api.thetvdb.com/search/series?name={query}"
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json().get('data', [])
            
            if data:
                # Get the first result
                series = data[0]
                return {
                    'title': series.get('seriesName'),
                    'released_on': series.get('firstAired', '').split('-')[0] if series.get('firstAired') else 'N/A',
                    'rating': series.get('siteRating'),
                    'genre': ', '.join([genre for genre in series.get('genre', []) if genre]) if series.get('genre') else 'N/A',
                    'poster_url': f"https://thetvdb.com/banners/{series.get('poster')}" if series.get('poster') else None,
                    'tvdb_id': series.get('id'),
                    'media_type': 'tv'
                }
    except Exception as e:
        logger.error(f"TVDB API error: {e}")
    
    return None

async def get_omdb_info(query, omdb_id=None):
    """Fetch movie/series information from OMDB API"""
    try:
        if omdb_id:
            url = f"http://www.omdbapi.com/?i={omdb_id}&apikey={OMDB_API_KEY}"
        else:
            url = f"http://www.omdbapi.com/?t={query}&apikey={OMDB_API_KEY}"
        
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        if data.get('Response') == 'True':
            # Extract the needed information
            return {
                'title': data.get('Title'),
                'released_on': data.get('Year', '').split('–')[0] if data.get('Year') else 'N/A',
                'rating': data.get('imdbRating'),
                'genre': data.get('Genre'),
                'poster_url': data.get('Poster') if data.get('Poster') != 'N/A' else None,
                'imdb_id': data.get('imdbID'),
                'media_type': 'series' if data.get('Type') == 'series' else 'movie'
            }
    except Exception as e:
        logger.error(f"OMDB API error: {e}")
    
    return None

# Poster management functions
async def fetch_api_posters(client, user_id, series_data, api_type, level="series", language_name=None, season_name=None):
    """Fetch posters from different APIs"""
    posters = []
    query = series_data.get('title', '')
    
    if api_type == "tmdb":
        if level == "series":
            tmdb_info = await get_tmdb_info(query, tmdb_id=series_data.get('tmdb_id'), media_type=series_data.get('media_type', 'tv'))
            if tmdb_info and tmdb_info.get('poster_url'):
                posters.append(tmdb_info['poster_url'])
        # Add season-specific poster fetching logic here if needed
    
    elif api_type == "imdb":
        if level == "series":
            imdb_info = await get_poster(series_data.get('imdb_id'), id=True) if series_data.get('imdb_id') else await get_poster(query, bulk=False)
            if imdb_info and imdb_info.get('poster'):
                posters.append(imdb_info['poster'])
        # Add season-specific poster fetching logic here if needed
    
    elif api_type == "tvdb":
        if level == "series":
            tvdb_info = await get_tvdb_info(query, tvdb_id=series_data.get('tvdb_id'))
            if tvdb_info and tvdb_info.get('poster_url'):
                posters.append(tvdb_info['poster_url'])
        # Add season-specific poster fetching logic here if needed
    
    elif api_type == "omdb":
        if level == "series":
            omdb_info = await get_omdb_info(query, omdb_id=series_data.get('omdb_id'))
            if omdb_info and omdb_info.get('poster_url'):
                posters.append(omdb_info['poster_url'])
        # Add season-specific poster fetching logic here if needed
    
    return posters

async def send_api_poster_selection(client, user_id, posters, current_index, series_data, level="series", language_name=None, season_name=None):
    """Send poster selection UI with navigation"""
    if not posters:
        await client.send_message(user_id, "No posters found from this API.")
        return
    
    poster_url = posters[current_index]
    text = f"Poster {current_index+1}/{len(posters)} from {posters[current_index].split('/')[2].split('.')[0].upper()}"
    
    buttons = []
    nav_buttons = []
    
    # Navigation buttons
    if current_index > 0:
        nav_buttons.append(InlineKeyboardButton("◀️", callback_data="poster_nav_prev"))
    
    nav_buttons.append(InlineKeyboardButton("✅", callback_data="poster_confirm"))
    
    if current_index < len(posters) - 1:
        nav_buttons.append(InlineKeyboardButton("▶️", callback_data="poster_nav_next"))
    
    buttons.append(nav_buttons)
    
    # Back button
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="poster_back")])
    
    reply_markup = InlineKeyboardMarkup(buttons)
    
    try:
        await client.send_photo(
            chat_id=user_id,
            photo=poster_url,
            caption=text,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error sending poster selection: {e}")

# Admin UI message sending functions
async def send_tmdb_selection_message(client: Client, user_id: int, query: str, results: list, message_id: int = None):
    logger.info(f"Sending TMDB selection message to user {user_id}")
    text = f"**Select a series from TMDB:**\n\nSearch query: `{query}`"
    
    buttons = []
    for i, item in enumerate(results):
        unique_id = str(uuid.uuid4())
        temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
        temp_admin_data[user_id][unique_id] = {
            'id': item.get('tmdb_id'),
            'media_type': item.get('media_type'),
            'source': 'tmdb',
            'query': query
        }
        button_text = f"{item.get('title', 'N/A')} ({item.get('year', 'N/A')})"
        buttons.append(InlineKeyboardButton(button_text, callback_data=f"sel_{unique_id}"))
    
    buttons.append(InlineKeyboardButton("🔍 Search IMDb Instead", callback_data="search_imdb"))
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
            logger.debug(f"Edited TMDB selection message {message_id}")
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=NO_POSTER_FOUND_IMG[0],
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            logger.debug(f"Sent new TMDB selection message {msg.id}")
            return msg.id
    except Exception as e:
        logger.error(f"Error sending TMDB selection message: {e}")
        return None

async def send_imdb_selection_message(client: Client, user_id: int, query: str, results: list, message_id: int = None):
    logger.info(f"Sending IMDb selection message to user {user_id}")
    text = f"**Select a series from IMDb:**\n\nSearch query: `{query}`"
    
    buttons = []
    for i, item in enumerate(results):
        unique_id = str(uuid.uuid4())
        temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
        temp_admin_data[user_id][unique_id] = {
            'id': item.get('imdb_id'),
            'media_type': item.get('media_type'),
            'source': 'imdb',
            'query': query
        }
        button_text = f"{item.get('title', 'N/A')} ({item.get('year', 'N/A')})"
        buttons.append(InlineKeyboardButton(button_text, callback_data=f"sel_{unique_id}"))
    
    buttons.append(InlineKeyboardButton("🔍 Search TMDB Instead", callback_data="search_tmdb"))
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
            logger.debug(f"Edited IMDb selection message {message_id}")
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=NO_POSTER_FOUND_IMG[0],
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            logger.debug(f"Sent new IMDb selection message {msg.id}")
            return msg.id
    except Exception as e:
        logger.error(f"Error sending IMDb selection message: {e}")
        return None

async def send_series_details_message(client: Client, user_id: int, series_data: dict, message_id: int = None):
    logger.info(f"Sending series details message to user {user_id}")
    series_key = series_data['_id']
    poster_file_id = get_poster_file_id(series_key) or NO_POSTER_FOUND_IMG[0]

    # Format the rating with vote count if available
    rating = series_data.get('rating', 'N/A')
    if rating != 'N/A' and isinstance(rating, (int, float)):
        # Format as "6.5 (8,863)" if we have vote count, otherwise just "6.5"
        rating_text = f"{rating}"
    else:
        rating_text = 'N/A'

    text = (
        f"○ **Title:** `{series_data.get('title', 'N/A')}`\\n"
        f"○ **Released On:** `{format_release_date(series_data.get('released_on', 'N/A'))}`\\n"
        f"○ **Genre:** `{series_data.get('genre', 'N/A')}`\\n"
        f"○ **Rating:** `{rating_text}`\\n"
        f"○ **Media Type:** `{series_data.get('media_type', 'N/A').upper()}`\\n\\n"
    )

    # Check if we need to add buttons for getting genre/rating from other sources
    buttons = [
        InlineKeyboardButton("🌐 Languages", callback_data="manage_languages"),
        InlineKeyboardButton("🖼️ Poster", callback_data="change_poster"),
        InlineKeyboardButton("📤 Publish", callback_data="publish_series")
    ]
    
    # Add button to get genre/rating from IMDb if data is from TMDB and missing genre or rating
    if series_data.get('source') == 'tmdb' and (not series_data.get('genre') or not series_data.get('rating')):
        buttons.insert(2, InlineKeyboardButton("📊 Get Genre & Rating from IMDb", callback_data="get_genre_rating_imdb"))
    
    # Add button to get genre/rating from TMDB if data is from IMDb and missing genre or rating
    if series_data.get('source') == 'imdb' and (not series_data.get('genre') or not series_data.get('rating')):
        buttons.insert(2, InlineKeyboardButton("📊 Get Genre & Rating from TMDB", callback_data="get_genre_rating_tmdb"))
    
    layout = [[buttons[0]], [buttons[1], buttons[2]]]
    if len(buttons) > 3:
        layout = [[buttons[0]], [buttons[1]], [buttons[2], buttons[3]]]
    
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
    
    text = f"**Series:** `{series_data.get('title', 'N/A')}`\\n\\n"
    text += "Select any Language group to add new Season/Part group inside them. Or click '+' button to add new Language group.\\n\\n"

    # Get language names
    language_names = [lang['name'] for lang in languages]
    
    # Create dynamic layout with + buttons
    add_buttons = [
        ("⬅️ Back", "back_to_series")
    ]
    
    layout = create_dynamic_layout_from_pattern(language_names, language_layout, add_buttons)
    
    # Add change poster button for the language
    if languages:
        layout.append([InlineKeyboardButton("🖼️ Change Language Poster", callback_data="change_language_poster")])
    
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
        f"**Series:** `{series_data.get('title', 'N/A')}`\\n"
        f"**Language:** `{language_name}`\\n\\n"
        "Select any Seasons group to add new Quality group into them. Or click '+' button to add new Seasons group.\\n\\n"
    )

    # Get season names
    season_names = [season['name'] for season in seasons]
    
    # Create dynamic layout with + buttons
    add_buttons = [
        ("🖼️ Change Season Poster", "change_season_poster"),
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
        f"**Series:** `{series_data.get('title', 'N/A')}`\\n"
        f"**Language:** `{language_name}`\\n"
        f"**Season:** `{season_name}`\\n\\n"
        "Select any Quality group to add new files into them. Or click '+' button to add new Quality group.\\n\\n"
    )

    # Get quality names
    quality_names = [quality['name'] for quality in qualities]
    
    # Create dynamic layout with + buttons
    add_buttons = [
        ("🖼️ Change Quality Poster", "change_quality_poster"),
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

# Command handlers
@Client.on_message(filters.command('assignadmin') & filters.user(ADMINS))
async def assign_admin_command(client: Client, message: Message):
    """Assign an admin to a channel"""
    if len(message.command) != 3:
        await message.reply("Usage: `/assignadmin <user_id> <channel_id>`")
        return
    
    try:
        user_id = int(message.command[1])
        channel_id = int(message.command[2])
    except ValueError:
        await message.reply("Invalid user_id or channel_id. They must be integers.")
        return
    
    if add_admin_assignment(user_id, channel_id):
        # Write assignments to env file
        write_admin_assignments_to_env()
        await message.reply(f"Admin assignment added: {user_id} -> {channel_id}\nChanges will apply after restart.")
    else:
        await message.reply("Failed to add admin assignment.")

@Client.on_message(filters.command('removeadmin') & filters.user(ADMINS))
async def remove_admin_command(client: Client, message: Message):
    """Remove an admin assignment"""
    if len(message.command) != 2:
        await message.reply("Usage: `/removeadmin <user_id>`")
        return
    
    try:
        user_id = int(message.command[1])
    except ValueError:
        await message.reply("Invalid user_id. It must be an integer.")
        return
    
    if remove_admin_assignment(user_id):
        # Write assignments to env file
        write_admin_assignments_to_env()
        await message.reply(f"Admin assignment removed for user: {user_id}\nChanges will apply after restart.")
    else:
        await message.reply("Failed to remove admin assignment or user not found.")

@Client.on_message(filters.command('newseriesui') & filters.private)
async def new_series_ui_command(client: Client, message: Message):
    """Create a new series (only for assigned admins)"""
    user_id = message.from_user.id
    if user_id not in Assigned:
        await message.reply("You are not authorized to use this command.")
        return
    
    logger.info(f"Admin {user_id} started new series UI")
    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None

    if not query:
        await message.reply("Usage: `/newseriesui <series_title>`")
        return

    temp_msg = await message.reply_photo(
        photo="https://envs.sh/EMw.jpg",
        caption="Searching TMDB, please wait..."
    )
    
    # First, search TMDB
    tmdb_results = await get_tmdb_info(query, bulk=True)
    
    if not tmdb_results:
        await temp_msg.edit_caption("No results found on TMDB for the provided series name.")
        return
    
    # Store the results in temp data
    temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
    temp_admin_data[user_id]["search_results"] = tmdb_results
    temp_admin_data[user_id]["query"] = query
    temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SEARCH_RESULTS"
    temp_admin_data[user_id]["main_message_id"] = temp_msg.id

    # Send the TMDB results as buttons
    await send_tmdb_selection_message(client, user_id, query, tmdb_results, temp_msg.id)

@Client.on_message(filters.command('editseries') & filters.private)
async def edit_series_command(client: Client, message: Message):
    """Edit an existing series (only for assigned admins)"""
    user_id = message.from_user.id
    if user_id not in Assigned:
        await message.reply("You are not authorized to use this command.")
        return
    
    logger.info(f"Admin {user_id} started editing series")
    
    # Get series key from command
    if len(message.command) < 2:
        await message.reply("Usage: `/editseries <series_key>`")
        return
    
    series_key = message.command[1]
    series_data = get_series_by_key(series_key)
    
    if not series_data:
        await message.reply("Series not found.")
        return
    
    # Check if series is published
    if not series_data.get('published', False):
        await message.reply("This series is not published yet. Use /newseries to add it.")
        return
    
    # Track this edit
    track_series_edit(series_key, user_id)
    
    # Store in temp data
    temp_msg = await message.reply_photo(
        photo=series_data.get('poster_file_id', NO_POSTER_FOUND_IMG[0]),
        caption="Loading series details..."
    )
    
    temp_admin_data[user_id] = {
        "current_series_key": series_key,
        "state": "SERIES_DETAILS",
        "main_message_id": temp_msg.id,
        "is_editing": True  # Flag to indicate we're editing
    }
    
    # Send series details message
    await send_series_details_message(client, user_id, series_data, temp_msg.id)

# Message handlers for admin UI
@Client.on_message(filters.text & filters.private)
async def handle_admin_text_message(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Received admin text message {message.id} from user {user_id}")
    
    if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
        await handle_admin_text_input(client, message)

@Client.on_message((filters.photo | filters.video | filters.document) & filters.private)
async def handle_admin_media_message(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Received admin media message {message.id} from user {user_id}")
    
    if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
        await handle_admin_media_input(client, message)

# Callback handlers for admin UI
@Client.on_callback_query()
async def admin_ui_callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    logger.info(f"Received admin UI callback from user {user_id}: {data}")

    if user_id not in temp_admin_data:
        logger.warning(f"Admin {user_id} not in temp_admin_data")
        await callback_query.answer("Session expired. Please start again with /newseriesui.", show_alert=True)
        return
    
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    
    # Handle IMDb search button
    if data == "search_imdb":
        await callback_query.answer("Searching IMDb...")
        query = temp_admin_data[user_id].get("query")
        
        # Search IMDb
        imdb_results = await get_poster(query, bulk=True)
        
        if not imdb_results:
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption="No results found on IMDb for the provided series name."
            )
            return
        
        # Store the results in temp data
        temp_admin_data[user_id]["search_results"] = imdb_results
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SEARCH_RESULTS"
        
        # Send the IMDb results as buttons
        await send_imdb_selection_message(client, user_id, query, imdb_results, main_message_id)
        return
    
    # Handle TMDB search button
    if data == "search_tmdb":
        await callback_query.answer("Searching TMDB...")
        query = temp_admin_data[user_id].get("query")
        
        # Search TMDB
        tmdb_results = await get_tmdb_info(query, bulk=True)
        
        if not tmdb_results:
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption="No results found on TMDB for the provided series name."
            )
            return
        
        # Store the results in temp data
        temp_admin_data[user_id]["search_results"] = tmdb_results
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SEARCH_RESULTS"
        
        # Send the TMDB results as buttons
        await send_tmdb_selection_message(client, user_id, query, tmdb_results, main_message_id)
        return
    
    # Handle get genre/rating from IMDb button
    if data == "get_genre_rating_imdb":
        await callback_query.answer("Getting genre and rating from IMDb...")
        series_key = temp_admin_data[user_id].get("current_series_key")
        series_data = get_series_by_key(series_key)
        
        if not series_data:
            await callback_query.answer("Series not found.", show_alert=True)
            return
        
        # Try to get IMDb ID from series data
        imdb_id = series_data.get("imdb_id")
        if not imdb_id:
            # Try to find IMDb ID using title and year
            title = series_data.get("title")
            year = series_data.get("released_on")
            imdb_results = await get_poster(f"{title} {year}", bulk=True)
            if imdb_results:
                imdb_id = imdb_results[0].get("imdb_id")
        
        if imdb_id:
            # Get IMDb details
            imdb_details = await get_poster(imdb_id, id=True)
            if imdb_details:
                # Update series data with IMDb genre and rating
                update_data = {}
                if not series_data.get("genre") and imdb_details.get("genres"):
                    update_data["genre"] = imdb_details.get("genres")
                if not series_data.get("rating") and imdb_details.get("rating"):
                    update_data["rating"] = imdb_details.get("rating")
                
                if update_data:
                    for field, value in update_data.items():
                        update_series_field(series_key, field, value)
                        series_data[field] = value
                    
                    await callback_query.answer("Genre and rating updated from IMDb.")
                    await send_series_details_message(client, user_id, series_data, main_message_id)
                    return
        
        await callback_query.answer("Failed to get genre and rating from IMDb.", show_alert=True)
        return
    
    # Handle get genre/rating from TMDB button
    if data == "get_genre_rating_tmdb":
        await callback_query.answer("Getting genre and rating from TMDB...")
        series_key = temp_admin_data[user_id].get("current_series_key")
        series_data = get_series_by_key(series_key)
        
        if not series_data:
            await callback_query.answer("Series not found.", show_alert=True)
            return
        
        # Try to get TMDB ID from series data
        tmdb_id = series_data.get("tmdb_id")
        media_type = series_data.get("media_type", "tv")
        
        if tmdb_id:
            # Get TMDB details
            tmdb_details = await get_tmdb_info(query=None, tmdb_id=tmdb_id, media_type=media_type)
            if tmdb_details:
                # Update series data with TMDB genre and rating
                update_data = {}
                if not series_data.get("genre") and tmdb_details.get("genres"):
                    update_data["genre"] = tmdb_details.get("genres")
                if not series_data.get("rating") and tmdb_details.get("rating"):
                    update_data["rating"] = tmdb_details.get("rating")
                
                if update_data:
                    for field, value in update_data.items():
                        update_series_field(series_key, field, value)
                        series_data[field] = value
                    
                    await callback_query.answer("Genre and rating updated from TMDB.")
                    await send_series_details_message(client, user_id, series_data, main_message_id)
                    return
        
        await callback_query.answer("Failed to get genre and rating from TMDB.", show_alert=True)
        return
    
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
            # Get TMDB details
            movie_details = await get_tmdb_info(query=None, tmdb_id=media_id, media_type=media_type)
            if movie_details:
                # Add source information
                movie_details['source'] = 'tmdb'
        elif source == 'imdb':
            # Get IMDb details
            movie_details = await get_poster(media_id, id=True)
            if movie_details:
                # Add source information and map fields
                movie_details['source'] = 'imdb'
                movie_details['released_on'] = movie_details.get('year')
                movie_details['genres'] = movie_details.get('genres')
        
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
                'released_on': format_release_date(movie_details.get('released_on', 'N/A')),
                'genre': movie_details.get('genres', 'N/A'),
                'rating': movie_details.get('rating', 'N/A'),
                'tmdb_id': movie_details.get('tmdb_id') if source == 'tmdb' else None,
                'imdb_id': movie_details.get('imdb_id') if source == 'imdb' else None,
                'media_type': movie_details.get('media_type', 'series'),
                'source': source,  # Store the source
                'poster_file_id': None,
                'languages': [],
                'language_layout': [],
                'published': False,
                'added_by': user_id,
                'edited_by': []
            }
            if not add_series(series_data, added_by=user_id):
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
        
        # Send poster to admin's assigned channel and get file ID
        poster_url = movie_details.get('poster_url') or movie_details.get('poster')
        poster_file_id = await send_poster_to_admin_channel(
            client, 
            user_id,
            poster_url=poster_url,
            caption="#MainPoster"
        )
        
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
        # Determine which source to show based on the first result
        if search_results and search_results[0].get("source") == "tmdb":
            await send_tmdb_selection_message(client, user_id, query, search_results, main_message_id)
        else:
            await send_imdb_selection_message(client, user_id, query, search_results, main_message_id)
    
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
    
    # Handle poster management callbacks
    elif data == "change_poster":
        series_key = temp_admin_data[user_id].get("current_series_key")
        series_data = get_series_by_key(series_key)
        if not series_data:
            await callback_query.answer("Series not found.", show_alert=True)
            return
        
        text = "Select poster source:"
        buttons = [
            [InlineKeyboardButton("🌐 TMDB", callback_data="poster_source_tmdb")],
            [InlineKeyboardButton("🎬 IMDb", callback_data="poster_source_imdb")],
            [InlineKeyboardButton("📺 TVDB", callback_data="poster_source_tvdb")],
            [InlineKeyboardButton("🎥 OMDB", callback_data="poster_source_omdb")],
            [InlineKeyboardButton("📤 Upload", callback_data="poster_upload")],
            [InlineKeyboardButton("⬅️ Back", callback_data="back_to_series")]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        
        try:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=main_message_id,
                media=InputMediaPhoto(media=series_data.get('poster_file_id', NO_POSTER_FOUND_IMG[0]), caption=text),
                reply_markup=reply_markup
            )
            temp_admin_data[user_id]["state"] = "SELECT_POSTER_SOURCE"
        except Exception as e:
            logger.error(f"Error editing poster source selection: {e}")
    
    elif data.startswith("poster_source_"):
        api_type = data.split("_")[2]
        series_key = temp_admin_data[user_id].get("current_series_key")
        series_data = get_series_by_key(series_key)
        if not series_data:
            await callback_query.answer("Series not found.", show_alert=True)
            return
        
        await callback_query.answer(f"Fetching posters from {api_type.upper()}...")
        
        posters = await fetch_api_posters(client, user_id, series_data, api_type)
        
        if not posters:
            await callback_query.answer(f"No posters found from {api_type.upper()}.", show_alert=True)
            return
        
        temp_admin_data[user_id]["posters"] = posters
        temp_admin_data[user_id]["current_poster_index"] = 0
        temp_admin_data[user_id]["poster_level"] = "series"
        temp_admin_data[user_id]["state"] = "SELECTING_POSTER"
        
        await send_api_poster_selection(
            client, user_id, posters, 0, series_data, level="series"
        )
    
    elif data == "poster_nav_prev":
        posters = temp_admin_data[user_id].get("posters", [])
        current_index = temp_admin_data[user_id].get("current_poster_index", 0)
        if current_index > 0:
            current_index -= 1
            temp_admin_data[user_id]["current_poster_index"] = current_index
            
            series_key = temp_admin_data[user_id].get("current_series_key")
            series_data = get_series_by_key(series_key)
            level = temp_admin_data[user_id].get("poster_level", "series")
            
            await send_api_poster_selection(
                client, user_id, posters, current_index, series_data, level=level
            )
    
    elif data == "poster_nav_next":
        posters = temp_admin_data[user_id].get("posters", [])
        current_index = temp_admin_data[user_id].get("current_poster_index", 0)
        if current_index < len(posters) - 1:
            current_index += 1
            temp_admin_data[user_id]["current_poster_index"] = current_index
            
            series_key = temp_admin_data[user_id].get("current_series_key")
            series_data = get_series_by_key(series_key)
            level = temp_admin_data[user_id].get("poster_level", "series")
            
            await send_api_poster_selection(
                client, user_id, posters, current_index, series_data, level=level
            )
    
    elif data == "poster_confirm":
        posters = temp_admin_data[user_id].get("posters", [])
        current_index = temp_admin_data[user_id].get("current_poster_index", 0)
        if current_index < len(posters):
            poster_url = posters[current_index]
            series_key = temp_admin_data[user_id].get("current_series_key")
            level = temp_admin_data[user_id].get("poster_level", "series")
            language_name = temp_admin_data[user_id].get("current_language_name")
            season_name = temp_admin_data[user_id].get("current_season_name")
            
            # Upload the poster to the channel and get file_id
            poster_file_id = await send_poster_to_admin_channel(
                client, 
                user_id,
                poster_url=poster_url,
                caption=f"#{'Main' if level == 'series' else level.capitalize()}Poster"
            )
            
            if poster_file_id:
                if level == "series":
                    update_series_field(series_key, "poster_file_id", poster_file_id)
                elif level == "language":
                    add_or_update_language(series_key, language_name, poster_file_id)
                elif level == "season":
                    add_or_update_season(series_key, language_name, season_name, poster_file_id)
                
                await callback_query.answer("Poster updated successfully!")
                
                # Go back to the previous screen
                if level == "series":
                    series_data = get_series_by_key(series_key)
                    await send_series_details_message(client, user_id, series_data, main_message_id)
                elif level == "language":
                    await send_language_management_message(client, user_id, series_key, main_message_id)
                elif level == "season":
                    await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
            else:
                await callback_query.answer("Failed to update poster.", show_alert=True)
    
    elif data == "poster_back":
        # Go back to poster source selection
        series_key = temp_admin_data[user_id].get("current_series_key")
        series_data = get_series_by_key(series_key)
        if not series_data:
            await callback_query.answer("Series not found.", show_alert=True)
            return
        
        text = "Select poster source:"
        buttons = [
            [InlineKeyboardButton("🌐 TMDB", callback_data="poster_source_tmdb")],
            [InlineKeyboardButton("🎬 IMDb", callback_data="poster_source_imdb")],
            [InlineKeyboardButton("📺 TVDB", callback_data="poster_source_tvdb")],
            [InlineKeyboardButton("🎥 OMDB", callback_data="poster_source_omdb")],
            [InlineKeyboardButton("📤 Upload", callback_data="poster_upload")],
            [InlineKeyboardButton("⬅️ Back", callback_data="back_to_series")]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        
        try:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=main_message_id,
                media=InputMediaPhoto(media=series_data.get('poster_file_id', NO_POSTER_FOUND_IMG[0]), caption=text),
                reply_markup=reply_markup
            )
            temp_admin_data[user_id]["state"] = "SELECT_POSTER_SOURCE"
        except Exception as e:
            logger.error(f"Error going back to poster source selection: {e}")
    
    elif data == "change_language_poster":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language_name")
        
        text = "Select poster source for language:"
        buttons = [
            [InlineKeyboardButton("🌐 TMDB", callback_data="poster_source_tmdb_lang")],
            [InlineKeyboardButton("🎬 IMDb", callback_data="poster_source_imdb_lang")],
            [InlineKeyboardButton("📺 TVDB", callback_data="poster_source_tvdb_lang")],
            [InlineKeyboardButton("🎥 OMDB", callback_data="poster_source_omdb_lang")],
            [InlineKeyboardButton("📤 Upload", callback_data="poster_upload_lang")],
            [InlineKeyboardButton("⬅️ Back", callback_data="back_to_languages")]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        
        try:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=main_message_id,
                media=InputMediaPhoto(media=NO_POSTER_FOUND_IMG[0], caption=text),
                reply_markup=reply_markup
            )
            temp_admin_data[user_id]["state"] = "SELECT_LANGUAGE_POSTER_SOURCE"
        except Exception as e:
            logger.error(f"Error editing language poster source selection: {e}")
    
    elif data == "change_season_poster":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language_name")
        season_name = temp_admin_data[user_id].get("current_season_name")
        
        text = "Select poster source for season:"
        buttons = [
            [InlineKeyboardButton("🌐 TMDB", callback_data="poster_source_tmdb_season")],
            [InlineKeyboardButton("🎬 IMDb", callback_data="poster_source_imdb_season")],
            [InlineKeyboardButton("📺 TVDB", callback_data="poster_source_tvdb_season")],
            [InlineKeyboardButton("🎥 OMDB", callback_data="poster_source_omdb_season")],
            [InlineKeyboardButton("📤 Upload", callback_data="poster_upload_season")],
            [InlineKeyboardButton("⬅️ Back", callback_data="back_to_seasons")]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        
        try:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=main_message_id,
                media=InputMediaPhoto(media=NO_POSTER_FOUND_IMG[0], caption=text),
                reply_markup=reply_markup
            )
            temp_admin_data[user_id]["state"] = "SELECT_SEASON_POSTER_SOURCE"
        except Exception as e:
            logger.error(f"Error editing season poster source selection: {e}")
    
    # Add handlers for language and season poster sources
    elif data.endswith("_lang"):
        api_type = data.split("_")[2]
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language_name")
        series_data = get_series_by_key(series_key)
        
        if not series_data:
            await callback_query.answer("Series not found.", show_alert=True)
            return
        
        await callback_query.answer(f"Fetching posters from {api_type.upper()}...")
        
        posters = await fetch_api_posters(client, user_id, series_data, api_type, level="language", language_name=language_name)
        
        if not posters:
            await callback_query.answer(f"No posters found from {api_type.upper()}.", show_alert=True)
            return
        
        temp_admin_data[user_id]["posters"] = posters
        temp_admin_data[user_id]["current_poster_index"] = 0
        temp_admin_data[user_id]["poster_level"] = "language"
        temp_admin_data[user_id]["state"] = "SELECTING_POSTER"
        
        await send_api_poster_selection(
            client, user_id, posters, 0, series_data, level="language", language_name=language_name
        )
    
    elif data.endswith("_season"):
        api_type = data.split("_")[2]
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language_name")
        season_name = temp_admin_data[user_id].get("current_season_name")
        series_data = get_series_by_key(series_key)
        
        if not series_data:
            await callback_query.answer("Series not found.", show_alert=True)
            return
        
        await callback_query.answer(f"Fetching posters from {api_type.upper()}...")
        
        posters = await fetch_api_posters(client, user_id, series_data, api_type, level="season", language_name=language_name, season_name=season_name)
        
        if not posters:
            await callback_query.answer(f"No posters found from {api_type.upper()}.", show_alert=True)
            return
        
        temp_admin_data[user_id]["posters"] = posters
        temp_admin_data[user_id]["current_poster_index"] = 0
        temp_admin_data[user_id]["poster_level"] = "season"
        temp_admin_data[user_id]["state"] = "SELECTING_POSTER"
        
        await send_api_poster_selection(
            client, user_id, posters, 0, series_data, level="season", language_name=language_name, season_name=season_name
        )
    
    # Handle other callbacks as needed
    else:
        await callback_query.answer("Unknown action", show_alert=True)

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

# Placeholder functions for processing inputs
async def process_language_input(client: Client, message: Message, text: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    target_row = temp_admin_data[user_id].get("target_row")
    
    # Add the language to the series
    if add_or_update_language(series_key, text):
        await message.reply(f"Language '{text}' added successfully.")
        
        # Update the language layout if needed
        series_data = get_series_by_key(series_key)
        languages = series_data.get("languages", [])
        language_layout = series_data.get("language_layout", [])
        
        # Ensure we have enough layout rows
        while len(language_layout) <= target_row:
            language_layout.append(1)
        
        # Update the layout
        language_layout[target_row] += 1
        update_series_field(series_key, "language_layout", language_layout)
        
        # Go back to language management
        await send_language_management_message(client, user_id, series_key, temp_admin_data[user_id].get("main_message_id"))
    else:
        await message.reply("Failed to add language.")

async def process_season_input(client: Client, message: Message, text: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language_name")
    target_row = temp_admin_data[user_id].get("target_row")
    
    # Add the season to the language
    if add_or_update_season(series_key, language_name, text):
        await message.reply(f"Season '{text}' added successfully.")
        
        # Update the season layout if needed
        series_data = get_series_by_key(series_key)
        languages = series_data.get("languages", [])
        
        for lang in languages:
            if lang["name"].lower() == language_name.lower():
                season_layout = lang.get("season_layout", [])
                
                # Ensure we have enough layout rows
                while len(season_layout) <= target_row:
                    season_layout.append(1)
                
                # Update the layout
                season_layout[target_row] += 1
                lang["season_layout"] = season_layout
                break
        
        # Update the series data
        update_series_field(series_key, "languages", languages)
        
        # Go back to season management
        await send_season_management_message(client, user_id, series_key, language_name, temp_admin_data[user_id].get("main_message_id"))
    else:
        await message.reply("Failed to add season.")

async def process_quality_input(client: Client, message: Message, text: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language_name")
    season_name = temp_admin_data[user_id].get("current_season_name")
    target_row = temp_admin_data[user_id].get("target_row")
    
    # Add the quality to the season
    if add_or_update_quality(series_key, language_name, season_name, text):
        await message.reply(f"Quality '{text}' added successfully.")
        
        # Update the quality layout if needed
        series_data = get_series_by_key(series_key)
        languages = series_data.get("languages", [])
        
        for lang in languages:
            if lang["name"].lower() == language_name.lower():
                for season in lang.get("seasons", []):
                    if season["name"].lower() == season_name.lower():
                        quality_layout = season.get("quality_layout", [])
                        
                        # Ensure we have enough layout rows
                        while len(quality_layout) <= target_row:
                            quality_layout.append(1)
                        
                        # Update the layout
                        quality_layout[target_row] += 1
                        season["quality_layout"] = quality_layout
                        break
                break
        
        # Update the series data
        update_series_field(series_key, "languages", languages)
        
        # Go back to quality management
        await send_quality_management_message(client, user_id, series_key, language_name, season_name, temp_admin_data[user_id].get("main_message_id"))
    else:
        await message.reply("Failed to add quality.")

async def process_codec_input(client: Client, message: Message, text: str):
    # Implementation for processing codec input
    await message.reply("Codec processed successfully.")

async def process_poster_input(client: Client, message: Message, level: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language_name")
    season_name = temp_admin_data[user_id].get("current_season_name")
    
    # Upload the poster to the channel and get file_id
    poster_file_id = await send_poster_to_admin_channel(
        client, 
        user_id,
        message=message,
        caption=f"#{'Main' if level == 'series' else level.capitalize()}Poster"
    )
    
    if poster_file_id:
        if level == "series":
            update_series_field(series_key, "poster_file_id", poster_file_id)
        elif level == "language":
            add_or_update_language(series_key, language_name, poster_file_id)
        elif level == "season":
            add_or_update_season(series_key, language_name, season_name, poster_file_id)
        
        await message.reply("Poster updated successfully!")
        
        # Go back to the previous screen
        if level == "series":
            series_data = get_series_by_key(series_key)
            await send_series_details_message(client, user_id, series_data, temp_admin_data[user_id].get("main_message_id"))
        elif level == "language":
            await send_language_management_message(client, user_id, series_key, temp_admin_data[user_id].get("main_message_id"))
        elif level == "season":
            await send_season_management_message(client, user_id, series_key, language_name, temp_admin_data[user_id].get("main_message_id"))
    else:
        await message.reply("Failed to update poster.")

async def process_first_file_input(client: Client, message: Message):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    quality_name = temp_admin_data[user_id].get("current_quality")
    
    # Get the message ID from the forwarded message
    channel_id, message_id = await get_message_id(client, message)
    
    if not channel_id or not message_id:
        await message.reply("Invalid file. Please forward a valid file from a channel.")
        return
    
    # Store the first file information
    temp_admin_data[user_id]["first_file"] = {
        "channel_id": channel_id,
        "message_id": message_id
    }
    
    # Ask for the last file
    temp_admin_data[user_id]["state"] = "AWAITING_LAST_FILE"
    await message.reply("Now forward me the last file (with tag) for this quality group.")

async def process_last_file_input(client: Client, message: Message):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    quality_name = temp_admin_data[user_id].get("current_quality")
    
    # Get the message ID from the forwarded message
    channel_id, message_id = await get_message_id(client, message)
    
    if not channel_id or not message_id:
        await message.reply("Invalid file. Please forward a valid file from a channel.")
        return
    
    # Get the first file information
    first_file = temp_admin_data[user_id].get("first_file")
    if not first_file:
        await message.reply("First file information not found. Please start over.")
        return
    
    # Create a unique link key for this quality group
    import uuid
    link_key = str(uuid.uuid4())
    
    # Store the file information in the episodes collection
    episodes_collection.insert_one({
        "file_link_key": link_key,
        "channel_id": first_file["channel_id"],
        "first_msg_id": first_file["message_id"],
        "last_msg_id": message_id,
        "created_at": datetime.utcnow()
    })
    
    # Update the quality with the link key
    if add_or_update_quality(series_key, language_name, season_name, quality_name, link_key):
        await message.reply(f"Files added successfully for {language_name}-{season_name}-{quality_name}")
        
        # Update the quality management view
        main_message_id = temp_admin_data[user_id].get("main_message_id")
        await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
        
        # Reset state
        temp_admin_data[user_id]["state"] = "MANAGE_QUALITIES"
        temp_admin_data[user_id].pop("first_file", None)
    else:
        await message.reply(f"Failed to add files for {language_name}-{season_name}-{quality_name}")
