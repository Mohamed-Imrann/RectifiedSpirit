# plugins/userbot_sync.py
import asyncio
from typing import List, Tuple

from pyrogram import Client
from info import SOURCE_CHANNEL_ID
from utils import get_file_id


async def fetch_files_from_channel_range(
    user: Client,
    first_msg_id: int,
    last_msg_id: int
) -> List[Tuple[str, str, str]]:
    """
    Uses USER session to read YOUR channel messages in [first_msg_id..last_msg_id].
    Returns list of (file_id, caption, msg_type)
    """
    if last_msg_id < first_msg_id:
        return []

    results = []
    ids = list(range(first_msg_id, last_msg_id + 1))

    # chunked (Telegram limit friendly)
    CHUNK = 100
    for i in range(0, len(ids), CHUNK):
        chunk = ids[i:i + CHUNK]
        msgs = await user.get_messages(SOURCE_CHANNEL_ID, chunk)

        # pyrogram returns list aligned; some can be None
        for m in msgs:
            if not m:
                continue
            if not m.media:
                continue
            media = get_file_id(m)
            if not media:
                continue
            results.append((media.file_id, m.caption or "", getattr(media, "message_type", "")))

        await asyncio.sleep(0.2)

    return results
