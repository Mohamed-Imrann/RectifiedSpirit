#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from bot import Bot
from pyrogram import filters, enums
from pyrogram.types import InlineKeyboardButton, ChatJoinRequest
from pyrogram.errors import UserNotParticipant

from info import ADMINS, REQ_CHANNEL_ONE, REQ_CHANNEL_TWO, REQ_CHANNEL_THREE
from utils import temp

import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# DB helpers (must exist)
from database.request_forcesub_db import (
    add_req_one, add_req_two, add_req_three,
    is_requested_one, is_requested_two, is_requested_three
)


# -----------------------------
# Internal: which channel is next for this user?
# -----------------------------
async def _get_pending_step(user_id: int):
    """
    Returns: (step_no, channel_id, invite_link, add_fn, is_fn)
    If all done => returns None
    """
    if user_id in ADMINS:
        return None

    if REQ_CHANNEL_ONE and temp.LINK_ONE and not await is_requested_one(user_id):
        return (1, int(REQ_CHANNEL_ONE), temp.LINK_ONE, add_req_one, is_requested_one)

    if REQ_CHANNEL_TWO and temp.LINK_TWO and not await is_requested_two(user_id):
        return (2, int(REQ_CHANNEL_TWO), temp.LINK_TWO, add_req_two, is_requested_two)

    if REQ_CHANNEL_THREE and getattr(temp, "LINK_THREE", None) and not await is_requested_three(user_id):
        return (3, int(REQ_CHANNEL_THREE), temp.LINK_THREE, add_req_three, is_requested_three)

    return None


# -----------------------------
# Public: Buttons (ONE CHANNEL ONLY)
# -----------------------------
async def create_request_forcesub_buttons(client: Bot, user_id: int):
    """
    Returns:
      [[InlineKeyboardButton(..)]]  -> if user must join something
      None                          -> if user already completed all
    """
    pending = await _get_pending_step(user_id)
    if not pending:
        return None

    step_no, channel_id, link, add_fn, is_fn = pending
    btn = [[InlineKeyboardButton(f"🎗 Join Channel {step_no} 🎗", url=link)]]
    return btn


# -----------------------------
# Public: strict check + auto advance
# -----------------------------
async def check_and_advance_if_joined(client: Bot, user_id: int) -> bool:
    """
    ✅ STRICT:
    - if user is member in current required channel -> mark as done (DB) and True
    - else -> False
    """
    pending = await _get_pending_step(user_id)
    if not pending:
        return True  # all done

    step_no, channel_id, link, add_fn, is_fn = pending

    try:
        member = await client.get_chat_member(channel_id, user_id)
        status = member.status

        if status in (enums.ChatMemberStatus.MEMBER,
                      enums.ChatMemberStatus.ADMINISTRATOR,
                      enums.ChatMemberStatus.OWNER):
            # ✅ joined => save + advance
            try:
                await add_fn(user_id)
            except Exception as e:
                logger.error(f"DB add step{step_no} failed: {e}")
            return True

        return False

    except UserNotParticipant:
        return False
    except Exception as e:
        # fail-safe: don't block if telegram API glitch
        logger.error(f"check_and_advance_if_joined error: {e}")
        return True


# -----------------------------
# Join Request handler (Optional but useful)
# If your channels are "request to join" type, this will auto-approve.
# -----------------------------
@Bot.on_chat_join_request(
    filters.chat(int(REQ_CHANNEL_ONE)) |
    filters.chat(int(REQ_CHANNEL_TWO)) |
    filters.chat(int(REQ_CHANNEL_THREE))
)
async def handle_join_request(bot: Bot, join_req: ChatJoinRequest):
    user_id = join_req.from_user.id
    chat_id = join_req.chat.id

    try:
        # ✅ auto-approve join request
        await join_req.approve()
    except Exception as e:
        logger.error(f"approve join request failed: {e}")

    try:
        if chat_id == int(REQ_CHANNEL_ONE):
            await add_req_one(user_id)
        elif chat_id == int(REQ_CHANNEL_TWO):
            await add_req_two(user_id)
        elif chat_id == int(REQ_CHANNEL_THREE):
            await add_req_three(user_id)
    except Exception as e:
        logger.error(f"handle_join_request db save failed: {e}")
