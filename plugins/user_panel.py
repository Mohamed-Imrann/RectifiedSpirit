import logging
from urllib.parse import quote, unquote

from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery

from database.series_sql import (
    find_series,
    get_series_by_id,
    list_languages,
    list_seasons,
    list_qualities,
    get_group_id_value,
    get_files,
)

logger = logging.getLogger(__name__)

# -------------------------
# Helpers
# -------------------------
def q(s: str) -> str:
    return quote(s or "", safe="")

def uq(s: str) -> str:
    return unquote(s or "")

def home_kb(series_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Languages", callback_data=f"usr:langs:{series_id}")]
    ])

async def _edit_text_or_caption(msg, text: str, reply_markup=None):
    """Safe edit helper for both photo-caption messages and text messages"""
    try:
        if getattr(msg, "photo", None):
            await msg.edit_caption(text, reply_markup=reply_markup)
        else:
            await msg.edit_text(text, reply_markup=reply_markup)
    except MessageNotModified:
        pass


# -------- USER SEARCH (only published) --------
@Client.on_message(filters.text & filters.incoming & ~filters.command(["newseries", "newseriesui", "start"]))
async def user_search(client: Client, message: Message):
    query = (message.text or "").strip()
    if not query:
        return

    row = await find_series(query)
    if not row:
        return  # silent if not found

    series_id = int(row[0])
    title = row[1] or ""
    poster = row[2]
    published = int(row[3] or 0)

    if published != 1:
        return

    year = (row[5] or "").strip()
    rating = row[6]
    genres = (row[7] or "").strip()
    overview = (row[8] or "").strip()

    meta_line = []
    if year:
        meta_line.append(year)
    if rating:
        try:
            meta_line.append(f"⭐ {float(rating):.1f}")
        except Exception:
            pass
    if genres:
        meta_line.append(genres)

    meta_txt = " • ".join(meta_line).strip()
    text = f"🎬 **{title}**"
    if meta_txt:
        text += f"\n`{meta_txt}`"
    text += "\n\nSelect option:"

    if overview:
        short = overview[:350].strip()
        if short:
            text += f"\n\n{short}"

    if poster:
        await message.reply_photo(poster, caption=text, reply_markup=home_kb(series_id))
    else:
        await message.reply_text(text, reply_markup=home_kb(series_id))

    logger.info(f"User searched '{query}' -> series_id={series_id}")


# -------- LANGUAGES --------
@Client.on_callback_query(filters.regex(r"^usr:langs:(\d+)$"))
async def usr_langs(_, cq: CallbackQuery):
    sid = int(cq.matches[0].group(1))
    langs = await list_languages(sid)
    if not langs:
        return await cq.answer("No languages", show_alert=True)

    rows = [[InlineKeyboardButton(l, callback_data=f"usr:lang:{sid}:{q(l)}")] for l in langs]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"usr:home:{sid}")])

    await cq.answer()
    await cq.message.edit_reply_markup(InlineKeyboardMarkup(rows))
    logger.debug(f"Languages listed for series_id={sid}: {langs}")


@Client.on_callback_query(filters.regex(r"^usr:home:(\d+)$"))
async def usr_home(_, cq: CallbackQuery):
    sid = int(cq.matches[0].group(1))
    row = await get_series_by_id(sid)
    if not row:
        return await cq.answer("Not found", show_alert=True)

    title = row[1] or ""
    poster = row[2]
    published = int(row[3] or 0)

    if published != 1:
        return await cq.answer("Unpublished", show_alert=True)

    year = (row[5] or "").strip()
    rating = row[6]
    genres = (row[7] or "").strip()
    overview = (row[8] or "").strip()

    meta_line = []
    if year:
        meta_line.append(year)
    if rating:
        try:
            meta_line.append(f"⭐ {float(rating):.1f}")
        except Exception:
            pass
    if genres:
        meta_line.append(genres)

    meta_txt = " • ".join(meta_line).strip()
    text = f"🎬 **{title}**"
    if meta_txt:
        text += f"\n`{meta_txt}`"
    text += "\n\nSelect option:"

    if overview:
        short = overview[:350].strip()
        if short:
            text += f"\n\n{short}"

    await cq.answer()
    await _edit_text_or_caption(cq.message, text, reply_markup=home_kb(sid))
    logger.debug(f"Returned to home for series_id={sid}")


# -------- SEASONS --------
@Client.on_callback_query(filters.regex(r"^usr:lang:(\d+):(.+)$"))
async def usr_seasons(_, cq: CallbackQuery):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    seasons = await list_seasons(sid, lang)
    if not seasons:
        return await cq.answer("No seasons", show_alert=True)

    rows = [
        [InlineKeyboardButton(s, callback_data=f"usr:season:{sid}:{q(lang)}:{q(s)}")]
        for s in seasons
    ]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"usr:langs:{sid}")])

    await cq.answer()
    await cq.message.edit_reply_markup(InlineKeyboardMarkup(rows))
    logger.debug(f"Seasons listed for series_id={sid}, lang={lang}: {seasons}")


# -------- QUALITIES --------
@Client.on_callback_query(filters.regex(r"^usr:season:(\d+):(.+):(.+)$"))
async def usr_qualities(_, cq: CallbackQuery):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    qualities = await list_qualities(sid, lang, season)
    if not qualities:
        return await cq.answer("No qualities", show_alert=True)

    rows = [
        [InlineKeyboardButton(qu, callback_data=f"usr:send:{sid}:{q(lang)}:{q(season)}:{q(qu)}")]
        for qu in qualities
    ]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"usr:lang:{sid}:{q(lang)}")])

    await cq.answer()
    await cq.message.edit_reply_markup(InlineKeyboardMarkup(rows))
    logger.debug(f"Qualities listed for series_id={sid}, lang={lang}, season={season}: {qualities}")


# -------- SEND FILES --------
@Client.on_callback_query(filters.regex(r"^usr:send:(\d+):(.+):(.+):(.+)$"))
async def usr_send(client: Client, cq: CallbackQuery):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    quality = uq(cq.matches[0].group(4))

    gid_row = await get_group_id_value(sid, lang, season, quality)
    group_id = int(gid_row[0]) if gid_row else 0
    if not group_id:
        return await cq.answer("No files", show_alert=True)

    files = await get_files(group_id)
    if not files:
        return await cq.answer("No files", show_alert=True)

    await cq.answer("Sending…")

    for file_id, caption, _msg_type in files:
        try:
            await cq.message.reply_cached_media(file_id, caption=caption or "")
        except Exception:
            try:
                await cq.message.reply_cached_media(file_id)
            except Exception:
                logger.error(f"Failed to send file_id={file_id} for group_id={group_id}")

    logger.info(f"Sent {len(files)} files for series_id={sid}, lang={lang}, season={season}, quality={quality}")
