# This is a sample config file, please fill in your details and rename to info.py

from pyrogram import Client
import re
from os import environ
from dotenv import load_dotenv
from Script import script
import time

load_dotenv("./dynamic.env", override=True)
id_pattern = re.compile(r'^.\d+$')
def is_enabled(value, default):
    if value.lower() in ["true", "yes", "1", "enable", "y"]: return True
    elif value.lower() in ["false", "no", "0", "disable", "n"]: return False
    else: return default

# Required API Credentials and Bot Settings
API_ID = int(environ.get('API_ID', '1234567')) # Your API ID from my.telegram.org
API_HASH = environ.get('API_HASH', 'your_api_hash') # Your API Hash from my.telegram.org
BOT_TOKEN = environ.get('BOT_TOKEN', 'your_bot_token') # Your Bot Token from @BotFather
BOT_USERNAME = environ.get('BOT_USERNAME', 'your_bot_username') # Your Bot Username

# Required Database and Channel Settings
DATABASE_URI = environ.get('DATABASE_URI', 'mongodb://localhost:27017/') # MongoDB URI
DATABASE_NAME = environ.get('DATABASE_NAME', 'your_database_name') # MongoDB Database Name
COLLECTION_NAME = environ.get('COLLECTION_NAME', 'Telegram_files') # MongoDB Collection Name for files
ADMINS = [int(admin) if id_pattern.search(admin) else admin for admin in environ.get('ADMINS', '12345').split()] # Your Telegram User ID(s) as admin
CHANNELS = [int(ch) if id_pattern.search(ch) else ch for ch in environ.get('CHANNELS', '-1001234567890').split()] # Channel ID(s) where files are indexed
AUTH_CHANNEL = int(environ.get('AUTH_CHANNEL', '')) if environ.get('AUTH_CHANNEL', '') and id_pattern.search(environ.get('AUTH_CHANNEL', '')) else None # Optional: Channel ID for force subscribe
REQ_CHANNEL_ONE = environ.get("REQ_CHANNEL_ONE", None) # Optional: First force subscribe channel ID
REQ_CHANNEL_ONE = (int(REQ_CHANNEL_ONE) if REQ_CHANNEL_ONE and id_pattern.search(REQ_CHANNEL_ONE) else False) if REQ_CHANNEL_ONE is not None else None
REQ_CHANNEL_TWO = environ.get("REQ_CHANNEL_TWO", None) # Optional: Second force subscribe channel ID
REQ_CHANNEL_TWO = (int(REQ_CHANNEL_TWO) if REQ_CHANNEL_TWO and id_pattern.search(REQ_CHANNEL_TWO) else False) if REQ_CHANNEL_TWO is not None else None

LOG_CHANNEL = int(environ.get('LOG_CHANNEL', '-1001234567890')) # Channel ID for bot logs
DB_CHANNEL = [int(ch) if id_pattern.search(ch) else ch for ch in environ.get('DB_CHANNEL', '-1001234567890').split()] # Channel ID(s) where bot stores files (if different from CHANNELS)
RAW_DB_CHANNEL = [int(ch) if id_pattern.search(ch) else ch for ch in environ.get('RAW_DB_CHANNEL', '1234567890').split()] # Raw channel IDs (without -100)
IMGBB_API_KEY = environ.get('IMGBB_API_KEY', '') # ImgBB API Key for image uploads (if used)
TMDB_API_KEY = environ.get('TMDB_API_KEY', '') # TMDB API Key for movie/series info (if used)

# Optional settings with defaults
SESSION = environ.get('SESSION', 'series') # Pyrogram session name
CACHE_TIME = int(environ.get('CACHE_TIME', 300)) # Cache time for inline queries
TMP_DOWNLOAD_DIRECTORY = environ.get("TMP_DOWNLOAD_DIRECTORY", "./DOWNLOADS/") # Temporary download directory
auth_users = [int(user) if id_pattern.search(user) else user for user in environ.get('AUTH_USERS', '').split()] # User IDs allowed to use inline search
AUTH_USERS = (auth_users + ADMINS) if auth_users else []

# Required Media settings with defaults
STICKER = is_enabled(environ.get('STICKER', 'False'), False) # Enable/disable sticker response
STICKER_ID = environ.get('STICKER_ID', "CAACAgUAAxkBAAJ0w2aZJMdpnEKbXtDVPJIvpL2XhIAhAAIrAAO8ljUq9-AkUFoHiMQeBA") # Sticker ID
PIC = is_enabled(environ.get('PIC', 'True'), True) # Enable/disable sending random pics
PICS = environ.get('PICS', "https://envs.sh/HqX.jpg https://envs.sh/Hqy.png https://envs.sh/H0D.jpg https://envs.sh/H0E.png https://envs.sh/H0Q.png").split() # List of image URLs

# Optional Bot messages and settings
START_TXT = environ.get('START_TXT', "I'm Maeve Wylie 🌸, a Group manager Bot Created for Series X, only authorised admins can access don't waste your time 😌")
NO_POSTER_FOUND_IMG = environ.get('NO_POSTER_FOUND_IMG', "https://telegra.ph/file/5e2d4418525832bc9a1b9").split() # Image for no poster found
SPELL_CHECK_IMAGE = environ.get('SPELL_CHECK_IMAGE', 'https://envs.sh/t8X.jpg?=ilovSTARLEY').split() # Image for spell check
JOIN_REQS_DB = environ.get("JOIN_REQS_DB", DATABASE_URI) # Database URI for join requests
CUSTOM_FILE_CAPTION = environ.get("CUSTOM_FILE_CAPTION", "{previouscaption}") # Custom caption for files
BATCH_FILE_CAPTION = environ.get("BATCH_FILE_CAPTION", '{previouscaption}') # Custom caption for batch files
AUTO_DELETE_TIME = int(environ.get('AUTO_DELETE_TIME', 600)) # Auto delete time for messages
AUTO_DELETE_MSG = environ.get('AUTO_DELETE_MSG', """<blockquote>⚠️ File Will Be Deleted In 10 Minutes.</blockquote>""") # Auto delete message
PROTECT_CONTENT = is_enabled(environ.get('PROTECT_CONTENT', "False"), False) # Enable/disable content protection
PUBLIC_FILE_STORE = is_enabled(environ.get('PUBLIC_FILE_STORE', "False"), False) # Enable/disable public file store
PORT = environ.get('PORT', "8080") # Port for web server

LONG_IMDB_DESCRIPTION = is_enabled(environ.get('LONG_IMDB_DESCRIPTION', "True"), True) # Enable/disable long IMDb description
MAX_LIST_ELM = int(environ.get('MAX_LIST_ELM', "8")) # Max list elements for search results
USE_CAPTION_FILTER = is_enabled(environ.get('USE_CAPTION_FILTER', "False"), False) # Enable/disable caption filter

# userbot = Client("my_userbot", api_id=API_ID2, api_hash=API_HASH2, session_string=SESSION_STRING)
# userbot.start()
