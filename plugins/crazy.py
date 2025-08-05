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
from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, TMDB_API_KEY, LOG_CHANNEL, DB_CHANNEL, RAW_DB_CHANNEL, NO_POSTER_FOUND_IMG
from database.crazy_db import (
    add_series, get_series_by_key, update_series_field, add_or_update_language,
    get_languages, delete_language, add_or_update_season, get_seasons, delete_season,
    add_or_update_quality, get_qualities, get_quality_link, delete_quality,
    get_poster_file_id, update_poster_file_id, publish_series, get_series, get_specific_poster
)
from utils import get_message_id, get_messages_in_range, delete_messages_from_user_chat, get_poster
from fuzzywuzzy import fuzz # Import fuzzywuzzy
from pyrogram.errors import MessageIdInvalid, FloodWait

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Temporary storage for multi-step UI interactions
# Key: user_id, Value: dictionary of current state
temp_admin_data = {}

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

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
    except (MessageIdInvalid, FloodWait) as e:
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
        except (MessageIdInvalid) as e_fallback:
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
    except (MessageIdInvalid, FloodWait) as e:
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
    except (MessageIdInvalid, FloodWait) as e:
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
    except (MessageIdInvalid, FloodWait) as e:
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
    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None

    if not query:
        await message.reply("Usage: `/newseries series_title`")
        return

    temp_msg = await message.reply_photo(
        photo=NO_POSTER_FOUND_IMG, # Temporary placeholder
        caption="Searching TMDB and IMDb, please wait..."
    )
    
    tmdb_results = await get_tmdb_info(query, bulk=True)
    imdb_results = get_poster(query, bulk=True) # Use get_poster for IMDb search

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
                'media_type': item.get('kind'), # 'movie' or 'tv series'
                'source': 'imdb',
                'poster_url': item.get('poster')
            })

    if not all_results:
        await temp_msg.edit_caption("No results found on TMDB or IMDb for the provided series name.")
        return

    buttons = []
    for item in all_results:
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
                callback_data=f"{item.get('source')}_select:{unique_id}"
            )
        ])
    
    reply_markup = InlineKeyboardMarkup(buttons)
    await temp_msg.edit_caption(
        "Select a series from below:\n\n"
        "**Choose Your Series:**",
        reply_markup=reply_markup
    )
    
    temp_admin_data[user_id]["state"] = "SELECTING_SERIES"
    temp_admin_data[user_id]["main_message_id"] = temp_msg.id

@Client.on_message(filters.command('cloneseries') & filters.user(ADMINS))
async def clone_series_command(client: Client, message: Message):
    user_id = message.from_user.id
    args = message.text.split(None, 2) # Split into command, original_name, new_name

    if len(args) < 3:
        await message.reply("Usage: `/cloneseries original_series_name_or_key new_series_title`")
        return

    original_query = args[1].strip()
    new_series_title = args[2].strip()
    
    # Generate a new series key from the new title, ensuring it's clean for _id
    new_series_key = new_series_title.lower().replace(" ", "").replace("-", "")

    # Check if new series title already exists
    existing_series_by_new_key = get_series_by_key(new_series_key)
    if existing_series_by_new_key:
        await message.reply(f"A series with the title '{new_series_title}' (key: `{new_series_key}`) already exists. Please choose a different title.")
        return

    # Find the original series by key or title
    original_series_data = get_series_by_key(original_query)
    if not original_series_data:
        # Try searching by title if not found by key
        all_series = get_series()
        for s in all_series:
            if s.get('title', '').lower() == original_query.lower():
                original_series_data = s
                break
    
    if not original_series_data:
        await message.reply(f"Original series '{original_query}' not found in the database.")
        return

    # Create a deep copy of the original series data
    cloned_series_data = copy.deepcopy(original_series_data)

    # Update the _id and title for the new series
    cloned_series_data['_id'] = new_series_key
    cloned_series_data['title'] = new_series_title
    cloned_series_data['published'] = False # New series is not published by default

    # Add the cloned series to the database
    if add_series(cloned_series_data):
        await message.reply(f"Series '{original_series_data.get('title', 'N/A')}' successfully cloned to '{new_series_title}' (key: `{new_series_key}`).\n\n"
                            f"The new series is currently **unpublished**. You can now edit it using the UI via `/editseries {new_series_title}` and then publish it.")
    else:
        await message.reply(f"Failed to clone series '{original_series_data.get('title', 'N/A')}' to '{new_series_title}'. It might already exist.")


@Client.on_message(filters.command('editseries') & filters.user(ADMINS))
async def edit_series_command(client: Client, message: Message):
    user_id = message.from_user.id
    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None

    if not query:
        await message.reply("Usage: `/editseries series_title_or_key`")
        return

    # Try direct lookup by key (lower and replace spaces/hyphens for consistency)
    series_key_lookup = query.lower().replace(" ", "").replace("-", "")
    series_data = get_series_by_key(series_key_lookup)

    if not series_data:
        # If not found by key, try fuzzy searching by title
        all_series = get_series()
        fuzzy_matches = []
        for s in all_series:
            title = s.get('title', '')
            key = s.get('_id', '')
            
            # Calculate fuzzy ratio for title and key
            title_ratio = fuzz.ratio(query.lower(), title.lower())
            key_ratio = fuzz.ratio(query.lower(), key.lower())
            
            # Use a threshold (e.g., 70 for good matches)
            if title_ratio >= 70 or key_ratio >= 70:
                fuzzy_matches.append((s, max(title_ratio, key_ratio)))
        
        # Sort by highest match ratio
        fuzzy_matches.sort(key=lambda x: x[1], reverse=True)
        
        if not fuzzy_matches:
            await message.reply(f"Series '{query}' not found in the database. Please check the title or key.")
            return
        elif len(fuzzy_matches) == 1:
            # Only one fuzzy match, load it directly
            series_data = fuzzy_matches[0][0]
        else:
            # Multiple fuzzy matches, present options
            buttons = []
            for item, score in fuzzy_matches[:5]: # Limit to top 5 fuzzy matches
                unique_id = str(uuid.uuid4())
                temp_admin_data[user_id] = temp_admin_data.get(user_id, {})
                temp_admin_data[user_id][unique_id] = {
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
            temp_admin_data[user_id]["state"] = "SELECTING_LOCAL_SERIES"
            temp_admin_data[user_id]["main_message_id"] = temp_msg.id
            return # Exit, wait for callback

    # Proceed to load the series for editing
    temp_msg = await message.reply_photo(
        photo=get_poster_file_id(series_data['_id']) or NO_POSTER_FOUND_IMG,
        caption=f"Loading series details for <code>{series_data.get('title', 'N/A')}</code>...",
        parse_mode=enums.ParseMode.HTML
    )

    temp_admin_data[user_id]["main_message_id"] = temp_msg.id
    temp_admin_data[user_id]["current_series_key"] = series_data['_id']
    temp_admin_data[user_id]["state"] = "SERIES_DETAILS_VIEW"
    
    await send_main_series_message(client, user_id, series_data, temp_msg.id)

    if series_data.get('published'):
        await client.send_message(
            user_id,
            "⚠️ **Warning:** This series is currently **published**. Any changes you make will **not** be live until you click 'Publish Series' again."
        )

@Client.on_message(filters.command('seriview') & filters.user(ADMINS))
async def seriview_command(client: Client, message: Message):
    user_id = message.from_user.id
    all_series = get_series()

    if not all_series:
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
    
    reply_markup = InlineKeyboardMarkup(chunk_buttons(buttons, chunk_size=3)) # One button per row for readability

    await message.reply_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode=enums.ParseMode.HTML,
        disable_web_page_preview=True
    )


# --- Callback Query Handlers ---

@Client.on_callback_query(filters.regex(r"^(tmdb|imdb)_select:") & filters.user(ADMINS))
async def media_selection_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data_parts = callback_query.data.split(":")
    source = data_parts[0].split('_')[0] # 'tmdb' or 'imdb'
    unique_id = data_parts[1]

    if user_id not in temp_admin_data or unique_id not in temp_admin_data[user_id]:
        await callback_query.answer("Session expired or invalid data.", show_alert=True)
        await callback_query.message.delete()
        return

    stored_data = temp_admin_data[user_id].pop(unique_id)
    media_id = stored_data['id']
    media_type = stored_data['media_type']
    main_message_id = temp_admin_data[user_id].get("main_message_id")

    await callback_query.answer(f"Fetching details from {source.upper()}...")

    movie_details = None
    if source == 'tmdb':
        movie_details = await get_tmdb_info(query=None, tmdb_id=media_id, media_type=media_type)
    elif source == 'imdb':
        movie_details = await get_poster(media_id, id=True) # Use get_poster for IMDb details

    if not movie_details:
        await client.edit_message_caption(
            chat_id=user_id,
            message_id=main_message_id,
            caption=f"Failed to retrieve {source.upper()} data. Please try again."
        )
        return

    # Generate a clean series key from the title for _id
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
            'tmdb_id': movie_details.get('tmdb_id') if source == 'tmdb' else None, # Store TMDB ID if from TMDB
            'imdb_id': movie_details.get('imdb_id') if source == 'imdb' else None, # Store IMDb ID if from IMDb
            'media_type': media_type,
            'poster_file_id': None, # Will be updated after download/upload
            'languages': [],
            'published': False
        }
        if not add_series(series_data): # Attempt to add, check if successful
            await callback_query.answer("Failed to add new series (might already exist). Loading existing series.", show_alert=True)
            series_data = get_series_by_key(series_key) # Re-fetch if insertion failed due to duplicate
            if not series_data: # If still not found, something is wrong
                await client.edit_message_caption(
                    chat_id=user_id,
                    message_id=main_message_id,
                    caption="Failed to create or load series. Please try again."
                )
                return

    # Re-fetch series_data to ensure it's the latest from DB, especially after add_series
    series_data = get_series_by_key(series_key)
    if not series_data: # Should not happen if add_series was successful or existing_series was found
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
        series_data["poster_file_id"] = poster_file_id # Update in memory for immediate use
    else:
        await client.send_message(user_id, "Failed to download/upload poster. Using placeholder.")
        update_series_field(series_key, "poster_file_id", NO_POSTER_FOUND_IMG)
        series_data["poster_file_id"] = NO_POSTER_FOUND_IMG

    # Update main message with series details and management buttons
    new_main_msg_id = await send_main_series_message(client, user_id, series_data, main_message_id)
    if new_main_msg_id: # Only update if sending/editing was successful
        temp_admin_data[user_id]["main_message_id"] = new_main_msg_id
        temp_admin_data[user_id]["current_series_key"] = series_key
        temp_admin_data[user_id]["state"] = "SERIES_DETAILS_VIEW"

@Client.on_callback_query(filters.regex(r"^local_series_select:") & filters.user(ADMINS))
async def local_series_selection_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data_parts = callback_query.data.split(":")
    # Check if data_parts has enough elements for the old UUID logic, if not, assume it's a direct key
    if len(data_parts) > 1 and len(data_parts[1]) == 36 and '-' in data_parts[1]: # Basic UUID check
        unique_id = data_parts[1]
        if user_id not in temp_admin_data or unique_id not in temp_admin_data[user_id]:
            await callback_query.answer("Session expired or invalid data.", show_alert=True)
            await callback_query.message.delete()
            return
        stored_data = temp_admin_data[user_id].pop(unique_id)
        series_key = stored_data['series_key']
    else:
        # Assume it's the direct series_key from /seriview
        series_key = data_parts[1]
        await callback_query.answer(f"Loading series: {series_key}...", show_alert=False)

    main_message_id = temp_admin_data[user_id].get("main_message_id")

    series_data = get_series_by_key(series_key)
    if not series_data:
        await client.edit_message_text(
            chat_id=user_id,
            message_id=main_message_id,
            text="Selected series not found in database. It might have been deleted."
        )
        return

    await callback_query.answer("Loading series for editing...")
    
    # Send/edit the main series message
    new_main_msg_id = await send_main_series_message(client, user_id, series_data, main_message_id)
    if new_main_msg_id: # Only update if sending/editing was successful
        temp_admin_data[user_id]["main_message_id"] = new_main_msg_id
        temp_admin_data[user_id]["current_series_key"] = series_key
        temp_admin_data[user_id]["state"] = "SERIES_DETAILS_VIEW"
    
    if series_data.get('published'):
        await client.send_message(
            user_id,
            "⚠️ **Warning:** This series is currently **published**. Any changes you make will **not** be live until you click 'Publish Series' again."
        )


@Client.on_callback_query(filters.regex(r"^back_to_series:") & filters.user(ADMINS))
async def back_to_series_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    series_key = callback_query.data.split(":")[1]
    main_message_id = temp_admin_data[user_id].get("main_message_id")

    series_data = get_series_by_key(series_key)
    if not series_data:
        await callback_query.answer("Series not found.", show_alert=True)
        return

    new_main_msg_id = await send_main_series_message(client, user_id, series_data, main_message_id)
    if new_main_msg_id:
        temp_admin_data[user_id]["main_message_id"] = new_main_msg_id
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
    
    await callback_query.answer("Enter language name...")
    
    # Use ReplyKeyboardMarkup for quick suggestions
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
    temp_admin_data[user_id]["state"] = "AWAITING_LANGUAGE_INPUT"
    temp_admin_data[user_id]["ask_message_id"] = ask_msg.id

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
    elif current_state == "AWAITING_CODEC_INPUT":
        await process_codec_input(client, message, message.text.strip())
    elif current_state == "EDITING_SERIES_TEXT":
        await process_edit_series_text(client, message, message.text.strip())
    # Note: AWAITING_FIRST_FILE and AWAITING_LAST_FILE are handled in handle_admin_media_and_link_input
    # Poster inputs are handled in handle_admin_media_input

@Client.on_message((filters.photo | filters.video | filters.document) & filters.private & filters.user(ADMINS))
async def handle_admin_media_input(client: Client, message: Message):
    user_id = message.from_user.id
    current_state = temp_admin_data.get(user_id, {}).get("state")

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
    else:
        # If media is sent in an unexpected state, just ignore or give a generic response
        # await message.reply("I'm not expecting a media file right now.") # Optional: for debugging
        pass # Do nothing, let the main message flow continue


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
        await message.delete() # Delete user's input message
    except Exception as e:
        logger.warning(f"Could not delete prompt/user message: {e}")

    if add_or_update_language(series_key, language_name):
        confirmation_msg = await client.send_message(
            chat_id=user_id,
            text=f"Language '{language_name}' added/updated successfully.",
            reply_markup=ReplyKeyboardRemove() # Remove keyboard from this new message
        )
        asyncio.create_task(confirmation_msg.delete()) # Delete confirmation after 5 seconds

        await send_language_management_message(client, user_id, series_key, main_message_id)
        temp_admin_data[user_id]["state"] = "MANAGE_LANGUAGES"
    else:
        await message.reply("Failed to add/update language.")

    temp_admin_data[user_id].pop("ask_message_id", None) # Clear ask_message_id from temp_admin_data

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
    temp_admin_data[user_id]["state"] = "AWAITING_SEASON_INPUT"
    temp_admin_data[user_id]["ask_message_id"] = ask_msg.id

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
        await message.delete() # Delete user's input message
    except Exception as e:
        logger.warning(f"Could not delete prompt/user message: {e}")

    if add_or_update_season(series_key, language_name, season_name):
        confirmation_msg = await client.send_message(
            chat_id=user_id,
            text=f"Season '{season_name}' added/updated successfully.",
            reply_markup=ReplyKeyboardRemove() # Remove keyboard from this new message
        )
        asyncio.create_task(confirmation_msg.delete()) # Delete confirmation after 5 seconds

        await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
        temp_admin_data[user_id]["state"] = "MANAGE_SEASONS"
    else:
        await message.reply("Failed to add/update season.")

    temp_admin_data[user_id].pop("ask_message_id", None) # Clear ask_message_id from temp_admin_data

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
    temp_admin_data[user_id]["state"] = "AWAITING_QUALITY_INPUT"
    temp_admin_data[user_id]["ask_message_id"] = ask_msg.id

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
        await message.delete() # Delete user's input message
    except Exception as e:
        logger.warning(f"Could not delete prompt/user message: {e}")

    # For now, we'll add with a placeholder link_key. Actual link will be added later.
    if add_or_update_quality(series_key, language_name, season_name, quality_name, "PENDING_LINK"):
        confirmation_msg = await client.send_message(
            chat_id=user_id,
            text=f"Quality '{quality_name}' added/updated successfully. Now add files.",
            reply_markup=ReplyKeyboardRemove() # Remove keyboard from this new message
        )
        asyncio.create_task(confirmation_msg.delete()) # Delete confirmation after 5 seconds

        await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
        temp_admin_data[user_id]["state"] = "MANAGE_QUALITIES"
    else:
        await message.reply("Failed to add/update quality.")

    temp_admin_data[user_id].pop("ask_message_id", None) # Clear ask_message_id from temp_admin_data

@Client.on_callback_query(filters.regex(r"^add_files:") & filters.user(ADMINS))
async def add_files_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    _, series_key, language_name, season_name, quality_name = callback_query.data.split(":")
    # main_message_id = temp_admin_data[user_id].get("main_message_id") # Not directly used here, but for context

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
        # Delete user's invalid input immediately
        try:
            await message.delete()
            if ask_message_id:
                await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
        except Exception as e:
            logger.warning(f"Could not delete invalid input/prompt: {e}")

        await client.send_message(user_id, "Invalid message. Please forward a message from a **DB Channel** or send a valid **post link from a DB Channel**.")
        temp_admin_data[user_id]["state"] = "IDLE" # Reset state
        temp_admin_data[user_id].pop("ask_message_id", None)
        return

    temp_admin_data[user_id]["first_file_channel_id"] = channel_id
    temp_admin_data[user_id]["first_file_msg_id"] = msg_id
    temp_admin_data[user_id]["files_to_delete"].append(message.id) # Add user's forwarded message to delete list

    # Delete the bot's prompt message
    try:
        if ask_message_id:
            await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
    except Exception as e:
        logger.warning(f"Could not delete prompt message: {e}")

    next_prompt_msg = await client.send_message(
        chat_id=user_id,
        text=f"Forward me the **last file** (with tag) for "
             f"<code>{temp_admin_data[user_id]['current_language'].title()} - "
             f"{temp_admin_data[user_id]['current_season'].title()} - "
             f"{temp_admin_data[user_id]['current_quality']}</code>\n\n"
             f"Go to first file: [Link](https://t.me/c/{abs(int(str(channel_id).replace('-100','')))}/{msg_id})", # Convert Pyrogram ID to raw for link
        parse_mode=enums.ParseMode.MARKDOWN,
        disable_web_page_preview=True
    )
    temp_admin_data[user_id]["state"] = "AWAITING_LAST_FILE"
    temp_admin_data[user_id]["ask_message_id"] = next_prompt_msg.id # Update ask_message_id for the next step

async def process_last_file_input(client: Client, message: Message):
    user_id = message.from_user.id
    ask_message_id = temp_admin_data[user_id].get("ask_message_id")

    channel_id, msg_id = await get_message_id(client, message)
    if not channel_id or not msg_id:
        # Delete user's invalid input immediately
        try:
            await message.delete()
            if ask_message_id:
                await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
        except Exception as e:
            logger.warning(f"Could not delete invalid input/prompt: {e}")
        await client.send_message(user_id, "Invalid message. Please forward a message from a **DB Channel** or send a valid **post link from a DB Channel**.")
        temp_admin_data[user_id]["state"] = "IDLE" # Reset state
        temp_admin_data[user_id].pop("ask_message_id", None)
        return
    
    if channel_id != temp_admin_data[user_id]["first_file_channel_id"]:
        # Delete user's invalid input immediately
        try:
            await message.delete()
            if ask_message_id:
                await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
        except Exception as e:
            logger.warning(f"Could not delete invalid input/prompt: {e}")
        await client.send_message(user_id, "Last file must be from the same channel as the first file.")
        temp_admin_data[user_id]["state"] = "IDLE" # Reset state
        temp_admin_data[user_id].pop("ask_message_id", None)
        return

    temp_admin_data[user_id]["last_file_msg_id"] = msg_id
    temp_admin_data[user_id]["files_to_delete"].append(message.id) # Add user's forwarded message to delete list

    # Delete the bot's prompt message
    try:
        if ask_message_id:
            await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
    except Exception as e:
        logger.warning(f"Could not delete prompt message: {e}")

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
             f"<code>{temp_admin_data[user_id]['current_language'].title()} - "
             f"{temp_admin_data[user_id]['current_season'].title()} - "
             f"{temp_admin_data[user_id]['current_quality']}</code>",
        parse_mode=enums.ParseMode.HTML,
        reply_markup=reply_keyboard
    )
    temp_admin_data[user_id]["state"] = "AWAITING_CODEC_INPUT"
    temp_admin_data[user_id]["ask_message_id"] = next_prompt_msg.id # Update ask_message_id for the next step

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

    # Delete the bot's prompt message and the user's reply
    try:
        if ask_message_id:
            await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
        await message.delete() # Delete user's input message
    except Exception as e:
        logger.warning(f"Could not delete prompt/user message: {e}")

    processing_msg = await client.send_message(
        chat_id=user_id,
        text="Processing files... Please wait. This might take a while.",
        reply_markup=ReplyKeyboardRemove() # Remove keyboard from this new message
    )

    # Copy messages to DB_CHANNEL
    target_db_channel_id = DB_CHANNEL[0] # Use the first DB channel for storage (Pyrogram format)
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
    
    # Generate the link_key using the RAW_DB_CHANNEL format for the channel ID
    link_key = f"get_{abs(int(str(target_db_channel_id).replace('-100','')))}.{new_first_msg_id}.{new_last_msg_id}" # Changed to dot separator for consistency

    if add_or_update_quality(series_key, language_name, season_name, quality_name, link_key, codec):
        # Delete user's forwarded messages
        await delete_messages_from_user_chat(client, user_id, files_to_delete)

        # Go back to quality management view
        main_message_id = temp_admin_data[user_id].get("main_message_id")
        temp_admin_data[user_id]["state"] = "MANAGE_QUALITIES"
        
        # Clear temporary file data
        temp_admin_data[user_id].pop("first_file_channel_id", None)
        temp_admin_data[user_id].pop("first_file_msg_id", None)
        temp_admin_data[user_id].pop("last_file_msg_id", None)
        temp_admin_data[user_id].pop("files_to_delete", None)

        await processing_msg.edit_text(f"Files added successfully for '{quality_name}'.")
        await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
    else:
        await processing_msg.edit_text("Failed to add files to database.")

    temp_admin_data[user_id].pop("ask_message_id", None) # Clear ask_message_id from temp_admin_data

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
        # Delete user's invalid input immediately
        try:
            await message.delete()
            if ask_message_id:
                await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
        except Exception as e:
            logger.warning(f"Could not delete invalid input/prompt: {e}")
        await client.send_message(user_id, "Please send a **photo or video** for the poster.")
        temp_admin_data[user_id]["state"] = "IDLE" # Reset state
        temp_admin_data[user_id].pop("ask_message_id", None)
        temp_admin_data[user_id].pop("current_language", None)
        temp_admin_data[user_id].pop("current_season", None)
        return

    # Delete the bot's prompt message and the user's reply
    try:
        if ask_message_id:
            await client.delete_messages(chat_id=user_id, message_ids=[ask_message_id])
        await message.delete() # Delete user's input message
    except Exception as e:
        logger.warning(f"Could not delete prompt/user message: {e}")

    processing_msg = await client.send_message(
        chat_id=user_id,
        text="Uploading poster... Please wait."
    )

    new_poster_file_id = await download_and_upload_poster(client, message=message)

    if new_poster_file_id:
        if level == "series":
            update_poster_file_id(series_key, new_poster_file_id)
            await processing_msg.edit_text("Series poster updated successfully.")
            new_main_msg_id = await send_main_series_message(client, user_id, get_series_by_key(series_key), main_message_id)
            if new_main_msg_id: temp_admin_data[user_id]["main_message_id"] = new_main_msg_id
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
    
    try:
        await client.edit_message_text(
            chat_id=user_id,
            message_id=main_message_id,
            text=text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data=f"back_to_series:{series_key}")]])
        )
    except (MessageIdInvalid, FloodWait) as e:
        logger.warning(f"Failed to edit series details prompt (ID: {main_message_id}): {e}. Sending a new one.")
        new_msg = await client.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data=f"back_to_series:{series_key}")]])
        )
        temp_admin_data[user_id]["main_message_id"] = new_msg.id # Update stored message ID
    except Exception as e:
        logger.error(f"An unexpected error occurred editing series details prompt: {e}")
        await client.send_message(user_id, "Error updating series details display. Please try again.")

    temp_admin_data[user_id]["state"] = "EDITING_SERIES_TEXT"
    temp_admin_data[user_id]["current_series_key"] = series_key

async def process_edit_series_text(client: Client, message: Message, input_text: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    main_message_id = temp_admin_data[user_id].get("main_message_id")

    if not series_key:
        await message.reply("Error: Series key not found in session.")
        return

    # Delete the user's input message
    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"Could not delete user's input message: {e}")

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
        confirmation_msg = await message.reply("Series details updated successfully.")
        asyncio.create_task(confirmation_msg.delete()) # Delete confirmation after 5 seconds
    else:
        confirmation_msg = await message.reply("No valid fields to update found in your message.")
        asyncio.create_task(confirmation_msg.delete()) # Delete confirmation after 5 seconds

    series_data = get_series_by_key(series_key)
    # Re-send/edit the main series message
    new_main_msg_id = await send_main_series_message(client, user_id, series_data, main_message_id)
    if new_main_msg_id: temp_admin_data[user_id]["main_message_id"] = new_main_msg_id
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
        logger.warning(f"Failed to edit publish confirmation message (ID: {main_message_id}): {e}. Sending a new one.")
        new_msg = await client.send_message(
            chat_id=user_id,
            text="Do you want to publish this series? NOTE: Once you publish this series, you can't edit it anymore. All the empty groups will be removed automatically.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Yes, Publish", callback_data=f"confirm_publish:{series_key}")],
                [InlineKeyboardButton("No, Cancel", callback_data=f"back_to_series:{series_key}")]
            ])
        )
        temp_admin_data[user_id]["main_message_id"] = new_msg.id # Update stored message ID
    except Exception as e:
        logger.error(f"An unexpected error occurred editing publish confirmation message: {e}")
        await client.send_message(user_id, "Error with publish confirmation. Please try again.")

    temp_admin_data[user_id]["state"] = "AWAITING_PUBLISH_CONFIRMATION"

@Client.on_callback_query(filters.regex(r"^confirm_publish:") & filters.user(ADMINS))
async def confirm_publish_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    series_key = callback_query.data.split(":")[1]
    main_message_id = temp_admin_data[user_id].get("main_message_id")

    if publish_series(series_key):
        try:
            await client.edit_message_text(
                chat_id=user_id,
                message_id=main_message_id,
                text="Published Successfully! This series is now live and cannot be edited via this UI."
            )
        except (MessageIdInvalid, FloodWait) as e:
            logger.warning(f"Failed to edit final publish message (ID: {main_message_id}): {e}. Sending a new one.")
            await client.send_message(
                chat_id=user_id,
                text="Published Successfully! This series is now live and cannot be edited via this UI."
            )
        except Exception as e:
            logger.error(f"An unexpected error occurred editing final publish message: {e}")
            await client.send_message(user_id, "Published Successfully! (But failed to update message).")
            
        temp_admin_data.pop(user_id, None) # Clear session data for this admin
    else:
        try:
            await client.edit_message_text(
                chat_id=user_id,
                message_id=main_message_id,
                text="Failed to publish series. Please try again."
            )
        except (MessageIdInvalid, FloodWait) as e:
            logger.warning(f"Failed to edit failed-publish message (ID: {main_message_id}): {e}. Sending a new one.")
            await client.send_message(
                chat_id=user_id,
                text="Failed to publish series. Please try again."
            )
        except Exception as e:
            logger.error(f"An unexpected error occurred editing failed-publish message: {e}")
            await client.send_message(user_id, "Failed to publish series. (But failed to update message).")

        # Re-send the main series message if publishing failed
        series_data = get_series_by_key(series_key)
        if series_data: # Ensure series_data is not None before passing
            new_main_msg_id = await send_main_series_message(client, user_id, series_data, main_message_id)
            if new_main_msg_id: temp_admin_data[user_id]["main_message_id"] = new_main_msg_id
            temp_admin_data[user_id]["state"] = "SERIES_DETAILS_VIEW"
        else:
            await client.send_message(user_id, "Series data not found after failed publish attempt. Please check logs.")
            temp_admin_data.pop(user_id, None) # Clear session if series data is completely lost
