import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message

from info import ADMINS
from utils import get_file_id, auto_delete
from database.series_sql import upsert_series, add_episode

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

    intro = await message.reply_text(
        f"✅ Series created: **{title}**\n\n"
        f"Now **episodes/files** send/forward pannunga.\n"
        f"Stop panna `/done` anuppu.\n\n"
        f"💡 Tip: One by one forward panna best.",
        quote=True
    )
    asyncio.create_task(auto_delete(intro))

    count = 0

    while True:
        try:
            m = await client.ask(
                chat_id=message.chat.id,
                text="📥 Next file anuppu (or type /done)",
                filters=(filters.media | filters.command("done")),
                timeout=600
            )
        except asyncio.TimeoutError:
            t = await message.reply_text("⏳ Timeout. Again /newseries start pannunga.")
            asyncio.create_task(auto_delete(t))
            return

        if (m.text or "").strip().lower() == "/done":
            done = await message.reply_text(f"🎉 Done! **{title}** total files added: `{count}`")
            asyncio.create_task(auto_delete(done))
            break

        media = get_file_id(m)
        if not media:
            # very rare fallback
            if m.document:
                media = m.document
                media.message_type = "document"
            elif m.video:
                media = m.video
                media.message_type = "video"
            else:
                continue

        await add_episode(series_id, media.file_id, m.caption or "", getattr(media, "message_type", ""))
        count += 1

        ack = await message.reply_text(f"✅ Saved file #{count}")
        asyncio.create_task(auto_delete(ack, 10))
