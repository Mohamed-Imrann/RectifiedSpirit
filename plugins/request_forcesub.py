# plugins/request_forcesub.py
import logging
from pyrogram import enums
from pyrogram.types import InlineKeyboardButton
from pyrogram.errors import UserNotParticipant

from database.join_reqs import JoinReqs
from database.request_forcesub_db import get_user_step, set_user_step

logger = logging.getLogger(__name__)
dbj = JoinReqs()


async def _all_required_chats() -> list:
    chats = []
    try:
        c1 = await dbj.get_fsub_chat1()
        if c1 and c1.get("chat_id"):
            chats.append(int(c1["chat_id"]))
    except Exception as e:
        logger.error(f"get_fsub_chat1 error: {e}")

    try:
        c2 = await dbj.get_fsub_chat2()
        if c2 and c2.get("chat_id"):
            chats.append(int(c2["chat_id"]))
    except Exception as e:
        logger.error(f"get_fsub_chat2 error: {e}")

    if hasattr(dbj, "get_fsub_chat3"):
        try:
            c3 = await dbj.get_fsub_chat3()
            if c3 and c3.get("chat_id"):
                chats.append(int(c3["chat_id"]))
        except Exception as e:
            logger.error(f"get_fsub_chat3 error: {e}")

    uniq = []
    for x in chats:
        if x not in uniq:
            uniq.append(x)
    return uniq


async def _get_invite_url(client, chat_id: int) -> str:
    # create join-request link if possible
    try:
        inv = await client.create_chat_invite_link(int(chat_id), creates_join_request=True)
        if inv and inv.invite_link:
            return inv.invite_link
    except Exception:
        pass

    # fallback username link
    try:
        chat = await client.get_chat(int(chat_id))
        if chat and getattr(chat, "username", None):
            return f"https://t.me/{chat.username}"
    except Exception:
        pass

    return "https://t.me/"


from pyrogram import enums
from pyrogram.errors import UserNotParticipant, ChatAdminRequired

async def _is_joined(client, chat_id: int, user_id: int) -> bool:
    try:
        mem = await client.get_chat_member(int(chat_id), int(user_id))
        return mem.status in (
            enums.ChatMemberStatus.MEMBER,
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER,
        )

    except UserNotParticipant:
        # ✅ join-request pending check
        try:
            reqs = await client.get_chat_join_requests(int(chat_id), limit=200)
            return any(int(r.user.id) == int(user_id) for r in reqs)
        except ChatAdminRequired:
            return False
        except Exception:
            return False
            
async def get_required_fsub_chat(client, user_id: int):
    """
    Returns (required_chat_id, total, step)
    """
    chats = await _all_required_chats()
    if not chats:
        return None, 0, 0

    total = len(chats)

    step = await get_user_step(int(user_id))
    if step < 1 or step > total:
        step = 1
        await set_user_step(int(user_id), 1)

    required_chat_id = chats[step - 1]
    return required_chat_id, total, step


async def create_request_forcesub_buttons(client, user_id: int):
    """
    If not joined required chat -> return one join button
    else -> None
    """
    required_chat_id, total, step = await get_required_fsub_chat(client, int(user_id))
    if not required_chat_id:
        return None

    joined = await _is_joined(client, required_chat_id, int(user_id))
    if joined:
        return None

    url = await _get_invite_url(client, required_chat_id)
    return [[InlineKeyboardButton(f"🎗 Join Channel {step} 🎗", url=url)]]
