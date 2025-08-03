import re
import os
import time
import math
import json
import string
import random
import asyncio
import logging
import requests
import pyrogram
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors.exceptions.bad_request_400 import MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty
from Script import script
from info import ADMINS, AUTH_CHANNEL, CUSTOM_FILE_CAPTION
from pyrogram.errors import FloodWait, UserIsBlocked, MessageNotModified, PeerIdInvalid
from utils import get_size, is_subscribed, get_poster, search_gagala, temp, get_settings, save_group_settings
from database.users_chats_db import db
from database.ia_filterdb import Media, get_file_details, unpack_new_file_id, get_bad_files
from database.gfilters_mdb import find_gfilter, get_gfilters
from database.connections_mdb import active_connection
import logging
from imdb import Cinemagoer
from fuzzywuzzy import fuzz
from difflib import get_close_matches

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Initialize IMDb
imdb = Cinemagoer()

class TempData:
    def __init__(self):
        self.ADMIN = {}
        self.U_NAME = None  # Bot username, set during bot startup
        self.B_NAME = None
        self.SETTINGS = {}
        self.FILES = {}
        self.admin_data = {}
        self.BANNED_CHATS = []
        self.BANNED_USERS = []
        self.MELCOW = {}
        self.CURRENT = int(os.environ.get("SKIP", 2))
        self.CANCEL = False
        self.ME = None

temp = TempData()

async def get_message_id(client, message):
    """
    Extracts channel ID and message ID from a forwarded message or a post link.
    Returns (channel_id, message_id) or (None, None) if invalid.
    """
    try:
        if message.forward_from_chat:
            # Forwarded message
            channel_id = message.forward_from_chat.id
            msg_id = message.forward_from_message_id
            logger.info(f"Extracted from forwarded message - Channel: {channel_id}, Message: {msg_id}")
            return channel_id, msg_id
        elif message.text and ('t.me/' in message.text or 'telegram.me/' in message.text):
            # Message link
            link = message.text.strip()
            if '/c/' in link:
                # Private channel link
                parts = link.split('/')
                channel_id = int('-100' + parts[-2])
                msg_id = int(parts[-1])
            else:
                # Public channel link
                parts = link.split('/')
                username = parts[-2]
                msg_id = int(parts[-1])
                try:
                    chat = await client.get_chat(username)
                    channel_id = chat.id
                except Exception as e:
                    logger.error(f"Error getting chat info for {username}: {e}")
                    return None, None
            
            logger.info(f"Extracted from link - Channel: {channel_id}, Message: {msg_id}")
            return channel_id, msg_id
        else:
            logger.warning("No forwarded message or valid link found")
            return None, None
    except Exception as e:
        logger.error(f"Error extracting message ID: {e}")
        return None, None

async def get_messages_in_range(client, source_channel_id, start_msg_id, end_msg_id, target_channel_id):
    """
    Copies messages from a source channel within a given range to a target channel.
    Returns a list of copied messages.
    """
    try:
        copied_messages = []
        logger.info(f"Copying messages from {start_msg_id} to {end_msg_id} in channel {source_channel_id}")
        
        for msg_id in range(start_msg_id, end_msg_id + 1):
            try:
                message = await client.get_messages(source_channel_id, msg_id)
                if message and not message.empty:
                    # Copy message to target channel
                    if message.media:
                        copied_msg = await client.copy_message(
                            chat_id=target_channel_id,
                            from_chat_id=source_channel_id,
                            message_id=msg_id
                        )
                    else:
                        copied_msg = await client.send_message(
                            chat_id=target_channel_id,
                            text=message.text or message.caption or "File"
                        )
                    copied_messages.append(copied_msg)
                    logger.info(f"Copied message {msg_id} to {copied_msg.id}")
                    
                    # Small delay to avoid flood limits
                    await asyncio.sleep(0.1)
                    
            except Exception as e:
                logger.error(f"Error copying message {msg_id}: {e}")
                continue
        
        logger.info(f"Successfully copied {len(copied_messages)} messages")
        return copied_messages
        
    except Exception as e:
        logger.error(f"Error in get_messages_in_range: {e}")
        return []

async def delete_messages_from_user_chat(client, user_id, message_ids):
    """Deletes a list of messages from the user's private chat."""
    try:
        if message_ids:
            await client.delete_messages(chat_id=user_id, message_ids=message_ids)
            logger.info(f"Deleted {len(message_ids)} messages from user {user_id}")
    except Exception as e:
        logger.error(f"Error deleting messages from user chat: {e}")

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

def get_file_id(msg: pyrogram.types.Message):
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

def extract_user(message: pyrogram.types.Message) -> (int, str):
    """extracts the user from a message"""
    # https://github.com/SpEcHiDe/PyroGramBot/blob/f30e2cca12002121bad1982f68cd0ff9814ce027/pyrobot/helper_functions/extract_user.py#L7
    user_id = None
    user_first_name = None
    if message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
        user_first_name = message.reply_to_message.from_user.first_name
    elif len(message.command) > 1:
        if (
            len(message.entities) >= 2 and
            message.entities[1].type == enums.MessageEntityType.TEXT_MENTION
        ):
            # 0: is the command
            # 1: should be the user
            required_entity = message.entities[1]
            user_id = required_entity.user.id
            user_first_name = required_entity.user.first_name
        else:
            user_id = message.command[1]
            # don't want to make a request -_-
            user_first_name = user_id
        try:
            user_id = int(user_id)
        except ValueError:
            pass
    else:
        user_id = message.from_user.id
        user_first_name = message.from_user.first_name
    return user_id, user_first_name

def last_online(from_user):
    time_list = ["s", "m", "h", "days"]
    if from_user.is_bot:
        return ""
    elif from_user.status == enums.UserStatus.RECENTLY:
        return "Recently"
    elif from_user.status == enums.UserStatus.LAST_WEEK:
        return "Within the last week"
    elif from_user.status == enums.UserStatus.LAST_MONTH:
        return "Within the last month"
    elif from_user.status == enums.UserStatus.LONG_AGO:
        return "A long time ago :("
    elif from_user.status == enums.UserStatus.ONLINE:
        return "Currently Online"
    elif from_user.status == enums.UserStatus.OFFLINE:
        return from_user.last_online_date.strftime("%a, %d %b %Y, %I:%M %p")

def split_quotes(text: str) -> list:
    if not any(i in text for i in ('\n', '\r')):
        return text.split(None, 1)
    return [i.strip() for i in re.findall(r'(?:[^\s,"]|"(?:\\.|[^"])*")+', text)]

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

def shortlink(url, api):
    main_url = f'https://{SHORTLINK_URL}/api'
    param = {'api': api, 'url': url}
    try:
        resp = requests.get(main_url, params=param, timeout=5)
        data = resp.json()
        if data["status"] == "success":
            return data['shortenedUrl']
        else:
            logger.error(f"Error in shortlink generation: {data}")
            return url
    except Exception as e:
        logger.error(f"Error in shortlink: {e}")
        return url

def get_shortlink(chat_id, url):
    if not SHORTLINK_URL:
        return url
    elif chat_id in SHORTLINK.get('exclude', []):
        return url
    else:
        return shortlink(url, SHORTLINK_API)

async def check_token_validity(api):
    main_url = f'https://{SHORTLINK_URL}/api'
    param = {'api': api}
    try:
        resp = requests.get(main_url, params=param, timeout=5)
        data = resp.json()
        return data.get("status") == "success"
    except Exception as e:
        logger.error(f"Error checking token validity: {e}")
        return False

async def get_shortlink_stats(api):
    main_url = f'https://{SHORTLINK_URL}/api/stats'
    param = {'api': api}
    try:
        resp = requests.get(main_url, params=param, timeout=5)
        data = resp.json()
        return data
    except Exception as e:
        logger.error(f"Error getting shortlink stats: {e}")
        return {}

async def is_subscribed(client, query):
    try:
        user = await client.get_chat_member(AUTH_CHANNEL, query.from_user.id)
    except UserNotParticipant:
        pass
    except Exception as e:
        logger.exception(e)
    else:
        if user.status != enums.ChatMemberStatus.BANNED:
            return True
    return False

async def get_poster(query, bulk=False, id=False, file=None):
    if not IMDB:
        return None
    
    logger.info(f"IMDB query: {query}")
    
    try:
        if id:
            # If query is an IMDb ID, get movie by ID
            movie = imdb.get_movie(query)
            movies = [movie] if movie else []
        else:
            # Search for movies/series
            movies = imdb.search_movie(query)
        
        if not movies:
            logger.warning(f"No IMDB results found for: {query}")
            return None
        
        if bulk:
            # Return multiple results for selection
            results = []
            for movie in movies[:10]:  # Limit to 10 results
                try:
                    imdb.update(movie, info=['main'])
                    poster = movie.get('full-size cover url', movie.get('cover url'))
                    results.append({
                        'title': movie.get('title', 'N/A'),
                        'year': movie.get('year', 'N/A'),
                        'imdb_id': movie.movieID,
                        'kind': movie.get('kind', 'movie'),
                        'poster': poster,
                        'rating': movie.get('rating', 'N/A'),
                        'genres': ', '.join(movie.get('genres', [])),
                        'plot': movie.get('plot outline', movie.get('plot', ['N/A'])[0] if movie.get('plot') else 'N/A')
                    })
                except Exception as e:
                    logger.error(f"Error processing movie {movie}: {e}")
                    continue
            return results
        else:
            # Return single result
            movie = movies[0]
            try:
                imdb.update(movie, info=['main'])
                poster = movie.get('full-size cover url', movie.get('cover url'))
                return {
                    'title': movie.get('title', 'N/A'),
                    'year': movie.get('year', 'N/A'),
                    'imdb_id': movie.movieID,
                    'kind': movie.get('kind', 'movie'),
                    'poster': poster,
                    'rating': movie.get('rating', 'N/A'),
                    'genres': ', '.join(movie.get('genres', [])),
                    'plot': movie.get('plot outline', movie.get('plot', ['N/A'])[0] if movie.get('plot') else 'N/A')
                }
            except Exception as e:
                logger.error(f"Error processing single movie result: {e}")
                return None
                
    except Exception as e:
        logger.error(f"Error in get_poster: {e}")
        return None

async def search_gagala(text):
    usr_agent = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/61.0.3163.100 Safari/537.36'
        }
    text = text.replace(" ", '+')
    url = f'https://www.google.com/search?q={text}'
    try:
        resp = requests.get(url, headers=usr_agent, timeout=5)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.error(f"Error in Google search: {e}")
        return ""

def find_most_similar_title(query, titles):
    """Find the most similar title using fuzzy matching."""
    if not titles:
        return None
    
    # Use fuzzywuzzy to find the best match
    best_match = None
    best_ratio = 0
    
    for title in titles:
        ratio = fuzz.ratio(query.lower(), title.lower())
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = title
    
    # Return the best match if it's above a threshold
    return best_match if best_ratio >= 60 else None

def chunk_buttons(buttons, chunk_size=2):
    """Chunk buttons into rows."""
    if not buttons:
        return []
    
    chunked = []
    for i in range(0, len(buttons), chunk_size):
        chunked.append(buttons[i:i + chunk_size])
    return chunked

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

def get_readable_time(seconds: int) -> str:
    count = 0
    up_time = ""
    time_list = []
    time_suffix_list = ["s", "m", "h", "days"]
    while count < 4:
        count += 1
        remainder, result = divmod(seconds, 60) if count < 3 else divmod(seconds, 24)
        if seconds == 0 and remainder == 0:
            break
        time_list.append(int(result))
        seconds = int(remainder)
    hmm = len(time_list)
    for x in range(hmm):
        time_list[x] = str(time_list[x]) + time_suffix_list[x]
    if len(time_list) == 4:
        up_time += f"{time_list.pop()}, "
    time_list.reverse()
    up_time += ":".join(time_list)
    return up_time

def get_readable_file_size(size_bytes):
    if size_bytes is None:
        return "0B"
    index = 0
    size_bytes = float(size_bytes)
    while size_bytes >= 1024:
        size_bytes /= 1024
        index += 1
    try:
        return f'{round(size_bytes, 2)}{["B", "KB", "MB", "GB", "TB"][index]}'
    except IndexError:
        return 'File too large'

def get_progress_bar_string(pct):
    pct = float(str(pct).strip('%'))
    p = min(max(pct, 0), 100)
    cFull = int(p // 8)
    p_str = '■' * cFull
    p_str += '□' * (12 - cFull)
    return f"[{p_str}]"

def time_formatter(milliseconds: int) -> str:
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    tmp = ((str(days) + "d, ") if days else "") + \
        ((str(hours) + "h, ") if hours else "") + \
        ((str(minutes) + "m, ") if minutes else "") + \
        ((str(seconds) + "s, ") if seconds else "") + \
        ((str(milliseconds) + "ms, ") if milliseconds else "")
    return tmp[:-2]

def get_file_name(media_msg):
    """Get file name from media message."""
    try:
        if media_msg.document:
            return media_msg.document.file_name
        elif media_msg.video:
            return media_msg.video.file_name or f"video_{media_msg.video.file_id[:10]}.mp4"
        elif media_msg.audio:
            return media_msg.audio.file_name or f"audio_{media_msg.audio.file_id[:10]}.mp3"
        elif media_msg.photo:
            return f"photo_{media_msg.photo.file_id[:10]}.jpg"
        elif media_msg.animation:
            return media_msg.animation.file_name or f"animation_{media_msg.animation.file_id[:10]}.gif"
        elif media_msg.voice:
            return f"voice_{media_msg.voice.file_id[:10]}.ogg"
        elif media_msg.video_note:
            return f"video_note_{media_msg.video_note.file_id[:10]}.mp4"
        elif media_msg.sticker:
            return f"sticker_{media_msg.sticker.file_id[:10]}.webp"
        else:
            return "unknown_file"
    except Exception as e:
        logger.error(f"Error getting file name: {e}")
        return "unknown_file"

async def encode_file_id(s: str) -> str:
    return s

async def decode_file_id(s: str) -> str:
    return s

def get_file_type(file_path):
    """Get file type from file path."""
    if not file_path:
        return "unknown"
    
    extension = file_path.split('.')[-1].lower()
    
    video_extensions = ['mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv', 'webm', '3gp']
    audio_extensions = ['mp3', 'wav', 'flac', 'aac', 'ogg', 'wma', 'm4a']
    image_extensions = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg']
    document_extensions = ['pdf', 'doc', 'docx', 'txt', 'rtf', 'odt']
    
    if extension in video_extensions:
        return "video"
    elif extension in audio_extensions:
        return "audio"
    elif extension in image_extensions:
        return "image"
    elif extension in document_extensions:
        return "document"
    else:
        return "document"  # Default to document for unknown types

def format_file_size(bytes_size):
    """Format file size in human readable format."""
    if bytes_size == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = int(math.floor(math.log(bytes_size, 1024)))
    p = math.pow(1024, i)
    s = round(bytes_size / p, 2)
    return f"{s} {size_names[i]}"

def clean_file_name(file_name):
    """Clean file name by removing special characters."""
    if not file_name:
        return "unknown_file"
    
    # Remove or replace problematic characters
    cleaned = re.sub(r'[<>:"/\\|?*]', '_', file_name)
    cleaned = re.sub(r'[^\w\s.-]', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    return cleaned if cleaned else "unknown_file"

def get_duration_string(duration_seconds):
    """Convert duration in seconds to readable string."""
    if not duration_seconds:
        return "Unknown"
    
    hours = duration_seconds // 3600
    minutes = (duration_seconds % 3600) // 60
    seconds = duration_seconds % 60
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes:02d}:{seconds:02d}"

def is_valid_file_id(file_id):
    """Check if file ID is valid."""
    if not file_id or not isinstance(file_id, str):
        return False
    
    # Basic validation - Telegram file IDs are usually long alphanumeric strings
    return len(file_id) > 10 and file_id.replace('_', '').replace('-', '').isalnum()

def generate_random_string(length=10):
    """Generate random string of specified length."""
    letters = string.ascii_lowercase + string.digits
    return ''.join(random.choice(letters) for _ in range(length))

def escape_markdown(text):
    """Escape markdown special characters."""
    if not text:
        return ""
    
    escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    return text

def truncate_text(text, max_length=100):
    """Truncate text to specified length."""
    if not text:
        return ""
    
    if len(text) <= max_length:
        return text
    
    return text[:max_length-3] + "..."

def validate_url(url):
    """Validate if string is a valid URL."""
    if not url:
        return False
    
    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    
    return url_pattern.match(url) is not None

def get_file_extension(filename):
    """Get file extension from filename."""
    if not filename:
        return ""
    
    return filename.split('.')[-1].lower() if '.' in filename else ""

def format_caption(template, **kwargs):
    """Format caption template with provided kwargs."""
    try:
        return template.format(**kwargs)
    except KeyError as e:
        logger.error(f"Missing key in caption template: {e}")
        return template
    except Exception as e:
        logger.error(f"Error formatting caption: {e}")
        return template

def is_admin_user(user_id):
    """Check if user is admin."""
    return user_id in ADMINS

def get_random_pic():
    """Get random picture from PICS list."""
    if PICS:
        return random.choice(PICS)
    return NOR_IMG

def get_spell_check_image():
    """Get random spell check image."""
    if SPELL_IMG:
        return random.choice(SPELL_IMG)
    return NOR_IMG

def log_user_activity(user_id, activity, details=None):
    """Log user activity."""
    logger.info(f"User {user_id} - {activity}" + (f" - {details}" if details else ""))

def log_error(error, context=None):
    """Log error with context."""
    logger.error(f"Error: {error}" + (f" - Context: {context}" if context else ""))

def log_info(message, context=None):
    """Log info message."""
    logger.info(f"{message}" + (f" - Context: {context}" if context else ""))

def log_warning(message, context=None):
    """Log warning message."""
    logger.warning(f"{message}" + (f" - Context: {context}" if context else ""))

def log_debug(message, context=None):
    """Log debug message."""
    logger.debug(f"{message}" + (f" - Context: {context}" if context else ""))
