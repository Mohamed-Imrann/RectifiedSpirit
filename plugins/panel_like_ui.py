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


# ---------- safe edit helper ----------
async def edit_panel(msg, text: str, reply_markup=None):
    try:
        if getattr(msg, "photo", None):
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
            gid = int(gid_row[0]) if gid_row else 0
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


def build_series_caption(row) -> str:
    """
    row = (id, title, poster, published, tmdb_id, year, rating, genres, overview)
    """
    title = row[1] or ""
    published = int(row[3] or 0)

    year = (row[5] or "").strip()
    rating = row[6]
    genres = (row[7] or "").strip()
    overview = (row[8] or "").strip()

    meta = []
    if year:
        meta.append(year)
    if rating:
        try:
            meta.append(f"⭐ {float(rating):.1f}")
        except Exception:
            pass
    if genres:
        meta.append(genres)

    meta_txt = " • ".join(meta).strip()
    status = "✅ Published" if published == 1 else "❌ Unpublished"

    text = f"✅ **Series:** `{title}`\n"
    if meta_txt:
        text += f"`{meta_txt}`\n"
    text += f"\nStatus: **{status}**\n\nSelect option:"

    if overview:
        short = overview[:350].strip()
        if short:
            text += f"\n\n{short}"

    return text


async def send_or_update_series_panel(message, row):
    """
    If poster exists -> send photo panel
    else -> send text panel
    """
    sid = int(row[0])
    poster = row[2]
    published = int(row[3] or 0)
    cap = build_series_caption(row)

    if poster:
        await message.reply_photo(poster, caption=cap, reply_markup=kb_series_home(sid, published))
    else:
        await message.reply_text(cap, reply_markup=kb_series_home(sid, published))


# =======================
# /newseries (ADMIN PANEL)
# =======================
@Client.on_message(filters.command("newseries") & filters.user(ADMINS))
async def newseries_panel(client: Client, message):
    try:
        ask = await client.ask(message.chat.id, "📌 Series name anuppu:", timeout=180)
    except Exception as e:
        return await message.reply_text(f"❌ Ask failed: `{e}`")

    title = (ask.text or "").strip()
    if not title:
        return await message.reply_text("❌ Empty title")

    # 1) Insert series first (always)
    try:
        sid = await upsert_series(title)
    except Exception as e:
        return await message.reply_text(f"❌ DB error (upsert): `{e}`")

    # 2) Send immediate panel first (so user never feels 'no response')
    row = await get_series_by_id(sid)
    published = int(row[3]) if row else 0

    cap = f"✅ **Series:** `{title}`\n\nSelect option:"
    panel_msg = await message.reply_text(cap, reply_markup=kb_series_home(sid, published))

    # 3) TMDB fetch in background-style (but still awaited safely)
    #    Even if TMDB fails, panel already shown.
    try:
        from utils import auto_fetch_and_set_poster_and_meta

        # small status msg (optional)
        status = await message.reply_text("🎬 TMDB fetching…")

        ok = await auto_fetch_and_set_poster_and_meta(
            client=client,
            series_id=sid,
            title=title,
            chat_id=message.chat.id
        )

        try:
            await status.delete()
        except Exception:
            pass

        # 4) If poster fetched, refresh panel as PHOTO message
        if ok:
            row2 = await get_series_by_id(sid)
            if row2:
                _sid, _title, poster_file_id, _pub, *_ = row2
                if poster_file_id:
                    # delete old text panel and resend as photo panel
                    try:
                        await panel_msg.delete()
                    except Exception:
                        pass
                    await message.reply_photo(
                        poster_file_id,
                        caption=cap,
                        reply_markup=kb_series_home(sid, published)
                    )

    except Exception as e:
        # TMDB fail shouldn't break UI
        await message.reply_text(f"⚠️ TMDB fetch skipped: `{e}`")

# =======================
# HOME
# =======================
@Client.on_callback_query(filters.regex(r"^adm:home:(\d+)$"))
async def adm_home(_, cq):
    sid = int(cq.matches[0].group(1))
    row = await get_series_by_id(sid)
    if not row:
        return await cq.answer("Not found", show_alert=True)

    await cq.answer()
    cap = build_series_caption(row)
    await edit_panel(cq.message, cap, kb_series_home(sid, int(row[3] or 0)))


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

    await cq.answer("Updated", show_alert=False)
    cap = build_series_caption(row)
    await edit_panel(cq.message, cap, kb_series_home(sid, int(new_val)))


# =======================
# POSTER (manual)
# =======================
@Client.on_callback_query(filters.regex(r"^adm:poster:(\d+)$"))
async def adm_poster(client: Client, cq):
    sid = int(cq.matches[0].group(1))
    await cq.answer("Send poster photo")

    msg = await cq.message.reply_text("🖼 Poster photo anuppu (send photo).")
    pm = await client.listen(cq.message.chat.id)

    if not pm.photo:
        return await msg.edit_text("❌ Photo illa. Retry pannunga.")

    await set_series_poster(sid, pm.photo.file_id)

    row = await get_series_by_id(sid)
    if not row:
        return await msg.edit_text("✅ Poster updated. (series missing?)")

    await msg.edit_text("✅ Poster updated.")
    cap = build_series_caption(row)
    await edit_panel(cq.message, cap, kb_series_home(sid, int(row[3] or 0)))


# =======================
# LANGUAGES
# =======================
@Client.on_callback_query(filters.regex(r"^adm:langs:(\d+)$"))
async def adm_langs(_, cq):
    sid = int(cq.matches[0].group(1))
    langs = await list_languages(sid)
    await cq.answer()
    text = "Select any Language group to add seasons. Or click + to add new."
    await edit_panel(cq.message, text, kb_langs(sid, langs))


@Client.on_callback_query(filters.regex(r"^adm:addlang:(\d+)$"))
async def adm_addlang(client: Client, cq):
    sid = int(cq.matches[0].group(1))

    ask = await client.ask(
        cq.message.chat.id,
        "🌐 Language name anuppu (ex: Multi Audio / Tamil):",
        timeout=180
    )
    lang = (ask.text or "").strip()
    if not lang:
        return await cq.answer("Empty", show_alert=True)

    await ensure_group(sid, lang, "season 1", "720p")

    langs = await list_languages(sid)
    await cq.answer("Added")
    await edit_panel(cq.message, "✅ Added language. Select any Language:", kb_langs(sid, langs))


@Client.on_callback_query(filters.regex(r"^adm:lang:(\d+):(.+)$"))
async def adm_lang(_, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    seasons = await list_seasons(sid, lang)
    await cq.answer()
    text = f"Language: `{lang}`\nSelect any Seasons group."
    await edit_panel(cq.message, text, kb_seasons(sid, lang, seasons))


# =======================
# SEASONS
# =======================
@Client.on_callback_query(filters.regex(r"^adm:addseason:(\d+):(.+)$"))
async def adm_addseason(client: Client, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    ask = await client.ask(cq.message.chat.id, "📦 Season name anuppu:", timeout=180)
    season = (ask.text or "").strip()
    if not season:
        return await cq.answer("Empty", show_alert=True)

    await ensure_group(sid, lang, season, "720p")

    seasons = await list_seasons(sid, lang)
    await cq.answer("Added")
    await edit_panel(cq.message, f"✅ Season Added. Language: `{lang}`", kb_seasons(sid, lang, seasons))


@Client.on_callback_query(filters.regex(r"^adm:season:(\d+):(.+):(.+)$"))
async def adm_season(_, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    qualities = await list_qualities(sid, lang, season)
    markup = await kb_qualities(sid, lang, season, qualities)

    await cq.answer()
    text = f"Language: `{lang}`\nSeason: `{season}`\nSelect any Quality to upload."
    await edit_panel(cq.message, text, markup)


# =======================
# QUALITIES
# =======================
@Client.on_callback_query(filters.regex(r"^adm:addquality:(\d+):(.+):(.+)$"))
async def adm_addquality(client: Client, cq):
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
        return await cq.answer("Empty", show_alert=True)

    await ensure_group(sid, lang, season, quality)

    qualities = await list_qualities(sid, lang, season)
    markup = await kb_qualities(sid, lang, season, qualities)

    await cq.answer("Added")
    await edit_panel(cq.message, f"✅ Quality Added. `{lang}` / `{season}`\nSelect any Quality:", markup)


# =======================
# UPLOAD (forward first + forward last)
# =======================
def _forward_info(m):
    """
    Returns (chat_id, msg_id) from forwarded message, else (None, None)
    """
    fchat = getattr(m, "forward_from_chat", None)
    mid = getattr(m, "forward_from_message_id", None)
    if not fchat or not mid:
        return None, None
    return int(fchat.id), int(mid)


async def _ensure_peer(user_client: Client, chat_id: int) -> bool:
    """
    Ensure peer cached for user session (prevents Peer invalid / ID not found)
    """
    try:
        await user_client.get_chat(chat_id)
        return True
    except Exception:
        return False


async def _user_fetch_range(user_client: Client, chat_id: int, first_id: int, last_id: int):
    if first_id > last_id:
        first_id, last_id = last_id, first_id

    ok = await _ensure_peer(user_client, chat_id)
    if not ok:
        return None  # signal peer issue

    msg_ids = list(range(first_id, last_id + 1))
    out = []

    CHUNK = 100
    for i in range(0, len(msg_ids), CHUNK):
        part = msg_ids[i:i + CHUNK]
        try:
            got = await user_client.get_messages(chat_id, part)
        except FloodWait as e:
            await asyncio.sleep(int(e.value) + 1)
            got = await user_client.get_messages(chat_id, part)
        except Exception:
            continue

        if not got:
            continue

        if isinstance(got, list):
            out.extend([m for m in got if m])
        else:
            out.append(got)

    out.sort(key=lambda x: int(x.id))
    return out


@Client.on_callback_query(filters.regex(r"^adm:upload:(\d+):(.+):(.+):(.+)$"))
async def adm_upload(client: Client, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    quality = uq(cq.matches[0].group(4))

    group_id = await ensure_group(sid, lang, season, quality)
    await cq.answer("Upload")

    user_client: Client | None = getattr(client, "user_client", None)
    if user_client is None:
        return await cq.message.reply_text("❌ user_client attach pannala. main.py la `bot.user_client = user` venum.")

    info = await cq.message.reply_text(
        f"📥 **{quality} Upload**\n\n"
        f"✅ Ippo source channel/group-la irundhu **FIRST file message** ah **forward** pannunga.\n"
        f"✅ Appuram bot **LAST file message** ketkum.\n\n"
        f"(Forward dhaan. link paste pannadheenga.)"
    )

    first_m = await client.listen(cq.message.chat.id)
    chat_id, first_id = _forward_info(first_m)
    if not chat_id:
        return await info.edit_text("❌ First message forward varala. Source channel message-ah forward pannunga.")

    await info.edit_text("🔗 ✅ First ok.\n\n➡️ Ippo **LAST file message** ah forward pannunga.")

    last_m = await client.listen(cq.message.chat.id)
    chat_id2, last_id = _forward_info(last_m)
    if not chat_id2 or chat_id2 != chat_id:
        return await info.edit_text("❌ Last message forward wrong. Same channel/group-la irundhu forward pannunga.")

    progress = await cq.message.reply_text("⏳ Fetching messages…")

    msgs = await _user_fetch_range(user_client, chat_id, first_id, last_id)
    if msgs is None:
        return await progress.edit_text(
            "❌ User session peer resolve aagala.\n\n"
            "✅ user account **source channel/group open pannitu** (once) try pannunga.\n"
            "✅ user account **join** la confirm pannunga."
        )

    if not msgs:
        return await progress.edit_text("❌ Range la messages fetch aagala. User account channel join/check pannunga.")

    media_msgs = []
    for m in msgs:
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
            await progress.edit_text(f"💾 Saving... `{saved}/{total}`\n⏳ Delay: `{SAVE_DELAY}s`")
        except Exception:
            pass
        await asyncio.sleep(SAVE_DELAY)

    await progress.edit_text(f"✅ **{quality} files added:** `{saved}`\n`{lang}` / `{season}`")

    qualities = await list_qualities(sid, lang, season)
    markup = await kb_qualities(sid, lang, season, qualities)
    text = f"Language: `{lang}`\nSeason: `{season}`\nSelect any Quality to upload."
    await edit_panel(cq.message, text, markup)

    try:
        await info.delete()
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

    await cq.answer()
    await edit_panel(cq.message, text, kb_confirm(back, yes))


@Client.on_callback_query(filters.regex(r"^adm:yes_dellang:(\d+):(.+)$"))
async def adm_dellang_yes(_, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    await delete_language(sid, lang)

    langs = await list_languages(sid)
    await cq.answer("Deleted")
    await edit_panel(cq.message, f"🗑 Deleted Language `{lang}` ✅\n\nSelect any Language:", kb_langs(sid, langs))


@Client.on_callback_query(filters.regex(r"^adm:delseason:(\d+):(.+):(.+)$"))
async def adm_delseason_confirm(_, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    text = f"⚠️ Delete Season Group?\n\n`{lang}` / `{season}`\n\nThis deletes ALL inside."
    back = f"adm:season:{sid}:{q(lang)}:{q(season)}"
    yes = f"adm:yes_delseason:{sid}:{q(lang)}:{q(season)}"

    await cq.answer()
    await edit_panel(cq.message, text, kb_confirm(back, yes))


@Client.on_callback_query(filters.regex(r"^adm:yes_delseason:(\d+):(.+):(.+)$"))
async def adm_delseason_yes(_, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    await delete_season(sid, lang, season)

    seasons = await list_seasons(sid, lang)
    await cq.answer("Deleted")
    await edit_panel(cq.message, f"🗑 Deleted Season `{season}` ✅\n\nLanguage: `{lang}`", kb_seasons(sid, lang, seasons))


@Client.on_callback_query(filters.regex(r"^adm:delquality:(\d+):(.+):(.+):(.+)$"))
async def adm_delquality_confirm(_, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    quality = uq(cq.matches[0].group(4))

    text = f"⚠️ Delete Quality?\n\n`{lang}` / `{season}` / `{quality}`\n\nAll files inside will be deleted."
    back = f"adm:season:{sid}:{q(lang)}:{q(season)}"
    yes = f"adm:yes_delquality:{sid}:{q(lang)}:{q(season)}:{q(quality)}"

    await cq.answer()
    await edit_panel(cq.message, text, kb_confirm(back, yes))


@Client.on_callback_query(filters.regex(r"^adm:yes_delquality:(\d+):(.+):(.+):(.+)$"))
async def adm_delquality_yes(_, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    quality = uq(cq.matches[0].group(4))

    await delete_quality(sid, lang, season, quality)

    qualities = await list_qualities(sid, lang, season)
    markup = await kb_qualities(sid, lang, season, qualities)

    await cq.answer("Deleted")
    await edit_panel(cq.message, f"🗑 Deleted Quality `{quality}` ✅\n\n`{lang}` / `{season}`", markup)
