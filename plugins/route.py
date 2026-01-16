import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message

from database.series_sql import find_series, get_episodes
from utils import auto_delete

# ✅ RULE: series DB-la irundha dhaan reply, illena silent.
@Client.on_message(filters.text & filters.incoming & ~filters.command(["newseries","listseries","delseries","ping","alive","speedtest"]))
async def user_search(client: Client, message: Message):
    query = (message.text or "").strip()
    if not query:
        return

    row = await find_series(query)
    if not row:
        return  # silent (your requirement)

    series_id, title = row
    eps = await get_episodes(series_id, limit=50)
    if not eps:
        return

    # send header
    header = await message.reply_text(f"✅ **{title}**\n📦 Episodes: `{len(eps)}`")
    asyncio.create_task(auto_delete(header))

    # send episodes (first 50)
    for file_id, caption, _message_type in eps:
        sent = await message.reply_cached_media(file_id, caption=caption or "")
        asyncio.create_task(auto_delete(sent))
