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
    IMDB
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
    log_user_activity,
    log_error,
    log_info,
    log_warning,
    log_debug,
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
        
        # Use the async search function
        matching_series = await search_published_series(text, limit=10)

        series_data = None

        # Try exact match by key or title from the matching_series
        for s in matching_series:
            if text.lower() == s['_id'].lower() or text.lower() == s['title'].lower():
                series_data = s
                log_info(f"Exact match found: {s['title']}")
                break
             
        # If no exact match, try close matches from the titles of matching_series
        if not series_data:
            matching_series_titles = [s['title'] for s in matching_series]
            close_matches_titles = find_close_matches(text, matching_series_titles)
            
            if not close_matches_titles:
                # Fallback to checking if the first word matches any title if no close matches
                first_word = text.split()[0]
                close_matches_titles = [name for name in matching_series_titles if name.lower().startswith(first_word.lower())]
            
            if close_matches_titles:
                log_info(f"Close matches found: {close_matches_titles}")
                buttons = []
                for match_title in close_matches_titles:
                    # Find the series data for the matched title
                    matched_series = next((s for s in matching_series if s['title'] == match_title), None)
                    if matched_series:
                        buttons.append(
                            InlineKeyboardButton(match_title, callback_data=f"spellcheck-{matched_series['_id']}")
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
            
            # Filter out languages with no seasons
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
            # Admin functionality would go here
            # For now, just handle public filters
            glob = await global_filters(client, message)
            if glob == False:
                await series_filter(client, message)
        else:
            # Handle non-admin messages (public filters)
            glob = await global_filters(client, message)
            if glob == False:
                await series_filter(client, message)
                
    except Exception as e:
        log_error(f"Error in main message handler: {e}")

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
