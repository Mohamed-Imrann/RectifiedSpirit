#!/usr/bin/env python3
# 8:43PM 2024-05-29
# ebiza.t.me

from bot import Bot
from pyrogram import filters, enums
from pyrogram.types import InlineKeyboardButton, ChatJoinRequest
from pyrogram.errors import UserNotParticipant

from info import ADMINS, REQ_CHANNEL_ONE, REQ_CHANNEL_TWO
from database.request_forcesub_db import add_req_one, add_req_two
from utils import temp

import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ----------------------------
# ✅ Helpers (REAL JOIN CHECK)
# ----------------------------
async def _is_joined(client, chat_id: int, user_id: int) -> bool:
    try:
        mem = await client.get_chat_member(int(chat_id), int(user_id))
        # joined if not left/banned
        return mem.status not in (enums.ChatMemberStatus.LEFT, enums.ChatMemberStatus.BANNED)
    except UserNotParticipant:
        return False
    except Exception:
        # bot has no access / not admin / invalid chat
        return False


async def is_fsub_ok_any_one(client, user_id: int) -> bool:
    """
    ✅ OR logic:
    Join channel 1 OR channel 2 => allow
    """
    if user_id in ADMINS:
        return True

    ok1 = False
    ok2 = False

    if REQ_CHANNEL_ONE:
        ok1 = await _is_joined(client, REQ_CHANNEL_ONE, user_id)

    if REQ_CHANNEL_TWO:
        ok2 = await _is_joined(client, REQ_CHANNEL_TWO, user_id)

    return ok1 or ok2


# ----------------------------
# ✅ Buttons (show only not-joined)
# ----------------------------
async def create_request_forcesub_buttons(client, user_id: int):
    if user_id in ADMINS:
        return None

    btn = []

    if temp.LINK_ONE and REQ_CHANNEL_ONE:
        ok1 = await _is_joined(client, REQ_CHANNEL_ONE, user_id)
        if not ok1:
            btn.append([InlineKeyboardButton("🎗 Jᴏɪɴ Cʜᴀɴɴᴇʟ 1 🎗", url=temp.LINK_ONE)])

    if temp.LINK_TWO and REQ_CHANNEL_TWO:
        ok2 = await _is_joined(client, REQ_CHANNEL_TWO, user_id)
        if not ok2:
            btn.append([InlineKeyboardButton("🎗 Jᴏɪɴ Cʜᴀɴɴᴇʟ 2 🎗", url=temp.LINK_TWO)])

    return btn if btn else None


# ----------------------------
# Join request handler (optional DB save)
# ----------------------------
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
