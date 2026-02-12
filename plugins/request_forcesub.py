#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging

from bot import Bot
from pyrogram import enums
from pyrogram.types import InlineKeyboardButton, ChatJoinRequest
from pyrogram.errors import UserNotParticipant, FloodWait

from database.join_reqs import JoinReqs
from utils import get_links_for_quality

# ✅ you must have these functions in database/request_forcesub_db.py
from database.request_forcesub_db import (
    get_user_step,
    set_user_step,
    advance_user_step,
    set_pending,
    get_pending,
    clear_pending,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

dbj = JoinReqs()


# ----------------------------
# Read all required chats from JoinReqs DB
# ----------------------------
async def _all_required_chats():
    chats = []

    try:
        c1 = await dbj.get_fsub_chat1()
        if c1 and c1.get("chat_id"):
            chats.append(int(c1["chat_id"]))
    except Exception:
        pass

    try:
        c2 = await dbj.get_fsub_chat2()
        if c2 and c2.get("chat_id"):
            chats.append(int(c2["chat_id"]))
    except Exception:
        pass

    # chat3 optional
    if hasattr(dbj, "get_fsub_chat3"):
        try:
            c3 = await dbj.get_fsub_chat3()
            if c3 and c3.get("chat_id"):
                chats.append(int(c3["chat_id"]))
        except Exception:
            pass

    # uniq preserve order
    uniq = []
    for x in chats:
        if x not in uniq:
            uniq.append(x)
    return uniq


async def get_required_fsub_chat(client: Bot, user_id: int):
    """
    returns: (required_chat_id, total_steps, step_no)
    """
    chats = await _all_required_chats()
    if not chats:
        return None, 0, 0

    total = len(chats)

    step = await get_user_step(int(user_id))
    if not step or step < 1 or step > total:
        step = 1
        await set_user_step(int(user_id), step)

    return int(chats[step - 1]), int(total), int(step)


# ----------------------------
# JOIN CHECK
# ✅ True if user is member OR request pending
# ----------------------------
async def _is_joined_or_requested(client: Bot, chat_id: int, user_id: int) -> bool:
    try:
        mem = await client.get_chat_member(int(chat_id), int(user_id))
        # if telegram returns status => not banned means ok
        return mem.status != enums.ChatMemberStatus.BANNED

    except UserNotParticipant:
        # Not a member. If request pending => allow
        try:
            reqs = await client.get_chat_join_requests(int(chat_id), limit=200)
            for r in reqs:
                if r.from_user and int(r.from_user.id) == int(user_id):
                    return True
        except Exception:
            pass
        return False

    except Exception as e:
        logger.error(f"_is_joined_or_requested error: {e}")
        return False


# ----------------------------
# INVITE URL
# ----------------------------
async def _get_chat_invite_url(client: Bot, chat_id: int) -> str:
    """
    Prefer join-request invite link (creates_join_request=True)
    """
    try:
        invite = await client.create_chat_invite_link(int(chat_id), creates_join_request=True)
        if invite and invite.invite_link:
            return invite.invite_link
    except Exception:
        pass

    try:
        chat = await client.get_chat(int(chat_id))
        if chat and getattr(chat, "username", None):
            return f"https://t.me/{chat.username}"
    except Exception:
        pass

    return "https://t.me/"


# ----------------------------
# ✅ REQUIRED: commands.py import expects this name
# ----------------------------
async def create_request_forcesub_buttons(client: Bot, user_id: int):
    """
    If user didn't join/request current step channel -> return button
    else -> None
    """
    required_chat_id, total, step = await get_required_fsub_chat(client, int(user_id))
    if not required_chat_id:
        return None

    ok = await _is_joined_or_requested(client, int(required_chat_id), int(user_id))
    if ok:
        return None

    url = await _get_chat_invite_url(client, int(required_chat_id))
    return [[InlineKeyboardButton(f"🎗 Join Channel {step} 🎗", url=url)]]


async def check_and_advance_if_joined(client: Bot, user_id: int) -> bool:
    """
    Called when user clicks Try Again / or before file send.
    If user joined/requested -> advance step and return True
    else False
    """
    required_chat_id, total, step = await get_required_fsub_chat(client, int(user_id))
    if not required_chat_id:
        return True

    ok = await _is_joined_or_requested(client, int(required_chat_id), int(user_id))
    if not ok:
        return False

    await advance_user_step(int(user_id), int(total))
    return True


# ----------------------------
# ✅ JOIN REQUEST EVENT:
# User sends join request -> bot sends pending files in PM
# ❌ DO NOT APPROVE (as you requested)
# ----------------------------
@Bot.on_chat_join_request()
async def on_join_request_handler(client: Bot, join_request: ChatJoinRequest):
    try:
        user_id = int(join_request.from_user.id)
        chat_id = int(join_request.chat.id)

        # ✅ handle ONLY our fsub chats
        required_chats = await _all_required_chats()
        if not required_chats or chat_id not in required_chats:
            return

        # ✅ must have pending saved from quality click
        pending = await get_pending(user_id)
        if not pending:
            return

        required_chat_id = int(pending.get("required_chat_id", 0))
        if required_chat_id != chat_id:
            return

        link_key = pending.get("link_key")
        total = int(pending.get("total", 1))
        if not link_key:
            await clear_pending(user_id)
            return

        # ✅ DO NOT APPROVE ❌
        # Just send files in PM immediately on request event

        files_to_send, *_ = await get_links_for_quality(client, link_key)
        if not files_to_send:
            await clear_pending(user_id)
            return

        for item in files_to_send:
            file_id = item.get("file_id")
            caption = item.get("caption") or ""
            if not file_id:
                continue

            try:
                await client.send_cached_media(
                    chat_id=user_id,
                    file_id=file_id,
                    caption=caption
                )
                await asyncio.sleep(0.3)

            except FloodWait as e:
                await asyncio.sleep(e.value)
                try:
                    await client.send_cached_media(
                        chat_id=user_id,
                        file_id=file_id,
                        caption=caption
                    )
                except Exception as ex:
                    logger.error(f"send_cached_media retry error: {ex}")

            except Exception as ex:
                logger.error(f"send_cached_media error: {ex}")

        # ✅ advance step after sending
        try:
            await advance_user_step(user_id, total)
        except Exception as ex:
            logger.error(f"advance_user_step error: {ex}")

        await clear_pending(user_id)

    except Exception as e:
        logger.error(f"on_join_request_handler error: {e}")
