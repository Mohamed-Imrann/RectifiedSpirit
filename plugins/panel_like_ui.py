# plugins/panel_like_ui.py
import asyncio
from urllib.parse import quote, unquote

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import MessageNotModified, FloodWait

from pyromod import listen

from info import ADMINS, TMDB_API_KEY
from utils import get_file_id

from database.series_sql import (
    upsert_series,
    get_series_by_id,
    list_languages,
    list_seasons,
    list_qualities,
    ensure_group,
    add_file,
    delete_language,
    delete_season,
    delete_quality,
    get_group_id_value,
    count_files_in_group,
    toggle_publish,
    set_series_poster,
)

import aiohttp

SAVE_DELAY = 1.2


# ---------- helpers ----------
def q(s): return quote(s or "", safe="")
def uq(s): return unquote(s or "")


async def edit_panel(msg, text, reply_markup=None):
    try:
        if msg.photo:
            await msg.edit_caption(text, reply_markup=reply_markup)
        else:
            await msg.edit_text(text, reply_markup=reply_markup)
    except MessageNotModified:
        pass


# ---------- keyboards ----------
def kb_home(series_id, published):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Languages", callback_data=f"adm:langs:{series_id}")],
        [InlineKeyboardButton(
            "📦 Published" if published else "📤 Unpublished",
            callback_data=f"adm:publish:{series_id}"
        )],
        [InlineKeyboardButton("🖼 Poster", callback_data=f"adm:poster:{series_id}")]
    ])


def kb_langs(series_id, langs):
    rows = [[InlineKeyboardButton(l, callback_data=f"adm:lang:{series_id}:{q(l)}")] for l in langs]
    rows.append([InlineKeyboardButton("+ Add Language", callback_data=f"adm:addlang:{series_id}")])
    rows.append([InlineKeyboardButton("⬅ Back", callback_data=f"adm:home:{series_id}")])
    return InlineKeyboardMarkup(rows)


def kb_seasons(series_id, lang, seasons):
    rows = [[InlineKeyboardButton(s, callback_data=f"adm:season:{series_id}:{q(lang)}:{q(s)}")] for s in seasons]
    rows.append([InlineKeyboardButton("+ Add Season", callback_data=f"adm:addseason:{series_id}:{q(lang)}")])
    rows.append([InlineKeyboardButton("⬅ Back", callback_data=f"adm:langs:{series_id}")])
    return InlineKeyboardMarkup(rows)


async def kb_qualities(series_id, lang, season, qualities):
    rows = []
    for ql in qualities:
        row = await get_group_id_value(series_id, lang, season, ql)
        gid = row[0] if row else None
        cnt = await count_files_in_group(gid) if gid else 0
        rows.append([
            InlineKeyboardButton(f"{ql} ({cnt})", callback_data=f"adm:upload:{series_id}:{q(lang)}:{q(season)}:{q(ql)}"),
            InlineKeyboardButton("🗑", callback_data=f"adm:delquality:{series_id}:{q(lang)}:{q(season)}:{q(ql)}")
        ])
    rows.append([InlineKeyboardButton("+ Add Quality", callback_data=f"adm:addquality:{series_id}:{q(lang)}:{q(season)}")])
    rows.append([InlineKeyboardButton("⬅ Back", callback_data=f"adm:lang:{series_id}:{q(lang)}")])
    return InlineKeyboardMarkup(rows)


# ---------- TMDB poster ----------
async def fetch_tmdb_poster(title):
    url = f"https://api.themoviedb.org/3/search/tv"
    params = {"query": title, "api_key": TMDB_API_KEY}

    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params) as r:
            data = await r.json()

    if not data.get("results"):
        return None

    poster = data["results"][0].get("poster_path")
    if not poster:
        return None

    return f"https://image.tmdb.org/t/p/w500{poster}"


# ================= /newseries =================
@Client.on_message(filters.command("newseries") & filters.user(ADMINS))
async def newseries(client, message):
    ask = await client.ask(message.chat.id, "📌 Series name anuppu:")
    title = ask.text.strip()

    sid = await upsert_series(title)

    poster_url = await fetch_tmdb_poster(title)
    sent = None

    if poster_url:
        sent = await message.reply_photo(
            poster_url,
            caption=f"✅ **Series:** `{title}`",
            reply_markup=kb_home(sid, 0)
        )
    else:
        sent = await message.reply_text(
            f"✅ **Series:** `{title}`",
            reply_markup=kb_home(sid, 0)
        )

    if sent and sent.photo:
        await set_series_poster(sid, sent.photo.file_id)


# ================= HOME =================
@Client.on_callback_query(filters.regex(r"^adm:home:(\d+)$"))
async def home(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    row = await get_series_by_id(sid)
    await edit_panel(cq.message, f"✅ **Series:** `{row[1]}`", kb_home(sid, row[3]))


# ================= LANG =================
@Client.on_callback_query(filters.regex(r"^adm:langs:(\d+)$"))
async def langs(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    langs = await list_languages(sid)
    await edit_panel(cq.message, "Select Language:", kb_langs(sid, langs))


@Client.on_callback_query(filters.regex(r"^adm:addlang:(\d+)$"))
async def addlang(client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    ask = await client.ask(cq.message.chat.id, "Language name:")
    await ensure_group(sid, ask.text.strip(), "Season 1", "720p")
    langs = await list_languages(sid)
    await edit_panel(cq.message, "Language added", kb_langs(sid, langs))


# ================= SEASON =================
@Client.on_callback_query(filters.regex(r"^adm:lang:(\d+):(.+)$"))
async def season(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    seasons = await list_seasons(sid, lang)
    await edit_panel(cq.message, f"{lang} seasons:", kb_seasons(sid, lang, seasons))


# ================= QUALITY =================
@Client.on_callback_query(filters.regex(r"^adm:season:(\d+):(.+):(.+)$"))
async def quality(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    qualities = await list_qualities(sid, lang, season)
    await edit_panel(cq.message, "Select Quality:", await kb_qualities(sid, lang, season, qualities))


# ================= UPLOAD =================
@Client.on_callback_query(filters.regex(r"^adm:upload:(\d+):(.+):(.+):(.+)$"))
async def upload(client, cq):
    await cq.answer()
    sid, lang, season, quality = (
        int(cq.matches[0].group(1)),
        uq(cq.matches[0].group(2)),
        uq(cq.matches[0].group(3)),
        uq(cq.matches[0].group(4)),
    )

    group_id = await ensure_group(sid, lang, season, quality)
    user = getattr(client, "user_client", None)

    if not user:
        return await cq.message.reply_text("❌ user_client missing")

    msg = await cq.message.reply_text("➡ Forward FIRST file")
    first = await client.listen(cq.message.chat.id)
    fchat, fid1 = first.forward_from_chat.id, first.forward_from_message_id

    await msg.edit_text("➡ Forward LAST file")
    last = await client.listen(cq.message.chat.id)
    fid2 = last.forward_from_message_id

    messages = await user.get_messages(fchat, list(range(fid1, fid2 + 1)))

    saved = 0
    for m in messages:
        media = get_file_id(m)
        if not media:
            continue
        await add_file(group_id, media.file_id, m.caption or "", media.message_type)
        saved += 1
        await asyncio.sleep(SAVE_DELAY)

    await msg.edit_text(f"✅ Uploaded {saved} files")
