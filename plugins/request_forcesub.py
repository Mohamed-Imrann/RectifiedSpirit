# plugins/request_forcesub.py
import logging
import time
from pyrogram import enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import UserNotParticipant, PeerIdInvalid

from database.join_reqs import JoinReqs
from database.request_forcesub_db import (
    get_user_step,
    set_user_step,
    advance_user_step,
    set_pending,
    get_pending,
    clear_pending,
)

logger = logging.getLogger(__name__)
db1 = JoinReqs()


# ----------------------------
# Safe PM helper
# ----------------------------
async def safe_send_pm(client, user_id: int, text: str, reply_markup=None):
    """
    Send a private message to a user safely.
    Returns True if sent, False otherwise.
    Handles PeerIdInvalid and logs other exceptions.
    """
    try:
        await client.send_message(chat_id=int(user_id), text=text, reply_markup=reply_markup)
        logger.info(f"safe_send_pm: message sent to {user_id}")
        return True
    except PeerIdInvalid as e:
        logger.warning(f"safe_send_pm: peer invalid for user {user_id}: {e}")
        return False
    except Exception as e:
        logger.exception(f"safe_send_pm unexpected error for user {user_id}: {e}")
        return False


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
            # requires bot to be admin in the chat to fetch join requests
            reqs = await client.get_chat_join_requests(int(chat_id), limit=200)
            for r in reqs:
                if r.from_user and r.from_user.id == int(user_id):
                    return True
        except Exception:
            # ignore errors (likely bot not admin)
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
        cid = int(chat_id)
    except Exception as e:
        logger.exception(f"_get_chat_invite_url invalid chat_id {chat_id}: {e}")
        return "https://t.me/"

    # 1) Try create_chat_invite_link (preferred)
    try:
        invite = await client.create_chat_invite_link(cid, creates_join_request=True)
        if invite and getattr(invite, "invite_link", None):
            return invite.invite_link
    except Exception:
        # ignore and fallback
        pass

    # 2) Try export_chat_invite_link if available
    try:
        if hasattr(client, "export_chat_invite_link"):
            try:
                link = await client.export_chat_invite_link(cid)
                if link:
                    return link
            except Exception:
                pass
    except Exception:
        pass

    # 3) Fallback to public username link
    try:
        chat = await client.get_chat(cid)
        if chat and getattr(chat, "username", None):
            return f"https://t.me/{chat.username}"
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
    """
    chats = await get_all_fsub_chats()
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
    Returns buttons if NOT joined/requested required channel.
    Also sets a pending record in DB so the bot can auto-send later if desired.
    """
    required_chat_id, total, step = await get_required_fsub_chat(client, int(user_id))
    if not required_chat_id:
        return None

    ok = await _is_joined_or_requested(client, required_chat_id, int(user_id))
    if ok:
        return None

    url = await _get_chat_invite_url(client, required_chat_id)

    # create a link_key and set pending so bot can later auto-send when approved
    try:
        link_key = f"fsub:{int(user_id)}:{int(required_chat_id)}:{int(time.time())}"
        await set_pending(int(user_id), link_key, int(required_chat_id), int(step), int(total))
    except Exception as e:
        logger.error(f"create_request_forcesub_buttons set_pending error: {e}")

    # ✅ only one button
    return [[InlineKeyboardButton(f"🎗 Join Channel {step} 🎗", url=url)]]


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

    # clear pending if exists
    try:
        pending = await get_pending(int(user_id))
        if pending:
            await clear_pending(int(user_id))
    except Exception:
        pass

    return True


# Backward compat
async def advance_user_fsub_step(user_id: int, total: int = 3):
    # not used now
    await advance_user_step(int(user_id), int(total))


# ----------------------------
# Forwarding files after approval
# ----------------------------
async def forward_files_to_user(client, user_id: int, chat_id: int):
    """
    Forward files/messages from the fsub chat to the user.
    Assumes JoinReqs (db1) has a method get_files_for_chat(chat_id) that returns
    a list of {"chat_id": <id>, "message_id": <msg_id>}.
    If your JoinReqs uses different method names, adapt accordingly.
    """
    try:
        files = []
        if hasattr(db1, "get_files_for_chat"):
            files = await db1.get_files_for_chat(int(chat_id))
        else:
            logger.error("forward_files_to_user: db1.get_files_for_chat not implemented")
            return False

        if not files:
            logger.info(f"forward_files_to_user: no files configured for chat {chat_id}")
            return False

        for f in files:
            try:
                src_chat = int(f.get("chat_id", chat_id))
                msg_id = int(f.get("message_id"))
                await client.forward_messages(chat_id=int(user_id), from_chat_id=src_chat, message_ids=msg_id)
            except Exception as e:
                logger.error(f"forward_files_to_user: failed to forward message {f} to user {user_id}: {e}")
        return True
    except Exception as e:
        logger.error(f"forward_files_to_user unexpected error: {e}")
        return False


# ----------------------------
# Helper: process pending entries (optional)
# ----------------------------
async def process_pending_for_user(client, user_id: int):
    """
    If a pending record exists for user, re-check membership and auto-send files.
    Call this from your main bot when you detect user activity (e.g., on /start or any command),
    or run a periodic task to scan pending_fsub collection and attempt delivery.
    """
    try:
        pending = await get_pending(int(user_id))
        if not pending:
            return False

        required_chat_id = int(pending.get("required_chat_id"))
        # re-check membership
        ok = await _is_joined_or_requested(client, required_chat_id, int(user_id))
        if not ok:
            return False

        # advance step
        total = int(pending.get("total", 1))
        try:
            await advance_user_step(int(user_id), int(total))
        except Exception as e:
            logger.error(f"process_pending_for_user advance error: {e}")

        # forward files
        forwarded = await forward_files_to_user(client, user_id, required_chat_id)

        # clear pending
        try:
            await clear_pending(int(user_id))
        except Exception as e:
            logger.error(f"process_pending_for_user clear_pending error: {e}")

        return forwarded
    except Exception as e:
        logger.error(f"process_pending_for_user unexpected error: {e}")
        return False


# ----------------------------
# Convenience: send PM with join button (use only when user has started the bot)
# ----------------------------
async def send_fsub_pm_with_button(client, user_id: int):
    """
    Create join button and attempt to send PM using safe_send_pm.
    Use this from a user-initiated handler (e.g., /start) to avoid PEER_ID_INVALID.
    """
    try:
        buttons = await create_request_forcesub_buttons(client, user_id)
        if not buttons:
            return False

        markup = InlineKeyboardMarkup(buttons)
        text = "Please join the channel to continue. After join-request, files will be delivered automatically."
        sent = await safe_send_pm(client, user_id, text, reply_markup=markup)
        return sent
    except Exception as e:
        logger.error(f"send_fsub_pm_with_button error: {e}")
        return False
