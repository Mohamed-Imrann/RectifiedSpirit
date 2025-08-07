#Credits Only To Abhishek
#None Of The People In The Repository Are Coding But Suggestions
#t.me/Abhishekissac
import re
import pyrogram 
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto
from info import ADMINS, SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG
from database.crazy_db import (
  get_series, get_series_name, get_poster_manuel, get_links_for_quality
)
from database.gfilters_mdb import (
  find_gfilter,
  get_gfilters
)
from utils import temp
from imdb import Cinemagoer
import asyncio
import difflib
import logging
import random

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

requestor = {}
imdb = Cinemagoer()

async def DeleteMessage(msg):
  await asyncio.sleep(600)
  await msg.delete()

def find_close_matches(query, possibilities, n=3, cutoff=0.6):
  return difflib.get_close_matches(query, possibilities, n, cutoff)

def chunk_buttons(buttons, chunk_size=3):
  return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]

def find_most_similar_title(query, search_results):
  titles = [movie.get('title', '').lower() for movie in search_results]
  matches = difflib.get_close_matches(query.lower(), titles, n=1, cutoff=0.6)
  if matches:
      for movie in search_results:
          if movie.get('title', '').lower() == matches[0]:
              return movie
  return None

def get_movie_poster(series_key):
  poster_url = get_poster_manuel(series_key)
  if not poster_url:
      series = get_series_name(series_key)
      if series:
          poster_url = series.get('poster_url') # Get from the main series data
  return poster_url or NO_POSTER_FOUND_IMG[0]

@Client.on_message(filters.text & (filters.private | filters.group))
async def handle_message(client, message):
  glob = await global_filters(client, message)
  if glob == False:
      await series_filter(client, message)


async def global_filters(client, message, text=False):
  group_id = message.chat.id
  name = text or message.text 
  reply_id = message.reply_to_message.id if message.reply_to_message else message.id 
  keywords = await get_gfilters("gfilters")
  for keyword in reversed(sorted(keywords, key=len)):
      pattern = r"( |^|[\W])" + re.escape(keyword) + r"( |$|[\W])"
      if re.search(pattern, name, flags=re.IGNORECASE):
          reply_text, btn, alert, fileid = await find_gfilter("gfilters", keyword)
          if reply_text:
              reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")
          
          try:
              if fileid == "None":
                  if btn == "[]":
                      piroxrk = await client.send_message(
                          group_id,
                          reply_text,
                          disable_web_page_preview=True,
                          reply_to_message_id=reply_id
                      )
                  else:
                      button = eval(btn)
                      piroxrk = await client.send_message(
                          group_id,
                          reply_text,
                          disable_web_page_preview=True,
                          reply_markup=InlineKeyboardMarkup(button),
                          reply_to_message_id=reply_id
                      )
              elif btn == "[]":
                  piroxrk = await client.send_cached_media(
                      group_id,
                      fileid,
                      caption=reply_text or "",
                      reply_to_message_id=reply_id
                  )
              else:
                  button = eval(btn)
                  piroxrk = await message.reply_cached_media(
                      fileid,
                      caption=reply_text or "",
                      reply_markup=InlineKeyboardMarkup(button),
                      reply_to_message_id=reply_id
                  )
          except Exception as e:
              logger.exception(e)
          break
  else:
      return False

# ... (existing imports and functions)

async def series_filter(client: Client, message: Message):
    text = message.text.strip()
    series_infos = get_series()
    series_keys = [series['key'] for series in series_infos]
    series_names = [series['title'] for series in series_infos]

    series_key = None
    
    # Try exact match by key first
    if text.lower().replace(" ", "").replace("-", "") in series_keys:
        series_key = text.lower().replace(" ", "").replace("-", "")
    else:
        # Try exact match by title
        for s_info in series_infos:
            if s_info['title'].lower() == text.lower():
                series_key = s_info['key']
                break
        
        if not series_key:
            # Try close matches for titles
            close_matches = find_close_matches(text, series_names)
            if not close_matches:
                # Fallback to starts-with if no close matches
                first_word = text.split()[0]
                close_matches = [name for name in series_names if name.lower().startswith(first_word.lower())]
            
            if close_matches:
                buttons = []
                for match in close_matches:
                    s_info = next((s for s in series_infos if s['title'] == match), None)
                    if s_info:
                        buttons.append(InlineKeyboardButton(match, callback_data=f"user_series:{s_info['key']}"))
                
                if buttons:
                    buttons_chunked = chunk_buttons(buttons, chunk_size=1)
                    reply_markup = InlineKeyboardMarkup(buttons_chunked)
                    etho = await message.reply_photo(photo=random.choice(SPELL_CHECK_IMAGE), caption="<b>Choose Your Series:</b>", reply_markup=reply_markup)
                    reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else None
                    requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
                    asyncio.create_task(DeleteMessage(etho))
                    return

    if series_key:
        series = get_series_name(series_key)
        if not series:
            return

        languages = series.get("languages", {})
        
        reply_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n\n"
            "Select the language you need...!"
        )
        poster_url = get_movie_poster(series_key)
        
        buttons = []
        for lang_key, lang_data in languages.items():
            buttons.append(InlineKeyboardButton(lang_data['name'], callback_data=f"user_series:{series_key}:{lang_key}"))
        
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        reply_markup = InlineKeyboardMarkup(buttons_chunked)
        
        try:
            if poster_url:
                etho = await message.reply_photo(photo=poster_url, caption=reply_text, reply_markup=reply_markup)
            else:
                etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG[0], caption=reply_text, reply_markup=reply_markup)
            
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
            asyncio.create_task(DeleteMessage(etho))
            logger.info("Series filter message sent.")
        except pyrogram.errors.MediaEmpty:
            logger.warning(f"MediaEmpty error for poster: {poster_url}. Using placeholder.")
            etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG[0], caption=reply_text, reply_markup=reply_markup)
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
            asyncio.create_task(DeleteMessage(etho))
        except Exception as e:
            logger.error(f"Error sending series filter message: {e}")

# ... (rest of the existing code)

@Client.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
  data = query.data
  parts = data.split(":")
  clicked_user = query.from_user.id
  chat_id = query.message.chat.id
  message_id = query.message.id

  reply_msg = query.message.reply_to_message  
  if reply_msg and reply_msg.from_user:
      requested_user = reply_msg.from_user.id
  else:
      requested_user = requestor.get(f"{chat_id}•{message_id}")
  
  if chat_id < 0 and requested_user and clicked_user != requested_user:
      await query.answer("Not your request!", show_alert=True)
      return

  if data == "pages":
      await query.answer()
      return

  elif data.startswith("b:"):
      # This is the final link to fetch files
      file_link_key = data.split(":", 1)[1]
      
      # Fetch files from the episodes collection
      files_to_send, channel_id, first_msg_id, last_msg_id = await get_links_for_quality(file_link_key)

      if not files_to_send:
          await query.answer("No files found for this quality.", show_alert=True)
          return

      await query.answer("Sending files...")
      
      track_msgs = []
      for entry in files_to_send:
          try:
              copied_msg = await client.send_cached_media(
                  chat_id=query.from_user.id, 
                  file_id=entry["file_id"],
                  caption=entry.get("caption", "")
              )
              if copied_msg and temp.AUTO_DELETE_TIME and temp.AUTO_DELETE_TIME > 0:
                  track_msgs.append(copied_msg)
              await asyncio.sleep(0.5)
          except FloodWait as e:
              logger.warning(f"FloodWait for {e.value} sec")
              await asyncio.sleep(e.value)
              copied_msg = await client.send_cached_media(
                  chat_id=query.from_user.id, 
                  file_id=entry["file_id"],
                  caption=entry.get("caption", "")
              )
              if copied_msg and temp.AUTO_DELETE_TIME and temp.AUTO_DELETE_TIME > 0:
                  track_msgs.append(copied_msg)
          except Exception as e:
              logger.error(f"Error sending cached media to user {query.from_user.id}: {e}")
              # Optionally, send an error message to the user
              await client.send_message(query.from_user.id, f"Error sending file: {e}")
              
      if track_msgs:
          delete_data = await client.send_message(
              chat_id=query.from_user.id,
              text=temp.AUTO_DELETE_MSG.format(time=temp.AUTO_DELETE_TIME)
          )
          asyncio.create_task(DeleteMessage(delete_data)) # Use DeleteMessage for the auto-delete message
      return

  elif data.startswith("user_series:"):
      series_key = parts[1]
      series = get_series_name(series_key)
      if not series:
          await query.message.edit_text("Series not found or deleted.", parse_mode=enums.ParseMode.HTML)
          return

      lang_key = parts[2] if len(parts) > 2 else None
      season_key = parts[3] if len(parts) > 3 else None
      quality_key = parts[4] if len(parts) > 4 else None

      base_text = (
          f"○ **Title:** `{series['title']}`\n"
          f"○ **Released On:** `{series['released_on']}`\n"
          f"○ **Genre:** `{series['genre']}`\n"
          f"○ **Rating:** `{series['rating']}`\n"
          f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n"
      )
      
      buttons = []
      current_level_data = None
      back_callback = None

      if not lang_key: # Show languages
          current_level_data = series.get("languages", {})
          for key, data_item in current_level_data.items():
              buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"user_series:{series_key}:{key}"))
          text = base_text + "\nSelect the language you need...!"
          # No back button at this level, as it's the initial series view
          
      elif not season_key: # Show seasons for selected language
          current_level_data = series.get("languages", {}).get(lang_key, {}).get("seasons", {})
          lang_name = series.get("languages", {}).get(lang_key, {}).get("name", "N/A")
          for key, data_item in current_level_data.items():
              buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"user_series:{series_key}:{lang_key}:{key}"))
          text = base_text + f"○ **Language:** `{lang_name}`\n\nSelect the season you need...!"
          back_callback = f"user_series:{series_key}"

      elif not quality_key: # Show qualities for selected season
          current_level_data = series.get("languages", {}).get(lang_key, {}).get("seasons", {}).get(season_key, {}).get("qualities", {})
          lang_name = series.get("languages", {}).get(lang_key, {}).get("name", "N/A")
          season_name = series.get("languages", {}).get(lang_key, {}).get("seasons", {}).get(season_key, {}).get("name", "N/A")
          for key, data_item in current_level_data.items():
              # The file_link_key is stored in crazy_db, but the actual files are in episodes collection
              file_link_key = data_item.get('file_link_key')
              if file_link_key:
                  buttons.append(InlineKeyboardButton(data_item['name'], callback_data=f"b:{file_link_key}"))
          text = base_text + f"○ **Language:** `{lang_name}`\n○ **Season:** `{season_name}`\n\nSelect the quality you need...!"
          back_callback = f"user_series:{series_key}:{lang_key}"
      
      buttons_chunked = chunk_buttons(buttons, chunk_size=2)
      if back_callback:
          buttons_chunked.append([InlineKeyboardButton("Back", callback_data=back_callback)])
      
      reply_markup = InlineKeyboardMarkup(buttons_chunked)

      try:
          await query.message.edit_text(
              text=text,
              reply_markup=reply_markup,
              disable_web_page_preview=True,
              parse_mode=enums.ParseMode.MARKDOWN
          )
      except Exception as e:
          logger.error(f"Error editing message in user_series callback: {e}")
          await query.answer("An error occurred. Please try again.", show_alert=True)
