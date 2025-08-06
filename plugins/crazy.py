import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, ReplyKeyboardRemove
from imdb import Cinemagoer 
import difflib
import asyncio
import re
import shutil
import os
from telegraph import upload_file
from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, IMGBB_API_KEY, TMDB_API_KEY, LOG_CHANNEL, DB_CHANNEL, RAW_DB_CHANNEL
from database.users_chats_db import db
from database.crazy_db import (
  add_series, delete_series_and_links, delete_all_series_and_links,
  get_series_name, get_series, add_poster_to_db, get_links_for_quality, delete_quality_files_from_episodes
)
from plugins.get_file_id import get_file_id
from utils import _get_user_state, _set_user_state, _clear_user_state, _update_main_message, _generate_reply_keyboard, _save_series_to_db, get_messages, temp
import base64
import hashlib
import requests
import uuid
import logging
import json # Added for json.dumps in view_user_state

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

imdb = Cinemagoer()

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

async def get_tmdb_info(query, bulk=False, id=False, media_type='tv'):
  headers = {
      "accept": "application/json",
      "Authorization": f"Bearer {TMDB_API_KEY}"
  }

  try:
      if not id:
          search_results_tv = []
          search_results_movie = []
          
          url_tv = f"{TMDB_BASE_URL}/search/tv"
          response_tv = requests.get(url_tv, headers=headers, params={"query": query})
          if response_tv.status_code == 200:
              data_tv = response_tv.json()
              for item in data_tv.get('results', [])[:5]:
                  if item.get('name'):
                      search_results_tv.append({
                          'title': item.get('name'),
                          'year': item.get('first_air_date', '').split('-')[0] if item.get('first_air_date') else 'N/A',
                          'tmdb_id': item.get('id'),
                          'media_type': 'tv'
                      })
          
          url_movie = f"{TMDB_BASE_URL}/search/movie"
          response_movie = requests.get(url_movie, headers=headers, params={"query": query})
          if response_movie.status_code == 200:
              data_movie = response_movie.json()
              for item in data_movie.get('results', [])[:5]:
                  if item.get('title'):
                      search_results_movie.append({
                          'title': item.get('title'),
                          'year': item.get('release_date', '').split('-')[0] if item.get('release_date') else 'N/A',
                          'tmdb_id': item.get('id'),
                          'media_type': 'movie'
                      })
          
          all_results = search_results_tv + search_results_movie
          return all_results[:10] if bulk else (all_results[0] if all_results else None)
      else:
          url = f"{TMDB_BASE_URL}/{media_type}/{query}"
          response = requests.get(url, headers=headers)
          if response.status_code == 200:
              data = response.json()
              genres = [g['name'] for g in data.get('genres', [])][:3]
              poster_path = data.get('poster_path')
              poster_url = f"{TMDB_IMAGE_BASE_URL}{poster_path}" if poster_path else None
              
              if media_type == 'tv':
                  title = data.get('name', 'N/A')
                  year = data.get('first_air_date', '').split('-')[0] if data.get('first_air_date') else 'N/A'
                  # For TV series, get end year if available
                  if data.get('last_air_date') and data.get('first_air_date') != data.get('last_air_date'):
                      year += f" - {data['last_air_date'].split('-')[0]}"
              else:
                  title = data.get('title', 'N/A')
                  year = data.get('release_date', '').split('-')[0] if data.get('release_date') else 'N/A'
              
              return {
                  'title': title,
                  'year': year,
                  'genres': ', '.join(genres) if genres else 'N/A',
                  'rating': data.get('vote_average', 'N/A'),
                  'poster': poster_url,
                  'tmdb_id': data.get('id'),
                  'media_type': media_type,
                  'url': f'https://www.themoviedb.org/{media_type}/{data.get("id")}'
              }
          return None

  except Exception as e:
      logger.error(f"TMDB Error: {e}")
      return None

@Client.on_message(filters.command('newseries') & filters.user(ADMINS))
async def new_series_command(client, message: Message):
  user_id = message.from_user.id
  
  if len(message.command) < 2:
      await message.reply_text("Usage: `/newseries <series_title>`")
      return

  series_title_query = message.text.split(None, 1)[1]
  
  # Clear any previous state for this user
  _clear_user_state(user_id)

  initial_msg = await message.reply_text("Searching TMDB...")
  
  tmdb_results = await get_tmdb_info(series_title_query, bulk=True)

  if not tmdb_results:
      await initial_msg.edit_text("No results found on TMDB for the provided series name.")
      return

  buttons = []
  for item in tmdb_results:
      item_title = item.get('title', 'N/A')
      item_year = item.get('year', 'N/A')
      tmdb_id = item.get('tmdb_id')
      media_type = item.get('media_type')
      
      buttons.append([
          InlineKeyboardButton(
              text=f"{item_title} ({item_year}) - {media_type.upper()}",
              callback_data=f"admin_series:{user_id}:select_tmdb:{tmdb_id}:{media_type}"
          )
      ])
  
  # Store initial state
  _set_user_state(user_id, {
      'main_msg_id': initial_msg.id,
      'current_step': 'SELECT_TMDB',
      'series_data': {}
  })

  await initial_msg.edit_text(
      "Select a series from the results below:",
      reply_markup=InlineKeyboardMarkup(buttons)
  )

@Client.on_message(filters.command('cancel') & filters.user(ADMINS))
async def cancel_admin_flow(client, message: Message):
  user_id = message.from_user.id
  user_state = _get_user_state(user_id)
  if user_state and user_state.get('main_msg_id'):
      try:
          await client.edit_message_text(
              chat_id=user_id,
              message_id=user_state['main_msg_id'],
              text="Admin operation cancelled.",
              reply_markup=None
          )
          if user_state.get('ask_msg_id'):
              await client.delete_messages(user_id, user_state['ask_msg_id'])
      except Exception as e:
          logger.warning(f"Error cleaning up cancelled admin flow: {e}")
      _clear_user_state(user_id)
      await message.reply_text("Admin operation cancelled and state cleared.")
  else:
      await message.reply_text("No active admin operation to cancel.")

@Client.on_message(filters.command('viewstate') & filters.user(ADMINS))
async def view_user_state(client, message: Message):
    user_id = message.from_user.id
    user_state = _get_user_state(user_id)
    if user_state:
        state_str = json.dumps(user_state, indent=2, default=str) # default=str to handle non-JSON serializable objects
        if len(state_str) > 4096:
            with io.BytesIO(state_str.encode()) as f:
                f.name = "user_state.json"
                await message.reply_document(f, caption="Your current admin UI state:")
        else:
            await message.reply_text(f"Your current admin UI state:\n```json\n{state_str}\n```", parse_mode=enums.ParseMode.MARKDOWN)
    else:
        await message.reply_text("No active admin UI state found for you.")

@Client.on_callback_query(filters.regex(r"^admin_series:") & filters.user(ADMINS))
async def admin_series_callback_handler(client, query):
  user_id = query.from_user.id
  data_parts = query.data.split(':')
  
  # Ensure the callback is for the current user and active session
  if str(user_id) != data_parts[1]:
      await query.answer("This is not your session!", show_alert=True)
      return

  user_state = _get_user_state(user_id)
  if not user_state or user_state.get('main_msg_id') != query.message.id:
      await query.answer("This session is expired or invalid. Please start a new one with /newseries.", show_alert=True)
      _clear_user_state(user_id)
      return

  action = data_parts[2]
  logger.info(f"User {user_id}: Callback action received: {action}")

  if action == 'select_tmdb':
      tmdb_id = data_parts[3]
      media_type = data_parts[4]
      
      await query.answer("Fetching details...")
      tmdb_details = await get_tmdb_info(tmdb_id, id=True, media_type=media_type)
      
      if not tmdb_details:
          await query.message.edit_text("Failed to retrieve TMDB data. Please try again.")
          _clear_user_state(user_id)
          return

      series_key = tmdb_details['title'].lower().replace(" ", "").replace("-", "")
      
      # Initialize series_data with TMDB info
      user_state['series_data'] = {
          'key': series_key,
          'title': tmdb_details.get('title', 'N/A'),
          'released_on': tmdb_details.get('year', 'N/A'),
          'genre': tmdb_details.get('genres', 'N/A'),
          'rating': tmdb_details.get('rating', 'N/A'),
          'poster_url': tmdb_details.get('poster'),
          'tmdb_id': tmdb_details.get('tmdb_id'),
          'media_type': tmdb_details.get('media_type'),
          'languages': {} # Initialize empty languages
      }
      user_state['current_step'] = 'EDIT_SERIES'
      _set_user_state(user_id, user_state)
      await _update_main_message(client, user_id)
      await query.answer("Series selected!")

  elif action == 'edit_series':
      user_state['current_step'] = 'EDIT_SERIES'
      _set_user_state(user_id, user_state)
      await _update_main_message(client, user_id)
      await query.answer("Editing series details.")

  elif action == 'add_poster':
      user_state['current_step'] = 'ADD_POSTER'
      _set_user_state(user_id, user_state)
      ask_msg = await query.message.reply_text("Please send me the new poster image.")
      user_state['ask_msg_id'] = ask_msg.id
      _set_user_state(user_id, user_state)
      await query.answer("Waiting for poster image...")

  elif action == 'manage_languages':
      user_state['current_step'] = 'MANAGE_LANGUAGES'
      _set_user_state(user_id, user_state)
      await _update_main_message(client, user_id)
      await query.answer("Managing languages.")

  elif action == 'add_language':
      user_state['current_step'] = 'ADD_LANGUAGE'
      _set_user_state(user_id, user_state)
      
      lang_options = ["English", "Spanish", "Japanese", "Korean", "French", "German", "Multi Audio (Ger + Eng)"]
      reply_kb = _generate_reply_keyboard(lang_options, row_width=3)
      
      ask_msg = await query.message.reply_text("Enter language name:", reply_markup=reply_kb)
      user_state['ask_msg_id'] = ask_msg.id
      _set_user_state(user_id, user_state)
      await query.answer("Waiting for language name...")

  elif action == 'select_language':
      lang_key = data_parts[3]
      user_state['current_language_key'] = lang_key
      user_state['current_step'] = 'MANAGE_SEASONS'
      _set_user_state(user_id, user_state)
      await _update_main_message(client, user_id)
      await query.answer(f"Selected language: {user_state['series_data']['languages'][lang_key]['name']}")

  elif action == 'add_season':
      lang_key = data_parts[3]
      user_state['current_step'] = 'ADD_SEASON'
      user_state['current_language_key'] = lang_key
      _set_user_state(user_id, user_state)

      season_options = [f"Season {i}" for i in range(1, 7)] + ["Part 1", "Part 2"]
      reply_kb = _generate_reply_keyboard(season_options, row_width=3)

      ask_msg = await query.message.reply_text("Enter season name (e.g., 'Season 1', 'Part 1'):", reply_markup=reply_kb)
      user_state['ask_msg_id'] = ask_msg.id
      _set_user_state(user_id, user_state)
      await query.answer("Waiting for season name...")

  elif action == 'select_season':
      lang_key = data_parts[3]
      season_key = data_parts[4]
      user_state['current_language_key'] = lang_key
      user_state['current_season_key'] = season_key
      user_state['current_step'] = 'MANAGE_QUALITIES'
      _set_user_state(user_id, user_state)
      await _update_main_message(client, user_id)
      await query.answer(f"Selected season: {user_state['series_data']['languages'][lang_key]['seasons'][season_key]['name']}")

  elif action == 'add_quality':
      lang_key = data_parts[3]
      season_key = data_parts[4]
      user_state['current_step'] = 'ADD_QUALITY'
      user_state['current_language_key'] = lang_key
      user_state['current_season_key'] = season_key
      _set_user_state(user_id, user_state)

      quality_options = ["360p", "480p", "720p", "1080p", "2160p", "H.264", "H.265", "H.265 10bit"]
      reply_kb = _generate_reply_keyboard(quality_options, row_width=3)

      ask_msg = await query.message.reply_text("Enter Quality Name (e.g., '720p', '1080p H.265'):", reply_markup=reply_kb)
      user_state['ask_msg_id'] = ask_msg.id
      _set_user_state(user_id, user_state)
      await query.answer("Waiting for quality name...")

  elif action == 'select_quality':
      lang_key = data_parts[3]
      season_key = data_parts[4]
      quality_key = data_parts[5]
      user_state['current_language_key'] = lang_key
      user_state['current_season_key'] = season_key
      user_state['current_quality_key'] = quality_key
      user_state['current_step'] = 'ADD_FILES_START'
      _set_user_state(user_id, user_state)
      
      ask_msg = await query.message.reply_text(
          f"Forward me the first file (with tag) for "
          f"{series_data['languages'][lang_key]['name']}-"
          f"{series_data['languages'][lang_key]['seasons'][season_key]['name']}-"
          f"{series_data['languages'][lang_key]['seasons'][season_key]['qualities'][quality_key]['name']}"
      )
      user_state['ask_msg_id'] = ask_msg.id
      _set_user_state(user_id, user_state)
      await _update_main_message(client, user_id) # Update main message to show current quality selected
      await query.answer("Waiting for first file...")

  elif action == 'publish_confirm':
      user_state['current_step'] = 'PUBLISH_CONFIRM'
      _set_user_state(user_id, user_state)
      await _update_main_message(client, user_id)
      await query.answer("Confirm publishing.")

  elif action == 'publish_yes':
      await query.answer("Publishing series...")
      await query.message.edit_text("Publishing series... This may take a moment.")
      
      series_data_to_publish = user_state['series_data']
      await _save_series_to_db(series_data_to_publish)
      
      await query.message.edit_text("Series published successfully! All empty groups have been removed.")
      _clear_user_state(user_id)
      await query.answer("Published!")

  elif action == 'publish_no':
      user_state['current_step'] = 'EDIT_SERIES'
      _set_user_state(user_id, user_state)
      await _update_main_message(client, user_id)
      await query.answer("Publishing cancelled.")

  elif action == 'delete_lang':
      lang_key_to_delete = data_parts[3]
      series_data = user_state['series_data']
      if lang_key_to_delete in series_data['languages']:
          # Delete associated files from episodes collection first
          lang_data = series_data['languages'][lang_key_to_delete]
          for season_key, season_data in lang_data.get('seasons', {}).items():
              for qual_key, qual_data in season_data.get('qualities', {}).items():
                  await delete_quality_files_from_episodes(qual_data.get('file_link_key'))
          
          del series_data['languages'][lang_key_to_delete]
          user_state['series_data'] = series_data
          user_state['current_step'] = 'MANAGE_LANGUAGES' # Go back to language list
          _set_user_state(user_id, user_state)
          await _update_main_message(client, user_id)
          await query.answer(f"Language '{lang_key_to_delete}' deleted.")
      else:
          await query.answer("Language not found.", show_alert=True)

  elif action == 'delete_seas':
      lang_key = data_parts[3]
      season_key_to_delete = data_parts[4]
      series_data = user_state['series_data']
      if lang_key in series_data['languages'] and season_key_to_delete in series_data['languages'][lang_key]['seasons']:
          # Delete associated files from episodes collection first
          season_data = series_data['languages'][lang_key]['seasons'][season_key_to_delete]
          for qual_key, qual_data in season_data.get('qualities', {}).items():
              await delete_quality_files_from_episodes(qual_data.get('file_link_key'))

          del series_data['languages'][lang_key]['seasons'][season_key_to_delete]
          user_state['series_data'] = series_data
          user_state['current_step'] = 'MANAGE_SEASONS' # Go back to season list
          _set_user_state(user_id, user_state)
          await _update_main_message(client, user_id)
          await query.answer(f"Season '{season_key_to_delete}' deleted.")
      else:
          await query.answer("Season not found.", show_alert=True)

  elif action == 'delete_qual':
      lang_key = data_parts[3]
      season_key = data_parts[4]
      quality_key_to_delete = data_parts[5]
      series_data = user_state['series_data']
      if (lang_key in series_data['languages'] and 
          season_key in series_data['languages'][lang_key]['seasons'] and
          quality_key_to_delete in series_data['languages'][lang_key]['seasons'][season_key]['qualities']):
          
          # Delete associated files from episodes collection first
          qual_data = series_data['languages'][lang_key]['seasons'][season_key]['qualities'][quality_key_to_delete]
          await delete_quality_files_from_episodes(qual_data.get('file_link_key'))

          del series_data['languages'][lang_key]['seasons'][season_key]['qualities'][quality_key_to_delete]
          user_state['series_data'] = series_data
          user_state['current_step'] = 'MANAGE_QUALITIES' # Go back to quality list
          _set_user_state(user_id, user_state)
          await _update_main_message(client, user_id)
          await query.answer(f"Quality '{quality_key_to_delete}' deleted.")
      else:
          await query.answer("Quality not found.", show_alert=True)

@Client.on_message(filters.private & filters.user(ADMINS) & filters.reply)
async def admin_reply_handler(client, message: Message):
  user_id = message.from_user.id
  user_state = _get_user_state(user_id)

  logger.info(f"User {user_id}: Reply handler triggered. Current step: {user_state.get('current_step')}, Reply to message ID: {message.reply_to_message.id}, Expected ask_msg_id: {user_state.get('ask_msg_id')}")

  if not user_state or user_state.get('ask_msg_id') != message.reply_to_message.id:
      # Not a reply to the bot's current "ask" message
      logger.info(f"User {user_id}: Reply not to expected ask message. Ignoring.")
      return

  current_step = user_state.get('current_step')
  series_data = user_state.get('series_data', {})
  
  # Delete the bot's "ask" message and the user's reply
  try:
      if user_state.get('ask_msg_id'):
          await client.delete_messages(user_id, [user_state['ask_msg_id'], message.id])
          logger.info(f"User {user_id}: Deleted ask_msg_id {user_state['ask_msg_id']} and user reply {message.id}.")
  except Exception as e:
      logger.warning(f"User {user_id}: Could not delete ask/reply messages: {e}")
  user_state['ask_msg_id'] = None # Clear ask_msg_id after handling

  if current_step == 'EDIT_SERIES':
      # This part handles direct text replies to the main message for editing fields
      # The request implies editing happens by replying to the main message,
      # but the current UI flow uses buttons for navigation.
      # For simplicity, I'll assume direct text replies are for the main series fields.
      # A more robust solution would involve specific "edit title" buttons.
      # For now, if the user replies to the main message with text, we'll try to parse it.
      # This part might need refinement based on how you want the "Edit" button to work.
      # Given the current flow, this block might not be hit often.
      pass

  elif current_step == 'ADD_LANGUAGE':
      lang_name = message.text.strip()
      logger.info(f"User {user_id}: ADD_LANGUAGE step. Received language name: '{lang_name}'")
      if not lang_name:
          await message.reply_text("Language name cannot be empty. Please try again.")
          return
      
      lang_key = lang_name.lower().replace(" ", "").replace("-", "") # Generate a simple key
      if lang_key in series_data.get('languages', {}):
          await message.reply_text(f"Language '{lang_name}' already exists. Please choose a different name or select the existing one.")
          return

      if 'languages' not in series_data:
          series_data['languages'] = {}
      series_data['languages'][lang_key] = {'name': lang_name, 'seasons': {}}
      
      user_state['series_data'] = series_data
      user_state['current_step'] = 'MANAGE_LANGUAGES' # Go back to language list
      _set_user_state(user_id, user_state)
      await _update_main_message(client, user_id)
      await message.reply_text(f"Language '{lang_name}' added successfully!", reply_markup=ReplyKeyboardRemove())
      logger.info(f"User {user_id}: Language '{lang_name}' added and state updated.")

  elif current_step == 'ADD_SEASON':
      lang_key = user_state['current_language_key']
      season_name = message.text.strip()
      logger.info(f"User {user_id}: ADD_SEASON step. Received season name: '{season_name}' for lang_key: {lang_key}")
      if not season_name:
          await message.reply_text("Season name cannot be empty. Please try again.")
          return
      
      season_key = season_name.lower().replace(" ", "").replace("-", "") # Generate a simple key
      if season_key in series_data['languages'][lang_key].get('seasons', {}):
          await message.reply_text(f"Season '{season_name}' already exists for this language. Please choose a different name or select the existing one.")
          return

      if 'seasons' not in series_data['languages'][lang_key]:
          series_data['languages'][lang_key]['seasons'] = {}
      series_data['languages'][lang_key]['seasons'][season_key] = {'name': season_name, 'qualities': {}}
      
      user_state['series_data'] = series_data
      user_state['current_step'] = 'MANAGE_SEASONS' # Go back to season list
      _set_user_state(user_id, user_state)
      await _update_main_message(client, user_id)
      await message.reply_text(f"Season '{season_name}' added successfully!", reply_markup=ReplyKeyboardRemove())
      logger.info(f"User {user_id}: Season '{season_name}' added and state updated.")

  elif current_step == 'ADD_QUALITY':
      lang_key = user_state['current_language_key']
      season_key = user_state['current_season_key']
      quality_name = message.text.strip()
      logger.info(f"User {user_id}: ADD_QUALITY step. Received quality name: '{quality_name}' for lang_key: {lang_key}, season_key: {season_key}")
      if not quality_name:
          await message.reply_text("Quality name cannot be empty. Please try again.")
          return
      
      quality_key = quality_name.lower().replace(" ", "").replace("-", "") # Generate a simple key
      if quality_key in series_data['languages'][lang_key]['seasons'][season_key].get('qualities', {}):
          await message.reply_text(f"Quality '{quality_name}' already exists for this season. Please choose a different name or select the existing one.")
          return

      if 'qualities' not in series_data['languages'][lang_key]['seasons'][season_key]:
          series_data['languages'][lang_key]['seasons'][season_key]['qualities'] = {}
      series_data['languages'][lang_key]['seasons'][season_key]['qualities'][quality_key] = {
          'name': quality_name, 
          'file_link_key': None, # Will be set after files are forwarded
          'files_to_add': [], # Temporary storage for files before publish
          'codec': None
      }
      
      user_state['series_data'] = series_data
      user_state['current_step'] = 'MANAGE_QUALITIES' # Go back to quality list
      _set_user_state(user_id, user_state)
      await _update_main_message(client, user_id)
      await message.reply_text(f"Quality '{quality_name}' added successfully!", reply_markup=ReplyKeyboardRemove())
      logger.info(f"User {user_id}: Quality '{quality_name}' added and state updated.")

  elif current_step == 'ADD_FILES_START':
      logger.info(f"User {user_id}: ADD_FILES_START step. Message media: {message.media}")
      if not message.media:
          await message.reply_text("Please forward a file, not text.")
          return
      
      channel_id, f_msg_id = await get_message_id(client, message)
      logger.info(f"User {user_id}: First file info - Channel ID: {channel_id}, Message ID: {f_msg_id}")
      if not channel_id or not f_msg_id:
          await message.reply_text("This message/link is not from a valid DB Channel. Please forward with quotes or send a valid link.")
          return

      user_state['current_first_msg_info'] = {'channel_id': channel_id, 'msg_id': f_msg_id}
      user_state['current_step'] = 'ADD_FILES_END'
      _set_user_state(user_id, user_state)

      ask_msg = await message.reply_text(
          f"Forward me the last file (with tag) for "
          f"{series_data['languages'][user_state['current_language_key']]['name']}-"
          f"{series_data['languages'][user_state['current_language_key']]['seasons'][user_state['current_season_key']]['name']}-"
          f"{series_data['languages'][user_state['current_language_key']]['seasons'][user_state['current_season_key']]['qualities'][user_state['current_quality_key']]['name']}\n\n"
          f"Go to first file: [Link](https://t.me/c/{channel_id.replace('-100', '')}/{f_msg_id})"
      )
      user_state['ask_msg_id'] = ask_msg.id
      _set_user_state(user_id, user_state)
      await message.reply_text("Waiting for last file...")
      logger.info(f"User {user_id}: First file received, asking for last file.")

  elif current_step == 'ADD_FILES_END':
      logger.info(f"User {user_id}: ADD_FILES_END step. Message media: {message.media}")
      if not message.media:
          await message.reply_text("Please forward a file, not text.")
          return
      
      s_channel_id, s_msg_id = await get_message_id(client, message)
      logger.info(f"User {user_id}: Last file info - Channel ID: {s_channel_id}, Message ID: {s_msg_id}")
      if not s_channel_id or not s_msg_id:
          await message.reply_text("This message/link is not from a valid DB Channel. Please forward with quotes or send a valid link.")
          return
      
      first_msg_info = user_state.get('current_first_msg_info')
      if not first_msg_info or first_msg_info['channel_id'] != s_channel_id:
          await message.reply_text("The last file is not from the same channel as the first file. Please try again.")
          return

      user_state['current_last_msg_info'] = {'channel_id': s_channel_id, 'msg_id': s_msg_id}
      user_state['current_step'] = 'ADD_FILES_CODEC'
      _set_user_state(user_id, user_state)

      codec_options = ["H.264", "H.265", "H.265 10bit"]
      reply_kb = _generate_reply_keyboard(codec_options, row_width=3)

      ask_msg = await message.reply_text("Send me the codec field:", reply_markup=reply_kb)
      user_state['ask_msg_id'] = ask_msg.id
      _set_user_state(user_id, user_state)
      await message.reply_text("Waiting for codec...")
      logger.info(f"User {user_id}: Last file received, asking for codec.")

  elif current_step == 'ADD_FILES_CODEC':
      codec = message.text.strip()
      logger.info(f"User {user_id}: ADD_FILES_CODEC step. Received codec: '{codec}'")
      if not codec:
          await message.reply_text("Codec cannot be empty. Please try again.")
          return

      first_msg_info = user_state['current_first_msg_info']
      last_msg_info = user_state['current_last_msg_info']
      
      channel_id = first_msg_info['channel_id']
      first_msg_id = first_msg_info['msg_id']
      last_msg_id = last_msg_info['msg_id']

      processing_msg = await message.reply_text("Processing files... This may take a while.")
      
      # Fetch messages from DB_CHANNEL
      message_ids_range = list(range(first_msg_id, last_msg_id + 1))
      fetched_messages = await get_messages(client, channel_id, message_ids_range)
      logger.info(f"User {user_id}: Fetched {len(fetched_messages)} messages from {channel_id} from {first_msg_id} to {last_msg_id}.")
      
      files_to_save = []
      for msg in fetched_messages:
          media = get_file_id(msg)
          if media:
              files_to_save.append({
                  "file_id": media.file_id,
                  "file_ref": media.file_ref,
                  "caption": msg.caption.html if msg.caption else None,
                  "message_id": msg.id # Store original message ID for reference
              })
      
      lang_key = user_state['current_language_key']
      season_key = user_state['current_season_key']
      quality_key = user_state['current_quality_key']
      
      # Generate file_link_key
      series_key = series_data['key']
      file_link_key = f"{series_key}-{lang_key}-{season_key}-{quality_key}"

      series_data['languages'][lang_key]['seasons'][season_key]['qualities'][quality_key]['file_link_key'] = file_link_key
      series_data['languages'][lang_key]['seasons'][season_key]['qualities'][quality_key]['files_to_add'] = files_to_save
      series_data['languages'][lang_key]['seasons'][season_key]['qualities'][quality_key]['codec'] = codec
      series_data['languages'][lang_key]['seasons'][season_key]['qualities'][quality_key]['channel_id'] = channel_id.replace('-100', '') # Store raw channel ID
      series_data['languages'][lang_key]['seasons'][season_key]['qualities'][quality_key]['first_msg_id'] = first_msg_id
      series_data['languages'][lang_key]['seasons'][season_key]['qualities'][quality_key]['last_msg_id'] = last_msg_id

      user_state['series_data'] = series_data
      user_state['current_step'] = 'MANAGE_QUALITIES' # Go back to quality list
      _set_user_state(user_id, user_state)

      await processing_msg.edit_text("Files added to Database Successfully!", reply_markup=ReplyKeyboardRemove())
      await _update_main_message(client, user_id)
      logger.info(f"User {user_id}: Files linked and state updated for quality '{quality_key}'.")
      
  elif current_step == 'ADD_POSTER':
      logger.info(f"User {user_id}: ADD_POSTER step. Message photo: {message.photo}")
      if not message.photo:
          await message.reply_text("Please send a photo for the poster.")
          return
      
      download_location = await message.download(file_name=os.path.join(TMP_DOWNLOAD_DIRECTORY, f"{user_id}_poster.jpg"))
      logger.info(f"User {user_id}: Poster downloaded to {download_location}")
      
      try:
          with open(download_location, "rb") as file:
              response = requests.post(
                  "https://api.imgbb.com/1/upload",
                  params={"key": IMGBB_API_KEY},
                  files={"image": file}
              )
              response_data = response.json()
          logger.info(f"User {user_id}: ImgBB upload response: {response_data}")
          
          if response.status_code == 200 and "data" in response_data:
              poster_url = response_data["data"]["url"]
              series_data['poster_url'] = poster_url
              user_state['series_data'] = series_data
              _set_user_state(user_id, user_state)
              await _update_main_message(client, user_id)
              await message.reply_text("Poster updated successfully!", reply_markup=ReplyKeyboardRemove())
              logger.info(f"User {user_id}: Poster updated to {poster_url}.")
          else:
              error_message = response_data.get("error", {}).get("message", "Unknown error")
              await message.reply_text(f"Failed to upload poster: {error_message}", reply_markup=ReplyKeyboardRemove())
              logger.error(f"User {user_id}: ImgBB upload failed: {error_message}")
      except Exception as e:
          logger.error(f"User {user_id}: Error uploading poster: {e}")
          await message.reply_text(f"An error occurred during poster upload: {e}", reply_markup=ReplyKeyboardRemove())
      finally:
          if os.path.exists(download_location):
              os.remove(download_location)
              logger.info(f"User {user_id}: Deleted temporary poster file: {download_location}")
      
      user_state['current_step'] = 'EDIT_SERIES' # Go back to edit series
      _set_user_state(user_id, user_state)
