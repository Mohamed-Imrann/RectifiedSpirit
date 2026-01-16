import asyncio
from urllib.parse import quote, unquote

from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from info import ADMINS
from utils import get_file_id, auto_delete
from database.series_sql import (
    upsert_series,
    get_series_by_id,
    set_series_poster,
    list_languages,
    list_seasons,
    list_qualities,
    ensure_group,
    get_group_id,
    add_file,
)

SAVE_DELAY = 1.2  # seconds


# ---------------- helpers ----------------

def q(s: str) -> str:
    return quote(s, safe="")

def uq(s: str) -> str:
    return unquote(s)

def series_home_kb(sid: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Languages", callback_data=f"ui:langs:{sid}")],
        [InlineKeyboardButton("🖼 Poster", callback_data=f"ui:poster:{sid}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="ui:cancel")]
    ])

# ---------------- /newseries ----------------

@Client.on_message(filters.command("newseries") & filters.user(ADMINS))
async def newseries(client, message):
    ask = await client.ask(
        message.chat.id,
        "📌 Send series name:",
        timeout=120
    )
    title = (ask.text or "").strip()
    if not title:
        return await message.reply_text("❌ Empty name")

    sid = await upsert_series(title)
    row = await get_series_by_id(sid)
    _, title, poster = row

    text = f"**Series:** {title}\n\nChoose option:"
    if poster:
        await message.reply_photo(
            poster,
            caption=text,
            reply_markup=series_home_kb(sid)
        )
    else:
        await message.reply_text(
            text,
            reply_markup=series_home_kb(sid)
        )

# ---------------- home actions ----------------

@Client.on_callback_query(filters.regex(r"^ui:cancel$"))
async def ui_cancel(_, cq):
    await cq.message.edit_text("❌ Cancelled")
    await cq.answer()

@Client.on_callback_query(filters.regex(r"^ui:poster:(\d+)$"))
async def ui_series_poster(client, cq):
    sid = int(cq.matches[0].group(1))
    msg = await cq.message.reply_text("🖼 Send poster photo")
    asyncio.create_task(auto_delete(msg, 10))

    p = await client.listen(cq.message.chat.id)
    if not p.photo:
        return await cq.answer("Photo only", show_alert=True)

    await set_series_poster(sid, p.photo.file_id)
    await cq.message.reply_text("✅ Poster updated")
    await cq.answer()

# ---------------- languages ----------------

@Client.on_callback_query(filters.regex(r"^ui:langs:(\d+)$"))
async def ui_languages(_, cq):
    sid = int(cq.matches[0].group(1))
    langs = await list_languages(sid)

    rows = []
    for l in langs:
        rows.append([
            InlineKeyboardButton(l, callback_data=f"ui:lang:{sid}:{q(l)}"),
            InlineKeyboardButton("🗑", callback_data=f"ui:del_lang:{sid}:{q(l)}")
        ])

    rows.append([InlineKeyboardButton("➕ Add First Item", callback_data=f"ui:add_lang:{sid}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"ui:home:{sid}")])

    await cq.message.edit_reply_markup(InlineKeyboardMarkup(rows))
    await cq.answer()

@Client.on_callback_query(filters.regex(r"^ui:add_lang:(\d+)$"))
async def ui_add_lang(client, cq):
    sid = int(cq.matches[0].group(1))
    ask = await client.ask(cq.message.chat.id, "Send language name:", timeout=120)
    lang = (ask.text or "").strip()
    if not lang:
        return await cq.answer("Empty", show_alert=True)

    await ensure_group(sid, lang, "season 1", "720p")
    await cq.message.reply_text("Language Added")
    await ui_languages(client, cq)

@Client.on_callback_query(filters.regex(r"^ui:del_lang:(\d+):(.+)$"))
async def ui_del_lang(_, cq):
    await cq.message.reply_text("Language deleted successfully.")
    await cq.answer()

@Client.on_callback_query(filters.regex(r"^ui:home:(\d+)$"))
async def ui_back_home(_, cq):
    sid = int(cq.matches[0].group(1))
    row = await get_series_by_id(sid)
    _, title, poster = row
    text = f"**Series:** {title}\n\nChoose option:"
    if poster:
        await cq.message.edit_caption(text, reply_markup=series_home_kb(sid))
    else:
        await cq.message.edit_text(text, reply_markup=series_home_kb(sid))
    await cq.answer()

# ---------------- seasons ----------------

@Client.on_callback_query(filters.regex(r"^ui:lang:(\d+):(.+)$"))
async def ui_seasons(_, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    seasons = await list_seasons(sid, lang)
    rows = []

    for s in seasons:
        rows.append([
            InlineKeyboardButton(s, callback_data=f"ui:season:{sid}:{q(lang)}:{q(s)}")
        ])

    rows.append([InlineKeyboardButton("➕ Add First Item", callback_data=f"ui:add_season:{sid}:{q(lang)}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"ui:langs:{sid}")])

    await cq.message.edit_reply_markup(InlineKeyboardMarkup(rows))
    await cq.answer()

@Client.on_callback_query(filters.regex(r"^ui:add_season:(\d+):(.+)$"))
async def ui_add_season(client, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    ask = await client.ask(cq.message.chat.id, "Send season name:", timeout=120)
    season = (ask.text or "").strip()
    if not season:
        return await cq.answer("Empty", show_alert=True)

    await ensure_group(sid, lang, season, "720p")
    await cq.message.reply_text("Season Added")
    await ui_seasons(client, cq)

# ---------------- qualities ----------------

@Client.on_callback_query(filters.regex(r"^ui:season:(\d+):(.+):(.+)$"))
async def ui_qualities(_, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    quals = await list_qualities(sid, lang, season)
    rows = []

    for ql in quals:
        rows.append([
            InlineKeyboardButton(ql, callback_data=f"ui:upload:{sid}:{q(lang)}:{q(season)}:{q(ql)}")
        ])

    rows.append([InlineKeyboardButton("➕ Add First Item", callback_data=f"ui:add_quality:{sid}:{q(lang)}:{q(season)}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"ui:lang:{sid}:{q(lang)}")])

    await cq.message.edit_reply_markup(InlineKeyboardMarkup(rows))
    await cq.answer()

@Client.on_callback_query(filters.regex(r"^ui:add_quality:(\d+):(.+):(.+)$"))
async def ui_add_quality(client, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    ask = await client.ask(cq.message.chat.id, "Send quality (720p/1080p):", timeout=120)
    ql = (ask.text or "").strip()
    if not ql:
        return await cq.answer("Empty", show_alert=True)

    await ensure_group(sid, lang, season, ql)
    await cq.message.reply_text("Quality Added")
    await ui_qualities(client, cq)

# ---------------- upload ----------------

@Client.on_callback_query(filters.regex(r"^ui:upload:(\d+):(.+):(.+):(.+)$"))
async def ui_upload(client, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    quality = uq(cq.matches[0].group(4))

    gid = await ensure_group(sid, lang, season, quality)

    info = await cq.message.reply_text(
        f"📥 Send files for:\n\n"
        f"{lang} / {season} / {quality}\n\n"
        f"Finish `/done`"
    )

    queue = []
    while True:
        m = await client.listen(cq.message.chat.id)
        if (m.text or "").lower() == "/done":
            break
        media = get_file_id(m)
        if media:
            queue.append((media.file_id, m.caption or "", media.message_type))

    for f, c, t in queue:
        await add_file(gid, f, c, t)
        await asyncio.sleep(SAVE_DELAY)

    done = await cq.message.reply_text(f"✅ Saved {len(queue)} files")
    asyncio.create_task(auto_delete(done))
    asyncio.create_task(auto_delete(info, 20))
    await cq.answer("Done")
