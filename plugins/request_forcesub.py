#!/usr/bin/env python3
# 8:43PM 2024-05-29
# ebiza.t.me

from bot import Bot
from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, ChatJoinRequest
from info import ADMINS, REQ_CHANNEL_ONE, REQ_CHANNEL_TWO
from database.request_forcesub_db import add_req_one, add_req_two, is_requested_one, is_requested_two
from utils import temp

import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ✅ FIX: accept (client, user_id) since caller sends 2 args
async def create_request_forcesub_buttons(client, user_id: int):
    btn = []

    if temp.LINK_ONE and user_id not in ADMINS and not await is_requested_one(user_id):
        btn.append([InlineKeyboardButton("🎗 Jᴏɪɴ Cʜᴀɴɴᴇʟ 1 🎗", url=temp.LINK_ONE)])

    if temp.LINK_TWO and user_id not in ADMINS and not await is_requested_two(user_id):
        btn.append([InlineKeyboardButton("🎗 Jᴏɪɴ Cʜᴀɴɴᴇʟ 2 🎗", url=temp.LINK_TWO)])

    return btn if btn else None


@Bot.on_chat_join_request(filters.chat(REQ_CHANNEL_ONE) | filters.chat(REQ_CHANNEL_TWO))
async def handle_join_request(bot: Bot, join_req: ChatJoinRequest):
    if join_req.chat.id == REQ_CHANNEL_ONE:
        try:
            await add_req_one(join_req.from_user.id)
        except Exception as e:
            logger.error(f"Error adding to req_one: {e}")

    elif join_req.chat.id == REQ_CHANNEL_TWO:
        try:
            await add_req_two(join_req.from_user.id)
        except Exception as e:
            logger.error(f"Error adding to req_two: {e}")
