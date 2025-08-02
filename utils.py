import logging
from pyrogram.errors import InputUserDeactivated, UserNotParticipant, FloodWait, UserIsBlocked, PeerIdInvalid, ChatWriteForbidden, MessageNotModified, ChannelPrivate, ChannelInvalid, MessageIdInvalid
from info import ADMINS, AUTH_CHANNEL, LONG_IMDB_DESCRIPTION, MAX_LIST_ELM, DB_CHANNEL, RAW_DB_CHANNEL, NO_POSTER_FOUND_IMG
from imdb import Cinemagoer 
import asyncio
from pyrogram.types import Message, InlineKeyboardButton
from pyrogram import enums
from typing import Union
import re
import os
from datetime import datetime
from typing import List
from database.users_chats_db import db
from bs4 import BeautifulSoup
import requests
from pyrogram.errors.exceptions.bad_request_400 import UserNotParticipant
import difflib # Import difflib for find_most_similar_title

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BTN_URL_REGEX = re.compile(
    r"(\[([^\[]+?)\]$$(buttonurl|buttonalert):(?:/{0,2})(.+?)(:same)?$$)"
)
temp_requests = {}
AUTO_DEL_SUCCESS_MSG = """Your File Has Been Deleted To Avoid BOT Copyright.\nYou Can Request Again If You Want!🫵🏻"""
AUTO_DELETE_TIME = 600
imdb = Cinemagoer() 

BANNED = {}
SMART_OPEN = '“'
SMART_CLOSE = '”'
START_CHAR = ('\'', '"', SMART_OPEN)
 
class temp(object):
    START_TIME = 0
    BANNED_USERS = []
    BANNED_CHATS = []
    ME = None
    CURRENT=int(os.environ.get("SKIP", 2))
    CANCEL = False
    MELCOW = {}
    FILES_IDS = {}
    U_NAME = None
    B_NAME = None
    LINK_ONE = None
    LINK_TWO = None
    SETTINGS = {}

def find_most_similar_title(query, search_results):
    """Finds the most similar title from IMDb search results."""
    titles = [movie.get('title', '').lower() for movie in search_results]
    matches = difflib.get_close_matches(query.lower(), titles, n=1, cutoff=0.6)
    if matches:
        for movie in search_results:
            if movie.get('title', '').lower() == matches[0]:
                return movie
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
        # Forwarded message from channel
        channel_id = str(message.forward_from_chat.id)
        raw_id = abs(int(channel_id.replace("-100", "")))
        if raw_id in RAW_DB_CHANNEL:
            return channel_id, message.forward_from_message_id
        return 0, 0

    elif message.text:
        # Direct link
        pattern = r"https://t.me/(?:c/)?(\d+)/(\d+)"
        matches = re.match(pattern, message.text)
        if not matches:
            return 0, 0

        extracted_raw_channel_id = int(matches.group(1))
        msg_id = int(matches.group(2))
        
        if extracted_raw_channel_id in RAW_DB_CHANNEL:
            pyrogram_channel_id = f"-100{extracted_raw_channel_id}"
            return pyrogram_channel_id, msg_id
        return 0, 0

    elif message.chat and str(message.chat.id).startswith("-100"):
        # Directly sent message from a channel (e.g., via bot API, not forwarded)
        channel_id = str(message.chat.id)
        raw_id = abs(int(channel_id.replace("-100", "")))
        if raw_id in RAW_DB_CHANNEL:
            return channel_id, message.id
        return 0, 0

    return 0, 0

async def get_messages_in_range(client, source_channel_id, start_msg_id, end_msg_id, target_channel_id):
    """
    Copies messages from a source channel to a target channel within a message ID range.
    Returns a list of the copied messages in the target channel.
    """
    copied_messages = []
    current_msg_id = start_msg_id
    
    logger.info(f"Attempting to copy messages from source_channel_id: {source_channel_id} (type: {type(source_channel_id)}) "
                f"from msg_id: {start_msg_id} to {end_msg_id} "
                f"to target_channel_id: {target_channel_id} (type: {type(target_channel_id)})")

    while current_msg_id <= end_msg_id:
        try:
            msg = await client.get_messages(chat_id=source_channel_id, message_ids=current_msg_id)
            if not msg:
                logger.warning(f"Message {current_msg_id} not found in source channel {source_channel_id}. Skipping.")
                current_msg_id += 1
                continue

            try:
                copied_msg = await msg.copy(chat_id=target_channel_id)
                copied_messages.append(copied_msg)
                logger.info(f"Successfully copied message {current_msg_id} to {target_channel_id} as {copied_msg.id}")
                await asyncio.sleep(0.5) # Small delay to avoid flood limits
            except ChatWriteForbidden:
                logger.error(f"Bot cannot write to target channel {target_channel_id}. Check permissions.")
                return [] # Critical error, stop copying
            except MessageNotModified:
                logger.warning(f"Message {current_msg_id} was not modified when copying to {target_channel_id}. Skipping.")
            except FloodWait as e:
                logger.warning(f"FloodWait: Sleeping for {e.value} seconds before retrying message {current_msg_id}")
                await asyncio.sleep(e.value)
                continue # Retry current message after delay
            except Exception as e:
                logger.error(f"Error copying message {current_msg_id} from {source_channel_id} to {target_channel_id}: {e}")
                # Decide whether to continue or break on error. For now, continue.
                pass
        except ChannelPrivate:
            logger.error(f"Source channel {source_channel_id} is private and bot is not a member or admin.")
            return []
        except ChannelInvalid:
            logger.error(f"Source channel ID {source_channel_id} is invalid.")
            return []
        except FloodWait as e:
            logger.warning(f"FloodWait on get_messages: Sleeping for {e.value} seconds before retrying message {current_msg_id}")
            await asyncio.sleep(e.value)
            continue # Retry current message after delay
        except Exception as e:
            logger.error(f"Error getting message {current_msg_id} from {source_channel_id}: {e}")
            # Decide whether to continue or break on error. For now, continue.
            pass
        current_msg_id += 1
    return copied_messages

async def get_messages(client, channel_id, message_ids):
    messages = []
    total_messages = 0
    while total_messages < len(message_ids):
        tem_ids = message_ids[total_messages:total_messages + 200]
        try:
            msgs = await client.get_messages(chat_id=channel_id, message_ids=tem_ids)
        except FloodWait as e:
            print(f"FloodWait: Sleeping for {e.x} seconds")
            await asyncio.sleep(e.x)
            msgs = await client.get_messages(chat_id=channel_id, message_ids=tem_ids)
        except Exception as e:
            print(f"An error occurred: {e}")
            break  # Exit on unexpected exceptions
        else:
            total_messages += len(tem_ids)
            messages.extend(msgs)
    return messages

async def delete_file(messages, client, process):
    await asyncio.sleep(AUTO_DELETE_TIME)
    for msg in messages:
        try:
            await client.delete_messages(chat_id=msg.chat.id, message_ids=[msg.id])
        except Exception as e:
            await asyncio.sleep(e.x)
            print(f"The attempt to delete the media {msg.id} was unsuccessful: {e}")

async def delete_messages_from_user_chat(client, user_id, message_ids):
    """Deletes a list of messages from a user's private chat."""
    try:
        await client.delete_messages(chat_id=user_id, message_ids=message_ids)
        logger.info(f"Successfully deleted messages {message_ids} from user {user_id} chat.")
    except Exception as e:
        logger.error(f"Failed to delete messages {message_ids} from user {user_id} chat: {e}")


def get_poster(query, bulk=False, id=False, file=None):
    if not id:
        query = (query.strip()).lower()
        title = query
        year = re.findall(r'[1-2]\d{3}$', query, re.IGNORECASE)
        if year:
            year = list_to_str(year[:1])
            title = (query.replace(year, "")).strip()
        elif file is not None:
            year = re.findall(r'[1-2]\d{3}', file, re.IGNORECASE)
            if year:
                year = list_to_str(year[:1]) 
        else:
            year = None
        movieid = imdb.search_movie(title.lower(), results=10)
        if not movieid:
            return None
        if year:
            filtered=list(filter(lambda k: str(k.get('year')) == str(year), movieid))
            if not filtered:
                filtered = movieid
        else:
            filtered = movieid
        movieid=list(filter(lambda k: k.get('kind') in ['movie', 'tv series'], filtered))
        if not movieid:
            movieid = filtered
        if bulk:
            return movieid
        movieid = movieid[0].movieID
    else:
        movieid = query
    movie = imdb.get_movie(movieid)
    if movie.get("original air date"):
        date = movie["original air date"]
    elif movie.get("year"):
        date = movie.get("year")
    else:
        date = "N/A"
    plot = ""
    if not LONG_IMDB_DESCRIPTION:
        plot = movie.get('plot')
        if plot and (plot) > 0:
            plot = plot[0]
    else:
        plot = movie.get('plot outline')
    if plot and len(plot) > 800:
        plot = plot[0:800] + "..."

    return {
        'title': movie.get('title'),
        'votes': movie.get('votes'),
        "aka": list_to_str(movie.get("akas")),
        "seasons": movie.get("number of seasons"),
        "box_office": movie.get('box office'),
        'localized_title': movie.get('localized title'),
        'kind': movie.get("kind"),
        "imdb_id": f"tt{movie.get('imdbID')}",
        "cast": list_to_str(movie.get("cast")),
        "runtime": list_to_str(movie.get("runtimes")),
        "countries": list_to_str(movie.get("countries")),
        "certificates": list_to_str(movie.get("certificates")),
        "languages": list_to_str(movie.get("languages")),
        "director": list_to_str(movie.get("director")),
        "writer":list_to_str(movie.get("writer")),
        "producer":list_to_str(movie.get("producer")) ,
        "composer":list_to_str(movie.get("composer")) ,
        "cinematographer":list_to_str(movie.get("cinematographer")),
        "music_team": list_to_str(movie.get("music department")),
        "distributors": list_to_str(movie.get("distributors")),
        'release_date': date,
        'year': movie.get('year'),
        'genres': list_to_str(movie.get("genres")),
        'poster': movie.get('full-size cover url') or NO_POSTER_FOUND_IMG, # Ensure a fallback poster
        'plot': plot,
        'rating': str(movie.get("rating")),
        'url':f'https://www.imdb.com/title/tt{movieid}'
    }

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
            # don't want to make a request -_-
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

    # 1 to avoid starting quote, and counter is exclusive so avoids ending
    key = remove_escapes(text[1:counter].strip())
    # index will be in range, or `else` would have been executed and returned
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
        # Check if btnurl is escaped
        n_escapes = 0
        to_check = match.start(1) - 1
        while to_check > 0 and text[to_check] == "\\":
            n_escapes += 1
            to_check -= 1

        # if even, not escaped -> create button
        if n_escapes % 2 == 0:
            note_data += text[prev:match.start(1)]
            prev = match.end(1)
            if match.group(3) == "buttonalert":
                # create a thruple with button label, url, and newline status
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
        # Check if btnurl is escaped
        n_escapes = 0
        to_check = match.start(1) - 1
        while to_check > 0 and text[to_check] == "\\":
            n_escapes += 1
            to_check -= 1

        # if even, not escaped -> create button
        if n_escapes % 2 == 0:
            note_data += text[prev:match.start(1)]
            prev = match.end(1)
            if match.group(3) == "buttonalert":
                # create a thruple with button label, url, and newline status
                if bool(match.group(5)) and buttons:
                    buttons[-1].append(InlineKeyboardButton(
                        text=match.group(2),
                        callback_data=f"alertmessage:{i}:{keyword}"
                    ))
                else:
                    buttons.append([InlineKeyboardButton(
                        text=match.group(2),
       
# Temporary storage for admin session data
class TempData:
  def __init__(self):
      self.ADMIN = {}
      self.U_NAME = None # Bot username, set during bot startup

temp = TempData()

async def get_message_id(client, message):
  """
  Extracts channel ID and message ID from a forwarded message or a post link.
  Returns (channel_id, message_id) or (None, None) if invalid.
  """
  if message.forward_from_chat and message.forward_from_chat.type == enums.ChatType.CHANNEL:
      return message.forward_from_chat.id, message.forward_from_message_id
  elif message.text and "t.me/c/" in message.text:
      match = re.search(r"t\.me/c/(\d+)/(\d+)", message.text)
      if match:
          channel_id_raw = int(match.group(1))
          message_id = int(match.group(2))
          # Convert raw channel ID to Pyrogram format (-100 prefix)
          channel_id = int(f"-100{channel_id_raw}")
          return channel_id, message_id
  return None, None


def split_list(l, n):
    for i in range(0, len(l), n):
        yield l[i:i + n]  

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

async def get_messages_in_range(client: Client, source_channel_id: int, start_msg_id: int, end_msg_id: int, target_channel_id: int):
  """
  Copies messages from a source channel within a given range to a target channel.
  Returns a list of copied messages.
  """
  copied_messages = []
  for msg_id in range(start_msg_id, end_msg_id + 1):
      try:
          # Get the message from the source channel
          msg = await client.get_messages(source_channel_id, msg_id)
          if msg:
              # Copy the message to the target channel
              copied_msg = await msg.copy(target_channel_id)
              copied_messages.append(copied_msg)
              await asyncio.sleep(0.5) # Small delay to avoid flood waits
      except FloodWait as e:
          logger.warning(f"FloodWait: Sleeping for {e.value} seconds.")
          await asyncio.sleep(e.value)
          # Retry the current message after waiting
          try:
              msg = await client.get_messages(source_channel_id, msg_id)
              if msg:
                  copied_msg = await msg.copy(target_channel_id)
                  copied_messages.append(copied_msg)
          except Exception as retry_e:
              logger.error(f"Failed to copy message {msg_id} after FloodWait: {retry_e}")
      except Exception as e:
          logger.error(f"Error copying message {msg_id} from {source_channel_id}: {e}")
  return copied_messages

async def delete_messages_from_user_chat(client: Client, user_id: int, message_ids: list):
  """Deletes a list of messages from the user's private chat."""
  if not message_ids:
      return
  try:
      await client.delete_messages(chat_id=user_id, message_ids=message_ids)
  except Exception as e:
      logger.warning(f"Could not delete messages {message_ids} from user {user_id} chat: {e}")

def get_poster(query, bulk=False, id=False):
  """
  Fetches movie/TV show information from IMDb.
  - query: search term
  - bulk: if True, returns multiple search results for selection
  - id: if True, query is an IMDb ID
  """
  ia = Cinemagoer()
  try:
      if id:
          # Fetch by IMDb ID
          movie = ia.get_movie(query)
          if movie:
              return {
                  'title': movie.get('title'),
                  'year': movie.get('year'),
                  'genres': ', '.join(movie.get('genres', [])),
                  'rating': movie.get('rating'),
                  'poster': movie.get('cover url'),
                  'imdb_id': movie.movieID,
                  'kind': movie.get('kind')
              }
          return None
      else:
          # Search by query
          search_results = ia.search_movie(query)
          if bulk:
              results = []
              for movie in search_results[:10]: # Limit to 10 results
                  results.append({
                      'title': movie.get('title'),
                      'year': movie.get('year'),
                      'imdb_id': movie.movieID,
                      'kind': movie.get('kind'),
                      'poster': movie.get('cover url')
                  })
              return results
          elif search_results:
              movie = search_results[0]
              return {
                  'title': movie.get('title'),
                  'year': movie.get('year'),
                  'genres': ', '.join(movie.get('genres', [])),
                  'rating': movie.get('rating'),
                  'poster': movie.get('cover url'),
                  'imdb_id': movie.movieID,
                  'kind': movie.get('kind')
              }
          return None
  except Exception as e:
      logger.error(f"IMDb API error: {e}")
      return None

def find_most_similar_title(query, titles):
  """Finds the most similar title from a list using fuzzy matching."""
  if not titles:
      return None
  
  best_match = None
  highest_ratio = -1
  
  for title in titles:
      ratio = fuzz.ratio(query.lower(), title.lower())
      if ratio > highest_ratio:
          highest_ratio = ratio
          best_match = title
          
  # Consider a match only if it's above a certain threshold (e.g., 70%)
  if highest_ratio >= 70:
      return best_match
  return None

def chunk_buttons(buttons, chunk_size=2):
  """Chunks a list of buttons into sublists of a given size."""
  return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]
