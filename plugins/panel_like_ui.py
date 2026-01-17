# plugins/panel_like_ui.py
import asyncio
from urllib.parse import quote, unquote

from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified, FloodWait, RPCError
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from pyromod import listen  # enables client.ask / client.listen

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
        if msg.photo:
            await msg.edit_caption(text, reply_markup=reply_markup)
        else:
            await msg.edit_text(text, reply_markup=reply_markup)
    except MessageNotModified:
        pass
    except RPCError:
        # If edit fails (deleted/old), send a new one as fallback
        await msg.reply_text(text, reply_markup=reply_markup)


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
async def newseries_panel(client: Client, message):
    ask = await client.ask(message.chat.id, "📌 Series name anuppu:", timeout=180)
    title = (ask.text or "").strip()
    if not title:
        return await message.reply_text("❌ Empty title")

    sid = await upsert_series(title)
    row = await get_series_by_id(sid)
    published = int(row[3]) if row else 0

    caption = f"✅ **Series:** `{title}`\n\nSelect option:"
    await message.reply_text(caption, reply_markup=kb_series_home(sid, published))


# =======================
# HOME (Back fix)
# =======================
@Client.on_callback_query(filters.regex(r"^adm:home:(\d+)$"))
async def adm_home(_, cq):
    sid = int(cq.matches[0].group(1))
    row = await get_series_by_id(sid)
    if not row:
        return await cq.answer("Not found", show_alert=True)

    _, title, _poster, published = row
    await cq.answer()

    caption = f"✅ **Series:** `{title}`\n\nSelect option:"
    await edit_panel(cq.message, caption, kb_series_home(sid, int(published)))


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
    status = "✅ Published" if int(new_val) == 1 else "❌ Unpublished"

    caption = f"✅ **Series:** `{title}`\n\nStatus: **{status}**\n\nSelect option:"
    await cq.answer(status, show_alert=True)
    await edit_panel(cq.message, caption, kb_series_home(sid, int(published)))


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

    _, title, _poster, published = row
    await msg.edit_text("✅ Poster updated.")
    cap = f"✅ **Series:** `{title}`\n\nSelect option:"
    await edit_panel(cq.message, cap, kb_series_home(sid, int(published)))


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

    # seed group so language exists
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
# UPLOAD (Option-B: forward first + forward last)
# =======================
def _forward_info(m):
    """
    Returns (chat_id, msg_id) from forwarded message, else (None, None)
    Works for forwarded from channels/groups.
    """
    fchat = getattr(m, "forward_from_chat", None)
    mid = getattr(m, "forward_from_message_id", None)
    if not fchat or not mid:
        return None, None
    return int(fchat.id), int(mid)


async def _user_fetch_range(user_client: Client, chat_id: int, first_id: int, last_id: int):
    """
    Fetch messages using USER client (bots can't GetHistory).
    Returns list of pyrogram Message objects.
    """
    if first_id > last_id:
        first_id, last_id = last_id, first_id

    # ensure peer is cached (prevents 'peer id invalid' sometimes)
    try:
        await user_client.get_chat(chat_id)
    except Exception:
        pass

    msg_ids = list(range(first_id, last_id + 1))
    out = []

    # chunk to avoid huge request
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

        # get_messages can return single or list
        if isinstance(got, list):
            out.extend([m for m in got if m])
        else:
            out.append(got)

    # sort by id asc
    out.sort(key=lambda x: int(x.id))
    return out


@Client.on_callback_query(filters.regex(r"^adm:upload:(\d+):(.+):(.+):(.+)$"))
async def adm_upload(client: Client, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    quality = uq(cq.matches[0].group(4))

    # create/get group id
    group_id = await ensure_group(sid, lang, season, quality)
    await cq.answer("Upload")

    # Need user client attached from main.py: bot.user_client = user
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

    # Fetch range using USER client
    msgs = await _user_fetch_range(user_client, chat_id, first_id, last_id)
    if not msgs:
        return await progress.edit_text("❌ Range la messages fetch aagala. User account channel join/check pannunga.")

    # Filter only media messages and save
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
            await progress.edit_text(
                f"💾 Saving... `{saved}/{total}`\n"
                f"⏳ Delay: `{SAVE_DELAY}s`"
            )
        except Exception:
            pass

        await asyncio.sleep(SAVE_DELAY)

    await progress.edit_text(f"✅ **{quality} files added:** `{saved}`\n`{lang}` / `{season}`")

    # refresh quality buttons with updated counts
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
