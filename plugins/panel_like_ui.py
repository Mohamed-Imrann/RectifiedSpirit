import asyncio
from urllib.parse import quote, unquote
from typing import List

from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified, FloodWait, RPCError
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from info import ADMINS
from utils import get_file_id, wait_user_message, auto_fetch_and_set_poster_and_meta

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
MAX_RETRIES = 3


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


def kb_langs(series_id: int, langs: List[str]):
    rows = []
    if langs:
        for name in langs:
            rows.append([InlineKeyboardButton(name, callback_data=f"adm:lang:{series_id}:{q(name)}")])
        rows.append([InlineKeyboardButton("+ Add Language", callback_data=f"adm:addlang:{series_id}")])
    else:
        rows.append([InlineKeyboardButton("+ Add First Item", callback_data=f"adm:addlang:{series_id}")])

    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"adm:home:{series_id}")])
    return InlineKeyboardMarkup(rows)


def kb_seasons(series_id: int, lang: str, seasons: List[str]):
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


async def kb_qualities(series_id: int, lang: str, season: str, qualities: List[str]):
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
    prompt = await message.reply_text("📌 Series name anuppu:")

    try:
        ask = await wait_user_message(message.chat.id, message.from_user.id, timeout=180)
    except Exception:
        return await prompt.edit_text("❌ Timeout. /newseries again.")

    title = (ask.text or "").strip()
    if not title:
        return await prompt.edit_text("❌ Empty title. /newseries again.")

    sid = await upsert_series(title)

    row = await get_series_by_id(sid)
    published = int(row[3]) if row else 0
    cap = f"✅ **Series:** `{title}`\n\nSelect option:"
    panel_msg = await message.reply_text(cap, reply_markup=kb_series_home(sid, published))

    status = await message.reply_text("🎬 TMDB fetching…")
    ok = False
    try:
        ok = await auto_fetch_and_set_poster_and_meta(client, sid, title, message.chat.id)
    except Exception:
        ok = False

    try:
        await status.delete()
    except Exception:
        pass
    try:
        await prompt.delete()
    except Exception:
        pass

    if ok:
        row2 = await get_series_by_id(sid)
        if row2:
            poster_file_id = row2[2]
            if poster_file_id:
                try:
                    await panel_msg.delete()
                except Exception:
                    pass
                await message.reply_photo(
                    poster_file_id,
                    caption=cap,
                    reply_markup=kb_series_home(sid, published)
                )


# =======================
# HOME
# =======================
@Client.on_callback_query(filters.regex(r"^adm:home:(\d+)$"))
async def adm_home(_, cq):
    sid = int(cq.matches[0].group(1))
    row = await get_series_by_id(sid)
    if not row:
        return await cq.answer("Not found", show_alert=True)

    _, title, _poster, published, *_ = row
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

    _, title, _poster, published, *_ = row
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
    try:
        pm = await wait_user_message(cq.message.chat.id, cq.from_user.id, timeout=180)
    except Exception:
        return await msg.edit_text("❌ Timeout. Retry.")

    if not pm.photo:
        return await msg.edit_text("❌ Photo illa. Retry pannunga.")

    await set_series_poster(sid, pm.photo.file_id)

    row = await get_series_by_id(sid)
    if not row:
