@Client.on_callback_query(filters.regex(r"^ns:"))
async def ns_cb(client, cq):
    uid = cq.from_user.id
    if uid not in WIZ:
        return await cq.answer("Session expired. /newseries again", show_alert=True)

    st = WIZ[uid]
    data = cq.data.split(":", 1)[1]

    # ❌ Cancel
    if data == "cancel":
        WIZ.pop(uid, None)
        await cq.message.edit_text("❌ Cancelled.")
        return await cq.answer("Cancelled")

    # 🌐 Language → auto Season
    if data == "lang":
        ask = await client.ask(
            cq.message.chat.id,
            "🌐 Language name anuppu (ex: Multi Audio / Tamil):",
            timeout=120
        )
        st["language"] = (ask.text or "").strip()

        # ➜ auto go to Season
        ask2 = await client.ask(
            cq.message.chat.id,
            "📦 Season name anuppu (ex: Season 1 / Season 4 Part 2):",
            timeout=120
        )
        st["season"] = (ask2.text or "").strip()

        # ➜ auto go to Quality
        ask3 = await client.ask(
            cq.message.chat.id,
            "🎞 Quality anuppu (ex: 720p / 1080p):",
            timeout=120
        )
        st["quality"] = (ask3.text or "").strip()

        await cq.message.edit_text(
            wizard_text(st),
            reply_markup=kb_newseries()
        )
        return await cq.answer("Set")

    # 📦 Season → auto Quality
    if data == "season":
        if not st.get("language"):
            return await cq.answer("First Language set pannunga", show_alert=True)

        ask = await client.ask(
            cq.message.chat.id,
            "📦 Season name anuppu:",
            timeout=120
        )
        st["season"] = (ask.text or "").strip()

        ask2 = await client.ask(
            cq.message.chat.id,
            "🎞 Quality anuppu (ex: 720p / 1080p):",
            timeout=120
        )
        st["quality"] = (ask2.text or "").strip()

        await cq.message.edit_text(
            wizard_text(st),
            reply_markup=kb_newseries()
        )
        return await cq.answer("Set")

    # 🎞 Quality → back to main
    if data == "quality":
        if not st.get("language") or not st.get("season"):
            return await cq.answer("First Language & Season set pannunga", show_alert=True)

        ask = await client.ask(
            cq.message.chat.id,
            "🎞 Quality anuppu (ex: 720p / 1080p):",
            timeout=120
        )
        st["quality"] = (ask.text or "").strip()

        await cq.message.edit_text(
            wizard_text(st),
            reply_markup=kb_newseries()
        )
        return await cq.answer("Saved")

    # 📸 Poster (unchanged)
    if data == "poster":
        pmsg = await cq.message.reply_text("📸 Poster photo anuppu (send photo).")
        asyncio.create_task(auto_delete(pmsg, 10))
        pm = await client.listen(cq.message.chat.id)
        if not pm.photo:
            return await cq.answer("Photo illa", show_alert=True)
        await set_series_poster(st["series_id"], pm.photo.file_id)
        ok = await cq.message.reply_text("✅ Poster updated.")
        asyncio.create_task(auto_delete(ok, 10))
        return await cq.answer("Done")

    # ✅ Start Upload (unchanged)
    if data == "start":
        if not st.get("language") or not st.get("season") or not st.get("quality"):
            return await cq.answer("First Language/Season/Quality set pannunga", show_alert=True)

        group_id = await ensure_group(
            st["series_id"], st["language"], st["season"], st["quality"]
        )

        info = await cq.message.reply_text(
            f"📥 Now send files for:\n\n"
            f"**{st['title']}**\n"
            f"Language: `{st['language']}`\n"
            f"Season: `{st['season']}`\n"
            f"Quality: `{st['quality']}`\n\n"
            f"Finish panna `/done`"
        )

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

        done = await cq.message.reply_text(
            f"🎉 Done! **{st['title']}** saved: `{saved}` files ✅"
        )
        asyncio.create_task(auto_delete(done))
        asyncio.create_task(auto_delete(info, 30))

        WIZ.pop(uid, None)
        return await cq.answer("Saved")
