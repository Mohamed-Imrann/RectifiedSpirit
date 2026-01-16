import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from info import ADMINS
from database.series_sql import (
    upsert_series,
    get_series_by_id,
    list_languages,
)

# =========================
# 🔐 ASK LOCK (VERY IMPORTANT)
# =========================
ACTIVE_ASK = set()


# =========================
# Keyboards
# =========================
def kb_series_home(series_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Languages", callback_data=f"adm:langs:{series_id}")],
    ])


def kb_langs(series_id: int, langs: list[str]):
    rows = []

    if langs:
        for l in langs:
            rows.append([InlineKeyboardButton(l, callback_data="noop")])
    else:
        rows.append([InlineKeyboardButton("➕ Add Language", callback_data="noop")])

    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"adm:home:{series_id}")])
    return InlineKeyboardMarkup(rows)


# =========================
# /newseries (ADMIN)
# =========================
@Client.on_message(filters.command("newseries") & filters.user(ADMINS))
async def newseries_panel(client, message):
    uid = message.from_user.id

    # 🚫 block parallel asks
    if uid in ACTIVE_ASK:
        return await message.reply_text(
            "⏳ Already waiting for input.\nFinish pannunga or wait."
        )

    ACTIVE_ASK.add(uid)

    try:
        ask = await client.ask(
            message.chat.id,
            "📌 Series name anuppu:",
            timeout=120
        )

        title = (ask.text or "").strip()
        if not title:
            await message.reply_text("❌ Empty series name")
            return

        sid = await upsert_series(title)
        row = await get_series_by_id(sid)

        await message.reply_text(
            f"✅ **Series created:** `{title}`\n\nSelect option:",
            reply_markup=kb_series_home(sid)
        )

    except asyncio.TimeoutError:
        await message.reply_text("⌛ Timeout. Try again.")

    finally:
        ACTIVE_ASK.discard(uid)


# =========================
# HOME (Back)
# =========================
@Client.on_callback_query(filters.regex(r"^adm:home:(\d+)$"))
async def adm_home(_, cq):
    sid = int(cq.matches[0].group(1))

    row = await get_series_by_id(sid)
    if not row:
        return await cq.answer("Series not found", show_alert=True)

    _, title, *_ = row

    await cq.answer()
    await cq.message.edit_text(
        f"✅ **Series:** `{title}`\n\nSelect option:",
        reply_markup=kb_series_home(sid)
    )


# =========================
# LANGUAGES
# =========================
@Client.on_callback_query(filters.regex(r"^adm:langs:(\d+)$"))
async def adm_langs(_, cq):
    sid = int(cq.matches[0].group(1))
    langs = await list_languages(sid)

    await cq.answer()
    await cq.message.edit_text(
        "🌐 **Languages**\nSelect group:",
        reply_markup=kb_langs(sid, langs)
    )


# =========================
# NO-OP buttons (safe)
# =========================
@Client.on_callback_query(filters.regex("^noop$"))
async def noop(_, cq):
    await cq.answer("🚧 Coming soon", show_alert=False)
