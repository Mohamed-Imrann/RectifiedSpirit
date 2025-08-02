import re
import os
import asyncio
import logging
from pyrogram import Client, enums
from pyrogram.errors import MessageEmpty, MessageNotModified, FloodWait
from imdb import Cinemagoer
from info import LOG_CHANNEL, DB_CHANNEL, RAW_DB_CHANNEL

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

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
