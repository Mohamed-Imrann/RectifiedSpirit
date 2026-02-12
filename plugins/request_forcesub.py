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

from database.request_forcesub_db import (
    add_req_one, add_req_two, add_req_three,
    is_requested_one, is_requested_two, is_requested_three
)

# -----------------------------
# Internal: which channel is next for this user?
# -----------------------------
async def _get_pending_step(user_id: int):
    if user_id in ADMINS:
        return None

    if REQ_CHANNEL_ONE and temp.LINK_ONE and not await is_requested_one(user_id):
        return (1, int(REQ_CHANNEL_ONE), temp.LINK_ONE, add_req_one)

    if REQ_CHANNEL_TWO and temp.LINK_TWO and not await is_requested_two(user_id):
        return (2, int(REQ_CHANNEL_TWO), temp.LINK_TWO, add_req_two)

    if REQ_CHANNEL_THREE and getattr(temp, "LINK_THREE", None) and not await is_requested_three(user_id):
        return (3, int(REQ_CHANNEL_THREE), temp.LINK_THREE, add_req_three)

    return None


# -----------------------------
# Public: Buttons (ONE CHANNEL ONLY)
# -----------------------------
async def create_request_forcesub_buttons(client: Bot, user_id: int):
    pending = await _get_pending_step(user_id)
    if not pending:
        return None

    step_no, channel_id, link, add_fn = pending
    return [[InlineKeyboardButton(f"🎗 Join Channel {step_no} 🎗", url=link)]]


# -----------------------------
# Public: strict check + auto advance
# -----------------------------
async def check_and_advance_if_joined(client: Bot, user_id: int) -> bool:
    pending = await _get_pending_step(user_id)
    if not pending:
        return True

    step_no, channel_id, link, add_fn = pending

    try:
        member = await client.get_chat_member(channel_id, user_id)
        if member.status in (
            enums.ChatMemberStatus.MEMBER,
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER
        ):
            try:
                await add_fn(user_id)
            except Exception as e:
                logger.error(f"DB add step{step_no} failed: {e}")
            return True

        return False

    except UserNotParticipant:
        return False
    except Exception as e:
        logger.error(f"check_and_advance_if_joined error: {e}")
        return True


# -----------------------------
# Join Request handler (ONLY for channels that exist)
# -----------------------------
_join_filters = []
if REQ_CHANNEL_ONE:
    _join_filters.append(filters.chat(int(REQ_CHANNEL_ONE)))
if REQ_CHANNEL_TWO:
    _join_filters.append(filters.chat(int(REQ_CHANNEL_TWO)))
if REQ_CHANNEL_THREE:
    _join_filters.append(filters.chat(int(REQ_CHANNEL_THREE)))

if _join_filters:
    join_filter = _join_filters[0]
    for f in _join_filters[1:]:
        join_filter = join_filter | f

    @Bot.on_chat_join_request(join_filter)
    async def handle_join_request(bot: Bot, join_req: ChatJoinRequest):
        user_id = join_req.from_user.id
        chat_id = join_req.chat.id

        try:
            await join_req.approve()
        except Exception as e:
            logger.error(f"approve join request failed: {e}")

        try:
            if REQ_CHANNEL_ONE and chat_id == int(REQ_CHANNEL_ONE):
                await add_req_one(user_id)
            elif REQ_CHANNEL_TWO and chat_id == int(REQ_CHANNEL_TWO):
                await add_req_two(user_id)
            elif REQ_CHANNEL_THREE and chat_id == int(REQ_CHANNEL_THREE):
                await add_req_three(user_id)
        except Exception as e:
            logger.error(f"handle_join_request db save failed: {e}")
