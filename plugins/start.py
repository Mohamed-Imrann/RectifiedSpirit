from pyrogram import Client, filters

@Client.on_message(filters.private & filters.command("start"))
async def start_cmd(client, message):
    user_id = message.from_user.id
    parts = message.text.split(maxsplit=1)
    payload = parts[1] if len(parts) > 1 else ""

    # ✅ deep link from group quality button
    if payload.startswith("b_"):
        link_key = payload.split("_", 1)[1]

        # ✅ FSUB check
        btn = await create_request_forcesub_buttons(client, int(user_id))
        if btn:
            await message.reply_text(
                "<b>🔒 Please join this channel to continue</b>\n\n✅ After join-request, files will come automatically.",
                reply_markup=InlineKeyboardMarkup(btn),
                parse_mode=enums.ParseMode.HTML
            )
            # optional: save pending (same like callback flow)
            required_chat_id, total, step = await get_required_fsub_chat(client, user_id)
            token = await create_temp_token(int(user_id), link_key, ttl_seconds=600)
            temp_key = f"tk:{token}"
            await set_pending(int(user_id), temp_key, int(required_chat_id), int(step), int(total) if total else 1)
            return

        # ✅ already joined → send
        sent = await sendseries(client, f"{user_id}:start", link_key)
        if sent:
            await clear_pending(int(user_id))
            await message.reply_text("✅ Sent!")
        else:
            await message.reply_text("❌ No files found!")
        return
