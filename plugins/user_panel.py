from urllib.parse import quote, unquote

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database.series_sql import (
    find_series,
    get_series_by_id,
    list_languages,
    list_seasons,
    list_qualities,
    get_group_id_value,
    get_files,
)

# -------- helpers --------

def q(s: str) -> str:
    return quote(s, safe="")

def uq(s: str) -> str:
    return unquote(s)

def home_kb(series_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Languages", callback_data=f"usr:langs:{series_id}")]
    ])

# -------- USER SEARCH --------

@Client.on_message(filters.text & filters.incoming & ~filters.command(["newseries"]))
async def user_search(client: Client, message):
    query = (message.text or "").strip()
    if not query:
        return

    row = await find_series(query)
    if not row:
        return  # silent if not found

    series_id, title, poster = row
    text = f"🎬 **{title}**\n\nSelect option:"

    if poster:
        await message.reply_photo(
            poster,
            caption=text,
            reply_markup=home_kb(series_id)
        )
    else:
        await message.reply_text(
            text,
            reply_markup=home_kb(series_id)
        )

# -------- LANGUAGES --------

@Client.on_callback_query(filters.regex(r"^usr:langs:(\d+)$"))
async def usr_langs(_, cq):
    sid = int(cq.matches[0].group(1))
    langs = await list_languages(sid)

    if not langs:
        return await cq.answer("No languages", show_alert=True)

    rows = [[InlineKeyboardButton(l, callback_data=f"usr:lang:{sid}:{q(l)}")] for l in langs]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"usr:home:{sid}")])

    await cq.message.edit_reply_markup(InlineKeyboardMarkup(rows))
    await cq.answer()

@Client.on_callback_query(filters.regex(r"^usr:home:(\d+)$"))
async def usr_home(_, cq):
    sid = int(cq.matches[0].group(1))
    row = await get_series_by_id(sid)
    if not row:
        return

    _, title, poster = row
    text = f"🎬 **{title}**\n\nSelect option:"
    if poster:
        await cq.message.edit_caption(text, reply_markup=home_kb(sid))
    else:
        await cq.message.edit_text(text, reply_markup=home_kb(sid))
    await cq.answer()

# -------- SEASONS --------

@Client.on_callback_query(filters.regex(r"^usr:lang:(\d+):(.+)$"))
async def usr_seasons(_, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    seasons = await list_seasons(sid, lang)
    if not seasons:
        return await cq.answer("No seasons", show_alert=True)

    rows = [
        [InlineKeyboardButton(s, callback_data=f"usr:season:{sid}:{q(lang)}:{q(s)}")]
        for s in seasons
    ]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"usr:langs:{sid}")])

    await cq.message.edit_reply_markup(InlineKeyboardMarkup(rows))
    await cq.answer()

# -------- QUALITIES --------

@Client.on_callback_query(filters.regex(r"^usr:season:(\d+):(.+):(.+)$"))
async def usr_qualities(_, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    qualities = await list_qualities(sid, lang, season)
    if not qualities:
        return await cq.answer("No qualities", show_alert=True)

    rows = [
        [InlineKeyboardButton(q, callback_data=f"usr:send:{sid}:{q(lang)}:{q(season)}:{q(q)}")]
        for q in qualities
    ]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"usr:lang:{sid}:{q(lang)}")])

    await cq.message.edit_reply_markup(InlineKeyboardMarkup(rows))
    await cq.answer()

# -------- SEND FILES --------

@Client.on_callback_query(filters.regex(r"^usr:send:(\d+):(.+):(.+):(.+)$"))
async def usr_send(client: Client, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    quality = uq(cq.matches[0].group(4))

    g = await get_group_id(sid, lang, season, quality)
    if not g:
        return await cq.answer("No files", show_alert=True)

    group_id = g[0]
    files = await get_files(group_id)
    if not files:
        return await cq.answer("No files", show_alert=True)

    await cq.answer("Sending files…")

    for file_id, caption, _ in files:
        await cq.message.reply_cached_media(
            file_id,
            caption=caption or ""
        )
