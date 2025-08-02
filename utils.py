import asyncio
import re
import base64
import logging
from pyrogram.errors import MessageIdInvalid, FloodWait
from pyrogram.raw.functions.messages import GetMessages
from pyrogram.raw.types import InputMessageID
from pyrogram.errors import MessageNotModified
from pyrogram.enums import ParseMode
from imdb import Cinemagoer
from fuzzywuzzy import fuzz
import os
import requests
import shutil
import uuid

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Temporary storage for multi-step UI interactions for admin commands
class Temp:
  def __init__(self):
      self.admin_data = {} # Centralized admin state

temp = Temp()

# Helper to chunk buttons for inline keyboard
def chunk_buttons(buttons, chunk_size=2):
  return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]

async def get_message_id(client, message):
  if message.forward_from_chat:
      return message.forward_from_chat.id, message.forward_from_message_id
  elif message.text and message.text.startswith("https://t.me/"):
      try:
          # Regex to extract channel ID and message ID from a Telegram post link
          match = re.match(r"https://t.me/c/(\d+)/(\d+)", message.text)
          if match:
              channel_id_raw = int(match.group(1))
              message_id = int(match.group(2))
              # Convert raw channel ID to Pyrogram format
              channel_id = int(f"-100{channel_id_raw}")
              return channel_id, message_id
      except Exception as e:
          logger.error(f"Error parsing Telegram link: {e}")
          return None, None
  return None, None

async def get_messages_in_range(client, channel_id, start_msg_id, end_msg_id, target_channel_id):
  copied_messages = []
  for msg_id in range(start_msg_id, end_msg_id + 1):
      try:
          # Get the message from the source channel
          msg = await client.get_messages(channel_id, msg_id)
          if msg:
              # Copy the message to the target channel
              copied_msg = await msg.copy(target_channel_id)
              copied_messages.append(copied_msg)
          else:
              logger.warning(f"Message {msg_id} not found in channel {channel_id}")
      except Exception as e:
          logger.error(f"Error copying message {msg_id} from {channel_id} to {target_channel_id}: {e}")
  return copied_messages

async def delete_messages_from_user_chat(client, user_id, message_ids):
  try:
      await client.delete_messages(chat_id=user_id, message_ids=message_ids)
      logger.info(f"Deleted messages {message_ids} from user {user_id} chat.")
  except Exception as e:
      logger.warning(f"Could not delete messages {message_ids} from user {user_id} chat: {e}")

# IMDB functions
ia = Cinemagoer()

def get_poster(query, bulk=False, id=False):
  try:
      if id:
          movie = ia.get_movie(query)
          if movie:
              return {
                  'title': movie.get('title'),
                  'year': movie.get('year'),
                  'imdb_id': movie.movieID,
                  'kind': movie.get('kind'),
                  'poster': movie.get('full-size poster')
              }
          return None
      
      search_results = ia.search_movie(query)
      if not search_results:
          return None

      if bulk:
          results = []
          for movie in search_results[:5]: # Limit to 5 results
              results.append({
                  'title': movie.get('title'),
                  'year': movie.get('year'),
                  'imdb_id': movie.movieID,
                  'kind': movie.get('kind'),
                  'poster': movie.get('full-size poster')
              })
          return results
      else:
          movie = search_results[0]
          return movie.get('full-size poster')
  except Exception as e:
      logger.error(f"IMDb error: {e}")
      return None

def find_most_similar_title(query, titles):
  if not titles:
      return None
  
  # Use fuzzywuzzy to find the best match
  best_match = None
  highest_score = -1
  
  for title in titles:
      score = fuzz.ratio(query.lower(), title.lower())
      if score > highest_score:
          highest_score = score
          best_match = title
  
  # You might want to set a threshold for "similarity"
  if highest_score >= 70: # Example threshold
      return best_match
  return None
