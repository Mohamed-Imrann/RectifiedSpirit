# plugins/request_forcesub.py
import logging
from pyrogram import enums
from pyrogram.types import InlineKeyboardButton
from pyrogram.errors import UserNotParticipant

from database.join_reqs import JoinReqs

# ✅ user-step DB (your new sequential db file)
from database.request_forcesub_db import (
    get_user_step,
    set_user_step,
    advance_user_step,
)

logger = logging.getLogger(__name__)
db1 = JoinReqs()


# ----------------------------
# Internal helpers
# ----------------------------
async def _is_joined(client, chat_id: int, user_id: int) -> bool:
    try:
        mem = await client.get_chat_member(int(chat_id), int(user_id))
        # if banned => treat not joined
        return mem.status != enums.ChatMemberStatus.BANNED
    except UserNotParticipant:
        return False
    except Exception as e:
        logger.error(f"_is_joined error: {e}")
        return False


async def _get_chat_invite_url(client, chat_id: int) -> str:
    """
    Try invite link (needs admin). If fails, try public @username link.
    """
    # 1) invite link
    try:
        invite = await client.create_chat_invite_link(int(chat_id))
        if invite and invite.invite_link:
            return invite.invite_link
    except Exception:
        pass

    # 2) username link
    try:
        chat = await client.get_chat(int(chat_id))
        if chat and getattr(chat, "username", None):
            return f"https://t.me/{chat.username}"
    except Exception:
        pass

    # 3) last fallback (private channel can't be opened without invite anyway)
    return "https://t.me/"


async def get_all_fsub_chats() -> list:
    """
    Reads fsub chats from JoinReqs DB (chat1/chat2/chat3).
    Returns list like: [chat1, chat2, chat3] (only those set)
    """
    chats = []

    try:
        c1 = await db1.get_fsub_chat1()
        if c1 and c1.get("chat_id"):
            chats.append(int(c1["chat_id"]))
    except Exception as e:
        logger.error(f"get_fsub_chat1 error: {e}")

    try:
        c2 = await db1.get_fsub_chat2()
        if c2 and c2.get("chat_id"):
            chats.append(int(c2["chat_id"]))
    except Exception as e:
        logger.error(f"get_fsub_chat2 error: {e}")

    # chat3 optional
    if hasattr(db1, "get_fsub_chat3"):
        try:
            c3 = await db1.get_fsub_chat3()
            if c3 and c3.get("chat_id"):
                chats.append(int(c3["chat_id"]))
        except Exception as e:
            logger.error(f"get_fsub_chat3 error: {e}")

    # remove duplicates while preserving order
    uniq = []
    for x in chats:
        if x not in uniq:
            uniq.append(x)

    return uniq


# ----------------------------
# Public API (used by start + pmfilter)
# ----------------------------
async def get_required_fsub_chat(client, user_id: int):
    """
    Returns (required_chat_id, total_chats, step)
    step = 1..total
    """
    chats = await get_all_fsub_chats()
    if not chats:
        return None, 0, 0

    total = len(chats)

    step = await get_user_step(int(user_id))  # from fsub_state
    if step < 1 or step > total:
        step = 1
        await set_user_step(int(user_id), 1)

    required_chat_id = chats[step - 1]
    return required_chat_id, total, step


async def create_request_forcesub_buttons(*args, **kwargs):
    """
    ✅ ONLY ONE CHANNEL button.

    Supports both calls:
      1) await create_request_forcesub_buttons(client, user_id)
      2) await create_request_forcesub_buttons(user_id)   (client passed via kwargs if available)
    Returns:
      - [[InlineKeyboardButton]] if NOT joined required channel
      - None if joined OR no fsub configured
    """
    client = None
    user_id = None

    if len(args) == 2:
        client, user_id = args[0], int(args[1])
    elif len(args) == 1:
        user_id = int(args[0])
        client = kwargs.get("client", None)
    else:
        client = kwargs.get("client", None)
        user_id = int(kwargs.get("user_id"))

    if client is None or user_id is None:
        # can't check join without client
        return None

    required_chat_id, total, step = await get_required_fsub_chat(client, user_id)
    if not required_chat_id:
        return None

    joined = await _is_joined(client, required_chat_id, user_id)
    if joined:
        return None

    url = await _get_chat_invite_url(client, required_chat_id)

    # ✅ only one button
    btn = [[InlineKeyboardButton(f"🎗 Join Channel {step} 🎗", url=url)]]
    return btn


async def check_and_advance_if_joined(client, user_id: int) -> bool:
    """
    Use this inside 'b:' handler BEFORE sending files.
    - If not joined => returns False (show fsub button)
    - If joined => advances user step and returns True
    """
    required_chat_id, total, step = await get_required_fsub_chat(client, int(user_id))
    if not required_chat_id:
        return True  # no fsub setup

    joined = await _is_joined(client, required_chat_id, int(user_id))
    if not joined:
        return False

    # ✅ joined -> next step for NEXT request
    await advance_user_step(int(user_id))
    return True


# Backward compatible name (your pmfilter imports this)
async def advance_user_fsub_step(user_id: int, total: int = 3):
    # total param not needed anymore; kept for compatibility
    await advance_user_step(int(user_id))
