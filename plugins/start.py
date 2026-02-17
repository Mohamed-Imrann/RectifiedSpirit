from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup
import asyncio

@Client.on_message(filters.private & filters.command("start"))
async def start_cmd(client, message):
    user_id = int(message.from_user.id)
    parts = (message.text or "").split(maxsplit=1)
    payload = parts[1].strip() if len(parts) > 1 else ""

    if not payload:
        return await message.reply_text("✅ Go to group and click quality button.")

    link_key = None
    temp_key = None

    # ----------------------------
    # ✅ Decode payload
    # ----------------------------
    if payload.startswith("b_"):
        link_key = payload.split("_", 1)[1].strip()
    elif payload.startswith("tk_"):
        token = payload.split("_", 1)[1].strip()
        temp_key = f"tk:{token}"
    else:
        # raw token
        temp_key = f"tk:{payload}"

    # ----------------------------
    # ✅ ForceSub Check
    # ----------------------------
    try:
        required_chat_id, total, step = await get_required_fsub_chat(client, user_id)
    except Exception as e:
        logger.error(f"[START] get_required_fsub_chat error: {e}", exc_info=True)
        required_chat_id, total, step = None, 0, 0

    btn = None
    try:
        btn = await create_request_forcesub_buttons(client, int(user_id))
    except Exception as e:
        logger.error(f"[START] create_request_forcesub_buttons error: {e}", exc_info=True)
        btn = None

    # ✅ IMPORTANT: block ONLY if required_chat_id exists
    if required_chat_id:
        try:
            # create token if only link_key exists
            if not temp_key and link_key:
                token = await create_temp_token(int(user_id), link_key, ttl_seconds=600)
                temp_key = f"tk:{token}"

            key_to_store = link_key if link_key else temp_key

            await set_pending(
                int(user_id),
                key_to_store,
                int(required_chat_id) if required_chat_id else 0,
                int(step) if step else 0,
                int(total) if total else 1
            )
        except Exception as e:
            logger.error(f"[START] set_pending error: {e}", exc_info=True)

        return await message.reply_text(
            "<b>🔒 Please join this channel to continue</b>\n\n✅ After join-request, files will come automatically.",
            reply_markup=InlineKeyboardMarkup(btn) if btn else None,
            parse_mode=enums.ParseMode.HTML
        )

    # ----------------------------
    # ✅ Already joined → Send Files
    # ----------------------------
    send_key = temp_key if temp_key else link_key

    # 🔥 DEBUG: show keys in logs
    logger.error(f"[START] send_key BEFORE resolve = {send_key}")

    try:
        send_key = await resolve_send_key(int(user_id), str(send_key))
    except Exception as e:
        logger.error(f"[START] resolve_send_key error: {e}", exc_info=True)

    logger.error(f"[START] send_key AFTER resolve  = {send_key}")

    try:
        await message.reply_text("✅ Sending files...")
    except Exception:
        pass

    try:
        # ✅ Prevent infinite hang
        sent = await asyncio.wait_for(
            sendseries(client, f"{user_id}:start", send_key),
            timeout=180
        )

        if sent:
            try:
                await clear_pending(int(user_id))
            except Exception:
                pass

            return await message.reply_text("✅ Sent!")
        else:
            return await message.reply_text("❌ No files found!")
    except asyncio.TimeoutError:
        logger.error(f"[START] sendseries TIMEOUT user={user_id} key={send_key}")
        return await message.reply_text("❌ Timeout while sending. Try again.")
    except Exception as e:
        logger.error(f"[START] sendseries CRASH user={user_id} key={send_key}: {e}", exc_info=True)
        return await message.reply_text("❌ Failed to send files.")
