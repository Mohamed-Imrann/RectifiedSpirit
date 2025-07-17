import asyncio
import re
import uuid
import logging
import os
import shutil
import requests
import copy # Import copy module for deepcopy
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from imdb import Cinemagoer
from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, TMDB_API_KEY, LOG_CHANNEL, DB_CHANNEL, RAW_DB_CHANNEL, IMGBB_API_KEY, NO_POSTER_FOUND_IMG
from database.crazy_db import (
    add_series, get_series_by_key, add_or_update_language,
    get_languages, delete_language, add_or_update_season, get_seasons, delete_season,
    add_or_update_quality, get_qualities, get_quality_link, delete_quality,
    get_poster_file_id, update_poster_file_id, publish_series, get_series, get_specific_poster, # Import get_specific_poster
    update_series, delete_series, get_all_series_keys, get_all_series_titles
)
from utils import get_message_id, get_messages_in_range, delete_messages_from_user_chat, get_poster, find_most_similar_title, get_movie_info, upload_image_to_imgbb, get_poster_from_tmdb
from fuzzywuzzy import fuzz # Import fuzzywuzzy
from pyrogram.errors import MessageIdInvalid, FloodWait # Removed MessageNotFound

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Temporary storage for multi-step UI interactions
# Key: user_id, Value: dictionary of current state
temp_admin_data = {}

# Temporary storage for series creation/editing process
# {user_id: {"step": "...", "data": {...}}}
user_series_data = {}

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
NO_POSTER_FOUND_IMG = "https://envs.sh/esA.jpg" # Placeholder image

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
    """
    Downloads a poster (from URL or user-provided photo/video), uploads it to LOG_CHANNEL,
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

async def send_main_series_message(client: Client, user_id: int, series_data: dict, message_id: int = None):
    """Sends or edits the main series details message. Handles MessageIdInvalid errors."""
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
    except (MessageIdInvalid, FloodWait) as e: # Removed MessageNotFound
        logger.warning(f"Failed to edit main series message (ID: {message_id}): {e}. Attempting to send a new message.")
        # If editing fails, send a new message and update the stored message_id
        try:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_file_id,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML
            )
            temp_admin_data[user_id]["main_message_id"] = msg.id # Update stored message ID
            return msg.id
        except Exception as new_send_e:
            logger.error(f"Failed to send new main series message after edit failure: {new_send_e}")
            # Fallback to text if media fails again or initially
            try:
                msg = await client.send_message(
                    chat_id=user_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=enums.ParseMode.HTML
                )
                temp_admin_data[user_id]["main_message_id"] = msg.id
                return msg.id
            except Exception as final_e:
                logger.error(f"Completely failed to send any main series message: {final_e}")
                return None
    except Exception as e:
        logger.error(f"An unexpected error occurred sending/editing main series message: {e}")
        # Fallback to text if any other error
        try:
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
                temp_admin_data[user_id]["main_message_id"] = msg.id
                return msg.id
        except (MessageIdInvalid) as e_fallback: # Removed MessageNotFound
            logger.warning(f"Fallback text edit/send also failed: {e_fallback}. Message ID was {message_id}. Attempting to send new.")
            try:
                msg = await client.send_message(
                    chat_id=user_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=enums.ParseMode.HTML
                )
                temp_admin_data[user_id]["main_message_id"] = msg.id
                return msg.id
            except Exception as e_final_text:
                logger.error(f"Final fallback for text message also failed: {e_final_text}")
                return None
        except Exception as other_fallback_e:
            logger.error(f"Another unexpected error in fallback: {other_fallback_e}")
            return None


async def send_language_management_message(client: Client, user_id: int, series_key: str, message_id: int):
    """Sends or edits the language management message. Handles MessageIdInvalid errors."""
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

    # Determine which poster to use: series poster
    poster_to_use = series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=poster_to_use, caption=text, parse_mode=enums.ParseMode.HTML),
                reply_markup=reply_markup
            )
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_to_use,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML
            )
            return msg.id
    except (MessageIdInvalid, FloodWait) as e: # Removed MessageNotFound
        logger.warning(f"Failed to edit language management message (ID: {message_id}): {e}. Attempting to send a new message.")
        new_msg = await client.send_photo(
            chat_id=user_id,
            photo=poster_to_use,
            caption=text,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
        temp_admin_data[user_id]["main_message_id"] = new_msg.id # Update stored message ID
        return new_msg.id
    except Exception as e:
        logger.error(f"An unexpected error occurred editing language management message: {e}")
        await client.send_message(user_id, "Error updating language management display. Please try again.")
        return None


async def send_season_management_message(client: Client, user_id: int, series_key: str, language_name: str, message_id: int):
    """Sends or edits the season management message. Handles MessageIdInvalid errors."""
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

    # Determine which poster to use: language poster, then series poster
    poster_to_use = current_lang.get("poster_file_id") or series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=poster_to_use, caption=text, parse_mode=enums.ParseMode.HTML),
                reply_markup=reply_markup
            )
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_to_use,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML
            )
            return msg.id
    except (MessageIdInvalid, FloodWait) as e: # Removed MessageNotFound
        logger.warning(f"Failed to edit season management message (ID: {message_id}): {e}. Attempting to send a new message.")
        new_msg = await client.send_photo(
            chat_id=user_id,
            photo=poster_to_use,
            caption=text,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
        temp_admin_data[user_id]["main_message_id"] = new_msg.id # Update stored message ID
        return new_msg.id
    except Exception as e:
        logger.error(f"An unexpected error occurred editing season management message: {e}")
        await client.send_message(user_id, "Error updating season management display. Please try again.")
        return None


async def send_quality_management_message(client: Client, user_id: int, series_key: str, language_name: str, season_name: str, message_id: int):
    """Sends or edits the quality management message. Handles MessageIdInvalid errors."""
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

    # Determine which poster to use: season poster, then language poster, then series poster
    poster_to_use = current_season.get("poster_file_id") or current_lang.get("poster_file_id") or series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=poster_to_use, caption=text, parse_mode=enums.ParseMode.HTML),
                reply_markup=reply_markup
            )
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_to_use,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML
            )
            return msg.id
    except (MessageIdInvalid, FloodWait) as e: # Removed MessageNotFound
        logger.warning(f"Failed to edit quality management message (ID: {message_id}): {e}. Attempting to send a new message.")
        new_msg = await client.send_photo(
            chat_id=user_id,
            photo=poster_to_use,
            caption=text,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
        temp_admin_data[user_id]["main_message_id"] = new_msg.id # Update stored message ID
        return new_msg.id
    except Exception as e:
        logger.error(f"An unexpected error occurred editing quality management message: {e}")
        await client.send_message(user_id, "Error updating quality management display. Please try again.")
        return None

# --- Command Handlers ---

@Client.on_message(filters.command('newseries') & filters.user(ADMINS))
async def new_series_command(client: Client, message: Message):
    user_id = message.from_user.id
    user_series_data[user_id] = {"step": "ask_title", "data": {"key": None, "title": None, "overview": None, "poster_path": None, "languages": {}}}
    await message.reply_text("Okay, let's create a new series. Please send me the **title** of the series.")

@Client.on_message(filters.command("editseries") & filters.user(ADMINS))
async def edit_series_command(client: Client, message: Message):
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text("Please provide the series key to edit. Example: `/editseries S001`")
        return

    series_key = args[1].upper()
    series_data = await get_series_by_key(series_key)
    if not series_data:
        await message.reply_text(f"No series found with key `{series_key}`.")
        return

    user_series_data[user_id] = {"step": "edit_menu", "data": series_data}
    await send_edit_menu(message, series_data)

@Client.on_message(filters.command("cloneseries") & filters.user(ADMINS))
async def clone_series_command(client: Client, message: Message):
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text("Please provide the series key to clone. Example: `/cloneseries S001`")
        return

    original_key = args[1].upper()
    original_series_data = await get_series_by_key(original_key)
    if not original_series_data:
        await message.reply_text(f"No series found with key `{original_key}` to clone.")
        return

    # Create a copy and mark it as unpublished
    cloned_data = original_series_data.copy()
    cloned_data.pop("_id", None) # Remove MongoDB _id
    cloned_data["key"] = None # Will be set by user
    cloned_data["title"] = f"CLONE - {cloned_data.get('title', 'Untitled')}"
    cloned_data["published"] = False # Mark as unpublished

    user_series_data[user_id] = {"step": "ask_clone_key", "data": cloned_data}
    await message.reply_text(f"Cloning series `{original_key}`. Please provide a **new unique key** for the cloned series (e.g., `S002`).")

@Client.on_message(filters.command("seriview") & filters.user(ADMINS))
async def view_series_command(client: Client, message: Message):
    all_keys = await get_all_series_keys()
    if not all_keys:
        await message.reply_text("No series found in the database.")
        return

    text = "**All Series Keys:**\n\n"
    buttons = []
    for key in all_keys:
        text += f"`{key}`\n"
        buttons.append(InlineKeyboardButton(f"Edit {key}", callback_data=f"edit_series_{key}"))
    
    # Arrange buttons in rows of 3
    keyboard_rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard_rows))


@Client.on_message(filters.text & filters.private & filters.user(ADMINS) & ~filters.command(["newseries", "editseries", "cloneseries", "seriview"]))
async def handle_series_input(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in user_series_data:
        return # Not in a series creation/edit flow

    current_step = user_series_data[user_id]["step"]
    series_data = user_series_data[user_id]["data"]

    if current_step == "ask_title":
        title = message.text
        movie_info = await get_movie_info(title, TMDB_API_KEY)
        if movie_info:
            series_data["title"] = movie_info["title"]
            series_data["overview"] = movie_info["overview"]
            series_data["poster_path"] = movie_info["poster_path"]
            user_series_data[user_id]["step"] = "ask_key"
            await message.reply_text(
                f"Found details for **{movie_info['title']}**.\n\n"
                f"Overview: {movie_info['overview']}\n"
                f"Poster: {movie_info['poster_url'] if movie_info['poster_url'] else 'N/A'}\n\n"
                "Please provide a **unique key** for this series (e.g., `S001`)."
            )
        else:
            await message.reply_text("Could not find series details. Please try a different title or provide it manually.")
            # Optionally, allow manual input for title/overview/poster
            # For now, let's just ask for title again
            await message.reply_text("Please send me the **title** of the series again.")

    elif current_step == "ask_key":
        key = message.text.upper()
        if not key.startswith("S") or not key[1:].isdigit() or len(key) != 4:
            await message.reply_text("Invalid key format. Please use `S` followed by three digits (e.g., `S001`).")
            return
        
        existing_series = await get_series_by_key(key)
        if existing_series:
            await message.reply_text(f"Series with key `{key}` already exists. Please choose a different unique key.")
            return
        
        series_data["key"] = key
        user_series_data[user_id]["step"] = "add_language"
        await message.reply_text(f"Series key set to `{key}`. Now, let's add a language. Please send the **language name** (e.g., `English`).")

    elif current_step == "ask_clone_key":
        key = message.text.upper()
        if not key.startswith("S") or not key[1:].isdigit() or len(key) != 4:
            await message.reply_text("Invalid key format. Please use `S` followed by three digits (e.g., `S001`).")
            return
        
        existing_series = await get_series_by_key(key)
        if existing_series:
            await message.reply_text(f"Series with key `{key}` already exists. Please choose a different unique key for the cloned series.")
            return
        
        series_data["key"] = key
        # Add the cloned series to DB
        success = await add_series(series_data)
        if success:
            await message.reply_text(f"Series `{series_data['title']}` cloned successfully with new key `{key}`. It is currently **unpublished**.")
            del user_series_data[user_id]
        else:
            await message.reply_text("Failed to clone series. Please try again.")
            del user_series_data[user_id]

    elif current_step == "add_language":
        lang_name = message.text
        lang_code = lang_name.lower().replace(" ", "_") # Simple code generation
        series_data["languages"][lang_code] = {"name": lang_name, "seasons": {}}
        user_series_data[user_id]["step"] = "add_season"
        user_series_data[user_id]["current_lang_code"] = lang_code
        await message.reply_text(f"Language '{lang_name}' added. Now, send the **season number** (e.g., `1`).")

    elif current_step == "add_season":
        season_num = message.text
        current_lang_code = user_series_data[user_id]["current_lang_code"]
        if not season_num.isdigit():
            await message.reply_text("Invalid season number. Please send a digit (e.g., `1`).")
            return
        
        season_name = f"Season {season_num}" # Default season name
        series_data["languages"][current_lang_code]["seasons"][season_num] = {"name": season_name, "files": []}
        user_series_data[user_id]["step"] = "add_file"
        user_series_data[user_id]["current_season_num"] = season_num
        await message.reply_text(f"Season {season_num} added. Now, forward me a **file** or send a **link** for this season. Send `/done` when finished with files for this season.")

    elif current_step == "add_file":
        current_lang_code = user_series_data[user_id]["current_lang_code"]
        current_season_num = user_series_data[user_id]["current_season_num"]

        if message.text == "/done":
            user_series_data[user_id]["step"] = "season_options"
            await message.reply_text(
                "Finished adding files for this season. What's next?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Add another season", callback_data="add_another_season")],
                    [InlineKeyboardButton("Add another language", callback_data="add_another_language")],
                    [InlineKeyboardButton("Save & Publish Series", callback_data="save_publish_series")]
                ])
            )
            return

        file_info = {}
        if message.document:
            file_info = {
                "type": "document",
                "file_id": message.document.file_id,
                "file_name": message.document.file_name,
                "caption": message.caption,
                "link": None # No direct link for forwarded files, will be generated on demand
            }
        elif message.video:
            file_info = {
                "type": "video",
                "file_id": message.video.file_id,
                "file_name": message.video.file_name,
                "caption": message.caption,
                "link": None
            }
        elif message.text and (message.text.startswith("http://") or message.text.startswith("https://")):
            file_info = {
                "type": "link",
                "file_name": f"Link: {message.text[:30]}...",
                "link": message.text,
                "caption": None
            }
        else:
            await message.reply_text("Please forward a file or send a direct link.")
            return
        
        series_data["languages"][current_lang_code]["seasons"][current_season_num]["files"].append(file_info)
        await message.reply_text("File/Link added. Send another file/link or `/done`.")

async def send_edit_menu(message: Message, series_data: dict):
    key = series_data["key"]
    title = series_data["title"]
    published_status = "Published" if series_data.get("published", False) else "Unpublished"
    
    text = f"**Editing Series:** `{key}` - **{title}**\n"
    text += f"Status: {published_status}\n\n"
    text += "What would you like to edit?"

    buttons = [
        [InlineKeyboardButton("Edit Title/Overview/Poster", callback_data=f"edit_series_details_{key}")],
        [InlineKeyboardButton("Manage Languages", callback_data=f"manage_languages_{key}")],
        [InlineKeyboardButton("Delete Series", callback_data=f"delete_series_confirm_{key}")],
        [InlineKeyboardButton("Toggle Publish Status", callback_data=f"toggle_publish_{key}")],
        [InlineKeyboardButton("Done Editing", callback_data=f"done_editing_{key}")]
    ]
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^(edit_series_|manage_languages_|delete_series_confirm_|toggle_publish_|done_editing_|add_another_season|add_another_language|save_publish_series|confirm_delete_series_|cancel_delete_series_|edit_lang_|delete_lang_confirm_|add_season_to_lang_|manage_season_|edit_season_details_|manage_season_files_|delete_season_confirm_|add_file_to_season_|edit_file_|delete_file_confirm_|confirm_delete_file_|cancel_delete_file_|confirm_delete_season_|cancel_delete_season_|confirm_delete_lang_|cancel_delete_lang_)"))
async def series_callback_handler(client: Client, query):
    user_id = query.from_user.id
    data = query.data
    parts = data.split("_")
    action = parts[0]
    series_key = parts[2] if len(parts) > 2 else None # For actions like edit_series_S001

    if action == "edit": # From /seriview
        series_key = parts[2]
        series_data = await get_series_by_key(series_key)
        if series_data:
            user_series_data[user_id] = {"step": "edit_menu", "data": series_data}
            await send_edit_menu(query.message, series_data)
        else:
            await query.answer("Series not found.", show_alert=True)
        await query.answer()
        return

    if action == "edit_series_details":
        series_data = await get_series_by_key(series_key)
        if series_data:
            user_series_data[user_id] = {"step": "edit_details", "data": series_data}
            await query.message.edit_text(
                f"**Editing details for {series_data['title']}**\n\n"
                "Send the **new title** for the series. Or send `/skip` to keep current title."
            )
        await query.answer()
        return

    if action == "manage_languages":
        series_data = await get_series_by_key(series_key)
        if series_data:
            user_series_data[user_id] = {"step": "manage_languages_menu", "data": series_data}
            await send_language_menu(query.message, series_data)
        await query.answer()
        return

    if action == "delete_series_confirm":
        await query.message.edit_text(
            f"Are you sure you want to delete series `{series_key}`? This action cannot be undone.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Yes, Delete", callback_data=f"confirm_delete_series_{series_key}")],
                [InlineKeyboardButton("No, Cancel", callback_data=f"cancel_delete_series_{series_key}")]
            ])
        )
        await query.answer()
        return

    if action == "confirm_delete_series":
        await delete_series(series_key)
        await query.message.edit_text(f"Series `{series_key}` deleted successfully.")
        if user_id in user_series_data:
            del user_series_data[user_id]
        await query.answer()
        return

    if action == "cancel_delete_series":
        series_data = await get_series_by_key(series_key)
        if series_data:
            user_series_data[user_id] = {"step": "edit_menu", "data": series_data}
            await send_edit_menu(query.message, series_data)
        await query.answer()
        return

    if action == "toggle_publish":
        series_data = await get_series_by_key(series_key)
        if series_data:
            current_status = series_data.get("published", False)
            series_data["published"] = not current_status
            await update_series(series_key, {"published": series_data["published"]})
            await query.answer(f"Series `{series_key}` is now {'Published' if series_data['published'] else 'Unpublished'}.", show_alert=True)
            user_series_data[user_id] = {"step": "edit_menu", "data": series_data} # Refresh menu
            await send_edit_menu(query.message, series_data)
        await query.answer()
        return

    if action == "done_editing":
        if user_id in user_series_data:
            del user_series_data[user_id]
        await query.message.edit_text(f"Finished editing series `{series_key}`.")
        await query.answer()
        return

    if action == "add_another_season":
        series_data = user_series_data[user_id]["data"]
        current_lang_code = user_series_data[user_id]["current_lang_code"]
        user_series_data[user_id]["step"] = "add_season"
        await query.message.edit_text(f"Okay, adding another season for '{series_data['languages'][current_lang_code]['name']}'. Send the **season number** (e.g., `2`).")
        await query.answer()
        return

    if action == "add_another_language":
        series_data = user_series_data[user_id]["data"]
        user_series_data[user_id]["step"] = "add_language"
        await query.message.edit_text("Okay, let's add another language. Please send the **language name** (e.g., `Hindi`).")
        await query.answer()
        return

    if action == "save_publish_series":
        series_data = user_series_data[user_id]["data"]
        series_data["published"] = True # Mark as published on save
        success = await add_series(series_data) if not await get_series_by_key(series_data["key"]) else await update_series(series_data["key"], series_data)
        
        if success:
            await query.message.edit_text(f"Series `{series_data['title']}` saved and published successfully!")
            del user_series_data[user_id]
        else:
            await query.message.edit_text("Failed to save/publish series. Please try again.")
        await query.answer()
        return

    # --- Language Management Callbacks ---
    if action == "edit_lang":
        series_key = parts[2]
        lang_code = parts[3]
        series_data = await get_series_by_key(series_key)
        if series_data:
            user_series_data[user_id] = {"step": "manage_lang_details", "data": series_data, "current_lang_code": lang_code}
            await send_lang_details_menu(query.message, series_data, lang_code)
        await query.answer()
        return

    if action == "delete_lang_confirm":
        series_key = parts[3]
        lang_code = parts[4]
        series_data = await get_series_by_key(series_key)
        if series_data and lang_code in series_data.get("languages", {}):
            lang_name = series_data["languages"][lang_code]["name"]
            await query.message.edit_text(
                f"Are you sure you want to delete language '{lang_name}' from series `{series_key}`? This will delete all its seasons and files.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Yes, Delete Language", callback_data=f"confirm_delete_lang_{series_key}_{lang_code}")],
                    [InlineKeyboardButton("No, Cancel", callback_data=f"cancel_delete_lang_{series_key}_{lang_code}")]
                ])
            )
        await query.answer()
        return

    if action == "confirm_delete_lang":
        series_key = parts[3]
        lang_code = parts[4]
        series_data = await get_series_by_key(series_key)
        if series_data and lang_code in series_data.get("languages", {}):
            del series_data["languages"][lang_code]
            await update_series(series_key, {"languages": series_data["languages"]})
            await query.message.edit_text(f"Language '{lang_code}' deleted from series `{series_key}`.")
            user_series_data[user_id] = {"step": "manage_languages_menu", "data": series_data} # Refresh menu
            await send_language_menu(query.message, series_data)
        await query.answer()
        return

    if action == "cancel_delete_lang":
        series_key = parts[3]
        lang_code = parts[4]
        series_data = await get_series_by_key(series_key)
        if series_data:
            user_series_data[user_id] = {"step": "manage_languages_menu", "data": series_data}
            await send_language_menu(query.message, series_data)
        await query.answer()
        return

    if action == "add_season_to_lang":
        series_key = parts[3]
        lang_code = parts[4]
        series_data = await get_series_by_key(series_key)
        if series_data:
            user_series_data[user_id] = {"step": "add_season_to_existing_lang", "data": series_data, "current_lang_code": lang_code}
            await query.message.edit_text(f"Adding a new season for '{series_data['languages'][lang_code]['name']}'. Please send the **season number** (e.g., `1`).")
        await query.answer()
        return

    # --- Season Management Callbacks ---
    if action == "manage_season":
        series_key = parts[2]
        lang_code = parts[3]
        season_num = parts[4]
        series_data = await get_series_by_key(series_key)
        if series_data:
            user_series_data[user_id] = {"step": "manage_season_menu", "data": series_data, "current_lang_code": lang_code, "current_season_num": season_num}
            await send_season_menu(query.message, series_data, lang_code, season_num)
        await query.answer()
        return

    if action == "delete_season_confirm":
        series_key = parts[3]
        lang_code = parts[4]
        season_num = parts[5]
        series_data = await get_series_by_key(series_key)
        if series_data and lang_code in series_data.get("languages", {}) and season_num in series_data["languages"][lang_code].get("seasons", {}):
            season_name = series_data["languages"][lang_code]["seasons"][season_num]["name"]
            await query.message.edit_text(
                f"Are you sure you want to delete season '{season_name}' from language '{lang_code}' in series `{series_key}`? This will delete all its files.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Yes, Delete Season", callback_data=f"confirm_delete_season_{series_key}_{lang_code}_{season_num}")],
                    [InlineKeyboardButton("No, Cancel", callback_data=f"cancel_delete_season_{series_key}_{lang_code}_{season_num}")]
                ])
            )
        await query.answer()
        return

    if action == "confirm_delete_season":
        series_key = parts[3]
        lang_code = parts[4]
        season_num = parts[5]
        series_data = await get_series_by_key(series_key)
        if series_data and lang_code in series_data.get("languages", {}) and season_num in series_data["languages"][lang_code].get("seasons", {}):
            del series_data["languages"][lang_code]["seasons"][season_num]
            await update_series(series_key, {"languages": series_data["languages"]})
            await query.message.edit_text(f"Season '{season_num}' deleted from language '{lang_code}' in series `{series_key}`.")
            user_series_data[user_id] = {"step": "manage_lang_details", "data": series_data, "current_lang_code": lang_code} # Refresh menu
            await send_lang_details_menu(query.message, series_data, lang_code)
        await query.answer()
        return

    if action == "cancel_delete_season":
        series_key = parts[3]
        lang_code = parts[4]
        season_num = parts[5]
        series_data = await get_series_by_key(series_key)
        if series_data:
            user_series_data[user_id] = {"step": "manage_season_menu", "data": series_data, "current_lang_code": lang_code, "current_season_num": season_num}
            await send_season_menu(query.message, series_data, lang_code, season_num)
        await query.answer()
        return

    if action == "add_file_to_season":
        series_key = parts[3]
        lang_code = parts[4]
        season_num = parts[5]
        series_data = await get_series_by_key(series_key)
        if series_data:
            user_series_data[user_id] = {"step": "add_file_to_existing_season", "data": series_data, "current_lang_code": lang_code, "current_season_num": season_num}
            await query.message.edit_text(f"Adding files for Season {season_num} of '{series_data['languages'][lang_code]['name']}'. Forward me a **file** or send a **link**. Send `/done` when finished.")
        await query.answer()
        return

    # --- File Management Callbacks ---
    if action == "manage_season_files":
        series_key = parts[3]
        lang_code = parts[4]
        season_num = parts[5]
        series_data = await get_series_by_key(series_key)
        if series_data:
            user_series_data[user_id] = {"step": "manage_files_menu", "data": series_data, "current_lang_code": lang_code, "current_season_num": season_num}
            await send_files_menu(query.message, series_data, lang_code, season_num)
        await query.answer()
        return

    if action == "delete_file_confirm":
        series_key = parts[3]
        lang_code = parts[4]
        season_num = parts[5]
        file_index = int(parts[6])
        series_data = await get_series_by_key(series_key)
        if series_data:
            files = series_data["languages"][lang_code]["seasons"][season_num]["files"]
            if 0 <= file_index < len(files):
                file_name = files[file_index].get("file_name", "Unnamed File")
                await query.message.edit_text(
                    f"Are you sure you want to delete file '{file_name}' from Season {season_num}?",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Yes, Delete File", callback_data=f"confirm_delete_file_{series_key}_{lang_code}_{season_num}_{file_index}")],
                        [InlineKeyboardButton("No, Cancel", callback_data=f"cancel_delete_file_{series_key}_{lang_code}_{season_num}_{file_index}")]
                    ])
                )
        await query.answer()
        return

    if action == "confirm_delete_file":
        series_key = parts[3]
        lang_code = parts[4]
        season_num = parts[5]
        file_index = int(parts[6])
        series_data = await get_series_by_key(series_key)
        if series_data:
            files = series_data["languages"][lang_code]["seasons"][season_num]["files"]
            if 0 <= file_index < len(files):
                deleted_file = files.pop(file_index)
                await update_series(series_key, {"languages": series_data["languages"]})
                await query.message.edit_text(f"File '{deleted_file.get('file_name', 'Unnamed File')}' deleted.")
                user_series_data[user_id] = {"step": "manage_files_menu", "data": series_data, "current_lang_code": lang_code, "current_season_num": season_num} # Refresh menu
                await send_files_menu(query.message, series_data, lang_code, season_num)
        await query.answer()
        return

    if action == "cancel_delete_file":
        series_key = parts[3]
        lang_code = parts[4]
        season_num = parts[5]
        file_index = int(parts[6]) # Not strictly needed but good for consistency
        series_data = await get_series_by_key(series_key)
        if series_data:
            user_series_data[user_id] = {"step": "manage_files_menu", "data": series_data, "current_lang_code": lang_code, "current_season_num": season_num}
            await send_files_menu(query.message, series_data, lang_code, season_num)
        await query.answer()
        return

    # --- Handlers for input during editing flows ---
@Client.on_message(filters.text & filters.private & filters.user(ADMINS) & ~filters.command(["newseries", "editseries", "cloneseries", "seriview"]))
async def handle_edit_input(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in user_series_data or not user_series_data[user_id].get("step").startswith("edit_"):
        return # Not in an editing flow that requires text input

    current_step = user_series_data[user_id]["step"]
    series_data = user_series_data[user_id]["data"]
    series_key = series_data["key"]

    if current_step == "edit_details":
        if message.text.lower() == "/skip":
            user_series_data[user_id]["step"] = "edit_overview"
            await message.reply_text("Send the **new overview** for the series. Or send `/skip` to keep current overview.")
            return

        new_title = message.text
        movie_info = await get_movie_info(new_title, TMDB_API_KEY)
        if movie_info:
            series_data["title"] = movie_info["title"]
            series_data["overview"] = movie_info["overview"]
            series_data["poster_path"] = movie_info["poster_path"]
            await update_series(series_key, {"title": series_data["title"], "overview": series_data["overview"], "poster_path": series_data["poster_path"]})
            await message.reply_text(f"Title, overview, and poster updated to **{series_data['title']}**.\n\n"
                                     "Returning to edit menu.",
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back to Edit Menu", callback_data=f"back_to_edit_menu_{series_key}")]])
                                    )
            user_series_data[user_id]["step"] = "edit_menu" # Go back to main edit menu
        else:
            await message.reply_text("Could not find details for the new title. Please try a different title or send `/skip`.")
        return

    if current_step == "add_season_to_existing_lang":
        season_num = message.text
        current_lang_code = user_series_data[user_id]["current_lang_code"]
        if not season_num.isdigit():
            await message.reply_text("Invalid season number. Please send a digit (e.g., `1`).")
            return
        
        if season_num in series_data["languages"][current_lang_code]["seasons"]:
            await message.reply_text(f"Season {season_num} already exists for this language. Please choose a different season number or manage the existing one.")
            return

        season_name = f"Season {season_num}"
        series_data["languages"][current_lang_code]["seasons"][season_num] = {"name": season_name, "files": []}
        await update_series(series_key, {"languages": series_data["languages"]})
        user_series_data[user_id]["step"] = "add_file_to_existing_season"
        user_series_data[user_id]["current_season_num"] = season_num
        await message.reply_text(f"Season {season_num} added. Now, forward me a **file** or send a **link** for this season. Send `/done` when finished with files for this season.")
        return

    if current_step == "add_file_to_existing_season":
        current_lang_code = user_series_data[user_id]["current_lang_code"]
        current_season_num = user_series_data[user_id]["current_season_num"]

        if message.text == "/done":
            user_series_data[user_id]["step"] = "manage_season_menu"
            await send_season_menu(message, series_data, current_lang_code, current_season_num)
            return

        file_info = {}
        if message.document:
            file_info = {
                "type": "document",
                "file_id": message.document.file_id,
                "file_name": message.document.file_name,
                "caption": message.caption,
                "link": None
            }
        elif message.video:
            file_info = {
                "type": "video",
                "file_id": message.video.file_id,
                "file_name": message.video.file_name,
                "caption": message.caption,
                "link": None
            }
        elif message.text and (message.text.startswith("http://") or message.text.startswith("https://")):
            file_info = {
                "type": "link",
                "file_name": f"Link: {message.text[:30]}...",
                "link": message.text,
                "caption": None
            }
        else:
            await message.reply_text("Please forward a file or send a direct link.")
            return
        
        series_data["languages"][current_lang_code]["seasons"][current_season_num]["files"].append(file_info)
        await update_series(series_key, {"languages": series_data["languages"]})
        await message.reply_text("File/Link added. Send another file/link or `/done`.")
        return

# --- Helper functions for menus ---
async def send_language_menu(message: Message, series_data: dict):
    key = series_data["key"]
    text = f"**Managing Languages for `{series_data['title']}`:**\n\n"
    buttons = []
    
    languages = series_data.get("languages", {})
    if languages:
        for lang_code, lang_data in languages.items():
            lang_name = lang_data.get("name", lang_code.upper())
            text += f"- {lang_name} (`{lang_code}`)\n"
            buttons.append([
                InlineKeyboardButton(f"Edit {lang_name}", callback_data=f"edit_lang_{key}_{lang_code}"),
                InlineKeyboardButton(f"Delete {lang_name}", callback_data=f"delete_lang_confirm_{key}_{lang_code}")
            ])
    else:
        text += "No languages added yet."

    buttons.append([InlineKeyboardButton("Add New Language", callback_data=f"add_language_to_series_{key}")])
    buttons.append([InlineKeyboardButton("Back to Main Edit Menu", callback_data=f"back_to_edit_menu_{key}")])
    
    await message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^add_language_to_series_"))
async def add_language_to_series_callback(client: Client, query):
    user_id = query.from_user.id
    series_key = query.data.split("_")[4]
    series_data = await get_series_by_key(series_key)
    if series_data:
        user_series_data[user_id] = {"step": "add_language_to_existing_series", "data": series_data}
        await query.message.edit_text("Please send the **language name** (e.g., `Spanish`).")
    await query.answer()

@Client.on_message(filters.text & filters.private & filters.user(ADMINS) & ~filters.command(["newseries", "editseries", "cloneseries", "seriview"]))
async def handle_add_language_to_existing_series(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in user_series_data or user_series_data[user_id]["step"] != "add_language_to_existing_series":
        return

    series_data = user_series_data[user_id]["data"]
    series_key = series_data["key"]
    lang_name = message.text
    lang_code = lang_name.lower().replace(" ", "_")

    if lang_code in series_data.get("languages", {}):
        await message.reply_text(f"Language '{lang_name}' already exists. Please choose a different name or manage the existing one.")
        return

    series_data["languages"][lang_code] = {"name": lang_name, "seasons": {}}
    await update_series(series_key, {"languages": series_data["languages"]})
    
    user_series_data[user_id]["step"] = "manage_languages_menu" # Go back to language menu
    await message.reply_text(f"Language '{lang_name}' added. Returning to language management.",
                             reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back to Language Menu", callback_data=f"manage_languages_{series_key}")]])
                            )
    await send_language_menu(message, series_data) # Refresh the menu
    
async def send_lang_details_menu(message: Message, series_data: dict, lang_code: str):
    key = series_data["key"]
    lang_name = series_data["languages"][lang_code]["name"]
    text = f"**Managing Language: {lang_name} (`{lang_code}`) for `{series_data['title']}`**\n\n"
    text += "Seasons:\n"
    
    seasons = series_data["languages"][lang_code].get("seasons", {})
    buttons = []
    if seasons:
        for season_num, season_data in seasons.items():
            season_name = season_data.get("name", f"Season {season_num}")
            text += f"- {season_name} (Files: {len(season_data.get('files', []))})\n"
            buttons.append([
                InlineKeyboardButton(f"Manage {season_name}", callback_data=f"manage_season_{key}_{lang_code}_{season_num}"),
                InlineKeyboardButton(f"Delete {season_name}", callback_data=f"delete_season_confirm_{key}_{lang_code}_{season_num}")
            ])
    else:
        text += "No seasons added yet for this language."

    buttons.append([InlineKeyboardButton("Add New Season", callback_data=f"add_season_to_lang_{key}_{lang_code}")])
    buttons.append([InlineKeyboardButton("Back to Language List", callback_data=f"manage_languages_{key}")])
    
    await message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

async def send_season_menu(message: Message, series_data: dict, lang_code: str, season_num: str):
    key = series_data["key"]
    lang_name = series_data["languages"][lang_code]["name"]
    season_name = series_data["languages"][lang_code]["seasons"][season_num]["name"]
    text = f"**Managing Season: {season_name} for {lang_name} in `{series_data['title']}`**\n\n"
    text += "Files:\n"
    
    files = series_data["languages"][lang_code]["seasons"][season_num].get("files", [])
    buttons = []
    if files:
        for i, file_info in enumerate(files):
            file_display_name = file_info.get("file_name", f"File {i+1}")
            text += f"- {file_display_name}\n"
            buttons.append([
                InlineKeyboardButton(f"Delete {file_display_name}", callback_data=f"delete_file_confirm_{key}_{lang_code}_{season_num}_{i}")
            ])
    else:
        text += "No files added yet for this season."

    buttons.append([InlineKeyboardButton("Add New File/Link", callback_data=f"add_file_to_season_{key}_{lang_code}_{season_num}")])
    buttons.append([InlineKeyboardButton("Back to Language Details", callback_data=f"edit_lang_{key}_{lang_code}")])
    
    await message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^back_to_edit_menu_"))
async def back_to_edit_menu_callback(client: Client, query):
    user_id = query.from_user.id
    series_key = query.data.split("_")[4]
    series_data = await get_series_by_key(series_key)
    if series_data:
        user_series_data[user_id] = {"step": "edit_menu", "data": series_data}
        await send_edit_menu(query.message, series_data)
    await query.answer()
