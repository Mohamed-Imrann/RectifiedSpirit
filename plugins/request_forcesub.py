# plugins/request_forcesub.py
import logging
from pyrogram import enums
from pyrogram.types import InlineKeyboardButton
from pyrogram.errors import UserNotParticipant

from database.join_reqs import JoinReqs
from database.request_forcesub_db import get_user_step, set_user_step, advance_user_step

logger = logging.getLogger(__name__)
db1 = JoinReqs()


async def _is_joined(client, chat_id: int, user_id: int) -> bool:
    """
    ✅ REAL join check:
    MEMBER/ADMIN/OWNER/RESTRICTED => joined
    LEFT/BANNED => not joined
    """
    try:
        mem = await client.get_chat_member(int(chat_id), int(user_id))

        if mem.status in (
            enums.ChatMemberStatus.MEMBER,
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER,
            enums.ChatMemberStatus.RESTRICTED,
        ):
            return True

        return False

    except UserNotParticipant:
        return False
    except Exception as e:
        logger.error(f"_is_joined error chat={chat_id} user={user_id}: {e}")
        return False


async def _get_chat_invite_url(client, chat_id: int) -> str:
    """
    invite link (needs admin) இல்லனா username link try பண்ணும்
    """
    try:
        invite = await client.create_chat_invite_link(int(chat_id))
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


async def get_all_fsub_chats() -> list:
    """
    Reads chats from JoinReqs DB: chat1/chat2/chat3
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

    if hasattr(db1, "get_fsub_chat3"):
        try:
            c3 = await db1.get_fsub_chat3()
            if c3 and c3.get("chat_id"):
                chats.append(int(c3["chat_id"]))
        except Exception as e:
            logger.error(f"get_fsub_chat3 error: {e}")

    # unique preserve order
    uniq = []
    for x in chats:
        if x not in uniq:
            uniq.append(x)

    return uniq


async def get_required_fsub_chat(client, user_id: int):
    """
    returns (required_chat_id, total, step)
    """
    chats = await get_all_fsub_chats()
    if not chats:
        return None, 0, 0

    total = len(chats)

    step = await get_user_step(int(user_id))
    if step < 1 or step > total:
        step = 1
        await set_user_step(int(user_id), 1)

    return chats[step - 1], total, step


async def create_request_forcesub_buttons(client, user_id: int):
    """
    ✅ ONLY ONE CHANNEL BUTTON.
    joined இல்லைனா => [[button]]
    joined ஆகி இருந்தா => None
    """
    required_chat_id, total, step = await get_required_fsub_chat(client, int(user_id))
    if not required_chat_id:
        return None

    if await _is_joined(client, required_chat_id, int(user_id)):
        return None

    url = await _get_chat_invite_url(client, required_chat_id)
    return [[InlineKeyboardButton(f"🎗 Join Channel {step} 🎗", url=url)]]


async def check_and_advance_if_joined(client, user_id: int) -> bool:
    """
    ✅ Use inside 'b:' handler BEFORE sending files
    - Not joined => False
    - Joined => advance step for NEXT request and True
    """
    required_chat_id, total, step = await get_required_fsub_chat(client, int(user_id))
    if not required_chat_id:
        return True  # no fsub configured

    joined = await _is_joined(client, required_chat_id, int(user_id))
    if not joined:
        return False

    await advance_user_step(int(user_id), total)
    return True
