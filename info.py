from pyrogram import Client
import re
from os import environ
from dotenv import load_dotenv
from Script import script
import time

# load_dotenv("./config.env")
load_dotenv("./dynamic.env", override=True)

id_pattern = re.compile(r'^.\d+$')
def is_enabled(value, default):
    if value.lower() in ["true", "yes", "1", "enable", "y"]:
        return True
    elif value.lower() in ["false", "no", "0", "disable", "n"]:
        return False
    else:
        return default

# Required API Credentials and Bot Settings
API_ID = environ['API_ID']
API_HASH = environ['API_HASH']
BOT_TOKEN = environ['BOT_TOKEN']
BOT_USERNAME = environ['BOT_USERNAME']
#API_ID2 = environ['API_ID2']
#API_HASH2 = environ['API_HASH2']
#SESSION_STRING = environ['SESSION_STRING']

# Required Database and Channel Settings
DATABASE_URI = environ['DATABASE_URI']
DATABASE_NAME = environ['DATABASE_NAME']
COLLECTION_NAME = environ['COLLECTION_NAME']
ADMINS = [int(admin) if id_pattern.search(admin) else admin for admin in environ['ADMINS'].split()]
CHANNELS = [int(ch) if id_pattern.search(ch) else ch for ch in environ['CHANNELS'].split()]
AUTH_CHANNEL = int(environ['AUTH_CHANNEL'])
REQ_CHANNEL = int(environ['REQ_CHANNEL'])
LOG_CHANNEL = environ['LOG_CHANNEL']
DB_CHANNEL = [int(ch) for ch in environ['DB_CHANNEL'].split(',')]
RAW_DB_CHANNEL = [int(ch) for ch in environ['RAW_DB_CHANNEL'].split(',')]
IMGBB_API_KEY = environ['IMGBB_API_KEY']

# Optional settings with defaults
SESSION = environ.get('SESSION', 'series')
CACHE_TIME = int(environ.get('CACHE_TIME', 300))
TMP_DOWNLOAD_DIRECTORY = environ.get("TMP_DOWNLOAD_DIRECTORY", "./DOWNLOADS/")
auth_users = [int(user) if id_pattern.search(user) else user for user in environ.get('AUTH_USERS', '').split()]
AUTH_USERS = (auth_users + ADMINS) if auth_users else []

# Required Media settings with defaults
STICKER = environ.get('STICKER', 'True')
STICKER_ID = environ.get('STICKER_ID', "CAACAgUAAxkBAAJ0w2aZJMdpnEKbXtDVPJIvpL2XhIAhAAIrAAO8ljUq9-AkUFoHiMQeBA")
PIC = environ.get('PIC', 'False')
PICS = environ.get('PICS', "https://envs.sh/PSI.jpg").split()

# Optional Bot messages and settings
START_TXT = environ.get('START_TXT', "Bot Started..! And its Up and Running..!")
NO_POSTER_FOUND_IMG = environ.get('NO_POSTER_FOUND_IMG', "https://envs.sh/kJK.jpg").split()
SPELL_CHECK_IMAGE = environ.get('SPELL_CHECK_IMAGE', 'https://envs.sh/kJj.jpg').split()
JOIN_REQS_DB = environ.get("JOIN_REQS_DB", DATABASE_URI)
CUSTOM_FILE_CAPTION = environ.get("CUSTOM_FILE_CAPTION", "{previouscaption}")
BATCH_FILE_CAPTION = environ.get("BATCH_FILE_CAPTION", '{previouscaption}')
AUTO_DELETE_TIME = int(environ.get('AUTO_DELETE_TIME', 0))
AUTO_DELETE_MSG = environ.get('AUTO_DELETE_MSG', """<blockquote>⚠️ 𝙁𝙞𝙡𝙚 𝙒𝙞𝙡𝙡 𝘽𝙚 𝘿𝙚𝙡𝙚𝙩𝙚𝙙 𝙄𝙣 10 𝙈𝙞𝙣𝙪𝙩𝙚𝙨.</blockquote>""")
PROTECT_CONTENT = is_enabled(environ.get('PROTECT_CONTENT', "False"), False)
PUBLIC_FILE_STORE = is_enabled(environ.get('PUBLIC_FILE_STORE', "False"), False)
PORT = environ.get('PORT', "8080")

LONG_IMDB_DESCRIPTION = "True"
MAX_LIST_ELM = "8"
USE_CAPTION_FILTER = "False"
#userbot = Client("my_userbot", api_id=API_ID2, api_hash=API_HASH2, session_string=SESSION_STRING)
#userbot.start()
