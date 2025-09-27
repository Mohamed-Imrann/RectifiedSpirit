from pyrogram import Client
import re
import os
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
API_ID = '20400973' #bots
API_HASH = '047838cb76d54bc445e155a7cab44664'
BOT_TOKEN = '7448922857:AAEiLcjbuhP_XNSl0KOiCj70OpBJWFWKbCA'
BOT_USERNAME = "Spidy_Series_bot"

# Required Database and Channel Settings
DATABASE_URI="mongodb+srv://sp:sp@cluster0.eh3zdcl.mongodb.net/?retryWrites=true&w=majority"
DATABASE_URL="mongodb+srv://sp:sp@cluster0.eh3zdcl.mongodb.net/?retryWrites=true&w=majority"
DATABASE_NAME = "series_collection"
COLLECTION_NAME = "series"
ADMINS = [int(admin) if id_pattern.search(admin) else admin for admin in environ.get('ADMINS', '7144888498 7188908429 7874364809').split()]
CHANNELS = [int(ch) if id_pattern.search(ch) else ch for ch in environ.get('CHANNELS', '-1001306691782').split()]
auth_channel = environ.get('AUTH_CHANNEL', '')
AUTH_CHANNEL = int(auth_channel) if auth_channel and id_pattern.search(auth_channel) else None
# Your request to join channel Ids
REQ_CHANNEL_ONE =environ.get("REQ_CHANNEL_ONE", '-1003456')
REQ_CHANNEL_ONE = (int(REQ_CHANNEL_ONE) if REQ_CHANNEL_ONE and id_pattern.search(REQ_CHANNEL_ONE) else False) if REQ_CHANNEL_ONE is not None else None
REQ_CHANNEL_TWO =environ.get("REQ_CHANNEL_TWO", '-1004567')
REQ_CHANNEL_TWO = (int(REQ_CHANNEL_TWO) if REQ_CHANNEL_TWO and id_pattern.search(REQ_CHANNEL_TWO) else False) if REQ_CHANNEL_TWO is not None else None

LOG_CHANNEL = "-1002361556192"
DB_CHANNEL = [-1002400599577]
RAW_DB_CHANNEL = 2400599577]
IMGBB_API_KEY = "e74d34d56644c5a9543019e408dbd891"
TMDB_API_KEY = "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiIwZjY0ZTY1MDRhYTZkY2JkNmQxMWMzMjRiZTU3MGFmYSIsIm5iZiI6MTc1MTk3MDQyMy4zNTAwMDAxLCJzdWIiOiI2ODZjZjI3N2ZmMzFhNDFhNDhlN2ZlNTMiLCJzY29wZXMiOlsiYXBpX3JlYWQiXSwidmVyc2lvbiI6MX0.dI7SXasXd9LfTedzTfZAW05gQPcOD7_TpEMHKCGNdvU"
# Optional settings with defaults
SESSION = environ.get('SESSION', 'series')
CACHE_TIME = int(environ.get('CACHE_TIME', 300))
TMP_DOWNLOAD_DIRECTORY = environ.get("TMP_DOWNLOAD_DIRECTORY", "./DOWNLOADS/")
auth_users = [int(user) if id_pattern.search(user) else user for user in environ.get('AUTH_USERS', '').split()]
AUTH_USERS = (auth_users + ADMINS) if auth_users else []

# Required Media settings with defaults
STICKER = environ.get('STICKER', 'False')
STICKER_ID = environ.get('STICKER_ID', "CAACAgUAAxkBAAJ0w2aZJMdpnEKbXtDVPJIvpL2XhIAhAAIrAAO8ljUq9-AkUFoHiMQeBA")
PIC = environ.get('PIC', 'True')
PICS = environ.get('PICS', "https://envs.sh/HqX.jpg https://envs.sh/Hqy.png https://envs.sh/H0D.jpg https://envs.sh/H0E.png https://envs.sh/H0Q.png").split()

IMDB = is_enabled(environ.get('IMDB', "True"), True) # Enable/disable IMDB features
IMDB_POSTER = is_enabled(environ.get('IMDB_POSTER', "True"), True) # Enable/disable IMDB poster fetching
PM_TXT = environ.get('PM_TXT', "Hello! Please send me a series title or key to get details.")
SPELL_CHECK_TXT = environ.get('SPELL_CHECK_TXT', "Did you mean something else? Please check your spelling or try a different title.")
CHANNELS_TXT = environ.get('CHANNELS_TXT', "Join our channels for more content!")

# Optional Bot messages and settings
WELCOME_MESSAGE = os.environ.get("WELCOME_MESSAGE", "Hello {mention}! I am an advanced auto-filter bot. Send me the name of a movie or series to get started.")

# Optional: About message.
ABOUT_MESSAGE = os.environ.get("ABOUT_MESSAGE", "I am an advanced auto-filter bot created by @cold_onez.")

# Optional: Start message for deep links.
START_DEEPLINK_MESSAGE = os.environ.get("START_DEEPLINK_MESSAGE", "Click the button below to get your file.")

# Optional: Support group link.
SUPPORT_GROUP_LINK = os.environ.get("SUPPORT_GROUP_LINK", "https://t.me/Sflixbots")

# Optional: Updates channel link.
UPDATES_CHANNEL_LINK = os.environ.get("UPDATES_CHANNEL_LINK", "https://t.me/SflixBots")

# Optional: Bot owner link.
BOT_OWNER_LINK = os.environ.get("BOT_OWNER_LINK", "t.me/Sflixbots")
START_TXT = environ.get('START_TXT', "𝗅'm SflixSeriesBot, ᴀ Gʀᴏᴜᴘ ᴍᴀɴᴀɢᴇʀ Bᴏᴛ Cʀᴇᴀᴛᴇᴅ ғᴏʀ Sflicb, ᴏɴʟʏ ᴀᴜᴛʜᴏʀɪsᴇᴅ ᴀᴅᴍɪɴs ᴄᴀɴ ᴀᴄᴄᴇss ᴅᴏɴ'ᴛ ᴡᴀsᴛᴇ ʏᴏᴜʀ ᴛɪᴍᴇ 😌")
NO_POSTER_FOUND_IMG = environ.get('NO_POSTER_FOUND_IMG', "https://envs.sh/EMw.jpg").split()
SPELL_CHECK_IMAGE = environ.get('SPELL_CHECK_IMAGE', 'https://envs.sh/EMw.jpg').split()
JOIN_REQS_DB = environ.get("JOIN_REQS_DB", DATABASE_URI)
CUSTOM_FILE_CAPTION = environ.get("CUSTOM_FILE_CAPTION", "{previouscaption}")
BATCH_FILE_CAPTION = environ.get("BATCH_FILE_CAPTION", '{previouscaption}')
AUTO_DELETE_TIME = int(environ.get('AUTO_DELETE_TIME', 600))
AUTO_DELETE_MSG = environ.get('AUTO_DELETE_MSG', """<blockquote>⚠️ 𝙁𝙞𝙡𝙚 𝙒𝙞𝙡𝙡 𝘽𝙚 𝘿𝙚𝙡𝙚𝙩𝙚𝙙 𝙄𝙣 10 𝙈𝙞𝙣𝙪𝙩𝙚𝙨.</blockquote>""")
PROTECT_CONTENT = is_enabled(environ.get('PROTECT_CONTENT', "False"), False)
PUBLIC_FILE_STORE = is_enabled(environ.get('PUBLIC_FILE_STORE', "False"), False)
PORT = environ.get('PORT', "8080")

ADMIN_CHANNELS_COLLECTION = "adminchannel"

LONG_IMDB_DESCRIPTION = "True"
MAX_LIST_ELM = "8"
USE_CAPTION_FILTER = "False"
#userbot = Client("my_userbot", api_id=API_ID2, api_hash=API_HASH2, session_string=SESSION_STRING)
#userbot.start()
