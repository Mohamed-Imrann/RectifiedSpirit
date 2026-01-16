# plugins/panel_like_ui.py
import asyncio
from urllib.parse import quote, unquote

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from info import ADMINS
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
    set_series_poster,   # ✅ poster
)

SAVE_DELAY = 1.2


def q(s: str) -> str:
    return quote(s, safe="")


def uq(s: str) -> str:
    return unquote(s)


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
        rows.append([InlineKeyboardButton("+ New Row", callback_data=f"adm:addlang:{series_id}")])
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
                InlineKeyboardButton("+", callback_data=f"adm:addseason:{series_id}:{q(lang)}")
            ])
        rows.append([InlineKeyboardButton("+ New Row", callback_data=f"adm:addseason:{series_id}:{q(lang)}")])
    else:
        rows.append([InlineKeyboardButton("+ Add First Item", callback_data=f"adm:addseason:{series_id}:{q(lang)}")])

    rows.append([InlineKeyboardButton("🗑 Delete Language Group", callback_data=f"adm:dellang:{series_id}:{q(lang)}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"adm:langs:{series_id}")])
    return InlineKeyboardMarkup(rows)


async def kb_qualities(series_id: int, lang: str, season: str, qualities: list[str]):
    rows = []

    if qualities:
        for qu in qualities:
            gid = await get_group_id_value(series_id, lang, season, qu)
            cnt = await count_files_in_group(gid) if gid else 0

            # ✅ count admin only (this file is admin panel, so always ok)
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

        rows.append([InlineKeyboardButton("+ New Row", callback_data=f"adm:addquality:{series_id}:{q(lang)}:{q(season)}")])
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
# HOME (Back fix)
# =======================
@Client.on_callback_query(filters.regex(r"^adm:home:(\d+)$"))
async def adm_home(client, cq):
    sid = int(cq.matches[0].group(1))

    row = await get_series_by_id(sid)
    if not row:
        await cq.answer("Not found", show_alert=True)
        return

    _, title, _poster, published = row

    # ✅ Always respond fast (avoid endless loading)
    await cq.answer()

    # ✅ Send NEW message instead of edit (no crash)
    caption = f"✅ **Series:** `{title}`\n\nSelect option:"
    await cq.message.reply_text(
        caption,
        reply_markup=kb_series_home(sid, published)
    )

    # Optional: delete old panel message
    try:
        await cq.message.delete()
    except Exception:
        pass

# =======================
# PUBLISH TOGGLE
# =======================
@Client.on_callback_query(filters.regex(r"^adm:publish:(\d+)$"))
async def adm_publish(_, cq):
    sid = int(cq.matches[0].group(1))
    new_val = await toggle_publish(sid)

    row = await get_series_by_id(sid)
    if not row:
        return await cq.answer("Not found", show_alert=True)

    _, title, _poster, published = row
    status = "✅ Published" if new_val == 1 else "❌ Unpublished"

    caption = f"✅ **Series:** `{title}`\n\nStatus: **{status}**\n\nSelect option:"
    if cq.message.photo:
        await cq.message.edit_caption(caption, reply_markup=kb_series_home(sid, published))
    else:
        await cq.message.edit_text(caption, reply_markup=kb_series_home(sid, published))

    await cq.answer(status, show_alert=True)


# =======================
# POSTER
# =======================
@Client.on_callback_query(filters.regex(r"^adm:poster:(\d+)$"))
async def adm_poster(client, cq):
    sid = int(cq.matches[0].group(1))
    await cq.answer("Send poster photo")

    msg = await cq.message.reply_text("🖼 Poster photo anuppu (send photo).")
    pm = await client.listen(cq.message.chat.id)

    if not pm.photo:
        try:
            await msg.edit_text("❌ Photo illa. Retry pannunga.")
        except Exception:
            pass
        return

    await set_series_poster(sid, pm.photo.file_id)

    row = await get_series_by_id(sid)
    if row:
        _, title, _poster, published = row
        try:
            await msg.edit_text("✅ Poster updated.")
        except Exception:
            pass
        # go home
        cap = f"✅ **Series:** `{title}`\n\nSelect option:"
        if cq.message.photo:
            await cq.message.edit_caption(cap, reply_markup=kb_series_home(sid, published))
        else:
            await cq.message.edit_text(cap, reply_markup=kb_series_home(sid, published))


# =======================
# LANGUAGES
# =======================
@Client.on_callback_query(filters.regex(r"^adm:langs:(\d+)$"))
async def adm_langs(_, cq):
    sid = int(cq.matches[0].group(1))
    langs = await list_languages(sid)

    text = "Select any Language group to add seasons. Or click + to add new."
    if cq.message.photo:
        await cq.message.edit_caption(text, reply_markup=kb_langs(sid, langs))
    else:
        await cq.message.edit_text(text, reply_markup=kb_langs(sid, langs))
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^adm:addlang:(\d+)$"))
async def adm_addlang(client, cq):
    sid = int(cq.matches[0].group(1))
    ask = await client.ask(cq.message.chat.id, "🌐 Language name anuppu (ex: Multi Audio / Tamil):", timeout=180)
    lang = (ask.text or "").strip()
    if not lang:
        return await cq.answer("Empty", show_alert=True)

    # create seed group so language exists
    await ensure_group(sid, lang, "season 1", "720p")

    langs = await list_languages(sid)
    text = "✅ Language Added. Select any Language:"
    if cq.message.photo:
        await cq.message.edit_caption(text, reply_markup=kb_langs(sid, langs))
    else:
        await cq.message.edit_text(text, reply_markup=kb_langs(sid, langs))
    await cq.answer("Added")


@Client.on_callback_query(filters.regex(r"^adm:lang:(\d+):(.+)$"))
async def adm_lang(_, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    seasons = await list_seasons(sid, lang)
    text = f"Language: `{lang}`\nSelect any Seasons group."
    if cq.message.photo:
        await cq.message.edit_caption(text, reply_markup=kb_seasons(sid, lang, seasons))
    else:
        await cq.message.edit_text(text, reply_markup=kb_seasons(sid, lang, seasons))
    await cq.answer()


# =======================
# SEASONS
# =======================
@Client.on_callback_query(filters.regex(r"^adm:addseason:(\d+):(.+)$"))
async def adm_addseason(client, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    ask = await client.ask(cq.message.chat.id, "📦 Season name anuppu:", timeout=180)
    season = (ask.text or "").strip()
    if not season:
        return await cq.answer("Empty", show_alert=True)

    await ensure_group(sid, lang, season, "720p")

    seasons = await list_seasons(sid, lang)
    text = f"✅ Season Added. Language: `{lang}`"
    if cq.message.photo:
        await cq.message.edit_caption(text, reply_markup=kb_seasons(sid, lang, seasons))
    else:
        await cq.message.edit_text(text, reply_markup=kb_seasons(sid, lang, seasons))
    await cq.answer("Added")


@Client.on_callback_query(filters.regex(r"^adm:season:(\d+):(.+):(.+)$"))
async def adm_season(_, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    qualities = await list_qualities(sid, lang, season)
    markup = await kb_qualities(sid, lang, season, qualities)

    text = f"Language: `{lang}`\nSeason: `{season}`\nSelect any Quality to upload."
    if cq.message.photo:
        await cq.message.edit_caption(text, reply_markup=markup)
    else:
        await cq.message.edit_text(text, reply_markup=markup)
    await cq.answer()


# =======================
# QUALITIES
# =======================
@Client.on_callback_query(filters.regex(r"^adm:addquality:(\d+):(.+):(.+)$"))
async def adm_addquality(client, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    ask = await client.ask(cq.message.chat.id, "🎞 Quality anuppu (ex: 720p / 1080p):", timeout=180)
    quality = (ask.text or "").strip()
    if not quality:
        return await cq.answer("Empty", show_alert=True)

    await ensure_group(sid, lang, season, quality)

    qualities = await list_qualities(sid, lang, season)
    markup = await kb_qualities(sid, lang, season, qualities)

    text = f"✅ Quality Added. `{lang}` / `{season}`\nSelect any Quality:"
    if cq.message.photo:
        await cq.message.edit_caption(text, reply_markup=markup)
    else:
        await cq.message.edit_text(text, reply_markup=markup)
    await cq.answer("Added")


# =======================
# UPLOAD (Quality click) + PROGRESS
# =======================
@Client.on_callback_query(filters.regex(r"^adm:upload:(\d+):(.+):(.+):(.+)$"))
async def adm_upload(client, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    quality = uq(cq.matches[0].group(4))

    group_id = await ensure_group(sid, lang, season, quality)
    await cq.answer("Upload mode")

    info = await cq.message.reply_text(
        f"📥 **Upload Mode**\n\n"
        f"Language: `{lang}`\nSeason: `{season}`\nQuality: `{quality}`\n\n"
        f"Files send pannunga… finish panna `/done`"
    )

    progress = await cq.message.reply_text("⏳ Waiting for files…")

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
            await progress.edit_text(
                f"💾 Saving... `{saved}/{total}`\n"
                f"⏳ Delay: `{SAVE_DELAY}s` each"
            )
        except Exception:
            pass

        await asyncio.sleep(SAVE_DELAY)

    await cq.message.reply_text(
        f"✅ **{quality} files added:** `{saved}`\n"
        f"`{lang}` / `{season}`"
    )

    # refresh quality buttons with updated counts
    qualities = await list_qualities(sid, lang, season)
    markup = await kb_qualities(sid, lang, season, qualities)

    text = f"Language: `{lang}`\nSeason: `{season}`\nSelect any Quality to upload."
    if cq.message.photo:
        await cq.message.edit_caption(text, reply_markup=markup)
    else:
        await cq.message.edit_text(text, reply_markup=markup)

    try:
        await info.delete()
    except Exception:
        pass
    try:
        await progress.delete()
    except Exception:
        pass


# =======================
# DELETE (confirm)
# =======================
@Client.on_callback_query(filters.regex(r"^adm:dellang:(\d+):(.+)$"))
async def adm_dellang_confirm(_, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    text = f"⚠️ Delete Language Group?\n\nLanguage: `{lang}`\n\nThis deletes ALL inside."
    back = f"adm:lang:{sid}:{q(lang)}"
    yes = f"adm:yes_dellang:{sid}:{q(lang)}"

    if cq.message.photo:
        await cq.message.edit_caption(text, reply_markup=kb_confirm(back, yes))
    else:
        await cq.message.edit_text(text, reply_markup=kb_confirm(back, yes))
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^adm:yes_dellang:(\d+):(.+)$"))
async def adm_dellang_yes(_, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    await delete_language(sid, lang)

    langs = await list_languages(sid)
    text = f"🗑 Deleted Language `{lang}` ✅\n\nSelect any Language:"
    if cq.message.photo:
        await cq.message.edit_caption(text, reply_markup=kb_langs(sid, langs))
    else:
        await cq.message.edit_text(text, reply_markup=kb_langs(sid, langs))
    await cq.answer("Deleted")


@Client.on_callback_query(filters.regex(r"^adm:delseason:(\d+):(.+):(.+)$"))
async def adm_delseason_confirm(_, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    text = f"⚠️ Delete Season Group?\n\n`{lang}` / `{season}`\n\nThis deletes ALL inside."
    back = f"adm:season:{sid}:{q(lang)}:{q(season)}"
    yes = f"adm:yes_delseason:{sid}:{q(lang)}:{q(season)}"

    if cq.message.photo:
        await cq.message.edit_caption(text, reply_markup=kb_confirm(back, yes))
    else:
        await cq.message.edit_text(text, reply_markup=kb_confirm(back, yes))
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^adm:yes_delseason:(\d+):(.+):(.+)$"))
async def adm_delseason_yes(_, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    await delete_season(sid, lang, season)

    seasons = await list_seasons(sid, lang)
    text = f"🗑 Deleted Season `{season}` ✅\n\nLanguage: `{lang}`"
    if cq.message.photo:
        await cq.message.edit_caption(text, reply_markup=kb_seasons(sid, lang, seasons))
    else:
        await cq.message.edit_text(text, reply_markup=kb_seasons(sid, lang, seasons))
    await cq.answer("Deleted")


@Client.on_callback_query(filters.regex(r"^adm:delquality:(\d+):(.+):(.+):(.+)$"))
async def adm_delquality_confirm(_, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    quality = uq(cq.matches[0].group(4))

    text = f"⚠️ Delete Quality?\n\n`{lang}` / `{season}` / `{quality}`\n\nAll files inside will be deleted."
    back = f"adm:season:{sid}:{q(lang)}:{q(season)}"
    yes = f"adm:yes_delquality:{sid}:{q(lang)}:{q(season)}:{q(quality)}"

    if cq.message.photo:
        await cq.message.edit_caption(text, reply_markup=kb_confirm(back, yes))
    else:
        await cq.message.edit_text(text, reply_markup=kb_confirm(back, yes))
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^adm:yes_delquality:(\d+):(.+):(.+):(.+)$"))
async def adm_delquality_yes(_, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    quality = uq(cq.matches[0].group(4))

    await delete_quality(sid, lang, season, quality)

    qualities = await list_qualities(sid, lang, season)
    markup = await kb_qualities(sid, lang, season, qualities)
    text = f"🗑 Deleted Quality `{quality}` ✅\n\n`{lang}` / `{season}`"
    if cq.message.photo:
        await cq.message.edit_caption(text, reply_markup=markup)
    else:
        await cq.message.edit_text(text, reply_markup=markup)
    await cq.answer("Deleted")
