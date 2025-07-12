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
API_ID = 19680279
API_HASH = "a32f974ade51b2dc74e8db4bb049ad01"
BOT_TOKEN = "5883096902:AAF-tI_T-F_zVI4oIANJPuZxDsvskqmAw6A"
BOT_USERNAME = "MC_MovieBetaBot"
#API_ID2 = environ['API_ID2']
#API_HASH2 = environ['API_HASH2']
#SESSION_STRING = environ['SESSION_STRING']

# Required Database and Channel Settings
DATABASE_URI="mongodb+srv://user:pass@cluster0.chedxq6.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
DATABASE_URL="mongodb+srv://user:pass@cluster0.chedxq6.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
DATABASE_NAME = "cluster0"
COLLECTION_NAME = "thernello_unda"
ADMINS = [int(admin) if id_pattern.search(admin) else admin for admin in environ.get('ADMINS', '1129673243 5394954571 7188908429').split()]
CHANNELS = [int(ch) if id_pattern.search(ch) else ch for ch in environ.get('CHANNELS', '-1001306691782').split()]
auth_channel = environ.get('AUTH_CHANNEL', '')
AUTH_CHANNEL = int(auth_channel) if auth_channel and id_pattern.search(auth_channel) else None
# Your request to join channel Ids
REQ_CHANNEL_ONE =environ.get("REQ_CHANNEL_ONE", None)
REQ_CHANNEL_ONE = (int(REQ_CHANNEL_ONE) if REQ_CHANNEL_ONE and id_pattern.search(REQ_CHANNEL_ONE) else False) if REQ_CHANNEL_ONE is not None else None
REQ_CHANNEL_TWO =environ.get("REQ_CHANNEL_TWO", None)
REQ_CHANNEL_TWO = (int(REQ_CHANNEL_TWO) if REQ_CHANNEL_TWO and id_pattern.search(REQ_CHANNEL_TWO) else False) if REQ_CHANNEL_TWO is not None else None

LOG_CHANNEL = "-1002480551308"
DB_CHANNEL = [-1002480551308, -1001306691782, -1002193376815]
RAW_DB_CHANNEL = [2480551308, 1306691782, 2193376815]
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

# Optional Bot messages and settings
START_TXT = environ.get('START_TXT', "𝗅'm Mᴀᴇᴠᴇ Wʏʟɪᴇ 🌸, ᴀ Gʀᴏᴜᴘ ᴍᴀɴᴀɢᴇʀ Bᴏᴛ Cʀᴇᴀᴛᴇᴅ ғᴏʀ Sᴇʀɪᴇs X, ᴏɴʟʏ ᴀᴜᴛʜᴏʀɪsᴇᴅ ᴀᴅᴍɪɴs ᴄᴀɴ ᴀᴄᴄᴇss ᴅᴏɴ'ᴛ ᴡᴀsᴛᴇ ʏᴏᴜʀ ᴛɪᴍᴇ 😌")
NO_POSTER_FOUND_IMG = environ.get('NO_POSTER_FOUND_IMG', "https://telegra.ph/file/5e2d4418525832bc9a1b9").split()
SPELL_CHECK_IMAGE = environ.get('SPELL_CHECK_IMAGE', 'https://envs.sh/t8X.jpg?=ilovSTARLEY').split()
JOIN_REQS_DB = environ.get("JOIN_REQS_DB", DATABASE_URI)
CUSTOM_FILE_CAPTION = environ.get("CUSTOM_FILE_CAPTION", "{previouscaption}")
BATCH_FILE_CAPTION = environ.get("BATCH_FILE_CAPTION", '{previouscaption}')
AUTO_DELETE_TIME = int(environ.get('AUTO_DELETE_TIME', 600))
AUTO_DELETE_MSG = environ.get('AUTO_DELETE_MSG', """<blockquote>⚠️ 𝙁𝙞𝙡𝙚 𝙒𝙞𝙡𝙡 𝘽𝙚 𝘿𝙚𝙡𝙚𝙩𝙚𝙙 𝙄𝙣 10 𝙈𝙞𝙣𝙪𝙩𝙚𝙨.</blockquote>""")
PROTECT_CONTENT = is_enabled(environ.get('PROTECT_CONTENT', "False"), False)
PUBLIC_FILE_STORE = is_enabled(environ.get('PUBLIC_FILE_STORE', "False"), False)
PORT = environ.get('PORT', "8080")

LONG_IMDB_DESCRIPTION = "True"
MAX_LIST_ELM = "8"
USE_CAPTION_FILTER = "False"
#userbot = Client("my_userbot", api_id=API_ID2, api_hash=API_HASH2, session_string=SESSION_STRING)
#userbot.start()
