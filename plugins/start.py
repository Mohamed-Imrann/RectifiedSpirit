from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup

@Client.on_message(filters.private & filters.command("start"))
async def start_cmd(client, message):
    user_id = message.from_user.id
    parts = message.text.split(maxsplit=1)
    payload = parts[1].strip() if len(parts) > 1 else ""

    if not payload:
        return await message.reply_text("✅ Go to group and click quality button.")

    # ----------------------------
    # ✅ Decode payload
    # ----------------------------
    link_key = None
    temp_key = None

    # deep link: b_<link_key>
    if payload.startswith("b_"):
        link_key = payload.split("_", 1)[1].strip()

    # deep link: tk_<token>  (if you use token deep link)
    elif payload.startswith("tk_"):
        token = payload.split("_", 1)[1].strip()
        temp_key = f"tk:{token}"

    # deep link: raw token only (if you open bot with ?start=<token>)
    else:
        # treat as token (safe fallback)
        temp_key = f"tk:{payload}"

    # ----------------------------
    # ✅ ForceSub Check
    # (ONLY block if user not joined)
    # ----------------------------
    try:
        required_chat_id, total, step = await get_required_fsub_chat(client, user_id)
    except Exception as e:
        logger.error(f"get_required_fsub_chat error: {e}")
        required_chat_id, total, step = None, 0, 0

    btn = await create_request_forcesub_buttons(client, int(user_id))

    if btn:
        # ✅ store pending so after join-request -> auto send
        try:
            # if we got link_key but not token, create token for pending retry flow
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
            logger.error(f"set_pending error: {e}")

        return await message.reply_text(
            "<b>🔒 Please join this channel to continue</b>\n\n✅ After join-request, files will come automatically.",
            reply_markup=InlineKeyboardMarkup(btn),
            parse_mode=enums.ParseMode.HTML
        )

    # ----------------------------
    # ✅ Already Joined → Send Files
    # ----------------------------
    send_key = temp_key if temp_key else link_key

    try:
        await message.reply_text("✅ Sending files...")
    except Exception:
        pass

    try:
        sent = await sendseries(client, f"{user_id}:start", send_key)
        if sent:
            try:
                await clear_pending(int(user_id))
            except Exception:
                pass

            # optional: advance step
            if required_chat_id and total:
                try:
                    await advance_user_step(int(user_id), int(total))
                except Exception:
                    pass

            return await message.reply_text("✅ Sent!")
        else:
            return await message.reply_text("❌ No files found!")
    except Exception as e:
        logger.error(f"start sendseries error: {e}", exc_info=True)
        return await message.reply_text("❌ Failed to send files.")
