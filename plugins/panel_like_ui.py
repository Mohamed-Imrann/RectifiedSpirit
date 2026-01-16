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
    get_group_id,
    add_file,
    get_files,
)

SAVE_DELAY = 1.2  # per file save delay
UPLOAD = {}       # uid -> {"group_id": int, "title": str, "lang": str, "season": str, "quality": str}


def q(s: str) -> str:
    return quote(s, safe="")

def uq(s: str) -> str:
    return unquote(s)


# ---------- UI builders ----------

def kb_series_home(series_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Languages", callback_data=f"adm:langs:{series_id}")],
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

def kb_qualities(series_id: int, lang: str, season: str, qualities: list[str]):
    rows = []
    if qualities:
        for qu in qualities:
            rows.append([
                InlineKeyboardButton(qu, callback_data=f"adm:upload:{series_id}:{q(lang)}:{q(season)}:{q(qu)}"),
                InlineKeyboardButton("+", callback_data=f"adm:addquality:{series_id}:{q(lang)}:{q(season)}")
            ])
        rows.append([InlineKeyboardButton("+ New Row", callback_data=f"adm:addquality:{series_id}:{q(lang)}:{q(season)}")])
    else:
        rows.append([InlineKeyboardButton("+ Add First Item", callback_data=f"adm:addquality:{series_id}:{q(lang)}:{q(season)}")])

    rows.append([InlineKeyboardButton("🗑 Delete Season Group", callback_data=f"adm:delseason:{series_id}:{q(lang)}:{q(season)}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"adm:lang:{series_id}:{q(lang)}")])
    return InlineKeyboardMarkup(rows)


# ---------- Command ----------

@Client.on_message(filters.command("newseriesui") & filters.user(ADMINS))
async def newseriesui(client: Client, message):
    ask = await client.ask(message.chat.id, "📌 Series name anuppu:", timeout=120)
    title = (ask.text or "").strip()
    if not title:
        return await message.reply_text("❌ Empty title")

    series_id = await upsert_series(title)
    row = await get_series_by_id(series_id)
    poster = row[2] if row else None

    caption = f"✅ **Series:** `{title}`\n\nSelect:"

    if poster:
        await message.reply_photo(poster, caption=caption, reply_markup=kb_series_home(series_id))
    else:
        await message.reply_text(caption, reply_markup=kb_series_home(series_id))


# ---------- Home ----------

@Client.on_callback_query(filters.regex(r"^adm:home:(\d+)$"))
async def adm_home(_, cq):
    sid = int(cq.matches[0].group(1))
    row = await get_series_by_id(sid)
    if not row:
        return await cq.answer("Not found", show_alert=True)
    _, title, poster = row

    caption = f"✅ **Series:** `{title}`\n\nSelect:"
    if poster and cq.message.photo:
        await cq.message.edit_caption(caption, reply_markup=kb_series_home(sid))
    elif poster and not cq.message.photo:
        await cq.message.delete()
        await cq.message.reply_photo(poster, caption=caption, reply_markup=kb_series_home(sid))
    else:
        if cq.message.photo:
            await cq.message.edit_caption(caption, reply_markup=kb_series_home(sid))
        else:
            await cq.message.edit_text(caption, reply_markup=kb_series_home(sid))
    await cq.answer()


# ---------- Languages ----------

@Client.on_callback_query(filters.regex(r"^adm:langs:(\d+)$"))
async def adm_langs(_, cq):
    sid = int(cq.matches[0].group(1))
    langs = await list_languages(sid)

    text = "Select any **Language** group.\nOr click **+** to add new."
    if cq.message.photo:
        await cq.message.edit_caption(text, reply_markup=kb_langs(sid, langs))
    else:
        await cq.message.edit_text(text, reply_markup=kb_langs(sid, langs))
    await cq.answer()

@Client.on_callback_query(filters.regex(r"^adm:addlang:(\d+)$"))
async def adm_addlang(client, cq):
    sid = int(cq.matches[0].group(1))
    ask = await client.ask(cq.message.chat.id, "看 🌐 Language name anuppu (ex: Multi Audio / Tamil):", timeout=120)
    lang = (ask.text or "").strip()
    if not lang:
        return await cq.answer("Empty", show_alert=True)

    # create a placeholder group so language exists
    await ensure_group(sid, lang, "season 1", "720p")
    langs = await list_languages(sid)

    text = "Language Added ✅\nSelect any **Language** group."
    if cq.message.photo:
        await cq.message.edit_caption(text, reply_markup=kb_langs(sid, langs))
    else:
        await cq.message.edit_text(text, reply_markup=kb_langs(sid, langs))
    await cq.answer("Added")


# ---------- Seasons ----------

@Client.on_callback_query(filters.regex(r"^adm:lang:(\d+):(.+)$"))
async def adm_lang(_, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    seasons = await list_seasons(sid, lang)
    text = f"Series Language: `{lang}`\nSelect any **Season** group."
    if cq.message.photo:
        await cq.message.edit_caption(text, reply_markup=kb_seasons(sid, lang, seasons))
    else:
        await cq.message.edit_text(text, reply_markup=kb_seasons(sid, lang, seasons))
    await cq.answer()

@Client.on_callback_query(filters.regex(r"^adm:addseason:(\d+):(.+)$"))
async def adm_addseason(client, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))

    ask = await client.ask(cq.message.chat.id, "📦 Season name anuppu (ex: season 1 / season 4 part 2):", timeout=120)
    season = (ask.text or "").strip()
    if not season:
        return await cq.answer("Empty", show_alert=True)

    # create placeholder quality
    await ensure_group(sid, lang, season, "720p")
    seasons = await list_seasons(sid, lang)

    text = f"Season Added ✅\nLanguage: `{lang}`"
    if cq.message.photo:
        await cq.message.edit_caption(text, reply_markup=kb_seasons(sid, lang, seasons))
    else:
        await cq.message.edit_text(text, reply_markup=kb_seasons(sid, lang, seasons))
    await cq.answer("Added")


# ---------- Qualities ----------

@Client.on_callback_query(filters.regex(r"^adm:season:(\d+):(.+):(.+)$"))
async def adm_season(_, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    qualities = await list_qualities(sid, lang, season)
    text = f"Language: `{lang}`\nSeason: `{season}`\nSelect any **Quality**."
    if cq.message.photo:
        await cq.message.edit_caption(text, reply_markup=kb_qualities(sid, lang, season, qualities))
    else:
        await cq.message.edit_text(text, reply_markup=kb_qualities(sid, lang, season, qualities))
    await cq.answer()

@Client.on_callback_query(filters.regex(r"^adm:addquality:(\d+):(.+):(.+)$"))
async def adm_addquality(client, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))

    ask = await client.ask(cq.message.chat.id, "🎞 Quality anuppu (ex: 720p / 1080p):", timeout=120)
    quality = (ask.text or "").strip()
    if not quality:
        return await cq.answer("Empty", show_alert=True)

    await ensure_group(sid, lang, season, quality)
    qualities = await list_qualities(sid, lang, season)

    text = f"Quality Added ✅\n`{lang}` / `{season}`"
    if cq.message.photo:
        await cq.message.edit_caption(text, reply_markup=kb_qualities(sid, lang, season, qualities))
    else:
        await cq.message.edit_text(text, reply_markup=kb_qualities(sid, lang, season, qualities))
    await cq.answer("Added")


# ---------- Upload (Quality button) ----------

@Client.on_callback_query(filters.regex(r"^adm:upload:(\d+):(.+):(.+):(.+)$"))
async def adm_upload(client, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    quality = uq(cq.matches[0].group(4))

    group_id = await ensure_group(sid, lang, season, quality)

    UPLOAD[cq.from_user.id] = {
        "group_id": group_id,
        "lang": lang,
        "season": season,
        "quality": quality,
    }

    msg = await cq.message.reply_text(
        f"📥 **Upload Mode**\n\n"
        f"Language: `{lang}`\nSeason: `{season}`\nQuality: `{quality}`\n\n"
        f"Files anuppunga… finish panna `/done`"
    )
    await cq.answer("Upload mode")

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

    saved = 0
    for file_id, caption, msg_type in queue:
        await add_file(group_id, file_id, caption, msg_type)
        saved += 1
        await asyncio.sleep(SAVE_DELAY)

    await msg.edit_text(f"✅ Done! saved `{saved}` files.")
    UPLOAD.pop(cq.from_user.id, None)


# ---------- Delete group (simple) ----------
# NOTE: DB-level delete functions not added here.
# If you want delete fully, tell me — I'll add delete_* SQL functions in series_sql.py and plug here.
@Client.on_callback_query(filters.regex(r"^adm:dellang:"))
async def adm_dellang(_, cq):
    await cq.answer("Delete not wired yet. Sollunga, delete SQL add panniduren.", show_alert=True)

@Client.on_callback_query(filters.regex(r"^adm:delseason:"))
async def adm_delseason(_, cq):
    await cq.answer("Delete not wired yet. Sollunga, delete SQL add panniduren.", show_alert=True)
