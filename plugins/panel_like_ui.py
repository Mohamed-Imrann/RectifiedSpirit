# plugins/panel_like_ui.py
import asyncio
from urllib.parse import quote, unquote

from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified, FloodWait, RPCError
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from pyromod import listen  # enables client.ask / client.listen

from info import ADMINS
from utils import get_file_id, auto_fetch_and_set_poster_and_meta

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

SAVE_DELAY = 1.2


def q(s: str) -> str:
    return quote(s or "", safe="")


def uq(s: str) -> str:
    return unquote(s or "")


# -------------------------
# PANEL RENDER (text/photo safe)
# -------------------------
async def _send_panel(client: Client, chat_id: int, title: str, published: int, poster_file_id: str | None):
    """
    Always returns a message (photo panel if poster exists, else text panel)
    """
    status = "✅ Published" if int(published) == 1 else "❌ Unpublished"
    caption = f"✅ **Series:** `{title}`\n\nStatus: **{status}**\n\nSelect option:"
    markup = kb_series_home(None, published)  # placeholder; we set series_id later outside
    # this function is called after we already know series_id in caller; so not used directly

    # kept for reference (not used)


async def edit_panel(msg, text: str, reply_markup=None):
    """
    Safe edit helper.
    NOTE: Telegram cannot convert text->photo or photo->text by editing.
    So we only edit inside same type; otherwise we will send a new panel.
    """
    try:
        if msg.photo:
            await msg.edit_caption(text, reply_markup=reply_markup)
        else:
            await msg.edit_text(text, reply_markup=reply_markup)
    except MessageNotModified:
        pass
    except RPCError:
        try:
            await msg.reply_text(text, reply_markup=reply_markup)
        except Exception:
            pass


async def send_or_replace_panel(client: Client, old_msg, series_id: int):
    """
    If poster exists -> send photo panel.
    Else -> send text panel.
    If old_msg exists, delete it (best-effort) and return new message.
    """
    row = await get_series_by_id(series_id)
    if not row:
        return None

    # row schema: id, title, poster_file_id, published, tmdb_id, year, rating, genres, overview
    sid, title, poster_file_id, published = int(row[0]), row[1], row[2], int(row[3])

    status = "✅ Published" if published == 1 else "❌ Unpublished"
    caption = f"✅ **Series:** `{title}`\n\nStatus: **{status}**\n\nSelect option:"
    markup = kb_series_home(sid, published)

    new_msg = None
    try:
        if poster_file_id:
            new_msg = await client.send_photo(old_msg.chat.id, poster_file_id, caption=caption, reply_markup=markup)
        else:
            new_msg = await client.send_message(old_msg.chat.id, caption, reply_markup=markup)
    except Exception:
        # fallback
        new_msg = await client.send_message(old_msg.chat.id, caption, reply_markup=markup)

    try:
        await old_msg.delete()
    except Exception:
        pass

    return new_msg


def kb_confirm(back_cb: str, yes_cb: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes Delete", callback_data=yes_cb)],
        [InlineKeyboardButton("⬅️ Cancel", callback_data=back_cb)],
    ])


def kb_series_home(series_id: int | None, published: int):
    # series_id None not used in callbacks; safe
    pub_txt = "✅ Published" if published == 1 else "❌ Unpublished"
    pub_emoji = "📦" if published == 1 else "📤"
    sid = series_id if series_id is not None else 0
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Languages", callback_data=f"adm:langs:{sid}")],
        [InlineKeyboardButton(f"{pub_emoji} {pub_txt}", callback_data=f"adm:publish:{sid}")],
        [InlineKeyboardButton("🖼 Poster", callback_data=f"adm:poster:{sid}")],
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
            rows.append([InlineKeyboardButton(s, callback_data=f"adm:season:{series_id}:{q(lang)}:{q(s)}")])
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
async def newseries_panel(client: Client, message):
    ask = await client.ask(message.chat.id, "📌 Series name anuppu:", timeout=180)
    title = (ask.text or "").strip()
    if not title:
        return await message.reply_text("❌ Empty title")

    sid = await upsert_series(title)

    # ✅ TMDB fetch status (but DO NOT vanish without response)
    fetch_msg = await message.reply_text("⏳ TMDB fetching…")
    try:
        await auto_fetch_and_set_poster_and_meta(client, sid, title, message.chat.id)
    except Exception:
        pass

    try:
        await fetch_msg.delete()
    except Exception:
        pass

    # ✅ send panel (photo panel if poster exists)
    row = await get_series_by_id(sid)
    published = int(row[3]) if row else 0
    poster_file_id = row[2] if row else None

    status = "✅ Published" if published == 1 else "❌ Unpublished"
    caption = f"✅ **Series:** `{title}`\n\nStatus: **{status}**\n\nSelect option:"
    markup = kb_series_home(sid, published)

    if poster_file_id:
        await message.reply_photo(poster_file_id, caption=caption, reply_markup=markup)
    else:
        await message.reply_text(caption, reply_markup=markup)


# =======================
# HOME
# =======================
@Client.on_callback_query(filters.regex(r"^adm:home:(\d+)$"))
async def adm_home(client: Client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    # ✅ replace panel with correct type (photo/text)
    await send_or_replace_panel(client, cq.message, sid)


# =======================
# PUBLISH TOGGLE
# =======================
@Client.on_callback_query(filters.regex(r"^adm:publish:(\d+)$"))
async def adm_publish(client: Client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    await toggle_publish(sid)
    # ✅ re-render panel (photo/text)
    await send_or_replace_panel(client, cq.message, sid)


# =======================
# POSTER (manual upload)
# =======================
@Client.on_callback_query(filters.regex(r"^adm:poster:(\d+)$"))
async def adm_poster(client: Client, cq):
    await cq.answer("Send poster photo", show_alert=False)
    sid = int(cq.matches[0].group(1))

    msg = await cq.message.reply_text("🖼 Poster photo anuppu (send photo).")
    pm = await client.listen(cq.message.chat.id)

    if not pm.photo:
        return await msg.edit_text("❌ Photo illa. Retry pannunga.")

    await set_series_poster(sid, pm.photo.file_id)
    await msg.edit_text("✅ Poster updated.")

    # ✅ re-render panel with photo now
    await send_or_replace_panel(client, cq.message, sid)


# =======================
# LANGUAGES
# =======================
@Client.on_callback_query(filters.regex(r"^adm:langs:(\d+)$"))
async def adm_langs(client: Client, cq):
    # ✅ avoid stuck loading
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    langs = await list_languages(sid)

    text = "Select any Language group to add seasons. Or click + to add new."
    # ✅ edit safe; if fail, send new
    await edit_panel(cq.message, text, kb_langs(sid, langs))


@Client.on_callback_query(filters.regex(r"^adm:addlang:(\d+)$"))
async def adm_addlang(client: Client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))

    ask = await client.ask(
        cq.message.chat.id,
        "🌐 Language name anuppu (ex: Multi Audio / Tamil):",
        timeout=180
    )
    lang = (ask.text or "").strip()
    if not lang:
        return await cq.message.reply_text("❌ Empty")

    await ensure_group(sid, lang, "season 1", "720p")

    langs = await list_languages(sid)
    await edit_panel(cq.message, "✅ Added language. Select any Language:", kb_langs(sid, langs))


@Client.on_callback_query(filters.regex(r"^adm:lang:(\d+):(.+)$"))
async def adm_lang(client: Client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    seasons = await list_seasons(sid, lang)
    text = f"Language: `{lang}`\nSelect any Seasons group."
    await edit_panel(cq.message, text, kb_seasons(sid, lang, seasons))


# =======================
# SEASONS
# =======================
@Client.on_callback_query(filters.regex(r"^adm:addseason:(\d+):(.+)$"))
async def adm_addseason(client: Client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    ask = await client.ask(cq.message.chat.id, "📦 Season name anuppu:", timeout=180)
    season = (ask.text or "").strip()
    if not season:
        return await cq.message.reply_text("❌ Empty")

    await ensure_group(sid, lang, season, "720p")
    seasons = await list_seasons(sid, lang)

    await edit_panel(cq.message, f"✅ Season Added. Language: `{lang}`", kb_seasons(sid, lang, seasons))


@Client.on_callback_query(filters.regex(r"^adm:season:(\d+):(.+):(.+)$"))
async def adm_season(client: Client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    qualities = await list_qualities(sid, lang, season)
    markup = await kb_qualities(sid, lang, season, qualities)

    text = f"Language: `{lang}`\nSeason: `{season}`\nSelect any Quality to upload."
    await edit_panel(cq.message, text, markup)


# =======================
# QUALITIES
# =======================
@Client.on_callback_query(filters.regex(r"^adm:addquality:(\d+):(.+):(.+)$"))
async def adm_addquality(client: Client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    ask = await client.ask(
        cq.message.chat.id,
        "🎞 Quality anuppu (ex: 720p / 1080p):",
        timeout=180
    )
    quality = (ask.text or "").strip()
    if not quality:
        return await cq.message.reply_text("❌ Empty")

    await ensure_group(sid, lang, season, quality)

    qualities = await list_qualities(sid, lang, season)
    markup = await kb_qualities(sid, lang, season, qualities)

    await edit_panel(cq.message, f"✅ Quality Added. `{lang}` / `{season}`\nSelect any Quality:", markup)


# =======================
# UPLOAD (RANGE FETCH FIXED)
# =======================

def _extract_forward_origin(m):
    """
    Returns (src_chat, src_msg_id) from forwarded message.
    Works for forward_from_chat OR forward_origin.
    """
    fchat = getattr(m, "forward_from_chat", None)
    fmid = getattr(m, "forward_from_message_id", None)
    if fchat and fmid:
        return fchat, int(fmid)

    origin = getattr(m, "forward_origin", None)
    if origin:
        ochat = getattr(origin, "chat", None)
        omid = getattr(origin, "message_id", None)
        if ochat and omid:
            return ochat, int(omid)

    return None, None


async def _ensure_peer(user_client: Client, chat_obj):
    """
    Cache peer properly to avoid 'Peer id invalid'.
    Prefer username; else fallback to id.
    """
    username = getattr(chat_obj, "username", None)
    cid = getattr(chat_obj, "id", None)

    if username:
        try:
            await user_client.get_chat(username)
            return username
        except Exception:
            pass

    if cid:
        try:
            await user_client.get_chat(int(cid))
            return int(cid)
        except Exception:
            pass

    return None


@Client.on_callback_query(filters.regex(r"^adm:upload:(\d+):(.+):(.+):(.+)$"))
async def adm_upload(client: Client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    quality = uq(cq.matches[0].group(4))

    group_id = await ensure_group(sid, lang, season, quality)

    user_client: Client | None = getattr(client, "user_client", None)
    if user_client is None:
        return await cq.message.reply_text("❌ user_client attach pannala. main.py la `bot.user_client = user` venum.")

    info = await cq.message.reply_text(
        f"📥 **{quality} Upload**\n\n"
        f"✅ Source channel/group-la irundhu **FIRST file message** forward pannunga."
    )

    first = await client.listen(cq.message.chat.id)
    src_chat1, first_id = _extract_forward_origin(first)
    if not src_chat1:
        return await info.edit_text("❌ Forward origin detect aagala. Direct source channel-la irundhu forward pannunga.")

    await info.edit_text("🔗 ✅ First ok.\n\n➡️ Ippo **LAST file message** ah forward pannunga.")

    last = await client.listen(cq.message.chat.id)
    src_chat2, last_id = _extract_forward_origin(last)
    if not src_chat2:
        return await info.edit_text("❌ Last forward origin detect aagala.")

    if int(src_chat1.id) != int(src_chat2.id):
        return await info.edit_text("❌ First & Last same channel/group illa. Same place-la irundhu forward pannunga.")

    peer_key = await _ensure_peer(user_client, src_chat1)
    if not peer_key:
        return await info.edit_text("❌ User account ku source channel access illa / join pannala / username illa.")

    if first_id > last_id:
        first_id, last_id = last_id, first_id

    progress = await cq.message.reply_text("⏳ Fetching messages…")

    msg_ids = list(range(first_id, last_id + 1))
    out = []

    CHUNK = 100
    for i in range(0, len(msg_ids), CHUNK):
        part = msg_ids[i:i + CHUNK]
        try:
            got = await user_client.get_messages(peer_key, part)
        except FloodWait as e:
            await asyncio.sleep(int(e.value) + 1)
            got = await user_client.get_messages(peer_key, part)
        except Exception:
            continue

        if not got:
            continue

        if isinstance(got, list):
            out.extend([m for m in got if m])
        else:
            out.append(got)

    out.sort(key=lambda x: int(x.id))

    if not out:
        return await progress.edit_text("❌ Range la messages fetch aagala. User join/permissions check pannunga.")

    media_msgs = []
    for m in out:
        if not m or not m.media:
            continue
        media = get_file_id(m)
        if not media:
            continue
        media_msgs.append((media.file_id, m.caption or "", getattr(media, "message_type", "")))

    if not media_msgs:
        return await progress.edit_text("❌ Range la media files illa.")

    total = len(media_msgs)
    saved = 0

    for file_id, caption, msg_type in media_msgs:
        await add_file(group_id, file_id, caption, msg_type)
        saved += 1
        try:
            await progress.edit_text(f"💾 Saving... `{saved}/{total}`")
        except Exception:
            pass
        await asyncio.sleep(SAVE_DELAY)

    await progress.edit_text(f"✅ **{quality} files added:** `{saved}`\n`{lang}` / `{season}`")

    qualities = await list_qualities(sid, lang, season)
    markup = await kb_qualities(sid, lang, season, qualities)
    await edit_panel(cq.message, f"Language: `{lang}`\nSeason: `{season}`\nSelect Quality:", markup)

    try:
        await info.delete()
    except Exception:
        pass


# =======================
# DELETE (confirm)
# =======================
@Client.on_callback_query(filters.regex(r"^adm:dellang:(\d+):(.+)$"))
async def adm_dellang_confirm(client: Client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    text = f"⚠️ Delete Language Group?\n\nLanguage: `{lang}`\n\nThis deletes ALL inside."
    back = f"adm:lang:{sid}:{q(lang)}"
    yes = f"adm:yes_dellang:{sid}:{q(lang)}"
    await edit_panel(cq.message, text, kb_confirm(back, yes))


@Client.on_callback_query(filters.regex(r"^adm:yes_dellang:(\d+):(.+)$"))
async def adm_dellang_yes(client: Client, cq):
    await cq.answer("Deleted")
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    await delete_language(sid, lang)
    langs = await list_languages(sid)
    await edit_panel(cq.message, f"🗑 Deleted Language `{lang}` ✅\n\nSelect any Language:", kb_langs(sid, langs))


@Client.on_callback_query(filters.regex(r"^adm:delseason:(\d+):(.+):(.+)$"))
async def adm_delseason_confirm(client: Client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    text = f"⚠️ Delete Season Group?\n\n`{lang}` / `{season}`\n\nThis deletes ALL inside."
    back = f"adm:season:{sid}:{q(lang)}:{q(season)}"
    yes = f"adm:yes_delseason:{sid}:{q(lang)}:{q(season)}"
    await edit_panel(cq.message, text, kb_confirm(back, yes))


@Client.on_callback_query(filters.regex(r"^adm:yes_delseason:(\d+):(.+):(.+)$"))
async def adm_delseason_yes(client: Client, cq):
    await cq.answer("Deleted")
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    await delete_season(sid, lang, season)
    seasons = await list_seasons(sid, lang)
    await edit_panel(cq.message, f"🗑 Deleted Season `{season}` ✅\n\nLanguage: `{lang}`", kb_seasons(sid, lang, seasons))


@Client.on_callback_query(filters.regex(r"^adm:delquality:(\d+):(.+):(.+):(.+)$"))
async def adm_delquality_confirm(client: Client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    quality = uq(cq.matches[0].group(4))

    text = f"⚠️ Delete Quality?\n\n`{lang}` / `{season}` / `{quality}`\n\nAll files inside will be deleted."
    back = f"adm:season:{sid}:{q(lang)}:{q(season)}"
    yes = f"adm:yes_delquality:{sid}:{q(lang)}:{q(season)}:{q(quality)}"
    await edit_panel(cq.message, text, kb_confirm(back, yes))


@Client.on_callback_query(filters.regex(r"^adm:yes_delquality:(\d+):(.+):(.+):(.+)$"))
async def adm_delquality_yes(client: Client, cq):
    await cq.answer("Deleted")
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    quality = uq(cq.matches[0].group(4))

    await delete_quality(sid, lang, season, quality)

    qualities = await list_qualities(sid, lang, season)
    markup = await kb_qualities(sid, lang, season, qualities)
    await edit_panel(cq.message, f"🗑 Deleted Quality `{quality}` ✅\n\n`{lang}` / `{season}`", markup)
