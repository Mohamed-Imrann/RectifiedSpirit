# plugins/panel_like_ui.py
import asyncio
from urllib.parse import quote, unquote

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from info import ADMINS, SAVE_DELAY, IMGBB_API_KEY, TMDB_API_KEY
from utils import get_file_id
from utils_poster import tmdb_get_poster, upload_imgbb

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

# =========================
# 🔐 Ask lock (avoid loading loop)
# =========================
ACTIVE_ASK = set()

def q(s: str) -> str:
    return quote(s, safe="")

def uq(s: str) -> str:
    return unquote(s)

async def safe_edit(cq, text: str, kb=None):
    """
    Avoid 'loading forever' by always answering and handling caption/text safely.
    """
    try:
        if cq.message.photo:
            await cq.message.edit_caption(text, reply_markup=kb)
        else:
            await cq.message.edit_text(text, reply_markup=kb)
    except Exception:
        # fallback: send new msg
        try:
            await cq.message.reply_text(text, reply_markup=kb)
        except Exception:
            pass

def _row_unpack_series(row):
    """
    get_series_by_id can return 3 or 4+ cols depending on your DB.
    Expected: (id, title, poster, published)
    We'll be defensive.
    """
    if not row:
        return None, None, None, 0
    sid = row[0]
    title = row[1] if len(row) > 1 else ""
    poster = row[2] if len(row) > 2 else None
    published = row[3] if len(row) > 3 else 0
    return sid, title, poster, published

# =========================
# Keyboards
# =========================
def kb_series_home(series_id: int, published: int):
    status = "✅ Published" if published == 1 else "❌ Unpublished"
    icon = "📦" if published == 1 else "📤"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Languages", callback_data=f"adm:langs:{series_id}")],
        [InlineKeyboardButton(f"{icon} {status}", callback_data=f"adm:publish:{series_id}")],
        [InlineKeyboardButton("🖼 Poster", callback_data=f"adm:poster:{series_id}")],
    ])

def kb_poster_menu(series_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Auto Fetch (TMDB)", callback_data=f"adm:poster_auto:{series_id}")],
        [InlineKeyboardButton("📸 Manual Upload", callback_data=f"adm:poster_manual:{series_id}")],
        [InlineKeyboardButton("⬅️ Back", callback_data=f"adm:home:{series_id}")],
    ])

def kb_langs(series_id: int, langs: list[str]):
    rows = []
    if langs:
        for name in langs:
            rows.append([InlineKeyboardButton(name, callback_data=f"adm:lang:{series_id}:{q(name)}")])
    rows.append([InlineKeyboardButton("➕ Add Language", callback_data=f"adm:addlang:{series_id}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"adm:home:{series_id}")])
    return InlineKeyboardMarkup(rows)

def kb_seasons(series_id: int, lang: str, seasons: list[str]):
    rows = []
    if seasons:
        for s in seasons:
            rows.append([InlineKeyboardButton(s, callback_data=f"adm:season:{series_id}:{q(lang)}:{q(s)}")])
    rows.append([InlineKeyboardButton("➕ Add Season", callback_data=f"adm:addseason:{series_id}:{q(lang)}")])
    rows.append([InlineKeyboardButton("🗑 Delete Language Group", callback_data=f"adm:dellang:{series_id}:{q(lang)}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"adm:langs:{series_id}")])
    return InlineKeyboardMarkup(rows)

async def kb_qualities(series_id: int, lang: str, season: str, qualities: list[str]):
    rows = []
    if qualities:
        for qu in qualities:
            gid_row = await get_group_id_value(series_id, lang, season, qu)
            gid = gid_row[0] if gid_row else None
            cnt = await count_files_in_group(gid) if gid else 0

            rows.append([
                InlineKeyboardButton(
                    f"{qu} ({cnt})",  # ✅ counts shown (admin only)
                    callback_data=f"adm:upload:{series_id}:{q(lang)}:{q(season)}:{q(qu)}"
                ),
                InlineKeyboardButton(
                    "🗑",
                    callback_data=f"adm:delquality:{series_id}:{q(lang)}:{q(season)}:{q(qu)}"
                )
            ])
    rows.append([InlineKeyboardButton("➕ Add Quality", callback_data=f"adm:addquality:{series_id}:{q(lang)}:{q(season)}")])
    rows.append([InlineKeyboardButton("🗑 Delete Season Group", callback_data=f"adm:delseason:{series_id}:{q(lang)}:{q(season)}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"adm:lang:{series_id}:{q(lang)}")])
    return InlineKeyboardMarkup(rows)

def kb_confirm(back_cb: str, yes_cb: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes Delete", callback_data=yes_cb)],
        [InlineKeyboardButton("⬅️ Cancel", callback_data=back_cb)],
    ])

# =========================
# /newseries (Admin)
# =========================
@Client.on_message(filters.command("newseries") & filters.user(ADMINS))
async def newseries_panel(client, message):
    uid = message.from_user.id

    if uid in ACTIVE_ASK:
        return await message.reply_text("⏳ Already waiting for input. Finish pannunga.")

    ACTIVE_ASK.add(uid)
    try:
        ask = await client.ask(message.chat.id, "📌 Series name anuppu:", timeout=180)
        title = (ask.text or "").strip()
        if not title:
            return await message.reply_text("❌ Empty title")

        sid = await upsert_series(title)
        row = await get_series_by_id(sid)
        sid, title, _poster, published = _row_unpack_series(row)

        await message.reply_text(
            f"✅ **Series:** `{title}`\n\nSelect option:",
            reply_markup=kb_series_home(sid, published)
        )
    except asyncio.TimeoutError:
        await message.reply_text("⌛ Timeout. /newseries again")
    finally:
        ACTIVE_ASK.discard(uid)

# =========================
# HOME
# =========================
@Client.on_callback_query(filters.regex(r"^adm:home:(\d+)$"))
async def adm_home(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    row = await get_series_by_id(sid)
    if not row:
        return await cq.message.reply_text("❌ Not found")

    sid, title, _poster, published = _row_unpack_series(row)
    await safe_edit(cq, f"✅ **Series:** `{title}`\n\nSelect option:", kb_series_home(sid, published))

# =========================
# PUBLISH TOGGLE
# =========================
@Client.on_callback_query(filters.regex(r"^adm:publish:(\d+)$"))
async def adm_publish(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    new_val = await toggle_publish(sid)

    row = await get_series_by_id(sid)
    if not row:
        return await cq.message.reply_text("❌ Not found")

    sid, title, _poster, published = _row_unpack_series(row)
    status = "✅ Published" if new_val == 1 else "❌ Unpublished"
    await safe_edit(cq, f"✅ **Series:** `{title}`\n\nStatus: **{status}**\n\nSelect option:", kb_series_home(sid, published))

# =========================
# POSTER MENU OPEN
# =========================
@Client.on_callback_query(filters.regex(r"^adm:poster:(\d+)$"))
async def adm_poster_menu(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    await safe_edit(cq, "🖼 **Poster Menu**\n\nChoose option:", kb_poster_menu(sid))

# =========================
# POSTER AUTO (TMDB)
# =========================
@Client.on_callback_query(filters.regex(r"^adm:poster_auto:(\d+)$"))
async def adm_poster_auto(_, cq):
    await cq.answer("Fetching…")
    sid = int(cq.matches[0].group(1))

    row = await get_series_by_id(sid)
    if not row:
        return await cq.answer("Not found", show_alert=True)

    sid, title, _poster, published = _row_unpack_series(row)

    poster_url = await tmdb_get_poster(title, TMDB_API_KEY)
    if not poster_url:
        return await cq.answer("TMDB poster not found", show_alert=True)

    await set_series_poster(sid, poster_url)

    await safe_edit(
        cq,
        f"✅ **Series:** `{title}`\n\n🖼 Poster auto set ✅\n\nSelect option:",
        kb_series_home(sid, published)
    )

# =========================
# POSTER MANUAL (Send photo -> IMGBB)
# =========================
@Client.on_callback_query(filters.regex(r"^adm:poster_manual:(\d+)$"))
async def adm_poster_manual(client, cq):
    await cq.answer("Send photo")
    sid = int(cq.matches[0].group(1))

    row = await get_series_by_id(sid)
    if not row:
        return await cq.answer("Not found", show_alert=True)

    sid, title, _poster, published = _row_unpack_series(row)

    tip = await cq.message.reply_text("📸 Poster photo anuppu (send photo).")
    try:
        pm = await client.listen(cq.message.chat.id)
    except Exception:
        return await tip.edit_text("❌ Listen failed. Retry.")

    if not pm.photo:
        return await tip.edit_text("❌ Photo illa. Retry pannunga.")

    # download -> bytes -> imgbb
    path = await client.download_media(pm.photo)
    try:
        with open(path, "rb") as f:
            photo_bytes = f.read()
    except Exception:
        return await tip.edit_text("❌ Download read failed.")

    imgbb_url = await upload_imgbb(photo_bytes, IMGBB_API_KEY)
    if not imgbb_url:
        return await tip.edit_text("❌ IMGBB upload failed.")

    await set_series_poster(sid, imgbb_url)
    await tip.edit_text("✅ Poster updated ✅")

    await safe_edit(
        cq,
        f"✅ **Series:** `{title}`\n\n🖼 Poster manual set ✅\n\nSelect option:",
        kb_series_home(sid, published)
    )

# =========================
# LANGUAGES
# =========================
@Client.on_callback_query(filters.regex(r"^adm:langs:(\d+)$"))
async def adm_langs(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    langs = await list_languages(sid)
    await safe_edit(cq, "🌐 **Languages**\nSelect group:", kb_langs(sid, langs))

@Client.on_callback_query(filters.regex(r"^adm:addlang:(\d+)$"))
async def adm_addlang(client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))

    uid = cq.from_user.id
    if uid in ACTIVE_ASK:
        return await cq.message.reply_text("⏳ Already waiting. Finish first.")
    ACTIVE_ASK.add(uid)

    try:
        ask = await client.ask(cq.message.chat.id, "🌐 Language name anuppu:", timeout=180)
        lang = (ask.text or "").strip()
        if not lang:
            return await cq.message.reply_text("❌ Empty")

        # seed entry
        await ensure_group(sid, lang, "Season 1", "720p")

        langs = await list_languages(sid)
        await safe_edit(cq, f"✅ Language Added: `{lang}`", kb_langs(sid, langs))
    except asyncio.TimeoutError:
        await cq.message.reply_text("⌛ Timeout")
    finally:
        ACTIVE_ASK.discard(uid)

@Client.on_callback_query(filters.regex(r"^adm:lang:(\d+):(.+)$"))
async def adm_lang(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    seasons = await list_seasons(sid, lang)
    await safe_edit(cq, f"Language: `{lang}`\nSelect Season:", kb_seasons(sid, lang, seasons))

# =========================
# SEASONS
# =========================
@Client.on_callback_query(filters.regex(r"^adm:addseason:(\d+):(.+)$"))
async def adm_addseason(client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    uid = cq.from_user.id
    if uid in ACTIVE_ASK:
        return await cq.message.reply_text("⏳ Already waiting. Finish first.")
    ACTIVE_ASK.add(uid)

    try:
        ask = await client.ask(cq.message.chat.id, "📦 Season name anuppu:", timeout=180)
        season = (ask.text or "").strip()
        if not season:
            return await cq.message.reply_text("❌ Empty")

        await ensure_group(sid, lang, season, "720p")

        seasons = await list_seasons(sid, lang)
        await safe_edit(cq, f"✅ Season Added: `{season}`", kb_seasons(sid, lang, seasons))
    except asyncio.TimeoutError:
        await cq.message.reply_text("⌛ Timeout")
    finally:
        ACTIVE_ASK.discard(uid)

@Client.on_callback_query(filters.regex(r"^adm:season:(\d+):(.+):(.+)$"))
async def adm_season(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    qualities = await list_qualities(sid, lang, season)
    markup = await kb_qualities(sid, lang, season, qualities)
    await safe_edit(cq, f"Language: `{lang}`\nSeason: `{season}`\nSelect Quality:", markup)

# =========================
# QUALITIES
# =========================
@Client.on_callback_query(filters.regex(r"^adm:addquality:(\d+):(.+):(.+)$"))
async def adm_addquality(client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    uid = cq.from_user.id
    if uid in ACTIVE_ASK:
        return await cq.message.reply_text("⏳ Already waiting. Finish first.")
    ACTIVE_ASK.add(uid)

    try:
        ask = await client.ask(cq.message.chat.id, "🎞 Quality anuppu (720p/1080p):", timeout=180)
        quality = (ask.text or "").strip()
        if not quality:
            return await cq.message.reply_text("❌ Empty")

        await ensure_group(sid, lang, season, quality)

        qualities = await list_qualities(sid, lang, season)
        markup = await kb_qualities(sid, lang, season, qualities)
        await safe_edit(cq, f"✅ Quality Added: `{quality}`", markup)
    except asyncio.TimeoutError:
        await cq.message.reply_text("⌛ Timeout")
    finally:
        ACTIVE_ASK.discard(uid)

# =========================
# UPLOAD (quality click) - /done method with progress
# =========================
@Client.on_callback_query(filters.regex(r"^adm:upload:(\d+):(.+):(.+):(.+)$"))
async def adm_upload(client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    quality = uq(cq.matches[0].group(4))

    group_id = await ensure_group(sid, lang, season, quality)

    info = await cq.message.reply_text(
        f"📥 **Upload Mode**\n\n"
        f"Language: `{lang}`\nSeason: `{season}`\nQuality: `{quality}`\n\n"
        f"Files send pannunga… finish panna `/done`"
    )

    progress = await cq.message.reply_text("⏳ Waiting for files…")
    queue = []

    while True:
        m = await client.listen(cq.message.chat.id)

        txt = (m.text or "").strip().lower()
        if txt == "/done":
            break

        if not m.media:
            continue

        media = get_file_id(m)
        if not media:
            continue

        queue.append((media.file_id, m.caption or "", getattr(media, "message_type", "")))

        try:
            await progress.edit_text(f"✅ Files received: `{len(queue)}`\nSend more… or `/done`")
        except Exception:
            pass

    if not queue:
        try:
            await progress.edit_text("❌ No files received.")
        except Exception:
            pass
        return

    saved = 0
    total = len(queue)

    for file_id, caption, msg_type in queue:
        await add_file(group_id, file_id, caption, msg_type)
        saved += 1
        try:
            await progress.edit_text(f"💾 Saving... `{saved}/{total}`\n⏳ Delay: `{SAVE_DELAY}s`")
        except Exception:
            pass
        await asyncio.sleep(SAVE_DELAY)

    await cq.message.reply_text(
        f"✅ **{quality} files added:** `{saved}`\n`{lang}` / `{season}`"
    )

    # refresh quality buttons with updated counts
    qualities = await list_qualities(sid, lang, season)
    markup = await kb_qualities(sid, lang, season, qualities)
    await safe_edit(cq, f"Language: `{lang}`\nSeason: `{season}`\nSelect Quality:", markup)

    try:
        await info.delete()
    except Exception:
        pass
    try:
        await progress.delete()
    except Exception:
        pass

# =========================
# DELETE FLOWS
# =========================
@Client.on_callback_query(filters.regex(r"^adm:dellang:(\d+):(.+)$"))
async def adm_dellang_confirm(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    text = f"⚠️ Delete Language Group?\n\nLanguage: `{lang}`\n\nThis deletes ALL inside."
    back = f"adm:lang:{sid}:{q(lang)}"
    yes = f"adm:yes_dellang:{sid}:{q(lang)}"
    await safe_edit(cq, text, kb_confirm(back, yes))

@Client.on_callback_query(filters.regex(r"^adm:yes_dellang:(\d+):(.+)$"))
async def adm_dellang_yes(_, cq):
    await cq.answer("Deleted")
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    await delete_language(sid, lang)

    langs = await list_languages(sid)
    await safe_edit(cq, f"🗑 Deleted Language `{lang}` ✅", kb_langs(sid, langs))

@Client.on_callback_query(filters.regex(r"^adm:delseason:(\d+):(.+):(.+)$"))
async def adm_delseason_confirm(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    text = f"⚠️ Delete Season Group?\n\n`{lang}` / `{season}`\n\nThis deletes ALL inside."
    back = f"adm:season:{sid}:{q(lang)}:{q(season)}"
    yes = f"adm:yes_delseason:{sid}:{q(lang)}:{q(season)}"
    await safe_edit(cq, text, kb_confirm(back, yes))

@Client.on_callback_query(filters.regex(r"^adm:yes_delseason:(\d+):(.+):(.+)$"))
async def adm_delseason_yes(_, cq):
    await cq.answer("Deleted")
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    await delete_season(sid, lang, season)

    seasons = await list_seasons(sid, lang)
    await safe_edit(cq, f"🗑 Deleted Season `{season}` ✅", kb_seasons(sid, lang, seasons))

@Client.on_callback_query(filters.regex(r"^adm:delquality:(\d+):(.+):(.+):(.+)$"))
async def adm_delquality_confirm(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    quality = uq(cq.matches[0].group(4))

    text = f"⚠️ Delete Quality?\n\n`{lang}` / `{season}` / `{quality}`\n\nAll files inside will be deleted."
    back = f"adm:season:{sid}:{q(lang)}:{q(season)}"
    yes = f"adm:yes_delquality:{sid}:{q(lang)}:{q(season)}:{q(quality)}"
    await safe_edit(cq, text, kb_confirm(back, yes))

@Client.on_callback_query(filters.regex(r"^adm:yes_delquality:(\d+):(.+):(.+):(.+)$"))
async def adm_delquality_yes(_, cq):
    await cq.answer("Deleted")
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    quality = uq(cq.matches[0].group(4))

    await delete_quality(sid, lang, season, quality)

    qualities = await list_qualities(sid, lang, season)
    markup = await kb_qualities(sid, lang, season, qualities)
    await safe_edit(cq, f"🗑 Deleted Quality `{quality}` ✅", markup)
