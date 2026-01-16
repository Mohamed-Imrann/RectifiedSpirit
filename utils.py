# utils.py
import asyncio
import os
from pyrogram.types import Message

# default: auto delete OFF
DEFAULT_AUTO_DELETE_SECONDS = int(os.getenv("AUTO_DELETE_SECONDS", "0"))

async def auto_delete(msg, sec: int | None = None):
    """
    Safe auto delete (no circular import).
    If sec is None -> uses env AUTO_DELETE_SECONDS
    If sec <= 0 -> does nothing
    """
    if sec is None:
        sec = DEFAULT_AUTO_DELETE_SECONDS

    if not sec or sec <= 0:
        return

    await asyncio.sleep(sec)
    try:
        await msg.delete()
    except Exception:
        pass


def get_file_id(msg: Message):
    """
    Returns media object with .file_id and sets .message_type
    """
    if msg.media:
        for message_type in (
            "photo",
            "animation",
            "audio",
            "document",
            "video",
            "video_note",
            "voice",
            "sticker",
        ):
            obj = getattr(msg, message_type, None)
            if obj:
                setattr(obj, "message_type", message_type)
                return obj
    return None
