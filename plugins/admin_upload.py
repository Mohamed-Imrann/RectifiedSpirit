import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message

from info import ADMINS
from utils import get_file_id, auto_delete
from database.series_sql import upsert_series, add_episode, list_series, delete_series


@Client.on_message(filters.command("newseries") & filters.user(ADMINS))
async def newseries(client: Client, message: Message):
    ask = await client.ask(
        chat_id=message.chat.id,
        text="📌 Series name anuppu (example: Breaking Bad)",
        timeout=120
    )
    title = (ask.text or "").strip()
    if not title:
        m = await message.reply_text("❌ Series name empty.")
        asyncio.create_task(auto_delete(m))
        return

    series_id = await upsert_series(title)

    msg = await message.reply_text(
        f"✅ Series created: **{title}**\n\n"
        f"Now episodes/files send/forward pannunga.\n"
        f"Finish panna `/done` anuppu.",
        quote=True
    )
    asyncio.create_task(auto_delete(msg))

    count = 0
    while True:
        m = await client.listen(message.chat.id)

        if m.text and m.text.strip().lower() == "/done":
            done = await message.reply_text(f"🎉 Done! **{title}** total files added: `{count}`")
            asyncio.create_task(auto_delete(done))
            break

        media = get_file_id(m)
        if not media:
            continue

        await add_episode(series_id, media.file_id, m.caption or "", getattr(media, "message_type", ""))
        count += 1

        if count % 10 == 0:
            p = await message.reply_text(f"➕ Added `{count}` files so far…")
            asyncio.create_task(auto_delete(p))


@Client.on_message(filters.command("listseries") & filters.user(ADMINS))
async def cmd_listseries(client: Client, message: Message):
    rows = await list_series()
    if not rows:
        m = await message.reply_text("No series found.")
        asyncio.create_task(auto_delete(m))
        return

    txt = "📚 **Series List**\n\n" + "\n".join([f"• {r[0]}" for r in rows])
    m = await message.reply_text(txt)
    asyncio.create_task(auto_delete(m))


@Client.on_message(filters.command("delseries") & filters.user(ADMINS))
async def cmd_delseries(client: Client, message: Message):
    if len(message.command) < 2:
        m = await message.reply_text("Usage: `/delseries Series Name`", quote=True)
        asyncio.create_task(auto_delete(m))
        return

    title = message.text.split(None, 1)[1]
    n = await delete_series(title)
    m = await message.reply_text("🗑 Deleted." if n else "❌ Series not found.")
    asyncio.create_task(auto_delete(m))
