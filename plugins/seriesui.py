import asyncio
import re
import uuid
import logging
import os
import shutil
import requests
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, InputMediaPhoto
from imdb import Cinemagoer
from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, TMDB_API_KEY, LOG_CHANNEL, DB_CHANNEL, RAW_DB_CHANNEL
from database.crazy_db import (
    add_series, get_series_by_key, update_series_field, add_or_update_language,
    get_languages, delete_language, add_or_update_season, get_seasons, delete_season,
    add_or_update_quality, get_qualities, get_quality_link, delete_quality,
    get_poster_file_id, update_poster_file_id, publish_series
)
from utils import get_message_id, get_messages_in_range, delete_messages_from_user_chat

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Temporary storage for multi-step UI interactions
# Key: user_id, Value: dictionary of current state
temp_admin_data = {}

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
NO_POSTER_FOUND_IMG = "https://telegra.ph/file/5e2d4418525832bc9a1b9" # Placeholder image

# Helper to chunk buttons for inline keyboard
def chunk_buttons(buttons, chunk_size=2):
    return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]

async def get_tmdb_info(query, bulk=False, tmdb_id=None, media_type=None):
    """
    Fetches movie/TV show information from TMDB.
    - query: search term
    - bulk: if True, returns multiple search results for selection
    - tmdb_id: if provided, fetches details for a specific ID
    - media_type: 'tv' or 'movie' (required if tmdb_id is provided)
    """
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
                        'media_type': 'tv'
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
                        'media_type': 'movie'
                    })
            
            return search_results[:10] # Return max 10 results total (TV first, then movies)

    except requests.exceptions.RequestException as e:
        logger.error(f"TMDB API error: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred with TMDB: {e}")
        return None

async def download_and_upload_poster(client: Client, message: Message, poster_url: str = None):
    """
    Downloads a poster (from URL or user-provided photo), uploads it to LOG_CHANNEL,
    and returns its file_id.
    """
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
        elif message.photo:
            # Use user-provided photo
            download_path = await message.download(file_name=os.path.join(temp_dir, "poster.jpg"))
        elif message.video:
            # Use user-provided video thumbnail
            download_path = await client.download_media(message.video.thumbs[0].file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        else:
            return None

        if download_path:
            # Upload to LOG_CHANNEL
            sent_msg = await client.send_photo(LOG_CHANNEL, photo=download_path, caption="Series Poster")
            file_id = sent_msg.photo.file_id
            await sent_msg.delete() # Delete from log channel to keep it clean
    except Exception as e:
        logger.error(f"Error downloading/uploading poster: {e}")
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
    return file_id

async def send_main_series_message(client: Client, user_id: int, series_data: dict, message_id: int = None):
    """Sends or edits the main series details message."""
    series_key = series_data['_id']
    poster_file_id = get_poster_file_id(series_key) or NO_POSTER_FOUND_IMG

    text = (
        f"○ <b>Title:</b> <code>{series_data.get('title', 'N/A')}</code>\n"
        f"○ <b>Released On:</b> <code>{series_data.get('released_on', 'N/A')}</code>\n"
        f"○ <b>Genre:</b> <code>{series_data.get('genre', 'N/A')}</code>\n"
        f"○ <b>Rating:</b> <code>{series_data.get('rating', 'N/A')}</code>\n"
        f"○ <b>TMDB ID:</b> <code>{series_data.get('tmdb_id', 'N/A')}</code>\n"
        f"○ <b>Media Type:</b> <code>{series_data.get('media_type', 'N/A').upper()}</code>\n\n"
    )

    buttons = [
        [InlineKeyboardButton("Edit Details", callback_data=f"edit_series_details:{series_key}")],
        [InlineKeyboardButton("Languages", callback_data=f"manage_languages:{series_key}")],
        [InlineKeyboardButton("Change Poster", callback_data=f"change_series_poster:{series_key}")],
        [InlineKeyboardButton("Publish Series", callback_data=f"publish_series:{series_key}")]
    ]

    reply_markup = InlineKeyboardMarkup(buttons)

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=poster_file_id, caption=text, parse_mode=enums.ParseMode.HTML),
                reply_markup=reply_markup
            )
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_file_id,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML
            )
            return msg.id
    except Exception as e:
        logger.error(f"Error sending/editing main series message: {e}")
        # Fallback to text if media fails
        if message_id:
            await client.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML
            )
            return message_id
        else:
            msg = await client.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML
            )
            return msg.id

async def send_language_management_message(client: Client, user_id: int, series_key: str, message_id: int):
    """Sends or edits the language management message."""
    series_data = get_series_by_key(series_key)
    if not series_data:
        await client.send_message(user_id, "Series not found.")
        return

    languages = series_data.get("languages", [])
    
    text = f"<b>Series:</b> <code>{series_data.get('title', 'N/A')}</code>\n\n"
    text += "Select any Language group to add new Season/Part group inside them. Or click '+' button to add new Language group.\n\n"

    buttons = []
    for lang in languages:
        buttons.append([
            InlineKeyboardButton(f"{lang['name']} ({len(lang.get('seasons', []))} Seasons)", callback_data=f"manage_seasons:{series_key}:{lang['name']}")
        ])
    
    buttons.append([InlineKeyboardButton("+ Language", callback_data=f"add_language:{series_key}")])
    buttons.append([InlineKeyboardButton("Back to Series", callback_data=f"back_to_series:{series_key}")])

    reply_markup = InlineKeyboardMarkup(buttons)

    await client.edit_message_text(
        chat_id=user_id,
        message_id=message_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=enums.ParseMode.HTML
    )

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
        f"<b>Series:</b> <code>{series_data.get('title', 'N/A')}</code>\n"
        f"<b>Language:</b> <code>{language_name}</code>\n\n"
        "Select any Seasons group to add new Quality group into them. Or click '+' button to add new Seasons group.\n\n"
    )

    buttons = []
    for season in seasons:
        buttons.append([
            InlineKeyboardButton(f"{season['name']} ({len(season.get('qualities', []))} Qualities)", callback_data=f"manage_qualities:{series_key}:{language_name}:{season['name']}")
        ])
    
    buttons.append([InlineKeyboardButton("+ Season", callback_data=f"add_season:{series_key}:{language_name}")])
    buttons.append([InlineKeyboardButton("Change Poster for this Language", callback_data=f"change_language_poster:{series_key}:{language_name}")])
    buttons.append([InlineKeyboardButton(f"Delete '{language_name}' Group", callback_data=f"delete_language:{series_key}:{language_name}")])
    buttons.append([InlineKeyboardButton("Back to Languages", callback_data=f"manage_languages:{series_key}")])

    reply_markup = InlineKeyboardMarkup(buttons)

    await client.edit_message_text(
        chat_id=user_id,
        message_id=message_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=enums.ParseMode.HTML
    )

async def send_quality_management_message(client: Client, user_id: int, series_key: str, language_name: str, season_name: str, message_id: int):
    """Sends or edits the quality management message."""
    series_data = get_series_by_key(series_key)
    if not series_data:
        await client.send_message(user_id, "Series not found.")
        return

    current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
    current_season = next((s for s in current_lang.get("seasons", []) if s["name"].lower() == season_name.lower()), None)
    if not current_season:
        await client.send_message(user_id, "Season not found.")
        return

    qualities = current_season.get("qualities", [])
    
    text = (
        f"<b>Series:</b> <code>{series_data.get('title', 'N/A')}</code>\n"
        f"<b>Language:</b> <code>{language_name}</code>\n"
        f"<b>Season:</b> <code>{season_name}</code>\n\n"
        "Select any Quality group to add new files into them. Or click '+' button to add new Quality group.\n\n"
    )

    buttons = []
    for quality in qualities:
        buttons.append([
            InlineKeyboardButton(f"{quality['name']}", callback_data=f"add_files:{series_key}:{language_name}:{season_name}:{quality['name']}")
        ])
    
    buttons.append([InlineKeyboardButton("+ Quality", callback_data=f"add_quality:{series_key}:{language_name}:{season_name}")])
    buttons.append([InlineKeyboardButton("Change Poster for this Season", callback_data=f"change_season_poster:{series_key}:{language_name}:{season_name}")])
    buttons.append([InlineKeyboardButton(f"Delete '{season_name}' Group", callback_data=f"delete_season:{series_key}:{language_name}:{season_name}")])
    buttons.append([InlineKeyboardButton("Back to Seasons", callback_data=f"manage_seasons:{series_key}:{language_name}")])

    reply_markup = InlineKeyboardMarkup(buttons)

    await client.edit_message_text(
        chat_id=user_id,
        message_id=message_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=enums.ParseMode.HTML
    )

# --- Command Handlers ---

@Client.on_message(filters.command('ri'))
async def new_series_command(client: Client, message: Message):
    user_id = message.from_user.id
    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None

    if not query:
        await message.reply("Usage: `/newseries <series_title>`")
        return

    temp_msg = await message.reply_photo(
        photo="https://files.catbox.moe/aqgdp4.jpg", # Temporary placeholder
        caption="Searching TMDB, please wait..."
    )
    
    search_results = await get_tmdb_info(query, bulk=True)

    if not search_results:
        await temp_msg.edit_caption("No results found on TMDB for the provided series name.")
        return

    buttons = []
    for item in search_results:
        unique_id = str(uuid.uuid4())
        temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
        temp_admin_data[user_id][unique_id] = {
            'tmdb_id': item.get('tmdb_id'),
            'media_type': item.get('media_type'),
            'query': query # Store original query for 'Back' button
        }
        buttons.append([
            InlineKeyboardButton(
                text=f"{item.get('title', 'N/A')} ({item.get('year', 'N/A')}) - {item.get('media_type', '').upper()}",
                callback_data=f"tmdb_select:{unique_id}"
            )
        ])
    
    reply_markup = InlineKeyboardMarkup(buttons)
    await temp_msg.edit_caption(
        "Select a series from below (movies too in buttons using TMDB):\n\n"
        "**Choose Your Series:**",
        reply_markup=reply_markup
    )
    
    temp_admin_data[user_id]["state"] = "SELECTING_SERIES"
    temp_admin_data[user_id]["main_message_id"] = temp_msg.id

# --- Callback Query Handlers ---

@Client.on_callback_query(filters.regex(r"^tmdb_select:") & filters.user(ADMINS))
async def tmdb_selection_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data_parts = callback_query.data.split(":")
    unique_id = data_parts[1]

    if user_id not in temp_admin_data or unique_id not in temp_admin_data[user_id]:
        await callback_query.answer("Session expired or invalid data.", show_alert=True)
        await callback_query.message.delete()
        return

    stored_data = temp_admin_data[user_id].pop(unique_id)
    tmdb_id = stored_data['tmdb_id']
    media_type = stored_data['media_type']
    original_query = stored_data['query']
    main_message_id = temp_admin_data[user_id].get("main_message_id")

    await callback_query.answer("Fetching details...")

    movie_details = await get_tmdb_info(query=None, tmdb_id=tmdb_id, media_type=media_type)

    if not movie_details:
        await client.edit_message_caption(
            chat_id=user_id,
            message_id=main_message_id,
            caption="Failed to retrieve TMDB data. Please try again."
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
            '_id': series_key, # Use series_key as _id for easy lookup
            'title': movie_details.get('title', 'N/A'),
            'released_on': movie_details.get('year', 'N/A'),
            'genre': movie_details.get('genres', 'N/A'),
            'rating': movie_details.get('rating', 'N/A'),
            'tmdb_id': tmdb_id,
            'media_type': media_type,
            'poster_file_id': None, # Will be updated after download/upload
            'languages': [],
            'published': False
        }
        add_series(series_data) # Save initial series data

    # Download and upload poster to LOG_CHANNEL, then update DB
    poster_file_id = await download_and_upload_poster(client, callback_query.message, movie_details.get('poster_url'))
    if poster_file_id:
        update_series_field(series_key, "poster_file_id", poster_file_id)
        series_data["poster_file_id"] = poster_file_id # Update in memory for immediate use
    else:
        await client.send_message(user_id, "Failed to download/upload poster. Using placeholder.")
        update_series_field(series_key, "poster_file_id", NO_POSTER_FOUND_IMG)
        series_data["poster_file_id"] = NO_POSTER_FOUND_IMG

    # Update main message with series details and management buttons
    new_main_msg_id = await send_main_series_message(client, user_id, series_data, main_message_id)
    temp_admin_data[user_id]["main_message_id"] = new_main_msg_id
    temp_admin_data[user_id]["current_series_key"] = series_key
    temp_admin_data[user_id]["state"] = "SERIES_DETAILS_VIEW"

@Client.on_callback_query(filters.regex(r"^back_to_series:") & filters.user(ADMINS))
async def back_to_series_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    series_key = callback_query.data.split(":")[1]
    main_message_id = temp_admin_data[user_id].get("main_message_id")

    series_data = get_series_by_key(series_key)
    if not series_data:
        await callback_query.answer("Series not found.", show_alert=True)
        return

    await send_main_series_message(client, user_id, series_data, main_message_id)
    temp_admin_data[user_id]["state"] = "SERIES_DETAILS_VIEW"
    temp_admin_data[user_id].pop("current_language", None)
    temp_admin_data[user_id].pop("current_season", None)
    temp_admin_data[user_id].pop("current_quality", None)

@Client.on_callback_query(filters.regex(r"^manage_languages:") & filters.user(ADMINS))
async def manage_languages_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    series_key = callback_query.data.split(":")[1]
    main_message_id = temp_admin_data[user_id].get("main_message_id")

    temp_admin_data[user_id]["current_series_key"] = series_key
    temp_admin_data[user_id]["state"] = "MANAGE_LANGUAGES"
    await send_language_management_message(client, user_id, series_key, main_message_id)

@Client.on_callback_query(filters.regex(r"^add_language:") & filters.user(ADMINS))
async def add_language_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    series_key = callback_query.data.split(":")[1]
    main_message_id = temp_admin_data[user_id].get("main_message_id")

    await callback_query.answer("Enter language name...")
    ask_msg = await client.send_message(
        user_id,
        "Enter language name (e.g., 'English', 'Multi Audio (Ger + Eng)'):",
        reply_markup=InlineKeyboardMarkup(chunk_buttons([
            InlineKeyboardButton("English", callback_data="lang_input:English"),
            InlineKeyboardButton("Spanish", callback_data="lang_input:Spanish"),
            InlineKeyboardButton("Japanese", callback_data="lang_input:Japanese"),
            InlineKeyboardButton("Korean", callback_data="lang_input:Korean"),
            InlineKeyboardButton("French", callback_data="lang_input:French"),
            InlineKeyboardButton("German", callback_data="lang_input:German")
        ]))
    )
    temp_admin_data[user_id]["state"] = "AWAITING_LANGUAGE_INPUT"
    temp_admin_data[user_id]["ask_message_id"] = ask_msg.id

@Client.on_callback_query(filters.regex(r"^lang_input:") & filters.user(ADMINS))
async def language_quick_input_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    language_name = callback_query.data.split(":")[1]
    
    if temp_admin_data[user_id].get("state") == "AWAITING_LANGUAGE_INPUT":
        await callback_query.message.edit_text(f"Language selected: {language_name}")
        await process_language_input(client, callback_query.message, language_name)
    else:
        await callback_query.answer("Invalid state.", show_alert=True)

@Client.on_message(filters.text & filters.private & filters.user(ADMINS))
async def handle_admin_text_input(client: Client, message: Message):
    user_id = message.from_user.id
    current_state = temp_admin_data.get(user_id, {}).get("state")
    
    if current_state == "AWAITING_LANGUAGE_INPUT":
        await process_language_input(client, message, message.text.strip())
    elif current_state == "AWAITING_SEASON_INPUT":
        await process_season_input(client, message, message.text.strip())
    elif current_state == "AWAITING_QUALITY_INPUT":
        await process_quality_input(client, message, message.text.strip())
    elif current_state == "AWAITING_FIRST_FILE":
        await process_first_file_input(client, message)
    elif current_state == "AWAITING_LAST_FILE":
        await process_last_file_input(client, message)
    elif current_state == "AWAITING_CODEC_INPUT":
        await process_codec_input(client, message, message.text.strip())
    elif current_state == "AWAITING_SERIES_POSTER":
        await process_poster_input(client, message, "series")
    elif current_state == "AWAITING_LANGUAGE_POSTER":
        await process_poster_input(client, message, "language")
    elif current_state == "AWAITING_SEASON_POSTER":
        await process_poster_input(client, message, "season")
    elif current_state == "EDITING_SERIES_TEXT":
        await process_edit_series_text(client, message, message.text.strip())

async def process_language_input(client: Client, message: Message, language_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    ask_message_id = temp_admin_data[user_id].get("ask_message_id")

    if not series_key:
        await message.reply("Error: Series key not found in session.")
        return

    if add_or_update_language(series_key, language_name):
        await client.edit_message_text(
            chat_id=user_id,
            message_id=ask_message_id,
            text=f"Language '{language_name}' added/updated successfully."
        )
        await send_language_management_message(client, user_id, series_key, main_message_id)
        temp_admin_data[user_id]["state"] = "MANAGE_LANGUAGES"
    else:
        await message.reply("Failed to add/update language.")

@Client.on_callback_query(filters.regex(r"^manage_seasons:") & filters.user(ADMINS))
async def manage_seasons_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    _, series_key, language_name = callback_query.data.split(":")
    main_message_id = temp_admin_data[user_id].get("main_message_id")

    temp_admin_data[user_id]["current_series_key"] = series_key
    temp_admin_data[user_id]["current_language"] = language_name
    temp_admin_data[user_id]["state"] = "MANAGE_SEASONS"
    await send_season_management_message(client, user_id, series_key, language_name, main_message_id)

@Client.on_callback_query(filters.regex(r"^add_season:") & filters.user(ADMINS))
async def add_season_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    _, series_key, language_name = callback_query.data.split(":")
    
    await callback_query.answer("Enter season name...")
    ask_msg = await client.send_message(
        user_id,
        "Enter season name (e.g., 'Season 1', 'Part 2'):",
        reply_markup=InlineKeyboardMarkup(chunk_buttons([
            InlineKeyboardButton("Season 1", callback_data="season_input:Season 1"),
            InlineKeyboardButton("Season 2", callback_data="season_input:Season 2"),
            InlineKeyboardButton("Season 3", callback_data="season_input:Season 3"),
            InlineKeyboardButton("Season 4", callback_data="season_input:Season 4"),
            InlineKeyboardButton("Season 5", callback_data="season_input:Season 5"),
            InlineKeyboardButton("Season 6", callback_data="season_input:Season 6")
        ]))
    )
    temp_admin_data[user_id]["state"] = "AWAITING_SEASON_INPUT"
    temp_admin_data[user_id]["ask_message_id"] = ask_msg.id

@Client.on_callback_query(filters.regex(r"^season_input:") & filters.user(ADMINS))
async def season_quick_input_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    season_name = callback_query.data.split(":")[1]
    
    if temp_admin_data[user_id].get("state") == "AWAITING_SEASON_INPUT":
        await callback_query.message.edit_text(f"Season selected: {season_name}")
        await process_season_input(client, callback_query.message, season_name)
    else:
        await callback_query.answer("Invalid state.", show_alert=True)

async def process_season_input(client: Client, message: Message, season_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    ask_message_id = temp_admin_data[user_id].get("ask_message_id")

    if not all([series_key, language_name]):
        await message.reply("Error: Series or language not found in session.")
        return

    if add_or_update_season(series_key, language_name, season_name):
        await client.edit_message_text(
            chat_id=user_id,
            message_id=ask_message_id,
            text=f"Season '{season_name}' added/updated successfully."
        )
        await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
        temp_admin_data[user_id]["state"] = "MANAGE_SEASONS"
    else:
        await message.reply("Failed to add/update season.")

@Client.on_callback_query(filters.regex(r"^manage_qualities:") & filters.user(ADMINS))
async def manage_qualities_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    _, series_key, language_name, season_name = callback_query.data.split(":")
    main_message_id = temp_admin_data[user_id].get("main_message_id")

    temp_admin_data[user_id]["current_series_key"] = series_key
    temp_admin_data[user_id]["current_language"] = language_name
    temp_admin_data[user_id]["current_season"] = season_name
    temp_admin_data[user_id]["state"] = "MANAGE_QUALITIES"
    await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)

@Client.on_callback_query(filters.regex(r"^add_quality:") & filters.user(ADMINS))
async def add_quality_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    _, series_key, language_name, season_name = callback_query.data.split(":")
    
    await callback_query.answer("Enter quality name...")
    ask_msg = await client.send_message(
        user_id,
        "Enter quality name (e.g., '720p', '1080p H.265'):",
        reply_markup=InlineKeyboardMarkup(chunk_buttons([
            InlineKeyboardButton("360p", callback_data="quality_input:360p"),
            InlineKeyboardButton("480p", callback_data="quality_input:480p"),
            InlineKeyboardButton("720p", callback_data="quality_input:720p"),
            InlineKeyboardButton("1080p", callback_data="quality_input:1080p"),
            InlineKeyboardButton("2160p", callback_data="quality_input:2160p"),
            InlineKeyboardButton("H.265", callback_data="quality_input:H.265")
        ]))
    )
    temp_admin_data[user_id]["state"] = "AWAITING_QUALITY_INPUT"
    temp_admin_data[user_id]["ask_message_id"] = ask_msg.id

@Client.on_callback_query(filters.regex(r"^quality_input:") & filters.user(ADMINS))
async def quality_quick_input_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    quality_name = callback_query.data.split(":")[1]
    
    if temp_admin_data[user_id].get("state") == "AWAITING_QUALITY_INPUT":
        await callback_query.message.edit_text(f"Quality selected: {quality_name}")
        await process_quality_input(client, callback_query.message, quality_name)
    else:
        await callback_query.answer("Invalid state.", show_alert=True)

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

    # For now, we'll add with a placeholder link_key. Actual link will be added later.
    if add_or_update_quality(series_key, language_name, season_name, quality_name, "PENDING_LINK"):
        await client.edit_message_text(
            chat_id=user_id,
            message_id=ask_message_id,
            text=f"Quality '{quality_name}' added/updated successfully. Now add files."
        )
        await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
        temp_admin_data[user_id]["state"] = "MANAGE_QUALITIES"
    else:
        await message.reply("Failed to add/update quality.")

@Client.on_callback_query(filters.regex(r"^add_files:") & filters.user(ADMINS))
async def add_files_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    _, series_key, language_name, season_name, quality_name = callback_query.data.split(":")
    main_message_id = temp_admin_data[user_id].get("main_message_id")

    temp_admin_data[user_id]["current_series_key"] = series_key
    temp_admin_data[user_id]["current_language"] = language_name
    temp_admin_data[user_id]["current_season"] = season_name
    temp_admin_data[user_id]["current_quality"] = quality_name
    temp_admin_data[user_id]["files_to_delete"] = [] # To store messages sent by user for deletion

    await callback_query.answer("Forward first file...")
    ask_msg = await client.send_message(
        user_id,
        f"Add me to the channel as admin and forward me the **first file** (with tag) for "
        f"<code>{language_name.title()} - {season_name.title()} - {quality_name}</code>",
        parse_mode=enums.ParseMode.HTML
    )
    temp_admin_data[user_id]["state"] = "AWAITING_FIRST_FILE"
    temp_admin_data[user_id]["ask_message_id"] = ask_msg.id

async def process_first_file_input(client: Client, message: Message):
    user_id = message.from_user.id
    ask_message_id = temp_admin_data[user_id].get("ask_message_id")
    
    channel_id, msg_id = await get_message_id(client, message)
    if not channel_id or not msg_id:
        await message.reply("Invalid message. Please forward a message from a DB Channel or send a valid post link.")
        return

    temp_admin_data[user_id]["first_file_channel_id"] = channel_id
    temp_admin_data[user_id]["first_file_msg_id"] = msg_id
    temp_admin_data[user_id]["files_to_delete"].append(message.id) # Add user's forwarded message to delete list

    await client.edit_message_text(
        chat_id=user_id,
        message_id=ask_message_id,
        text=f"Forward me the **last file** (with tag) for "
             f"<code>{temp_admin_data[user_id]['current_language'].title()} - "
             f"{temp_admin_data[user_id]['current_season'].title()} - "
             f"{temp_admin_data[user_id]['current_quality']}</code>\n\n"
             f"Go to first file: [Link](https://t.me/c/{abs(int(channel_id))}/{msg_id})",
        parse_mode=enums.ParseMode.MARKDOWN,
        disable_web_page_preview=True
    )
    temp_admin_data[user_id]["state"] = "AWAITING_LAST_FILE"

async def process_last_file_input(client: Client, message: Message):
    user_id = message.from_user.id
    ask_message_id = temp_admin_data[user_id].get("ask_message_id")

    channel_id, msg_id = await get_message_id(client, message)
    if not channel_id or not msg_id:
        await message.reply("Invalid message. Please forward a message from a DB Channel or send a valid post link.")
        return
    
    if channel_id != temp_admin_data[user_id]["first_file_channel_id"]:
        await message.reply("Last file must be from the same channel as the first file.")
        return

    temp_admin_data[user_id]["last_file_msg_id"] = msg_id
    temp_admin_data[user_id]["files_to_delete"].append(message.id)

    await client.edit_message_text(
        chat_id=user_id,
        message_id=ask_message_id,
        text=f"Send me the **codec field** for "
             f"<code>{temp_admin_data[user_id]['current_language'].title()} - "
             f"{temp_admin_data[user_id]['current_season'].title()} - "
             f"{temp_admin_data[user_id]['current_quality']}</code>",
        parse_mode=enums.ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(chunk_buttons([
            InlineKeyboardButton("H.264", callback_data="codec_input:H.264"),
            InlineKeyboardButton("H.265", callback_data="codec_input:H.265"),
            InlineKeyboardButton("H.265 10bit", callback_data="codec_input:H.265 10bit")
        ]))
    )
    temp_admin_data[user_id]["state"] = "AWAITING_CODEC_INPUT"

@Client.on_callback_query(filters.regex(r"^codec_input:") & filters.user(ADMINS))
async def codec_quick_input_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    codec = callback_query.data.split(":")[1]
    
    if temp_admin_data[user_id].get("state") == "AWAITING_CODEC_INPUT":
        await callback_query.message.edit_text(f"Codec selected: {codec}")
        await process_codec_input(client, callback_query.message, codec)
    else:
        await callback_query.answer("Invalid state.", show_alert=True)

async def process_codec_input(client: Client, message: Message, codec: str):
    user_id = message.from_user.id
    ask_message_id = temp_admin_data[user_id].get("ask_message_id")
    
    series_key = temp_admin_data[user_id]["current_series_key"]
    language_name = temp_admin_data[user_id]["current_language"]
    season_name = temp_admin_data[user_id]["current_season"]
    quality_name = temp_admin_data[user_id]["current_quality"]
    first_file_channel_id = temp_admin_data[user_id]["first_file_channel_id"]
    first_file_msg_id = temp_admin_data[user_id]["first_file_msg_id"]
    last_file_msg_id = temp_admin_data[user_id]["last_file_msg_id"]
    files_to_delete = temp_admin_data[user_id]["files_to_delete"]

    processing_msg = await client.edit_message_text(
        chat_id=user_id,
        message_id=ask_message_id,
        text="Processing files... Please wait. This might take a while."
    )

    # Copy messages to DB_CHANNEL
    target_db_channel_id = DB_CHANNEL[0] # Use the first DB channel for storage
    copied_messages = await get_messages_in_range(
        client, 
        first_file_channel_id, 
        first_file_msg_id, 
        last_file_msg_id, 
        target_db_channel_id
    )

    if not copied_messages:
        await processing_msg.edit_text("Failed to copy files to DB Channel. Please check bot's admin rights in the source and target channels.")
        return

    new_first_msg_id = copied_messages[0].id
    new_last_msg_id = copied_messages[-1].id
    
    # Generate the link_key
    link_key = f"get_{abs(target_db_channel_id)}_{new_first_msg_id}_{new_last_msg_id}"

    if add_or_update_quality(series_key, language_name, season_name, quality_name, link_key, codec):
        await processing_msg.edit_text("Files added to Database Successfully!")
        
        # Delete user's forwarded messages
        await delete_messages_from_user_chat(client, user_id, files_to_delete)

        # Go back to quality management view
        main_message_id = temp_admin_data[user_id].get("main_message_id")
        await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
        temp_admin_data[user_id]["state"] = "MANAGE_QUALITIES"
        
        # Clear temporary file data
        temp_admin_data[user_id].pop("first_file_channel_id", None)
        temp_admin_data[user_id].pop("first_file_msg_id", None)
        temp_admin_data[user_id].pop("last_file_msg_id", None)
        temp_admin_data[user_id].pop("files_to_delete", None)
    else:
        await processing_msg.edit_text("Failed to add files to database.")

@Client.on_callback_query(filters.regex(r"^change_series_poster:") & filters.user(ADMINS))
async def change_series_poster_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    series_key = callback_query.data.split(":")[1]
    
    await callback_query.answer("Send me the new poster image/video.")
    ask_msg = await client.send_message(user_id, "Please send the new poster image or video (thumbnail will be used).")
    temp_admin_data[user_id]["state"] = "AWAITING_SERIES_POSTER"
    temp_admin_data[user_id]["ask_message_id"] = ask_msg.id

@Client.on_callback_query(filters.regex(r"^change_language_poster:") & filters.user(ADMINS))
async def change_language_poster_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    _, series_key, language_name = callback_query.data.split(":")
    
    temp_admin_data[user_id]["current_language"] = language_name # Set for poster processing
    await callback_query.answer("Send me the new poster image/video for this language.")
    ask_msg = await client.send_message(user_id, f"Please send the new poster image or video for '{language_name}'.")
    temp_admin_data[user_id]["state"] = "AWAITING_LANGUAGE_POSTER"
    temp_admin_data[user_id]["ask_message_id"] = ask_msg.id

@Client.on_callback_query(filters.regex(r"^change_season_poster:") & filters.user(ADMINS))
async def change_season_poster_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    _, series_key, language_name, season_name = callback_query.data.split(":")
    
    temp_admin_data[user_id]["current_language"] = language_name # Set for poster processing
    temp_admin_data[user_id]["current_season"] = season_name # Set for poster processing
    await callback_query.answer("Send me the new poster image/video for this season.")
    ask_msg = await client.send_message(user_id, f"Please send the new poster image or video for '{season_name}'.")
    temp_admin_data[user_id]["state"] = "AWAITING_SEASON_POSTER"
    temp_admin_data[user_id]["ask_message_id"] = ask_msg.id

async def process_poster_input(client: Client, message: Message, level: str):
    user_id = message.from_user.id
    ask_message_id = temp_admin_data[user_id].get("ask_message_id")
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    main_message_id = temp_admin_data[user_id].get("main_message_id")

    if not message.photo and not message.video:
        await message.reply("Please send a photo or video.")
        return

    processing_msg = await client.edit_message_text(
        chat_id=user_id,
        message_id=ask_message_id,
        text="Uploading poster... Please wait."
    )

    new_poster_file_id = await download_and_upload_poster(client, message)

    if new_poster_file_id:
        if level == "series":
            update_poster_file_id(series_key, new_poster_file_id)
            await processing_msg.edit_text("Series poster updated successfully.")
            await send_main_series_message(client, user_id, get_series_by_key(series_key), main_message_id)
            temp_admin_data[user_id]["state"] = "SERIES_DETAILS_VIEW"
        elif level == "language":
            add_or_update_language(series_key, language_name, new_poster_file_id)
            await processing_msg.edit_text("Language poster updated successfully.")
            await send_language_management_message(client, user_id, series_key, main_message_id)
            temp_admin_data[user_id]["state"] = "MANAGE_LANGUAGES"
        elif level == "season":
            add_or_update_season(series_key, language_name, season_name, new_poster_file_id)
            await processing_msg.edit_text("Season poster updated successfully.")
            await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
            temp_admin_data[user_id]["state"] = "MANAGE_SEASONS"
    else:
        await processing_msg.edit_text("Failed to upload new poster.")

    # Clean up temp data for poster
    temp_admin_data[user_id].pop("current_language", None)
    temp_admin_data[user_id].pop("current_season", None)
    temp_admin_data[user_id].pop("ask_message_id", None)

@Client.on_callback_query(filters.regex(r"^edit_series_details:") & filters.user(ADMINS))
async def edit_series_details_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    series_key = callback_query.data.split(":")[1]
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    series_data = get_series_by_key(series_key)

    if not series_data:
        await callback_query.answer("Series not found.", show_alert=True)
        return

    text = (
        f"**Editing Series Details for:** <code>{series_data.get('title', 'N/A')}</code>\n\n"
        "Send the updated details in the format:\n"
        "Title: <new title>\n"
        "Released On: <new year>\n"
        "Genre: <new genre>\n"
        "Rating: <new rating>\n\n"
        "You can omit fields you don't want to change. Example:\n"
        "Title: New Dark Title\nRating: 9.0"
    )
    
    await client.edit_message_text(
        chat_id=user_id,
        message_id=main_message_id,
        text=text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data=f"back_to_series:{series_key}")]])
    )
    temp_admin_data[user_id]["state"] = "EDITING_SERIES_TEXT"
    temp_admin_data[user_id]["current_series_key"] = series_key

async def process_edit_series_text(client: Client, message: Message, input_text: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    main_message_id = temp_admin_data[user_id].get("main_message_id")

    if not series_key:
        await message.reply("Error: Series key not found in session.")
        return

    updates = {}
    lines = input_text.split('\n')
    for line in lines:
        if ':' in line:
            field, value = line.split(':', 1)
            field = field.strip().lower().replace(' ', '_')
            value = value.strip()
            if field in ['title', 'released_on', 'genre', 'rating']:
                updates[field] = value
    
    if updates:
        for field, value in updates.items():
            update_series_field(series_key, field, value)
        await message.reply("Series details updated successfully.")
    else:
        await message.reply("No valid fields to update found in your message.")

    series_data = get_series_by_key(series_key)
    await send_main_series_message(client, user_id, series_data, main_message_id)
    temp_admin_data[user_id]["state"] = "SERIES_DETAILS_VIEW"

@Client.on_callback_query(filters.regex(r"^delete_language:") & filters.user(ADMINS))
async def delete_language_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    _, series_key, language_name = callback_query.data.split(":")
    main_message_id = temp_admin_data[user_id].get("main_message_id")

    if delete_language(series_key, language_name):
        await callback_query.answer(f"Language '{language_name}' deleted.", show_alert=True)
    else:
        await callback_query.answer(f"Failed to delete language '{language_name}'.", show_alert=True)
    
    await send_language_management_message(client, user_id, series_key, main_message_id)
    temp_admin_data[user_id]["state"] = "MANAGE_LANGUAGES"

@Client.on_callback_query(filters.regex(r"^delete_season:") & filters.user(ADMINS))
async def delete_season_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    _, series_key, language_name, season_name = callback_query.data.split(":")
    main_message_id = temp_admin_data[user_id].get("main_message_id")

    if delete_season(series_key, language_name, season_name):
        await callback_query.answer(f"Season '{season_name}' deleted.", show_alert=True)
    else:
        await callback_query.answer(f"Failed to delete season '{season_name}'.", show_alert=True)
    
    await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
    temp_admin_data[user_id]["state"] = "MANAGE_SEASONS"

@Client.on_callback_query(filters.regex(r"^delete_quality:") & filters.user(ADMINS))
async def delete_quality_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    _, series_key, language_name, season_name, quality_name = callback_query.data.split(":")
    main_message_id = temp_admin_data[user_id].get("main_message_id")

    if delete_quality(series_key, language_name, season_name, quality_name):
        await callback_query.answer(f"Quality '{quality_name}' deleted.", show_alert=True)
    else:
        await callback_query.answer(f"Failed to delete quality '{quality_name}'.", show_alert=True)
    
    await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
    temp_admin_data[user_id]["state"] = "MANAGE_QUALITIES"

@Client.on_callback_query(filters.regex(r"^publish_series:") & filters.user(ADMINS))
async def publish_series_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    series_key = callback_query.data.split(":")[1]
    main_message_id = temp_admin_data[user_id].get("main_message_id")

    await client.edit_message_text(
        chat_id=user_id,
        message_id=main_message_id,
        text="Do you want to publish this series? NOTE: Once you publish this series, you can't edit it anymore. All the empty groups will be removed automatically.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Yes, Publish", callback_data=f"confirm_publish:{series_key}")],
            [InlineKeyboardButton("No, Cancel", callback_data=f"back_to_series:{series_key}")]
        ])
    )
    temp_admin_data[user_id]["state"] = "AWAITING_PUBLISH_CONFIRMATION"

@Client.on_callback_query(filters.regex(r"^confirm_publish:") & filters.user(ADMINS))
async def confirm_publish_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    series_key = callback_query.data.split(":")[1]
    main_message_id = temp_admin_data[user_id].get("main_message_id")

    if publish_series(series_key):
        await client.edit_message_text(
            chat_id=user_id,
            message_id=main_message_id,
            text="Published Successfully! This series is now live and cannot be edited via this UI."
        )
        temp_admin_data.pop(user_id, None) # Clear session data for this admin
    else:
        await client.edit_message_text(
            chat_id=user_id,
            message_id=main_message_id,
            text="Failed to publish series. Please try again."
        )
        await send_main_series_message(client, user_id, get_series_by_key(series_key), main_message_id)
        temp_admin_data[user_id]["state"] = "SERIES_DETAILS_VIEW"
