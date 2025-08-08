#!/usr/bin/env python3
# 8:43PM 2024-05-29
# ebiza.t.me
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, ChatJoinRequest
from info import ADMINS, REQ_CHANNEL_ONE, REQ_CHANNEL_TWO
from Script import script
import asyncio
from info import CUSTOM_FILE_CAPTION
from database.request_forcesub_db import add_req_one, add_req_two, is_requested_one, is_requested_two
from utils import get_size, temp


# utils ---> 609, plugins.commands ---> 97
import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

async def create_request_forcesub_buttons(user_id:int):
    #logger.info(f"Creating forcesub buttons for user {user_id}")
    btn = []
    if temp.LINK_ONE and user_id not in ADMINS and not await is_requested_one(user_id):
        btn.append([InlineKeyboardButton("🎗 Jᴏɪɴ Cʜᴀɴɴᴇʟ 1 🎗", url=temp.LINK_ONE)])
    if temp.LINK_TWO and user_id not in ADMINS and not await is_requested_two(user_id):
        #logger.info("Adding Channel 2 button")
        btn.append([InlineKeyboardButton("🎗 Jᴏɪɴ Cʜᴀɴɴᴇʟ 2 🎗", url=temp.LINK_TWO)])
    if btn:
        #logger.info("Returning forcesub buttons")
        return btn
    else:
        #logger.info("No forcesub buttons needed")
        return None

@Client.on_chat_join_request(filters.chat(REQ_CHANNEL_ONE) | filters.chat(REQ_CHANNEL_TWO))
async def handle_join_request(bot: Client, join_req: ChatJoinRequest):
    #logger.info(f"Handling join request for user {join_req.from_user.id} in chat {join_req.chat.id}")
    if join_req.chat.id == REQ_CHANNEL_ONE:
        try:
            #logger.info("Adding to req_one DB")
            await add_req_one(join_req.from_user.id)
        except Exception as e:
            logger.error(f"Error adding to req_one: {e}")
    elif join_req.chat.id == REQ_CHANNEL_TWO:
        try:
            #logger.info("Adding to req_two DB")
            await add_req_two(join_req.from_user.id)
        except Exception as e:
            logger.error(f"Error adding to req_two: {e}")
