#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from pyrogram import filters, enums
from pyrogram.types import InlineKeyboardButton, ChatJoinRequest
from pyrogram.errors import UserNotParticipant

from info import ADMINS, REQ_CHANNEL_ONE, REQ_CHANNEL_TWO, REQ_CHANNEL_THREE
from utils import temp

# DB helpers (must exist)
from database.request_forcesub_db import (
    add_req_one, add_req_two, add_req_three,
    is_requested_one, is_requested_two, is_requested_three
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# -----------------------------
# Internal: which channel is next for this user?
# -----------------------------
async def _get_pending_step(user_id: int):
    """
    Returns: (step_no, channel_id, invite_link, add_fn, is_fn)
    If all done => returns None
    """
    if int(user_id) in ADMINS:
        return None

    # step 1
    if REQ_CHANNEL_ONE and getattr(temp, "LINK_ONE", None):
        if not await is_requested_one(user_id):
            return (1, int(REQ_CHANNEL_ONE), temp.LINK_ONE, add_req_one, is_requested_one)

    # step 2
    if REQ_CHANNEL_TWO and getattr(temp, "LINK_TWO", None):
        if not await is_requested_two(user_id):
            return (2, int(REQ_CHANNEL_TWO), temp.LINK_TWO, add_req_two, is_requested_two)

    # step 3
    if REQ_CHANNEL_THREE and getattr(temp, "LINK_THREE", None):
        if not await is_requested_three(user_id):
            return (3, int(REQ_CHANNEL_THREE), temp.LINK_THREE, add_req_three, is_requested_three)

    return None


# -----------------------------
# Public: Buttons (ONE CHANNEL ONLY)
# -----------------------------
async def create_request_forcesub_buttons(client: "Bot", user_id: int):
    """
    Returns:
      [[InlineKeyboardButton(..)]]  -> if user must join something
      None                          -> if user already completed all
    """
    pending = await _get_pending_step(int(user_id))
    if not pending:
        return None

    step_no, channel_id, link, add_fn, is_fn = pending
    return [[InlineKeyboardButton(f"🎗 Join Channel {step_no} 🎗", url=link)]]


# -----------------------------
# Public: strict check + auto advance
# -----------------------------
async def check_and_advance_if_joined(client: "Bot", user_id: int) -> bool:
    """
    ✅ STRICT:
    - If user is member in current required channel -> mark as done (DB) and True
    - Else -> False
    """
    pending = await _get_pending_step(int(user_id))
    if not pending:
        return True  # all done

    step_no, channel_id, link, add_fn, is_fn = pending

    try:
        member = await client.get_chat_member(int(channel_id), int(user_id))
        status = member.status

        # ✅ joined statuses
        if status in (
            enums.ChatMemberStatus.MEMBER,
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER
        ):
            try:
                await add_fn(int(user_id))  # ✅ save completion for this step
            except Exception as e:
                logger.error(f"DB add step{step_no} failed: {e}")
            return True

        # ❌ not joined / left / kicked / banned etc
        return False

    except UserNotParticipant:
        return False
    except Exception as e:
        # ✅ STRICT MODE: if telegram glitch, do not allow send
        logger.error(f"check_and_advance_if_joined error: {e}")
        return False


# -----------------------------
# Join Request handler (Optional)
# If your channels are "request to join" type, this will auto-approve + save.
# -----------------------------
_join_filters = None
try:
    fl = None
    if REQ_CHANNEL_ONE:
        fl = filters.chat(int(REQ_CHANNEL_ONE))
    if REQ_CHANNEL_TWO:
        fl = (fl | filters.chat(int(REQ_CHANNEL_TWO))) if fl else filters.chat(int(REQ_CHANNEL_TWO))
    if REQ_CHANNEL_THREE:
        fl = (fl | filters.chat(int(REQ_CHANNEL_THREE))) if fl else filters.chat(int(REQ_CHANNEL_THREE))
    _join_filters = fl
except Exception as e:
    logger.error(f"Join request filters build error: {e}")
    _join_filters = None


if _join_filters:
    @Bot.on_chat_join_request(_join_filters)
    async def handle_join_request(bot: "Bot", join_req: ChatJoinRequest):
        user_id = join_req.from_user.id
        chat_id = join_req.chat.id

        # ✅ auto-approve join request
        try:
            await join_req.approve()
        except Exception as e:
            logger.error(f"approve join request failed: {e}")

        # ✅ save to DB for that channel
        try:
            if REQ_CHANNEL_ONE and chat_id == int(REQ_CHANNEL_ONE):
                await add_req_one(user_id)
            elif REQ_CHANNEL_TWO and chat_id == int(REQ_CHANNEL_TWO):
                await add_req_two(user_id)
            elif REQ_CHANNEL_THREE and chat_id == int(REQ_CHANNEL_THREE):
                await add_req_three(user_id)
        except Exception as e:
            logger.error(f"handle_join_request db save failed: {e}")
