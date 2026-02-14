# plugins/request_forcesub.py
import logging
from pyrogram import enums, filters
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
    True if:
      - user is already member
      - OR user sent Join Request (pending)
    """
    try:
        mem = await client.get_chat_member(int(chat_id), int(user_id))
        logger.info(f"_is_joined_or_requested get_chat_member: chat={chat_id} user={user_id} status={mem.status}")
        return mem.status != enums.ChatMemberStatus.BANNED

    except UserNotParticipant:
        logger.info(f"_is_joined_or_requested: user {user_id} not participant in chat {chat_id} — checking join requests")
        try:
            reqs = await client.get_chat_join_requests(int(chat_id), limit=200)
            logger.info(f"_is_joined_or_requested: join requests fetched count={len(reqs)} for chat={chat_id}")
            for r in reqs:
                if r.from_user and r.from_user.id == int(user_id):
                    logger.info(f"_is_joined_or_requested: found pending join request for user {user_id} in chat {chat_id}")
                    return True
        except Exception as e:
            logger.exception(f"_is_joined_or_requested get_chat_join_requests failed for chat {chat_id}: {e}")
        return False

    except Exception as e:
        logger.exception(f"_is_joined_or_requested unexpected error for chat {chat_id} user {user_id}: {e}")
        return False


async def _get_chat_invite_url(client, chat_id: int) -> str:
    """
    Prefer join-request invite link (creates_join_request=True)
    Fallbacks:
      - export_chat_invite_link if available
      - public username t.me/username
      - generic t.me/
    """
    try:
        cid = int(chat_id)
    except Exception as e:
        logger.exception(f"_get_chat_invite_url invalid chat_id {chat_id}: {e}")
        return "https://t.me/"

    # 1) Try create_chat_invite_link (preferred)
    try:
        logger.info(f"_get_chat_invite_url: trying create_chat_invite_link for chat {cid}")
        invite = await client.create_chat_invite_link(cid, creates_join_request=True)
        if invite and getattr(invite, "invite_link", None):
            logger.info(f"_get_chat_invite_url: create_chat_invite_link succeeded for chat {cid}")
            return invite.invite_link
        else:
            logger.info(f"_get_chat_invite_url: create_chat_invite_link returned no invite_link for chat {cid}")
    except Exception as e:
        logger.exception(f"_get_chat_invite_url create_chat_invite_link failed for chat {cid}: {e}")

    # 2) Try export_chat_invite_link (older API) if available
    try:
        if hasattr(client, "export_chat_invite_link"):
            logger.info(f"_get_chat_invite_url: trying export_chat_invite_link for chat {cid}")
            try:
                link = await client.export_chat_invite_link(cid)
                if link:
                    logger.info(f"_get_chat_invite_url: export_chat_invite_link succeeded for chat {cid}")
                    return link
                else:
                    logger.info(f"_get_chat_invite_url: export_chat_invite_link returned empty for chat {cid}")
            except Exception as e:
                logger.exception(f"_get_chat_invite_url export_chat_invite_link failed for chat {cid}: {e}")
    except Exception:
        pass

    # 3) Fallback to public username link
    try:
        logger.info(f"_get_chat_invite_url: trying get_chat for chat {cid} to check username")
        chat = await client.get_chat(cid)
        username = getattr(chat, "username", None)
        if username:
            logger.info(f"_get_chat_invite_url: found username {username} for chat {cid}")
            return f"https://t.me/{username}"
        else:
            logger.info(f"_get_chat_invite_url: no username for chat {cid}")
    except Exception as e:
        logger.exception(f"_get_chat_invite_url get_chat failed for chat {cid}: {e}")

    # 4) Last resort
    logger.warning(f"_get_chat_invite_url: falling back to generic t.me for chat {cid}")
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
        logger.exception(f"get_fsub_chat1 error: {e}")

    try:
        c2 = await db1.get_fsub_chat2()
        if c2 and c2.get("chat_id"):
            chats.append(int(c2["chat_id"]))
    except Exception as e:
        logger.exception(f"get_fsub_chat2 error: {e}")

    if hasattr(db1, "get_fsub_chat3"):
        try:
            c3 = await db1.get_fsub_chat3()
            if c3 and c3.get("chat_id"):
                chats.append(int(c3["chat_id"]))
        except Exception as e:
            logger.exception(f"get_fsub_chat3 error: {e}")

    # uniq preserve order
    uniq = []
    for x in chats:
        if x not in uniq:
            uniq.append(x)
    logger.info(f"get_all_fsub_chats returning {uniq}")
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
        logger.info("get_required_fsub_chat no fsub chats configured")
        return None, 0, 0

    total = len(chats)

    step = await get_user_step(int(user_id))
    if step < 1 or step > total:
        step = 1
        await set_user_step(int(user_id), 1)

    required_chat_id = chats[step - 1]
    logger.info(f"get_required_fsub_chat user={user_id} step={step}/{total} required_chat_id={required_chat_id}")
    return required_chat_id, total, step


async def create_request_forcesub_buttons(client, user_id: int):
    """
    Returns only one button (join link) if NOT joined/requested required channel.
    """
    required_chat_id, total, step = await get_required_fsub_chat(client, int(user_id))
    if not required_chat_id:
        return None

    ok = await _is_joined_or_requested(client, required_chat_id, int(user_id))
    if ok:
        logger.info(f"create_request_forcesub_buttons: user {user_id} already joined or requested chat {required_chat_id}")
        return None

    url = await _get_chat_invite_url(client, required_chat_id)
    if not url:
        logger.warning(f"create_request_forcesub_buttons: no invite url for chat {required_chat_id}")
        return None

    # ✅ only one button (no "I Joined" callback)
    logger.info(f"create_request_forcesub_buttons: returning button for user {user_id} chat {required_chat_id} url={url}")
    return [[InlineKeyboardButton(f"🎗 Join Channel {step} 🎗", url=url)]]


async def check_and_advance_if_joined(client, user_id: int) -> bool:
    """
    If joined/requested => advance step and return True
    """
    required_chat_id, total, step = await get_required_fsub_chat(client, int(user_id))
    if not required_chat_id:
        return True

    ok = await _is_joined_or_requested(client, required_chat_id, int(user_id))
    if not ok:
        logger.info(f"check_and_advance_if_joined: user {user_id} not joined/requested chat {required_chat_id}")
        return False

    await advance_user_step(int(user_id), total)
    logger.info(f"check_and_advance_if_joined: advanced user {user_id} step (total {total})")
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
    Assumes DB has stored message_ids for files in that chat.
    Example DB API used: db1.get_files_for_chat(chat_id) -> list of {"chat_id":..., "message_id":...}
    """
    try:
        files = []
        if hasattr(db1, "get_files_for_chat"):
            files = await db1.get_files_for_chat(int(chat_id))
        else:
            logger.warning("forward_files_to_user: db1.get_files_for_chat not implemented")
            return False

        if not files:
            logger.info(f"forward_files_to_user: no files configured for chat {chat_id}")
            return False

        for f in files:
            try:
                src_chat = int(f.get("chat_id", chat_id))
                msg_id = int(f.get("message_id"))
                await client.forward_messages(chat_id=int(user_id), from_chat_id=src_chat, message_ids=msg_id)
                logger.info(f"forward_files_to_user: forwarded message {msg_id} from {src_chat} to user {user_id}")
            except Exception as e:
                logger.exception(f"forward_files_to_user: failed to forward message {f} to user {user_id}: {e}")
        return True
    except Exception as e:
        logger.exception(f"forward_files_to_user unexpected error: {e}")
        return False


# ----------------------------
# Optional: /checkjoin command handler
# ----------------------------
# Register this handler in your main bot file. Example (Pyrogram v2):
# app.add_handler(pyrogram.handlers.MessageHandler(cmd_checkjoin, filters=filters.command("checkjoin") & filters.private))
#
# Or using decorator in main where `app` is available:
# @app.on_message(filters.command("checkjoin") & filters.private)
# async def cmd_checkjoin(client, message): ...
#
# The handler below is provided so you can register it as shown above.

async def cmd_checkjoin(client, message):
    """
    User runs /checkjoin to re-check membership and receive files if approved.
    """
    try:
        user_id = message.from_user.id
        required_chat_id, total, step = await get_required_fsub_chat(client, user_id)
        if not required_chat_id:
            await message.reply_text("No subscription channels configured.")
            return

        ok = await _is_joined_or_requested(client, required_chat_id, user_id)
        if not ok:
            await message.reply_text(
                "You are not a member and no pending join request found. Please join the channel and wait for admin approval, then run /checkjoin again."
            )
            return

        # Advance user step
        await advance_user_step(int(user_id), total)

        # Forward files for this chat to user
        forwarded = await forward_files_to_user(client, user_id, required_chat_id)
        if forwarded:
            await message.reply_text("Thanks! Files have been sent to you.")
        else:
            await message.reply_text("You're approved, but no files are configured to send.")
    except Exception as e:
        logger.exception(f"cmd_checkjoin error: {e}")
        try:
            await message.reply_text("Something went wrong while checking. Try again later.")
        except Exception:
            pass
