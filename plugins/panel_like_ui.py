# plugins/panel_like_ui.py
import asyncio
import re
from urllib.parse import quote, unquote

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from info import ADMINS, SAVE_DELAY
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

# ---------------- helpers ----------------

def q(s: str) -> str:
    return quote(s, safe="")

def uq(s: str) -> str:
    return unquote(s)

def parse_tme_link(link: str):
    """
    Supports:
      https://t.me/c/3319100929/13     -> chat_id = -1003319100929, msg_id=13
      https://t.me/SomeChannel/55      -> chat = "SomeChannel", msg_id=55
      https://t.me/+Abcdef/55          -> not supported (private invite links)
    Returns: (chat, msg_id) or (None, None)
    """
    s = (link or "").strip()

    # t.me/c/<internal_id>/<msg_id>
    m = re.search(r"t\.me\/c\/(\d+)\/(\d+)", s)
    if m:
        internal = m.group(1)
        msg_id = int(m.group(2))
        chat_id = int(f"-100{internal}")
        return chat_id, msg_id

    # t.me/<username>/<msg_id>
    m = re.search(r"t\.me\/([A-Za-z0-9_]+)\/(\d+)", s)
    if m:
        username = m.group(1)
        msg_id = int(m.group(2))
        return username, msg_id

    return None, None

async def safe_edit_panel(cq, text: str, reply_markup=None):
    """
    Try edit_caption/edit_text; if fails, send new message.
    """
    try:
        if cq.message.photo:
            await cq.message.edit_caption(text, reply_markup=reply_markup)
        else:
            await cq.message.edit_text(text, reply_markup=reply_markup)
        return
    except Exception:
        try:
            await cq.message.reply_text(text, reply_markup=reply_markup)
        except Exception:
            pass

def kb_confirm(back_cb: str, yes_cb: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes Delete", callback_data=yes_cb)],
        [InlineKeyboardButton("⬅️ Cancel", callback_data=back_cb)],
    ])

def kb_series_home(series_id: int, published: int):
    pub_txt = "✅ Published" if published == 1 else "❌ Unpublished"
    pub_emoji = "📦" if published == 1 else "📤"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Languages", callback_data=f"adm:langs:{series_id}")],
        [InlineKeyboardButton(f"{pub_emoji} {pub_txt}", callback_data=f"adm:publish:{series_id}")],
        [InlineKeyboardButton("🖼 Poster", callback_data=f"adm:poster:{series_id}")],
    ])

def kb_langs(series_id: int, langs: list[str]):
    rows = []
    if langs:
        for name in langs:
            rows.append([InlineKeyboardButton(name, callback_data=f"adm:lang:{series_id}:{q(name)}")])
        rows.append([InlineKeyboardButton("+ Add Language", callback_data=f"adm:addlang:{series_id}")])
    else:
        rows.append([InlineKeyboardButton("+ Add First Item", callback_data=f"adm:addlang:{series_id}")])

    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"adm:home:{series_id}")])
    return InlineKeyboardMarkup(rows)

def kb_seasons(series_id: int, lang: str, seasons: list[str]):
    rows = []
    if seasons:
        for s in seasons:
            rows.append([
                InlineKeyboardButton(s, callback_data=f"adm:season:{series_id}:{q(lang)}:{q(s)}"),
                InlineKeyboardButton("+", callback_data=f"adm:addseason:{series_id}:{q(lang)}"),
            ])
        rows.append([InlineKeyboardButton("+ Add Season", callback_data=f"adm:addseason:{series_id}:{q(lang)}")])
    else:
        rows.append([InlineKeyboardButton("+ Add First Item", callback_data=f"adm:addseason:{series_id}:{q(lang)}")])

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
                    f"{qu} ({cnt})",
                    callback_data=f"adm:upload:{series_id}:{q(lang)}:{q(season)}:{q(qu)}"
                ),
                InlineKeyboardButton(
                    "🗑",
                    callback_data=f"adm:delquality:{series_id}:{q(lang)}:{q(season)}:{q(qu)}"
                )
            ])
        rows.append([InlineKeyboardButton("+ Add Quality", callback_data=f"adm:addquality:{series_id}:{q(lang)}:{q(season)}")])
    else:
        rows.append([InlineKeyboardButton("+ Add First Item", callback_data=f"adm:addquality:{series_id}:{q(lang)}:{q(season)}")])

    rows.append([InlineKeyboardButton("🗑 Delete Season Group", callback_data=f"adm:delseason:{series_id}:{q(lang)}:{q(season)}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"adm:lang:{series_id}:{q(lang)}")])
    return InlineKeyboardMarkup(rows)

# =======================
# /newseries (ADMIN PANEL)
# =======================
@Client.on_message(filters.command("newseries") & filters.user(ADMINS))
async def newseries_panel(client, message):
    ask = await client.ask(message.chat.id, "📌 Series name anuppu:", timeout=180)
    title = (ask.text or "").strip()
    if not title:
        return await message.reply_text("❌ Empty title")

    sid = await upsert_series(title)
    row = await get_series_by_id(sid)
    published = row[3] if row else 0

    caption = f"✅ **Series:** `{title}`\n\nSelect option:"
    await message.reply_text(caption, reply_markup=kb_series_home(sid, published))

# =======================
# HOME
# =======================
@Client.on_callback_query(filters.regex(r"^adm:home:(\d+)$"))
async def adm_home(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))

    row = await get_series_by_id(sid)
    if not row:
        return await cq.message.reply_text("❌ Not found")

    _, title, _poster, published = row
    caption = f"✅ **Series:** `{title}`\n\nSelect option:"
    await safe_edit_panel(cq, caption, kb_series_home(sid, published))

# =======================
# PUBLISH TOGGLE
# =======================
@Client.on_callback_query(filters.regex(r"^adm:publish:(\d+)$"))
async def adm_publish(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    new_val = await toggle_publish(sid)

    row = await get_series_by_id(sid)
    if not row:
        return await cq.message.reply_text("❌ Not found")

    _, title, _poster, published = row
    status = "✅ Published" if new_val == 1 else "❌ Unpublished"
    caption = f"✅ **Series:** `{title}`\n\nStatus: **{status}**\n\nSelect option:"
    await safe_edit_panel(cq, caption, kb_series_home(sid, published))

# =======================
# POSTER
# =======================
@Client.on_callback_query(filters.regex(r"^adm:poster:(\d+)$"))
async def adm_poster(client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))

    tip = await cq.message.reply_text("🖼 Poster photo anuppu (send photo).")
    pm = await client.listen(cq.message.chat.id)

    if not pm.photo:
        return await tip.edit_text("❌ Photo illa. Retry pannunga.")

    await set_series_poster(sid, pm.photo.file_id)

    row = await get_series_by_id(sid)
    if not row:
        return await tip.edit_text("✅ Poster updated. (series not found?)")

    _, title, _poster, published = row
    await tip.edit_text("✅ Poster updated.")

    caption = f"✅ **Series:** `{title}`\n\nSelect option:"
    await safe_edit_panel(cq, caption, kb_series_home(sid, published))

# =======================
# LANGUAGES
# =======================
@Client.on_callback_query(filters.regex(r"^adm:langs:(\d+)$"))
async def adm_langs(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    langs = await list_languages(sid)

    text = "Select any Language group to add seasons. Or click + to add new."
    await safe_edit_panel(cq, text, kb_langs(sid, langs))

@Client.on_callback_query(filters.regex(r"^adm:addlang:(\d+)$"))
async def adm_addlang(client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))

    ask = await client.ask(cq.message.chat.id, "🌐 Language name anuppu (ex: Multi Audio / Tamil):", timeout=180)
    lang = (ask.text or "").strip()
    if not lang:
        return await cq.message.reply_text("❌ Empty")

    await ensure_group(sid, lang, "season 1", "720p")

    langs = await list_languages(sid)
    text = f"✅ Language Added: `{lang}`"
    await safe_edit_panel(cq, text, kb_langs(sid, langs))

@Client.on_callback_query(filters.regex(r"^adm:lang:(\d+):(.+)$"))
async def adm_lang(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    seasons = await list_seasons(sid, lang)
    text = f"Language: `{lang}`\nSelect any Seasons group."
    await safe_edit_panel(cq, text, kb_seasons(sid, lang, seasons))

# =======================
# SEASONS
# =======================
@Client.on_callback_query(filters.regex(r"^adm:addseason:(\d+):(.+)$"))
async def adm_addseason(client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    ask = await client.ask(cq.message.chat.id, "📦 Season name anuppu:", timeout=180)
    season = (ask.text or "").strip()
    if not season:
        return await cq.message.reply_text("❌ Empty")

    await ensure_group(sid, lang, season, "720p")

    seasons = await list_seasons(sid, lang)
    text = f"✅ Season Added: `{season}`\nLanguage: `{lang}`"
    await safe_edit_panel(cq, text, kb_seasons(sid, lang, seasons))

@Client.on_callback_query(filters.regex(r"^adm:season:(\d+):(.+):(.+)$"))
async def adm_season(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    qualities = await list_qualities(sid, lang, season)
    markup = await kb_qualities(sid, lang, season, qualities)

    text = f"Language: `{lang}`\nSeason: `{season}`\nSelect any Quality to upload."
    await safe_edit_panel(cq, text, markup)

# =======================
# QUALITIES
# =======================
@Client.on_callback_query(filters.regex(r"^adm:addquality:(\d+):(.+):(.+)$"))
async def adm_addquality(client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    ask = await client.ask(cq.message.chat.id, "🎞 Quality anuppu (ex: 720p / 1080p):", timeout=180)
    quality = (ask.text or "").strip()
    if not quality:
        return await cq.message.reply_text("❌ Empty")

    await ensure_group(sid, lang, season, quality)

    qualities = await list_qualities(sid, lang, season)
    markup = await kb_qualities(sid, lang, season, qualities)

    text = f"✅ Quality Added: `{quality}`\n`{lang}` / `{season}`"
    await safe_edit_panel(cq, text, markup)

# =======================
# UPLOAD (Option B - LINK RANGE, bot copy_message)
# =======================
@Client.on_callback_query(filters.regex(r"^adm:upload:(\d+):(.+):(.+):(.+)$"))
async def adm_upload(client, cq):
    await cq.answer()

    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    quality = uq(cq.matches[0].group(4))

    group_id = await ensure_group(sid, lang, season, quality)

    await cq.message.reply_text(
        f"📥 **{quality} Upload (Link Range)**\n\n"
        f"✅ Source channel/group-la irukkura **FIRST file** message link paste pannunga\n"
        f"✅ Source channel/group-la irukkura **LAST file** message link paste pannunga\n\n"
        f"Example:\n`https://t.me/c/3319100929/3`"
    )

    a1 = await client.ask(cq.message.chat.id, f"🔗 {quality} FIRST file link:", timeout=300)
    chat1, first_id = parse_tme_link(a1.text)
    if not chat1 or not first_id:
        return await cq.message.reply_text("❌ First link wrong. Retry pannunga.")

    a2 = await client.ask(cq.message.chat.id, f"🔗 {quality} LAST file link:", timeout=300)
    chat2, last_id = parse_tme_link(a2.text)
    if not chat2 or not last_id:
        return await cq.message.reply_text("❌ Last link wrong. Retry pannunga.")

    if str(chat1) != str(chat2):
        return await cq.message.reply_text("❌ First & Last link same channel/group illa. Same place link kudunga.")

    if last_id < first_id:
        return await cq.message.reply_text("❌ Last id smaller than first. Retry pannunga.")

    progress = await cq.message.reply_text("⏳ Copy + Save start...")

    saved = 0
    skipped = 0
    total = (last_id - first_id) + 1

    for i, mid in enumerate(range(first_id, last_id + 1), start=1):
        try:
            # Copy message to current chat, so bot can read media & get file_id
            copied = await client.copy_message(
                chat_id=cq.message.chat.id,
                from_chat_id=chat1,
                message_id=mid
            )

            if not copied or not copied.media:
                skipped += 1
            else:
                media = get_file_id(copied)
                if not media:
                    skipped += 1
                else:
                    await add_file(
                        group_id,
                        media.file_id,
                        copied.caption or "",
                        getattr(media, "message_type", "")
                    )
                    saved += 1
                    await asyncio.sleep(SAVE_DELAY)

            # progress update (avoid too many edits)
            if i == 1 or i == total or i % 5 == 0:
                try:
                    await progress.edit_text(
                        f"💾 Saving... `{i}/{total}`\n"
                        f"✅ Saved: `{saved}` | ⏭ Skipped: `{skipped}`\n"
                        f"⏳ Delay: `{SAVE_DELAY}s`"
                    )
                except Exception:
                    pass

        except Exception:
            skipped += 1
            continue

    try:
        await progress.edit_text(
            f"✅ **{quality} files added:** `{saved}`\n"
            f"⏭ Skipped: `{skipped}`\n"
            f"`{lang}` / `{season}`"
        )
    except Exception:
        pass

    # refresh quality buttons with updated counts
    qualities = await list_qualities(sid, lang, season)
    markup = await kb_qualities(sid, lang, season, qualities)
    text = f"Language: `{lang}`\nSeason: `{season}`\nSelect any Quality to upload."
    await safe_edit_panel(cq, text, markup)

# =======================
# DELETE (confirm)
# =======================
@Client.on_callback_query(filters.regex(r"^adm:dellang:(\d+):(.+)$"))
async def adm_dellang_confirm(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    text = f"⚠️ Delete Language Group?\n\nLanguage: `{lang}`\n\nThis deletes ALL inside."
    back = f"adm:lang:{sid}:{q(lang)}"
    yes = f"adm:yes_dellang:{sid}:{q(lang)}"
    await safe_edit_panel(cq, text, kb_confirm(back, yes))

@Client.on_callback_query(filters.regex(r"^adm:yes_dellang:(\d+):(.+)$"))
async def adm_dellang_yes(_, cq):
    await cq.answer("Deleted")
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    await delete_language(sid, lang)

    langs = await list_languages(sid)
    text = f"🗑 Deleted Language `{lang}` ✅\n\nSelect any Language:"
    await safe_edit_panel(cq, text, kb_langs(sid, langs))

@Client.on_callback_query(filters.regex(r"^adm:delseason:(\d+):(.+):(.+)$"))
async def adm_delseason_confirm(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    text = f"⚠️ Delete Season Group?\n\n`{lang}` / `{season}`\n\nThis deletes ALL inside."
    back = f"adm:season:{sid}:{q(lang)}:{q(season)}"
    yes = f"adm:yes_delseason:{sid}:{q(lang)}:{q(season)}"
    await safe_edit_panel(cq, text, kb_confirm(back, yes))

@Client.on_callback_query(filters.regex(r"^adm:yes_delseason:(\d+):(.+):(.+)$"))
async def adm_delseason_yes(_, cq):
    await cq.answer("Deleted")
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    await delete_season(sid, lang, season)

    seasons = await list_seasons(sid, lang)
    text = f"🗑 Deleted Season `{season}` ✅\n\nLanguage: `{lang}`"
    await safe_edit_panel(cq, text, kb_seasons(sid, lang, seasons))

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
    await safe_edit_panel(cq, text, kb_confirm(back, yes))

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
    text = f"🗑 Deleted Quality `{quality}` ✅\n\n`{lang}` / `{season}`"
    await safe_edit_panel(cq, text, markup)
