from pyrogram import Client, filters
from utils import resolve_pending

@Client.on_message(filters.incoming & ~filters.service)
async def _resolve_waiters(_, message):
    try:
        uid = message.from_user.id if message.from_user else 0
        if not uid:
            return
        resolve_pending(message.chat.id, uid, message)
    except Exception:
        pass
