import re
import asyncio
import requests
import time
from info import DB_CHANNEL, RAW_DB_CHANNEL, TMDB_API_KEY, IMGBB_API_KEY
from pyrogram.errors import FloodWait

class Temp:
    # A simple class to hold temporary global variables if needed
    # For example, U_NAME might be bot's username
    U_NAME = None 

temp = Temp() # Instantiate the Temp class

async def get_message_id(client, message):
    """
    Extracts channel ID and message ID from a forwarded message or a post link.
    Returns (channel_id, message_id) or (None, None).
    """
    if message.forward_from_chat and message.forward_from_message_id:
        return message.forward_from_chat.id, message.forward_from_message_id
    elif message.text and "t.me/c/" in message.text:
        match = re.search(r"t\.me/c/(\d+)/(\d+)", message.text)
        if match:
            chat_id_raw = int(match.group(1))
            msg_id = int(match.group(2))
            # Convert raw chat ID to Pyrogram format
            pyrogram_chat_id = int(f"-100{chat_id_raw}")
            return pyrogram_chat_id, msg_id
    return None, None

async def get_messages_in_range(client, channel_id, start_msg_id, end_msg_id, target_channel_id):
    """
    Copies messages from a source channel within a range to a target channel.
    Returns a list of copied message objects.
    """
    copied_messages = []
    for i in range(start_msg_id, end_msg_id + 1):
        try:
            msg = await client.get_messages(channel_id, i)
            if msg:
                # Copy message to target_channel_id
                copied_msg = await msg.copy(target_channel_id)
                copied_messages.append(copied_msg)
        except FloodWait as e:
            print(f"FloodWait during message copy: {e.value} seconds. Waiting...")
            await asyncio.sleep(e.value)
            # Retry the current message after waiting
            try:
                msg = await client.get_messages(channel_id, i)
                if msg:
                    copied_msg = await msg.copy(target_channel_id)
                    copied_messages.append(copied_msg)
            except Exception as retry_e:
                print(f"Error copying message {i} from {channel_id} after retry: {retry_e}")
                continue
        except Exception as e:
            # Handle MessageNotFound or other errors
            print(f"Error copying message {i} from {channel_id}: {e}")
            continue
    return copied_messages

async def delete_messages_from_user_chat(client, user_id, message_ids):
    """Deletes messages from a user's private chat."""
    try:
        await client.delete_messages(chat_id=user_id, message_ids=message_ids)
    except Exception as e:
        print(f"Error deleting messages from user chat: {e}")

def get_poster(query, bulk=False, id=False):
    """
    Simulates fetching movie/TV show information from IMDb.
    In a real bot, this would query an IMDb API or a scraper.
    """
    # This is a synchronous placeholder. If a real IMDb API is used, it might need to be async.
    if id:
        # Simulate fetching details for a specific IMDb ID
        return {"title": "Sample Movie", "year": "2023", "imdb_id": query, "poster": "https://via.placeholder.com/500x750?text=IMDb+Poster"}
    if bulk:
        # Simulate bulk search results
        return [
            {"title": "Movie A", "year": "2020", "imdb_id": "tt12345", "kind": "movie", "poster": "https://via.placeholder.com/500x750?text=Movie+A"},
            {"title": "TV Show B", "year": "2021", "imdb_id": "tt67890", "kind": "tv series", "poster": "https://via.placeholder.com/500x750?text=TV+Show+B"}
        ]
    return {"title": "Default Movie", "year": "2023", "imdb_id": "tt00000", "poster": "https://via.placeholder.com/500x750?text=Default+Poster"}

def find_most_similar_title(query, titles):
    """
    Finds the most similar title from a list using fuzzy matching.
    """
    from fuzzywuzzy import fuzz
    best_match = None
    highest_ratio = 0
    for title in titles:
        ratio = fuzz.ratio(query.lower(), title.lower())
        if ratio > highest_ratio:
            highest_ratio = ratio
            best_match = title
    return best_match

async def get_movie_info(query, tmdb_api_key):
    """
    Fetches movie/TV info from TMDB using the TMDB API.
    """
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {tmdb_api_key}"
    }
    try:
        url = f"https://api.themoviedb.org/3/search/multi?query={requests.utils.quote(query)}"
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        if data and data.get('results'):
            first_result = data['results'][0]
            media_type = first_result.get('media_type')
            if media_type == 'movie':
                return {
                    "title": first_result.get('title'),
                    "overview": first_result.get('overview'),
                    "poster_path": first_result.get('poster_path'),
                    "poster_url": f"https://image.tmdb.org/t/p/w500{first_result.get('poster_path')}" if first_result.get('poster_path') else None
                }
            elif media_type == 'tv':
                return {
                    "title": first_result.get('name'),
                    "overview": first_result.get('overview'),
                    "poster_path": first_result.get('poster_path'),
                    "poster_url": f"https://image.tmdb.org/t/p/w500{first_result.get('poster_path')}" if first_result.get('poster_path') else None
                }
    except Exception as e:
        print(f"Error fetching movie info from TMDB: {e}")
    return None

async def upload_image_to_imgbb(image_path):
    """
    Uploads an image to ImgBB. (Placeholder implementation)
    Requires IMGBB_API_KEY from info.py.
    """
    # In a real scenario, you'd read the image file and send it to ImgBB API.
    # For now, returns a dummy URL.
    print(f"Uploading {image_path} to ImgBB (stub)...")
    return "https://i.ibb.co/dummy/dummy.jpg"

async def get_poster_from_tmdb(poster_path, tmdb_api_key):
    """
    Constructs a full TMDB poster URL.
    """
    if poster_path:
        return f"https://image.tmdb.org/t/p/w500{poster_path}"
    return None

def get_size(bytes, suffix="B"):
    """
    Formats file size into a human-readable string (e.g., 1.23 MB).
    """
    factor = 1024
    for unit in ["", "K", "M", "G", "T", "P"]:
        if bytes < factor:
            return f"{bytes:.2f}{unit}{suffix}"
        bytes /= factor


def get_readable_time(seconds: int) -> str:
    """
    Converts seconds into a human-readable time string (e.g., 1d2h30m).
    """
    result = ''
    (days, remainder) = divmod(seconds, 86400)
    (hours, remainder) = divmod(remainder, 3600)
    (minutes, seconds) = divmod(remainder, 60)
    if days > 0:
        result += f'{days}d'
    if hours > 0:
        result += f'{hours}h'
    if minutes > 0:
        result += f'{minutes}m'
    if seconds > 0:
        result += f'{seconds}s'
    return result

def get_seconds(time_string):
    """
    Converts a time string (e.g., "1h30m") into total seconds.
    """
    if not time_string:
        return 0
    seconds = 0
    parts = re.findall(r'(\d+)([hms])', time_string)
    for value, unit in parts:
        value = int(value)
        if unit == 'h':
            seconds += value * 3600
        elif unit == 'm':
            seconds += value * 60
        elif unit == 's':
            seconds += value
    return seconds

def chunk_buttons(buttons, chunk_size=2):
    """
    Helper function to chunk buttons into lists of lists with a specified chunk size.
    """
    return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]
