from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database.series_sql import (
    find_series_by_name,
    list_languages,
    list_seasons,
    list_qualities,
    get_group_id,
    get_files,
)

def kb_rows(items, prefix, sid, lang=None, season=None):
    rows = []
    for x in items:
        data = f"{prefix}|{sid}|{x}"
        if lang is not None:
            data = f"{prefix}|{sid}|{lang}|{x}"
        if season is not None:
            data = f"{prefix}|{sid}|{lang}|{season}|{x}"
        rows.append([InlineKeyboardButton(str(x), callback_data=data)])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"back|{sid}")])
    return InlineKeyboardMarkup(rows)

@Client.on_message(filters.command(["search", "s"]))
async def search_cmd(client: Client, message):
    if len(message.command) < 2:
        return await message.reply_text("Usage:\n/search <series name>")

    q = " ".join(message.command[1:]).strip()
    s = await find_series_by_name(q)

    if not s:
        return await message.reply_text("❌ Series not found.")

    sid, title, poster_file_id, published, tmdb_id, year, rating, genres, overview = s

    langs = await list_languages(sid)
    if not langs:
        return await message.reply_text("❌ No files added for this series yet.")

    text = f"🎬 **{title}**\nChoose language:"
    await message.reply_text(
        text,
        reply_markup=kb_rows(langs, "lang", sid),
        disable_web_page_preview=True,
    )

@Client.on_callback_query()
async def callbacks(client, cq):
    data = cq.data or ""
    parts = data.split("|")

    # back
    if parts[0] == "back":
        sid = int(parts[1])
        langs = await list_languages(sid)
        return await cq.message.edit_text(
            "Choose language:",
            reply_markup=kb_rows(langs, "lang", sid),
        )

    # lang|sid|LANG
    if parts[0] == "lang" and len(parts) == 3:
        sid = int(parts[1]); lang = parts[2]
        seasons = await list_seasons(sid, lang)
        if not seasons:
            return await cq.answer("No seasons found", show_alert=True)

        return await cq.message.edit_text(
            f"Language: **{lang}**\nChoose season:",
            reply_markup=kb_rows(seasons, "season", sid, lang=lang),
        )

    # season|sid|LANG|SEASON
    if parts[0] == "season" and len(parts) == 4:
        sid = int(parts[1]); lang = parts[2]; season = parts[3]
        qualities = await list_qualities(sid, lang, season)
        if not qualities:
            return await cq.answer("No qualities found", show_alert=True)

        return await cq.message.edit_text(
            f"Language: **{lang}**\nSeason: **{season}**\nChoose quality:",
            reply_markup=kb_rows(qualities, "quality", sid, lang=lang, season=season),
        )

    # quality|sid|LANG|SEASON|QUALITY
    if parts[0] == "quality" and len(parts) == 5:
        sid = int(parts[1]); lang = parts[2]; season = parts[3]; quality = parts[4]

        row = await get_group_id(sid, lang, season, quality)
        if not row:
            return await cq.answer("Group not found", show_alert=True)

        group_id = int(row[0])
        files = await get_files(group_id)
        if not files:
            return await cq.answer("No files in this group", show_alert=True)

        await cq.answer("Sending files…", show_alert=False)

        # Send all files (document/video/audio) based on msg_type if you stored it
        sent = 0
        for file_id, caption, msg_type in files:
            cap = caption or ""
            # If msg_type empty, default to document
            t = (msg_type or "document").lower()

            try:
                if t == "video":
                    await cq.message.reply_video(file_id, caption=cap)
                elif t == "audio":
                    await cq.message.reply_audio(file_id, caption=cap)
                else:
                    await cq.message.reply_document(file_id, caption=cap)
                sent += 1
            except Exception:
                # fallback
                await cq.message.reply_document(file_id, caption=cap)
                sent += 1

        return await cq.message.edit_text(
            f"✅ Sent **{sent}** files\nLanguage: **{lang}** | Season: **{season}** | Quality: **{quality}**"
        )

    return await cq.answer("Invalid action", show_alert=True)
