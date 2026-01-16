import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from info import ADMINS
from utils import get_file_id, auto_delete
from database.series_sql import (
    upsert_series, get_series_by_id, set_series_poster,
    list_languages, list_seasons, list_qualities,
    ensure_group, add_file
)

SAVE_DELAY = 1.2  # bulk save delay


def kb_series_home(series_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Languages", callback_data=f"adm:lang:{series_id}")],
        [InlineKeyboardButton("📸 Poster", callback_data=f"adm:poster:{series_id}")],
    ])


@Client.on_message(filters.command("edit") & filters.user(ADMINS))
async def admin_edit(client: Client, message: Message):
    ask = await client.ask(message.chat.id, "Series name anuppu (edit/create):", timeout=120)
    title = (ask.text or "").strip()
    if not title:
        m = await message.reply_text("❌ Empty.")
        asyncio.create_task(auto_delete(m))
        return

    series_id = await upsert_series(title)
    row = await get_series_by_id(series_id)
    _, title, poster_file_id = row

    text = f"**{title}**\n\nSelect option:"
    if poster_file_id:
        await message.reply_photo(poster_file_id, caption=text, reply_markup=kb_series_home(series_id))
    else:
        await message.reply_text(text, reply_markup=kb_series_home(series_id))


@Client.on_callback_query(filters.regex(r"^adm:poster:(\d+)$"))
async def cb_poster(client, cq):
    series_id = int(cq.matches[0].group(1))
    row = await get_series_by_id(series_id)
    if not row:
        return await cq.answer("Not found", show_alert=True)

    msg = await cq.message.reply_text("📸 Poster photo anuppu (send photo).")
    asyncio.create_task(auto_delete(msg, 10))

    photo_msg = await client.listen(cq.message.chat.id)
    if not photo_msg.photo:
        return await cq.message.reply_text("❌ Photo illa. Try again /edit")

    file_id = photo_msg.photo.file_id
    await set_series_poster(series_id, file_id)
    await cq.message.reply_text("✅ Poster updated.")
    await cq.answer("Done")


@Client.on_callback_query(filters.regex(r"^adm:lang:(\d+)$"))
async def cb_languages(client, cq):
    series_id = int(cq.matches[0].group(1))
    langs = await list_languages(series_id)

    rows = []
    for l in langs[:10]:
        rows.append([InlineKeyboardButton(l, callback_data=f"adm:season:{series_id}:{l}")])

    rows.append([InlineKeyboardButton("➕ Add Language", callback_data=f"adm:addlang:{series_id}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"adm:home:{series_id}")])

    await cq.message.edit_reply_markup(InlineKeyboardMarkup(rows))
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^adm:addlang:(\d+)$"))
async def cb_addlang(client, cq):
    series_id = int(cq.matches[0].group(1))
    ask = await client.ask(cq.message.chat.id, "Language name anuppu (example: Multi Audio / Tamil):", timeout=120)
    lang = (ask.text or "").strip()
    if not lang:
        return await cq.answer("Empty", show_alert=True)

    # create a default season+quality placeholder so language shows up
    await ensure_group(series_id, lang, "Season 1", "720p")
    await cq.message.reply_text(f"✅ Added language: {lang}")
    await cb_languages(client, cq)


@Client.on_callback_query(filters.regex(r"^adm:season:(\d+):(.+)$"))
async def cb_seasons(client, cq):
    series_id = int(cq.matches[0].group(1))
    lang = cq.matches[0].group(2)

    seasons = await list_seasons(series_id, lang)
    rows = [[InlineKeyboardButton(s, callback_data=f"adm:quality:{series_id}:{lang}:{s}")] for s in seasons[:12]]
    rows.append([InlineKeyboardButton("➕ Add Season", callback_data=f"adm:addseason:{series_id}:{lang}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"adm:lang:{series_id}")])

    await cq.message.edit_reply_markup(InlineKeyboardMarkup(rows))
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^adm:addseason:(\d+):(.+)$"))
async def cb_addseason(client, cq):
    series_id = int(cq.matches[0].group(1))
    lang = cq.matches[0].group(2)

    ask = await client.ask(cq.message.chat.id, "Season name anuppu (example: Season 2 / Season 4 Part 2):", timeout=120)
    season = (ask.text or "").strip()
    if not season:
        return await cq.answer("Empty", show_alert=True)

    await ensure_group(series_id, lang, season, "720p")
    await cq.message.reply_text(f"✅ Added season: {season}")
    await cb_seasons(client, cq)


@Client.on_callback_query(filters.regex(r"^adm:quality:(\d+):(.+):(.+)$"))
async def cb_qualities(client, cq):
    series_id = int(cq.matches[0].group(1))
    lang = cq.matches[0].group(2)
    season = cq.matches[0].group(3)

    quals = await list_qualities(series_id, lang, season)
    rows = [[InlineKeyboardButton(q, callback_data=f"adm:upload:{series_id}:{lang}:{season}:{q}")] for q in quals[:12]]
    rows.append([InlineKeyboardButton("➕ Add Quality", callback_data=f"adm:addquality:{series_id}:{lang}:{season}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"adm:season:{series_id}:{lang}")])

    await cq.message.edit_reply_markup(InlineKeyboardMarkup(rows))
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^adm:addquality:(\d+):(.+):(.+)$"))
async def cb_addquality(client, cq):
    series_id = int(cq.matches[0].group(1))
    lang = cq.matches[0].group(2)
    season = cq.matches[0].group(3)

    ask = await client.ask(cq.message.chat.id, "Quality anuppu (example: 720p / 1080p):", timeout=120)
    quality = (ask.text or "").strip()
    if not quality:
        return await cq.answer("Empty", show_alert=True)

    await ensure_group(series_id, lang, season, quality)
    await cq.message.reply_text(f"✅ Added quality: {quality}")
    await cb_qualities(client, cq)


@Client.on_callback_query(filters.regex(r"^adm:upload:(\d+):(.+):(.+):(.+)$"))
async def cb_upload(client, cq):
    series_id = int(cq.matches[0].group(1))
    lang = cq.matches[0].group(2)
    season = cq.matches[0].group(3)
    quality = cq.matches[0].group(4)

    group_id = await ensure_group(series_id, lang, season, quality)

    info = await cq.message.reply_text(
        f"📥 Now send files for:\n\n"
        f"**Language:** {lang}\n**Season:** {season}\n**Quality:** {quality}\n\n"
        f"Finish panna `/done`",
        quote=True
    )
    asyncio.create_task(auto_delete(info, 20))

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

    done = await cq.message.reply_text(f"🎉 Saved `{saved}` files to {lang} / {season} / {quality}")
    asyncio.create_task(auto_delete(done))
    await cq.answer("Saved")


@Client.on_callback_query(filters.regex(r"^adm:home:(\d+)$"))
async def cb_home(client, cq):
    series_id = int(cq.matches[0].group(1))
    row = await get_series_by_id(series_id)
    if not row:
        return await cq.answer("Not found", show_alert=True)
    _, title, poster = row
    text = f"**{title}**\n\nSelect option:"
    await cq.message.edit_text(text, reply_markup=kb_series_home(series_id))
    await cq.answer()
