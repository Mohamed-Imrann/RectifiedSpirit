import time
from pyrogram import Client, filters
import psutil
import asyncio

start_time = time.time()

async def get_bot_uptime():
    # Calculate the uptime in seconds
    uptime_seconds = int(time.time() - start_time)
    uptime_minutes = uptime_seconds // 60
    uptime_hours = uptime_minutes // 60
    uptime_days = uptime_hours // 24
    uptime_weeks = uptime_days // 7
    ###############################
    uptime_string = f"{uptime_days % 7}Days:{uptime_hours % 24}Hours:{uptime_minutes % 60}Minutes:{uptime_seconds % 60}Seconds"
    return uptime_string

@Client.on_message(filters.command("ping")) 
async def ping(_, message):
    start_t = time.time()
    rm = await message.reply_text("👀")
    end_t = time.time()
    time_taken_s = (end_t - start_t) * 1000
    uptime = await get_bot_uptime()
    cpu_usage = psutil.cpu_percent()
    ram_usage = psutil.virtual_memory().percent
    await rm.edit(f"🏓 𝖯𝗂𝗇𝗀: <code>{time_taken_s:.3f} ms</code>\n\n⏰ 𝖴𝗉𝗍𝗂𝗆𝖾: <code>{uptime}</code>\n🤖 𝖢𝖯𝖴 𝖴𝗌𝖺𝗀𝖾: <code>{cpu_usage} %</code>\n📥 𝖱𝖺𝗆 𝖴𝗌𝖺𝗀𝖾: <code>{ram_usage} %</code>")

@Client.on_message(filters.command("alive"))
async def check_alive(_, message):
    await message.reply_text("𝖡𝗎𝖽𝖽𝗒 𝖨𝖺𝗆 𝖠𝗅𝗂𝗏𝖾 :) 𝖧𝗂𝗍 /start", quote=True)
