# plugins/fsub_joinreq_listener.py
import asyncio
import logging
from bot import Bot
from pyrogram.types import ChatJoinRequest
from pyrogram.errors import FloodWait

from database.join_reqs import JoinReqs
from database.request_forcesub_db import get_pending, clear_pending, advance_user_step
from utils import get_links_for_quality

logger = logging.getLogger(__name__)
dbj = JoinReqs()


async def _all_required_chats() -> list:
    chats = []
    try:
        c1 = await dbj.get_fsub_chat1()
        if c1 and c1.get("chat_id"):
            chats.append(int(c1["chat_id"]))
    except:
        pass
    try:
        c2 = await dbj.get_fsub_chat2()
        if c2 and c2.get("chat_id"):
            chats.append(int(c2["chat_id"]))
    except:
        pass
    if hasattr(dbj, "get_fsub_chat3"):
        try:
            c3 = await dbj.get_fsub_chat3()
            if c3 and c3.get("chat_id"):
                chats.append(int(c3["chat_id"]))
        except:
            pass

    uniq = []
    for x in chats:
        if x not in uniq:
            uniq.append(x)
    return uniq


@Bot.on_chat_join_request()
async def on_join_request_handler(client: Bot, join_request: ChatJoinRequest):
    """
    ❌ DO NOT APPROVE
    ✅ If user sent join-request -> send files in PM
    """
    try:
        user_id = int(join_request.from_user.id)
        chat_id = int(join_request.chat.id)

        required_chats = await _all_required_chats()
        if chat_id not in required_chats:
            return

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
                await client.send_cached_media(chat_id=user_id, file_id=file_id, caption=caption)
                await asyncio.sleep(0.3)
            except FloodWait as e:
                await asyncio.sleep(e.value)
                try:
                    await client.send_cached_media(chat_id=user_id, file_id=file_id, caption=caption)
                except Exception as ex:
                    logger.error(f"send_cached_media retry error: {ex}")
            except Exception as ex:
                logger.error(f"send_cached_media error: {ex}")

        # next step
        try:
            await advance_user_step(user_id, total)
        except Exception as ex:
            logger.error(f"advance_user_step error: {ex}")

        await clear_pending(user_id)

    except Exception as e:
        logger.error(f"on_join_request_handler error: {e}")
