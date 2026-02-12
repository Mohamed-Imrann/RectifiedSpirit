# plugins/request_forcesub.py
import logging
from pyrogram import enums
from pyrogram.types import InlineKeyboardButton
from pyrogram.errors import UserNotParticipant

from database.join_reqs import JoinReqs

logger = logging.getLogger(__name__)

db1 = JoinReqs()

async def _is_joined(client, chat_id: int, user_id: int) -> bool:
    try:
        mem = await client.get_chat_member(chat_id, user_id)
        return mem.status != enums.ChatMemberStatus.BANNED
    except UserNotParticipant:
        return False
    except Exception as e:
        logger.error(f"_is_joined error: {e}")
        return False

async def get_required_fsub_chat(client, user_id: int):
    """
    Returns (chat_id, total_chats) based on user's step.
    """
    chats = await db1.get_all_fsub_chats()
    if not chats:
        return None, 0

    step = await db1.get_user_step(user_id)  # 1..N
    total = len(chats)

    # clamp
    if step > total:
        step = 1
        await db1.set_user_step(user_id, 1)

    required_chat_id = chats[step - 1]
    return required_chat_id, total

async def create_request_forcesub_buttons(client, user_id: int):
    """
    ✅ ONLY ONE CHANNEL BUTTON returns.
    If user not joined required channel -> return [[button]]
    else -> return None
    """
    required_chat_id, total = await get_required_fsub_chat(client, user_id)
    if not required_chat_id:
        return None

    joined = await _is_joined(client, required_chat_id, user_id)
    if joined:
        return None

    try:
        invite = await client.create_chat_invite_link(required_chat_id)
        url = invite.invite_link
    except Exception:
        # public channel username might work without invite link
        url = f"https://t.me/c/{str(required_chat_id).replace('-100','')}/1"

    # ✅ only one button
    return [[InlineKeyboardButton("🎗 Join Channel 🎗", url=url)]]

async def advance_user_fsub_step(user_id: int, total: int):
    await db1.advance_user_step(user_id, total)
