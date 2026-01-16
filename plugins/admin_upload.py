# plugins/admin_upload.py

import asyncio

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from info import ADMINS
from utils import auto_delete, get_file_id
from database.series_sql import (
    upsert_series,
    get_series_by_id,
    set_series_poster,
    ensure_group,
    add_file,
)

SAVE_DELAY = 1.2
WIZ = {}


def kb_newseries():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Language", callback_data="ns:lang"),
         InlineKeyboardButton("📦 Season", callback_data="ns:season")],
        [InlineKeyboardButton("🎞 Quality", callback_data="ns:quality"),
         InlineKeyboardButton("🖼 Poster", callback_data="ns:poster")],
        [InlineKeyboardButton("✅ Start Upload", callback_data="ns:start")],
        [InlineKeyboardButton("❌ Cancel", callback_data="ns:cancel")],
    ])


def wizard_text(st: dict) -> str:
    return (
        "✅ **New Series Setup**\n\n"
        f"Title: `{st.get('title')}`\n"
        f"Language: `{st.get('language') or 'None'}`\n"
        f"Season: `{st.get('season') or 'None'}`\n"
        f"Quality: `{st.get('quality') or 'None'}`\n\n"
        "Set pannitu **Start Upload** click pannunga."
    )


@Client.on_message(filters.command("newseries") & filters.user(ADMINS))
async def newseries_cmd(client, message):
    try:
        ask = await client.ask(message.chat.id, "📌 Series name anuppu:", timeout=120)
    except Exception:
        return await message.reply_text("⏳ Timeout. /newseries again")

    title = (ask.text or "").strip()
    if not title:
        return await message.reply_text("❌ Empty title")

    series_id = await upsert_series(title)
    row = await get_series_by_id(series_id)
    poster = row[2] if row else None

    WIZ[message.from_user.id] = {
        "series_id": series_id,
        "title": title,
        "language": None,
        "season": None,
        "quality": None,
    }

    if poster:
        await message.reply_photo(poster, caption=wizard_text(WIZ[message.from_user.id]), reply_markup=kb_newseries())
    else:
        await message.reply_text(wizard_text(WIZ[message.from_user.id]), reply_markup=kb_newseries())


@Client.on_callback_query(filters.regex(r"^ns:"))
async def ns_cb(client, cq):
    uid = cq.from_user.id
    if uid not in WIZ:
        return await cq.answer("Session expired. /newseries again", show_alert=True)

    st = WIZ[uid]
    data = cq.data.split(":", 1)[1]

    # ❌ Cancel
    if data == "cancel":
        WIZ.pop(uid, None)
        await cq.message.edit_text("❌ Cancelled.")
        return await cq.answer("Cancelled")

    # 🌐 Language -> auto Season -> auto Quality -> back main
    if data == "lang":
        try:
            ask = await client.ask(
                cq.message.chat.id,
                "🌐 Language name anuppu (ex: Multi Audio / Tamil):",
                timeout=120
            )
            st["language"] = (ask.text or "").strip()

            ask2 = await client.ask(
                cq.message.chat.id,
                "📦 Season name anuppu (ex: Season 1 / Season 4 Part 2):",
                timeout=120
            )
            st["season"] = (ask2.text or "").strip()

            ask3 = await client.ask(
                cq.message.chat.id,
                "🎞 Quality anuppu (ex: 720p / 1080p):",
                timeout=120
            )
            st["quality"] = (ask3.text or "").strip()
        except Exception:
            return await cq.answer("⏳ Timeout", show_alert=True)

        await cq.message.edit_text(wizard_text(st), reply_markup=kb_newseries())
        return await cq.answer("Set")

    # 📦 Season -> auto Quality -> back main
    if data == "season":
        if not st.get("language"):
            return await cq.answer("First Language set pannunga", show_alert=True)

        try:
            ask = await client.ask(
                cq.message.chat.id,
                "📦 Season name anuppu:",
                timeout=120
            )
            st["season"] = (ask.text or "").strip()

            ask2 = await client.ask(
                cq.message.chat.id,
                "🎞 Quality anuppu (ex: 720p / 1080p):",
                timeout=120
            )
            st["quality"] = (ask2.text or "").strip()
        except Exception:
            return await cq.answer("⏳ Timeout", show_alert=True)

        await cq.message.edit_text(wizard_text(st), reply_markup=kb_newseries())
        return await cq.answer("Set")

    # 🎞 Quality -> back main
    if data == "quality":
        if not st.get("language") or not st.get("season"):
            return await cq.answer("First Language & Season set pannunga", show_alert=True)

        try:
            ask = await client.ask(
                cq.message.chat.id,
                "🎞 Quality anuppu (ex: 720p / 1080p):",
                timeout=120
            )
            st["quality"] = (ask.text or "").strip()
        except Exception:
            return await cq.answer("⏳ Timeout", show_alert=True)

        await cq.message.edit_text(wizard_text(st), reply_markup=kb_newseries())
        return await cq.answer("Saved")

    # 🖼 Poster
    if data == "poster":
        pmsg = await cq.message.reply_text("📸 Poster photo anuppu (send photo).")
        asyncio.create_task(auto_delete(pmsg, 10))

        pm = await client.listen(cq.message.chat.id)
        if not pm.photo:
            return await cq.answer("Photo illa", show_alert=True)

        await set_series_poster(st["series_id"], pm.photo.file_id)
        ok = await cq.message.reply_text("✅ Poster updated.")
        asyncio.create_task(auto_delete(ok, 10))

        # refresh wizard text (same message)
        try:
            await cq.message.edit_text(wizard_text(st), reply_markup=kb_newseries())
        except Exception:
            pass

        return await cq.answer("Done")

    # ✅ Start Upload
    if data == "start":
        if not st.get("language") or not st.get("season") or not st.get("quality"):
            return await cq.answer("First Language/Season/Quality set pannunga", show_alert=True)

        group_id = await ensure_group(
            st["series_id"], st["language"], st["season"], st["quality"]
        )

        info = await cq.message.reply_text(
            f"📥 Now send files for:\n\n"
            f"**{st['title']}**\n"
            f"Language: `{st['language']}`\n"
            f"Season: `{st['season']}`\n"
            f"Quality: `{st['quality']}`\n\n"
            f"Finish panna `/done`"
        )

        queue = []
        while True:
            m = await client.listen(cq.message.chat.id)
            if (m.text or "").strip().lower() == "/done":
                break
            if not m.media:
                continue
            media = get_file_id(m)
            if not media:
                continue
            queue.append((media.file_id, m.caption or "", getattr(media, "message_type", "")))

        saved = 0
        for file_id, caption, msg_type in queue:
            await add_file(group_id, file_id, caption, msg_type)
            saved += 1
            await asyncio.sleep(SAVE_DELAY)

        done = await cq.message.reply_text(
            f"🎉 Done! **{st['title']}** saved: `{saved}` files ✅"
        )
        asyncio.create_task(auto_delete(done))
        asyncio.create_task(auto_delete(info, 30))

        WIZ.pop(uid, None)
        return await cq.answer("Saved")
