import logging
import asyncio
import re
import os
from datetime import datetime
from typing import Union, List
from pyrogram.errors import InputUserDeactivated, UserNotParticipant, FloodWait, UserIsBlocked, PeerIdInvalid, MessageIdInvalid
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto
from pyrogram import enums
from imdb import Cinemagoer
from bs4 import BeautifulSoup
import requests
from fuzzywuzzy import fuzz
import uuid

from info import ADMINS, AUTH_CHANNEL, LONG_IMDB_DESCRIPTION, MAX_LIST_ELM, DB_CHANNEL, RAW_DB_CHANNEL, AUTO_DELETE_TIME, AUTO_DELETE_MSG, NO_POSTER_FOUND_IMG, TMDB_API_KEY, TVDB_API_KEY, OMDB_API_KEY, Assigned
from database.crazy_db import episodes_collection

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BTN_URL_REGEX = re.compile(
    r"(\[([^\[]+?)\]$$(buttonurl|buttonalert):(?:/\{0,2\})(.+?)(:same)?$$)"
)
temp_requests = {}
AUTO_DEL_SUCCESS_MSG = """Your File Has Been Deleted To Avoid BOT Copyright.\nYou Can Request Again If You Want!🫵🏻"""
imdb = Cinemagoer() 

BANNED = {}
SMART_OPEN = '"'
SMART_CLOSE = '"'
START_CHAR = ('\'', '"', SMART_OPEN)

class Temp(object):
    """
    A temporary storage class for bot-related data that needs to persist
    across different parts of the application during runtime.
    """
    BANNED_USERS = []
    BANNED_CHATS = []
    ME = None  # Bot's user ID
    U_NAME = None  # Bot's username
    B_NAME = None  # Bot's first name
    LINK_ONE = None # Invite link for REQ_CHANNEL_ONE
    LINK_TWO = None # Invite link for REQ_CHANNEL_TWO
    AUTO_DELETE_TIME = AUTO_DELETE_TIME # Time in seconds to auto-delete messages
    AUTO_DELETE_MSG = "This message will be auto-deleted in {time} seconds to save chat space."

temp = Temp()

async def get_poster_from_all_apis(query):
    """
    Try to get poster from multiple APIs (TMDB, IMDb, TVDB, OMDB)
    Returns the first available poster URL or None
    """
    # Try TMDB first
    tmdb_info = await get_tmdb_info(query, bulk=False)
    if tmdb_info and tmdb_info.get('poster_url'):
        return tmdb_info['poster_url']
    
    # Try IMDb
    imdb_info = await get_poster(query, bulk=False)
    if imdb_info and imdb_info.get('poster_url'):
        return imdb_info['poster_url']
    
    # Try TVDB
    tvdb_info = await get_tvdb_info(query)
    if tvdb_info and tvdb_info.get('poster_url'):
        return tvdb_info['poster_url']
    
    # Try OMDB
    omdb_info = await get_omdb_info(query)
    if omdb_info and omdb_info.get('poster_url'):
        return omdb_info['poster_url']
    
    return None

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

    
async def get_comprehensive_series_info(query):
    """
    Get comprehensive series information from multiple sources with fuzzy matching
    Ensures title and released_on are always present, and tries to get rating and genre
    """
    info = {
        'title': None,
        'released_on': None,
        'rating': None,
        'genre': None,
        'poster_url': None,
        'media_type': 'series'
    }
    
    # Try TMDB first
    tmdb_results = await get_tmdb_info(query, bulk=True)
    if tmdb_results:
        # Use fuzzy matching to find the best result
        best_match = find_most_similar_title(query, [r['title'] for r in tmdb_results])
        if best_match:
            best_match = best_match[0]  # Take the top match
            for result in tmdb_results:
                if result['title'] == best_match:
                    tmdb_info = await get_tmdb_info(query, tmdb_id=result['tmdb_id'], media_type=result['media_type'])
                    if tmdb_info:
                        info.update({
                            'title': tmdb_info.get('title'),
                            'released_on': tmdb_info.get('year'),
                            'rating': tmdb_info.get('rating'),
                            'genre': tmdb_info.get('genres'),
                            'poster_url': tmdb_info.get('poster_url'),
                            'media_type': tmdb_info.get('media_type', 'series')
                        })
                    break
    
    # If title or released_on is missing, try IMDb
    if not info.get('title') or not info.get('released_on'):
        imdb_results = await get_poster(query, bulk=True)
        if imdb_results:
            best_match = find_most_similar_title(query, [r['title'] for r in imdb_results])
            if best_match:
                best_match = best_match[0]
                for result in imdb_results:
                    if result['title'] == best_match:
                        imdb_info = await get_poster(result['imdb_id'], id=True)
                        if imdb_info:
                            if not info.get('title'):
                                info['title'] = imdb_info.get('title')
                            if not info.get('released_on'):
                                info['released_on'] = imdb_info.get('year')
                            if not info.get('rating'):
                                info['rating'] = imdb_info.get('rating')
                            if not info.get('genre'):
                                info['genre'] = imdb_info.get('genres')
                            if not info.get('poster_url'):
                                info['poster_url'] = imdb_info.get('poster_url')
                            if not info.get('media_type'):
                                info['media_type'] = imdb_info.get('media_type', 'series')
                        break
    
    # If still missing, try TVDB
    if not info.get('title') or not info.get('released_on'):
        tvdb_info = await get_tvdb_info(query)
        if tvdb_info:
            if not info.get('title'):
                info['title'] = tvdb_info.get('title')
            if not info.get('released_on'):
                info['released_on'] = tvdb_info.get('year')
            if not info.get('rating'):
                info['rating'] = tvdb_info.get('rating')
            if not info.get('genre'):
                info['genre'] = tvdb_info.get('genre')
            if not info.get('poster_url'):
                info['poster_url'] = tvdb_info.get('poster_url')
    
    # If still missing, try OMDB
    if not info.get('title') or not info.get('released_on'):
        omdb_info = await get_omdb_info(query)
        if omdb_info:
            if not info.get('title'):
                info['title'] = omdb_info.get('title')
            if not info.get('released_on'):
                info['released_on'] = omdb_info.get('year')
            if not info.get('rating'):
                info['rating'] = omdb_info.get('rating')
            if not info.get('genre'):
                info['genre'] = omdb_info.get('genre')
            if not info.get('poster_url'):
                info['poster_url'] = omdb_info.get('poster_url')
    
    # Ensure we have at least title and released_on
    if not info.get('title'):
        info['title'] = query
    if not info.get('released_on'):
        info['released_on'] = "N/A"
    
    # Format genre and rating properly
    if info.get('genre') and isinstance(info['genre'], list):
        info['genre'] = ', '.join(info['genre'][:3])  # Limit to 3 genres
    
    return info

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

async def send_poster_to_admin_channel(client, user_id, poster_url=None, message=None, caption="#MainPoster"):
    """
    Send a poster to the admin's assigned channel and return the file ID.
    If a poster with the same caption already exists, delete it and send a new one.
    Uses message copying instead of downloading/uploading for efficiency.
    """
    # Get the assigned channel for this admin
    channel_id = Assigned.get(user_id)
    if not channel_id:
        # If not assigned, use the default LOG_CHANNEL
        channel_id = LOG_CHANNEL
    
    # First, check if there's already a message with the same caption in the channel
    async for msg in client.iter_messages(channel_id, limit=100):
        if msg.caption and msg.caption.strip() == caption:
            await msg.delete()
    
    # Now send the new poster
    try:
        if poster_url:
            # For URL posters, we need to download and upload as Telegram can't directly send from external URLs
            response = requests.get(poster_url)
            if response.status_code == 200:
                temp_path = f"temp_poster_{uuid.uuid4()}.jpg"
                with open(temp_path, 'wb') as f:
                    f.write(response.content)
                try:
                    sent_msg = await client.send_photo(channel_id, photo=temp_path, caption=caption)
                    return sent_msg.photo.file_id
                finally:
                    os.remove(temp_path)
        elif message:
            # For user-provided media, copy directly to the channel
            if message.photo:
                # Copy photo message
                sent_msg = await message.copy(chat_id=channel_id, caption=caption)
                return sent_msg.photo.file_id
            elif message.video and message.video.thumbs:
                # For videos, use the thumbnail as poster
                thumb = message.video.thumbs[0]
                sent_msg = await client.send_photo(
                    chat_id=channel_id,
                    photo=thumb.file_id,
                    caption=caption
                )
                return sent_msg.photo.file_id
    except Exception as e:
        logger.error(f"Error sending poster to admin channel: {e}")
    
    return None

async def is_subscribed(bot, query=None, userid=None):
    try:
        if userid == None and query != None:
            user = await bot.get_chat_member(AUTH_CHANNEL, query.from_user.id)
        else:
            user = await bot.get_chat_member(AUTH_CHANNEL, int(userid))
    except UserNotParticipant:
        pass
    except Exception as e:
        logger.exception(e)
    else:
        if user.status != enums.ChatMemberStatus.BANNED:
            return True
    return False

async def get_message_id(client, message):
    if message.forward_from_chat:
        # Forwarded message case
        channel_id = str(message.forward_from_chat.id) 
        if int(channel_id) in DB_CHANNEL or int(channel_id) in RAW_DB_CHANNEL:
            return channel_id, message.forward_from_message_id
        else:
            return 0, 0
    elif message.text:
        pattern = r"https://t.me/(?:c/)?(\d+)/(\d+)"
        matches = re.match(pattern, message.text)
        if not matches:
            return 0, 0
        extracted_channel_id = matches.group(1)
        msg_id = int(matches.group(2))
        
        # Convert extracted_channel_id to Pyrogram's internal format if it's a raw ID
        # Pyrogram uses -100 for supergroups, so if it's a raw ID like 12345, it becomes -10012345
        if not extracted_channel_id.startswith('-100'):
            extracted_channel_id = f"-100{extracted_channel_id}"

        if int(extracted_channel_id) in DB_CHANNEL or int(extracted_channel_id) in RAW_DB_CHANNEL: 
            return extracted_channel_id, msg_id
        else:
            return 0, 0
    else:
        return 0, 0

async def get_messages(client, source_channel_id, message_ids: Union[List[int], range]):
    """
    Fetches messages from a source channel given a list of message IDs.
    Returns a list of the fetched messages.
    """
    messages = []
    
    # Ensure source_channel_id is in Pyrogram's format (-100xxxx)
    if not str(source_channel_id).startswith('-100'):
        source_channel_id = int(f"-100{source_channel_id}")
    else:
        source_channel_id = int(source_channel_id)

    message_ids_to_fetch = list(message_ids) # Convert range to list if it's a range
    
    total_fetched = 0
    while total_fetched < len(message_ids_to_fetch):
        batch_ids = message_ids_to_fetch[total_fetched:total_fetched + 200] # Fetch in batches
        try:
            msgs = await client.get_messages(chat_id=source_channel_id, message_ids=batch_ids)
            messages.extend(msgs)
            total_fetched += len(batch_ids)
        except FloodWait as e:
            logger.warning(f"FloodWait during get_messages: Sleeping for {e.x} seconds")
            await asyncio.sleep(e.x)
        except Exception as e:
            logger.error(f"Error fetching messages from {source_channel_id}: {e}")
            break # Exit on unexpected exceptions
    return messages

async def delete_messages_from_user_chat(client, user_id, message_ids: List[int]):
    """Deletes a list of messages from a user's private chat with the bot."""
    if not message_ids:
        return
    try:
        await client.delete_messages(chat_id=user_id, message_ids=message_ids)
        logger.info(f"Deleted messages {message_ids} from user {user_id} chat.")
    except MessageIdInvalid:
        logger.warning(f"Some messages in {message_ids} for user {user_id} were already deleted or invalid.")
    except Exception as e:
        logger.error(f"Error deleting messages {message_ids} from user {user_id} chat: {e}")

async def delete_file(messages, client, process):
    await asyncio.sleep(temp.AUTO_DELETE_TIME)
    for msg in messages:
        try:
            await client.delete_messages(chat_id=msg.chat.id, message_ids=[msg.id])
        except Exception as e:
            await asyncio.sleep(e.x)
            print(f"The attempt to delete the media {msg.id} was unsuccessful: {e}")
    await process.edit_text(AUTO_DEL_SUCCESS_MSG)

async def get_poster(query, bulk=False, id=False):
    try:
        if not id:
            search_results = imdb.search_movie(query)
            if not search_results:
                return None
            if bulk:
                top_movies = []
                for movie in search_results[:5]:
                    try:
                        movie_id = movie.movieID
                        full_movie = imdb.get_movie(movie_id)
                        top_movies.append({
                            'title': full_movie.get('title', 'N/A'),
                            'released_on': str(full_movie.get('year', 'N/A')),  # Changed to 'released_on'
                            'imdb_id': movie_id
                        })
                    except Exception as e:
                        print(f"Error fetching movie details: {e}")
                        continue
                return top_movies
            movie = search_results[0]
            movie_id = movie.movieID
        else:
            movie_id = query
        movie = imdb.get_movie(movie_id)
        if not movie:
            return None
        
        # Format release date - IMDb only provides year
        year = movie.get('year', 'N/A')
        if year != 'N/A':
            formatted_date = str(year)
        else:
            formatted_date = 'N/A'
            
        return {
            'title': movie.get('title', 'N/A'),
            'released_on': formatted_date,  # Changed to 'released_on'
            'genres': ', '.join(movie.get('genres', [])) or 'N/A',
            'languages': ', '.join(movie.get('languages', [])) or 'Original Audio',
            'rating': movie.get('rating', 'N/A'),
            'plot': movie.get('plot outline') or (movie.get('plot', ['N/A'])[0]),
            'poster': movie.get('full-size cover url', 'N/A'),
            'imdb_id': movie_id,
            'url': f'https://www.imdb.com/title/tt{movie_id}'
        }
    except Exception as e:
        print(f"IMDb Error: {e}")
        return None
        
async def broadcast_messages(user_id, message):
    try:
        await message.copy(chat_id=user_id)
        return True, "Success"
    except FloodWait as e:
        await asyncio.sleep(e.x)
        return await broadcast_messages(user_id, message)
    except InputUserDeactivated:
        await db.delete_user(int(user_id))
        logging.info(f"{user_id}-Removed from Database, since deleted account.")
        return False, "Deleted"
    except UserIsBlocked:
        logging.info(f"{user_id} -Blocked the bot.")
        return False, "Blocked"
    except PeerIdInvalid:
        await db.delete_user(int(user_id))
        logging.info(f"{user_id} - PeerIdInvalid")
        return False, "Error"
    except Exception as e:
        return False, "Error"

async def broadcast_messages_group(chat_id, message):
    try:
        kd = await message.copy(chat_id=chat_id)
        try:
            await kd.pin()
        except:
            pass
        return True, "Succes"
    except FloodWait as e:
        await asyncio.sleep(e.x)
        return await broadcast_messages_group(chat_id, message)
    except Exception as e:
        return False, "Error"

async def search_gagala(text):
    usr_agent = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/61.0.3163.100 Safari/537.36'
        }
    text = text.replace(" ", '+')
    url = f'https://www.google.com/search?q={text}'
    response = requests.get(url, headers=usr_agent)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    titles = soup.find_all( 'h3' )
    return [title.getText() for title in titles]

async def get_settings(group_id):
    settings = temp.SETTINGS.get(group_id)
    if not settings:
        settings = await db.get_settings(group_id)
        temp.SETTINGS[group_id] = settings
    return settings
    
async def save_group_settings(group_id, key, value):
    current = await get_settings(group_id)
    current[key] = value
    temp.SETTINGS[group_id] = current
    await db.update_settings(group_id, current)
    
def get_size(size):
    """Get size in readable format"""
    units = ["Bytes", "KB", "MB", "GB", "TB", "PB", "EB"]
    size = float(size)
    i = 0
    while size >= 1024.0 and i < len(units):
        i += 1
        size /= 1024.0
    return "%.2f %s" % (size, units[i])

def split_list(l, n):
    for i in range(0, len(l), n):
        yield l[i:i + n]  

# Moved get_file_id from plugins/get_file_id.py to here as it's a utility
def get_file_id(msg: Message):
    if msg.media:
        for message_type in (
            "photo",
            "animation",
            "audio",
            "document",
            "video",
            "video_note",
            "voice",
            "sticker"
        ):
            obj = getattr(msg, message_type)
            if obj:
                setattr(obj, "message_type", message_type)
                return obj

def extract_user(message: Message) -> Union[int, str]:
    """extracts the user from a message"""
    user_id = None
    user_first_name = None
    if message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
        user_first_name = message.reply_to_message.from_user.first_name
    elif len(message.command) > 1:
        if (
            len(message.entities) > 1 and
            message.entities[1].type == enums.MessageEntityType.TEXT_MENTION
        ):
            required_entity = message.entities[1]
            user_id = required_entity.user.id
            user_first_name = required_entity.user.first_name
        else:
            user_id = message.command[1]
            user_first_name = user_id
        try:
            user_id = int(user_id)
        except ValueError:
            pass
    else:
        user_id = message.from_user.id
        user_first_name = message.from_user.first_name
    return (user_id, user_first_name)

def list_to_str(k):
    if not k:
        return "N/A"
    elif len(k) == 1:
        return str(k[0])
    elif MAX_LIST_ELM:
        k = k[:int(MAX_LIST_ELM)]
        return ' '.join(f'{elem}, ' for elem in k)
    else:
        return ' '.join(f'{elem}, ' for elem in k)

def last_online(from_user):
    time = ""
    if from_user.is_bot:
        time += "🤖 Bot :("
    elif from_user.status == enums.UserStatus.RECENTLY:
        time += "Recently"
    elif from_user.status == enums.UserStatus.LAST_WEEK:
        time += "Within the last week"
    elif from_user.status == enums.UserStatus.LAST_MONTH:
        time += "Within the last month"
    elif from_user.status == enums.UserStatus.LONG_AGO:
        time += "A long time ago :("
    elif from_user.status == enums.UserStatus.ONLINE:
        time += "Currently Online"
    elif from_user.status == enums.UserStatus.OFFLINE:
        time += from_user.last_online_date.strftime("%a, %d %b %Y, %H:%M:%S")
    return time

def split_quotes(text: str) -> List:
    if not any(text.startswith(char) for char in START_CHAR):
        return text.split(None, 1)
    counter = 1  # ignore first char -> is some kind of quote
    while counter < len(text):
        if text[counter] == "\\":
            counter += 1
        elif text[counter] == text[0] or (text[0] == SMART_OPEN and text[counter] == SMART_CLOSE):
            break
        counter += 1
    else:
        return text.split(None, 1)
    key = remove_escapes(text[1:counter].strip())
    rest = text[counter + 1:].strip()
    if not key:
        key = text[0] + text[0]
    return list(filter(None, [key, rest]))

def gfilterparser(text, keyword):
    if "buttonalert" in text:
        text = (text.replace("\n", "\\n").replace("\t", "\\t"))
    buttons = []
    note_data = ""
    prev = 0
    i = 0
    alerts = []
    for match in BTN_URL_REGEX.finditer(text):
        n_escapes = 0
        to_check = match.start(1) - 1
        while to_check > 0 and text[to_check] == "\\":
            n_escapes += 1
            to_check -= 1
        if n_escapes % 2 == 0:
            note_data += text[prev:match.start(1)]
            prev = match.end(1)
            if match.group(3) == "buttonalert":
                if bool(match.group(5)) and buttons:
                    buttons[-1].append(InlineKeyboardButton(
                        text=match.group(2),
                        callback_data=f"gfilteralert:{i}:{keyword}"
                    ))
                else:
                    buttons.append([InlineKeyboardButton(
                        text=match.group(2),
                        callback_data=f"gfilteralert:{i}:{keyword}"
                    )])
                i += 1
                alerts.append(match.group(4))
            elif bool(match.group(5)) and buttons:
                buttons[-1].append(InlineKeyboardButton(
                    text=match.group(2),
                    url=match.group(4).replace(" ", "")
                ))
            else:
                buttons.append([InlineKeyboardButton(
                    text=match.group(2),
                    url=match.group(4).replace(" ", "")
                )])
        else:
            note_data += text[prev:to_check]
            prev = match.start(1) - 1
    else:
        note_data += text[prev:]
    try:
        return note_data, buttons, alerts
    except:
        return note_data, buttons, None
        
def parser(text, keyword):
    if "buttonalert" in text:
        text = (text.replace("\n", "\\n").replace("\t", "\\t"))
    buttons = []
    note_data = ""
    prev = 0
    i = 0
    alerts = []
    for match in BTN_URL_REGEX.finditer(text):
        n_escapes = 0
        to_check = match.start(1) - 1
        while to_check > 0 and text[to_check] == "\\":
            n_escapes += 1
            to_check -= 1
        if n_escapes % 2 == 0:
            note_data += text[prev:match.start(1)]
            prev = match.end(1)
            if match.group(3) == "buttonalert":
                if bool(match.group(5)) and buttons:
                    buttons[-1].append(InlineKeyboardButton(
                        text=match.group(2),
                        callback_data=f"alertmessage:{i}:{keyword}"
                    ))
                else:
                    buttons.append([InlineKeyboardButton(
                        text=match.group(2),
                        callback_data=f"alertmessage:{i}:{keyword}"
                    )])
                i += 1
                alerts.append(match.group(4))
            elif bool(match.group(5)) and buttons:
                buttons[-1].append(InlineKeyboardButton(
                    text=match.group(2),
                    url=match.group(4).replace(" ", "")
                ))
            else:
                buttons.append([InlineKeyboardButton(
                    text=match.group(2),
                    url=match.group(4).replace(" ", "")
                )])
        else:
            note_data += text[prev:to_check]
            prev = match.start(1) - 1
    else:
        note_data += text[prev:]
    try:
        return note_data, buttons, alerts
    except:
        return note_data, buttons, None

def remove_escapes(text: str) -> str:
    res = ""
    is_escaped = False
    for counter in range(len(text)):
        if is_escaped:
            res += text[counter]
            is_escaped = False
        elif text[counter] == "\\":
            is_escaped = True
        else:
            res += text[counter]
    return res

def humanbytes(size):
    if not size:
        return ""
    power = 2**10
    n = 0
    Dic_powerN = {0: ' ', 1: 'Ki', 2: 'Mi', 3: 'Gi', 4: 'Ti'}
    while size > power:
        size /= power
        n += 1
    return str(round(size, 2)) + " " + Dic_powerN[n] + 'B'

def _generate_reply_keyboard(options: List[str], row_width: int = 3):
    keyboard_buttons = []
    for i in range(0, len(options), row_width):
        row = [KeyboardButton(text) for text in options[i:i+row_width]]
        keyboard_buttons.append(row)
    return ReplyKeyboardMarkup(keyboard_buttons, resize_keyboard=True, one_time_keyboard=True)

def find_most_similar_title(query: str, titles: List[str]):
    """Finds the most similar title from a list using fuzzy matching."""
    if not titles:
        return None
    
    best_matches = []
    for title in titles:
        score = fuzz.ratio(query.lower(), title.lower())
        if score > 60:  # Only consider matches above 60% similarity
            best_matches.append((title, score))
    
    # Sort by score and return top matches
    best_matches.sort(key=lambda x: x[1], reverse=True)
    return [match[0] for match in best_matches[:5]]

async def get_links_for_quality(file_link_key: str):
    """
    Retrieves file information from the episodes collection based on a file_link_key.
    This function is crucial for fetching the actual media files associated with a quality.
    
    Args:
        file_link_key (str): The unique key linking to the file entries in the episodes collection.
        
    Returns:
        tuple: A tuple containing:
            - list: A list of dictionaries, each containing 'file_id' and 'caption' for the media.
            - int: Channel ID (placeholder, as it's not directly stored per link_key here).
            - int: First message ID (placeholder).
            - int: Last message ID (placeholder).
    """
    logger.info(f"Fetching file links for key: {file_link_key}")
    
    # Find the document in the episodes_collection using the file_link_key
    # Assuming each document in episodes_collection has a 'file_link_key' and 'files' field
    # where 'files' is a list of {'file_id': '...', 'caption': '...'}
    episode_doc = episodes_collection.find_one({"file_link_key": file_link_key})

    if episode_doc and episode_doc.get("files"):
        files_to_send = episode_doc["files"]
        # These values might be stored in the episode_doc or derived,
        # for now, they are placeholders.
        channel_id = episode_doc.get("channel_id", 0) 
        first_msg_id = episode_doc.get("first_msg_id", 0)
        last_msg_id = episode_doc.get("last_msg_id", 0)
        logger.info(f"Found {len(files_to_send)} files for link key {file_link_key}")
        return files_to_send, channel_id, first_msg_id, last_msg_id
    
    logger.warning(f"No files found in episodes_collection for link key: {file_link_key}")
    return [], 0, 0, 0
