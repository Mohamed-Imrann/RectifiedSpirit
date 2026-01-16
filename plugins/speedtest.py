import asyncio
import speedtest
from time import time

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode

from utils import auto_delete


def convert_from_bits_per_sec(bps: float) -> str:
    units = ["bps", "Kbps", "Mbps", "Gbps", "Tbps"]
    i = 0
    while bps >= 1000 and i < len(units) - 1:
        bps /= 1000
        i += 1
    return f"{bps:.2f} {units[i]}"


@Client.on_message(filters.command("speedtest"))
async def speedtest_command_handler(client: Client, message: Message):
    """
    /speedtest          -> image (default)
    /speedtest text     -> text output
    /speedtest file     -> send image as document
    """
    parts = (message.text or "").split(maxsplit=1)
    option = parts[1].lower().strip() if len(parts) > 1 else "image"

    as_text = (option == "text")
    as_file = (option == "file")

    processing = await message.reply_text("`Calculating internet speed... please wait!`")

    start_t = time()
    try:
        s = speedtest.Speedtest()
        s.get_best_server()
        s.download()
        s.upload()
        end_t = time()

        took = round(end_t - start_t, 2)
        r = s.results.dict()

        down_bps = float(r.get("download", 0))
        up_bps = float(r.get("upload", 0))
        ping_ms = float(r.get("ping", 0))

        down_hr = convert_from_bits_per_sec(down_bps)
        up_hr = convert_from_bits_per_sec(up_bps)

        down_mbs = round((down_bps / 8) / 1e6, 2)
        up_mbs = round((up_bps / 8) / 1e6, 2)

        if as_text:
            txt = (
                f"🏁 **SpeedTest** done in `{took}s`\n\n"
                f"⬇️ Download: `{down_hr}` | `{down_mbs} MB/s`\n"
                f"⬆️ Upload: `{up_hr}` | `{up_mbs} MB/s`\n"
                f"🏓 Ping: `{ping_ms:.2f} ms`"
            )
            await processing.edit(txt, parse_mode=ParseMode.MARKDOWN)
            asyncio.create_task(auto_delete(processing))
            return

        img_url = s.results.share()
        cap = (
            f"🏁 **SpeedTest** done in `{took}s`\n\n"
            f"⬇️ Download: `{down_hr}` | `{down_mbs} MB/s`\n"
            f"⬆️ Upload: `{up_hr}` | `{up_mbs} MB/s`\n"
            f"🏓 Ping: `{ping_ms:.2f} ms`"
        )

        if as_file:
            sent = await client.send_document(
                chat_id=message.chat.id,
                document=img_url,
                caption=cap,
                parse_mode=ParseMode.MARKDOWN,
                reply_to_message_id=message.id,
            )
        else:
            sent = await client.send_photo(
                chat_id=message.chat.id,
                photo=img_url,
                caption=cap,
                parse_mode=ParseMode.MARKDOWN,
                reply_to_message_id=message.id,
            )

        await processing.delete()
        asyncio.create_task(auto_delete(sent))

    except Exception as exc:
        await processing.edit(f"❌ **SpeedTest Error:** `{exc}`", parse_mode=ParseMode.MARKDOWN)
        asyncio.create_task(auto_delete(processing))
