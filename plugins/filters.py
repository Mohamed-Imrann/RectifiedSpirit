import asyncio
import re
import uuid
import logging
import os
import shutil
import requests
import copy
import difflib
import random
import pyrogram
from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    Message, 
    CallbackQuery, 
    InputMediaPhoto, 
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    ReplyKeyboardRemove
)
from pyrogram.errors import MessageIdInvalid, FloodWait, UserNotParticipant, MediaEmpty
from imdb import Cinemagoer
from fuzzywuzzy import fuzz
from info import (
    ADMINS, 
    TMP_DOWNLOAD_DIRECTORY, 
    TMDB_API_KEY, 
    LOG_CHANNEL, 
    DB_CHANNEL, 
    RAW_DB_CHANNEL, 
    SPELL_CHECK_IMAGE, 
    NO_POSTER_FOUND_IMG,
    AUTH_CHANNEL,
    PICS,
    NOR_IMG,
    SPELL_IMG
)
from database.crazy_db import (
    db,
    add_series, 
    get_series_by_key, 
    update_series_field, 
    add_or_update_language,
    get_languages, 
    delete_language, 
    add_or_update_season, 
    get_seasons, 
    delete_season,
    add_or_update_quality, 
    get_qualities, 
    get_quality_link, 
    delete_quality,
    get_poster_file_id, 
    update_poster_file_id, 
    publish_series, 
    get_series, 
    search_published_series,
    get_specific_poster
)
from database.gfilters_mdb import (
    find_gfilter,
    get_gfilters
)
from utils import (
    get_message_id, 
    get_messages_in_range, 
    delete_messages_from_user_chat, 
    get_poster, 
    find_most_similar_title, 
    temp, 
    chunk_buttons,
    get_size,
    is_subscribed,
    search_gagala,
    get_settings,
    save_group_settings,
    log_user_activity,
    log_error,
    log_info,
    log_warning,
    log_debug,
    get_random_pic,
    get_spell_check_image,
    is_admin_user,
    validate_url,
    format_caption,
    truncate_text,
    escape_markdown,
    get_file_type,
    format_file_size,
    clean_file_name,
    get_duration_string,
    is_valid_file_id,
    generate_random_string
)

# Initialize logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Initialize IMDb
imdb = Cinemagoer()

# TMDB Constants
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

# Requestor for user-specific callbacks in groups
requestor = {}

async def DeleteMessage(msg):
    """Delete message after 10 minutes"""
    try:
        await asyncio.sleep(600)
        await msg.delete()
        log_debug(f"Auto-deleted message {msg.id}")
    except Exception as e:
        log_error(f"Error auto-deleting message: {e}")

def find_close_matches(query, possibilities, n=3, cutoff=0.6):
    """Find close matches using difflib"""
    try:
        return difflib.get_close_matches(query, possibilities, n, cutoff)
    except Exception as e:
        log_error(f"Error finding close matches: {e}")
        return []

def get_series_poster_for_user(series_key):
    """Get series poster for user display, handling both file IDs and URLs"""
    try:
        poster_source = get_poster_file_id(series_key)
        if poster_source:
            if poster_source.startswith(('http://', 'https://')):
                log_info(f"Poster for series {series_key} is a URL: {poster_source}")
                return poster_source
            elif len(poster_source) > 20 and poster_source.replace('_', '').replace('-', '').isalnum():
                log_info(f"Poster for series {series_key} is a File ID: {poster_source}")
                return poster_source
            else:
                log_warning(f"Poster for series {series_key} is an unrecognized format: {poster_source}. Falling back to default.")
                return NO_POSTER_FOUND_IMG
        else:
            log_info(f"No poster found for series {series_key}. Using default.")
            return NO_POSTER_FOUND_IMG
    except Exception as e:
        log_error(f"Error getting series poster: {e}")
        return NO_POSTER_FOUND_IMG

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
            log_info(f"Fetching TMDB details for ID: {tmdb_id}, type: {media_type}")
            url = f"{TMDB_BASE_URL}/{media_type}/{tmdb_id}"
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            genres = [g['name'] for g in data.get('genres', [])][:3]
            poster_path = data.get('poster_path')
            poster_url = f"{TMDB_IMAGE_BASE_URL}{poster_path}" if poster_path else NO_POSTER_FOUND_IMG

            if media_type == 'tv':
                title = data.get('name', 'N/A')
                first_air = data.get('first_air_date', '')
                last_air = data.get('last_air_date', '')
                if first_air and last_air:
                    year = f"{first_air.split('-')[0]} - {last_air.split('-')[0]}"
                elif first_air:
                    year = first_air.split('-')[0]
                else:
                    year = 'N/A'
            else:  # movie
                title = data.get('title', 'N/A')
                release_date = data.get('release_date', '')
                year = release_date.split('-')[0] if release_date else 'N/A'
            
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
            log_info(f"Successfully fetched TMDB data for {title}")
            return result
        else:
            log_info(f"Searching TMDB for: {query}")
            search_results = []
            
            # Search TV shows
            url_tv = f"{TMDB_BASE_URL}/search/tv"
            response_tv = requests.get(url_tv, headers=headers, params={"query": query}, timeout=10)
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
            response_movie = requests.get(url_movie, headers=headers, params={"query": query}, timeout=10)
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
            
            log_info(f"Found {len(search_results)} TMDB results for {query}")
            return search_results[:10]

    except requests.exceptions.RequestException as e:
        log_error(f"TMDB API request error: {e}")
        return None
    except Exception as e:
        log_error(f"Unexpected error in TMDB search: {e}")
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
        log_info("Starting poster download and upload process")
        
        if poster_url:
            log_info(f"Downloading poster from URL: {poster_url}")
            response = requests.get(poster_url, stream=True, timeout=30)
            response.raise_for_status()
            download_path = os.path.join(temp_dir, "poster.jpg")
            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            log_info("Successfully downloaded poster from URL")
            
        elif message and message.photo and message.photo.file_id:
            log_info("Downloading poster from user photo")
            download_path = await client.download_media(
                message.photo.file_id, 
                file_name=os.path.join(temp_dir, "poster.jpg")
            )
            
        elif message and message.video and message.video.thumbs and message.video.thumbs[0].file_id:
            log_info("Downloading poster from video thumbnail")
            download_path = await client.download_media(
                message.video.thumbs[0].file_id, 
                file_name=os.path.join(temp_dir, "poster.jpg")
            )
        else:
            log_warning("No valid poster source provided")
            return None

        if download_path and os.path.exists(download_path):
            log_info(f"Uploading poster to LOG_CHANNEL: {LOG_CHANNEL}")
            sent_msg = await client.send_photo(LOG_CHANNEL, photo=download_path, caption="Series Poster")
            file_id = sent_msg.photo.file_id
            log_info(f"Successfully uploaded poster, file_id: {file_id}")
            
            try:
                await sent_msg.delete()
                log_debug("Deleted temporary poster message from LOG_CHANNEL")
            except Exception as e:
                log_warning(f"Could not delete temporary poster message: {e}")
        else:
            log_error("Download path does not exist or download failed")
            
    except requests.exceptions.RequestException as e:
        log_error(f"Error downloading poster from URL: {e}")
    except Exception as e:
        log_error(f"Error in poster download/upload process: {e}")
    finally:
        if os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
                log_debug("Cleaned up temporary directory")
            except Exception as e:
                log_warning(f"Error cleaning up temp directory: {e}")
    
    return file_id

async def send_main_series_message(client: Client, user_id: int, series_data: dict, message_id: int = None):
    """Sends or edits the main series details message with comprehensive error handling"""
    try:
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
        log_info(f"Sending main series message for {series_key}")

        try:
            if message_id:
                await client.edit_message_media(
                    chat_id=user_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=poster_file_id, caption=text, parse_mode=enums.ParseMode.HTML),
                    reply_markup=reply_markup
                )
                log_info(f"Successfully edited main series message {message_id}")
                return message_id
            else:
                msg = await client.send_photo(
                    chat_id=user_id,
                    photo=poster_file_id,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=enums.ParseMode.HTML
                )
                log_info(f"Successfully sent new main series message {msg.id}")
                return msg.id
                
        except (MessageIdInvalid, FloodWait) as e:
            log_warning(f"Failed to edit main series message (ID: {message_id}): {e}. Attempting to send new message.")
            try:
                msg = await client.send_photo(
                    chat_id=user_id,
                    photo=poster_file_id,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=enums.ParseMode.HTML
                )
                temp.admin_data[user_id]["main_message_id"] = msg.id
                log_info(f"Successfully sent fallback main series message {msg.id}")
                return msg.id
            except Exception as new_send_e:
                log_error(f"Failed to send new main series message after edit failure: {new_send_e}")
                try:
                    msg = await client.send_message(
                        chat_id=user_id,
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=enums.ParseMode.HTML
                    )
                    temp.admin_data[user_id]["main_message_id"] = msg.id
                    log_info(f"Successfully sent text-only main series message {msg.id}")
                    return msg.id
                except Exception as final_e:
                    log_error(f"Completely failed to send any main series message: {final_e}")
                    return None
                    
        except Exception as e:
            log_error(f"Unexpected error sending/editing main series message: {e}")
            try:
                if message_id:
                    await client.edit_message_text(
                        chat_id=user_id,
                        message_id=message_id,
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=enums.ParseMode.HTML
                    )
                    log_info(f"Successfully edited as text message {message_id}")
                    return message_id
                else:
                    msg = await client.send_message(
                        chat_id=user_id,
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=enums.ParseMode.HTML
                    )
                    temp.admin_data[user_id]["main_message_id"] = msg.id
                    log_info(f"Successfully sent text message {msg.id}")
                    return msg.id
            except (MessageIdInvalid) as e_fallback:
                log_warning(f"Fallback text edit/send also failed: {e_fallback}. Attempting final send.")
                try:
                    msg = await client.send_message(
                        chat_id=user_id,
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=enums.ParseMode.HTML
                    )
                    temp.admin_data[user_id]["main_message_id"] = msg.id
                    log_info(f"Final fallback message sent successfully {msg.id}")
                    return msg.id
                except Exception as e_final_text:
                    log_error(f"Final fallback for text message also failed: {e_final_text}")
                    return None
            except Exception as other_fallback_e:
                log_error(f"Another unexpected error in fallback: {other_fallback_e}")
                return None
                
    except Exception as e:
        log_error(f"Critical error in send_main_series_message: {e}")
        return None

async def send_language_management_message(client: Client, user_id: int, series_key: str, message_id: int):
    """Sends or edits the language management message with comprehensive error handling"""
    try:
        series_data = get_series_by_key(series_key)
        if not series_data:
            log_error(f"Series not found for key: {series_key}")
            await client.send_message(user_id, "Series not found.")
            return

        languages = series_data.get("languages", [])
        
        text = f"<b>Series:</b> <code>{series_data.get('title', 'N/A')}</code>\n\n"
        text += "Select any Language group to add new Season/Part group inside them. Or click '+' button to add new Language group.\n\n"

        buttons = []
        for lang in languages:
            season_count = len(lang.get('seasons', []))
            buttons.append([
                InlineKeyboardButton(
                    f"{lang['name']} ({season_count} Seasons)", 
                    callback_data=f"manage_seasons:{series_key}:{lang['name']}"
                )
            ])
        
        buttons.append([InlineKeyboardButton("+ Language", callback_data=f"add_language:{series_key}")])
        buttons.append([InlineKeyboardButton("Back to Series", callback_data=f"back_to_series:{series_key}")])

        reply_markup = InlineKeyboardMarkup(buttons)
        poster_to_use = series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG

        log_info(f"Sending language management message for series {series_key}")

        try:
            if message_id:
                await client.edit_message_media(
                    chat_id=user_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=poster_to_use, caption=text, parse_mode=enums.ParseMode.HTML),
                    reply_markup=reply_markup
                )
                log_info(f"Successfully edited language management message {message_id}")
                return message_id
            else:
                msg = await client.send_photo(
                    chat_id=user_id,
                    photo=poster_to_use,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=enums.ParseMode.HTML
                )
                log_info(f"Successfully sent language management message {msg.id}")
                return msg.id
                
        except (MessageIdInvalid, FloodWait) as e:
            log_warning(f"Failed to edit language management message (ID: {message_id}): {e}. Sending new message.")
            new_msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_to_use,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML
            )
            temp.admin_data[user_id]["main_message_id"] = new_msg.id
            log_info(f"Successfully sent fallback language management message {new_msg.id}")
            return new_msg.id
            
        except Exception as e:
            log_error(f"Unexpected error editing language management message: {e}")
            await client.send_message(user_id, "Error updating language management display. Please try again.")
            return None
            
    except Exception as e:
        log_error(f"Critical error in send_language_management_message: {e}")
        return None

async def send_season_management_message(client: Client, user_id: int, series_key: str, language_name: str, message_id: int):
    """Sends or edits the season management message with comprehensive error handling"""
    try:
        series_data = get_series_by_key(series_key)
        if not series_data:
            log_error(f"Series not found for key: {series_key}")
            await client.send_message(user_id, "Series not found.")
            return

        current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
        if not current_lang:
            log_error(f"Language {language_name} not found in series {series_key}")
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
            quality_count = len(season.get('qualities', []))
            buttons.append([
                InlineKeyboardButton(
                    f"{season['name']} ({quality_count} Qualities)", 
                    callback_data=f"manage_qualities:{series_key}:{language_name}:{season['name']}"
                )
            ])
        
        buttons.append([InlineKeyboardButton("+ Season", callback_data=f"add_season:{series_key}:{language_name}")])
        buttons.append([InlineKeyboardButton("Change Poster for this Language", callback_data=f"change_language_poster:{series_key}:{language_name}")])
        buttons.append([InlineKeyboardButton(f"Delete '{language_name}' Group", callback_data=f"delete_language:{series_key}:{language_name}")])
        buttons.append([InlineKeyboardButton("Back to Languages", callback_data=f"manage_languages:{series_key}")])

        reply_markup = InlineKeyboardMarkup(buttons)
        poster_to_use = current_lang.get("poster_file_id") or series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG

        log_info(f"Sending season management message for {series_key}:{language_name}")

        try:
            if message_id:
                await client.edit_message_media(
                    chat_id=user_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=poster_to_use, caption=text, parse_mode=enums.ParseMode.HTML),
                    reply_markup=reply_markup
                )
                log_info(f"Successfully edited season management message {message_id}")
                return message_id
            else:
                msg = await client.send_photo(
                    chat_id=user_id,
                    photo=poster_to_use,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=enums.ParseMode.HTML
                )
                log_info(f"Successfully sent season management message {msg.id}")
                return msg.id
                
        except (MessageIdInvalid, FloodWait) as e:
            log_warning(f"Failed to edit season management message (ID: {message_id}): {e}. Sending new message.")
            new_msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_to_use,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML
            )
            temp.admin_data[user_id]["main_message_id"] = new_msg.id
            log_info(f"Successfully sent fallback season management message {new_msg.id}")
            return new_msg.id
            
        except Exception as e:
            log_error(f"Unexpected error editing season management message: {e}")
            await client.send_message(user_id, "Error updating season management display. Please try again.")
            return None
            
    except Exception as e:
        log_error(f"Critical error in send_season_management_message: {e}")
        return None

async def send_quality_management_message(client: Client, user_id: int, series_key: str, language_name: str, season_name: str, message_id: int):
    """Sends or edits the quality management message with comprehensive error handling"""
    try:
        series_data = get_series_by_key(series_key)
        if not series_data:
            log_error(f"Series not found for key: {series_key}")
            await client.send_message(user_id, "Series not found.")
            return

        current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
        current_season = next((s for s in current_lang.get("seasons", []) if s["name"].lower() == season_name.lower()), None) if current_lang else None
        
        if not current_season:
            log_error(f"Season {season_name} not found in {series_key}:{language_name}")
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
                InlineKeyboardButton(
                    f"{quality['name']}", 
                    callback_data=f"add_files:{series_key}:{language_name}:{season_name}:{quality['name']}"
                )
            ])
        
        buttons.append([InlineKeyboardButton("+ Quality", callback_data=f"add_quality:{series_key}:{language_name}:{season_name}")])
        buttons.append([InlineKeyboardButton("Change Poster for this Season", callback_data=f"change_season_poster:{series_key}:{language_name}:{season_name}")])
        buttons.append([InlineKeyboardButton(f"Delete '{season_name}' Group", callback_data=f"delete_season:{series_key}:{language_name}:{season_name}")])
        buttons.append([InlineKeyboardButton("Back to Seasons", callback_data=f"manage_seasons:{series_key}:{language_name}")])

        reply_markup = InlineKeyboardMarkup(buttons)
        poster_to_use = current_season.get("poster_file_id") or current_lang.get("poster_file_id") or series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG

        log_info(f"Sending quality management message for {series_key}:{language_name}:{season_name}")

        try:
            if message_id:
                await client.edit_message_media(
                    chat_id=user_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=poster_to_use, caption=text, parse_mode=enums.ParseMode.HTML),
                    reply_markup=reply_markup
                )
                log_info(f"Successfully edited quality management message {message_id}")
                return message_id
            else:
                msg = await client.send_photo(
                    chat_id=user_id,
                    photo=poster_to_use,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=enums.ParseMode.HTML
                )
                log_info(f"Successfully sent quality management message {msg.id}")
                return msg.id
                
        except (MessageIdInvalid, FloodWait) as e:
            log_warning(f"Failed to edit quality management message (ID: {message_id}): {e}. Sending new message.")
            new_msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_to_use,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML
            )
            temp.admin_data[user_id]["main_message_id"] = new_msg.id
            log_info(f"Successfully sent fallback quality management message {new_msg.id}")
            return new_msg.id
            
        except Exception as e:
            log_error(f"Unexpected error editing quality management message: {e}")
            await client.send_message(user_id, "Error updating quality management display. Please try again.")
            return None
            
    except Exception as e:
        log_error(f"Critical error in send_quality_management_message: {e}")
        return None

# --- Core Logic Functions ---

async def _new_series_command_logic(client: Client, message: Message, query: str):
    """Handle new series creation command logic"""
    try:
        user_id = message.from_user.id
        log_user_activity(user_id, "new_series_command", query)
        
        temp_msg = await message.reply_photo(
            photo=NO_POSTER_FOUND_IMG,
            caption="Searching TMDB and IMDb, please wait..."
        )
        
        log_info(f"Searching for series: {query}")
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
                    'media_type': item.get('kind'),
                    'source': 'imdb',
                    'poster_url': item.get('poster')
                })

        if not all_results:
            log_warning(f"No results found for query: {query}")
            await temp_msg.edit_caption("No results found on TMDB or IMDb for the provided series name.")
            return

        buttons = []
        for item in all_results:
            unique_id = str(uuid.uuid4())
            temp.admin_data[user_id][unique_id] = {
                'id': item.get('tmdb_id') if item.get('source') == 'tmdb' else item.get('imdb_id'),
                'media_type': item.get('media_type'),
                'source': item.get('source'),
                'query': query
            }
            buttons.append([
                InlineKeyboardButton(
                    text=f"{item.get('title', 'N/A')} ({item.get('year', 'N/A')}) - {item.get('source').upper()}",
                    callback_data=f"{item.get('source')}_select:{unique_id}"
                )
            ])
        
        reply_markup = InlineKeyboardMarkup(buttons)
        await temp_msg.edit_caption(
            "Select a series from below:\n\n"
            "**Choose Your Series:**",
            reply_markup=reply_markup
        )
        
        temp.admin_data[user_id]["state"] = "SELECTING_SERIES"
        temp.admin_data[user_id]["main_message_id"] = temp_msg.id
        log_info(f"Presented {len(all_results)} results to user {user_id}")
        
    except Exception as e:
        log_error(f"Error in new series command logic: {e}")
        await message.reply("An error occurred while searching for series. Please try again.")

async def _clone_series_command_logic(client: Client, message: Message, original_query: str, new_series_title: str):
    """Handle series cloning command logic"""
    try:
        user_id = message.from_user.id
        log_user_activity(user_id, "clone_series_command", f"{original_query} -> {new_series_title}")
        
        new_series_key = new_series_title.lower().replace(" ", "").replace("-", "")

        existing_series_by_new_key = get_series_by_key(new_series_key)
        if existing_series_by_new_key:
            log_warning(f"Series with key {new_series_key} already exists")
            await message.reply(f"A series with the title '{new_series_title}' (key: `{new_series_key}`) already exists. Please choose a different title.")
            return

        original_series_data = get_series_by_key(original_query)
        if not original_series_data:
            all_series = get_series()
            for s in all_series:
                if s.get('title', '').lower() == original_query.lower():
                    original_series_data = s
                    break
        
        if not original_series_data:
            log_warning(f"Original series not found: {original_query}")
            await message.reply(f"Original series '{original_query}' not found in the database.")
            return

        cloned_series_data = copy.deepcopy(original_series_data)
        cloned_series_data['_id'] = new_series_key
        cloned_series_data['title'] = new_series_title
        cloned_series_data['published'] = False

        if add_series(cloned_series_data):
            log_info(f"Successfully cloned series {original_query} to {new_series_title}")
            await message.reply(
                f"Series '{original_series_data.get('title', 'N/A')}' successfully cloned to '{new_series_title}' (key: `{new_series_key}`).\n\n"
                f"The new series is currently **unpublished**. You can now edit it using the UI via `/editseries {new_series_title}` and then publish it."
            )
        else:
            log_error(f"Failed to clone series {original_query} to {new_series_title}")
            await message.reply(f"Failed to clone series '{original_series_data.get('title', 'N/A')}' to '{new_series_title}'. It might already exist.")
            
    except Exception as e:
        log_error(f"Error in clone series command logic: {e}")
        await message.reply("An error occurred while cloning the series. Please try again.")

async def _edit_series_command_logic(client: Client, message: Message, query: str):
    """Handle edit series command logic"""
    try:
        user_id = message.from_user.id
        log_user_activity(user_id, "edit_series_command", query)

        series_key_lookup = query.lower().replace(" ", "").replace("-", "")
        series_data = get_series_by_key(series_key_lookup)

        if not series_data:
            log_info(f"Direct lookup failed for {query}, trying fuzzy search")
            all_series = get_series()
            fuzzy_matches = []
            
            for s in all_series:
                title = s.get('title', '')
                key = s.get('_id', '')
                
                title_ratio = fuzz.ratio(query.lower(), title.lower())
                key_ratio = fuzz.ratio(query.lower(), key.lower())
                
                if title_ratio >= 70 or key_ratio >= 70:
                    fuzzy_matches.append((s, max(title_ratio, key_ratio)))
            
            fuzzy_matches.sort(key=lambda x: x[1], reverse=True)
            
            if not fuzzy_matches:
                log_warning(f"No matches found for query: {query}")
                await message.reply(f"Series '{query}' not found in the database. Please check the title or key.")
                return
            elif len(fuzzy_matches) == 1:
                series_data = fuzzy_matches[0][0]
                log_info(f"Single fuzzy match found: {series_data.get('title')}")
            else:
                log_info(f"Multiple fuzzy matches found: {len(fuzzy_matches)}")
                buttons = []
                for item, score in fuzzy_matches[:5]:
                    unique_id = str(uuid.uuid4())
                    temp.admin_data[user_id][unique_id] = {
                        'series_key': item['_id']
                    }
                    buttons.append([
                        InlineKeyboardButton(
                            text=f"{item.get('title', 'N/A')} (Score: {score}%)",
                            callback_data=f"local_series_select:{unique_id}"
                        )
                    ])
                
                reply_markup = InlineKeyboardMarkup(buttons)
                temp_msg = await message.reply(
                    "Multiple series found. Please select one to edit:",
                    reply_markup=reply_markup
                )
                temp.admin_data[user_id]["state"] = "SELECTING_LOCAL_SERIES"
                temp.admin_data[user_id]["main_message_id"] = temp_msg.id
                return

        temp_msg = await message.reply_photo(
            photo=get_poster_file_id(series_data['_id']) or NO_POSTER_FOUND_IMG,
            caption=f"Loading series details for <code>{series_data.get('title', 'N/A')}</code>...",
            parse_mode=enums.ParseMode.HTML
        )

        temp.admin_data[user_id]["main_message_id"] = temp_msg.id
        temp.admin_data[user_id]["current_series_key"] = series_data['_id']
        temp.admin_data[user_id]["state"] = "SERIES_DETAILS_VIEW"
        
        await send_main_series_message(client, user_id, series_data, temp_msg.id)

        if series_data.get('published'):
            await client.send_message(
                user_id,
                "⚠️ **Warning:** This series is currently **published**. Any changes you make will **not** be live until you click 'Publish Series' again."
            )
            
        log_info(f"Successfully loaded series {series_data.get('title')} for editing")
        
    except Exception as e:
        log_error(f"Error in edit series command logic: {e}")
        await message.reply("An error occurred while loading the series. Please try again.")

async def _seriview_command_logic(client: Client, message: Message):
    """Handle series view command logic"""
    try:
        user_id = message.from_user.id
        log_user_activity(user_id, "seriview_command")
        
        all_series = get_series()

        if not all_series:
            log_info("No series found in database")
            await message.reply("No series found in the database.")
            return

        text = "<b>All Series in Database:</b>\n\n"
        buttons = []
        
        for s in all_series:
            title = s.get('title', 'N/A')
            series_key = s.get('_id', 'N/A')
            published_status = "✅ Published" if s.get('published', False) else "❌ Unpublished"
            
            text += f"• <code>{title}</code> (Key: <code>{series_key}</code>) - {published_status}\n"
            buttons.append([
                InlineKeyboardButton(f"Edit {title}", callback_data=f"local_series_select:{series_key}")
            ])
        
        reply_markup = InlineKeyboardMarkup(chunk_buttons(buttons, chunk_size=1))

        await message.reply_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True
        )
        
        log_info(f"Displayed {len(all_series)} series to user {user_id}")
        
    except Exception as e:
        log_error(f"Error in seriview command logic: {e}")
        await message.reply("An error occurred while fetching series list. Please try again.")

async def _process_language_input(client: Client, message: Message, language_name: str):
    """Process language input from admin"""
    try:
        user_id = message.from_user.id
        series_key = temp.admin_data[user_id].get("current_series_key")
        main_message_id = temp.admin_data[user_id].get("main_message_id")
        ask_message_id = temp.admin_data[user_id].get("ask_message_id")

        if not series_key:
            log_error(f"Series key not found in session for user {user_id}")
            await message.reply("Error: Series key not found in session.")
            return

        log_user_activity(user_id, "process_language_input", f"{series_key}:{language_name}")

        try:
            if ask_message_id:
                await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
            await message.delete()
        except Exception as e:
            log_warning(f"Could not delete prompt/user message: {e}")

        if add_or_update_language(series_key, language_name):
            log_info(f"Successfully added/updated language {language_name} for series {series_key}")
            confirmation_msg = await client.send_message(
                chat_id=user_id,
                text=f"Language '{language_name}' added/updated successfully.",
                reply_markup=ReplyKeyboardRemove()
            )
            asyncio.create_task(DeleteMessage(confirmation_msg))

            await send_language_management_message(client, user_id, series_key, main_message_id)
            temp.admin_data[user_id]["state"] = "MANAGE_LANGUAGES"
        else:
            log_error(f"Failed to add/update language {language_name} for series {series_key}")
            await message.reply("Failed to add/update language.")

        temp.admin_data[user_id].pop("ask_message_id", None)
        
    except Exception as e:
        log_error(f"Error processing language input: {e}")
        await message.reply("An error occurred while processing language input.")

async def _process_season_input(client: Client, message: Message, season_name: str):
    """Process season input from admin"""
    try:
        user_id = message.from_user.id
        series_key = temp.admin_data[user_id].get("current_series_key")
        language_name = temp.admin_data[user_id].get("current_language")
        main_message_id = temp.admin_data[user_id].get("main_message_id")
        ask_message_id = temp.admin_data[user_id].get("ask_message_id")

        if not all([series_key, language_name]):
            log_error(f"Series or language not found in session for user {user_id}")
            await message.reply("Error: Series or language not found in session.")
            return

        log_user_activity(user_id, "process_season_input", f"{series_key}:{language_name}:{season_name}")

        try:
            if ask_message_id:
                await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
            await message.delete()
        except Exception as e:
            log_warning(f"Could not delete prompt/user message: {e}")

        if add_or_update_season(series_key, language_name, season_name):
            log_info(f"Successfully added/updated season {season_name} for {series_key}:{language_name}")
            confirmation_msg = await client.send_message(
                chat_id=user_id,
                text=f"Season '{season_name}' added/updated successfully.",
                reply_markup=ReplyKeyboardRemove()
            )
            asyncio.create_task(DeleteMessage(confirmation_msg))

            await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
            temp.admin_data[user_id]["state"] = "MANAGE_SEASONS"
        else:
            log_error(f"Failed to add/update season {season_name} for {series_key}:{language_name}")
            await message.reply("Failed to add/update season.")

        temp.admin_data[user_id].pop("ask_message_id", None)
        
    except Exception as e:
        log_error(f"Error processing season input: {e}")
        await message.reply("An error occurred while processing season input.")

async def _process_quality_input(client: Client, message: Message, quality_name: str):
    """Process quality input from admin"""
    try:
        user_id = message.from_user.id
        series_key = temp.admin_data[user_id].get("current_series_key")
        language_name = temp.admin_data[user_id].get("current_language")
        season_name = temp.admin_data[user_id].get("current_season")
        main_message_id = temp.admin_data[user_id].get("main_message_id")
        ask_message_id = temp.admin_data[user_id].get("ask_message_id")

        if not all([series_key, language_name, season_name]):
            log_error(f"Series, language, or season not found in session for user {user_id}")
            await message.reply("Error: Series, language, or season not found in session.")
            return

        log_user_activity(user_id, "process_quality_input", f"{series_key}:{language_name}:{season_name}:{quality_name}")

        try:
            if ask_message_id:
                await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
            await message.delete()
        except Exception as e:
            log_warning(f"Could not delete prompt/user message: {e}")

        if add_or_update_quality(series_key, language_name, season_name, quality_name, "PENDING_LINK"):
            log_info(f"Successfully added/updated quality {quality_name} for {series_key}:{language_name}:{season_name}")
            confirmation_msg = await client.send_message(
                chat_id=user_id,
                text=f"Quality '{quality_name}' added/updated successfully. Now add files.",
                reply_markup=ReplyKeyboardRemove()
            )
            asyncio.create_task(DeleteMessage(confirmation_msg))

            await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
            temp.admin_data[user_id]["state"] = "MANAGE_QUALITIES"
        else:
            log_error(f"Failed to add/update quality {quality_name} for {series_key}:{language_name}:{season_name}")
            await message.reply("Failed to add/update quality.")

        temp.admin_data[user_id].pop("ask_message_id", None)
        
    except Exception as e:
        log_error(f"Error processing quality input: {e}")
        await message.reply("An error occurred while processing quality input.")

async def _process_first_file_input(client: Client, message: Message):
    """Process first file input from admin"""
    try:
        user_id = message.from_user.id
        ask_message_id = temp.admin_data[user_id].get("ask_message_id")
        
        log_user_activity(user_id, "process_first_file_input")
        
        channel_id, msg_id = await get_message_id(client, message)
        if not channel_id or not msg_id:
            try:
                await message.delete()
                if ask_message_id:
                    await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
            except Exception as e:
                log_warning(f"Could not delete invalid input/prompt: {e}")

            await client.send_message(user_id, "Invalid message. Please forward a message from a **DB Channel** or send a valid **post link from a DB Channel**.")
            temp.admin_data[user_id]["state"] = "IDLE"
            temp.admin_data[user_id].pop("ask_message_id", None)
            return

        temp.admin_data[user_id]["first_file_channel_id"] = channel_id
        temp.admin_data[user_id]["first_file_msg_id"] = msg_id
        temp.admin_data[user_id]["files_to_delete"].append(message.id)

        try:
            if ask_message_id:
                await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
        except Exception as e:
            log_warning(f"Could not delete prompt message: {e}")

        next_prompt_msg = await client.send_message(
            chat_id=user_id,
            text=f"Forward me the **last file** (with tag) for "
                 f"<code>{temp.admin_data[user_id]['current_language'].title()} - "
                 f"{temp.admin_data[user_id]['current_season'].title()} - "
                 f"{temp.admin_data[user_id]['current_quality']}</code>\n\n"
                 f"Go to first file: [Link](https://t.me/c/{abs(int(str(channel_id).replace('-100','')))}/{msg_id})",
            parse_mode=enums.ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
        temp.admin_data[user_id]["state"] = "AWAITING_LAST_FILE"
        temp.admin_data[user_id]["ask_message_id"] = next_prompt_msg.id
        
        log_info(f"First file processed: {channel_id}:{msg_id}")
        
    except Exception as e:
        log_error(f"Error processing first file input: {e}")
        await message.reply("An error occurred while processing the first file.")

async def _process_last_file_input(client: Client, message: Message):
    """Process last file input from admin"""
    try:
        user_id = message.from_user.id
        ask_message_id = temp.admin_data[user_id].get("ask_message_id")

        log_user_activity(user_id, "process_last_file_input")

        channel_id, msg_id = await get_message_id(client, message)
        if not channel_id or not msg_id:
            try:
                await message.delete()
                if ask_message_id:
                    await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
            except Exception as e:
                log_warning(f"Could not delete invalid input/prompt: {e}")
            await client.send_message(user_id, "Invalid message. Please forward a message from a **DB Channel** or send a valid **post link from a DB Channel**.")
            temp.admin_data[user_id]["state"] = "IDLE"
            temp.admin_data[user_id].pop("ask_message_id", None)
            return
        
        if channel_id != temp.admin_data[user_id]["first_file_channel_id"]:
            try:
                await message.delete()
                if ask_message_id:
                    await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
            except Exception as e:
                log_warning(f"Could not delete invalid input/prompt: {e}")
            await client.send_message(user_id, "Last file must be from the same channel as the first file.")
            temp.admin_data[user_id]["state"] = "IDLE"
            temp.admin_data[user_id].pop("ask_message_id", None)
            return

        temp.admin_data[user_id]["last_file_msg_id"] = msg_id
        temp.admin_data[user_id]["files_to_delete"].append(message.id)

        try:
            if ask_message_id:
                await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
        except Exception as e:
            log_warning(f"Could not delete prompt message: {e}")

        reply_keyboard = ReplyKeyboardMarkup(
            [
                [KeyboardButton("H.264"), KeyboardButton("H.265")],
                [KeyboardButton("H.265 10bit")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )

        next_prompt_msg = await client.send_message(
            chat_id=user_id,
            text=f"Send me the **codec field** for "
                 f"<code>{temp.admin_data[user_id]['current_language'].title()} - "
                 f"{temp.admin_data[user_id]['current_season'].title()} - "
                 f"{temp.admin_data[user_id]['current_quality']}</code>",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=reply_keyboard
        )
        temp.admin_data[user_id]["state"] = "AWAITING_CODEC_INPUT"
        temp.admin_data[user_id]["ask_message_id"] = next_prompt_msg.id
        
        log_info(f"Last file processed: {channel_id}:{msg_id}")
        
    except Exception as e:
        log_error(f"Error processing last file input: {e}")
        await message.reply("An error occurred while processing the last file.")

async def _process_codec_input(client: Client, message: Message, codec: str):
    """Process codec input from admin"""
    try:
        user_id = message.from_user.id
        ask_message_id = temp.admin_data[user_id].get("ask_message_id")
        
        series_key = temp.admin_data[user_id]["current_series_key"]
        language_name = temp.admin_data[user_id]["current_language"]
        season_name = temp.admin_data[user_id]["current_season"]
        quality_name = temp.admin_data[user_id]["current_quality"]
        first_file_channel_id = temp.admin_data[user_id]["first_file_channel_id"]
        first_file_msg_id = temp.admin_data[user_id]["first_file_msg_id"]
        last_file_msg_id = temp.admin_data[user_id]["last_file_msg_id"]
        files_to_delete = temp.admin_data[user_id]["files_to_delete"]

        log_user_activity(user_id, "process_codec_input", f"{series_key}:{language_name}:{season_name}:{quality_name}:{codec}")

        try:
            if ask_message_id:
                await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
            await message.delete()
        except Exception as e:
            log_warning(f"Could not delete prompt/user message: {e}")

        processing_msg = await client.send_message(
            chat_id=user_id,
            text="Processing files... Please wait. This might take a while.",
            reply_markup=ReplyKeyboardRemove()
        )

        target_db_channel_id = DB_CHANNEL[0]
        log_info(f"Copying messages from {first_file_channel_id} ({first_file_msg_id}-{last_file_msg_id}) to {target_db_channel_id}")
        
        copied_messages = await get_messages_in_range(
            client, 
            first_file_channel_id, 
            first_file_msg_id, 
            last_file_msg_id, 
            target_db_channel_id
        )

        if not copied_messages:
            log_error("Failed to copy files to DB Channel")
            await processing_msg.edit_text("Failed to copy files to DB Channel. Please check bot's admin rights in the source and target channels.")
            return

        new_first_msg_id = copied_messages[0].id
        new_last_msg_id = copied_messages[-1].id
        
        link_key = f"get_{abs(int(str(target_db_channel_id).replace('-100','')))}_{new_first_msg_id}_{new_last_msg_id}"

        if add_or_update_quality(series_key, language_name, season_name, quality_name, link_key, codec):
            log_info(f"Successfully added files with link_key: {link_key}")
            await delete_messages_from_user_chat(client, user_id, files_to_delete)

            main_message_id = temp.admin_data[user_id].get("main_message_id")
            temp.admin_data[user_id]["state"] = "MANAGE_QUALITIES"
            
            temp.admin_data[user_id].pop("first_file_channel_id", None)
            temp.admin_data[user_id].pop("first_file_msg_id", None)
            temp.admin_data[user_id].pop("last_file_msg_id", None)
            temp.admin_data[user_id].pop("files_to_delete", None)
            
            await processing_msg.edit_text("Files processed successfully!")
            await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
        else:
            log_error("Failed to add files to database")
            await processing_msg.edit_text("Failed to add files to database.")

        temp.admin_data[user_id].pop("ask_message_id", None)
        
    except Exception as e:
        log_error(f"Error processing codec input: {e}")
        await message.reply("An error occurred while processing codec input.")

async def _process_poster_input(client: Client, message: Message, level: str):
    """Process poster input from admin"""
    try:
        user_id = message.from_user.id
        ask_message_id = temp.admin_data[user_id].get("ask_message_id")
        series_key = temp.admin_data[user_id].get("current_series_key")
        language_name = temp.admin_data[user_id].get("current_language")
        season_name = temp.admin_data[user_id].get("current_season")
        main_message_id = temp.admin_data[user_id].get("main_message_id")

        log_user_activity(user_id, "process_poster_input", f"{level}:{series_key}")

        if not message.photo and not message.video:
            try:
                await message.delete()
                if ask_message_id:
                    await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
            except Exception as e:
                log_warning(f"Could not delete invalid input/prompt: {e}")
            await client.send_message(user_id, "Please send a **photo or video** for the poster.")
            temp.admin_data[user_id]["state"] = "IDLE"
            temp.admin_data[user_id].pop("ask_message_id", None)
            temp.admin_data[user_id].pop("current_language", None)
            temp.admin_data[user_id].pop("current_season", None)
            return

        try:
            if ask_message_id:
                await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
            await message.delete()
        except Exception as e:
            log_warning(f"Could not delete prompt/user message: {e}")

        processing_msg = await client.send_message(
            chat_id=user_id,
            text="Uploading poster... Please wait."
        )

        new_poster_file_id = await download_and_upload_poster(client, message=message)

        if new_poster_file_id:
            log_info(f"Successfully uploaded new poster: {new_poster_file_id}")
            if level == "series":
                update_series_field(series_key, "poster_file_id", new_poster_file_id)
                await processing_msg.edit_text("Series poster updated successfully.")
                new_main_msg_id = await send_main_series_message(client, user_id, get_series_by_key(series_key), main_message_id)
                if new_main_msg_id: 
                    temp.admin_data[user_id]["main_message_id"] = new_main_msg_id
                temp.admin_data[user_id]["state"] = "SERIES_DETAILS_VIEW"
            elif level == "language":
                add_or_update_language(series_key, language_name, new_poster_file_id)
                await processing_msg.edit_text("Language poster updated successfully.")
                await send_language_management_message(client, user_id, series_key, main_message_id)
                temp.admin_data[user_id]["state"] = "MANAGE_LANGUAGES"
            elif level == "season":
                add_or_update_season(series_key, language_name, season_name, new_poster_file_id)
                await processing_msg.edit_text("Season poster updated successfully.")
                await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
                temp.admin_data[user_id]["state"] = "MANAGE_SEASONS"
        else:
            log_error("Failed to upload new poster")
            await processing_msg.edit_text("Failed to upload new poster.")

        temp.admin_data[user_id].pop("current_language", None)
        temp.admin_data[user_id].pop("current_season", None)
        temp.admin_data[user_id].pop("ask_message_id", None)
        
    except Exception as e:
        log_error(f"Error processing poster input: {e}")
        await message.reply("An error occurred while processing poster input.")

async def _process_edit_series_text(client: Client, message: Message, input_text: str):
    """Process series text editing input from admin"""
    try:
        user_id = message.from_user.id
        series_key = temp.admin_data[user_id].get("current_series_key")
        main_message_id = temp.admin_data[user_id].get("main_message_id")

        if not series_key:
            log_error(f"Series key not found in session for user {user_id}")
            await message.reply("Error: Series key not found in session.")
            return

        log_user_activity(user_id, "process_edit_series_text", f"{series_key}:{input_text[:50]}")

        try:
            await message.delete()
        except Exception as e:
            log_warning(f"Could not delete user's input message: {e}")

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
            log_info(f"Updated series fields: {updates}")
            confirmation_msg = await message.reply("Series details updated successfully.")
            asyncio.create_task(DeleteMessage(confirmation_msg))
        else:
            log_warning("No valid fields found in update text")
            confirmation_msg = await message.reply("No valid fields to update found in your message.")
            asyncio.create_task(DeleteMessage(confirmation_msg))

        series_data = get_series_by_key(series_key)
        new_main_msg_id = await send_main_series_message(client, user_id, series_data, main_message_id)
        if new_main_msg_id: 
            temp.admin_data[user_id]["main_message_id"] = new_main_msg_id
        temp.admin_data[user_id]["state"] = "SERIES_DETAILS_VIEW"
        
    except Exception as e:
        log_error(f"Error processing edit series text: {e}")
        await message.reply("An error occurred while processing series text edit.")

# --- Helper Functions for Callback Dispatcher ---

async def _handle_media_selection_logic(client: Client, callback_query: CallbackQuery, source: str, media_id: str, media_type: str, main_message_id: int):
    """Handle media selection from TMDB/IMDb results"""
    try:
        user_id = callback_query.from_user.id
        log_user_activity(user_id, "handle_media_selection", f"{source}:{media_id}:{media_type}")
        
        movie_details = None
        if source == 'tmdb':
            movie_details = await get_tmdb_info(query=None, tmdb_id=media_id, media_type=media_type)
        elif source == 'imdb':
            movie_details = await get_poster(media_id, id=True)

        if not movie_details:
            log_error(f"Failed to retrieve {source} data for {media_id}")
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
            log_info(f"Series {series_key} already exists, loading for editing")
            await callback_query.answer("Series already exists. Loading for editing.", show_alert=True)
        else:
            log_info(f"Creating new series {series_key}")
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
                log_warning(f"Failed to add series {series_key}, might already exist")
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
            log_error(f"Failed to retrieve series data for {series_key}")
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
            log_info(f"Successfully uploaded poster for series {series_key}")
        else:
            log_warning(f"Failed to download/upload poster for series {series_key}")
            await client.send_message(user_id, "Failed to download/upload poster. Using placeholder.")
            update_series_field(series_key, "poster_file_id", NO_POSTER_FOUND_IMG)
            series_data["poster_file_id"] = NO_POSTER_FOUND_IMG

        new_main_msg_id = await send_main_series_message(client, user_id, series_data, main_message_id)
        if new_main_msg_id:
            temp.admin_data[user_id]["main_message_id"] = new_main_msg_id
            temp.admin_data[user_id]["current_series_key"] = series_key
            temp.admin_data[user_id]["state"] = "SERIES_DETAILS_VIEW"
            
    except Exception as e:
        log_error(f"Error handling media selection: {e}")
        await callback_query.answer("An error occurred while processing selection.", show_alert=True)

async def _handle_local_series_selection_logic(client: Client, callback_query: CallbackQuery, series_key: str, main_message_id: int):
    """Handle local series selection from database"""
    try:
        user_id = callback_query.from_user.id
        log_user_activity(user_id, "handle_local_series_selection", series_key)
        
        series_data = get_series_by_key(series_key)
        if not series_data:
            log_error(f"Series {series_key} not found in database")
            await client.edit_message_text(
                chat_id=user_id,
                message_id=main_message_id,
                text="Selected series not found in database. It might have been deleted."
            )
            return
        
        await callback_query.answer("Loading series for editing...")
        
        new_main_msg_id = await send_main_series_message(client, user_id, series_data, main_message_id)
        if new_main_msg_id:
            temp.admin_data[user_id]["main_message_id"] = new_main_msg_id
            temp.admin_data[user_id]["current_series_key"] = series_key
            temp.admin_data[user_id]["state"] = "SERIES_DETAILS_VIEW"
        
        if series_data.get('published'):
            await client.send_message(
                user_id,
                "⚠️ **Warning:** This series is currently **published**. Any changes you make will **not** be live until you click 'Publish Series' again."
            )
            
        log_info(f"Successfully loaded series {series_key} for editing")
        
    except Exception as e:
        log_error(f"Error handling local series selection: {e}")
        await callback_query.answer("An error occurred while loading series.", show_alert=True)

async def _handle_back_to_series_logic(client: Client, callback_query: CallbackQuery, series_key: str):
    """Handle back to series navigation"""
    try:
        user_id = callback_query.from_user.id
        main_message_id = temp.admin_data[user_id].get("main_message_id")

        log_user_activity(user_id, "handle_back_to_series", series_key)

        series_data = get_series_by_key(series_key)
        if not series_data:
            await callback_query.answer("Series not found.", show_alert=True)
            return

        new_main_msg_id = await send_main_series_message(client, user_id, series_data, main_message_id)
        if new_main_msg_id:
            temp.admin_data[user_id]["main_message_id"] = new_main_msg_id
            temp.admin_data[user_id]["state"] = "SERIES_DETAILS_VIEW"
            temp.admin_data[user_id].pop("current_language", None)
            temp.admin_data[user_id].pop("current_season", None)
            temp.admin_data[user_id].pop("current_quality", None)
            
    except Exception as e:
        log_error(f"Error handling back to series: {e}")
        await callback_query.answer("An error occurred.", show_alert=True)

async def _handle_edit_series_details_logic(client: Client, callback_query: CallbackQuery, series_key: str):
    """Handle edit series details request"""
    try:
        user_id = callback_query.from_user.id
        main_message_id = temp.admin_data[user_id].get("main_message_id")
        
        log_user_activity(user_id, "handle_edit_series_details", series_key)
        
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
        
        try:
            await client.edit_message_text(
                chat_id=user_id,
                message_id=main_message_id,
                text=text,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data=f"back_to_series:{series_key}")]])
            )
        except (MessageIdInvalid, FloodWait) as e:
            log_warning(f"Failed to edit series details prompt (ID: {main_message_id}): {e}. Sending new message.")
            new_msg = await client.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data=f"back_to_series:{series_key}")]])
            )
            temp.admin_data[user_id]["main_message_id"] = new_msg.id
        except Exception as e:
            log_error(f"Unexpected error editing series details prompt: {e}")
            await client.send_message(user_id, "Error updating series details display. Please try again.")

        temp.admin_data[user_id]["state"] = "EDITING_SERIES_TEXT"
        temp.admin_data[user_id]["current_series_key"] = series_key
        
    except Exception as e:
        log_error(f"Error handling edit series details: {e}")
        await callback_query.answer("An error occurred.", show_alert=True)

async def _handle_manage_languages_logic(client: Client, callback_query: CallbackQuery, series_key: str):
    """Handle manage languages request"""
    try:
        user_id = callback_query.from_user.id
        main_message_id = temp.admin_data[user_id].get("main_message_id")

        log_user_activity(user_id, "handle_manage_languages", series_key)

        temp.admin_data[user_id]["current_series_key"] = series_key
        temp.admin_data[user_id]["state"] = "MANAGE_LANGUAGES"
        await send_language_management_message(client, user_id, series_key, main_message_id)
        
    except Exception as e:
        log_error(f"Error handling manage languages: {e}")
        await callback_query.answer("An error occurred.", show_alert=True)

async def _handle_add_language_logic(client: Client, callback_query: CallbackQuery, series_key: str):
    """Handle add language request"""
    try:
        user_id = callback_query.from_user.id
        
        log_user_activity(user_id, "handle_add_language", series_key)
        
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
        temp.admin_data[user_id]["state"] = "AWAITING_LANGUAGE_INPUT"
        temp.admin_data[user_id]["ask_message_id"] = ask_msg.id
        
    except Exception as e:
        log_error(f"Error handling add language: {e}")
        await callback_query.answer("An error occurred.", show_alert=True)

async def _handle_manage_seasons_logic(client: Client, callback_query: CallbackQuery, series_key: str, language_name: str):
    """Handle manage seasons request"""
    try:
        user_id = callback_query.from_user.id
        main_message_id = temp.admin_data[user_id].get("main_message_id")

        log_user_activity(user_id, "handle_manage_seasons", f"{series_key}:{language_name}")

        temp.admin_data[user_id]["current_series_key"] = series_key
        temp.admin_data[user_id]["current_language"] = language_name
        temp.admin_data[user_id]["state"] = "MANAGE_SEASONS"
        await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
        
    except Exception as e:
        log_error(f"Error handling manage seasons: {e}")
        await callback_query.answer("An error occurred.", show_alert=True)

async def _handle_add_season_logic(client: Client, callback_query: CallbackQuery, series_key: str, language_name: str):
    """Handle add season request"""
    try:
        user_id = callback_query.from_user.id
        
        log_user_activity(user_id, "handle_add_season", f"{series_key}:{language_name}")
        
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
        temp.admin_data[user_id]["state"] = "AWAITING_SEASON_INPUT"
        temp.admin_data[user_id]["ask_message_id"] = ask_msg.id
        
    except Exception as e:
        log_error(f"Error handling add season: {e}")
        await callback_query.answer("An error occurred.", show_alert=True)

async def _handle_manage_qualities_logic(client: Client, callback_query: CallbackQuery, series_key: str, language_name: str, season_name: str):
    """Handle manage qualities request"""
    try:
        user_id = callback_query.from_user.id
        main_message_id = temp.admin_data[user_id].get("main_message_id")

        log_user_activity(user_id, "handle_manage_qualities", f"{series_key}:{language_name}:{season_name}")

        temp.admin_data[user_id]["current_series_key"] = series_key
        temp.admin_data[user_id]["current_language"] = language_name
        temp.admin_data[user_id]["current_season"] = season_name
        temp.admin_data[user_id]["state"] = "MANAGE_QUALITIES"
        await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
        
    except Exception as e:
        log_error(f"Error handling manage qualities: {e}")
        await callback_query.answer("An error occurred.", show_alert=True)

async def _handle_add_quality_logic(client: Client, callback_query: CallbackQuery, series_key: str, language_name: str, season_name: str):
    """Handle add quality request"""
    try:
        user_id = callback_query.from_user.id
        
        log_user_activity(user_id, "handle_add_quality", f"{series_key}:{language_name}:{season_name}")
        
        await callback_query.answer("Enter quality name...")

        reply_keyboard = ReplyKeyboardMarkup(
            [
                [KeyboardButton("360p"), KeyboardButton("480p")],
                [KeyboardButton("720p"), KeyboardButton("1080p")],
                [KeyboardButton("2160p"), KeyboardButton("4K")],
                [KeyboardButton("H.264"), KeyboardButton("H.265"), KeyboardButton("H.265 10bit")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )

        ask_msg = await client.send_message(
            user_id,
            "Enter quality name (e.g., '720p', '1080p H.265'):",
            reply_markup=reply_keyboard
        )
        temp.admin_data[user_id]["state"] = "AWAITING_QUALITY_INPUT"
        temp.admin_data[user_id]["ask_message_id"] = ask_msg.id
        
    except Exception as e:
        log_error(f"Error handling add quality: {e}")
        await callback_query.answer("An error occurred.", show_alert=True)

async def _handle_add_files_logic(client: Client, callback_query: CallbackQuery, series_key: str, language_name: str, season_name: str, quality_name: str):
    """Handle add files request"""
    try:
        user_id = callback_query.from_user.id

        log_user_activity(user_id, "handle_add_files", f"{series_key}:{language_name}:{season_name}:{quality_name}")

        temp.admin_data[user_id]["current_series_key"] = series_key
        temp.admin_data[user_id]["current_language"] = language_name
        temp.admin_data[user_id]["current_season"] = season_name
        temp.admin_data[user_id]["current_quality"] = quality_name
        temp.admin_data[user_id]["files_to_delete"] = []

        await callback_query.answer("Forward first file...")
        ask_msg = await client.send_message(
            user_id,
            f"Add me to the channel as admin and forward me the **first file** (with tag) for "
            f"<code>{language_name.title()} - {season_name.title()} - {quality_name}</code>",
            parse_mode=enums.ParseMode.HTML
        )
        temp.admin_data[user_id]["state"] = "AWAITING_FIRST_FILE"
        temp.admin_data[user_id]["ask_message_id"] = ask_msg.id
        
    except Exception as e:
        log_error(f"Error handling add files: {e}")
        await callback_query.answer("An error occurred.", show_alert=True)

async def _handle_change_poster_logic(client: Client, callback_query: CallbackQuery, series_key: str, level: str, language_name: str = None, season_name: str = None):
    """Handle change poster request"""
    try:
        user_id = callback_query.from_user.id

        log_user_activity(user_id, "handle_change_poster", f"{level}:{series_key}")

        if level == "series":
            await callback_query.answer("Send me the new poster image/video.")
            ask_msg = await client.send_message(user_id, "Please send the new poster image or video (thumbnail will be used).")
            temp.admin_data[user_id]["state"] = "AWAITING_SERIES_POSTER"
            temp.admin_data[user_id]["ask_message_id"] = ask_msg.id
        elif level == "language":
            temp.admin_data[user_id]["current_language"] = language_name
            await callback_query.answer("Send me the new poster image/video for this language.")
            ask_msg = await client.send_message(user_id, f"Please send the new poster image or video for '{language_name}'.")
            temp.admin_data[user_id]["state"] = "AWAITING_LANGUAGE_POSTER"
            temp.admin_data[user_id]["ask_message_id"] = ask_msg.id
        elif level == "season":
            temp.admin_data[user_id]["current_language"] = language_name
            temp.admin_data[user_id]["current_season"] = season_name
            await callback_query.answer("Send me the new poster image/video for this season.")
            ask_msg = await client.send_message(user_id, f"Please send the new poster image or video for '{season_name}'.")
            temp.admin_data[user_id]["state"] = "AWAITING_SEASON_POSTER"
            temp.admin_data[user_id]["ask_message_id"] = ask_msg.id
            
    except Exception as e:
        log_error(f"Error handling change poster: {e}")
        await callback_query.answer("An error occurred.", show_alert=True)

async def _handle_delete_language_logic(client: Client, callback_query: CallbackQuery, series_key: str, language_name: str):
    """Handle delete language request"""
    try:
        user_id = callback_query.from_user.id
        main_message_id = temp.admin_data[user_id].get("main_message_id")

        log_user_activity(user_id, "handle_delete_language", f"{series_key}:{language_name}")

        if delete_language(series_key, language_name):
            log_info(f"Successfully deleted language {language_name} from series {series_key}")
            await callback_query.answer(f"Language '{language_name}' deleted.", show_alert=True)
        else:
            log_error(f"Failed to delete language {language_name} from series {series_key}")
            await callback_query.answer(f"Failed to delete language '{language_name}'.", show_alert=True)
        
        await send_language_management_message(client, user_id, series_key, main_message_id)
        temp.admin_data[user_id]["state"] = "MANAGE_LANGUAGES"
        
    except Exception as e:
        log_error(f"Error handling delete language: {e}")
        await callback_query.answer("An error occurred.", show_alert=True)

async def _handle_delete_season_logic(client: Client, callback_query: CallbackQuery, series_key: str, language_name: str, season_name: str):
    """Handle delete season request"""
    try:
        user_id = callback_query.from_user.id
        main_message_id = temp.admin_data[user_id].get("main_message_id")

        log_user_activity(user_id, "handle_delete_season", f"{series_key}:{language_name}:{season_name}")

        if delete_season(series_key, language_name, season_name):
            log_info(f"Successfully deleted season {season_name} from {series_key}:{language_name}")
            await callback_query.answer(f"Season '{season_name}' deleted.", show_alert=True)
        else:
            log_error(f"Failed to delete season {season_name} from {series_key}:{language_name}")
            await callback_query.answer(f"Failed to delete season '{season_name}'.", show_alert=True)
        
        await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
        temp.admin_data[user_id]["state"] = "MANAGE_SEASONS"
        
    except Exception as e:
        log_error(f"Error handling delete season: {e}")
        await callback_query.answer("An error occurred.", show_alert=True)

async def _handle_delete_quality_logic(client: Client, callback_query: CallbackQuery, series_key: str, language_name: str, season_name: str, quality_name: str):
    """Handle delete quality request"""
    try:
        user_id = callback_query.from_user.id
        main_message_id = temp.admin_data[user_id].get("main_message_id")

        log_user_activity(user_id, "handle_delete_quality", f"{series_key}:{language_name}:{season_name}:{quality_name}")

        if delete_quality(series_key, language_name, season_name, quality_name):
            log_info(f"Successfully deleted quality {quality_name} from {series_key}:{language_name}:{season_name}")
            await callback_query.answer(f"Quality '{quality_name}' deleted.", show_alert=True)
        else:
            log_error(f"Failed to delete quality {quality_name} from {series_key}:{language_name}:{season_name}")
            await callback_query.answer(f"Failed to delete quality '{quality_name}'.", show_alert=True)
        
        await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
        temp.admin_data[user_id]["state"] = "MANAGE_QUALITIES"
        
    except Exception as e:
        log_error(f"Error handling delete quality: {e}")
        await callback_query.answer("An error occurred.", show_alert=True)

async def _handle_publish_series_logic(client: Client, callback_query: CallbackQuery, series_key: str):
    """Handle publish series request"""
    try:
        user_id = callback_query.from_user.id
        main_message_id = temp.admin_data[user_id].get("main_message_id")

        log_user_activity(user_id, "handle_publish_series", series_key)

        try:
            await client.edit_message_text(
                chat_id=user_id,
                message_id=main_message_id,
                text="Do you want to publish this series? NOTE: Once you publish this series, you can't edit it anymore. All the empty groups will be removed automatically.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Yes, Publish", callback_data=f"confirm_publish:{series_key}")],
                    [InlineKeyboardButton("No, Cancel", callback_data=f"back_to_series:{series_key}")]
                ])
            )
        except (MessageIdInvalid, FloodWait) as e:
            log_warning(f"Failed to edit publish confirmation message (ID: {main_message_id}): {e}. Sending new message.")
            new_msg = await client.send_message(
                chat_id=user_id,
                text="Do you want to publish this series? NOTE: Once you publish this series, you can't edit it anymore. All the empty groups will be removed automatically.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Yes, Publish", callback_data=f"confirm_publish:{series_key}")],
                    [InlineKeyboardButton("No, Cancel", callback_data=f"back_to_series:{series_key}")]
                ])
            )
            temp.admin_data[user_id]["main_message_id"] = new_msg.id
        except Exception as e:
            log_error(f"Unexpected error editing publish confirmation message: {e}")
            await client.send_message(user_id, "Error with publish confirmation. Please try again.")

        temp.admin_data[user_id]["state"] = "AWAITING_PUBLISH_CONFIRMATION"
        
    except Exception as e:
        log_error(f"Error handling publish series: {e}")
        await callback_query.answer("An error occurred.", show_alert=True)

async def _handle_confirm_publish_logic(client: Client, callback_query: CallbackQuery, series_key: str):
    """Handle confirm publish request"""
    try:
        user_id = callback_query.from_user.id
        main_message_id = temp.admin_data[user_id].get("main_message_id")

        log_user_activity(user_id, "handle_confirm_publish", series_key)

        if publish_series(series_key):
            log_info(f"Successfully published series {series_key}")
            try:
                await client.edit_message_text(
                    chat_id=user_id,
                    message_id=main_message_id,
                    text="Published Successfully! This series is now live and cannot be edited via this UI."
                )
            except (MessageIdInvalid, FloodWait) as e:
                log_warning(f"Failed to edit final publish message (ID: {main_message_id}): {e}. Sending new message.")
                await client.send_message(
                    chat_id=user_id,
                    text="Published Successfully! This series is now live and cannot be edited via this UI."
                )
            except Exception as e:
                log_error(f"Unexpected error editing final publish message: {e}")
                await client.send_message(user_id, "Published Successfully! (But failed to update message).")
                
            temp.admin_data.pop(user_id, None)
        else:
            log_error(f"Failed to publish series {series_key}")
            try:
                await client.edit_message_text(
                    chat_id=user_id,
                    message_id=main_message_id,
                    text="Failed to publish series. Please try again."
                )
            except (MessageIdInvalid, FloodWait) as e:
                log_warning(f"Failed to edit failed-publish message (ID: {main_message_id}): {e}. Sending new message.")
                await client.send_message(
                    chat_id=user_id,
                    text="Failed to publish series. Please try again."
                )
            except Exception as e:
                log_error(f"Unexpected error editing failed-publish message: {e}")
                await client.send_message(user_id, "Failed to publish series. (But failed to update message).")

            series_data = get_series_by_key(series_key)
            if series_data:
                new_main_msg_id = await send_main_series_message(client, user_id, series_data, main_message_id)
                if new_main_msg_id: 
                    temp.admin_data[user_id]["main_message_id"] = new_main_msg_id
                temp.admin_data[user_id]["state"] = "SERIES_DETAILS_VIEW"
            else:
                await client.send_message(user_id, "Series data not found after failed publish attempt. Please check logs.")
                temp.admin_data.pop(user_id, None)
                
    except Exception as e:
        log_error(f"Error handling confirm publish: {e}")
        await callback_query.answer("An error occurred.", show_alert=True)

# --- From pmfilter.py ---

async def global_filters(client, message, text=False):
    """Handle global filters for messages"""
    try:
        group_id = message.chat.id
        name = text or message.text 
        reply_id = message.reply_to_message.id if message.reply_to_message else message.id 
        
        log_debug(f"Checking global filters for message in chat {group_id}")
        
        keywords = await get_gfilters("gfilters")
        for keyword in reversed(sorted(keywords, key=len)):
            pattern = r"( |^|[\\W])" + re.escape(keyword) + r"( |$|[\\W])"
            if re.search(pattern, name, flags=re.IGNORECASE):
                log_info(f"Global filter triggered for keyword: {keyword}")
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
                    log_info(f"Global filter response sent for keyword: {keyword}")
                except Exception as e:
                    log_error(f"Error sending global filter response: {e}")
                return True
        return False
        
    except Exception as e:
        log_error(f"Error in global filters: {e}")
        return False

async def series_filter(client, message):
    """Handle series filtering for public users"""
    try:
        text = message.text.strip()
        log_info(f"Series filter triggered for query: {text}")
        
        matching_series = search_published_series(text, limit=10)

        series_data = None

        for s in matching_series:
            if text.lower() == s['_id'].lower() or text.lower() == s['title'].lower():
                series_data = s
                log_info(f"Exact match found: {s['title']}")
                break
             
        if not series_data:
            matching_series_titles = [s['title'] for s in matching_series]
            close_matches_titles = find_most_similar_title(text, matching_series_titles)
            
            if close_matches_titles:
                log_info(f"Close match found: {close_matches_titles}")
                buttons = []
                matched_series = next((s for s in matching_series if s['title'] == close_matches_titles), None)
                if matched_series:
                    buttons.append(
                        InlineKeyboardButton(close_matches_titles, callback_data=f"spellcheck-{matched_series['_id']}")
                    )
                    
                if buttons:
                    buttons_chunked = chunk_buttons(buttons, chunk_size=1)
                    reply_markup = InlineKeyboardMarkup(buttons_chunked)
                    etho = await message.reply_photo(
                        photo=random.choice(SPELL_CHECK_IMAGE), 
                        caption="<b>Choose Your Series:</b>", 
                        reply_markup=reply_markup
                    )
                    reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else None
                    requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
                    asyncio.create_task(DeleteMessage(etho))
                    return

        if series_data:
            log_info(f"Displaying series details for: {series_data['title']}")
            languages = series_data.get("languages", [])
            
            languages = [lang for lang in languages if lang.get('seasons')]

            if not languages:
                await message.reply_text("No languages available for this series yet.")
                return

            reply_text = (
                f"○ <b>Title:</b> <code>{series_data['title']}</code>\n"
                f"○ <b>Released On:</b> <code>{series_data.get('released_on', 'N/A')}</code>\n"
                f"○ <b>Genre:</b> <code>{series_data.get('genre', 'N/A')}</code>\n"
                f"○ <b>Rating:</b> <code>{series_data.get('rating', 'N/A')}</code>\n\n"
                "Select the language you need...!"
            )
            
            poster_to_use = get_series_poster_for_user(series_data['_id'])
            
            buttons = []
            for lang in languages:
                buttons.append(InlineKeyboardButton(lang['name'], callback_data=f"user_lang:{series_data['_id']}:{lang['name']}"))
            
            buttons_chunked = chunk_buttons(buttons, chunk_size=2)
            reply_markup = InlineKeyboardMarkup(buttons_chunked)
            
            try:
                etho = await message.reply_photo(
                    photo=poster_to_use, 
                    caption=reply_text, 
                    reply_markup=reply_markup, 
                    parse_mode=enums.ParseMode.HTML
                )
                reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
                requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
                asyncio.create_task(DeleteMessage(etho))
                log_info(f"Series details sent successfully for: {series_data['title']}")
            except MediaEmpty:
                log_error(f"MediaEmpty error for poster: {poster_to_use}. Falling back to NO_POSTER_FOUND_IMG.")
                etho = await message.reply_photo(
                    photo=NO_POSTER_FOUND_IMG, 
                    caption=reply_text, 
                    reply_markup=reply_markup, 
                    parse_mode=enums.ParseMode.HTML
                )
                reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
                requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
                asyncio.create_task(DeleteMessage(etho))
            except Exception as e:
                log_error(f"Error sending series details to user: {e}")
                await message.reply_text("An error occurred while fetching series details.")
                
    except Exception as e:
        log_error(f"Error in series filter: {e}")

# --- Combined Message Handler ---
@Client.on_message(filters.text & (filters.private | filters.group))
async def handle_message(client, message):
    """Main message handler for both admin and public messages"""
    try:
        user_id = message.from_user.id
        is_admin = user_id in ADMINS and message.chat.type == enums.ChatType.PRIVATE
        
        log_debug(f"Message from user {user_id}, is_admin: {is_admin}")
        
        if is_admin:
            if message.text and message.text.startswith('/'):
                command = message.command[0].lower()
                
                if user_id not in temp.admin_data:
                    temp.admin_data[user_id] = {}
                    
                log_user_activity(user_id, "admin_command", command)
                    
                if command == "newseries":
                    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None
                    if not query:
                        await message.reply("Usage: `/newseries <series_title>`")
                        return
                    await _new_series_command_logic(client, message, query)
                elif command == "cloneseries":
                    args = message.text.split(None, 2)
                    if len(args) < 3:
                        await message.reply("Usage: `/cloneseries <original_series_name_or_key> <new_series_title>`")
                        return
                    original_query = args[1].strip()
                    new_series_title = args[2].strip()
                    await _clone_series_command_logic(client, message, original_query, new_series_title)
                elif command == "editseries":
                    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None
                    if not query:
                        await message.reply("Usage: `/editseries <series_title_or_key>`")
                        return
                    await _edit_series_command_logic(client, message, query)
                elif command == "seriview":
                    await _seriview_command_logic(client, message)
                else:
                    glob = await global_filters(client, message)
                    if glob == False:
                        await series_filter(client, message)
            else:
                current_state = temp.admin_data.get(user_id, {}).get("state")
                if current_state == "AWAITING_LANGUAGE_INPUT":
                    await _process_language_input(client, message, message.text.strip())
                elif current_state == "AWAITING_SEASON_INPUT":
                    await _process_season_input(client, message, message.text.strip())
                elif current_state == "AWAITING_QUALITY_INPUT":
                    await _process_quality_input(client, message, message.text.strip())
                elif current_state == "AWAITING_CODEC_INPUT":
                    await _process_codec_input(client, message, message.text.strip())
                elif current_state == "EDITING_SERIES_TEXT":
                    await _process_edit_series_text(client, message, message.text.strip())
                else:
                    glob = await global_filters(client, message)
                    if glob == False:
                        await series_filter(client, message)
        else:
            glob = await global_filters(client, message)
            if glob == False:
                await series_filter(client, message)
                
    except Exception as e:
        log_error(f"Error in main message handler: {e}")

@Client.on_message((filters.photo | filters.video | filters.document) & filters.private & filters.user(ADMINS))
async def admin_media_input_dispatcher(client: Client, message: Message):
    """Handle media input from admins"""
    try:
        user_id = message.from_user.id
        current_state = temp.admin_data.get(user_id, {}).get("state")

        log_user_activity(user_id, "admin_media_input", current_state)

        if current_state == "AWAITING_SERIES_POSTER":
            await _process_poster_input(client, message, "series")
        elif current_state == "AWAITING_LANGUAGE_POSTER":
            await _process_poster_input(client, message, "language")
        elif current_state == "AWAITING_SEASON_POSTER":
            await _process_poster_input(client, message, "season")
        elif current_state == "AWAITING_FIRST_FILE":
            await _process_first_file_input(client, message)
        elif current_state == "AWAITING_LAST_FILE":
            await _process_last_file_input(client, message)
        else:
            log_warning(f"Unhandled media input state: {current_state}")
            
    except Exception as e:
        log_error(f"Error in admin media input dispatcher: {e}")

@Client.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    """Main callback query handler"""
    try:
        data = query.data
        parts = data.split(":")
        action = parts[0]
        series_key = parts[1] if len(parts) > 1 else None
        clicked_user = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.id

        log_debug(f"Callback query from user {clicked_user}: {data}")

        reply_msg = query.message.reply_to_message  
        if reply_msg and reply_msg.from_user:
            requested_user = reply_msg.from_user.id
        else:
            requested_user = requestor.get(f"{chat_id}•{message_id}")
        
        if chat_id < 0 and requested_user and clicked_user != requested_user:
            await query.answer("Not your request!", show_alert=True)
            return

        if clicked_user in ADMINS:
            if clicked_user not in temp.admin_data:
                temp.admin_data[clicked_user] = {}

            if series_key and temp.admin_data[clicked_user].get("current_series_key") and series_key != temp.admin_data[clicked_user]["current_series_key"]:
                await query.answer("This action is for a different series you were editing. Please start a new edit session.", show_alert=True)
                return

            log_user_activity(clicked_user, "admin_callback", action)

            if action.startswith("tmdb_select") or action.startswith("imdb_select"):
                source = action.split('_')[0]
                unique_id = parts[1]
                if unique_id not in temp.admin_data[clicked_user]:
                    await query.answer("Session expired or invalid data.", show_alert=True)
                    await query.message.delete()
                    return
                stored_data = temp.admin_data[clicked_user].pop(unique_id)
                media_id = stored_data['id']
                media_type = stored_data['media_type']
                main_message_id = temp.admin_data[clicked_user].get("main_message_id")
                
                await query.answer(f"Fetching details from {source.upper()}...")
                await _handle_media_selection_logic(client, query, source, media_id, media_type, main_message_id)

            elif action.startswith("local_series_select"):
                if len(parts) > 1 and len(parts[1]) == 36 and '-' in parts[1]:
                    unique_id = parts[1]
                    if clicked_user not in temp.admin_data or unique_id not in temp.admin_data[clicked_user]:
                        await query.answer("Session expired or invalid data.", show_alert=True)
                        await query.message.delete()
                        return
                    stored_data = temp.admin_data[clicked_user].pop(unique_id)
                    series_key = stored_data['series_key']
                else:
                    series_key = parts[1]
                
                main_message_id = temp.admin_data[clicked_user].get("main_message_id")
                await query.answer(f"Loading series: {series_key}...", show_alert=False)
                await _handle_local_series_selection_logic(client, query, series_key, main_message_id)

            elif action == "back_to_series":
                await query.answer("Going back...")
                await _handle_back_to_series_logic(client, query, series_key)

            elif action == "edit_series_details":
                await query.answer("Editing details...")
                await _handle_edit_series_details_logic(client, query, series_key)

            elif action == "manage_languages":
                await query.answer("Managing languages...")
                await _handle_manage_languages_logic(client, query, series_key)

            elif action == "add_language":
                await query.answer("Adding language...")
                await _handle_add_language_logic(client, query, series_key)

            elif action.startswith("manage_seasons"):
                language_name = parts[2]
                await query.answer("Managing seasons...")
                await _handle_manage_seasons_logic(client, query, series_key, language_name)

            elif action.startswith("add_season"):
                language_name = parts[2]
                await query.answer("Adding season...")
                await _handle_add_season_logic(client, query, series_key, language_name)

            elif action.startswith("manage_qualities"):
                language_name = parts[2]
                season_name = parts[3]
                await query.answer("Managing qualities...")
                await _handle_manage_qualities_logic(client, query, series_key, language_name, season_name)

            elif action.startswith("add_quality"):
                language_name = parts[2]
                season_name = parts[3]
                await query.answer("Adding quality...")
                await _handle_add_quality_logic(client, query, series_key, language_name, season_name)

            elif action.startswith("add_files"):
                language_name = parts[2]
                season_name = parts[3]
                quality_name = parts[4]
                await query.answer("Adding files...")
                await _handle_add_files_logic(client, query, series_key, language_name, season_name, quality_name)

            elif action.startswith("change_series_poster"):
                await query.answer("Changing series poster...")
                await _handle_change_poster_logic(client, query, series_key, "series")

            elif action.startswith("change_language_poster"):
                language_name = parts[2]
                await query.answer("Changing language poster...")
                await _handle_change_poster_logic(client, query, series_key, "language", language_name)

            elif action.startswith("change_season_poster"):
                language_name = parts[2]
                season_name = parts[3]
                await query.answer("Changing season poster...")
                await _handle_change_poster_logic(client, query, series_key, "season", language_name, season_name)

            elif action.startswith("delete_language"):
                language_name = parts[2]
                await query.answer("Deleting language...")
                await _handle_delete_language_logic(client, query, series_key, language_name)

            elif action.startswith("delete_season"):
                language_name = parts[2]
                season_name = parts[3]
                await query.answer("Deleting season...")
                await _handle_delete_season_logic(client, query, series_key, language_name, season_name)

            elif action.startswith("delete_quality"):
                language_name = parts[2]
                season_name = parts[3]
                quality_name = parts[4]
                await query.answer("Deleting quality...")
                await _handle_delete_quality_logic(client, query, series_key, language_name, season_name, quality_name)

            elif action.startswith("publish_series"):
                await query.answer("Publishing series...")
                await _handle_publish_series_logic(client, query, series_key)

            elif action.startswith("confirm_publish"):
                await query.answer("Confirming publish...")
                await _handle_confirm_publish_logic(client, query, series_key)

            else:
                await handle_public_callbacks(client, query, data, parts, action, series_key)
        else:
            await handle_public_callbacks(client, query, data, parts, action, series_key)
            
    except Exception as e:
        log_error(f"Error in callback handler: {e}")
        await query.answer("An error occurred. Please try again.", show_alert=True)

async def handle_public_callbacks(client, query, data, parts, action, series_key):
    """Handle public user callbacks"""
    try:
        log_debug(f"Handling public callback: {action}")
        
        if data == "pages":
            await query.answer()
            return

        elif data.startswith("b:"):
            try:
                k = data.split(":")
                parameter = k[1]
                url = f"https://t.me/{temp.U_NAME}?start={parameter}"
                await query.answer(url=url)
                log_info(f"Bot link generated: {url}")
            except Exception:
                await query.answer("Invalid URL provided.", show_alert=True)

        elif data.startswith("spellcheck-"):
            series_key = parts[1]
            log_info(f"Spellcheck callback for series: {series_key}")
            series_data = get_series_by_key(series_key)
            if series_data and series_data.get('published', False):
                languages = series_data.get("languages", [])
                languages = [lang for lang in languages if lang.get('seasons')]

                if not languages:
                    await query.answer("No languages available for this series yet.", show_alert=True)
                    return

                reply_text = (
                    f"○ <b>Title:</b> <code>{series_data['title']}</code>\n"
                    f"○ <b>Released On:</b> <code>{series_data.get('released_on', 'N/A')}</code>\n"
                    f"○ <b>Genre:</b> <code>{series_data.get('genre', 'N/A')}</code>\n"
                    f"○ <b>Rating:</b> <code>{series_data.get('rating', 'N/A')}</code>\n\n"
                    "Select the language you need...!"
                )
                
                poster_to_use = get_series_poster_for_user(series_data['_id'])
                
                buttons = []
                for lang in languages:
                    buttons.append(InlineKeyboardButton(lang['name'], callback_data=f"user_lang:{series_key}:{lang['name']}"))
                
                buttons_chunked = chunk_buttons(buttons, chunk_size=2)
                reply_markup = InlineKeyboardMarkup(buttons_chunked)

                try:
                    media = InputMediaPhoto(media=poster_to_use, caption=reply_text, parse_mode=enums.ParseMode.HTML)
                    await client.edit_message_media(
                        chat_id=query.message.chat.id,
                        message_id=query.message.id,
                        media=media,
                        reply_markup=reply_markup
                    )
                    log_info(f"Spellcheck response sent for series: {series_key}")
                except MediaEmpty:
                    log_error(f"MediaEmpty error for poster: {poster_to_use} during edit. Falling back to NO_POSTER_FOUND_IMG.")
                    media = InputMediaPhoto(
                        media=NO_POSTER_FOUND_IMG,
                        caption=reply_text,
                        parse_mode=enums.ParseMode.HTML
                    )
                    await client.edit_message_media(
                        chat_id=query.message.chat.id,
                        message_id=query.message.id,
                        media=media,
                        reply_markup=reply_markup
                    )
                except Exception as e:
                    log_error(f"Error editing message media for series details: {e}")
                    await query.message.edit_text("An error occurred while fetching series details.")
            else:
                await query.message.edit_text(
                    "Series not found or not published.",
                    disable_web_page_preview=True,
                    parse_mode=enums.ParseMode.HTML
                )

        elif data.startswith("user_lang:"):
            _, series_key, language_name = parts
            log_info(f"User language selection: {series_key}:{language_name}")
            series_data = get_series_by_key(series_key)

            if series_data and series_data.get('published', False):
                current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
                seasons = current_lang.get("seasons", []) if current_lang else []
                seasons = [s for s in seasons if s.get('qualities')]

                if not seasons:
                    await query.answer("No seasons available for this language yet.", show_alert=True)
                    return

                reply_text = (
                    f"○ <b>Title:</b> <code>{series_data['title']}</code>\n"
                    f"○ <b>Released On:</b> <code>{series_data.get('released_on', 'N/A')}</code>\n"
                    f"○ <b>Genre:</b> <code>{series_data.get('genre', 'N/A')}</code>\n"
                    f"○ <b>Rating:</b> <code>{series_data.get('rating', 'N/A')}</code>\n"
                    f"○ <b>Language:</b> <code>{language_name.title()}</code>\n\n"
                    "Select the season you need...!"
                )
                
                buttons = []
                for season in seasons:
                    buttons.append(InlineKeyboardButton(season['name'], callback_data=f"user_season:{series_key}:{language_name}:{season['name']}"))
                
                buttons_chunked = chunk_buttons(buttons)
                buttons_chunked.append([InlineKeyboardButton("Back", callback_data=f"spellcheck-{series_key}")])
                reply_markup = InlineKeyboardMarkup(buttons_chunked)
                
                await query.message.edit_text(text=reply_text, reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML)
                log_info(f"Language selection response sent: {series_key}:{language_name}")

        elif data.startswith("user_season:"):
            _, series_key, language_name, season_name = parts
            log_info(f"User season selection: {series_key}:{language_name}:{season_name}")
            series_data = get_series_by_key(series_key)

            if series_data and series_data.get('published', False):
                current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
                current_season = next((s for s in current_lang.get("seasons", []) if s["name"].lower() == season_name.lower()), None) if current_lang else None
                qualities = current_season.get("qualities", []) if current_season else []
                qualities = [q for q in qualities if q.get('link_key')]

                if not qualities:
                    await query.answer("No qualities available for this season yet.", show_alert=True)
                    return

                reply_text = (
                    f"○ <b>Title:</b> <code>{series_data['title']}</code>\n"
                    f"○ <b>Released On:</b> <code>{series_data.get('released_on', 'N/A')}</code>\n"
                    f"○ <b>Genre:</b> <code>{series_data.get('genre', 'N/A')}</code>\n"
                    f"○ <b>Rating:</b> <code>{series_data.get('rating', 'N/A')}</code>\n"
                    f"○ <b>Language:</b> <code>{language_name.title()}</code>\n"
                    f"○ <b>Season:</b> <code>{season_name.title()}</code>\n\n"
                    "Select the quality you need...!"
                )
                
                buttons = []
                for quality in qualities:
                    buttons.append(InlineKeyboardButton(quality['name'], callback_data=f"b:{quality['link_key']}"))
                
                buttons_chunked = chunk_buttons(buttons, chunk_size=2)
                buttons_chunked.append([InlineKeyboardButton("Back", callback_data=f"user_lang:{series_key}:{language_name}")])
                reply_markup = InlineKeyboardMarkup(buttons_chunked)
                
                await query.message.edit_text(
                    text=reply_text,
                    reply_markup=reply_markup,
                    disable_web_page_preview=True,
                    parse_mode=enums.ParseMode.HTML
                )
                log_info(f"Season selection response sent: {series_key}:{language_name}:{season_name}")
                
    except Exception as e:
        log_error(f"Error in public callback handler: {e}")
        await query.answer("An error occurred. Please try again.", show_alert=True)
