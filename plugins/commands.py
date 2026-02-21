#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from bot import Bot
import sys
import asyncio
from os import environ, execle, system
import os
import logging
from Script import script

from pyrogram import filters, enums
from pyrogram.errors import ChatAdminRequired, FloodWait, BadRequest
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from database.users_chats_db import db
from database.request_forcesub_db import delete_all_one, delete_all_two
from database.join_reqs import JoinReqs

from pymongo import MongoClient
from info import (
    ADMINS, AUTH_CHANNEL, LOG_CHANNEL, CUSTOM_FILE_CAPTION, BATCH_FILE_CAPTION,
    PROTECT_CONTENT, DATABASE_URI, AUTO_DELETE_TIME, AUTO_DELETE_MSG,
    BATCH_FILE_CAPTION as CUSTOM_CAPTION, RAW_DB_CHANNEL,
    START_TXT
)
from utils import get_size
import json

# ✅ FSUB (OR logic)
from plugins.request_forcesub import create_request_forcesub_buttons, is_fsub_ok_any_one

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

BATCH_FILES = {}
from utils import get_messages, delete_file

mongo_client = MongoClient(DATABASE_URI)
edb = mongo_client["file_database"]
ecollection = edb["episodes"]

# ✅ instance once
db1 = JoinReqs()


def _append_env_line(key: str, value: int):
    """
    ✅ Append to dynamic.env without overwriting.
    Also removes old same-key line if exists (optional safe).
    """
    path = "./dynamic.env"
    lines = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except Exception:
            lines = []

    # remove old same-key lines
    new_lines = [ln for ln in lines if not ln.startswith(f"{key}=")]
    new_lines.append(f"{key}={value}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines) + "\n")


@Bot.on_message(filters.command("start"))
async def start_command(client, message):
    try:
        # ✅ GROUP START => just register group and return
        if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            await asyncio.sleep(2)
            if not await db.get_chat(message.chat.id):
                total = await client.get_chat_members_count(message.chat.id)
                await client.send_message(
                    LOG_CHANNEL,
                    script.LOG_TEXT_G.format(message.chat.title, message.chat.id, total, "Unknown")
                )
                await db.add_chat(message.chat.id, message.chat.title)
            return

        # ✅ add user
        if not await db.is_user_exist(message.from_user.id):
            await db.add_user(message.from_user.id, message.from_user.first_name)

        deep_link = None
        if len(message.command) > 1:
            deep_link = message.text.split(None, 1)[1]

        # ============================================================
        # ✅ IMPORTANT:
        # AUTH_CHANNEL + FORCE SUB check ONLY when deep_link exists
        # ============================================================
        if deep_link:

            # ✅ AUTH_CHANNEL check only for deep_link (files access)
            if AUTH_CHANNEL:
                from utils import is_subscribed
                if not await is_subscribed(client, message):
                    try:
                        invite_link = await client.create_chat_invite_link(int(AUTH_CHANNEL))
                    except ChatAdminRequired:
                        logger.error("AUTH_CHANNEL: bot not admin / invite permission missing")
                        return

                    btn = [[InlineKeyboardButton("❆ Jᴏɪɴ Oᴜʀ Bᴀᴄᴋ-Uᴘ Cʜᴀɴɴᴇʟ ❆", url=invite_link.invite_link)]]
                    btn.append([InlineKeyboardButton("⏳ Try Again ⏳", callback_data=f"b:{deep_link}")])

                    await client.send_message(
                        chat_id=message.from_user.id,
                        text="♦️ <b><u>READ THIS INSTRUCTION</u></b> ♦️\n\n🗣 <i>Follow instructions to access movies</i>",
                        reply_markup=InlineKeyboardMarkup(btn),
                        parse_mode=enums.ParseMode.HTML
                    )
                    return

            # ✅ FSUB OR logic (Join any one channel)
            ok = await is_fsub_ok_any_one(client, message.from_user.id)
            if not ok:
                btn = await create_request_forcesub_buttons(client, message.from_user.id)
                if not btn:
                    # fallback message if no links
                    await client.send_message(
                        chat_id=message.from_user.id,
                        text="<b>FSUB channels not configured.</b>",
                        parse_mode=enums.ParseMode.HTML
                    )
                    return

                btn.append([InlineKeyboardButton("↻ Tʀʏ Aɢᴀɪɴ", callback_data=f"b:{deep_link}")])
                await client.send_message(
                    chat_id=message.from_user.id,
                    text="<b>Please join any ONE channel below to use bot</b>",
                    reply_markup=InlineKeyboardMarkup(btn),
                    parse_mode=enums.ParseMode.HTML
                )
                return

            # ✅ Passed fsub => continue deep_link flow
            temp_msg = await message.reply("Please wait...")

            if deep_link.startswith("get_"):
                args = deep_link.split("_")
                if len(args) == 4:
                    channel_id = args[1]
                    start = int(args[2])
                    end = int(args[3])

                    if int(channel_id) not in RAW_DB_CHANNEL:
                        await temp_msg.delete()
                        return

                    ids = range(start, end + 1)
                else:
                    await temp_msg.delete()
                    return

                try:
                    messages = await asyncio.wait_for(
                        get_messages(client, f"-100{channel_id}", ids),
                        timeout=30.0
                    )
                except Exception as e:
                    logger.error(f"Error fetching messages: {e}")
                    await temp_msg.delete()
                    return

                await temp_msg.delete()
                track_msgs = []

                for msg in messages:
                    try:
                        caption = CUSTOM_CAPTION.format(
                            previouscaption="" if not msg.caption else msg.caption.html,
                            filename=msg.document.file_name
                        ) if bool(CUSTOM_CAPTION) and bool(msg.document) else ("" if not msg.caption else msg.caption.html)

                        reply_markup = msg.reply_markup

                        if AUTO_DELETE_TIME and AUTO_DELETE_TIME > 0:
                            copied_msg = await msg.copy(
                                chat_id=message.from_user.id,
                                caption=caption,
                                parse_mode=enums.ParseMode.HTML,
                                reply_markup=reply_markup
                            )
                            if copied_msg:
                                track_msgs.append(copied_msg)
                        else:
                            await msg.copy(
                                chat_id=message.from_user.id,
                                caption=caption,
                                parse_mode=enums.ParseMode.HTML,
                                reply_markup=reply_markup
                            )
                            await asyncio.sleep(0.4)

                    except FloodWait as e:
                        await asyncio.sleep(e.value)
                    except BadRequest:
                        continue
                    except Exception:
                        continue

                if track_msgs:
                    delete_data = await client.send_message(
                        chat_id=message.from_user.id,
                        text=AUTO_DELETE_MSG.format(time=AUTO_DELETE_TIME)
                    )
                    asyncio.create_task(delete_file(track_msgs, client, delete_data))
                return

            elif deep_link.startswith("e_"):
                args = deep_link.split("_")
                if len(args) < 2:
                    await temp_msg.delete()
                    return

                series_name = args[1]
                series_data = ecollection.find_one({"series": series_name})
                if not series_data or not series_data.get("files"):
                    await temp_msg.delete()
                    return

                await temp_msg.delete()
                for entry in series_data["files"]:
                    try:
                        await client.send_cached_media(
                            message.chat.id,
                            entry["file_id"],
                            caption=entry.get("caption", ""),
                            protect_content=PROTECT_CONTENT
                        )
                        await asyncio.sleep(2)
                    except FloodWait as e:
                        await asyncio.sleep(e.value)
                    except Exception:
                        continue
                return

            elif deep_link.startswith("B-"):
                file_id = deep_link.split("-", 1)[1]
                msgs = BATCH_FILES.get(file_id)

                if not msgs:
                    file = await client.download_media(file_id)
                    try:
                        with open(file, encoding="utf-8") as file_data:
                            msgs = json.loads(file_data.read())
                    except Exception as e:
                        await temp_msg.edit(f"FAILED: {e}")
                        return
                    os.remove(file)
                    BATCH_FILES[file_id] = msgs

                await temp_msg.delete()

                for msg in msgs:
                    try:
                        title = msg.get("title")
                        size = get_size(int(msg.get("size", 0)))
                        f_caption = msg.get("caption", "")

                        if BATCH_FILE_CAPTION:
                            try:
                                f_caption = BATCH_FILE_CAPTION.format(
                                    file_name='' if title is None else title,
                                    file_size='' if size is None else size,
                                    previouscaption='' if f_caption is None else f_caption
                                )
                            except Exception:
                                pass

                        if f_caption is None:
                            f_caption = f"{title}"

                        await client.send_cached_media(
                            chat_id=message.from_user.id,
                            file_id=msg.get("file_id"),
                            caption=f_caption,
                            protect_content=msg.get('protect', PROTECT_CONTENT)
                        )
                        await asyncio.sleep(1)

                    except FloodWait as e:
                        await asyncio.sleep(e.value)  # ✅ fixed
                    except Exception:
                        continue
                return

        # ============================================================
        # ✅ NORMAL /start (NO deep_link)
        # ============================================================
        buttons = [
            [InlineKeyboardButton("📢 Series Channel", url="https://t.me/Spidy_Series")],
            [InlineKeyboardButton("👥 Series Group", url="https://t.me/+0hnh1h_L0dc5MDE1")],
            [InlineKeyboardButton("Switch Inline", switch_inline_query_current_chat='')]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)

        await message.reply_text(
            text=START_TXT,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.MARKDOWN
        )
        return

    except Exception as e:
        logger.error(f"Unexpected error in start_command: {str(e)}", exc_info=True)
        try:
            await message.reply_text("Something Went Wrong, Try Again")
        except:
            pass


@Bot.on_message(filters.command("logs") & filters.user(ADMINS))
async def log_file(bot, message):
    try:
        await message.reply_document('TelegramBot.txt')
    except Exception as e:
        await message.reply(str(e))


@Bot.on_message(filters.command('restart') & filters.user(ADMINS))
async def restart_bot(client, message):
    try:
        msg = await message.reply_text(text="<b>Bot Restarting ...</b>")
        await msg.edit("<b>Restart Successfully Completed ✅</b>")
        system("git pull -f && pip3 install --no-cache-dir -r requirements.txt")
        execle(sys.executable, sys.executable, "main.py", environ)
    except Exception as e:
        await message.reply_text(f"Restart failed: {str(e)}")


@Bot.on_message(filters.command("purgerequests1") & filters.user(ADMINS))
async def purge_req_one(bot: Bot, message: Message):
    pls_wait = await bot.send_message(
        chat_id=message.chat.id,
        text="<b>Purging Req One Database...</b>",
        reply_to_message_id=message.id
    )
    await asyncio.sleep(1)
    await delete_all_one()
    await pls_wait.edit("<b>Req One Database Purged ✅.</b>")


@Bot.on_message(filters.command("purgerequests2") & filters.user(ADMINS))
async def purge_req_two(bot: Bot, message: Message):
    pls_wait = await bot.send_message(
        chat_id=message.chat.id,
        text="<b>Purging Req Two Database...</b>",
        reply_to_message_id=message.id
    )
    await asyncio.sleep(1)
    await delete_all_two()
    await pls_wait.edit("<b>Req Two Database Purged ✅.</b>")


from database.crazy_db import get_series

# ✅ view all 3 fsub chats
@Bot.on_message(filters.command("viewchat") & filters.user(ADMINS))
async def view_fsub_chats(bot: Bot, message: Message):
    try:
        c1 = await db1.get_fsub_chat1()
        c2 = await db1.get_fsub_chat2()
        c3 = await db1.get_fsub_chat3() if hasattr(db1, "get_fsub_chat3") else None

        t1 = c1.get("chat_id") if c1 else None
        t2 = c2.get("chat_id") if c2 else None
        t3 = c3.get("chat_id") if c3 else None

        txt = (
            "✅ <b>FSUB Chats</b>\n\n"
            f"1️⃣ <code>{t1}</code>\n"
            f"2️⃣ <code>{t2}</code>\n"
            f"3️⃣ <code>{t3}</code>\n"
        )
        await message.reply_text(txt, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        await message.reply_text(f"❌ viewchat error: <code>{e}</code>", parse_mode=enums.ParseMode.HTML)


# ✅ setchat1 = save only, NO restart
@Bot.on_message(filters.command("setchat1") & filters.user(ADMINS))
async def add_fsub_chats1(bot: Bot, update: Message):
    chat = update.command[1] if len(update.command) > 1 else None
    if not chat:
        return await update.reply_text("Invalid chat id.", quote=True)
    chat = int(chat)

    await db1.add_fsub_chat1(chat)
    _append_env_line("REQ_CHANNEL_ONE", chat)

    await update.reply_text(
        f"✅ Saved chat1: <code>{chat}</code>\nℹ️ Restart will happen after /setchat3",
        quote=True,
        parse_mode=enums.ParseMode.HTML
    )


# ✅ setchat2 = save only, NO restart
@Bot.on_message(filters.command("setchat2") & filters.user(ADMINS))
async def add_fsub_chats2(bot: Bot, update: Message):
    chat = update.command[1] if len(update.command) > 1 else None
    if not chat:
        return await update.reply_text("Invalid chat id.", quote=True)
    chat = int(chat)

    await db1.add_fsub_chat2(chat)
    _append_env_line("REQ_CHANNEL_TWO", chat)

    await update.reply_text(
        f"✅ Saved chat2: <code>{chat}</code>\nℹ️ Restart will happen after /setchat3",
        quote=True,
        parse_mode=enums.ParseMode.HTML
    )


# ✅ setchat3 = save + restart
@Bot.on_message(filters.command("setchat3") & filters.user(ADMINS))
async def add_fsub_chats3(bot: Bot, update: Message):
    chat = update.command[1] if len(update.command) > 1 else None
    if not chat:
        return await update.reply_text("Invalid chat id.", quote=True)
    chat = int(chat)

    if not hasattr(db1, "add_fsub_chat3"):
        return await update.reply_text("Your JoinReqs DB has no chat3 support.", quote=True)

    await db1.add_fsub_chat3(chat)
    _append_env_line("REQ_CHANNEL_THREE", chat)

    await update.reply_text(
        f"✅ Saved chat3: <code>{chat}</code>\n🔄 Restarting now...",
        quote=True,
        parse_mode=enums.ParseMode.HTML
    )

    os.execl(sys.executable, sys.executable, "main.py")


@Bot.on_message(filters.command("stats") & filters.user(ADMINS))
async def stats_cmd(client: Bot, message: Message):
    try:
        total_users = await db.total_users_count()
        total_chats = await db.total_chat_count()

        # DB size
        try:
            db_size = await db.get_db_size()
        except Exception:
            db_size = 0

        # Series stats
        series_list = get_series() or []
        total_series = len(series_list)
        published_series = len([s for s in series_list if s.get("published", False)])

        txt = (
            "📊 <b>Bot Stats</b>\n\n"
            f"👤 Users: <code>{total_users}</code>\n"
            f"👥 Groups: <code>{total_chats}</code>\n\n"
            f"📺 Series Total: <code>{total_series}</code>\n"
            f"✅ Published: <code>{published_series}</code>\n\n"
            f"💾 DB Size: <code>{db_size}</code> bytes\n"
        )

        await message.reply_text(txt, parse_mode=enums.ParseMode.HTML)

    except Exception as e:
        await message.reply_text(
            f"❌ stats error: <code>{e}</code>",
            parse_mode=enums.ParseMode.HTML
        )


@Bot.on_message(filters.command("fsl") & filters.user(ADMINS))
async def full_series_list(client: Bot, message: Message):
    try:
        args = message.text.split(maxsplit=1)
        mode = args[1].strip().lower() if len(args) > 1 else ""

        series_list = get_series() or []
        if not series_list:
            return await message.reply_text("❌ No series found in database.", parse_mode=enums.ParseMode.HTML)

        total_series = len(series_list)

        if mode == "detailed":
            text = "📚 <b>Full Series List (Detailed)</b>\n\n"
        else:
            text = "📚 <b>Full Series List</b>\n\n"

        text += f"📺 Total Series: <code>{total_series}</code>\n\n"

        for i, s in enumerate(series_list, start=1):
            title = s.get("title", "Unknown")
            released = s.get("released_on", "N/A")
            rating = s.get("rating", "N/A")
            published = "✅" if s.get("published", False) else "❌"

            if mode == "detailed":
                languages = s.get("languages", []) or []
                lang_count = len(languages)

                season_count = 0
                for lang in languages:
                    seasons = lang.get("seasons", []) or []
                    season_count += len(seasons)

                text += (
                    f"{i}. <b>{title}</b> {published}\n"
                    f"   📅 {released} | ⭐ {rating}\n"
                    f"   🌐 Languages: <code>{lang_count}</code> | 🎬 Seasons: <code>{season_count}</code>\n\n"
                )
            else:
                text += (
                    f"{i}. <b>{title}</b>\n"
                    f"   📅 {released} | ⭐ {rating} {published}\n\n"
                )

        # Telegram 4096 limit safe split
        if len(text) > 4000:
            chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
            for chunk in chunks:
                await message.reply_text(chunk, parse_mode=enums.ParseMode.HTML)
        else:
            await message.reply_text(text, parse_mode=enums.ParseMode.HTML)

    except Exception as e:
        await message.reply_text(f"❌ fsl error: <code>{e}</code>", parse_mode=enums.ParseMode.HTML)
