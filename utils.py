import logging
from pyrogram.errors import InputUserDeactivated, UserNotParticipant, FloodWait, UserIsBlocked, PeerIdInvalid
from info import ADMINS, AUTH_CHANNEL, LONG_IMDB_DESCRIPTION, MAX_LIST_ELM, DB_CHANNEL, RAW_DB_CHANNEL, AUTO_DELETE_TIME, AUTO_DELETE_MSG, NO_POSTER_FOUND_IMG
from imdb import Cinemagoer 
import asyncio
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto
from pyrogram import enums
from typing import Union, List
import re
import os
from datetime import datetime
from database.users_chats_db import db
from bs4 import BeautifulSoup
import requests
from pyrogram.errors.exceptions.bad_request_400 import UserNotParticipant, MediaEmpty


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BTN_URL_REGEX = re.compile(
  r"(\[([^\[]+?)\]$$(buttonurl|buttonalert):(?:/\{0,2\})(.+?)(:same)?$$)"
)
temp_requests = {}
AUTO_DEL_SUCCESS_MSG = """Your File Has Been Deleted To Avoid BOT Copyright.\nYou Can Request Again If You Want!🫵🏻"""
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
  USER_DATA = {} # New: To store admin UI state

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
      if channel_id in map(str, DB_CHANNEL):
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
      
      if extracted_channel_id in map(str, RAW_DB_CHANNEL): 
          return extracted_channel_id, msg_id
      else:
          return 0, 0

  else:
      return 0, 0


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

  await process.edit_text(AUTO_DEL_SUCCESS_MSG)

async def get_poster(query, bulk=False, id=False, file=None):
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
      "producer":list_to_str(movie.get("producer")),
      "composer":list_to_str(movie.get("composer")) ,
      "cinematographer":list_to_str(movie.get("cinematographer")),
      "music_team": list_to_str(movie.get("music department")),
      "distributors": list_to_str(movie.get("distributors")),
      'release_date': date,
      'year': movie.get('year'),
      'genres': list_to_str(movie.get("genres")),
      'poster': movie.get('full-size cover url'),
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
  for counter in range(len(text)): # Corrected: len(text) instead of (text)
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

def _get_user_state(user_id: int):
  return temp.USER_DATA.get(user_id, {})

def _set_user_state(user_id: int, state: dict):
  temp.USER_DATA[user_id] = state

def _clear_user_state(user_id: int):
  if user_id in temp.USER_DATA:
      del temp.USER_DATA[user_id]

async def _update_main_message(client, user_id: int):
  user_state = _get_user_state(user_id)
  if not user_state or not user_state.get('main_msg_id'):
      logger.warning(f"User {user_id}: No active main message ID found in state for update.")
      return

  series_data = user_state.get('series_data', {})
  current_step = user_state.get('current_step')
  main_msg_id = user_state['main_msg_id']

  text = ""
  poster_url = series_data.get('poster_url', NO_POSTER_FOUND_IMG[0])
  reply_markup = await _generate_admin_buttons(user_id)

  if current_step == 'SELECT_TMDB':
      text = "Please select a series from the results below:"
  elif current_step == 'EDIT_SERIES' or current_step == 'PUBLISH_CONFIRM':
      title = series_data.get('title', 'N/A')
      released_on = series_data.get('released_on', 'N/A')
      genre = series_data.get('genre', 'N/A')
      rating = series_data.get('rating', 'N/A')
      media_type = series_data.get('media_type', 'N/A').upper()
      tmdb_id = series_data.get('tmdb_id', 'N/A')
      
      text = (
          f"**Title:** `{title}`\n"
          f"**Released On:** `{released_on}`\n"
          f"**Genre:** `{genre}`\n"
          f"**Rating:** `{rating}`\n"
          f"**Media Type:** `{media_type}`\n"
          f"**TMDB ID:** `{tmdb_id}`\n\n"
      )
      if current_step == 'PUBLISH_CONFIRM':
          text += "Do you want to publish this series? NOTE: Once you publish this series, you can't edit it anymore. All the empty groups will be removed automatically."
      else:
          text += "Click below buttons to add Languages, Poster, or Publish."
  elif current_step == 'MANAGE_LANGUAGES':
      text = "Select any Language group to add new Season/Part group inside them. Or click '+' button to add new Language group."
  elif current_step == 'MANAGE_SEASONS':
      lang_key = user_state.get('current_language_key')
      lang_name = series_data.get('languages', {}).get(lang_key, {}).get('name', 'N/A')
      text = f"**Language:** `{lang_name}`\n\nSelect any Seasons group to add new Quality group into them. Or click '+' button to add new Seasons group."
  elif current_step == 'MANAGE_QUALITIES':
      lang_key = user_state.get('current_language_key')
      season_key = user_state.get('current_season_key')
      lang_name = series_data.get('languages', {}).get(lang_key, {}).get('name', 'N/A')
      season_name = series_data.get('languages', {}).get(lang_key, {}).get('seasons', {}).get(season_key, {}).get('name', 'N/A')
      text = f"**Language:** `{lang_name}`\n**Season:** `{season_name}`\n\nSelect any Quality group to add new files into them. Or click '+' button to add new Quality group."
  elif current_step == 'ADD_FILES_START':
      lang_key = user_state.get('current_language_key')
      season_key = user_state.get('current_season_key')
      quality_key = user_state.get('current_quality_key')
      lang_name = series_data.get('languages', {}).get(lang_key, {}).get('name', 'N/A')
      season_name = series_data.get('languages', {}).get(lang_key, {}).get('seasons', {}).get(season_key, {}).get('name', 'N/A')
      quality_name = series_data.get('languages', {}).get(lang_key, {}).get('seasons', {}).get(season_key, {}).get('qualities', {}).get(quality_key, {}).get('name', 'N/A')
      text = f"**Language:** `{lang_name}`\n**Season:** `{season_name}`\n**Quality:** `{quality_name}`\n\nForward me the first file (with tag) for this quality."

  try:
      if poster_url and poster_url != NO_POSTER_FOUND_IMG[0]:
          media = InputMediaPhoto(media=poster_url, caption=text, parse_mode=enums.ParseMode.MARKDOWN)
      else:
          media = InputMediaPhoto(media=NO_POSTER_FOUND_IMG[0], caption=text, parse_mode=enums.ParseMode.MARKDOWN)
      
      await client.edit_message_media(
          chat_id=user_id,
          message_id=main_msg_id,
          media=media,
          reply_markup=reply_markup
      )
      logger.info(f"User {user_id}: Main message updated successfully for step {current_step}.")
  except MediaEmpty:
      logger.warning(f"User {user_id}: MediaEmpty error for poster: {poster_url}. Using placeholder.")
      media = InputMediaPhoto(media=NO_POSTER_FOUND_IMG[0], caption=text, parse_mode=enums.ParseMode.MARKDOWN)
      await client.edit_message_media(
          chat_id=user_id,
          message_id=main_msg_id,
          media=media,
          reply_markup=reply_markup
      )
  except Exception as e:
      logger.error(f"User {user_id}: Error updating main message for step {current_step}: {e}")
      # Fallback to editing text if media update fails for any other reason
      await client.edit_message_text(
          chat_id=user_id,
          message_id=main_msg_id,
          text=text,
          reply_markup=reply_markup,
          parse_mode=enums.ParseMode.MARKDOWN
      )

async def _generate_admin_buttons(user_id: int):
  user_state = _get_user_state(user_id)
  current_step = user_state.get('current_step')
  series_data = user_state.get('series_data', {})
  buttons = []

  if current_step == 'SELECT_TMDB':
      # Buttons generated dynamically by the command handler
      pass
  elif current_step == 'EDIT_SERIES':
      buttons.append([
          InlineKeyboardButton("Language", callback_data=f"admin_series:{user_id}:manage_languages"),
          InlineKeyboardButton("Poster", callback_data=f"admin_series:{user_id}:add_poster")
      ])
      buttons.append([InlineKeyboardButton("Publish", callback_data=f"admin_series:{user_id}:publish_confirm")])
  elif current_step == 'MANAGE_LANGUAGES':
      languages = series_data.get('languages', {})
      for lang_key, lang_data in languages.items():
          buttons.append([InlineKeyboardButton(lang_data['name'], callback_data=f"admin_series:{user_id}:select_language:{lang_key}")])
      buttons.append([InlineKeyboardButton("+ Language", callback_data=f"admin_series:{user_id}:add_language")])
      buttons.append([InlineKeyboardButton("Back", callback_data=f"admin_series:{user_id}:edit_series")])
  elif current_step == 'MANAGE_SEASONS':
      lang_key = user_state.get('current_language_key')
      seasons = series_data.get('languages', {}).get(lang_key, {}).get('seasons', {})
      for season_key, season_data in seasons.items():
          buttons.append([InlineKeyboardButton(season_data['name'], callback_data=f"admin_series:{user_id}:select_season:{lang_key}:{season_key}")])
      buttons.append([InlineKeyboardButton("+ Season", callback_data=f"admin_series:{user_id}:add_season:{lang_key}")])
      buttons.append([InlineKeyboardButton(f"Delete '{series_data['languages'][lang_key]['name']}' Group", callback_data=f"admin_series:{user_id}:delete_lang:{lang_key}")])
      buttons.append([InlineKeyboardButton("Back", callback_data=f"admin_series:{user_id}:manage_languages")])
  elif current_step == 'MANAGE_QUALITIES':
      lang_key = user_state.get('current_language_key')
      season_key = user_state.get('current_season_key')
      qualities = series_data.get('languages', {}).get(lang_key, {}).get('seasons', {}).get(season_key, {}).get('qualities', {})
      for qual_key, qual_data in qualities.items():
          buttons.append([InlineKeyboardButton(qual_data['name'], callback_data=f"admin_series:{user_id}:select_quality:{lang_key}:{season_key}:{qual_key}")])
      buttons.append([InlineKeyboardButton("+ Quality", callback_data=f"admin_series:{user_id}:add_quality:{lang_key}:{season_key}")])
      buttons.append([InlineKeyboardButton(f"Delete '{series_data['languages'][lang_key]['seasons'][season_key]['name']}' Group", callback_data=f"admin_series:{user_id}:delete_seas:{lang_key}:{season_key}")])
      buttons.append([InlineKeyboardButton("Back", callback_data=f"admin_series:{user_id}:manage_seasons")])
  elif current_step == 'ADD_FILES_START' or current_step == 'ADD_FILES_END' or current_step == 'ADD_FILES_CODEC':
      lang_key = user_state.get('current_language_key')
      season_key = user_state.get('current_season_key')
      quality_key = user_state.get('current_quality_key')
      
      # If files are already linked, show a link to them
      file_link_key = series_data.get('languages', {}).get(lang_key, {}).get('seasons', {}).get(season_key, {}).get('qualities', {}).get(quality_key, {}).get('file_link_key')
      if file_link_key:
          # Assuming file_link_key is like "get_channelid_firstmsg_lastmsg"
          parts = file_link_key.split('_')
          if len(parts) == 4:
              channel_id = parts[1] # This is the raw channel ID
              first_msg_id = int(parts[2])
              # Construct a direct link to the first message
              link = f"https://t.me/c/{channel_id}/{first_msg_id}"
              buttons.append([InlineKeyboardButton("Go to Files", url=link)])
      
      buttons.append([InlineKeyboardButton(f"Delete '{series_data['languages'][lang_key]['seasons'][season_key]['qualities'][quality_key]['name']}' Group", callback_data=f"admin_series:{user_id}:delete_qual:{lang_key}:{season_key}:{quality_key}")])
      buttons.append([InlineKeyboardButton("Back", callback_data=f"admin_series:{user_id}:manage_qualities")])
  elif current_step == 'PUBLISH_CONFIRM':
      buttons.append([
          InlineKeyboardButton("Yes", callback_data=f"admin_series:{user_id}:publish_yes"),
          InlineKeyboardButton("No", callback_data=f"admin_series:{user_id}:publish_no")
      ])

  return InlineKeyboardMarkup(buttons)

def _generate_reply_keyboard(options: List[str], row_width: int = 3):
  keyboard_buttons = []
  for i in range(0, len(options), row_width):
      row = [KeyboardButton(text) for text in options[i:i+row_width]]
      keyboard_buttons.append(row)
  return ReplyKeyboardMarkup(keyboard_buttons, resize_keyboard=True, one_time_keyboard=True)

async def _save_series_to_db(series_data: dict):
  from database.crazy_db import add_series, delete_quality_files_from_episodes
  from pymongo import MongoClient
  from info import DATABASE_URI

  mongo_client = MongoClient(DATABASE_URI)
  db = mongo_client["file_database"]
  episodes_collection = db["episodes"]

  series_key = series_data['key']

  # Clean up empty languages, seasons, qualities
  cleaned_languages = {}
  for lang_key, lang_data in series_data.get('languages', {}).items():
      cleaned_seasons = {}
      for season_key, season_data in lang_data.get('seasons', {}).items():
          cleaned_qualities = {}
          for qual_key, qual_data in season_data.get('qualities', {}).items():
              if qual_data.get('file_link_key'): # Only keep qualities with linked files
                  cleaned_qualities[qual_key] = qual_data
              else:
                  # If quality has no files, ensure it's deleted from episodes collection if it existed
                  await delete_quality_files_from_episodes(qual_data.get('file_link_key'))
          if cleaned_qualities: # Only keep seasons with qualities
              season_data['qualities'] = cleaned_qualities
              cleaned_seasons[season_key] = season_data
          else:
              # Delete files associated with this season if it becomes empty
              for qual_key, qual_data in season_data.get('qualities', {}).items():
                  await delete_quality_files_from_episodes(qual_data.get('file_link_key'))

      if cleaned_seasons: # Only keep languages with seasons
          lang_data['seasons'] = cleaned_seasons
          cleaned_languages[lang_key] = lang_data
      else:
          # Delete files associated with this language if it becomes empty
          for season_key, season_data in lang_data.get('seasons', {}).items():
              for qual_key, qual_data in season_data.get('qualities', {}).items():
                  await delete_quality_files_from_episodes(qual_data.get('file_link_key'))

  series_data['languages'] = cleaned_languages

  # Save the cleaned series data to crazy_db
  await add_series(series_data)

  # Save file links to episodes collection
  for lang_key, lang_data in series_data.get('languages', {}).items():
      for season_key, season_data in lang_data.get('seasons', {}).items():
          for qual_key, qual_data in season_data.get('qualities', {}).items():
              file_link_key = qual_data.get('file_link_key')
              if file_link_key and qual_data.get('files_to_add'):
                  # This means files were just added in this session
                  episodes_collection.update_one(
                      {"file_link_key": file_link_key},
                      {"$set": {
                          "files": qual_data['files_to_add'],
                          "channel_id": qual_data.get('channel_id'),
                          "first_msg_id": qual_data.get('first_msg_id'),
                          "last_msg_id": qual_data.get('last_msg_id')
                      }},
                      upsert=True
                  )
              elif file_link_key:
                  # Ensure existing file_link_key is still valid in episodes collection
                  # (no need to re-save if files_to_add is empty, implies no change)
                  pass
              else:
                  logger.warning(f"Quality {qual_key} for {series_key} has no file_link_key during publish.")

  logger.info(f"Series '{series_data['title']}' published successfully.")
