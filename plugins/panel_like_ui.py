# plugins/panel_like_ui.py
import asyncio
from urllib.parse import quote, unquote

from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified, FloodWait, RPCError
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from pyromod import listen

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
        if msg.photo:
            await msg.edit_caption(text, reply_markup=reply_markup)
        else:
            await msg.edit_text(text, reply_markup=reply_markup)
    except MessageNotModified:
        pass
    except RPCError:
        await msg.reply_text(text, reply_markup=reply_markup)


# ---------- keyboards ----------
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
        [InlineKeyboardButton("🖼 Poster", callback_data=f"adm:poster_menu:{series_id}")],
    ])


def kb_poster_menu(series_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Auto Fetch (TMDB)", callback_data=f"adm:poster_auto:{series_id}")],
        [InlineKeyboardButton("📸 Manual Upload", callback_data=f"adm:poster_manual:{series_id}")],
        [InlineKeyboardButton("⬅️ Back", callback_data=f"adm:home:{series_id}")],
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
# /newseries
# =======================
@Client.on_message(filters.command("newseries") & filters.user(ADMINS))
async def newseries_panel(client: Client, message):
    ask = await client.ask(message.chat.id, "📌 Series name anuppu:", timeout=180)
    title = (ask.text or "").strip()
    if not title:
        return await message.reply_text("❌ Empty title")

    sid = await upsert_series(title)

    # 🔥 AUTO FETCH POSTER + META
    try:
        ok = await auto_fetch_and_set_poster_and_meta(client, sid, title, message.chat.id)
        if ok:
            await message.reply_text("🤖 TMDB poster + metadata auto set ✅")
    except Exception:
        pass

    row = await get_series_by_id(sid)
    published = int(row[-1]) if row else 0

    caption = f"✅ **Series:** `{title}`\n\nSelect option:"
    await message.reply_text(caption, reply_markup=kb_series_home(sid, published))


# =======================
# HOME
# =======================
@Client.on_callback_query(filters.regex(r"^adm:home:(\d+)$"))
async def adm_home(_, cq):
    sid = int(cq.matches[0].group(1))
    row = await get_series_by_id(sid)
    if not row:
        return await cq.answer("Not found", show_alert=True)

    _, title, *_rest = row
    published = int(row[-1])

    await cq.answer()
    caption = f"✅ **Series:** `{title}`\n\nSelect option:"
    await edit_panel(cq.message, caption, kb_series_home(sid, published))


# =======================
# PUBLISH
# =======================
@Client.on_callback_query(filters.regex(r"^adm:publish:(\d+)$"))
async def adm_publish(_, cq):
    sid = int(cq.matches[0].group(1))
    new_val = await toggle_publish(sid)

    row = await get_series_by_id(sid)
    if not row:
        return await cq.answer("Not found", show_alert=True)

    title = row[1]
    published = int(row[-1])
    status = "✅ Published" if published == 1 else "❌ Unpublished"

    await cq.answer(status, show_alert=True)
    caption = f"✅ **Series:** `{title}`\n\nStatus: **{status}**\n\nSelect option:"
    await edit_panel(cq.message, caption, kb_series_home(sid, published))


# =======================
# POSTER MENU
# =======================
@Client.on_callback_query(filters.regex(r"^adm:poster_menu:(\d+)$"))
async def adm_poster_menu(_, cq):
    sid = int(cq.matches[0].group(1))
    await cq.answer()
    await edit_panel(cq.message, "🖼 **Poster Menu**\n\nSelect option:", kb_poster_menu(sid))


# =======================
# POSTER AUTO
# =======================
@Client.on_callback_query(filters.regex(r"^adm:poster_auto:(\d+)$"))
async def adm_poster_auto(client: Client, cq):
    sid = int(cq.matches[0].group(1))
    row = await get_series_by_id(sid)
    if not row:
        return await cq.answer("Not found", show_alert=True)

    title = row[1]
    await cq.answer("Fetching from TMDB…")

    ok = await auto_fetch_and_set_poster_and_meta(client, sid, title, cq.message.chat.id)
    if not ok:
        return await cq.answer("TMDB poster not found", show_alert=True)

    published = int(row[-1])
    caption = f"✅ **Series:** `{title}`\n\n🖼 Poster auto updated ✅"
    await edit_panel(cq.message, caption, kb_series_home(sid, published))


# =======================
# POSTER MANUAL
# =======================
@Client.on_callback_query(filters.regex(r"^adm:poster_manual:(\d+)$"))
async def adm_poster_manual(client: Client, cq):
    sid = int(cq.matches[0].group(1))
    await cq.answer("Send poster photo")

    msg = await cq.message.reply_text("🖼 Poster photo anuppu (send photo).")
    pm = await client.listen(cq.message.chat.id)

    if not pm.photo:
        return await msg.edit_text("❌ Photo illa.")

    await set_series_poster(sid, pm.photo.file_id)
    row = await get_series_by_id(sid)

    title = row[1]
    published = int(row[-1])

    await msg.edit_text("✅ Poster updated.")
    caption = f"✅ **Series:** `{title}`\n\nSelect option:"
    await edit_panel(cq.message, caption, kb_series_home(sid, published))


# =======================
# (👇 BELOW THIS – YOUR EXISTING LANGUAGE / SEASON / QUALITY / UPLOAD / DELETE CODE)
# =======================
# ⛔ NOTHING CHANGED BELOW – keep exactly same as your current file
