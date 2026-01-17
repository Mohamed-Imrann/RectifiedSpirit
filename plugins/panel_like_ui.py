# plugins/panel_like_ui.py
import asyncio
from urllib.parse import quote, unquote

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import MessageNotModified, FloodWait

from pyromod import listen

from info import ADMINS
from utils import (
    get_file_id,
    auto_fetch_and_set_poster_and_meta,
)

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


# =========================
# HELPERS
# =========================
def q(s: str) -> str:
    return quote(s or "", safe="")


def uq(s: str) -> str:
    return unquote(s or "")


async def edit_panel(msg, text: str, reply_markup=None):
    try:
        if msg.photo:
            await msg.edit_caption(text, reply_markup=reply_markup)
        else:
            await msg.edit_text(text, reply_markup=reply_markup)
    except MessageNotModified:
        pass
    except Exception:
        try:
            await msg.reply_text(text, reply_markup=reply_markup)
        except Exception:
            pass


async def send_series_panel(client: Client, chat_id: int, series_id: int):
    row = await get_series_by_id(series_id)
    if not row:
        return

    sid, title, poster_file_id, published = row
    caption = f"🎬 **{title}**\n\nSelect option:"

    if poster_file_id:
        await client.send_photo(
            chat_id,
            poster_file_id,
            caption=caption,
            reply_markup=kb_series_home(sid, int(published)),
        )
    else:
        await client.send_message(
            chat_id,
            caption,
            reply_markup=kb_series_home(sid, int(published)),
        )


# =========================
# KEYBOARDS
# =========================
def kb_series_home(series_id: int, published: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Languages", callback_data=f"adm:langs:{series_id}")],
        [InlineKeyboardButton(
            "📦 Published" if published else "📤 Unpublished",
            callback_data=f"adm:publish:{series_id}"
        )],
        [InlineKeyboardButton("🖼 Poster", callback_data=f"adm:poster:{series_id}")]
    ])


def kb_langs(series_id: int, langs: list[str]):
    rows = [[InlineKeyboardButton(l, callback_data=f"adm:lang:{series_id}:{q(l)}")] for l in langs]
    rows.append([InlineKeyboardButton("+ Add Language", callback_data=f"adm:addlang:{series_id}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"adm:home:{series_id}")])
    return InlineKeyboardMarkup(rows)


def kb_seasons(series_id: int, lang: str, seasons: list[str]):
    rows = [[InlineKeyboardButton(s, callback_data=f"adm:season:{series_id}:{q(lang)}:{q(s)}")] for s in seasons]
    rows.append([InlineKeyboardButton("+ Add Season", callback_data=f"adm:addseason:{series_id}:{q(lang)}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"adm:langs:{series_id}")])
    return InlineKeyboardMarkup(rows)


async def kb_qualities(series_id: int, lang: str, season: str, qualities: list[str]):
    rows = []
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
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"adm:lang:{series_id}:{q(lang)}")])
    return InlineKeyboardMarkup(rows)


# =========================
# /newseries
# =========================
@Client.on_message(filters.command("newseries") & filters.user(ADMINS))
async def newseries(client: Client, message):
    ask = await client.ask(message.chat.id, "📌 Series name anuppu:")
    title = (ask.text or "").strip()
    if not title:
        return

    sid = await upsert_series(title)

    # 🔥 AUTO FETCH TMDB (poster + meta)
    await auto_fetch_and_set_poster_and_meta(
        client,
        series_id=sid,
        title=title,
        chat_id=message.chat.id
    )

    # show panel with poster (if fetched)
    await send_series_panel(client, message.chat.id, sid)


# =========================
# HOME
# =========================
@Client.on_callback_query(filters.regex(r"^adm:home:(\d+)$"))
async def adm_home(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    row = await get_series_by_id(sid)
    if not row:
        return
    await edit_panel(
        cq.message,
        f"🎬 **{row[1]}**\n\nSelect option:",
        kb_series_home(sid, int(row[3]))
    )


# =========================
# PUBLISH
# =========================
@Client.on_callback_query(filters.regex(r"^adm:publish:(\d+)$"))
async def adm_publish(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    new = await toggle_publish(sid)
    row = await get_series_by_id(sid)
    await edit_panel(
        cq.message,
        f"🎬 **{row[1]}**\n\nStatus: {'Published' if new else 'Unpublished'}",
        kb_series_home(sid, int(new))
    )


# =========================
# POSTER (MANUAL)
# =========================
@Client.on_callback_query(filters.regex(r"^adm:poster:(\d+)$"))
async def adm_poster(client: Client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))

    msg = await cq.message.reply_text("🖼 Poster photo anuppu (send photo).")
    pm = await client.listen(cq.message.chat.id)

    if not pm.photo:
        return await msg.edit_text("❌ Photo illa.")

    await set_series_poster(sid, pm.photo.file_id)

    try:
        await msg.delete()
        await cq.message.delete()
    except Exception:
        pass

    await send_series_panel(client, cq.message.chat.id, sid)


# =========================
# LANGUAGES
# =========================
@Client.on_callback_query(filters.regex(r"^adm:langs:(\d+)$"))
async def adm_langs(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    langs = await list_languages(sid)
    await edit_panel(cq.message, "Select Language:", kb_langs(sid, langs))


@Client.on_callback_query(filters.regex(r"^adm:addlang:(\d+)$"))
async def adm_addlang(client: Client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    ask = await client.ask(cq.message.chat.id, "Language name:")
    await ensure_group(sid, ask.text.strip(), "Season 1", "720p")
    langs = await list_languages(sid)
    await edit_panel(cq.message, "Language added", kb_langs(sid, langs))


# =========================
# SEASONS
# =========================
@Client.on_callback_query(filters.regex(r"^adm:lang:(\d+):(.+)$"))
async def adm_seasons(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    seasons = await list_seasons(sid, lang)
    await edit_panel(cq.message, f"{lang} seasons:", kb_seasons(sid, lang, seasons))


@Client.on_callback_query(filters.regex(r"^adm:addseason:(\d+):(.+)$"))
async def adm_addseason(client: Client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    ask = await client.ask(cq.message.chat.id, "Season name:")
    await ensure_group(sid, lang, ask.text.strip(), "720p")
    seasons = await list_seasons(sid, lang)
    await edit_panel(cq.message, "Season added", kb_seasons(sid, lang, seasons))


# =========================
# QUALITIES
# =========================
@Client.on_callback_query(filters.regex(r"^adm:season:(\d+):(.+):(.+)$"))
async def adm_qualities(_, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    qualities = await list_qualities(sid, lang, season)
    await edit_panel(
        cq.message,
        f"{lang} / {season}\nSelect quality:",
        await kb_qualities(sid, lang, season, qualities)
    )


# =========================
# UPLOAD (forward range)
# =========================
@Client.on_callback_query(filters.regex(r"^adm:upload:(\d+):(.+):(.+):(.+)$"))
async def adm_upload(client: Client, cq):
    await cq.answer()
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    quality = uq(cq.matches[0].group(4))

    group_id = await ensure_group(sid, lang, season, quality)
    user = getattr(client, "user_client", None)
    if not user:
        return await cq.message.reply_text("❌ user_client not attached")

    info = await cq.message.reply_text("➡️ Forward FIRST file")
    first = await client.listen(cq.message.chat.id)
    chat_id = first.forward_from_chat.id
    first_id = first.forward_from_message_id

    await info.edit_text("➡️ Forward LAST file")
    last = await client.listen(cq.message.chat.id)
    last_id = last.forward_from_message_id

    progress = await cq.message.reply_text("⏳ Fetching…")

    msgs = await user.get_messages(chat_id, list(range(first_id, last_id + 1)))
    saved = 0

    for m in msgs:
        media = get_file_id(m)
        if not media:
            continue
        await add_file(group_id, media.file_id, m.caption or "", media.message_type)
        saved += 1
        await asyncio.sleep(SAVE_DELAY)

    await progress.edit_text(f"✅ {quality} uploaded: {saved} files")
