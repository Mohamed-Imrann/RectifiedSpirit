#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import asyncio
import time
from pyrogram import filters, Client, enums
from pyrogram.errors import FloodWait
from pymongo import MongoClient
from pyrogram.errors.exceptions.bad_request_400 import ChannelInvalid, UsernameInvalid, UsernameNotModified
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from info import ADMINS, AUTH_CHANNEL, DB_CHANNEL, DATABASE_URI
#from database.ia_filterdb import unpack_new_file_id
from utils import temp, get_message_id
import re
import os
import json
import base64
from pyrogram.file_id import FileId
import zlib
import logging

BATCH_STORE = int('-1002250913478')

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
mongo_client = MongoClient(DATABASE_URI)
db = mongo_client["file_database"]
collection = db["episodes"]

async def allowed(_, __, message):
  if message.from_user and message.from_user.id in ADMINS:
      return True
  return False


import logging
import asyncio

logger = logging.getLogger(__name__)

@Client.on_message(filters.private & filters.command('batch') & filters.create(allowed))
async def batch(client, message):

  while True:
      try:         
          first_message = await client.ask(
              text="Forward the First Message from DB Channel (with Quotes) or Send the DB Channel Post Link",
              chat_id=message.from_user.id,
              filters=(filters.forwarded | (filters.text & ~filters.forwarded)),
              timeout=60
          )
      except asyncio.TimeoutError:      
          return

      channel_id, f_msg_id = await get_message_id(client, first_message)

      if channel_id and f_msg_id:
          break
      else:
          await first_message.reply("   Error\n\nThis message/link is not from a valid DB Channel.", quote=True)
          continue

  while True:
      try:
          second_message = await client.ask(
              text="Forward the Last Message from DB Channel (with Quotes) or Send the DB Channel Post Link",
              chat_id=message.from_user.id,
              filters=(filters.forwarded | (filters.text & ~filters.forwarded)),
              timeout=60
          )
      except asyncio.TimeoutError:
          return

      s_channel_id, s_msg_id = await get_message_id(client, second_message)

      if s_channel_id == channel_id and s_msg_id:
          break
      else:
          await second_message.reply("   Error\n\nThis message/link is not from the same DB Channel.", quote=True)
          continue

  raw_channel_id = channel_id.replace("-100", "")
  result_string = f"get_{raw_channel_id}_{f_msg_id}_{s_msg_id}"
  await message.reply_text(f"{result_string}")



def unpack_new_file_id(new_file_id):
  decoded = FileId.decode(new_file_id)
  file_id = new_file_id  # Store full file_id
  file_ref = decoded.file_reference
  return file_id, file_ref

# ============================================================
# ✅ TEMP TOKEN SYSTEM (for deep-link / forcesub pending send)
#    - create_temp_token(user_id, link_key, ttl_seconds)
#    - get_link_key_by_token(user_id, token)
#    - delete_temp_token(token)
# ============================================================
import secrets

# Use a separate collection for temp tokens
temp_tokens_col = mongo_client["file_database"]["temp_tokens"]

# Best-effort index. Helps auto cleanup expired docs.
try:
    temp_tokens_col.create_index("exp", expireAfterSeconds=0)
    temp_tokens_col.create_index([("token", 1)], unique=True)
    temp_tokens_col.create_index([("user_id", 1)])
except Exception:
    pass

async def create_temp_token(user_id: int, link_key: str, ttl_seconds: int = 600) -> str:
    """Create a short-lived token that maps to a link_key.
    Stored in Mongo so it works across restarts / multi instances.
    """
    token = secrets.token_urlsafe(16)
    exp = time.time() + int(ttl_seconds)

    doc = {
        "token": token,
        "user_id": int(user_id),
        "link_key": str(link_key),
        "exp": exp,
        "created_at": time.time(),
    }

    def _insert():
        try:
            temp_tokens_col.insert_one(doc)
            return token
        except Exception:
            # token collision rare; retry once
            new_token = secrets.token_urlsafe(18)
            doc["token"] = new_token
            temp_tokens_col.insert_one(doc)
            return new_token

    return await asyncio.to_thread(_insert)

async def get_link_key_by_token(user_id: int, token: str):
    """Return real link_key for a token (only if belongs to user and not expired)."""
    token = (token or "").strip()
    if not token:
        return None

    def _get():
        doc = temp_tokens_col.find_one({"token": token})
        if not doc:
            return None
        if int(doc.get("user_id", 0)) != int(user_id):
            return None
        if float(doc.get("exp", 0)) < time.time():
            # cleanup
            try:
                temp_tokens_col.delete_one({"token": token})
            except Exception:
                pass
            return None
        return doc.get("link_key")

    return await asyncio.to_thread(_get)

async def delete_temp_token(token: str):
    token = (token or "").strip()
    if not token:
        return

    def _del():
        try:
            temp_tokens_col.delete_one({"token": token})
        except Exception:
            pass

    await asyncio.to_thread(_del)
