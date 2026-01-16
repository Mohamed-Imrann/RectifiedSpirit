import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database.series_sql import (
    find_series,
    list_languages,
    list_seasons,
    list_qualities,
    get_group_id,
    get_files,
)
from utils import auto_delete


# ---------- Keyboards ----------

def kb_languages(series_id: int, langs: list[str]):
    rows = [[InlineKeyboardButton(l, callback_data=f"usr:season:{series_id}:{l}")]
            for l in langs]
    return InlineKeyboardMarkup(rows)


def kb_seasons(series_id: int, lang: str, seasons: list[str]):
    rows = [[InlineKeyboardButton(s, callback_data=f"usr:quality:{series_id}:{lang}:{s}")]
            for s in seasons]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"usr:lang:{series_id}")])
    return InlineKeyboardMarkup(rows)


def kb_qualities(series_id: int, lang: str, season: str, qualities: list[str]):
    rows = [[InlineKeyboardButton(q, callback_data=f"usr:send:{series_id}:{lang}:{season}:{q}")]
            for q in qualities]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"usr:season:{series_id}:{lang}")])
    return InlineKeyboardMarkup(rows)


# ---------- User search ----------

@Client.on_message(filters.text & filters.incoming & ~filters.command(["newseries"]))
async def user_search(client: Client, message):
    query = (message.text or "").strip()
    if not query:
        return

    row = await find_series(query)
    if not row:
        return  # ❌ silent if not found (as you wanted)

    series_id, title, poster = row
    langs = await list_languages(series_id)
    if not langs:
        return

    caption = f"🎬 **{title}**\n\nSelect **Language**:"
    if poster:
        m = await message.reply_photo(
            poster,
            caption=caption,
            reply_markup=kb_languages(series_id, langs)
        )
    else:
        m = await message.reply_text(
            caption,
            reply_markup=kb_languages(series_id, langs)
        )

    asyncio.create_task(auto_delete(m))


# ---------- Callbacks ----------

@Client.on_callback_query(filters.regex(r"^usr:lang:(\d+)$"))
async def cb_lang(client, cq):
    series_id = int(cq.matches[0].group(1))
    langs = await list_languages(series_id)
    await cq.message.edit_reply_markup(kb_languages(series_id, langs))
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^usr:season:(\d+):(.+)$"))
async def cb_season(client, cq):
    series_id = int(cq.matches[0].group(1))
    lang = cq.matches[0].group(2)

    seasons = await list_seasons(series_id, lang)
    await cq.message.edit_reply_markup(
        kb_seasons(series_id, lang, seasons)
    )
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^usr:quality:(\d+):(.+):(.+)$"))
async def cb_quality(client, cq):
    series_id = int(cq.matches[0].group(1))
    lang = cq.matches[0].group(2)
    season = cq.matches[0].group(3)

    qualities = await list_qualities(series_id, lang, season)
    await cq.message.edit_reply_markup(
        kb_qualities(series_id, lang, season, qualities)
    )
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^usr:send:(\d+):(.+):(.+):(.+)$"))
async def cb_send(client, cq):
    series_id = int(cq.matches[0].group(1))
    lang = cq.matches[0].group(2)
    season = cq.matches[0].group(3)
    quality = cq.matches[0].group(4)

    g = await get_group_id(series_id, lang, season, quality)
    if not g:
        return await cq.answer("No files", show_alert=True)

    group_id = g[0]
    files = await get_files(group_id)
    if not files:
        return await cq.answer("No files", show_alert=True)

    await cq.answer("Sending…")

    for file_id, caption, _ in files:
        sent = await cq.message.reply_cached_media(
            file_id,
            caption=caption or ""
        )
        asyncio.create_task(auto_delete(sent))
