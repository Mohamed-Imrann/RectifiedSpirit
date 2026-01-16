import asyncio
from pyrogram.types import Message
from info import AUTO_DELETE_SECONDS

async def auto_delete(msg, sec: int = AUTO_DELETE_SECONDS):
    if not sec or sec <= 0:
        return
    await asyncio.sleep(sec)
    try:
        await msg.delete()
    except:
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
