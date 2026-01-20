# plugins/panel_like_ui.py
import asyncio
from urllib.parse import quote, unquote

from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified, FloodWait
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


async def edit_panel(msg, text: str, reply_markup=None):
    try:
        if msg.photo:
            await msg.edit_caption(text, reply_markup=reply_markup)
        else:
            await msg.edit_text(text, reply_markup=reply_markup)
    except MessageNotModified:
        pass
    except Exception:
        await msg.reply_text(text, reply_markup=reply_markup)


# =========================
# /newseries
# =========================
@Client.on_message(filters.command("newseries") & filters.user(ADMINS))
async def newseries_panel(client: Client, message):
    ask = await client.ask(message.chat.id, "📌 Series name anuppu:")
    title = (ask.text or "").strip()
    if not title:
        return await message.reply_text("❌ Empty title")

    sid = await upsert_series(title)

    # ⬇️ TMDB AUTO FETCH (NON BLOCKING)
    asyncio.create_task(
        auto_fetch_and_set_poster_and_meta(
            client, sid, title, message.chat.id
        )
    )

    row = await get_series_by_id(sid)
    published = int(row[3]) if row else 0

    text = f"✅ **Series:** `{title}`\n\nSelect option:"
    await message.reply_text(text, reply_markup=kb_series_home(sid, published))


# =========================
# KEYBOARDS
# =========================
def kb_series_home(series_id: int, published: int):
    pub_txt = "✅ Published" if published else "❌ Unpublished"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Languages", callback_data=f"adm:langs:{series_id}")],
        [InlineKeyboardButton(pub_txt, callback_data=f"adm:publish:{series_id}")],
        [InlineKeyboardButton("🖼 Poster", callback_data=f"adm:poster:{series_id}")],
    ])


# =========================
# UPLOAD (FIXED RANGE FETCH)
# =========================
@Client.on_callback_query(filters.regex(r"^adm:upload:(\d+):(.+):(.+):(.+)$"))
async def adm_upload(client: Client, cq):
    sid = int(cq.matches[0].group(1))
    lang = uq(cq.matches[0].group(2))
    season = uq(cq.matches[0].group(3))
    quality = uq(cq.matches[0].group(4))

    group_id = await ensure_group(sid, lang, season, quality)
    await cq.answer()

    user_client: Client = getattr(client, "user_client", None)
    if not user_client:
        return await cq.message.reply_text("❌ user_client not attached")

    info = await cq.message.reply_text(
        "🔗 First file message ah forward pannunga"
    )

    first = await client.listen(cq.message.chat.id)
    if not first:
        return await info.edit_text("❌ First message missing")

    await info.edit_text("➡️ Ippo LAST file message ah forward pannunga")

    last = await client.listen(cq.message.chat.id)
    if not last:
        return await info.edit_text("❌ Last message missing")

    chat_id = first.chat.id
    first_id = first.id
    last_id = last.id

    if first_id > last_id:
        first_id, last_id = last_id, first_id

    progress = await cq.message.reply_text("⏳ Fetching messages...")

    messages = []
    try:
        async for m in user_client.iter_history(
            chat_id,
            offset_id=last_id + 1,
            reverse=True
        ):
            if m.id < first_id:
                break
            messages.append(m)
    except FloodWait as e:
        await asyncio.sleep(e.value)
    except Exception:
        return await progress.edit_text(
            "❌ User account channel access illa / join pannala"
        )

    media_msgs = []
    for m in messages:
        media = get_file_id(m)
        if media:
            media_msgs.append(
                (media.file_id, m.caption or "", getattr(media, "message_type", ""))
            )

    if not media_msgs:
        return await progress.edit_text("❌ Media files illa")

    saved = 0
    for file_id, caption, msg_type in media_msgs:
        await add_file(group_id, file_id, caption, msg_type)
        saved += 1
        await progress.edit_text(f"💾 Saving {saved}/{len(media_msgs)}")
        await asyncio.sleep(SAVE_DELAY)

    await progress.edit_text(f"✅ `{saved}` files added")

    try:
        await info.delete()
    except Exception:
        pass
