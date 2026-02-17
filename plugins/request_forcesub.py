# plugins/request_forcesub.py
import logging
from pyrogram import enums
from pyrogram.types import InlineKeyboardButton
from pyrogram.errors import UserNotParticipant

from database.join_reqs import JoinReqs
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
async def _is_joined_or_requested(client, chat_id: int, user_id: int) -> bool:
    """
    ✅ True if:
      - user is already member
      - OR user sent Join Request (pending)
    """
    try:
        mem = await client.get_chat_member(int(chat_id), int(user_id))
        return mem.status != enums.ChatMemberStatus.BANNED

    except UserNotParticipant:
        # ✅ If join-request pending => allow
        try:
            reqs = await client.get_chat_join_requests(int(chat_id), limit=200)
            for r in reqs:
                if r.from_user and r.from_user.id == int(user_id):
                    return True
        except Exception:
            pass
        return False

    except Exception as e:
        logger.error(f"_is_joined_or_requested error: {e}")
        return False


async def _get_chat_invite_url(client, chat_id: int) -> str:
    """
    ✅ Prefer join-request invite link (creates_join_request=True)
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


def _get_bot_deeplink(client, start_payload: str = "checksub") -> str:
    """
    ✅ Group message button click -> Bot PM open aaganum na
    URL deep-link must:
      https://t.me/<bot_username>?start=<payload>
    """
    try:
        bot_username = getattr(getattr(client, "me", None), "username", None)
        if bot_username:
            return f"https://t.me/{bot_username}?start={start_payload}"
    except Exception:
        pass
    return "https://t.me/"


async def get_all_fsub_chats() -> list:
    """
    Reads fsub chats from JoinReqs DB (chat1/chat2/chat3).
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

    # uniq preserve order
    uniq = []
    for x in chats:
        if x not in uniq:
            uniq.append(x)
    return uniq


# ----------------------------
# Public API
# ----------------------------
async def get_required_fsub_chat(client, user_id: int):
    """
    Returns (required_chat_id, total, step)
    ✅ Auto-skip steps that user already joined/requested
    """
    chats = await get_all_fsub_chats()
    if not chats:
        return None, 0, 0

    total = len(chats)

    step = await get_user_step(int(user_id))
    if step < 1 or step > total:
        step = 1
        await set_user_step(int(user_id), 1)

    # ✅ AUTO SKIP: if already joined/requested -> move forward
    while step <= total:
        required_chat_id = chats[step - 1]
        ok = await _is_joined_or_requested(client, required_chat_id, int(user_id))

        if ok:
            # already satisfied this step, advance
            step += 1
            await set_user_step(int(user_id), step if step <= total else total)
            continue

        # not joined -> this is required
        return required_chat_id, total, step

    # all done
    return None, total, total

async def create_request_forcesub_buttons(client, user_id: int):
    """
    Returns buttons if NOT joined/requested required channel.
    ✅ NOW: Adds "Open Bot" deep link so group click redirects to bot PM.
    """
    required_chat_id, total, step = await get_required_fsub_chat(client, int(user_id))
    if not required_chat_id:
        return None

    ok = await _is_joined_or_requested(client, required_chat_id, int(user_id))
    if ok:
        return None

    join_url = await _get_chat_invite_url(client, required_chat_id)

    # ✅ Deep link payload includes step so you can show which channel step pending
    # Example: /start checksub_s1
    bot_pm_url = _get_bot_deeplink(client, start_payload=f"checksub_s{step}")

    # ✅ Buttons (URL only) -> group-la click pannina PM open aagum
    return [
        [InlineKeyboardButton(f"🔔 Join Channel {step} ", url=join_url)],
        [InlineKeyboardButton("✅ Open Bot (After Join)", url=bot_pm_url)],
    ]


async def check_and_advance_if_joined(client, user_id: int) -> bool:
    """
    ✅ If joined/requested => advance step and return True
    """
    required_chat_id, total, step = await get_required_fsub_chat(client, int(user_id))
    if not required_chat_id:
        return True

    ok = await _is_joined_or_requested(client, required_chat_id, int(user_id))
    if not ok:
        return False

    await advance_user_step(int(user_id), total)
    return True


# Backward compat
async def advance_user_fsub_step(user_id: int, total: int = 3):
    # not used now
    await advance_user_step(int(user_id), int(total))
