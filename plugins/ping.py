import time
import asyncio
import psutil
import logging
from pyrogram import Client, filters
from pyrogram.types import Message

from utils import auto_delete

logger = logging.getLogger(__name__)
START_TIME = time.time()

def uptime_str() -> str:
    s = int(time.time() - START_TIME)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    return f"{d}d {h}h {m}m {s}s"

@Client.on_message(filters.command("ping"))
async def ping(client: Client, message: Message):
    t1 = time.time()
    rm = await message.reply_text("👀")
    t2 = time.time()
    ms = (t2 - t1) * 1000

    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent

    await rm.edit_text(
        f"🏓 **Ping:** `{ms:.2f} ms`\n"
        f"⏰ **Uptime:** `{uptime_str()}`\n"
        f"🤖 **CPU:** `{cpu}%`\n"
        f"📥 **RAM:** `{ram}%`"
    )
    logger.info(f"Ping reply sent: {ms:.2f} ms, CPU={cpu}%, RAM={ram}%")
    asyncio.create_task(auto_delete(rm))

@Client.on_message(filters.command("alive"))
async def alive(client: Client, message: Message):
    m = await message.reply_text("✅ Buddy I am Alive 🙂 Hit /ping")
    logger.info("Alive check responded")
    asyncio.create_task(auto_delete(m))
