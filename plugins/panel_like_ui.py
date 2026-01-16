import asyncio
import re
from urllib.parse import quote, unquote

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from info import ADMINS, SAVE_DELAY
from plugins.userbot_sync import fetch_files_from_channel_range

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

# ================= HELPERS =================

def q(s: str) -> str:
    return quote(s, safe="")

def uq(s: str) -> str:
    return unquote(s)

def extract_msg_id(link: str):
    m = re.search(r"/(\d+)\s*$", (link or "").strip())
    if not m:
        return None
    return int(m.group(1))

async def safe_edit(cq, text, kb=None):
    try:
        if cq.message.photo:
            await cq.message.edit_caption(text, reply_markup=kb)
        else:
            await cq.message.edit_text(text, reply_markup=kb)
    except Exception:
        try:
            await cq.message.reply_text(text, reply_markup=kb)
        except Exception:
            pass

# ================= KEYBOARDS =================

def kb_series_home(sid, published):
    status = "✅ Published" if published else "❌ Unpublished"
    icon = "📦" if published else "📤"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Languages", callback_data=f"adm:langs:{sid}")],
        [InlineKeyboardButton(f"{icon} {status}", callback_data=f"adm:publish:{sid}")],
        [InlineKeyboardButton("🖼 Poster", callback_data=f"adm:poster:{sid}")],
    ])

def kb_langs(sid, langs):
    rows = [[InlineKeyboardButton(l, callback_data=f"adm:lang:{sid}:{q(l)}")] for l in langs]
    rows.append([InlineKeyboardButton("+ Add Language", callback_data=f"adm:addlang:{sid}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"adm:home:{sid}")])
    return InlineKeyboardMarkup(rows)

def kb_seasons(sid, lang, seasons):
    rows = [[InlineKeyboardButton(s, callback_data=f"adm:season:{sid}:{q(lang)}:{q(s)}")] for s in seasons]
    rows.append([InlineKeyboardButton("+ Add Season", callback_data=f"adm:addseason:{sid}:{q(lang)}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"adm:langs:{sid}")])
    return InlineKeyboardMarkup(rows)

async def kb_qualities(sid, lang, season, qualities):
    rows = []
    for ql in qualities:
        gid_row = await get_group_id_value(sid, lang, season, ql)
        gid = gid_row[0] if gid_row else None
        cnt = await count_files_in_group(gid) if gid else 0
        rows.append([
            InlineKeyboardButton(f"{ql} ({cnt})", callback_data=f"adm:upload:{sid}:{q(lang)}:{q(season)}:{q(ql)}"),
            InlineKeyboardButton("🗑", callback_data=f"adm:delquality:{sid}:{q(lang)}:{q(season)}:{q(ql)}"),
        ])
    rows.append([InlineKeyboardButton("+ Add Quality", callback_data=f"adm:addquality:{sid}:{q(lang)}:{q(season)}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"adm:lang:{sid}:{q(lang)}")])
    return InlineKeyboardMarkup(rows)

# ================= /newseries =================

@Client.on_message(filters.command("newseries") & filters.user(ADMINS))
async def newseries_panel(client, message):
    ask = await client.ask(message.chat.id, "📌 Series name anuppu:", timeout=180)
    title = (ask.text or "").strip()
    if not title:
        return

    sid = await upsert_series(title)
    row = await get_series_by_id(sid)
    published = row[3] if row else 0

    await message.reply_text(
        f"✅ **Series:** `{title}`\n\nSelect option:",
        reply_markup=kb_series_home(sid, published)
    )

# ================= HOME =================

@Client.on_callback_query(filters.regex(r"^adm:home:(\d+)$"))
async def adm_home(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    row = await get_series_by_id(sid)
    if not row:
        return
    _, title, _, published = row
    await safe_edit(cq, f"✅ **Series:** `{title}`\n\nSelect option:", kb_series_home(sid, published))

# ================= PUBLISH =================

@Client.on_callback_query(filters.regex(r"^adm:publish:(\d+)$"))
async def adm_publish(_, cq):
    sid = int(cq.matches[0].group(1))
    await toggle_publish(sid)
    row = await get_series_by_id(sid)
    _, title, _, published = row
    await cq.answer("Updated", show_alert=True)
    await safe_edit(cq, f"✅ **Series:** `{title}`\n\nSelect option:", kb_series_home(sid, published))

# ================= LANG / SEASON / QUALITY =================

@Client.on_callback_query(filters.regex(r"^adm:langs:(\d+)$"))
async def adm_langs(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    langs = await list_languages(sid)
    await safe_edit(cq, "Select language:", kb_langs(sid, langs))

@Client.on_callback_query(filters.regex(r"^adm:lang:(\d+):(.+)$"))
async def adm_lang(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    seasons = await list_seasons(sid, lang)
    await safe_edit(cq, f"Language: `{lang}`", kb_seasons(sid, lang, seasons))

@Client.on_callback_query(filters.regex(r"^adm:season:(\d+):(.+):(.+)$"))
async def adm_season(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    qualities = await list_qualities(sid, lang, season)
    kb = await kb_qualities(sid, lang, season, qualities)
    await safe_edit(cq, f"{lang} / {season}\nSelect quality:", kb)

# ================= OPTION-B UPLOAD =================

@Client.on_callback_query(filters.regex(r"^adm:upload:(\d+):(.+):(.+):(.+)$"))
async def adm_upload(client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    quality = uq(cq.matches[0].group(4))

    group_id = await ensure_group(sid, lang, season, quality)

    await cq.message.reply_text(
        f"📥 **{quality} Upload**\n\n"
        f"Channel-la irukkura FIRST file link & LAST file link paste pannunga."
    )

    a1 = await client.ask(cq.message.chat.id, "🔗 FIRST file link:", timeout=300)
    first_id = extract_msg_id(a1.text)
    if not first_id:
        return await cq.message.reply_text("❌ First link wrong")

    a2 = await client.ask(cq.message.chat.id, "🔗 LAST file link:", timeout=300)
    last_id = extract_msg_id(a2.text)
    if not last_id or last_id < first_id:
        return await cq.message.reply_text("❌ Last link wrong")

    user = getattr(client, "user_client", None)
    if not user:
        return await cq.message.reply_text("❌ User session not running")

    progress = await cq.message.reply_text("⏳ Files fetch pannuren...")

    files = await fetch_files_from_channel_range(user, first_id, last_id)
    if not files:
        return await progress.edit_text("❌ No files found")

    saved = 0
    for file_id, caption, msg_type in files:
        await add_file(group_id, file_id, caption, msg_type)
        saved += 1
        await progress.edit_text(f"💾 Saved {saved}/{len(files)}")
        await asyncio.sleep(SAVE_DELAY)

    await progress.edit_text(f"✅ **{quality} files added:** `{saved}`")

# ================= DELETE =================

@Client.on_callback_query(filters.regex(r"^adm:delquality:(\d+):(.+):(.+):(.+)$"))
async def adm_delquality(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    quality = uq(cq.matches[0].group(4))
    await delete_quality(sid, lang, season, quality)
    qualities = await list_qualities(sid, lang, season)
    kb = await kb_qualities(sid, lang, season, qualities)
    await safe_edit(cq, "Deleted", kb)
