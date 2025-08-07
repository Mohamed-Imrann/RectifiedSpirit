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

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, 
    InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    Message
)
from imdb import Cinemagoer
from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, TMDB_API_KEY, LOG_CHANNEL, DB_CHANNEL, RAW_DB_CHANNEL
from database.crazy_db import (
    add_series, get_series_by_key, update_series_field, add_or_update_language,
    get_languages, delete_language, add_or_update_season, get_seasons, delete_season,
    add_or_update_quality, get_qualities, get_quality_link, delete_quality,
    get_poster_file_id, update_poster_file_id, publish_series
)
from utils import (
    get_message_id, get_messages_in_range, delete_messages_from_user_chat, 
    get_poster, find_most_similar_title
)
from fuzzywuzzy import fuzz
from pyrogram.errors import MessageIdInvalid, FloodWait

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Temporary storage for multi-step UI interactions
temp_admin_data = {}

imdb = Cinemagoer()

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
NO_POSTER_FOUND_IMG = "https://envs.sh/esA.jpg"

# Helper to chunk buttons for inline keyboard
def chunk_buttons(buttons, chunk_size=2):
    return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]

async def get_tmdb_info(query, bulk=False, tmdb_id=None, media_type=None):
    """Fetches movie/TV show information from TMDB."""
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {TMDB_API_KEY}"
    }

    try:
        if tmdb_id:
            # Fetch details for a specific TMDB ID
            url = f"{TMDB_BASE_URL}/{media_type}/{tmdb_id}"
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
            
            return {
                'title': title,
                'year': year,
                'genres': ', '.join(genres) if genres else 'N/A',
                'rating': data.get('vote_average', 'N/A'),
                'poster_url': poster_url,
                'tmdb_id': data.get('id'),
                'media_type': media_type,
                'url': f'https://www.themoviedb.org/{media_type}/{data.get("id")}'
            }
        else:
            # Search mode
            search_results = []
            
            # Search TV shows
            url_tv = f"{TMDB_BASE_URL}/search/tv"
            response_tv = requests.get(url_tv, headers=headers, params={"query": query})
            response_tv.raise_for_status()
            data_tv = response_tv.json()
            for item in data_tv.get('results', [])[:5]: # Limit to 5 results
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
            response_movie = requests.get(url_movie, headers=headers, params={"query": query})
            response_movie.raise_for_status()
            data_movie = response_movie.json()
            for item in data_movie.get('results', [])[:5]: # Limit to 5 results
                if item.get('title'):
                    search_results.append({
                        'title': item.get('title'),
                        'year': item.get('release_date', '').split('-')[0] if item.get('release_date') else 'N/A',
                        'tmdb_id': item.get('id'),
                        'media_type': 'movie',
                        'source': 'tmdb'
                    })
            
            return search_results[:10] # Return max 10 results total (TV first, then movies)

    except requests.exceptions.RequestException as e:
        logger.error(f"TMDB API error: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred with TMDB: {e}")
        return None

async def download_and_upload_poster(client: Client, poster_url: str = None, message: Message = None):
    """Downloads a poster (from URL or user-provided photo), uploads it to LOG_CHANNEL, and returns its file_id."""
    temp_dir = os.path.join(TMP_DOWNLOAD_DIRECTORY, str(uuid.uuid4()))
    os.makedirs(temp_dir, exist_ok=True)
    download_path = None
    file_id = None

    try:
        if poster_url:
            # Download from URL
            response = requests.get(poster_url, stream=True)
            response.raise_for_status()
            download_path = os.path.join(temp_dir, "poster.jpg")
            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        elif message and message.photo and message.photo.file_id:
            # Use user-provided photo
            download_path = await client.download_media(message.photo.file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        elif message and message.video and message.video.thumbs and message.video.thumbs[0].file_id:
            # Use user-provided video thumbnail
            download_path = await client.download_media(message.video.thumbs[0].file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        else:
            logger.warning("No valid poster source (URL, photo, or video thumbnail) provided.")
            return None

        if download_path:
            # Upload to LOG_CHANNEL
            sent_msg = await client.send_photo(LOG_CHANNEL, photo=download_path, caption="Series Poster")
            file_id = sent_msg.photo.file_id
            try:
                await sent_msg.delete() # Delete from log channel to keep it clean
            except Exception as e:
                logger.warning(f"Could not delete temporary poster message from LOG_CHANNEL: {e}")
    except Exception as e:
        logger.error(f"Error downloading/uploading poster: {e}")
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
    return file_id

async def send_series_selection_message(client: Client, user_id: int, query: str, results: list, message_id: int = None):
    """Sends or edits the series selection message with TMDB/IMDb results."""
    text = f"**Select a series from below:**\n\nSearch query: `{query}`"
    
    buttons = []
    for item in results:
        unique_id = str(uuid.uuid4())
        temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
        temp_admin_data[user_id][unique_id] = {
            'id': item.get('tmdb_id') if item.get('source') == 'tmdb' else item.get('imdb_id'),
            'media_type': item.get('media_type'),
            'source': item.get('source'),
            'query': query # Store original query for 'Back' button
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
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=NO_POSTER_FOUND_IMG,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.MARKDOWN
            )
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
        [InlineKeyboardButton("🌐 Languages", callback_data=f"newui_manage_languages:{series_key}")],
        [InlineKeyboardButton("🖼️ Change Poster", callback_data=f"newui_change_poster:{series_key}")],
        [InlineKeyboardButton("📤 Publish Series", callback_data=f"newui_publish_series:{series_key}")],
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
    """Sends or edits the language management message."""
    series_data = get_series_by_key(series_key)
    if not series_data:
        await client.send_message(user_id, "Series not found.")
        return

    languages = series_data.get("languages", [])
    
    text = f"**Series:** `{series_data.get('title', 'N/A')}`\n\n"
    text += "Select any Language group to add new Season/Part group inside them. Or click '+' button to add new Language group.\n\n"

    buttons = []
    for lang in languages:
        buttons.append([
            InlineKeyboardButton(f"{lang['name']} ({len(lang.get('seasons', []))} Seasons)", 
                              callback_data=f"newui_manage_seasons:{series_key}:{lang['name']}")
        ])
    
    buttons.append([InlineKeyboardButton("+ Language", callback_data=f"newui_add_language:{series_key}")])
    buttons.append([InlineKeyboardButton("⬅️ Back to Series", callback_data=f"newui_back_to_series:{series_key}")])

    reply_markup = InlineKeyboardMarkup(buttons)

    # Determine which poster to use: series poster
    poster_to_use = series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG

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
    """Sends or edits the season management message."""
    series_data = get_series_by_key(series_key)
    if not series_data:
        await client.send_message(user_id, "Series not found.")
        return

    current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
    if not current_lang:
        await client.send_message(user_id, "Language not found.")
        return

    seasons = current_lang.get("seasons", [])
    
    text = (
        f"**Series:** `{series_data.get('title', 'N/A')}`\n"
        f"**Language:** `{language_name}`\n\n"
        "Select any Seasons group to add new Quality group into them. Or click '+' button to add new Seasons group.\n\n"
    )

    buttons = []
    for season in seasons:
        buttons.append([
            InlineKeyboardButton(f"{season['name']} ({len(season.get('qualities', []))} Qualities)", 
                              callback_data=f"newui_manage_qualities:{series_key}:{language_name}:{season['name']}")
        ])
    
    buttons.append([InlineKeyboardButton("+ Season", callback_data=f"newui_add_season:{series_key}:{language_name}")])
    buttons.append([InlineKeyboardButton("🖼️ Change Poster for this Language", callback_data=f"newui_change_language_poster:{series_key}:{language_name}")])
    buttons.append([InlineKeyboardButton(f"🗑️ Delete '{language_name}' Group", callback_data=f"newui_delete_language:{series_key}:{language_name}")])
    buttons.append([InlineKeyboardButton("⬅️ Back to Languages", callback_data=f"newui_manage_languages:{series_key}")])

    reply_markup = InlineKeyboardMarkup(buttons)

    # Determine which poster to use: language poster, then series poster
    poster_to_use = current_lang.get("poster_file_id") or series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG

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
    """Sends or edits the quality management message."""
    series_data = get_series_by_key(series_key)
    if not series_data:
        await client.send_message(user_id, "Series not found.")
        return

    current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
    current_season = next((s for s in current_lang.get("seasons", []) if s["name"].lower() == season_name.lower()), None) if current_lang else None
    if not current_season:
        await client.send_message(user_id, "Season not found.")
        return

    qualities = current_season.get("qualities", [])
    
    text = (
        f"**Series:** `{series_data.get('title', 'N/A')}`\n"
        f"**Language:** `{language_name}`\n"
        f"**Season:** `{season_name}`\n\n"
        "Select any Quality group to add new files into them. Or click '+' button to add new Quality group.\n\n"
    )

    buttons = []
    for quality in qualities:
        buttons.append([
            InlineKeyboardButton(f"{quality['name']}", 
                              callback_data=f"newui_add_files:{series_key}:{language_name}:{season_name}:{quality['name']}")
        ])
    
    buttons.append([InlineKeyboardButton("+ Quality", callback_data=f"newui_add_quality:{series_key}:{language_name}:{season_name}")])
    buttons.append([InlineKeyboardButton("🖼️ Change Poster for this Season", callback_data=f"newui_change_season_poster:{series_key}:{language_name}:{season_name}")])
    buttons.append([InlineKeyboardButton(f"🗑️ Delete '{season_name}' Group", callback_data=f"newui_delete_season:{series_key}:{language_name}:{season_name}")])
    buttons.append([InlineKeyboardButton("⬅️ Back to Seasons", callback_data=f"newui_manage_seasons:{series_key}:{language_name}")])

    reply_markup = InlineKeyboardMarkup(buttons)

    # Determine which poster to use: season poster, then language poster, then series poster
    poster_to_use = current_season.get("poster_file_id") or current_lang.get("poster_file_id") or series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG

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

# --- Command Handlers ---

@Client.on_message(filters.command('newseriesui') & filters.user(ADMINS))
async def new_series_ui_command(client: Client, message: Message):
    user_id = message.from_user.id
    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None

    if not query:
        await message.reply("Usage: `/newseriesui <series_title>`")
        return

    temp_msg = await message.reply_photo(
        photo=NO_POSTER_FOUND_IMG, # Temporary placeholder
        caption="Searching TMDB and IMDb, please wait..."
    )
    
    tmdb_results = await get_tmdb_info(query, bulk=True)
    imdb_results = await get_poster(query, bulk=True) # Use get_poster for IMDb search

    all_results = []
    if tmdb_results:
        for item in tmdb_results:
            item['source'] = 'tmdb'
            all_results.append(item)
    if imdb_results:
        for item in imdb_results:
            # Ensure IMDb results have consistent keys
            all_results.append({
                'title': item.get('title'),
                'year': item.get('year'),
                'imdb_id': item.get('imdb_id'),
                'media_type': item.get('media_type'), # 'movie' or 'tv series'
                'source': 'imdb',
                'poster_url': item.get('poster_url')
            })

    if not all_results:
        await temp_msg.edit_caption("No results found on TMDB or IMDb for the provided series name.")
        return

    # Store the search results in temp_admin_data
    temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
    temp_admin_data[user_id]["search_results"] = all_results
    temp_admin_data[user_id]["query"] = query
    temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SEARCH_RESULTS"
    temp_admin_data[user_id]["main_message_id"] = temp_msg.id

    await send_series_selection_message(client, user_id, query, all_results, temp_msg.id)

# --- Callback Query Handlers ---

@Client.on_callback_query(filters.regex(r"^newui_") & filters.user(ADMINS))
async def newui_callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data.split(":")
    action = data[0].replace("newui_", "")
    
    if user_id not in temp_admin_data:
        await callback_query.answer("Session expired. Please start again with /newseriesui.", show_alert=True)
        return
    
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    
    if action == "search_again":
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
    
    elif action in ["tmdb_select", "imdb_select"]:
        unique_id = data[1]
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
        
        # Check if series already exists, if so, load it
        existing_series = get_series_by_key(series_key)
        if existing_series:
            series_data = existing_series
            await callback_query.answer("Series already exists. Loading for editing.", show_alert=True)
        else:
            # Create new series data
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
        
        # Re-fetch series_data to ensure it's the latest from DB
        series_data = get_series_by_key(series_key)
        if not series_data:
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption="Failed to retrieve series data after initial setup. Please try again."
            )
            return
        
        # Download and upload poster to LOG_CHANNEL, then update DB
        poster_file_id = await download_and_upload_poster(client, poster_url=movie_details.get('poster_url') or movie_details.get('poster'))
        if poster_file_id:
            update_series_field(series_key, "poster_file_id", poster_file_id)
            series_data["poster_file_id"] = poster_file_id
        else:
            await client.send_message(user_id, "Failed to download/upload poster. Using placeholder.")
            update_series_field(series_key, "poster_file_id", NO_POSTER_FOUND_IMG)
            series_data["poster_file_id"] = NO_POSTER_FOUND_IMG
        
        # Update main message with series details and management buttons
        new_main_msg_id = await send_series_details_message(client, user_id, series_data, main_message_id)
        if new_main_msg_id:
            temp_admin_data[user_id]["main_message_id"] = new_main_msg_id
            temp_admin_data[user_id]["current_series_key"] = series_key
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SERIES_DETAILS"
    
    elif action == "back_to_search":
        await callback_query.answer("Going back to search results...")
        query = temp_admin_data[user_id].get("query")
        search_results = temp_admin_data[user_id].get("search_results", [])
        
        if not query or not search_results:
            await callback_query.answer("No previous search data found.", show_alert=True)
            return
        
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SEARCH_RESULTS"
        await send_series_selection_message(client, user_id, query, search_results, main_message_id)
    
    elif action == "back_to_series":
        series_key = data[1]
        series_data = get_series_by_key(series_key)
        if not series_data:
            await callback_query.answer("Series not found.", show_alert=True)
            return
        
        await callback_query.answer("Going back to series details...")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SERIES_DETAILS"
        await send_series_details_message(client, user_id, series_data, main_message_id)
    
    elif action == "manage_languages":
        series_key = data[1]
        await callback_query.answer("Managing languages...")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_LANGUAGES"
        await send_language_management_message(client, user_id, series_key, main_message_id)
    
    elif action == "add_language":
        series_key = data[1]
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
    
    elif action == "manage_seasons":
        _, series_key, language_name = data
        await callback_query.answer("Managing seasons...")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_SEASONS"
        await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
    
    elif action == "add_season":
        _, series_key, language_name = data
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
    
    elif action == "manage_qualities":
        _, series_key, language_name, season_name = data
        await callback_query.answer("Managing qualities...")
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_QUALITIES"
        await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
    
    elif action == "add_quality":
        _, series_key, language_name, season_name = data
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
    
    elif action == "add_files":
        _, series_key, language_name, season_name, quality_name = data
        await callback_query.answer("Adding files...")
        
        # Store the current quality context
        temp_admin_data[user_id]["current_language"] = language_name
        temp_admin_data[user_id]["current_season"] = season_name
        temp_admin_data[user_id]["current_quality"] = quality_name
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_AWAITING_FIRST_FILE"
        
        await client.send_message(
            user_id,
            f"Forward me the first file (with tag) for {language_name}-{season_name}-{quality_name}"
        )
    
    elif action == "change_poster":
        series_key = data[1]
        await callback_query.answer("Send a new poster...")
        
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_AWAITING_SERIES_POSTER"
        temp_admin_data[user_id]["current_series_key"] = series_key
        
        await client.send_message(
            user_id,
            "Please send a photo or video to use as the series poster:"
        )
    
    elif action == "change_language_poster":
        _, series_key, language_name = data
        await callback_query.answer("Send a new poster...")
        
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_AWAITING_LANGUAGE_POSTER"
        temp_admin_data[user_id]["current_series_key"] = series_key
        temp_admin_data[user_id]["current_language"] = language_name
        
        await client.send_message(
            user_id,
            f"Please send a photo or video to use as the poster for {language_name}:"
        )
    
    elif action == "change_season_poster":
        _, series_key, language_name, season_name = data
        await callback_query.answer("Send a new poster...")
        
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_AWAITING_SEASON_POSTER"
        temp_admin_data[user_id]["current_series_key"] = series_key
        temp_admin_data[user_id]["current_language"] = language_name
        temp_admin_data[user_id]["current_season"] = season_name
        
        await client.send_message(
            user_id,
            f"Please send a photo or video to use as the poster for {language_name}-{season_name}:"
        )
    
    elif action == "delete_language":
        _, series_key, language_name = data
        await callback_query.answer(f"Deleting {language_name}...")
        
        if delete_language(series_key, language_name):
            await client.send_message(user_id, f"Language '{language_name}' deleted successfully.")
            # Refresh the language management view
            await send_language_management_message(client, user_id, series_key, main_message_id)
        else:
            await client.send_message(user_id, f"Failed to delete language '{language_name}'.")
    
    elif action == "delete_season":
        _, series_key, language_name, season_name = data
        await callback_query.answer(f"Deleting {season_name}...")
        
        if delete_season(series_key, language_name, season_name):
            await client.send_message(user_id, f"Season '{season_name}' deleted successfully.")
            # Refresh the season management view
            await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
        else:
            await client.send_message(user_id, f"Failed to delete season '{season_name}'.")
    
    elif action == "publish_series":
        series_key = data[1]
        await callback_query.answer("Publishing series...")
        
        # Show confirmation dialog
        text = (
            "Do you want to publish this series?\n\n"
            "NOTE: Once you publish this series, you can't edit it anymore.\n"
            "All the empty groups will be removed automatically."
        )
        
        buttons = [
            [InlineKeyboardButton("✅ Yes", callback_data=f"newui_confirm_publish:{series_key}")],
            [InlineKeyboardButton("❌ No", callback_data=f"newui_cancel_publish:{series_key}")]
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
        series_key = data[1]
        await callback_query.answer("Publishing...")
        
        if publish_series(series_key):
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption="✅ Series published successfully!"
            )
            # Clear the state
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_PUBLISHED"
        else:
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption="❌ Failed to publish series. Please try again."
            )
    
    elif action == "cancel_publish":
        series_key = data[1]
        await callback_query.answer("Cancelling publish...")
        
        series_data = get_series_by_key(series_key)
        if series_data:
            await send_series_details_message(client, user_id, series_data, main_message_id)
        else:
            await client.send_message(user_id, "Series not found.")
    
    elif action == "edit_details":
        series_key = data[1]
        await callback_query.answer("Editing series details...")
        
        series_data = get_series_by_key(series_key)
        if not series_data:
            await client.send_message(user_id, "Series not found.")
            return
        
        # Show editable fields
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
            [InlineKeyboardButton("⬅️ Back", callback_data=f"newui_back_to_series:{series_key}")]
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
    
    elif action == "edit_field":
        _, series_key, field = data
        await callback_query.answer(f"Editing {field}...")
        
        temp_admin_data[user_id]["state"] = f"NEW_SERIES_UI_EDITING_{field.upper()}"
        temp_admin_data[user_id]["current_series_key"] = series_key
        temp_admin_data[user_id]["current_field"] = field
        
        field_display = field.replace("_", " ").title()
        await client.send_message(
            user_id,
            f"Enter new value for {field_display}:"
        )

# --- Message Handlers ---

@Client.on_message(filters.text & filters.private & filters.user(ADMINS))
async def handle_admin_text_input(client: Client, message: Message):
    user_id = message.from_user.id
    current_state = temp_admin_data.get(user_id, {}).get("state")
    
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

@Client.on_message((filters.photo | filters.video | filters.document) & filters.private & filters.user(ADMINS))
async def handle_admin_media_input(client: Client, message: Message):
    user_id = message.from_user.id
    current_state = temp_admin_data.get(user_id, {}).get("state")
    
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

# --- Process Input Functions ---

async def process_language_input(client: Client, message: Message, language_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    ask_message_id = temp_admin_data[user_id].get("ask_message_id")

    if not series_key:
        await message.reply("Error: Series key not found in session.")
        return

    # Delete the bot's prompt message and the user's reply
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
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    ask_message_id = temp_admin_data[user_id].get("ask_message_id")

    if not all([series_key, language_name]):
        await message.reply("Error: Series or language not found in session.")
        return

    # Delete the bot's prompt message and the user's reply
    try:
        if ask_message_id:
            await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
        await message.delete()
    except Exception as e:
        logger.warning(f"Could not delete prompt/user message: {e}")

    if add_or_update_season(series_key, language_name, season_name):
        confirmation_msg = await client.send_message(
            chat_id=user_id,
            text=f"Season '{season_name}' added/updated successfully.",
            reply_markup=ReplyKeyboardRemove()
        )
        asyncio.create_task(confirmation_msg.delete())

        await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_SEASONS"
    else:
        await message.reply("Failed to add/update season.")

    temp_admin_data[user_id].pop("ask_message_id", None)

async def process_quality_input(client: Client, message: Message, quality_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    ask_message_id = temp_admin_data[user_id].get("ask_message_id")

    if not all([series_key, language_name, season_name]):
        await message.reply("Error: Series, language, or season not found in session.")
        return

    # Delete the bot's prompt message and the user's reply
    try:
        if ask_message_id:
            await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
        await message.delete()
    except Exception as e:
        logger.warning(f"Could not delete prompt/user message: {e}")

    if add_or_update_quality(series_key, language_name, season_name, quality_name):
        confirmation_msg = await client.send_message(
            chat_id=user_id,
            text=f"Quality '{quality_name}' added/updated successfully.",
            reply_markup=ReplyKeyboardRemove()
        )
        asyncio.create_task(confirmation_msg.delete())

        await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_QUALITIES"
    else:
        await message.reply("Failed to add/update quality.")

    temp_admin_data[user_id].pop("ask_message_id", None)

async def process_codec_input(client: Client, message: Message, codec: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    quality_name = temp_admin_data[user_id].get("current_quality")
    first_file_id = temp_admin_data[user_id].get("first_file_id")
    last_file_id = temp_admin_data[user_id].get("last_file_id")
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    ask_message_id = temp_admin_data[user_id].get("ask_message_id")

    if not all([series_key, language_name, season_name, quality_name, first_file_id, last_file_id]):
        await message.reply("Error: Missing data in session.")
        return

    # Delete the bot's prompt message and the user's reply
    try:
        if ask_message_id:
            await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
        await message.delete()
    except Exception as e:
        logger.warning(f"Could not delete prompt/user message: {e}")

    # Update the quality with the codec and link_key
    link_key = f"{first_file_id}_{last_file_id}"
    if add_or_update_quality(series_key, language_name, season_name, quality_name, link_key=link_key, codec=codec):
        confirmation_msg = await client.send_message(
            chat_id=user_id,
            text=f"Files added to database successfully for {language_name}-{season_name}-{quality_name}.",
            reply_markup=ReplyKeyboardRemove()
        )
        asyncio.create_task(confirmation_msg.delete())

        # Go back to quality management
        await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_MANAGE_QUALITIES"
    else:
        await message.reply("Failed to add files to database.")

    temp_admin_data[user_id].pop("ask_message_id", None)
    temp_admin_data[user_id].pop("first_file_id", None)
    temp_admin_data[user_id].pop("last_file_id", None)

async def process_field_edit(client: Client, message: Message, new_value: str, field: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    main_message_id = temp_admin_data[user_id].get("main_message_id")

    if not series_key:
        await message.reply("Error: Series key not found in session.")
        return

    # Update the field in the database
    if update_series_field(series_key, field, new_value):
        confirmation_msg = await client.send_message(
            chat_id=user_id,
            text=f"Field '{field}' updated successfully.",
            reply_markup=ReplyKeyboardRemove()
        )
        asyncio.create_task(confirmation_msg.delete())

        # Go back to series details
        series_data = get_series_by_key(series_key)
        if series_data:
            await send_series_details_message(client, user_id, series_data, main_message_id)
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SERIES_DETAILS"
        else:
            await client.send_message(user_id, "Series not found.")
    else:
        await message.reply(f"Failed to update field '{field}'.")

    # Clean up
    temp_admin_data[user_id].pop("current_field", None)

async def process_poster_input(client: Client, message: Message, poster_type: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    main_message_id = temp_admin_data[user_id].get("main_message_id")

    if not series_key:
        await message.reply("Error: Series key not found in session.")
        return

    # Download and upload the poster
    poster_file_id = await download_and_upload_poster(client, message=message)
    if not poster_file_id:
        await message.reply("Failed to process the poster. Please try again.")
        return

    # Update the poster in the database
    if poster_type == "series":
        if update_poster_file_id(series_key, poster_file_id):
            await message.reply("Series poster updated successfully.")
        else:
            await message.reply("Failed to update series poster.")
    elif poster_type == "language":
        language_name = temp_admin_data[user_id].get("current_language")
        if language_name and add_or_update_language(series_key, language_name, poster_file_id=poster_file_id):
            await message.reply(f"Language poster for '{language_name}' updated successfully.")
        else:
            await message.reply("Failed to update language poster.")
    elif poster_type == "season":
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        if language_name and season_name and add_or_update_season(series_key, language_name, season_name, poster_file_id=poster_file_id):
            await message.reply(f"Season poster for '{language_name}-{season_name}' updated successfully.")
        else:
            await message.reply("Failed to update season poster.")

    # Refresh the current view
    current_state = temp_admin_data[user_id].get("state")
    if current_state == "NEW_SERIES_UI_SERIES_DETAILS":
        series_data = get_series_by_key(series_key)
        if series_data:
            await send_series_details_message(client, user_id, series_data, main_message_id)
    elif current_state == "NEW_SERIES_UI_MANAGE_LANGUAGES":
        await send_language_management_message(client, user_id, series_key, main_message_id)
    elif current_state == "NEW_SERIES_UI_MANAGE_SEASONS":
        language_name = temp_admin_data[user_id].get("current_language")
        if language_name:
            await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
    elif current_state == "NEW_SERIES_UI_MANAGE_QUALITIES":
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        if language_name and season_name:
            await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)

async def process_first_file_input(client: Client, message: Message):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    quality_name = temp_admin_data[user_id].get("current_quality")

    if not all([series_key, language_name, season_name, quality_name]):
        await message.reply("Error: Missing data in session.")
        return

    # Get the message ID of the forwarded file
    channel_id, msg_id = await get_message_id(client, message)
    if not channel_id or not msg_id:
        await message.reply("Invalid file. Please forward a file from a channel.")
        return

    # Store the first file ID
    temp_admin_data[user_id]["first_file_id"] = f"{channel_id}_{msg_id}"
    temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_AWAITING_LAST_FILE"

    # Delete the user's message
    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"Could not delete user message: {e}")

    # Ask for the last file
    await client.send_message(
        user_id,
        f"Forward me the last file (with tag) for {language_name}-{season_name}-{quality_name}\n"
        f"Go to first file: https://t.me/c/{str(channel_id).replace('-100', '')}/{msg_id}"
    )

async def process_last_file_input(client: Client, message: Message):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    quality_name = temp_admin_data[user_id].get("current_quality")
    first_file_id = temp_admin_data[user_id].get("first_file_id")

    if not all([series_key, language_name, season_name, quality_name, first_file_id]):
        await message.reply("Error: Missing data in session.")
        return

    # Get the message ID of the forwarded file
    channel_id, msg_id = await get_message_id(client, message)
    if not channel_id or not msg_id:
        await message.reply("Invalid file. Please forward a file from a channel.")
        return

    # Store the last file ID
    last_file_id = f"{channel_id}_{msg_id}"
    temp_admin_data[user_id]["last_file_id"] = last_file_id
    temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_AWAITING_CODEC_INPUT"

    # Delete the user's message
    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"Could not delete user message: {e}")

    # Ask for the codec
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
from typing import Dict, Any

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, 
    InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from imdb import Cinemagoer
from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, TMDB_API_KEY, LOG_CHANNEL, DB_CHANNEL, RAW_DB_CHANNEL, SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG
from database.crazy_db import (
    add_series, get_series_by_key, update_series_field, add_or_update_language,
    get_languages, delete_language, add_or_update_season, get_seasons, delete_season,
    add_or_update_quality, get_qualities, get_quality_link, delete_quality,
    get_poster_file_id, update_poster_file_id, publish_series, get_series_name, get_poster_manuel, get_links_for_quality
)
from database.gfilters_mdb import (
    find_gfilter,
    get_gfilters
)
from utils import (
    get_message_id, get_messages_in_range, delete_messages_from_user_chat, 
    get_poster, find_most_similar_title, temp
)
from fuzzywuzzy import fuzz
from pyrogram.errors import MessageIdInvalid, FloodWait

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Temporary storage for multi-step UI interactions
temp_admin_data = {}

# Dictionary to hold locks for admin users
admin_locks: Dict[int, asyncio.Lock] = {}

# Dictionary to track user requests for series selection
user_requestor = {}

imdb = Cinemagoer()

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

# Helper to get or create a lock for an admin user
def get_admin_lock(user_id: int) -> asyncio.RLock:
    if user_id not in admin_locks:
        admin_locks[user_id] = asyncio.RLock()
    return admin_locks[user_id]

# Helper function to delete a message after a delay
async def DeleteMessage(msg):
    await asyncio.sleep(600)
    try:
        await msg.delete()
    except Exception as e:
        logger.warning(f"Failed to delete message: {e}")

# Helper to chunk buttons for inline keyboard
def chunk_buttons(buttons, chunk_size=2):
    return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]

# Global filter function (moved from pm_filter.py)
async def global_filters(client: Client, message: Message, text=False):
    group_id = message.chat.id
    name = text or message.text 
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id 
    keywords = await get_gfilters("gfilters")
    for keyword in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[\W])" + re.escape(keyword) + r"( |$|[\W])"
        if re.search(pattern, name, flags=re.IGNORECASE):
            reply_text, btn, alert, fileid = await find_gfilter("gfilters", keyword)
            if reply_text:
                reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")
            
            try:
                if fileid == "None":
                    if btn == "[]":
                        piroxrk = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_to_message_id=reply_id
                        )
                    else:
                        button = eval(btn)
                        piroxrk = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_markup=InlineKeyboardMarkup(button),
                            reply_to_message_id=reply_id
                        )
                elif btn == "[]":
                    piroxrk = await client.send_cached_media(
                        group_id,
                        fileid,
                        caption=reply_text or "",
                        reply_to_message_id=reply_id
                    )
                else:
                    button = eval(btn)
                    piroxrk = await message.reply_cached_media(
                        fileid,
                        caption=reply_text or "",
                        reply_markup=InlineKeyboardMarkup(button),
                        reply_to_message_id=reply_id
                    )
            except Exception as e:
                logger.exception(e)
            break
    else:
        return False

# Series filter function (moved from pm_filter.py)
async def series_filter(client: Client, message: Message):
    text = message.text.strip()
    series_infos = get_series()
    series_keys = [series['key'] for series in series_infos]
    series_names = [series['title'] for series in series_infos]

    series_key = None
    
    # Try exact match by key first
    if text.lower().replace(" ", "").replace("-", "") in series_keys:
        series_key = text.lower().replace(" ", "").replace("-", "")
    else:
        # Try exact match by title
        for s_info in series_infos:
            if s_info['title'].lower() == text.lower():
                series_key = s_info['key']
                break
        
        if not series_key:
            # Try close matches for titles
            close_matches = find_close_matches(text, series_names)
            if not close_matches:
                # Fallback to starts-with if no close matches
                first_word = text.split()[0]
                close_matches = [name for name in series_names if name.lower().startswith(first_word.lower())]
            
            if close_matches:
                buttons = []
                for match in close_matches:
                    s_info = next((s for s in series_infos if s['title'] == match), None)
                    if s_info:
                        buttons.append(InlineKeyboardButton(match, callback_data=f"user_series:{s_info['key']}"))
                
                if buttons:
                    buttons_chunked = chunk_buttons(buttons, chunk_size=1)
                    reply_markup = InlineKeyboardMarkup(buttons_chunked)
                    etho = await message.reply_photo(photo=random.choice(SPELL_CHECK_IMAGE), caption="<b>Choose Your Series:</b>", reply_markup=reply_markup)
                    reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else None
                    user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
                    asyncio.create_task(DeleteMessage(etho))
                    return

    if series_key:
        series = get_series_name(series_key)
        if not series:
            return

        languages = series.get("languages", {})
        
        reply_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n\n"
            "Select the language you need...!"
        )
        poster_url = get_movie_poster(series_key)
        
        buttons = []
        for lang_key, lang_data in languages.items():
            buttons.append(InlineKeyboardButton(lang_data['name'], callback_data=f"user_series:{series_key}:{lang_key}"))
        
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        reply_markup = InlineKeyboardMarkup(buttons_chunked)
        
        try:
            if poster_url:
                etho = await message.reply_photo(photo=poster_url, caption=reply_text, reply_markup=reply_markup)
            else:
                etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG[0], caption=reply_text, reply_markup=reply_markup)
            
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
            asyncio.create_task(DeleteMessage(etho))
            logger.info("Series filter message sent.")
        except pyrogram.errors.MediaEmpty:
            logger.warning(f"MediaEmpty error for poster: {poster_url}. Using placeholder.")
            etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG[0], caption=reply_text, reply_markup=reply_markup)
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
            asyncio.create_task(DeleteMessage(etho))
        except Exception as e:
            logger.error(f"Error sending series filter message: {e}")

def find_close_matches(query, possibilities, n=3, cutoff=0.6):
    import difflib
    return difflib.get_close_matches(query, possibilities, n, cutoff)

def get_movie_poster(series_key):
    poster_url = get_poster_manuel(series_key)
    if not poster_url:
        series = get_series_name(series_key)
        if series:
            poster_url = series.get('poster_url') # Get from the main series data
    return poster_url or NO_POSTER_FOUND_IMG[0]

# TMDB and other helper functions from the original admin_ui.py
async def get_tmdb_info(query, bulk=False, tmdb_id=None, media_type=None):
    """Fetches movie/TV show information from TMDB."""
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {TMDB_API_KEY}"
    }

    try:
        if tmdb_id:
            # Fetch details for a specific TMDB ID
            url = f"{TMDB_BASE_URL}/{media_type}/{tmdb_id}"
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
            
            return {
                'title': title,
                'year': year,
                'genres': ', '.join(genres) if genres else 'N/A',
                'rating': data.get('vote_average', 'N/A'),
                'poster_url': poster_url,
                'tmdb_id': data.get('id'),
                'media_type': media_type,
                'url': f'https://www.themoviedb.org/{media_type}/{data.get("id")}'
            }
        else:
            # Search mode
            search_results = []
            
            # Search TV shows
            url_tv = f"{TMDB_BASE_URL}/search/tv"
            response_tv = requests.get(url_tv, headers=headers, params={"query": query})
            response_tv.raise_for_status()
            data_tv = response_tv.json()
            for item in data_tv.get('results', [])[:5]: # Limit to 5 results
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
            response_movie = requests.get(url_movie, headers=headers, params={"query": query})
            response_movie.raise_for_status()
            data_movie = response_movie.json()
            for item in data_movie.get('results', [])[:5]: # Limit to 5 results
                if item.get('title'):
                    search_results.append({
                        'title': item.get('title'),
                        'year': item.get('release_date', '').split('-')[0] if item.get('release_date') else 'N/A',
                        'tmdb_id': item.get('id'),
                        'media_type': 'movie',
                        'source': 'tmdb'
                    })
            
            return search_results[:10] # Return max 10 results total (TV first, then movies)

    except requests.exceptions.RequestException as e:
        logger.error(f"TMDB API error: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred with TMDB: {e}")
        return None

async def download_and_upload_poster(client: Client, poster_url: str = None, message: Message = None):
    """Downloads a poster (from URL or user-provided photo), uploads it to LOG_CHANNEL, and returns its file_id."""
    temp_dir = os.path.join(TMP_DOWNLOAD_DIRECTORY, str(uuid.uuid4()))
    os.makedirs(temp_dir, exist_ok=True)
    download_path = None
    file_id = None

    try:
        if poster_url:
            # Download from URL
            response = requests.get(poster_url, stream=True)
            response.raise_for_status()
            download_path = os.path.join(temp_dir, "poster.jpg")
            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        elif message and message.photo and message.photo.file_id:
            # Use user-provided photo
            download_path = await client.download_media(message.photo.file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        elif message and message.video and message.video.thumbs and message.video.thumbs[0].file_id:
            # Use user-provided video thumbnail
            download_path = await client.download_media(message.video.thumbs[0].file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        else:
            logger.warning("No valid poster source (URL, photo, or video thumbnail) provided.")
            return None

        if download_path:
            # Upload to LOG_CHANNEL
            sent_msg = await client.send_photo(LOG_CHANNEL, photo=download_path, caption="Series Poster")
            file_id = sent_msg.photo.file_id
            try:
                await sent_msg.delete() # Delete from log channel to keep it clean
            except Exception as e:
                logger.warning(f"Could not delete temporary poster message from LOG_CHANNEL: {e}")
    except Exception as e:
        logger.error(f"Error downloading/uploading poster: {e}")
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
    return file_id

# Message handlers
@Client.on_message(filters.text & (filters.private | filters.group))
async def handle_message(client: Client, message: Message):
    user_id = message.from_user.id
    
    # If the message is in a group, apply global and series filters
    if message.chat.type != enums.ChatType.PRIVATE:
        glob = await global_filters(client, message)
        if glob == False:
            await series_filter(client, message)
        return
    
    # For private chats
    if user_id in ADMINS:
        # Check if the admin has an active state
        if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
            # Acquire the lock for this admin
            async with get_admin_lock(user_id):
                await handle_admin_text_input(client, message)
            return
    
    # For non-admins or admins without active state, apply global and series filters
    glob = await global_filters(client, message)
    if glob == False:
        await series_filter(client, message)

@Client.on_message((filters.photo | filters.video | filters.document) & (filters.private | filters.group))
async def handle_media_message(client: Client, message: Message):
    user_id = message.from_user.id
    
    if message.chat.type != enums.ChatType.PRIVATE:
        # In groups, we don't process media for admin UI, so we return
        return
    
    if user_id in ADMINS:
        if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
            async with get_admin_lock(user_id):
                await handle_admin_media_input(client, message)
            return
    
    # For non-admins or admins without active state, we don't do anything with media in private
    return

# Command handler for the new admin UI
@Client.on_message(filters.command('newseriesui') & filters.user(ADMINS))
async def new_series_ui_command(client: Client, message: Message):
    user_id = message.from_user.id
    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None

    if not query:
        await message.reply("Usage: `/newseriesui <series_title>`")
        return

    # Acquire the lock for this admin
    async with get_admin_lock(user_id):
        temp_msg = await message.reply_photo(
            photo=NO_POSTER_FOUND_IMG, # Temporary placeholder
            caption="Searching TMDB and IMDb, please wait..."
        )
        
        tmdb_results = await get_tmdb_info(query, bulk=True)
        imdb_results = await get_poster(query, bulk=True) # Use get_poster for IMDb search

        all_results = []
        if tmdb_results:
            for item in tmdb_results:
                item['source'] = 'tmdb'
                all_results.append(item)
        if imdb_results:
            for item in imdb_results:
                # Ensure IMDb results have consistent keys
                all_results.append({
                    'title': item.get('title'),
                    'year': item.get('year'),
                    'imdb_id': item.get('imdb_id'),
                    'media_type': item.get('media_type'), # 'movie' or 'tv series'
                    'source': 'imdb',
                    'poster_url': item.get('poster_url')
                })

        if not all_results:
            await temp_msg.edit_caption("No results found on TMDB or IMDb for the provided series name.")
            return

        # Store the search results in temp_admin_data
        temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
        temp_admin_data[user_id]["search_results"] = all_results
        temp_admin_data[user_id]["query"] = query
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SEARCH_RESULTS"
        temp_admin_data[user_id]["main_message_id"] = temp_msg.id

        await send_series_selection_message(client, user_id, query, all_results, temp_msg.id)

# Callback query handler
@Client.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data

    # Check if it's an admin UI callback (starts with "newui_")
    if data.startswith("newui_"):
        if user_id in ADMINS:
            async with get_admin_lock(user_id):
                await newui_callback_handler(client, callback_query)
        else:
            await callback_query.answer("You are not authorized!", show_alert=True)
        return

    # Otherwise, it's a user series callback
    if data.startswith("user_series:") or data.startswith("b:"):
        await user_series_callback_handler(client, callback_query)
        return

# User series callback handler (moved from pm_filter.py)
async def user_series_callback_handler(client: Client, query: CallbackQuery):
    data = query.data
    parts = data.split(":")
    clicked_user = query.from_user.id
    chat_id = query.message.chat.id
    message_id = query.message.id

    reply_msg = query.message.reply_to_message  
    if reply_msg and reply_msg.from_user:
        requested_user = reply_msg.from_user.id
    else:
        requested_user = user_requestor.get(f"{chat_id}•{message_id}")
    
    if chat_id < 0 and requested_user and clicked_user != requested_user:
        await query.answer("Not your request!", show_alert=True)
        return

    if data == "pages":
        await query.answer()
        return

    elif data.startswith("b:"):
        # This is the final link to fetch files
        file_link_key = data.split(":", 1)[1]
        
        # Fetch files from the episodes collection
        files_to_send, channel_id, first_msg_id, last_msg_id = await get_links_for_quality(file_link_key)

        if not files_to_send:
            await query.answer("No files found for this quality.", show_alert=True)
            return

        await query.answer("Sending files...")
        
        track_msgs = []
        for entry in files_to_send:
            try:
                copied_msg = await client.send_cached_media(
                    chat_id=query.from_user.id, 
                    file_id=entry["file_id"],
                    caption=entry.get("caption", "")
                )
                if copied_msg and temp.AUTO_DELETE_TIME and temp.AUTO_DELETE_TIME > 0:
                    track_msgs.append(copied_msg)
                await asyncio.sleep(0.5)
            except FloodWait as e:
                logger.warning(f"FloodWait for {e.value} sec")
                await asyncio.sleep(e.value)
                copied_msg = await client.send_cached_media(
                    chat_id=query.from_user.id, 
                    file_id=entry["file_id"],
                    caption=entry.get("caption", "")
                )
                if copied_msg and temp.AUTO_DELETE_TIME and temp.AUTO_DELETE_TIME > 0:
                    track_msgs.append(copied_msg)
            except Exception as e:
                logger.error(f"Error sending cached media to user {query.from_user.id}: {e}")
                # Optionally, send an error message to the user
                await client.send_message(query.from_user.id, f"Error sending file: {e}")
                
        if track_msgs:
            delete_data = await client.send_message(
                chat_id=query.from_user.id,
                text=temp.AUTO_DELETE_MSG.format(time=temp.AUTO_DELETE_TIME)
            )
            asyncio.create_task(DeleteMessage(delete_data)) # Use DeleteMessage for the auto-delete message
        return

    elif data.startswith("user_series:"):
        series_key = parts[1]
        series = get_series_name(series_key)
        if not series:
            await query.message.edit_text("Series not found or deleted.", parse_mode=enums.ParseMode.HTML)
            return

        lang_key = parts[2] if len(parts) > 2 else None
        season_key = parts[3] if len(parts) > 3 else None
        quality_key = parts[4] if len(parts) > 4 else None

        base_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n"
        )
        
        buttons = []
        current_level_data = None
        back_callback = None

        if not lang_key: # Show languages
            current_level_data = series.get("languages", {})
            for key, data_item in current_level_data.items():
                buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"user_series:{series_key}:{key}"))
            text = base_text + "\nSelect the language you need...!"
            # No back button at this level, as it's the initial series view
            
        elif not season_key: # Show seasons for selected language
            current_level_data = series.get("languages", {}).get(lang_key, {}).get("seasons", {})
            lang_name = series.get("languages", {}).get(lang_key, {}).get("name", "N/A")
            for key, data_item in current_level_data.items():
                buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"user_series:{series_key}:{lang_key}:{key}"))
            text = base_text + f"○ **Language:** `{lang_name}`\n\nSelect the season you need...!"
            back_callback = f"user_series:{series_key}"

        elif not quality_key: # Show qualities for selected season
            current_level_data = series.get("languages", {}).get(lang_key, {}).get("seasons", {}).get(season_key, {}).get("qualities", {})
            lang_name = series.get("languages", {}).get(lang_key, {}).get("name", "N/A")
            season_name = series.get("languages", {}).get(lang_key, {}).get("seasons", {}).get(season_key, {}).get("name", "N/A")
            for key, data_item in current_level_data.items():
                # The file_link_key is stored in crazy_db, but the actual files are in episodes collection
                file_link_key = data_item.get('file_link_key')
                if file_link_key:
                    buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"b:{file_link_key}"))
            text = base_text + f"○ **Language:** `{lang_name}`\n○ **Season:** `{season_name}`\n\nSelect the quality you need...!"
            back_callback = f"user_series:{series_key}:{lang_key}"
        
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        if back_callback:
            buttons_chunked.append([InlineKeyboardButton("Back", callback_data=back_callback)])
        
        reply_markup = InlineKeyboardMarkup(buttons_chunked)

        try:
            await query.message.edit_text(
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error editing message in user_series callback: {e}")
            await query.answer("An error occurred. Please try again.", show_alert=True)

# Admin UI callback handler
async def newui_callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data.split(":")
    action = data[0].replace("newui_", "")
    
    if user_id not in temp_admin_data:
        await callback_query.answer("Session expired. Please start again with /newseriesui.", show_alert=True)
        return
    
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    
    if action == "search_again":
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
    
    elif action in ["tmdb_select", "imdb_select"]:
        unique_id = data[1]
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
        
        # Check if series already exists, if so, load it
        existing_series = get_series_by_key(series_key)
        if existing_series:
            series_data = existing_series
            await callback_query.answer("Series already exists. Loading for editing.", show_alert=True)
        else:
            # Create new series data
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
        
        # Re-fetch series_data to ensure it's the latest from DB
        series_data = get_series_by_key(series_key)
        if not series_data:
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption="Failed to retrieve series data after initial setup. Please try again."
            )
            return
        
        # Download and upload poster to LOG_CHANNEL, then update DB
        poster_file_id = await download_and_upload_poster(client, poster_url=movie_details.get('poster_url') or movie_details.get('poster'))
        if poster_file_id:
            update_series_field(series_key, "poster_file_id", poster_file_id)
            series_data["poster_file_id"] = poster_file_id
        else:
            await client.send_message(user_id, "Failed to download/upload poster. Using placeholder.")
            update_series_field(series_key, "poster_file_id", NO_POSTER_FOUND_IMG)
            series_data["poster_file_id"] = NO_POSTER_FOUND_IMG
        
        # Update main message with series details and management buttons
        new_main_msg_id = await send_series_details_message(client, user_id, series_data, main_message_id)
        if new_main_msg_id:
            temp_admin_data[user_id]["main_message_id"] = new_main_msg_id
            temp_admin_data[user_id]["current_series_key"] = series_key
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SERIES_DETAILS"
    
    # ... (rest of the callback actions from the original admin_ui.py)

# ... (rest of the functions from the original admin_ui.py)

# Process input functions (handle_admin_text_input, handle_admin_media_input, etc.)
# ... (rest of the functions from the original admin_ui.py)import asyncio
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
from typing import Dict, Any

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, 
    InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from imdb import Cinemagoer
from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, TMDB_API_KEY, LOG_CHANNEL, DB_CHANNEL, RAW_DB_CHANNEL, SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG
from database.crazy_db import (
    add_series, get_series_by_key, update_series_field, add_or_update_language,
    get_languages, delete_language, add_or_update_season, get_seasons, delete_season,
    add_or_update_quality, get_qualities, get_quality_link, delete_quality,
    get_poster_file_id, update_poster_file_id, publish_series, get_series_name, get_poster_manuel, get_links_for_quality
)
from database.gfilters_mdb import (
    find_gfilter,
    get_gfilters
)
from utils import (
    get_message_id, get_messages_in_range, delete_messages_from_user_chat, 
    get_poster, find_most_similar_title, temp
)
from fuzzywuzzy import fuzz
from pyrogram.errors import MessageIdInvalid, FloodWait

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Temporary storage for multi-step UI interactions
temp_admin_data = {}

# Dictionary to hold locks for admin users
admin_locks: Dict[int, asyncio.RLock] = {}

# Dictionary to track user requests for series selection
user_requestor = {}

imdb = Cinemagoer()

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

# Helper to get or create a lock for an admin user
def get_admin_lock(user_id: int) -> asyncio.RLock:
    if user_id not in admin_locks:
        admin_locks[user_id] = asyncio.RLock()
    return admin_locks[user_id]

# Helper function to delete a message after a delay
async def DeleteMessage(msg):
    await asyncio.sleep(600)
    try:
        await msg.delete()
    except Exception as e:
        logger.warning(f"Failed to delete message: {e}")

# Helper to chunk buttons for inline keyboard
def chunk_buttons(buttons, chunk_size=2):
    return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]

# Global filter function (moved from pm_filter.py)
async def global_filters(client: Client, message: Message, text=False):
    group_id = message.chat.id
    name = text or message.text 
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id 
    keywords = await get_gfilters("gfilters")
    for keyword in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[\W])" + re.escape(keyword) + r"( |$|[\W])"
        if re.search(pattern, name, flags=re.IGNORECASE):
            reply_text, btn, alert, fileid = await find_gfilter("gfilters", keyword)
            if reply_text:
                reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")
            
            try:
                if fileid == "None":
                    if btn == "[]":
                        piroxrk = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_to_message_id=reply_id
                        )
                    else:
                        button = eval(btn)
                        piroxrk = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_markup=InlineKeyboardMarkup(button),
                            reply_to_message_id=reply_id
                        )
                elif btn == "[]":
                    piroxrk = await client.send_cached_media(
                        group_id,
                        fileid,
                        caption=reply_text or "",
                        reply_to_message_id=reply_id
                    )
                else:
                    button = eval(btn)
                    piroxrk = await message.reply_cached_media(
                        fileid,
                        caption=reply_text or "",
                        reply_markup=InlineKeyboardMarkup(button),
                        reply_to_message_id=reply_id
                    )
            except Exception as e:
                logger.exception(e)
            break
    else:
        return False

# Series filter function (moved from pm_filter.py)
async def series_filter(client: Client, message: Message):
    text = message.text.strip()
    series_infos = get_series()
    series_keys = [series['key'] for series in series_infos]
    series_names = [series['title'] for series in series_infos]

    series_key = None
    
    # Try exact match by key first
    if text.lower().replace(" ", "").replace("-", "") in series_keys:
        series_key = text.lower().replace(" ", "").replace("-", "")
    else:
        # Try exact match by title
        for s_info in series_infos:
            if s_info['title'].lower() == text.lower():
                series_key = s_info['key']
                break
        
        if not series_key:
            # Try close matches for titles
            close_matches = find_close_matches(text, series_names)
            if not close_matches:
                # Fallback to starts-with if no close matches
                first_word = text.split()[0]
                close_matches = [name for name in series_names if name.lower().startswith(first_word.lower())]
            
            if close_matches:
                buttons = []
                for match in close_matches:
                    s_info = next((s for s in series_infos if s['title'] == match), None)
                    if s_info:
                        buttons.append(InlineKeyboardButton(match, callback_data=f"user_series:{s_info['key']}"))
                
                if buttons:
                    buttons_chunked = chunk_buttons(buttons, chunk_size=1)
                    reply_markup = InlineKeyboardMarkup(buttons_chunked)
                    etho = await message.reply_photo(photo=random.choice(SPELL_CHECK_IMAGE), caption="<b>Choose Your Series:</b>", reply_markup=reply_markup)
                    reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else None
                    user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
                    asyncio.create_task(DeleteMessage(etho))
                    return

    if series_key:
        series = get_series_name(series_key)
        if not series:
            return

        languages = series.get("languages", {})
        
        reply_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n\n"
            "Select the language you need...!"
        )
        poster_url = get_movie_poster(series_key)
        
        buttons = []
        for lang_key, lang_data in languages.items():
            buttons.append(InlineKeyboardButton(lang_data['name'], callback_data=f"user_series:{series_key}:{lang_key}"))
        
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        reply_markup = InlineKeyboardMarkup(buttons_chunked)
        
        try:
            if poster_url:
                etho = await message.reply_photo(photo=poster_url, caption=reply_text, reply_markup=reply_markup)
            else:
                etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG[0], caption=reply_text, reply_markup=reply_markup)
            
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
            asyncio.create_task(DeleteMessage(etho))
            logger.info("Series filter message sent.")
        except pyrogram.errors.MediaEmpty:
            logger.warning(f"MediaEmpty error for poster: {poster_url}. Using placeholder.")
            etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG[0], caption=reply_text, reply_markup=reply_markup)
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
            asyncio.create_task(DeleteMessage(etho))
        except Exception as e:
            logger.error(f"Error sending series filter message: {e}")

def find_close_matches(query, possibilities, n=3, cutoff=0.6):
    import difflib
    return difflib.get_close_matches(query, possibilities, n, cutoff)

def get_movie_poster(series_key):
    poster_url = get_poster_manuel(series_key)
    if not poster_url:
        series = get_series_name(series_key)
        if series:
            poster_url = series.get('poster_url') # Get from the main series data
    return poster_url or NO_POSTER_FOUND_IMG[0]

# TMDB and other helper functions from the original admin_ui.py
async def get_tmdb_info(query, bulk=False, tmdb_id=None, media_type=None):
    """Fetches movie/TV show information from TMDB."""
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {TMDB_API_KEY}"
    }

    try:
        if tmdb_id:
            # Fetch details for a specific TMDB ID
            url = f"{TMDB_BASE_URL}/{media_type}/{tmdb_id}"
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
            
            return {
                'title': title,
                'year': year,
                'genres': ', '.join(genres) if genres else 'N/A',
                'rating': data.get('vote_average', 'N/A'),
                'poster_url': poster_url,
                'tmdb_id': data.get('id'),
                'media_type': media_type,
                'url': f'https://www.themoviedb.org/{media_type}/{data.get("id")}'
            }
        else:
            # Search mode
            search_results = []
            
            # Search TV shows
            url_tv = f"{TMDB_BASE_URL}/search/tv"
            response_tv = requests.get(url_tv, headers=headers, params={"query": query})
            response_tv.raise_for_status()
            data_tv = response_tv.json()
            for item in data_tv.get('results', [])[:5]: # Limit to 5 results
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
            response_movie = requests.get(url_movie, headers=headers, params={"query": query})
            response_movie.raise_for_status()
            data_movie = response_movie.json()
            for item in data_movie.get('results', [])[:5]: # Limit to 5 results
                if item.get('title'):
                    search_results.append({
                        'title': item.get('title'),
                        'year': item.get('release_date', '').split('-')[0] if item.get('release_date') else 'N/A',
                        'tmdb_id': item.get('id'),
                        'media_type': 'movie',
                        'source': 'tmdb'
                    })
            
            return search_results[:10] # Return max 10 results total (TV first, then movies)

    except requests.exceptions.RequestException as e:
        logger.error(f"TMDB API error: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred with TMDB: {e}")
        return None

async def download_and_upload_poster(client: Client, poster_url: str = None, message: Message = None):
    """Downloads a poster (from URL or user-provided photo), uploads it to LOG_CHANNEL, and returns its file_id."""
    temp_dir = os.path.join(TMP_DOWNLOAD_DIRECTORY, str(uuid.uuid4()))
    os.makedirs(temp_dir, exist_ok=True)
    download_path = None
    file_id = None

    try:
        if poster_url:
            # Download from URL
            response = requests.get(poster_url, stream=True)
            response.raise_for_status()
            download_path = os.path.join(temp_dir, "poster.jpg")
            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        elif message and message.photo and message.photo.file_id:
            # Use user-provided photo
            download_path = await client.download_media(message.photo.file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        elif message and message.video and message.video.thumbs and message.video.thumbs[0].file_id:
            # Use user-provided video thumbnail
            download_path = await client.download_media(message.video.thumbs[0].file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        else:
            logger.warning("No valid poster source (URL, photo, or video thumbnail) provided.")
            return None

        if download_path:
            # Upload to LOG_CHANNEL
            sent_msg = await client.send_photo(LOG_CHANNEL, photo=download_path, caption="Series Poster")
            file_id = sent_msg.photo.file_id
            try:
                await sent_msg.delete() # Delete from log channel to keep it clean
            except Exception as e:
                logger.warning(f"Could not delete temporary poster message from LOG_CHANNEL: {e}")
    except Exception as e:
        logger.error(f"Error downloading/uploading poster: {e}")
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
    return file_id

# Message handlers
@Client.on_message(filters.text & (filters.private | filters.group))
async def handle_message(client: Client, message: Message):
    user_id = message.from_user.id
    
    # If the message is in a group, apply global and series filters
    if message.chat.type != enums.ChatType.PRIVATE:
        glob = await global_filters(client, message)
        if glob == False:
            await series_filter(client, message)
        return
    
    # For private chats
    if user_id in ADMINS:
        # Check if the admin has an active state
        if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
            # Acquire the lock for this admin
            async with get_admin_lock(user_id):
                await handle_admin_text_input(client, message)
            return
    
    # For non-admins or admins without active state, apply global and series filters
    glob = await global_filters(client, message)
    if glob == False:
        await series_filter(client, message)

@Client.on_message((filters.photo | filters.video | filters.document) & (filters.private | filters.group))
async def handle_media_message(client: Client, message: Message):
    user_id = message.from_user.id
    
    if message.chat.type != enums.ChatType.PRIVATE:
        # In groups, we don't process media for admin UI, so we return
        return
    
    if user_id in ADMINS:
        if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
            async with get_admin_lock(user_id):
                await handle_admin_media_input(client, message)
            return
    
    # For non-admins or admins without active state, we don't do anything with media in private
    return

# Command handler for the new admin UI
@Client.on_message(filters.command('newseriesui') & filters.user(ADMINS))
async def new_series_ui_command(client: Client, message: Message):
    user_id = message.from_user.id
    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None

    if not query:
        await message.reply("Usage: `/newseriesui <series_title>`")
        return

    # Acquire the lock for this admin
    async with get_admin_lock(user_id):
        temp_msg = await message.reply_photo(
            photo=NO_POSTER_FOUND_IMG, # Temporary placeholder
            caption="Searching TMDB and IMDb, please wait..."
        )
        
        tmdb_results = await get_tmdb_info(query, bulk=True)
        imdb_results = await get_poster(query, bulk=True) # Use get_poster for IMDb search

        all_results = []
        if tmdb_results:
            for item in tmdb_results:
                item['source'] = 'tmdb'
                all_results.append(item)
        if imdb_results:
            for item in imdb_results:
                # Ensure IMDb results have consistent keys
                all_results.append({
                    'title': item.get('title'),
                    'year': item.get('year'),
                    'imdb_id': item.get('imdb_id'),
                    'media_type': item.get('media_type'), # 'movie' or 'tv series'
                    'source': 'imdb',
                    'poster_url': item.get('poster_url')
                })

        if not all_results:
            await temp_msg.edit_caption("No results found on TMDB or IMDb for the provided series name.")
            return

        # Store the search results in temp_admin_data
        temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
        temp_admin_data[user_id]["search_results"] = all_results
        temp_admin_data[user_id]["query"] = query
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SEARCH_RESULTS"
        temp_admin_data[user_id]["main_message_id"] = temp_msg.id

        await send_series_selection_message(client, user_id, query, all_results, temp_msg.id)

# Callback query handler
@Client.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data

    # Check if it's an admin UI callback (starts with "newui_")
    if data.startswith("newui_"):
        if user_id in ADMINS:
            async with get_admin_lock(user_id):
                await newui_callback_handler(client, callback_query)
        else:
            await callback_query.answer("You are not authorized!", show_alert=True)
        return

    # Otherwise, it's a user series callback
    if data.startswith("user_series:") or data.startswith("b:"):
        await user_series_callback_handler(client, callback_query)
        return

# User series callback handler (moved from pm_filter.py)
async def user_series_callback_handler(client: Client, query: CallbackQuery):
    data = query.data
    parts = data.split(":")
    clicked_user = query.from_user.id
    chat_id = query.message.chat.id
    message_id = query.message.id

    reply_msg = query.message.reply_to_message  
    if reply_msg and reply_msg.from_user:
        requested_user = reply_msg.from_user.id
    else:
        requested_user = user_requestor.get(f"{chat_id}•{message_id}")
    
    if chat_id < 0 and requested_user and clicked_user != requested_user:
        await query.answer("Not your request!", show_alert=True)
        return

    if data == "pages":
        await query.answer()
        return

    elif data.startswith("b:"):
        # This is the final link to fetch files
        file_link_key = data.split(":", 1)[1]
        
        # Fetch files from the episodes collection
        files_to_send, channel_id, first_msg_id, last_msg_id = await get_links_for_quality(file_link_key)

        if not files_to_send:
            await query.answer("No files found for this quality.", show_alert=True)
            return

        await query.answer("Sending files...")
        
        track_msgs = []
        for entry in files_to_send:
            try:
                copied_msg = await client.send_cached_media(
                    chat_id=query.from_user.id, 
                    file_id=entry["file_id"],
                    caption=entry.get("caption", "")
                )
                if copied_msg and temp.AUTO_DELETE_TIME and temp.AUTO_DELETE_TIME > 0:
                    track_msgs.append(copied_msg)
                await asyncio.sleep(0.5)
            except FloodWait as e:
                logger.warning(f"FloodWait for {e.value} sec")
                await asyncio.sleep(e.value)
                copied_msg = await client.send_cached_media(
                    chat_id=query.from_user.id, 
                    file_id=entry["file_id"],
                    caption=entry.get("caption", "")
                )
                if copied_msg and temp.AUTO_DELETE_TIME and temp.AUTO_DELETE_TIME > 0:
                    track_msgs.append(copied_msg)
            except Exception as e:
                logger.error(f"Error sending cached media to user {query.from_user.id}: {e}")
                # Optionally, send an error message to the user
                await client.send_message(query.from_user.id, f"Error sending file: {e}")
                
        if track_msgs:
            delete_data = await client.send_message(
                chat_id=query.from_user.id,
                text=temp.AUTO_DELETE_MSG.format(time=temp.AUTO_DELETE_TIME)
            )
            asyncio.create_task(DeleteMessage(delete_data)) # Use DeleteMessage for the auto-delete message
        return

    elif data.startswith("user_series:"):
        series_key = parts[1]
        series = get_series_name(series_key)
        if not series:
            await query.message.edit_text("Series not found or deleted.", parse_mode=enums.ParseMode.HTML)
            return

        lang_key = parts[2] if len(parts) > 2 else None
        season_key = parts[3] if len(parts) > 3 else None
        quality_key = parts[4] if len(parts) > 4 else None

        base_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n"
        )
        
        buttons = []
        current_level_data = None
        back_callback = None

        if not lang_key: # Show languages
            current_level_data = series.get("languages", {})
            for key, data_item in current_level_data.items():
                buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"user_series:{series_key}:{key}"))
            text = base_text + "\nSelect the language you need...!"
            # No back button at this level, as it's the initial series view
            
        elif not season_key: # Show seasons for selected language
            current_level_data = series.get("languages", {}).get(lang_key, {}).get("seasons", {})
            lang_name = series.get("languages", {}).get(lang_key, {}).get("name", "N/A")
            for key, data_item in current_level_data.items():
                buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"user_series:{series_key}:{lang_key}:{key}"))
            text = base_text + f"○ **Language:** `{lang_name}`\n\nSelect the season you need...!"
            back_callback = f"user_series:{series_key}"

        elif not quality_key: # Show qualities for selected season
            current_level_data = series.get("languages", {}).get(lang_key, {}).get("seasons", {}).get(season_key, {}).get("qualities", {})
            lang_name = series.get("languages", {}).get(lang_key, {}).get("name", "N/A")
            season_name = series.get("languages", {}).get(lang_key, {}).get("seasons", {}).get(season_key, {}).get("name", "N/A")
            for key, data_item in current_level_data.items():
                # The file_link_key is stored in crazy_db, but the actual files are in episodes collection
                file_link_key = data_item.get('file_link_key')
                if file_link_key:
                    buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"b:{file_link_key}"))
            text = base_text + f"○ **Language:** `{lang_name}`\n○ **Season:** `{season_name}`\n\nSelect the quality you need...!"
            back_callback = f"user_series:{series_key}:{lang_key}"
        
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        if back_callback:
            buttons_chunked.append([InlineKeyboardButton("Back", callback_data=back_callback)])
        
        reply_markup = InlineKeyboardMarkup(buttons_chunked)

        try:
            await query.message.edit_text(
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error editing message in user_series callback: {e}")
            await query.answer("An error occurred. Please try again.", show_alert=True)

# Admin UI callback handler
async def newui_callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data.split(":")
    action = data[0].replace("newui_", "")
    
    if user_id not in temp_admin_data:
        await callback_query.answer("Session expired. Please start again with /newseriesui.", show_alert=True)
        return
    
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    
    if action == "search_again":
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
    
    elif action in ["tmdb_select", "imdb_select"]:
        unique_id = data[1]
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
        
        # Check if series already exists, if so, load it
        existing_series = get_series_by_key(series_key)
        if existing_series:
            series_data = existing_series
            await callback_query.answer("Series already exists. Loading for editing.", show_alert=True)
        else:
            # Create new series data
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
        
        # Re-fetch series_data to ensure it's the latest from DB
        series_data = get_series_by_key(series_key)
        if not series_data:
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption="Failed to retrieve series data after initial setup. Please try again."
            )
            return
        
        # Download and upload poster to LOG_CHANNEL, then update DB
        poster_file_id = await download_and_upload_poster(client, poster_url=movie_details.get('poster_url') or movie_details.get('poster'))
        if poster_file_id:
            update_series_field(series_key, "poster_file_id", poster_file_id)
            series_data["poster_file_id"] = poster_file_id
        else:
            await client.send_message(user_id, "Failed to download/upload poster. Using placeholder.")
            update_series_field(series_key, "poster_file_id", NO_POSTER_FOUND_IMG)
            series_data["poster_file_id"] = NO_POSTER_FOUND_IMG
        
        # Update main message with series details and management buttons
        new_main_msg_id = await send_series_details_message(client, user_id, series_data, main_message_id)
        if new_main_msg_id:
            temp_admin_data[user_id]["main_message_id"] = new_main_msg_id
            temp_admin_data[user_id]["current_series_key"] = series_key
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SERIES_DETAILS"
    
    # ... (rest of the callback actions from the original admin_ui.py)

# ... (rest of the functions from the original admin_ui.py)

# Process input functions (handle_admin_text_input, handle_admin_media_input, etc.)
# ... (rest of the functions from the original admin_ui.pyimport asyncio
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
from typing import Dict, Any

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, 
    InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from imdb import Cinemagoer
from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, TMDB_API_KEY, LOG_CHANNEL, DB_CHANNEL, RAW_DB_CHANNEL, SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG
from database.crazy_db import (
    add_series, get_series_by_key, update_series_field, add_or_update_language,
    get_languages, delete_language, add_or_update_season, get_seasons, delete_season,
    add_or_update_quality, get_qualities, get_quality_link, delete_quality,
    get_poster_file_id, update_poster_file_id, publish_series, get_series_name, get_poster_manuel, get_links_for_quality
)
from database.gfilters_mdb import (
    find_gfilter,
    get_gfilters
)
from utils import (
    get_message_id, get_messages_in_range, delete_messages_from_user_chat, 
    get_poster, find_most_similar_title, temp
)
from fuzzywuzzy import fuzz
from pyrogram.errors import MessageIdInvalid, FloodWait

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Temporary storage for multi-step UI interactions
temp_admin_data = {}

# Dictionary to hold locks for admin users
admin_locks: Dict[int, asyncio.RLock] = {}

# Dictionary to track user requests for series selection
user_requestor = {}

imdb = Cinemagoer()

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

# Helper to get or create a lock for an admin user
def get_admin_lock(user_id: int) -> asyncio.RLock:
    if user_id not in admin_locks:
        admin_locks[user_id] = asyncio.RLock()
    return admin_locks[user_id]

# Helper function to delete a message after a delay
async def DeleteMessage(msg):
    await asyncio.sleep(600)
    try:
        await msg.delete()
    except Exception as e:
        logger.warning(f"Failed to delete message: {e}")

# Helper to chunk buttons for inline keyboard
def chunk_buttons(buttons, chunk_size=2):
    return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]

# Global filter function (moved from pm_filter.py)
async def global_filters(client: Client, message: Message, text=False):
    group_id = message.chat.id
    name = text or message.text 
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id 
    keywords = await get_gfilters("gfilters")
    for keyword in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[\W])" + re.escape(keyword) + r"( |$|[\W])"
        if re.search(pattern, name, flags=re.IGNORECASE):
            reply_text, btn, alert, fileid = await find_gfilter("gfilters", keyword)
            if reply_text:
                reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")
            
            try:
                if fileid == "None":
                    if btn == "[]":
                        piroxrk = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_to_message_id=reply_id
                        )
                    else:
                        button = eval(btn)
                        piroxrk = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_markup=InlineKeyboardMarkup(button),
                            reply_to_message_id=reply_id
                        )
                elif btn == "[]":
                    piroxrk = await client.send_cached_media(
                        group_id,
                        fileid,
                        caption=reply_text or "",
                        reply_to_message_id=reply_id
                    )
                else:
                    button = eval(btn)
                    piroxrk = await message.reply_cached_media(
                        fileid,
                        caption=reply_text or "",
                        reply_markup=InlineKeyboardMarkup(button),
                        reply_to_message_id=reply_id
                    )
            except Exception as e:
                logger.exception(e)
            break
    else:
        return False

# Series filter function (moved from pm_filter.py)
async def series_filter(client: Client, message: Message):
    text = message.text.strip()
    series_infos = get_series()
    series_keys = [series['key'] for series in series_infos]
    series_names = [series['title'] for series in series_infos]

    series_key = None
    
    # Try exact match by key first
    if text.lower().replace(" ", "").replace("-", "") in series_keys:
        series_key = text.lower().replace(" ", "").replace("-", "")
    else:
        # Try exact match by title
        for s_info in series_infos:
            if s_info['title'].lower() == text.lower():
                series_key = s_info['key']
                break
        
        if not series_key:
            # Try close matches for titles
            close_matches = find_close_matches(text, series_names)
            if not close_matches:
                # Fallback to starts-with if no close matches
                first_word = text.split()[0]
                close_matches = [name for name in series_names if name.lower().startswith(first_word.lower())]
            
            if close_matches:
                buttons = []
                for match in close_matches:
                    s_info = next((s for s in series_infos if s['title'] == match), None)
                    if s_info:
                        buttons.append(InlineKeyboardButton(match, callback_data=f"user_series:{s_info['key']}"))
                
                if buttons:
                    buttons_chunked = chunk_buttons(buttons, chunk_size=1)
                    reply_markup = InlineKeyboardMarkup(buttons_chunked)
                    etho = await message.reply_photo(photo=random.choice(SPELL_CHECK_IMAGE), caption="<b>Choose Your Series:</b>", reply_markup=reply_markup)
                    reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else None
                    user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
                    asyncio.create_task(DeleteMessage(etho))
                    return

    if series_key:
        series = get_series_name(series_key)
        if not series:
            return

        languages = series.get("languages", {})
        
        reply_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n\n"
            "Select the language you need...!"
        )
        poster_url = get_movie_poster(series_key)
        
        buttons = []
        for lang_key, lang_data in languages.items():
            buttons.append(InlineKeyboardButton(lang_data['name'], callback_data=f"user_series:{series_key}:{lang_key}"))
        
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        reply_markup = InlineKeyboardMarkup(buttons_chunked)
        
        try:
            if poster_url:
                etho = await message.reply_photo(photo=poster_url, caption=reply_text, reply_markup=reply_markup)
            else:
                etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG[0], caption=reply_text, reply_markup=reply_markup)
            
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
            asyncio.create_task(DeleteMessage(etho))
            logger.info("Series filter message sent.")
        except pyrogram.errors.MediaEmpty:
            logger.warning(f"MediaEmpty error for poster: {poster_url}. Using placeholder.")
            etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG[0], caption=reply_text, reply_markup=reply_markup)
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
            asyncio.create_task(DeleteMessage(etho))
        except Exception as e:
            logger.error(f"Error sending series filter message: {e}")

def find_close_matches(query, possibilities, n=3, cutoff=0.6):
    import difflib
    return difflib.get_close_matches(query, possibilities, n, cutoff)

def get_movie_poster(series_key):
    poster_url = get_poster_manuel(series_key)
    if not poster_url:
        series = get_series_name(series_key)
        if series:
            poster_url = series.get('poster_url') # Get from the main series data
    return poster_url or NO_POSTER_FOUND_IMG[0]

# TMDB and other helper functions from the original admin_ui.py
async def get_tmdb_info(query, bulk=False, tmdb_id=None, media_type=None):
    """Fetches movie/TV show information from TMDB."""
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {TMDB_API_KEY}"
    }

    try:
        if tmdb_id:
            # Fetch details for a specific TMDB ID
            url = f"{TMDB_BASE_URL}/{media_type}/{tmdb_id}"
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
            
            return {
                'title': title,
                'year': year,
                'genres': ', '.join(genres) if genres else 'N/A',
                'rating': data.get('vote_average', 'N/A'),
                'poster_url': poster_url,
                'tmdb_id': data.get('id'),
                'media_type': media_type,
                'url': f'https://www.themoviedb.org/{media_type}/{data.get("id")}'
            }
        else:
            # Search mode
            search_results = []
            
            # Search TV shows
            url_tv = f"{TMDB_BASE_URL}/search/tv"
            response_tv = requests.get(url_tv, headers=headers, params={"query": query})
            response_tv.raise_for_status()
            data_tv = response_tv.json()
            for item in data_tv.get('results', [])[:5]: # Limit to 5 results
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
            response_movie = requests.get(url_movie, headers=headers, params={"query": query})
            response_movie.raise_for_status()
            data_movie = response_movie.json()
            for item in data_movie.get('results', [])[:5]: # Limit to 5 results
                if item.get('title'):
                    search_results.append({
                        'title': item.get('title'),
                        'year': item.get('release_date', '').split('-')[0] if item.get('release_date') else 'N/A',
                        'tmdb_id': item.get('id'),
                        'media_type': 'movie',
                        'source': 'tmdb'
                    })
            
            return search_results[:10] # Return max 10 results total (TV first, then movies)

    except requests.exceptions.RequestException as e:
        logger.error(f"TMDB API error: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred with TMDB: {e}")
        return None

async def download_and_upload_poster(client: Client, poster_url: str = None, message: Message = None):
    """Downloads a poster (from URL or user-provided photo), uploads it to LOG_CHANNEL, and returns its file_id."""
    temp_dir = os.path.join(TMP_DOWNLOAD_DIRECTORY, str(uuid.uuid4()))
    os.makedirs(temp_dir, exist_ok=True)
    download_path = None
    file_id = None

    try:
        if poster_url:
            # Download from URL
            response = requests.get(poster_url, stream=True)
            response.raise_for_status()
            download_path = os.path.join(temp_dir, "poster.jpg")
            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        elif message and message.photo and message.photo.file_id:
            # Use user-provided photo
            download_path = await client.download_media(message.photo.file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        elif message and message.video and message.video.thumbs and message.video.thumbs[0].file_id:
            # Use user-provided video thumbnail
            download_path = await client.download_media(message.video.thumbs[0].file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        else:
            logger.warning("No valid poster source (URL, photo, or video thumbnail) provided.")
            return None

        if download_path:
            # Upload to LOG_CHANNEL
            sent_msg = await client.send_photo(LOG_CHANNEL, photo=download_path, caption="Series Poster")
            file_id = sent_msg.photo.file_id
            try:
                await sent_msg.delete() # Delete from log channel to keep it clean
            except Exception as e:
                logger.warning(f"Could not delete temporary poster message from LOG_CHANNEL: {e}")
    except Exception as e:
        logger.error(f"Error downloading/uploading poster: {e}")
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
    return file_id

# Message handlers
@Client.on_message(filters.text & (filters.private | filters.group))
async def handle_message(client: Client, message: Message):
    user_id = message.from_user.id
    
    # If the message is in a group, apply global and series filters
    if message.chat.type != enums.ChatType.PRIVATE:
        glob = await global_filters(client, message)
        if glob == False:
            await series_filter(client, message)
        return
    
    # For private chats
    if user_id in ADMINS:
        # Check if the admin has an active state
        if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
            # Acquire the lock for this admin
            async with get_admin_lock(user_id):
                await handle_admin_text_input(client, message)
            return
    
    # For non-admins or admins without active state, apply global and series filters
    glob = await global_filters(client, message)
    if glob == False:
        await series_filter(client, message)

@Client.on_message((filters.photo | filters.video | filters.document) & (filters.private | filters.group))
async def handle_media_message(client: Client, message: Message):
    user_id = message.from_user.id
    
    if message.chat.type != enums.ChatType.PRIVATE:
        # In groups, we don't process media for admin UI, so we return
        return
    
    if user_id in ADMINS:
        if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
            async with get_admin_lock(user_id):
                await handle_admin_media_input(client, message)
            return
    
    # For non-admins or admins without active state, we don't do anything with media in private
    return

# Command handler for the new admin UI
@Client.on_message(filters.command('newseriesui') & filters.user(ADMINS))
async def new_series_ui_command(client: Client, message: Message):
    user_id = message.from_user.id
    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None

    if not query:
        await message.reply("Usage: `/newseriesui <series_title>`")
        return

    # Acquire the lock for this admin
    async with get_admin_lock(user_id):
        temp_msg = await message.reply_photo(
            photo=NO_POSTER_FOUND_IMG, # Temporary placeholder
            caption="Searching TMDB and IMDb, please wait..."
        )
        
        tmdb_results = await get_tmdb_info(query, bulk=True)
        imdb_results = await get_poster(query, bulk=True) # Use get_poster for IMDb search

        all_results = []
        if tmdb_results:
            for item in tmdb_results:
                item['source'] = 'tmdb'
                all_results.append(item)
        if imdb_results:
            for item in imdb_results:
                # Ensure IMDb results have consistent keys
                all_results.append({
                    'title': item.get('title'),
                    'year': item.get('year'),
                    'imdb_id': item.get('imdb_id'),
                    'media_type': item.get('media_type'), # 'movie' or 'tv series'
                    'source': 'imdb',
                    'poster_url': item.get('poster_url')
                })

        if not all_results:
            await temp_msg.edit_caption("No results found on TMDB or IMDb for the provided series name.")
            return

        # Store the search results in temp_admin_data
        temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
        temp_admin_data[user_id]["search_results"] = all_results
        temp_admin_data[user_id]["query"] = query
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SEARCH_RESULTS"
        temp_admin_data[user_id]["main_message_id"] = temp_msg.id

        await send_series_selection_message(client, user_id, query, all_results, temp_msg.id)

# Callback query handler
@Client.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data

    # Check if it's an admin UI callback (starts with "newui_")
    if data.startswith("newui_"):
        if user_id in ADMINS:
            async with get_admin_lock(user_id):
                await newui_callback_handler(client, callback_query)
        else:
            await callback_query.answer("You are not authorized!", show_alert=True)
        return

    # Otherwise, it's a user series callback
    if data.startswith("user_series:") or data.startswith("b:"):
        await user_series_callback_handler(client, callback_query)
        return

# User series callback handler (moved from pm_filter.py)
async def user_series_callback_handler(client: Client, query: CallbackQuery):
    data = query.data
    parts = data.split(":")
    clicked_user = query.from_user.id
    chat_id = query.message.chat.id
    message_id = query.message.id

    reply_msg = query.message.reply_to_message  
    if reply_msg and reply_msg.from_user:
        requested_user = reply_msg.from_user.id
    else:
        requested_user = user_requestor.get(f"{chat_id}•{message_id}")
    
    if chat_id < 0 and requested_user and clicked_user != requested_user:
        await query.answer("Not your request!", show_alert=True)
        return

    if data == "pages":
        await query.answer()
        return

    elif data.startswith("b:"):
        # This is the final link to fetch files
        file_link_key = data.split(":", 1)[1]
        
        # Fetch files from the episodes collection
        files_to_send, channel_id, first_msg_id, last_msg_id = await get_links_for_quality(file_link_key)

        if not files_to_send:
            await query.answer("No files found for this quality.", show_alert=True)
            return

        await query.answer("Sending files...")
        
        track_msgs = []
        for entry in files_to_send:
            try:
                copied_msg = await client.send_cached_media(
                    chat_id=query.from_user.id, 
                    file_id=entry["file_id"],
                    caption=entry.get("caption", "")
                )
                if copied_msg and temp.AUTO_DELETE_TIME and temp.AUTO_DELETE_TIME > 0:
                    track_msgs.append(copied_msg)
                await asyncio.sleep(0.5)
            except FloodWait as e:
                logger.warning(f"FloodWait for {e.value} sec")
                await asyncio.sleep(e.value)
                copied_msg = await client.send_cached_media(
                    chat_id=query.from_user.id, 
                    file_id=entry["file_id"],
                    caption=entry.get("caption", "")
                )
                if copied_msg and temp.AUTO_DELETE_TIME and temp.AUTO_DELETE_TIME > 0:
                    track_msgs.append(copied_msg)
            except Exception as e:
                logger.error(f"Error sending cached media to user {query.from_user.id}: {e}")
                # Optionally, send an error message to the user
                await client.send_message(query.from_user.id, f"Error sending file: {e}")
                
        if track_msgs:
            delete_data = await client.send_message(
                chat_id=query.from_user.id,
                text=temp.AUTO_DELETE_MSG.format(time=temp.AUTO_DELETE_TIME)
            )
            asyncio.create_task(DeleteMessage(delete_data)) # Use DeleteMessage for the auto-delete message
        return

    elif data.startswith("user_series:"):
        series_key = parts[1]
        series = get_series_name(series_key)
        if not series:
            await query.message.edit_text("Series not found or deleted.", parse_mode=enums.ParseMode.HTML)
            return

        lang_key = parts[2] if len(parts) > 2 else None
        season_key = parts[3] if len(parts) > 3 else None
        quality_key = parts[4] if len(parts) > 4 else None

        base_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n"
        )
        
        buttons = []
        current_level_data = None
        back_callback = None

        if not lang_key: # Show languages
            current_level_data = series.get("languages", {})
            for key, data_item in current_level_data.items():
                buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"user_series:{series_key}:{key}"))
            text = base_text + "\nSelect the language you need...!"
            # No back button at this level, as it's the initial series view
            
        elif not season_key: # Show seasons for selected language
            current_level_data = series.get("languages", {}).get(lang_key, {}).get("seasons", {})
            lang_name = series.get("languages", {}).get(lang_key, {}).get("name", "N/A")
            for key, data_item in current_level_data.items():
                buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"user_series:{series_key}:{lang_key}:{key}"))
            text = base_text + f"○ **Language:** `{lang_name}`\n\nSelect the season you need...!"
            back_callback = f"user_series:{series_key}"

        elif not quality_key: # Show qualities for selected season
            current_level_data = series.get("languages", {}).get(lang_key, {}).get("seasons", {}).get(season_key, {}).get("qualities", {})
            lang_name = series.get("languages", {}).get(lang_key, {}).get("name", "N/A")
            season_name = series.get("languages", {}).get(lang_key, {}).get("seasons", {}).get(season_key, {}).get("name", "N/A")
            for key, data_item in current_level_data.items():
                # The file_link_key is stored in crazy_db, but the actual files are in episodes collection
                file_link_key = data_item.get('file_link_key')
                if file_link_key:
                    buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"b:{file_link_key}"))
            text = base_text + f"○ **Language:** `{lang_name}`\n○ **Season:** `{season_name}`\n\nSelect the quality you need...!"
            back_callback = f"user_series:{series_key}:{lang_key}"
        
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        if back_callback:
            buttons_chunked.append([InlineKeyboardButton("Back", callback_data=back_callback)])
        
        reply_markup = InlineKeyboardMarkup(buttons_chunked)

        try:
            await query.message.edit_text(
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error editing message in user_series callback: {e}")
            await query.answer("An error occurred. Please try again.", show_alert=True)

# Admin UI callback handler
async def newui_callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data.split(":")
    action = data[0].replace("newui_", "")
    
    if user_id not in temp_admin_data:
        await callback_query.answer("Session expired. Please start again with /newseriesui.", show_alert=True)
        return
    
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    
    if action == "search_again":
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
    
    elif action in ["tmdb_select", "imdb_select"]:
        unique_id = data[1]
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
        
        # Check if series already exists, if so, load it
        existing_series = get_series_by_key(series_key)
        if existing_series:
            series_data = existing_series
            await callback_query.answer("Series already exists. Loading for editing.", show_alert=True)
        else:
            # Create new series data
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
        
        # Re-fetch series_data to ensure it's the latest from DB
        series_data = get_series_by_key(series_key)
        if not series_data:
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption="Failed to retrieve series data after initial setup. Please try again."
            )
            return
        
        # Download and upload poster to LOG_CHANNEL, then update DB
        poster_file_id = await download_and_upload_poster(client, poster_url=movie_details.get('poster_url') or movie_details.get('poster'))
        if poster_file_id:
            update_series_field(series_key, "poster_file_id", poster_file_id)
            series_data["poster_file_id"] = poster_file_id
        else:
            await client.send_message(user_id, "Failed to download/upload poster. Using placeholder.")
            update_series_field(series_key, "poster_file_id", NO_POSTER_FOUND_IMG)
            series_data["poster_file_id"] = NO_POSTER_FOUND_IMG
        
        # Update main message with series details and management buttons
        new_main_msg_id = await send_series_details_message(client, user_id, series_data, main_message_id)
        if new_main_msg_id:
            temp_admin_data[user_id]["main_message_id"] = new_main_msg_id
            temp_admin_data[user_id]["current_series_key"] = series_key
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SERIES_DETAILS"
    
    # ... (rest of the callback actions from the original admin_ui.py)

# ... (rest of the functions from the original admin_ui.py)

# Process input functions (handle_admin_text_input, handle_admin_media_input, etc.)
# ... (rest of the functions from the original admin_ui.pimport asyncio
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
from typing import Dict, Any

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, 
    InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from imdb import Cinemagoer
from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, TMDB_API_KEY, LOG_CHANNEL, DB_CHANNEL, RAW_DB_CHANNEL, SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG
from database.crazy_db import (
    add_series, get_series_by_key, update_series_field, add_or_update_language,
    get_languages, delete_language, add_or_update_season, get_seasons, delete_season,
    add_or_update_quality, get_qualities, get_quality_link, delete_quality,
    get_poster_file_id, update_poster_file_id, publish_series, get_series_name, get_poster_manuel, get_links_for_quality
)
from database.gfilters_mdb import (
    find_gfilter,
    get_gfilters
)
from utils import (
    get_message_id, get_messages_in_range, delete_messages_from_user_chat, 
    get_poster, find_most_similar_title, temp
)
from fuzzywuzzy import fuzz
from pyrogram.errors import MessageIdInvalid, FloodWait

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Temporary storage for multi-step UI interactions
temp_admin_data = {}

# Dictionary to hold locks for admin users
admin_locks: Dict[int, asyncio.RLock] = {}

# Dictionary to track user requests for series selection
user_requestor = {}

imdb = Cinemagoer()

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

# Helper to get or create a lock for an admin user
def get_admin_lock(user_id: int) -> asyncio.RLock:
    if user_id not in admin_locks:
        admin_locks[user_id] = asyncio.RLock()
    return admin_locks[user_id]

# Helper function to delete a message after a delay
async def DeleteMessage(msg):
    await asyncio.sleep(600)
    try:
        await msg.delete()
    except Exception as e:
        logger.warning(f"Failed to delete message: {e}")

# Helper to chunk buttons for inline keyboard
def chunk_buttons(buttons, chunk_size=2):
    return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]

# Global filter function (moved from pm_filter.py)
async def global_filters(client: Client, message: Message, text=False):
    group_id = message.chat.id
    name = text or message.text 
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id 
    keywords = await get_gfilters("gfilters")
    for keyword in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[\W])" + re.escape(keyword) + r"( |$|[\W])"
        if re.search(pattern, name, flags=re.IGNORECASE):
            reply_text, btn, alert, fileid = await find_gfilter("gfilters", keyword)
            if reply_text:
                reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")
            
            try:
                if fileid == "None":
                    if btn == "[]":
                        piroxrk = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_to_message_id=reply_id
                        )
                    else:
                        button = eval(btn)
                        piroxrk = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_markup=InlineKeyboardMarkup(button),
                            reply_to_message_id=reply_id
                        )
                elif btn == "[]":
                    piroxrk = await client.send_cached_media(
                        group_id,
                        fileid,
                        caption=reply_text or "",
                        reply_to_message_id=reply_id
                    )
                else:
                    button = eval(btn)
                    piroxrk = await message.reply_cached_media(
                        fileid,
                        caption=reply_text or "",
                        reply_markup=InlineKeyboardMarkup(button),
                        reply_to_message_id=reply_id
                    )
            except Exception as e:
                logger.exception(e)
            break
    else:
        return False

# Series filter function (moved from pm_filter.py)
async def series_filter(client: Client, message: Message):
    text = message.text.strip()
    series_infos = get_series()
    series_keys = [series['key'] for series in series_infos]
    series_names = [series['title'] for series in series_infos]

    series_key = None
    
    # Try exact match by key first
    if text.lower().replace(" ", "").replace("-", "") in series_keys:
        series_key = text.lower().replace(" ", "").replace("-", "")
    else:
        # Try exact match by title
        for s_info in series_infos:
            if s_info['title'].lower() == text.lower():
                series_key = s_info['key']
                break
        
        if not series_key:
            # Try close matches for titles
            close_matches = find_close_matches(text, series_names)
            if not close_matches:
                # Fallback to starts-with if no close matches
                first_word = text.split()[0]
                close_matches = [name for name in series_names if name.lower().startswith(first_word.lower())]
            
            if close_matches:
                buttons = []
                for match in close_matches:
                    s_info = next((s for s in series_infos if s['title'] == match), None)
                    if s_info:
                        buttons.append(InlineKeyboardButton(match, callback_data=f"user_series:{s_info['key']}"))
                
                if buttons:
                    buttons_chunked = chunk_buttons(buttons, chunk_size=1)
                    reply_markup = InlineKeyboardMarkup(buttons_chunked)
                    etho = await message.reply_photo(photo=random.choice(SPELL_CHECK_IMAGE), caption="<b>Choose Your Series:</b>", reply_markup=reply_markup)
                    reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else None
                    user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
                    asyncio.create_task(DeleteMessage(etho))
                    return

    if series_key:
        series = get_series_name(series_key)
        if not series:
            return

        languages = series.get("languages", {})
        
        reply_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n\n"
            "Select the language you need...!"
        )
        poster_url = get_movie_poster(series_key)
        
        buttons = []
        for lang_key, lang_data in languages.items():
            buttons.append(InlineKeyboardButton(lang_data['name'], callback_data=f"user_series:{series_key}:{lang_key}"))
        
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        reply_markup = InlineKeyboardMarkup(buttons_chunked)
        
        try:
            if poster_url:
                etho = await message.reply_photo(photo=poster_url, caption=reply_text, reply_markup=reply_markup)
            else:
                etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG[0], caption=reply_text, reply_markup=reply_markup)
            
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
            asyncio.create_task(DeleteMessage(etho))
            logger.info("Series filter message sent.")
        except pyrogram.errors.MediaEmpty:
            logger.warning(f"MediaEmpty error for poster: {poster_url}. Using placeholder.")
            etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG[0], caption=reply_text, reply_markup=reply_markup)
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
            asyncio.create_task(DeleteMessage(etho))
        except Exception as e:
            logger.error(f"Error sending series filter message: {e}")

def find_close_matches(query, possibilities, n=3, cutoff=0.6):
    import difflib
    return difflib.get_close_matches(query, possibilities, n, cutoff)

def get_movie_poster(series_key):
    poster_url = get_poster_manuel(series_key)
    if not poster_url:
        series = get_series_name(series_key)
        if series:
            poster_url = series.get('poster_url') # Get from the main series data
    return poster_url or NO_POSTER_FOUND_IMG[0]

# TMDB and other helper functions from the original admin_ui.py
async def get_tmdb_info(query, bulk=False, tmdb_id=None, media_type=None):
    """Fetches movie/TV show information from TMDB."""
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {TMDB_API_KEY}"
    }

    try:
        if tmdb_id:
            # Fetch details for a specific TMDB ID
            url = f"{TMDB_BASE_URL}/{media_type}/{tmdb_id}"
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
            
            return {
                'title': title,
                'year': year,
                'genres': ', '.join(genres) if genres else 'N/A',
                'rating': data.get('vote_average', 'N/A'),
                'poster_url': poster_url,
                'tmdb_id': data.get('id'),
                'media_type': media_type,
                'url': f'https://www.themoviedb.org/{media_type}/{data.get("id")}'
            }
        else:
            # Search mode
            search_results = []
            
            # Search TV shows
            url_tv = f"{TMDB_BASE_URL}/search/tv"
            response_tv = requests.get(url_tv, headers=headers, params={"query": query})
            response_tv.raise_for_status()
            data_tv = response_tv.json()
            for item in data_tv.get('results', [])[:5]: # Limit to 5 results
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
            response_movie = requests.get(url_movie, headers=headers, params={"query": query})
            response_movie.raise_for_status()
            data_movie = response_movie.json()
            for item in data_movie.get('results', [])[:5]: # Limit to 5 results
                if item.get('title'):
                    search_results.append({
                        'title': item.get('title'),
                        'year': item.get('release_date', '').split('-')[0] if item.get('release_date') else 'N/A',
                        'tmdb_id': item.get('id'),
                        'media_type': 'movie',
                        'source': 'tmdb'
                    })
            
            return search_results[:10] # Return max 10 results total (TV first, then movies)

    except requests.exceptions.RequestException as e:
        logger.error(f"TMDB API error: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred with TMDB: {e}")
        return None

async def download_and_upload_poster(client: Client, poster_url: str = None, message: Message = None):
    """Downloads a poster (from URL or user-provided photo), uploads it to LOG_CHANNEL, and returns its file_id."""
    temp_dir = os.path.join(TMP_DOWNLOAD_DIRECTORY, str(uuid.uuid4()))
    os.makedirs(temp_dir, exist_ok=True)
    download_path = None
    file_id = None

    try:
        if poster_url:
            # Download from URL
            response = requests.get(poster_url, stream=True)
            response.raise_for_status()
            download_path = os.path.join(temp_dir, "poster.jpg")
            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        elif message and message.photo and message.photo.file_id:
            # Use user-provided photo
            download_path = await client.download_media(message.photo.file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        elif message and message.video and message.video.thumbs and message.video.thumbs[0].file_id:
            # Use user-provided video thumbnail
            download_path = await client.download_media(message.video.thumbs[0].file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        else:
            logger.warning("No valid poster source (URL, photo, or video thumbnail) provided.")
            return None

        if download_path:
            # Upload to LOG_CHANNEL
            sent_msg = await client.send_photo(LOG_CHANNEL, photo=download_path, caption="Series Poster")
            file_id = sent_msg.photo.file_id
            try:
                await sent_msg.delete() # Delete from log channel to keep it clean
            except Exception as e:
                logger.warning(f"Could not delete temporary poster message from LOG_CHANNEL: {e}")
    except Exception as e:
        logger.error(f"Error downloading/uploading poster: {e}")
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
    return file_id

# Message handlers
@Client.on_message(filters.text & (filters.private | filters.group))
async def handle_message(client: Client, message: Message):
    user_id = message.from_user.id
    
    # If the message is in a group, apply global and series filters
    if message.chat.type != enums.ChatType.PRIVATE:
        glob = await global_filters(client, message)
        if glob == False:
            await series_filter(client, message)
        return
    
    # For private chats
    if user_id in ADMINS:
        # Check if the admin has an active state
        if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
            # Acquire the lock for this admin
            async with get_admin_lock(user_id):
                await handle_admin_text_input(client, message)
            return
    
    # For non-admins or admins without active state, apply global and series filters
    glob = await global_filters(client, message)
    if glob == False:
        await series_filter(client, message)

@Client.on_message((filters.photo | filters.video | filters.document) & (filters.private | filters.group))
async def handle_media_message(client: Client, message: Message):
    user_id = message.from_user.id
    
    if message.chat.type != enums.ChatType.PRIVATE:
        # In groups, we don't process media for admin UI, so we return
        return
    
    if user_id in ADMINS:
        if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
            async with get_admin_lock(user_id):
                await handle_admin_media_input(client, message)
            return
    
    # For non-admins or admins without active state, we don't do anything with media in private
    return

# Command handler for the new admin UI
@Client.on_message(filters.command('newseriesui') & filters.user(ADMINS))
async def new_series_ui_command(client: Client, message: Message):
    user_id = message.from_user.id
    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None

    if not query:
        await message.reply("Usage: `/newseriesui <series_title>`")
        return

    # Acquire the lock for this admin
    async with get_admin_lock(user_id):
        temp_msg = await message.reply_photo(
            photo=NO_POSTER_FOUND_IMG, # Temporary placeholder
            caption="Searching TMDB and IMDb, please wait..."
        )
        
        tmdb_results = await get_tmdb_info(query, bulk=True)
        imdb_results = await get_poster(query, bulk=True) # Use get_poster for IMDb search

        all_results = []
        if tmdb_results:
            for item in tmdb_results:
                item['source'] = 'tmdb'
                all_results.append(item)
        if imdb_results:
            for item in imdb_results:
                # Ensure IMDb results have consistent keys
                all_results.append({
                    'title': item.get('title'),
                    'year': item.get('year'),
                    'imdb_id': item.get('imdb_id'),
                    'media_type': item.get('media_type'), # 'movie' or 'tv series'
                    'source': 'imdb',
                    'poster_url': item.get('poster_url')
                })

        if not all_results:
            await temp_msg.edit_caption("No results found on TMDB or IMDb for the provided series name.")
            return

        # Store the search results in temp_admin_data
        temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
        temp_admin_data[user_id]["search_results"] = all_results
        temp_admin_data[user_id]["query"] = query
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SEARCH_RESULTS"
        temp_admin_data[user_id]["main_message_id"] = temp_msg.id

        await send_series_selection_message(client, user_id, query, all_results, temp_msg.id)

# Callback query handler
@Client.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data

    # Check if it's an admin UI callback (starts with "newui_")
    if data.startswith("newui_"):
        if user_id in ADMINS:
            async with get_admin_lock(user_id):
                await newui_callback_handler(client, callback_query)
        else:
            await callback_query.answer("You are not authorized!", show_alert=True)
        return

    # Otherwise, it's a user series callback
    if data.startswith("user_series:") or data.startswith("b:"):
        await user_series_callback_handler(client, callback_query)
        return

# User series callback handler (moved from pm_filter.py)
async def user_series_callback_handler(client: Client, query: CallbackQuery):
    data = query.data
    parts = data.split(":")
    clicked_user = query.from_user.id
    chat_id = query.message.chat.id
    message_id = query.message.id

    reply_msg = query.message.reply_to_message  
    if reply_msg and reply_msg.from_user:
        requested_user = reply_msg.from_user.id
    else:
        requested_user = user_requestor.get(f"{chat_id}•{message_id}")
    
    if chat_id < 0 and requested_user and clicked_user != requested_user:
        await query.answer("Not your request!", show_alert=True)
        return

    if data == "pages":
        await query.answer()
        return

    elif data.startswith("b:"):
        # This is the final link to fetch files
        file_link_key = data.split(":", 1)[1]
        
        # Fetch files from the episodes collection
        files_to_send, channel_id, first_msg_id, last_msg_id = await get_links_for_quality(file_link_key)

        if not files_to_send:
            await query.answer("No files found for this quality.", show_alert=True)
            return

        await query.answer("Sending files...")
        
        track_msgs = []
        for entry in files_to_send:
            try:
                copied_msg = await client.send_cached_media(
                    chat_id=query.from_user.id, 
                    file_id=entry["file_id"],
                    caption=entry.get("caption", "")
                )
                if copied_msg and temp.AUTO_DELETE_TIME and temp.AUTO_DELETE_TIME > 0:
                    track_msgs.append(copied_msg)
                await asyncio.sleep(0.5)
            except FloodWait as e:
                logger.warning(f"FloodWait for {e.value} sec")
                await asyncio.sleep(e.value)
                copied_msg = await client.send_cached_media(
                    chat_id=query.from_user.id, 
                    file_id=entry["file_id"],
                    caption=entry.get("caption", "")
                )
                if copied_msg and temp.AUTO_DELETE_TIME and temp.AUTO_DELETE_TIME > 0:
                    track_msgs.append(copied_msg)
            except Exception as e:
                logger.error(f"Error sending cached media to user {query.from_user.id}: {e}")
                # Optionally, send an error message to the user
                await client.send_message(query.from_user.id, f"Error sending file: {e}")
                
        if track_msgs:
            delete_data = await client.send_message(
                chat_id=query.from_user.id,
                text=temp.AUTO_DELETE_MSG.format(time=temp.AUTO_DELETE_TIME)
            )
            asyncio.create_task(DeleteMessage(delete_data)) # Use DeleteMessage for the auto-delete message
        return

    elif data.startswith("user_series:"):
        series_key = parts[1]
        series = get_series_name(series_key)
        if not series:
            await query.message.edit_text("Series not found or deleted.", parse_mode=enums.ParseMode.HTML)
            return

        lang_key = parts[2] if len(parts) > 2 else None
        season_key = parts[3] if len(parts) > 3 else None
        quality_key = parts[4] if len(parts) > 4 else None

        base_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n"
        )
        
        buttons = []
        current_level_data = None
        back_callback = None

        if not lang_key: # Show languages
            current_level_data = series.get("languages", {})
            for key, data_item in current_level_data.items():
                buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"user_series:{series_key}:{key}"))
            text = base_text + "\nSelect the language you need...!"
            # No back button at this level, as it's the initial series view
            
        elif not season_key: # Show seasons for selected language
            current_level_data = series.get("languages", {}).get(lang_key, {}).get("seasons", {})
            lang_name = series.get("languages", {}).get(lang_key, {}).get("name", "N/A")
            for key, data_item in current_level_data.items():
                buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"user_series:{series_key}:{lang_key}:{key}"))
            text = base_text + f"○ **Language:** `{lang_name}`\n\nSelect the season you need...!"
            back_callback = f"user_series:{series_key}"

        elif not quality_key: # Show qualities for selected season
            current_level_data = series.get("languages", {}).get(lang_key, {}).get("seasons", {}).get(season_key, {}).get("qualities", {})
            lang_name = series.get("languages", {}).get(lang_key, {}).get("name", "N/A")
            season_name = series.get("languages", {}).get(lang_key, {}).get("seasons", {}).get(season_key, {}).get("name", "N/A")
            for key, data_item in current_level_data.items():
                # The file_link_key is stored in crazy_db, but the actual files are in episodes collection
                file_link_key = data_item.get('file_link_key')
                if file_link_key:
                    buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"b:{file_link_key}"))
            text = base_text + f"○ **Language:** `{lang_name}`\n○ **Season:** `{season_name}`\n\nSelect the quality you need...!"
            back_callback = f"user_series:{series_key}:{lang_key}"
        
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        if back_callback:
            buttons_chunked.append([InlineKeyboardButton("Back", callback_data=back_callback)])
        
        reply_markup = InlineKeyboardMarkup(buttons_chunked)

        try:
            await query.message.edit_text(
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error editing message in user_series callback: {e}")
            await query.answer("An error occurred. Please try again.", show_alert=True)

# Admin UI callback handler
async def newui_callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data.split(":")
    action = data[0].replace("newui_", "")
    
    if user_id not in temp_admin_data:
        await callback_query.answer("Session expired. Please start again with /newseriesui.", show_alert=True)
        return
    
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    
    if action == "search_again":
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
    
    elif action in ["tmdb_select", "imdb_select"]:
        unique_id = data[1]
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
        
        # Check if series already exists, if so, load it
        existing_series = get_series_by_key(series_key)
        if existing_series:
            series_data = existing_series
            await callback_query.answer("Series already exists. Loading for editing.", show_alert=True)
        else:
            # Create new series data
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
        
        # Re-fetch series_data to ensure it's the latest from DB
        series_data = get_series_by_key(series_key)
        if not series_data:
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption="Failed to retrieve series data after initial setup. Please try again."
            )
            return
        
        # Download and upload poster to LOG_CHANNEL, then update DB
        poster_file_id = await download_and_upload_poster(client, poster_url=movie_details.get('poster_url') or movie_details.get('poster'))
        if poster_file_id:
            update_series_field(series_key, "poster_file_id", poster_file_id)
            series_data["poster_file_id"] = poster_file_id
        else:
            await client.send_message(user_id, "Failed to download/upload poster. Using placeholder.")
            update_series_field(series_key, "poster_file_id", NO_POSTER_FOUND_IMG)
            series_data["poster_file_id"] = NO_POSTER_FOUND_IMG
        
        # Update main message with series details and management buttons
        new_main_msg_id = await send_series_details_message(client, user_id, series_data, main_message_id)
        if new_main_msg_id:
            temp_admin_data[user_id]["main_message_id"] = new_main_msg_id
            temp_admin_data[user_id]["current_series_key"] = series_key
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SERIES_DETAILS"
    
    # ... (rest of the callback actions from the original admin_ui.py)

# ... (rest of the functions from the original admin_ui.py)

# Process input functions (handle_admin_text_input, handle_admin_media_input, etc.)
# ... (rest of the functions from the original admin_ui.import asyncio
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
from typing import Dict, Any

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, 
    InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from imdb import Cinemagoer
from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, TMDB_API_KEY, LOG_CHANNEL, DB_CHANNEL, RAW_DB_CHANNEL, SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG
from database.crazy_db import (
    add_series, get_series_by_key, update_series_field, add_or_update_language,
    get_languages, delete_language, add_or_update_season, get_seasons, delete_season,
    add_or_update_quality, get_qualities, get_quality_link, delete_quality,
    get_poster_file_id, update_poster_file_id, publish_series, get_series_name, get_poster_manuel, get_links_for_quality
)
from database.gfilters_mdb import (
    find_gfilter,
    get_gfilters
)
from utils import (
    get_message_id, get_messages_in_range, delete_messages_from_user_chat, 
    get_poster, find_most_similar_title, temp
)
from fuzzywuzzy import fuzz
from pyrogram.errors import MessageIdInvalid, FloodWait

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Temporary storage for multi-step UI interactions
temp_admin_data = {}

# Dictionary to hold locks for admin users
admin_locks: Dict[int, asyncio.RLock] = {}

# Dictionary to track user requests for series selection
user_requestor = {}

imdb = Cinemagoer()

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

# Helper to get or create a lock for an admin user
def get_admin_lock(user_id: int) -> asyncio.RLock:
    if user_id not in admin_locks:
        admin_locks[user_id] = asyncio.RLock()
    return admin_locks[user_id]

# Helper function to delete a message after a delay
async def DeleteMessage(msg):
    await asyncio.sleep(600)
    try:
        await msg.delete()
    except Exception as e:
        logger.warning(f"Failed to delete message: {e}")

# Helper to chunk buttons for inline keyboard
def chunk_buttons(buttons, chunk_size=2):
    return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]

# Global filter function (moved from pm_filter.py)
async def global_filters(client: Client, message: Message, text=False):
    group_id = message.chat.id
    name = text or message.text 
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id 
    keywords = await get_gfilters("gfilters")
    for keyword in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[\W])" + re.escape(keyword) + r"( |$|[\W])"
        if re.search(pattern, name, flags=re.IGNORECASE):
            reply_text, btn, alert, fileid = await find_gfilter("gfilters", keyword)
            if reply_text:
                reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")
            
            try:
                if fileid == "None":
                    if btn == "[]":
                        piroxrk = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_to_message_id=reply_id
                        )
                    else:
                        button = eval(btn)
                        piroxrk = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_markup=InlineKeyboardMarkup(button),
                            reply_to_message_id=reply_id
                        )
                elif btn == "[]":
                    piroxrk = await client.send_cached_media(
                        group_id,
                        fileid,
                        caption=reply_text or "",
                        reply_to_message_id=reply_id
                    )
                else:
                    button = eval(btn)
                    piroxrk = await message.reply_cached_media(
                        fileid,
                        caption=reply_text or "",
                        reply_markup=InlineKeyboardMarkup(button),
                        reply_to_message_id=reply_id
                    )
            except Exception as e:
                logger.exception(e)
            break
    else:
        return False

# Series filter function (moved from pm_filter.py)
async def series_filter(client: Client, message: Message):
    text = message.text.strip()
    series_infos = get_series()
    series_keys = [series['key'] for series in series_infos]
    series_names = [series['title'] for series in series_infos]

    series_key = None
    
    # Try exact match by key first
    if text.lower().replace(" ", "").replace("-", "") in series_keys:
        series_key = text.lower().replace(" ", "").replace("-", "")
    else:
        # Try exact match by title
        for s_info in series_infos:
            if s_info['title'].lower() == text.lower():
                series_key = s_info['key']
                break
        
        if not series_key:
            # Try close matches for titles
            close_matches = find_close_matches(text, series_names)
            if not close_matches:
                # Fallback to starts-with if no close matches
                first_word = text.split()[0]
                close_matches = [name for name in series_names if name.lower().startswith(first_word.lower())]
            
            if close_matches:
                buttons = []
                for match in close_matches:
                    s_info = next((s for s in series_infos if s['title'] == match), None)
                    if s_info:
                        buttons.append(InlineKeyboardButton(match, callback_data=f"user_series:{s_info['key']}"))
                
                if buttons:
                    buttons_chunked = chunk_buttons(buttons, chunk_size=1)
                    reply_markup = InlineKeyboardMarkup(buttons_chunked)
                    etho = await message.reply_photo(photo=random.choice(SPELL_CHECK_IMAGE), caption="<b>Choose Your Series:</b>", reply_markup=reply_markup)
                    reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else None
                    user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
                    asyncio.create_task(DeleteMessage(etho))
                    return

    if series_key:
        series = get_series_name(series_key)
        if not series:
            return

        languages = series.get("languages", {})
        
        reply_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n\n"
            "Select the language you need...!"
        )
        poster_url = get_movie_poster(series_key)
        
        buttons = []
        for lang_key, lang_data in languages.items():
            buttons.append(InlineKeyboardButton(lang_data['name'], callback_data=f"user_series:{series_key}:{lang_key}"))
        
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        reply_markup = InlineKeyboardMarkup(buttons_chunked)
        
        try:
            if poster_url:
                etho = await message.reply_photo(photo=poster_url, caption=reply_text, reply_markup=reply_markup)
            else:
                etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG[0], caption=reply_text, reply_markup=reply_markup)
            
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
            asyncio.create_task(DeleteMessage(etho))
            logger.info("Series filter message sent.")
        except pyrogram.errors.MediaEmpty:
            logger.warning(f"MediaEmpty error for poster: {poster_url}. Using placeholder.")
            etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG[0], caption=reply_text, reply_markup=reply_markup)
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
            asyncio.create_task(DeleteMessage(etho))
        except Exception as e:
            logger.error(f"Error sending series filter message: {e}")

def find_close_matches(query, possibilities, n=3, cutoff=0.6):
    import difflib
    return difflib.get_close_matches(query, possibilities, n, cutoff)

def get_movie_poster(series_key):
    poster_url = get_poster_manuel(series_key)
    if not poster_url:
        series = get_series_name(series_key)
        if series:
            poster_url = series.get('poster_url') # Get from the main series data
    return poster_url or NO_POSTER_FOUND_IMG[0]

# TMDB and other helper functions from the original admin_ui.py
async def get_tmdb_info(query, bulk=False, tmdb_id=None, media_type=None):
    """Fetches movie/TV show information from TMDB."""
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {TMDB_API_KEY}"
    }

    try:
        if tmdb_id:
            # Fetch details for a specific TMDB ID
            url = f"{TMDB_BASE_URL}/{media_type}/{tmdb_id}"
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
            
            return {
                'title': title,
                'year': year,
                'genres': ', '.join(genres) if genres else 'N/A',
                'rating': data.get('vote_average', 'N/A'),
                'poster_url': poster_url,
                'tmdb_id': data.get('id'),
                'media_type': media_type,
                'url': f'https://www.themoviedb.org/{media_type}/{data.get("id")}'
            }
        else:
            # Search mode
            search_results = []
            
            # Search TV shows
            url_tv = f"{TMDB_BASE_URL}/search/tv"
            response_tv = requests.get(url_tv, headers=headers, params={"query": query})
            response_tv.raise_for_status()
            data_tv = response_tv.json()
            for item in data_tv.get('results', [])[:5]: # Limit to 5 results
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
            response_movie = requests.get(url_movie, headers=headers, params={"query": query})
            response_movie.raise_for_status()
            data_movie = response_movie.json()
            for item in data_movie.get('results', [])[:5]: # Limit to 5 results
                if item.get('title'):
                    search_results.append({
                        'title': item.get('title'),
                        'year': item.get('release_date', '').split('-')[0] if item.get('release_date') else 'N/A',
                        'tmdb_id': item.get('id'),
                        'media_type': 'movie',
                        'source': 'tmdb'
                    })
            
            return search_results[:10] # Return max 10 results total (TV first, then movies)

    except requests.exceptions.RequestException as e:
        logger.error(f"TMDB API error: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred with TMDB: {e}")
        return None

async def download_and_upload_poster(client: Client, poster_url: str = None, message: Message = None):
    """Downloads a poster (from URL or user-provided photo), uploads it to LOG_CHANNEL, and returns its file_id."""
    temp_dir = os.path.join(TMP_DOWNLOAD_DIRECTORY, str(uuid.uuid4()))
    os.makedirs(temp_dir, exist_ok=True)
    download_path = None
    file_id = None

    try:
        if poster_url:
            # Download from URL
            response = requests.get(poster_url, stream=True)
            response.raise_for_status()
            download_path = os.path.join(temp_dir, "poster.jpg")
            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        elif message and message.photo and message.photo.file_id:
            # Use user-provided photo
            download_path = await client.download_media(message.photo.file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        elif message and message.video and message.video.thumbs and message.video.thumbs[0].file_id:
            # Use user-provided video thumbnail
            download_path = await client.download_media(message.video.thumbs[0].file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        else:
            logger.warning("No valid poster source (URL, photo, or video thumbnail) provided.")
            return None

        if download_path:
            # Upload to LOG_CHANNEL
            sent_msg = await client.send_photo(LOG_CHANNEL, photo=download_path, caption="Series Poster")
            file_id = sent_msg.photo.file_id
            try:
                await sent_msg.delete() # Delete from log channel to keep it clean
            except Exception as e:
                logger.warning(f"Could not delete temporary poster message from LOG_CHANNEL: {e}")
    except Exception as e:
        logger.error(f"Error downloading/uploading poster: {e}")
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
    return file_id

# Message handlers
@Client.on_message(filters.text & (filters.private | filters.group))
async def handle_message(client: Client, message: Message):
    user_id = message.from_user.id
    
    # If the message is in a group, apply global and series filters
    if message.chat.type != enums.ChatType.PRIVATE:
        glob = await global_filters(client, message)
        if glob == False:
            await series_filter(client, message)
        return
    
    # For private chats
    if user_id in ADMINS:
        # Check if the admin has an active state
        if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
            # Acquire the lock for this admin
            async with get_admin_lock(user_id):
                await handle_admin_text_input(client, message)
            return
    
    # For non-admins or admins without active state, apply global and series filters
    glob = await global_filters(client, message)
    if glob == False:
        await series_filter(client, message)

@Client.on_message((filters.photo | filters.video | filters.document) & (filters.private | filters.group))
async def handle_media_message(client: Client, message: Message):
    user_id = message.from_user.id
    
    if message.chat.type != enums.ChatType.PRIVATE:
        # In groups, we don't process media for admin UI, so we return
        return
    
    if user_id in ADMINS:
        if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
            async with get_admin_lock(user_id):
                await handle_admin_media_input(client, message)
            return
    
    # For non-admins or admins without active state, we don't do anything with media in private
    return

# Command handler for the new admin UI
@Client.on_message(filters.command('newseriesui') & filters.user(ADMINS))
async def new_series_ui_command(client: Client, message: Message):
    user_id = message.from_user.id
    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None

    if not query:
        await message.reply("Usage: `/newseriesui <series_title>`")
        return

    # Acquire the lock for this admin
    async with get_admin_lock(user_id):
        temp_msg = await message.reply_photo(
            photo=NO_POSTER_FOUND_IMG, # Temporary placeholder
            caption="Searching TMDB and IMDb, please wait..."
        )
        
        tmdb_results = await get_tmdb_info(query, bulk=True)
        imdb_results = await get_poster(query, bulk=True) # Use get_poster for IMDb search

        all_results = []
        if tmdb_results:
            for item in tmdb_results:
                item['source'] = 'tmdb'
                all_results.append(item)
        if imdb_results:
            for item in imdb_results:
                # Ensure IMDb results have consistent keys
                all_results.append({
                    'title': item.get('title'),
                    'year': item.get('year'),
                    'imdb_id': item.get('imdb_id'),
                    'media_type': item.get('media_type'), # 'movie' or 'tv series'
                    'source': 'imdb',
                    'poster_url': item.get('poster_url')
                })

        if not all_results:
            await temp_msg.edit_caption("No results found on TMDB or IMDb for the provided series name.")
            return

        # Store the search results in temp_admin_data
        temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
        temp_admin_data[user_id]["search_results"] = all_results
        temp_admin_data[user_id]["query"] = query
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SEARCH_RESULTS"
        temp_admin_data[user_id]["main_message_id"] = temp_msg.id

        await send_series_selection_message(client, user_id, query, all_results, temp_msg.id)

# Callback query handler
@Client.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data

    # Check if it's an admin UI callback (starts with "newui_")
    if data.startswith("newui_"):
        if user_id in ADMINS:
            async with get_admin_lock(user_id):
                await newui_callback_handler(client, callback_query)
        else:
            await callback_query.answer("You are not authorized!", show_alert=True)
        return

    # Otherwise, it's a user series callback
    if data.startswith("user_series:") or data.startswith("b:"):
        await user_series_callback_handler(client, callback_query)
        return

# User series callback handler (moved from pm_filter.py)
async def user_series_callback_handler(client: Client, query: CallbackQuery):
    data = query.data
    parts = data.split(":")
    clicked_user = query.from_user.id
    chat_id = query.message.chat.id
    message_id = query.message.id

    reply_msg = query.message.reply_to_message  
    if reply_msg and reply_msg.from_user:
        requested_user = reply_msg.from_user.id
    else:
        requested_user = user_requestor.get(f"{chat_id}•{message_id}")
    
    if chat_id < 0 and requested_user and clicked_user != requested_user:
        await query.answer("Not your request!", show_alert=True)
        return

    if data == "pages":
        await query.answer()
        return

    elif data.startswith("b:"):
        # This is the final link to fetch files
        file_link_key = data.split(":", 1)[1]
        
        # Fetch files from the episodes collection
        files_to_send, channel_id, first_msg_id, last_msg_id = await get_links_for_quality(file_link_key)

        if not files_to_send:
            await query.answer("No files found for this quality.", show_alert=True)
            return

        await query.answer("Sending files...")
        
        track_msgs = []
        for entry in files_to_send:
            try:
                copied_msg = await client.send_cached_media(
                    chat_id=query.from_user.id, 
                    file_id=entry["file_id"],
                    caption=entry.get("caption", "")
                )
                if copied_msg and temp.AUTO_DELETE_TIME and temp.AUTO_DELETE_TIME > 0:
                    track_msgs.append(copied_msg)
                await asyncio.sleep(0.5)
            except FloodWait as e:
                logger.warning(f"FloodWait for {e.value} sec")
                await asyncio.sleep(e.value)
                copied_msg = await client.send_cached_media(
                    chat_id=query.from_user.id, 
                    file_id=entry["file_id"],
                    caption=entry.get("caption", "")
                )
                if copied_msg and temp.AUTO_DELETE_TIME and temp.AUTO_DELETE_TIME > 0:
                    track_msgs.append(copied_msg)
            except Exception as e:
                logger.error(f"Error sending cached media to user {query.from_user.id}: {e}")
                # Optionally, send an error message to the user
                await client.send_message(query.from_user.id, f"Error sending file: {e}")
                
        if track_msgs:
            delete_data = await client.send_message(
                chat_id=query.from_user.id,
                text=temp.AUTO_DELETE_MSG.format(time=temp.AUTO_DELETE_TIME)
            )
            asyncio.create_task(DeleteMessage(delete_data)) # Use DeleteMessage for the auto-delete message
        return

    elif data.startswith("user_series:"):
        series_key = parts[1]
        series = get_series_name(series_key)
        if not series:
            await query.message.edit_text("Series not found or deleted.", parse_mode=enums.ParseMode.HTML)
            return

        lang_key = parts[2] if len(parts) > 2 else None
        season_key = parts[3] if len(parts) > 3 else None
        quality_key = parts[4] if len(parts) > 4 else None

        base_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n"
        )
        
        buttons = []
        current_level_data = None
        back_callback = None

        if not lang_key: # Show languages
            current_level_data = series.get("languages", {})
            for key, data_item in current_level_data.items():
                buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"user_series:{series_key}:{key}"))
            text = base_text + "\nSelect the language you need...!"
            # No back button at this level, as it's the initial series view
            
        elif not season_key: # Show seasons for selected language
            current_level_data = series.get("languages", {}).get(lang_key, {}).get("seasons", {})
            lang_name = series.get("languages", {}).get(lang_key, {}).get("name", "N/A")
            for key, data_item in current_level_data.items():
                buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"user_series:{series_key}:{lang_key}:{key}"))
            text = base_text + f"○ **Language:** `{lang_name}`\n\nSelect the season you need...!"
            back_callback = f"user_series:{series_key}"

        elif not quality_key: # Show qualities for selected season
            current_level_data = series.get("languages", {}).get(lang_key, {}).get("seasons", {}).get(season_key, {}).get("qualities", {})
            lang_name = series.get("languages", {}).get(lang_key, {}).get("name", "N/A")
            season_name = series.get("languages", {}).get(lang_key, {}).get("seasons", {}).get(season_key, {}).get("name", "N/A")
            for key, data_item in current_level_data.items():
                # The file_link_key is stored in crazy_db, but the actual files are in episodes collection
                file_link_key = data_item.get('file_link_key')
                if file_link_key:
                    buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"b:{file_link_key}"))
            text = base_text + f"○ **Language:** `{lang_name}`\n○ **Season:** `{season_name}`\n\nSelect the quality you need...!"
            back_callback = f"user_series:{series_key}:{lang_key}"
        
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        if back_callback:
            buttons_chunked.append([InlineKeyboardButton("Back", callback_data=back_callback)])
        
        reply_markup = InlineKeyboardMarkup(buttons_chunked)

        try:
            await query.message.edit_text(
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error editing message in user_series callback: {e}")
            await query.answer("An error occurred. Please try again.", show_alert=True)

# Admin UI callback handler
async def newui_callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data.split(":")
    action = data[0].replace("newui_", "")
    
    if user_id not in temp_admin_data:
        await callback_query.answer("Session expired. Please start again with /newseriesui.", show_alert=True)
        return
    
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    
    if action == "search_again":
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
    
    elif action in ["tmdb_select", "imdb_select"]:
        unique_id = data[1]
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
        
        # Check if series already exists, if so, load it
        existing_series = get_series_by_key(series_key)
        if existing_series:
            series_data = existing_series
            await callback_query.answer("Series already exists. Loading for editing.", show_alert=True)
        else:
            # Create new series data
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
        
        # Re-fetch series_data to ensure it's the latest from DB
        series_data = get_series_by_key(series_key)
        if not series_data:
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption="Failed to retrieve series data after initial setup. Please try again."
            )
            return
        
        # Download and upload poster to LOG_CHANNEL, then update DB
        poster_file_id = await download_and_upload_poster(client, poster_url=movie_details.get('poster_url') or movie_details.get('poster'))
        if poster_file_id:
            update_series_field(series_key, "poster_file_id", poster_file_id)
            series_data["poster_file_id"] = poster_file_id
        else:
            await client.send_message(user_id, "Failed to download/upload poster. Using placeholder.")
            update_series_field(series_key, "poster_file_id", NO_POSTER_FOUND_IMG)
            series_data["poster_file_id"] = NO_POSTER_FOUND_IMG
        
        # Update main message with series details and management buttons
        new_main_msg_id = await send_series_details_message(client, user_id, series_data, main_message_id)
        if new_main_msg_id:
            temp_admin_data[user_id]["main_message_id"] = new_main_msg_id
            temp_admin_data[user_id]["current_series_key"] = series_key
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SERIES_DETAILS"
    
    # ... (rest of the callback actions from the original admin_ui.py)

# ... (rest of the functions from the original admin_ui.py)

# Process input functions (handle_admin_text_input, handle_admin_media_input, etc.)
# ... (rest of the functions from the original admin_uiimport asyncio
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
from typing import Dict, Any

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, 
    InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from imdb import Cinemagoer
from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, TMDB_API_KEY, LOG_CHANNEL, DB_CHANNEL, RAW_DB_CHANNEL, SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG
from database.crazy_db import (
    add_series, get_series_by_key, update_series_field, add_or_update_language,
    get_languages, delete_language, add_or_update_season, get_seasons, delete_season,
    add_or_update_quality, get_qualities, get_quality_link, delete_quality,
    get_poster_file_id, update_poster_file_id, publish_series, get_series_name, get_poster_manuel, get_links_for_quality
)
from database.gfilters_mdb import (
    find_gfilter,
    get_gfilters
)
from utils import (
    get_message_id, get_messages_in_range, delete_messages_from_user_chat, 
    get_poster, find_most_similar_title, temp
)
from fuzzywuzzy import fuzz
from pyrogram.errors import MessageIdInvalid, FloodWait

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Temporary storage for multi-step UI interactions
temp_admin_data = {}

# Dictionary to hold locks for admin users
admin_locks: Dict[int, asyncio.RLock] = {}

# Dictionary to track user requests for series selection
user_requestor = {}

imdb = Cinemagoer()

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

# Helper to get or create a lock for an admin user
def get_admin_lock(user_id: int) -> asyncio.RLock:
    if user_id not in admin_locks:
        admin_locks[user_id] = asyncio.RLock()
    return admin_locks[user_id]

# Helper function to delete a message after a delay
async def DeleteMessage(msg):
    await asyncio.sleep(600)
    try:
        await msg.delete()
    except Exception as e:
        logger.warning(f"Failed to delete message: {e}")

# Helper to chunk buttons for inline keyboard
def chunk_buttons(buttons, chunk_size=2):
    return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]

# Global filter function (moved from pm_filter.py)
async def global_filters(client: Client, message: Message, text=False):
    group_id = message.chat.id
    name = text or message.text 
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id 
    keywords = await get_gfilters("gfilters")
    for keyword in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[\W])" + re.escape(keyword) + r"( |$|[\W])"
        if re.search(pattern, name, flags=re.IGNORECASE):
            reply_text, btn, alert, fileid = await find_gfilter("gfilters", keyword)
            if reply_text:
                reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")
            
            try:
                if fileid == "None":
                    if btn == "[]":
                        piroxrk = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_to_message_id=reply_id
                        )
                    else:
                        button = eval(btn)
                        piroxrk = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_markup=InlineKeyboardMarkup(button),
                            reply_to_message_id=reply_id
                        )
                elif btn == "[]":
                    piroxrk = await client.send_cached_media(
                        group_id,
                        fileid,
                        caption=reply_text or "",
                        reply_to_message_id=reply_id
                    )
                else:
                    button = eval(btn)
                    piroxrk = await message.reply_cached_media(
                        fileid,
                        caption=reply_text or "",
                        reply_markup=InlineKeyboardMarkup(button),
                        reply_to_message_id=reply_id
                    )
            except Exception as e:
                logger.exception(e)
            break
    else:
        return False

# Series filter function (moved from pm_filter.py)
async def series_filter(client: Client, message: Message):
    text = message.text.strip()
    series_infos = get_series()
    series_keys = [series['key'] for series in series_infos]
    series_names = [series['title'] for series in series_infos]

    series_key = None
    
    # Try exact match by key first
    if text.lower().replace(" ", "").replace("-", "") in series_keys:
        series_key = text.lower().replace(" ", "").replace("-", "")
    else:
        # Try exact match by title
        for s_info in series_infos:
            if s_info['title'].lower() == text.lower():
                series_key = s_info['key']
                break
        
        if not series_key:
            # Try close matches for titles
            close_matches = find_close_matches(text, series_names)
            if not close_matches:
                # Fallback to starts-with if no close matches
                first_word = text.split()[0]
                close_matches = [name for name in series_names if name.lower().startswith(first_word.lower())]
            
            if close_matches:
                buttons = []
                for match in close_matches:
                    s_info = next((s for s in series_infos if s['title'] == match), None)
                    if s_info:
                        buttons.append(InlineKeyboardButton(match, callback_data=f"user_series:{s_info['key']}"))
                
                if buttons:
                    buttons_chunked = chunk_buttons(buttons, chunk_size=1)
                    reply_markup = InlineKeyboardMarkup(buttons_chunked)
                    etho = await message.reply_photo(photo=random.choice(SPELL_CHECK_IMAGE), caption="<b>Choose Your Series:</b>", reply_markup=reply_markup)
                    reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else None
                    user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
                    asyncio.create_task(DeleteMessage(etho))
                    return

    if series_key:
        series = get_series_name(series_key)
        if not series:
            return

        languages = series.get("languages", {})
        
        reply_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n\n"
            "Select the language you need...!"
        )
        poster_url = get_movie_poster(series_key)
        
        buttons = []
        for lang_key, lang_data in languages.items():
            buttons.append(InlineKeyboardButton(lang_data['name'], callback_data=f"user_series:{series_key}:{lang_key}"))
        
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        reply_markup = InlineKeyboardMarkup(buttons_chunked)
        
        try:
            if poster_url:
                etho = await message.reply_photo(photo=poster_url, caption=reply_text, reply_markup=reply_markup)
            else:
                etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG[0], caption=reply_text, reply_markup=reply_markup)
            
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
            asyncio.create_task(DeleteMessage(etho))
            logger.info("Series filter message sent.")
        except pyrogram.errors.MediaEmpty:
            logger.warning(f"MediaEmpty error for poster: {poster_url}. Using placeholder.")
            etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG[0], caption=reply_text, reply_markup=reply_markup)
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
            asyncio.create_task(DeleteMessage(etho))
        except Exception as e:
            logger.error(f"Error sending series filter message: {e}")

def find_close_matches(query, possibilities, n=3, cutoff=0.6):
    import difflib
    return difflib.get_close_matches(query, possibilities, n, cutoff)

def get_movie_poster(series_key):
    poster_url = get_poster_manuel(series_key)
    if not poster_url:
        series = get_series_name(series_key)
        if series:
            poster_url = series.get('poster_url') # Get from the main series data
    return poster_url or NO_POSTER_FOUND_IMG[0]

# TMDB and other helper functions from the original admin_ui.py
async def get_tmdb_info(query, bulk=False, tmdb_id=None, media_type=None):
    """Fetches movie/TV show information from TMDB."""
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {TMDB_API_KEY}"
    }

    try:
        if tmdb_id:
            # Fetch details for a specific TMDB ID
            url = f"{TMDB_BASE_URL}/{media_type}/{tmdb_id}"
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
            
            return {
                'title': title,
                'year': year,
                'genres': ', '.join(genres) if genres else 'N/A',
                'rating': data.get('vote_average', 'N/A'),
                'poster_url': poster_url,
                'tmdb_id': data.get('id'),
                'media_type': media_type,
                'url': f'https://www.themoviedb.org/{media_type}/{data.get("id")}'
            }
        else:
            # Search mode
            search_results = []
            
            # Search TV shows
            url_tv = f"{TMDB_BASE_URL}/search/tv"
            response_tv = requests.get(url_tv, headers=headers, params={"query": query})
            response_tv.raise_for_status()
            data_tv = response_tv.json()
            for item in data_tv.get('results', [])[:5]: # Limit to 5 results
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
            response_movie = requests.get(url_movie, headers=headers, params={"query": query})
            response_movie.raise_for_status()
            data_movie = response_movie.json()
            for item in data_movie.get('results', [])[:5]: # Limit to 5 results
                if item.get('title'):
                    search_results.append({
                        'title': item.get('title'),
                        'year': item.get('release_date', '').split('-')[0] if item.get('release_date') else 'N/A',
                        'tmdb_id': item.get('id'),
                        'media_type': 'movie',
                        'source': 'tmdb'
                    })
            
            return search_results[:10] # Return max 10 results total (TV first, then movies)

    except requests.exceptions.RequestException as e:
        logger.error(f"TMDB API error: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred with TMDB: {e}")
        return None

async def download_and_upload_poster(client: Client, poster_url: str = None, message: Message = None):
    """Downloads a poster (from URL or user-provided photo), uploads it to LOG_CHANNEL, and returns its file_id."""
    temp_dir = os.path.join(TMP_DOWNLOAD_DIRECTORY, str(uuid.uuid4()))
    os.makedirs(temp_dir, exist_ok=True)
    download_path = None
    file_id = None

    try:
        if poster_url:
            # Download from URL
            response = requests.get(poster_url, stream=True)
            response.raise_for_status()
            download_path = os.path.join(temp_dir, "poster.jpg")
            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        elif message and message.photo and message.photo.file_id:
            # Use user-provided photo
            download_path = await client.download_media(message.photo.file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        elif message and message.video and message.video.thumbs and message.video.thumbs[0].file_id:
            # Use user-provided video thumbnail
            download_path = await client.download_media(message.video.thumbs[0].file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        else:
            logger.warning("No valid poster source (URL, photo, or video thumbnail) provided.")
            return None

        if download_path:
            # Upload to LOG_CHANNEL
            sent_msg = await client.send_photo(LOG_CHANNEL, photo=download_path, caption="Series Poster")
            file_id = sent_msg.photo.file_id
            try:
                await sent_msg.delete() # Delete from log channel to keep it clean
            except Exception as e:
                logger.warning(f"Could not delete temporary poster message from LOG_CHANNEL: {e}")
    except Exception as e:
        logger.error(f"Error downloading/uploading poster: {e}")
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
    return file_id

# Message handlers
@Client.on_message(filters.text & (filters.private | filters.group))
async def handle_message(client: Client, message: Message):
    user_id = message.from_user.id
    
    # If the message is in a group, apply global and series filters
    if message.chat.type != enums.ChatType.PRIVATE:
        glob = await global_filters(client, message)
        if glob == False:
            await series_filter(client, message)
        return
    
    # For private chats
    if user_id in ADMINS:
        # Check if the admin has an active state
        if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
            # Acquire the lock for this admin
            async with get_admin_lock(user_id):
                await handle_admin_text_input(client, message)
            return
    
    # For non-admins or admins without active state, apply global and series filters
    glob = await global_filters(client, message)
    if glob == False:
        await series_filter(client, message)

@Client.on_message((filters.photo | filters.video | filters.document) & (filters.private | filters.group))
async def handle_media_message(client: Client, message: Message):
    user_id = message.from_user.id
    
    if message.chat.type != enums.ChatType.PRIVATE:
        # In groups, we don't process media for admin UI, so we return
        return
    
    if user_id in ADMINS:
        if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
            async with get_admin_lock(user_id):
                await handle_admin_media_input(client, message)
            return
    
    # For non-admins or admins without active state, we don't do anything with media in private
    return

# Command handler for the new admin UI
@Client.on_message(filters.command('newseriesui') & filters.user(ADMINS))
async def new_series_ui_command(client: Client, message: Message):
    user_id = message.from_user.id
    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None

    if not query:
        await message.reply("Usage: `/newseriesui <series_title>`")
        return

    # Acquire the lock for this admin
    async with get_admin_lock(user_id):
        temp_msg = await message.reply_photo(
            photo=NO_POSTER_FOUND_IMG, # Temporary placeholder
            caption="Searching TMDB and IMDb, please wait..."
        )
        
        tmdb_results = await get_tmdb_info(query, bulk=True)
        imdb_results = await get_poster(query, bulk=True) # Use get_poster for IMDb search

        all_results = []
        if tmdb_results:
            for item in tmdb_results:
                item['source'] = 'tmdb'
                all_results.append(item)
        if imdb_results:
            for item in imdb_results:
                # Ensure IMDb results have consistent keys
                all_results.append({
                    'title': item.get('title'),
                    'year': item.get('year'),
                    'imdb_id': item.get('imdb_id'),
                    'media_type': item.get('media_type'), # 'movie' or 'tv series'
                    'source': 'imdb',
                    'poster_url': item.get('poster_url')
                })

        if not all_results:
            await temp_msg.edit_caption("No results found on TMDB or IMDb for the provided series name.")
            return

        # Store the search results in temp_admin_data
        temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
        temp_admin_data[user_id]["search_results"] = all_results
        temp_admin_data[user_id]["query"] = query
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SEARCH_RESULTS"
        temp_admin_data[user_id]["main_message_id"] = temp_msg.id

        await send_series_selection_message(client, user_id, query, all_results, temp_msg.id)

# Callback query handler
@Client.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data

    # Check if it's an admin UI callback (starts with "newui_")
    if data.startswith("newui_"):
        if user_id in ADMINS:
            async with get_admin_lock(user_id):
                await newui_callback_handler(client, callback_query)
        else:
            await callback_query.answer("You are not authorized!", show_alert=True)
        return

    # Otherwise, it's a user series callback
    if data.startswith("user_series:") or data.startswith("b:"):
        await user_series_callback_handler(client, callback_query)
        return

# User series callback handler (moved from pm_filter.py)
async def user_series_callback_handler(client: Client, query: CallbackQuery):
    data = query.data
    parts = data.split(":")
    clicked_user = query.from_user.id
    chat_id = query.message.chat.id
    message_id = query.message.id

    reply_msg = query.message.reply_to_message  
    if reply_msg and reply_msg.from_user:
        requested_user = reply_msg.from_user.id
    else:
        requested_user = user_requestor.get(f"{chat_id}•{message_id}")
    
    if chat_id < 0 and requested_user and clicked_user != requested_user:
        await query.answer("Not your request!", show_alert=True)
        return

    if data == "pages":
        await query.answer()
        return

    elif data.startswith("b:"):
        # This is the final link to fetch files
        file_link_key = data.split(":", 1)[1]
        
        # Fetch files from the episodes collection
        files_to_send, channel_id, first_msg_id, last_msg_id = await get_links_for_quality(file_link_key)

        if not files_to_send:
            await query.answer("No files found for this quality.", show_alert=True)
            return

        await query.answer("Sending files...")
        
        track_msgs = []
        for entry in files_to_send:
            try:
                copied_msg = await client.send_cached_media(
                    chat_id=query.from_user.id, 
                    file_id=entry["file_id"],
                    caption=entry.get("caption", "")
                )
                if copied_msg and temp.AUTO_DELETE_TIME and temp.AUTO_DELETE_TIME > 0:
                    track_msgs.append(copied_msg)
                await asyncio.sleep(0.5)
            except FloodWait as e:
                logger.warning(f"FloodWait for {e.value} sec")
                await asyncio.sleep(e.value)
                copied_msg = await client.send_cached_media(
                    chat_id=query.from_user.id, 
                    file_id=entry["file_id"],
                    caption=entry.get("caption", "")
                )
                if copied_msg and temp.AUTO_DELETE_TIME and temp.AUTO_DELETE_TIME > 0:
                    track_msgs.append(copied_msg)
            except Exception as e:
                logger.error(f"Error sending cached media to user {query.from_user.id}: {e}")
                # Optionally, send an error message to the user
                await client.send_message(query.from_user.id, f"Error sending file: {e}")
                
        if track_msgs:
            delete_data = await client.send_message(
                chat_id=query.from_user.id,
                text=temp.AUTO_DELETE_MSG.format(time=temp.AUTO_DELETE_TIME)
            )
            asyncio.create_task(DeleteMessage(delete_data)) # Use DeleteMessage for the auto-delete message
        return

    elif data.startswith("user_series:"):
        series_key = parts[1]
        series = get_series_name(series_key)
        if not series:
            await query.message.edit_text("Series not found or deleted.", parse_mode=enums.ParseMode.HTML)
            return

        lang_key = parts[2] if len(parts) > 2 else None
        season_key = parts[3] if len(parts) > 3 else None
        quality_key = parts[4] if len(parts) > 4 else None

        base_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n"
        )
        
        buttons = []
        current_level_data = None
        back_callback = None

        if not lang_key: # Show languages
            current_level_data = series.get("languages", {})
            for key, data_item in current_level_data.items():
                buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"user_series:{series_key}:{key}"))
            text = base_text + "\nSelect the language you need...!"
            # No back button at this level, as it's the initial series view
            
        elif not season_key: # Show seasons for selected language
            current_level_data = series.get("languages", {}).get(lang_key, {}).get("seasons", {})
            lang_name = series.get("languages", {}).get(lang_key, {}).get("name", "N/A")
            for key, data_item in current_level_data.items():
                buttons.append(InlineKeyboardButton(data_item['name'], calladminata=f"user_series:{series_key}:{lang_key}:{key}"))
            text = base_text + f"○ **Language:** `{lang_name}`\n\nSelect the season you need...!"
            back_callback = f"user_series:{series_key}"

        elif not quality_key: # Show qualities for selected season
            current_level_data = series.get("languages", {}).get(lang_key, {}).get("seasons", {}).get(season_key, {}).get("qualities", {})
            lang_name = series.get("languages", {}).get(lang_key, {}).get("name", "N/A")
            season_name = series.get("languages", {}).get(lang_key, {}).get("seasons", {}).get(season_key, {}).get("name", "N/A")
            for key, data_item in current_level_data.items():
                # The file_link_key is stored in crazy_db, but the actual files are in episodes collection
                file_link_key = data_item.get('file_link_key')
                if file_link_key:
                    buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"b:{file_link_key}"))
            text = base_text + f"○ **Language:** `{lang_name}`\n○ **Season:** `{season_name}`\n\nSelect the quality you need...!"
            back_callback = f"user_series:{series_key}:{lang_key}"
        
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        if back_callback:
            buttons_chunked.append([InlineKeyboardButton("Back", callback_data=back_callback)])
        
        reply_markup = InlineKeyboardMarkup(buttons_chunked)

        try:
            await query.message.edit_text(
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error editing message in user_series callback: {e}")
            await query.answer("An error occurred. Please try again.", show_alert=True)

# Admin UI callback handler
async def newui_callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data.split(":")
    action = data[0].replace("newui_", "")
    
    if user_id not in temp_admin_data:
        await callback_query.answer("Session expired. Please start again with /newseriesui.", show_alert=True)
        return
    
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    
    if action == "search_again":
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
    
    elif action in ["tmdb_select", "imdb_select"]:
        unique_id = data[1]
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
        
        # Check if series already exists, if so, load it
        existing_series = get_series_by_key(series_key)
        if existing_series:
            series_data = existing_series
            await callback_query.answer("Series already exists. Loading for editing.", show_alert=True)
        else:
            # Create new series data
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
        
        # Re-fetch series_data to ensure it's the latest from DB
        series_data = get_series_by_key(series_key)
        if not series_data:
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption="Failed to retrieve series data after initial setup. Please try again."
            )
            return
        
        # Download and upload poster to LOG_CHANNEL, then update DB
        poster_file_id = await download_and_upload_poster(client, poster_url=movie_details.get('poster_url') or movie_details.get('poster'))
        if poster_file_id:
            update_series_field(series_key, "poster_file_id", poster_file_id)
            series_data["poster_file_id"] = poster_file_id
        else:
            await client.send_message(user_id, "Failed to download/upload poster. Using placeholder.")
            update_series_field(series_key, "poster_file_id", NO_POSTER_FOUND_IMG)
            series_data["poster_file_id"] = NO_POSTER_FOUND_IMG
        
        # Update main message with series details and management buttons
        new_main_msg_id = await send_series_details_message(client, user_id, series_data, main_message_id)
        if new_main_msg_id:
            temp_admin_data[user_id]["main_message_id"] = new_main_msg_id
            temp_admin_data[user_id]["current_series_key"] = series_key
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SERIES_DETAILS"
    
    # ... (rest of the callback actions from the original admin_ui.py)

# ... (rest of the functions from the original admin_ui.py)

# Process input functions (handle_admin_text_input, handle_admin_media_input, etc.)
# ... (rest of the functions from the original admin_uimport asyncio
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
from typing import Dict, Any

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, 
    InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from imdb import Cinemagoer
from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, TMDB_API_KEY, LOG_CHANNEL, DB_CHANNEL, RAW_DB_CHANNEL, SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG
from database.crazy_db import (
    add_series, get_series_by_key, update_series_field, add_or_update_language,
    get_languages, delete_language, add_or_update_season, get_seasons, delete_season,
    add_or_update_quality, get_qualities, get_quality_link, delete_quality,
    get_poster_file_id, update_poster_file_id, publish_series, get_series_name, get_poster_manuel, get_links_for_quality
)
from database.gfilters_mdb import (
    find_gfilter,
    get_gfilters
)
from utils import (
    get_message_id, get_messages_in_range, delete_messages_from_user_chat, 
    get_poster, find_most_similar_title, temp
)
from fuzzywuzzy import fuzz
from pyrogram.errors import MessageIdInvalid, FloodWait

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Temporary storage for multi-step UI interactions
temp_admin_data = {}

# Dictionary to hold locks for admin users
admin_locks: Dict[int, asyncio.Lock] = {}

# Dictionary to track user requests for series selection
user_requestor = {}

imdb = Cinemagoer()

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

# Helper to get or create a lock for an admin user
def get_admin_lock(user_id: int) -> asyncio.RLock:
    if user_id not in admin_locks:
        admin_locks[user_id] = asyncio.RLock()
    return admin_locks[user_id]

# Helper function to delete a message after a delay
async def DeleteMessage(msg):
    await asyncio.sleep(600)
    try:
        await msg.delete()
    except Exception as e:
        logger.warning(f"Failed to delete message: {e}")

# Helper to chunk buttons for inline keyboard
def chunk_buttons(buttons, chunk_size=2):
    return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]

# Global filter function (moved from pm_filter.py)
async def global_filters(client: Client, message: Message, text=False):
    group_id = message.chat.id
    name = text or message.text 
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id 
    keywords = await get_gfilters("gfilters")
    for keyword in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[\W])" + re.escape(keyword) + r"( |$|[\W])"
        if re.search(pattern, name, flags=re.IGNORECASE):
            reply_text, btn, alert, fileid = await find_gfilter("gfilters", keyword)
            if reply_text:
                reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")
            
            try:
                if fileid == "None":
                    if btn == "[]":
                        piroxrk = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_to_message_id=reply_id
                        )
                    else:
                        button = eval(btn)
                        piroxrk = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_markup=InlineKeyboardMarkup(button),
                            reply_to_message_id=reply_id
                        )
                elif btn == "[]":
                    piroxrk = await client.send_cached_media(
                        group_id,
                        fileid,
                        caption=reply_text or "",
                        reply_to_message_id=reply_id
                    )
                else:
                    button = eval(btn)
                    piroxrk = await message.reply_cached_media(
                        fileid,
                        caption=reply_text or "",
                        reply_markup=InlineKeyboardMarkup(button),
                        reply_to_message_id=reply_id
                    )
            except Exception as e:
                logger.exception(e)
            break
    else:
        return False

# Series filter function (moved from pm_filter.py)
async def series_filter(client: Client, message: Message):
    text = message.text.strip()
    series_infos = get_series()
    series_keys = [series['key'] for series in series_infos]
    series_names = [series['title'] for series in series_infos]

    series_key = None
    
    # Try exact match by key first
    if text.lower().replace(" ", "").replace("-", "") in series_keys:
        series_key = text.lower().replace(" ", "").replace("-", "")
    else:
        # Try exact match by title
        for s_info in series_infos:
            if s_info['title'].lower() == text.lower():
                series_key = s_info['key']
                break
        
        if not series_key:
            # Try close matches for titles
            close_matches = find_close_matches(text, series_names)
            if not close_matches:
                # Fallback to starts-with if no close matches
                first_word = text.split()[0]
                close_matches = [name for name in series_names if name.lower().startswith(first_word.lower())]
            
            if close_matches:
                buttons = []
                for match in close_matches:
                    s_info = next((s for s in series_infos if s['title'] == match), None)
                    if s_info:
                        buttons.append(InlineKeyboardButton(match, callback_data=f"user_series:{s_info['key']}"))
                
                if buttons:
                    buttons_chunked = chunk_buttons(buttons, chunk_size=1)
                    reply_markup = InlineKeyboardMarkup(buttons_chunked)
                    etho = await message.reply_photo(photo=random.choice(SPELL_CHECK_IMAGE), caption="<b>Choose Your Series:</b>", reply_markup=reply_markup)
                    reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else None
                    user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
                    asyncio.create_task(DeleteMessage(etho))
                    return

    if series_key:
        series = get_series_name(series_key)
        if not series:
            return

        languages = series.get("languages", {})
        
        reply_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n\n"
            "Select the language you need...!"
        )
        poster_url = get_movie_poster(series_key)
        
        buttons = []
        for lang_key, lang_data in languages.items():
            buttons.append(InlineKeyboardButton(lang_data['name'], callback_data=f"user_series:{series_key}:{lang_key}"))
        
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        reply_markup = InlineKeyboardMarkup(buttons_chunked)
        
        try:
            if poster_url:
                etho = await message.reply_photo(photo=poster_url, caption=reply_text, reply_markup=reply_markup)
            else:
                etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG[0], caption=reply_text, reply_markup=reply_markup)
            
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
            asyncio.create_task(DeleteMessage(etho))
            logger.info("Series filter message sent.")
        except pyrogram.errors.MediaEmpty:
            logger.warning(f"MediaEmpty error for poster: {poster_url}. Using placeholder.")
            etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG[0], caption=reply_text, reply_markup=reply_markup)
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
            asyncio.create_task(DeleteMessage(etho))
        except Exception as e:
            logger.error(f"Error sending series filter message: {e}")

def find_close_matches(query, possibilities, n=3, cutoff=0.6):
    import difflib
    return difflib.get_close_matches(query, possibilities, n, cutoff)

def get_movie_poster(series_key):
    poster_url = get_poster_manuel(series_key)
    if not poster_url:
        series = get_series_name(series_key)
        if series:
            poster_url = series.get('poster_url') # Get from the main series data
    return poster_url or NO_POSTER_FOUND_IMG[0]

# TMDB and other helper functions from the original admin_ui.py
async def get_tmdb_info(query, bulk=False, tmdb_id=None, media_type=None):
    """Fetches movie/TV show information from TMDB."""
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {TMDB_API_KEY}"
    }

    try:
        if tmdb_id:
            # Fetch details for a specific TMDB ID
            url = f"{TMDB_BASE_URL}/{media_type}/{tmdb_id}"
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
            
            return {
                'title': title,
                'year': year,
                'genres': ', '.join(genres) if genres else 'N/A',
                'rating': data.get('vote_average', 'N/A'),
                'poster_url': poster_url,
                'tmdb_id': data.get('id'),
                'media_type': media_type,
                'url': f'https://www.themoviedb.org/{media_type}/{data.get("id")}'
            }
        else:
            # Search mode
            search_results = []
            
            # Search TV shows
            url_tv = f"{TMDB_BASE_URL}/search/tv"
            response_tv = requests.get(url_tv, headers=headers, params={"query": query})
            response_tv.raise_for_status()
            data_tv = response_tv.json()
            for item in data_tv.get('results', [])[:5]: # Limit to 5 results
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
            response_movie = requests.get(url_movie, headers=headers, params={"query": query})
            response_movie.raise_for_status()
            data_movie = response_movie.json()
            for item in data_movie.get('results', [])[:5]: # Limit to 5 results
                if item.get('title'):
                    search_results.append({
                        'title': item.get('title'),
                        'year': item.get('release_date', '').split('-')[0] if item.get('release_date') else 'N/A',
                        'tmdb_id': item.get('id'),
                        'media_type': 'movie',
                        'source': 'tmdb'
                    })
            
            return search_results[:10] # Return max 10 results total (TV first, then movies)

    except requests.exceptions.RequestException as e:
        logger.error(f"TMDB API error: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred with TMDB: {e}")
        return None

async def download_and_upload_poster(client: Client, poster_url: str = None, message: Message = None):
    """Downloads a poster (from URL or user-provided photo), uploads it to LOG_CHANNEL, and returns its file_id."""
    temp_dir = os.path.join(TMP_DOWNLOAD_DIRECTORY, str(uuid.uuid4()))
    os.makedirs(temp_dir, exist_ok=True)
    download_path = None
    file_id = None

    try:
        if poster_url:
            # Download from URL
            response = requests.get(poster_url, stream=True)
            response.raise_for_status()
            download_path = os.path.join(temp_dir, "poster.jpg")
            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        elif message and message.photo and message.photo.file_id:
            # Use user-provided photo
            download_path = await client.download_media(message.photo.file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        elif message and message.video and message.video.thumbs and message.video.thumbs[0].file_id:
            # Use user-provided video thumbnail
            download_path = await client.download_media(message.video.thumbs[0].file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        else:
            logger.warning("No valid poster source (URL, photo, or video thumbnail) provided.")
            return None

        if download_path:
            # Upload to LOG_CHANNEL
            sent_msg = await client.send_photo(LOG_CHANNEL, photo=download_path, caption="Series Poster")
            file_id = sent_msg.photo.file_id
            try:
                await sent_msg.delete() # Delete from log channel to keep it clean
            except Exception as e:
                logger.warning(f"Could not delete temporary poster message from LOG_CHANNEL: {e}")
    except Exception as e:
        logger.error(f"Error downloading/uploading poster: {e}")
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
    return file_id

# Message handlers
@Client.on_message(filters.text & (filters.private | filters.group))
async def handle_message(client: Client, message: Message):
    user_id = message.from_user.id
    
    # If the message is in a group, apply global and series filters
    if message.chat.type != enums.ChatType.PRIVATE:
        glob = await global_filters(client, message)
        if glob == False:
            await series_filter(client, message)
        return
    
    # For private chats
    if user_id in ADMINS:
        # Check if the admin has an active state
        if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
            # Acquire the lock for this admin
            async with get_admin_lock(user_id):
                await handle_admin_text_input(client, message)
            return
    
    # For non-admins or admins without active state, apply global and series filters
    glob = await global_filters(client, message)
    if glob == False:
        await series_filter(client, message)

@Client.on_message((filters.photo | filters.video | filters.document) & (filters.private | filters.group))
async def handle_media_message(client: Client, message: Message):
    user_id = message.from_user.id
    
    if message.chat.type != enums.ChatType.PRIVATE:
        # In groups, we don't process media for admin UI, so we return
        return
    
    if user_id in ADMINS:
        if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
            async with get_admin_lock(user_id):
                await handle_admin_media_input(client, message)
            return
    
    # For non-admins or admins without active state, we don't do anything with media in private
    return

# Command handler for the new admin UI
@Client.on_message(filters.command('newseriesui') & filters.user(ADMINS))
async def new_series_ui_command(client: Client, message: Message):
    user_id = message.from_user.id
    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None

    if not query:
        await message.reply("Usage: `/newseriesui <series_title>`")
        return

    # Acquire the lock for this admin
    async with get_admin_lock(user_id):
        temp_msg = await message.reply_photo(
            photo=NO_POSTER_FOUND_IMG, # Temporary placeholder
            caption="Searching TMDB and IMDb, please wait..."
        )
        
        tmdb_results = await get_tmdb_info(query, bulk=True)
        imdb_results = await get_poster(query, bulk=True) # Use get_poster for IMDb search

        all_results = []
        if tmdb_results:
            for item in tmdb_results:
                item['source'] = 'tmdb'
                all_results.append(item)
        if imdb_results:
            for item in imdb_results:
                # Ensure IMDb results have consistent keys
                all_results.append({
                    'title': item.get('title'),
                    'year': item.get('year'),
                    'imdb_id': item.get('imdb_id'),
                    'media_type': item.get('media_type'), # 'movie' or 'tv series'
                    'source': 'imdb',
                    'poster_url': item.get('poster_url')
                })

        if not all_results:
            await temp_msg.edit_caption("No results found on TMDB or IMDb for the provided series name.")
            return

        # Store the search results in temp_admin_data
        temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
        temp_admin_data[user_id]["search_results"] = all_results
        temp_admin_data[user_id]["query"] = query
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SEARCH_RESULTS"
        temp_admin_data[user_id]["main_message_id"] = temp_msg.id

        await send_series_selection_message(client, user_id, query, all_results, temp_msg.id)

# Callback query handler
@Client.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data

    # Check if it's an admin UI callback (starts with "newui_")
    if data.startswith("newui_"):
        if user_id in ADMINS:
            async with get_admin_lock(user_id):
                await newui_callback_handler(client, callback_query)
        else:
            await callback_query.answer("You are not authorized!", show_alert=True)
        return

    # Otherwise, it's a user series callback
    if data.startswith("user_series:") or data.startswith("b:"):
        await user_series_callback_handler(client, callback_query)
        return

# User series callback handler (moved from pm_filter.py)
async def user_series_callback_handler(client: Client, query: CallbackQuery):
    data = query.data
    parts = data.split(":")
    clicked_user = query.from_user.id
    chat_id = query.message.chat.id
    message_id = query.message.id

    reply_msg = query.message.reply_to_message  
    if reply_msg and reply_msg.from_user:
        requested_user = reply_msg.from_user.id
    else:
        requested_user = user_requestor.get(f"{chat_id}•{message_id}")
    
    if chat_id < 0 and requested_user and clicked_user != requested_user:
        await query.answer("Not your request!", show_alert=True)
        return

    if data == "pages":
        await query.answer()
        return

    elif data.startswith("b:"):
        # This is the final link to fetch files
        file_link_key = data.split(":", 1)[1]
        
        # Fetch files from the episodes collection
        files_to_send, channel_id, first_msg_id, last_msg_id = await get_links_for_quality(file_link_key)

        if not files_to_send:
            await query.answer("No files found for this quality.", show_alert=True)
            return

        await query.answer("Sending files...")
        
        track_msgs = []
        for entry in files_to_send:
            try:
                copied_msg = await client.send_cached_media(
                    chat_id=query.from_user.id, 
                    file_id=entry["file_id"],
                    caption=entry.get("caption", "")
                )
                if copied_msg and temp.AUTO_DELETE_TIME and temp.AUTO_DELETE_TIME > 0:
                    track_msgs.append(copied_msg)
                await asyncio.sleep(0.5)
            except FloodWait as e:
                logger.warning(f"FloodWait for {e.value} sec")
                await asyncio.sleep(e.value)
                copied_msg = await client.send_cached_media(
                    chat_id=query.from_user.id, 
                    file_id=entry["file_id"],
                    caption=entry.get("caption", "")
                )
                if copied_msg and temp.AUTO_DELETE_TIME and temp.AUTO_DELETE_TIME > 0:
                    track_msgs.append(copied_msg)
            except Exception as e:
                logger.error(f"Error sending cached media to user {query.from_user.id}: {e}")
                # Optionally, send an error message to the user
                await client.send_message(query.from_user.id, f"Error sending file: {e}")
                
        if track_msgs:
            delete_data = await client.send_message(
                chat_id=query.from_user.id,
                text=temp.AUTO_DELETE_MSG.format(time=temp.AUTO_DELETE_TIME)
            )
            asyncio.create_task(DeleteMessage(delete_data)) # Use DeleteMessage for the auto-delete message
        return

    elif data.startswith("user_series:"):
        series_key = parts[1]
        series = get_series_name(series_key)
        if not series:
            await query.message.edit_text("Series not found or deleted.", parse_mode=enums.ParseMode.HTML)
            return

        lang_key = parts[2] if len(parts) > 2 else None
        season_key = parts[3] if len(parts) > 3 else None
        quality_key = parts[4] if len(parts) > 4 else None

        base_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n"
        )
        
        buttons = []
        current_level_data = None
        back_callback = None

        if not lang_key: # Show languages
            current_level_data = series.get("languages", {})
            for key, data_item in current_level_data.items():
                buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"user_series:{series_key}:{key}"))
            text = base_text + "\nSelect the language you need...!"
            # No back button at this level, as it's the initial series view
            
        elif not season_key: # Show seasons for selected language
            current_level_data = series.get("languages", {}).get(lang_key, {}).get("seasons", {})
            lang_name = series.get("languages", {}).get(lang_key, {}).get("name", "N/A")
            for key, data_item in current_level_data.items():
                buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"user_series:{series_key}:{lang_key}:{key}"))
            text = base_text + f"○ **Language:** `{lang_name}`\n\nSelect the season you need...!"
            back_callback = f"user_series:{series_key}"

        elif not quality_key: # Show qualities for selected season
            current_level_data = series.get("languages", {}).get(lang_key, {}).get("seasons", {}).get(season_key, {}).get("qualities", {})
            lang_name = series.get("languages", {}).get(lang_key, {}).get("name", "N/A")
            season_name = series.get("languages", {}).get(lang_key, {}).get("seasons", {}).get(season_key, {}).get("name", "N/A")
            for key, data_item in current_level_data.items():
                # The file_link_key is stored in crazy_db, but the actual files are in episodes collection
                file_link_key = data_item.get('file_link_key')
                if file_link_key:
                    buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"b:{file_link_key}"))
            text = base_text + f"○ **Language:** `{lang_name}`\n○ **Season:** `{season_name}`\n\nSelect the quality you need...!"
            back_callback = f"user_series:{series_key}:{lang_key}"
        
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        if back_callback:
            buttons_chunked.append([InlineKeyboardButton("Back", callback_data=back_callback)])
        
        reply_markup = InlineKeyboardMarkup(buttons_chunked)

        try:
            await query.message.edit_text(
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error editing message in user_series callback: {e}")
            await query.answer("An error occurred. Please try again.", show_alert=True)

# Admin UI callback handler
async def newui_callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data.split(":")
    action = data[0].replace("newui_", "")
    
    if user_id not in temp_admin_data:
        await callback_query.answer("Session expired. Please start again with /newseriesui.", show_alert=True)
        return
    
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    
    if action == "search_again":
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
    
    elif action in ["tmdb_select", "imdb_select"]:
        unique_id = data[1]
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
        
        # Check if series already exists, if so, load it
        existing_series = get_series_by_key(series_key)
        if existing_series:
            series_data = existing_series
            await callback_query.answer("Series already exists. Loading for editing.", show_alert=True)
        else:
            # Create new series data
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
        
        # Re-fetch series_data to ensure it's the latest from DB
        series_data = get_series_by_key(series_key)
        if not series_data:
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption="Failed to retrieve series data after initial setup. Please try again."
            )
            return
        
        # Download and upload poster to LOG_CHANNEL, then update DB
        poster_file_id = await download_and_upload_poster(client, poster_url=movie_details.get('poster_url') or movie_details.get('poster'))
        if poster_file_id:
            update_series_field(series_key, "poster_file_id", poster_file_id)
            series_data["poster_file_id"] = poster_file_id
        else:
            await client.send_message(user_id, "Failed to download/upload poster. Using placeholder.")
            update_series_field(series_key, "poster_file_id", NO_POSTER_FOUND_IMG)
            series_data["poster_file_id"] = NO_POSTER_FOUND_IMG
        
        # Update main message with series details and management buttons
        new_main_msg_id = await send_series_details_message(client, user_id, series_data, main_message_id)
        if new_main_msg_id:
            temp_admin_data[user_id]["main_message_id"] = new_main_msg_id
            temp_admin_data[user_id]["current_series_key"] = series_key
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SERIES_DETAILS"
    
    # ... (rest of the callback actions from the original admin_ui.py)

# ... (rest of the functions from the original admin_ui.py)

# Process input functions (handle_admin_text_input, handle_admin_media_input, etc.)
# ... (rest of the functions from the original admin_import asyncio
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
from typing import Dict, Any

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, 
    InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from imdb import Cinemagoer
from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, TMDB_API_KEY, LOG_CHANNEL, DB_CHANNEL, RAW_DB_CHANNEL, SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG
from database.crazy_db import (
    add_series, get_series_by_key, update_series_field, add_or_update_language,
    get_languages, delete_language, add_or_update_season, get_seasons, delete_season,
    add_or_update_quality, get_qualities, get_quality_link, delete_quality,
    get_poster_file_id, update_poster_file_id, publish_series, get_series_name, get_poster_manuel, get_links_for_quality
)
from database.gfilters_mdb import (
    find_gfilter,
    get_gfilters
)
from utils import (
    get_message_id, get_messages_in_range, delete_messages_from_user_chat, 
    get_poster, find_most_similar_title, temp
)
from fuzzywuzzy import fuzz
from pyrogram.errors import MessageIdInvalid, FloodWait

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Temporary storage for multi-step UI interactions
temp_admin_data = {}

# Dictionary to hold locks for admin users
admin_locks: Dict[int, asyncio.RLock] = {}

# Dictionary to track user requests for series selection
user_requestor = {}

imdb = Cinemagoer()

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

# Helper to get or create a lock for an admin user
def get_admin_lock(user_id: int) -> asyncio.RLock:
    if user_id not in admin_locks:
        admin_locks[user_id] = asyncio.RLock()
    return admin_locks[user_id]

# Helper function to delete a message after a delay
async def DeleteMessage(msg):
    await asyncio.sleep(600)
    try:
        await msg.delete()
    except Exception as e:
        logger.warning(f"Failed to delete message: {e}")

# Helper to chunk buttons for inline keyboard
def chunk_buttons(buttons, chunk_size=2):
    return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]

# Global filter function (moved from pm_filter.py)
async def global_filters(client: Client, message: Message, text=False):
    group_id = message.chat.id
    name = text or message.text 
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id 
    keywords = await get_gfilters("gfilters")
    for keyword in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[\W])" + re.escape(keyword) + r"( |$|[\W])"
        if re.search(pattern, name, flags=re.IGNORECASE):
            reply_text, btn, alert, fileid = await find_gfilter("gfilters", keyword)
            if reply_text:
                reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")
            
            try:
                if fileid == "None":
                    if btn == "[]":
                        piroxrk = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_to_message_id=reply_id
                        )
                    else:
                        button = eval(btn)
                        piroxrk = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_markup=InlineKeyboardMarkup(button),
                            reply_to_message_id=reply_id
                        )
                elif btn == "[]":
                    piroxrk = await client.send_cached_media(
                        group_id,
                        fileid,
                        caption=reply_text or "",
                        reply_to_message_id=reply_id
                    )
                else:
                    button = eval(btn)
                    piroxrk = await message.reply_cached_media(
                        fileid,
                        caption=reply_text or "",
                        reply_markup=InlineKeyboardMarkup(button),
                        reply_to_message_id=reply_id
                    )
            except Exception as e:
                logger.exception(e)
            break
    else:
        return False

# Series filter function (moved from pm_filter.py)
async def series_filter(client: Client, message: Message):
    text = message.text.strip()
    series_infos = get_series()
    series_keys = [series['key'] for series in series_infos]
    series_names = [series['title'] for series in series_infos]

    series_key = None
    
    # Try exact match by key first
    if text.lower().replace(" ", "").replace("-", "") in series_keys:
        series_key = text.lower().replace(" ", "").replace("-", "")
    else:
        # Try exact match by title
        for s_info in series_infos:
            if s_info['title'].lower() == text.lower():
                series_key = s_info['key']
                break
        
        if not series_key:
            # Try close matches for titles
            close_matches = find_close_matches(text, series_names)
            if not close_matches:
                # Fallback to starts-with if no close matches
                first_word = text.split()[0]
                close_matches = [name for name in series_names if name.lower().startswith(first_word.lower())]
            
            if close_matches:
                buttons = []
                for match in close_matches:
                    s_info = next((s for s in series_infos if s['title'] == match), None)
                    if s_info:
                        buttons.append(InlineKeyboardButton(match, callback_data=f"user_series:{s_info['key']}"))
                
                if buttons:
                    buttons_chunked = chunk_buttons(buttons, chunk_size=1)
                    reply_markup = InlineKeyboardMarkup(buttons_chunked)
                    etho = await message.reply_photo(photo=random.choice(SPELL_CHECK_IMAGE), caption="<b>Choose Your Series:</b>", reply_markup=reply_markup)
                    reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else None
                    user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
                    asyncio.create_task(DeleteMessage(etho))
                    return

    if series_key:
        series = get_series_name(series_key)
        if not series:
            return

        languages = series.get("languages", {})
        
        reply_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n\n"
            "Select the language you need...!"
        )
        poster_url = get_movie_poster(series_key)
        
        buttons = []
        for lang_key, lang_data in languages.items():
            buttons.append(InlineKeyboardButton(lang_data['name'], callback_data=f"user_series:{series_key}:{lang_key}"))
        
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        reply_markup = InlineKeyboardMarkup(buttons_chunked)
        
        try:
            if poster_url:
                etho = await message.reply_photo(photo=poster_url, caption=reply_text, reply_markup=reply_markup)
            else:
                etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG[0], caption=reply_text, reply_markup=reply_markup)
            
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
            asyncio.create_task(DeleteMessage(etho))
            logger.info("Series filter message sent.")
        except pyrogram.errors.MediaEmpty:
            logger.warning(f"MediaEmpty error for poster: {poster_url}. Using placeholder.")
            etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG[0], caption=reply_text, reply_markup=reply_markup)
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
            asyncio.create_task(DeleteMessage(etho))
        except Exception as e:
            logger.error(f"Error sending series filter message: {e}")

def find_close_matches(query, possibilities, n=3, cutoff=0.6):
    import difflib
    return difflib.get_close_matches(query, possibilities, n, cutoff)

def get_movie_poster(series_key):
    poster_url = get_poster_manuel(series_key)
    if not poster_url:
        series = get_series_name(series_key)
        if series:
            poster_url = series.get('poster_url') # Get from the main series data
    return poster_url or NO_POSTER_FOUND_IMG[0]

# TMDB and other helper functions from the original admin_ui.py
async def get_tmdb_info(query, bulk=False, tmdb_id=None, media_type=None):
    """Fetches movie/TV show information from TMDB."""
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {TMDB_API_KEY}"
    }

    try:
        if tmdb_id:
            # Fetch details for a specific TMDB ID
            url = f"{TMDB_BASE_URL}/{media_type}/{tmdb_id}"
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
            
            return {
                'title': title,
                'year': year,
                'genres': ', '.join(genres) if genres else 'N/A',
                'rating': data.get('vote_average', 'N/A'),
                'poster_url': poster_url,
                'tmdb_id': data.get('id'),
                'media_type': media_type,
                'url': f'https://www.themoviedb.org/{media_type}/{data.get("id")}'
            }
        else:
            # Search mode
            search_results = []
            
            # Search TV shows
            url_tv = f"{TMDB_BASE_URL}/search/tv"
            response_tv = requests.get(url_tv, headers=headers, params={"query": query})
            response_tv.raise_for_status()
            data_tv = response_tv.json()
            for item in data_tv.get('results', [])[:5]: # Limit to 5 results
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
            response_movie = requests.get(url_movie, headers=headers, params={"query": query})
            response_movie.raise_for_status()
            data_movie = response_movie.json()
            for item in data_movie.get('results', [])[:5]: # Limit to 5 results
                if item.get('title'):
                    search_results.append({
                        'title': item.get('title'),
                        'year': item.get('release_date', '').split('-')[0] if item.get('release_date') else 'N/A',
                        'tmdb_id': item.get('id'),
                        'media_type': 'movie',
                        'source': 'tmdb'
                    })
            
            return search_results[:10] # Return max 10 results total (TV first, then movies)

    except requests.exceptions.RequestException as e:
        logger.error(f"TMDB API error: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred with TMDB: {e}")
        return None

async def download_and_upload_poster(client: Client, poster_url: str = None, message: Message = None):
    """Downloads a poster (from URL or user-provided photo), uploads it to LOG_CHANNEL, and returns its file_id."""
    temp_dir = os.path.join(TMP_DOWNLOAD_DIRECTORY, str(uuid.uuid4()))
    os.makedirs(temp_dir, exist_ok=True)
    download_path = None
    file_id = None

    try:
        if poster_url:
            # Download from URL
            response = requests.get(poster_url, stream=True)
            response.raise_for_status()
            download_path = os.path.join(temp_dir, "poster.jpg")
            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        elif message and message.photo and message.photo.file_id:
            # Use user-provided photo
            download_path = await client.download_media(message.photo.file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        elif message and message.video and message.video.thumbs and message.video.thumbs[0].file_id:
            # Use user-provided video thumbnail
            download_path = await client.download_media(message.video.thumbs[0].file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        else:
            logger.warning("No valid poster source (URL, photo, or video thumbnail) provided.")
            return None

        if download_path:
            # Upload to LOG_CHANNEL
            sent_msg = await client.send_photo(LOG_CHANNEL, photo=download_path, caption="Series Poster")
            file_id = sent_msg.photo.file_id
            try:
                await sent_msg.delete() # Delete from log channel to keep it clean
            except Exception as e:
                logger.warning(f"Could not delete temporary poster message from LOG_CHANNEL: {e}")
    except Exception as e:
        logger.error(f"Error downloading/uploading poster: {e}")
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
    return file_id

# Message handlers
@Client.on_message(filters.text & (filters.private | filters.group))
async def handle_message(client: Client, message: Message):
    user_id = message.from_user.id
    
    # If the message is in a group, apply global and series filters
    if message.chat.type != enums.ChatType.PRIVATE:
        glob = await global_filters(client, message)
        if glob == False:
            await series_filter(client, message)
        return
    
    # For private chats
    if user_id in ADMINS:
        # Check if the admin has an active state
        if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
            # Acquire the lock for this admin
            async with get_admin_lock(user_id):
                await handle_admin_text_input(client, message)
            return
    
    # For non-admins or admins without active state, apply global and series filters
    glob = await global_filters(client, message)
    if glob == False:
        await series_filter(client, message)

@Client.on_message((filters.photo | filters.video | filters.document) & (filters.private | filters.group))
async def handle_media_message(client: Client, message: Message):
    user_id = message.from_user.id
    
    if message.chat.type != enums.ChatType.PRIVATE:
        # In groups, we don't process media for admin UI, so we return
        return
    
    if user_id in ADMINS:
        if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
            async with get_admin_lock(user_id):
                await handle_admin_media_input(client, message)
            return
    
    # For non-admins or admins without active state, we don't do anything with media in private
    return

# Command handler for the new admin UI
@Client.on_message(filters.command('newseriesui') & filters.user(ADMINS))
async def new_series_ui_command(client: Client, message: Message):
    user_id = message.from_user.id
    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None

    if not query:
        await message.reply("Usage: `/newseriesui <series_title>`")
        return

    # Acquire the lock for this admin
    async with get_admin_lock(user_id):
        temp_msg = await message.reply_photo(
            photo=NO_POSTER_FOUND_IMG, # Temporary placeholder
            caption="Searching TMDB and IMDb, please wait..."
        )
        
        tmdb_results = await get_tmdb_info(query, bulk=True)
        imdb_results = await get_poster(query, bulk=True) # Use get_poster for IMDb search

        all_results = []
        if tmdb_results:
            for item in tmdb_results:
                item['source'] = 'tmdb'
                all_results.append(item)
        if imdb_results:
            for item in imdb_results:
                # Ensure IMDb results have consistent keys
                all_results.append({
                    'title': item.get('title'),
                    'year': item.get('year'),
                    'imdb_id': item.get('imdb_id'),
                    'media_type': item.get('media_type'), # 'movie' or 'tv series'
                    'source': 'imdb',
                    'poster_url': item.get('poster_url')
                })

        if not all_results:
            await temp_msg.edit_caption("No results found on TMDB or IMDb for the provided series name.")
            return

        # Store the search results in temp_admin_data
        temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
        temp_admin_data[user_id]["search_results"] = all_results
        temp_admin_data[user_id]["query"] = query
        temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SEARCH_RESULTS"
        temp_admin_data[user_id]["main_message_id"] = temp_msg.id

        await send_series_selection_message(client, user_id, query, all_results, temp_msg.id)

# Callback query handler
@Client.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data

    # Check if it's an admin UI callback (starts with "newui_")
    if data.startswith("newui_"):
        if user_id in ADMINS:
            async with get_admin_lock(user_id):
                await newui_callback_handler(client, callback_query)
        else:
            await callback_query.answer("You are not authorized!", show_alert=True)
        return

    # Otherwise, it's a user series callback
    if data.startswith("user_series:") or data.startswith("b:"):
        await user_series_callback_handler(client, callback_query)
        return

# User series callback handler (moved from pm_filter.py)
async def user_series_callback_handler(client: Client, query: CallbackQuery):
    data = query.data
    parts = data.split(":")
    clicked_user = query.from_user.id
    chat_id = query.message.chat.id
    message_id = query.message.id

    reply_msg = query.message.reply_to_message  
    if reply_msg and reply_msg.from_user:
        requested_user = reply_msg.from_user.id
    else:
        requested_user = user_requestor.get(f"{chat_id}•{message_id}")
    
    if chat_id < 0 and requested_user and clicked_user != requested_user:
        await query.answer("Not your request!", show_alert=True)
        return

    if data == "pages":
        await query.answer()
        return

    elif data.startswith("b:"):
        # This is the final link to fetch files
        file_link_key = data.split(":", 1)[1]
        
        # Fetch files from the episodes collection
        files_to_send, channel_id, first_msg_id, last_msg_id = await get_links_for_quality(file_link_key)

        if not files_to_send:
            await query.answer("No files found for this quality.", show_alert=True)
            return

        await query.answer("Sending files...")
        
        track_msgs = []
        for entry in files_to_send:
            try:
                copied_msg = await client.send_cached_media(
                    chat_id=query.from_user.id, 
                    file_id=entry["file_id"],
                    caption=entry.get("caption", "")
                )
                if copied_msg and temp.AUTO_DELETE_TIME and temp.AUTO_DELETE_TIME > 0:
                    track_msgs.append(copied_msg)
                await asyncio.sleep(0.5)
            except FloodWait as e:
                logger.warning(f"FloodWait for {e.value} sec")
                await asyncio.sleep(e.value)
                copied_msg = await client.send_cached_media(
                    chat_id=query.from_user.id, 
                    file_id=entry["file_id"],
                    caption=entry.get("caption", "")
                )
                if copied_msg and temp.AUTO_DELETE_TIME and temp.AUTO_DELETE_TIME > 0:
                    track_msgs.append(copied_msg)
            except Exception as e:
                logger.error(f"Error sending cached media to user {query.from_user.id}: {e}")
                # Optionally, send an error message to the user
                await client.send_message(query.from_user.id, f"Error sending file: {e}")
                
        if track_msgs:
            delete_data = await client.send_message(
                chat_id=query.from_user.id,
                text=temp.AUTO_DELETE_MSG.format(time=temp.AUTO_DELETE_TIME)
            )
            asyncio.create_task(DeleteMessage(delete_data)) # Use DeleteMessage for the auto-delete message
        return

    elif data.startswith("user_series:"):
        series_key = parts[1]
        series = get_series_name(series_key)
        if not series:
            await query.message.edit_text("Series not found or deleted.", parse_mode=enums.ParseMode.HTML)
            return

        lang_key = parts[2] if len(parts) > 2 else None
        season_key = parts[3] if len(parts) > 3 else None
        quality_key = parts[4] if len(parts) > 4 else None

        base_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n"
        )
        
        buttons = []
        current_level_data = None
        back_callback = None

        if not lang_key: # Show languages
            current_level_data = series.get("languages", {})
            for key, data_item in current_level_data.items():
                buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"user_series:{series_key}:{key}"))
            text = base_text + "\nSelect the language you need...!"
            # No back button at this level, as it's the initial series view
            
        elif not season_key: # Show seasons for selected language
            current_level_data = series.get("languages", {}).get(lang_key, {}).get("seasons", {})
            lang_name = series.get("languages", {}).get(lang_key, {}).get("name", "N/A")
            for key, data_item in current_level_data.items():
                buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"user_series:{series_key}:{lang_key}:{key}"))
            text = base_text + f"○ **Language:** `{lang_name}`\n\nSelect the season you need...!"
            back_callback = f"user_series:{series_key}"

        elif not quality_key: # Show qualities for selected season
            current_level_data = series.get("languages", {}).get(lang_key, {}).get("seasons", {}).get(season_key, {}).get("qualities", {})
            lang_name = series.get("languages", {}).get(lang_key, {}).get("name", "N/A")
            season_name = series.get("languages", {}).get(lang_key, {}).get("seasons", {}).get(season_key, {}).get("name", "N/A")
            for key, data_item in current_level_data.items():
                # The file_link_key is stored in crazy_db, but the actual files are in episodes collection
                file_link_key = data_item.get('file_link_key')
                if file_link_key:
                    buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"b:{file_link_key}"))
            text = base_text + f"○ **Language:** `{lang_name}`\n○ **Season:** `{season_name}`\n\nSelect the quality you need...!"
            back_callback = f"user_series:{series_key}:{lang_key}"
        
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        if back_callback:
            buttons_chunked.append([InlineKeyboardButton("Back", callback_data=back_callback)])
        
        reply_markup = InlineKeyboardMarkup(buttons_chunked)

        try:
            await query.message.edit_text(
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error editing message in user_series callback: {e}")
            await query.answer("An error occurred. Please try again.", show_alert=True)

# Admin UI callback handler
async def newui_callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data.split(":")
    action = data[0].replace("newui_", "")
    
    if user_id not in temp_admin_data:
        await callback_query.answer("Session expired. Please start again with /newseriesui.", show_alert=True)
        return
    
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    
    if action == "search_again":
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
    
    elif action in ["tmdb_select", "imdb_select"]:
        unique_id = data[1]
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
        
        # Check if series already exists, if so, load it
        existing_series = get_series_by_key(series_key)
        if existing_series:
            series_data = existing_series
            await callback_query.answer("Series already exists. Loading for editing.", show_alert=True)
        else:
            # Create new series data
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
        
        # Re-fetch series_data to ensure it's the latest from DB
        series_data = get_series_by_key(series_key)
        if not series_data:
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption="Failed to retrieve series data after initial setup. Please try again."
            )
            return
        
        # Download and upload poster to LOG_CHANNEL, then update DB
        poster_file_id = await download_and_upload_poster(client, poster_url=movie_details.get('poster_url') or movie_details.get('poster'))
        if poster_file_id:
            update_series_field(series_key, "poster_file_id", poster_file_id)
            series_data["poster_file_id"] = poster_file_id
        else:
            await client.send_message(user_id, "Failed to download/upload poster. Using placeholder.")
            update_series_field(series_key, "poster_file_id", NO_POSTER_FOUND_IMG)
            series_data["poster_file_id"] = NO_POSTER_FOUND_IMG
        
        # Update main message with series details and management buttons
        new_main_msg_id = await send_series_details_message(client, user_id, series_data, main_message_id)
        if new_main_msg_id:
            temp_admin_data[user_id]["main_message_id"] = new_main_msg_id
            temp_admin_data[user_id]["current_series_key"] = series_key
            temp_admin_data[user_id]["state"] = "NEW_SERIES_UI_SERIES_DETAILS"
    
    # ... (rest of the callback actions from the original admin_ui.py)

# ... (rest of the functions from the original admin_ui.py)

# Process input functions (handle_admin_text_input, handle_admin_media_input, etc.)
# ... (rest of the functions from the original admin
