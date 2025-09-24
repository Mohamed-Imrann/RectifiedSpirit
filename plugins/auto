import re
import asyncio
from info import userbot, BOT_USERNAME, CHANNELS
from pyrogram import Client, filters
from pyrogram.types import Message

first_link = None
last_link = None
series_name = None
language = None
season = None
quality = None


def extract_series_details(text):
    pattern = r'^SADD\s+([^\s]+)\s+"([^"]+)"\s+"([^"]+)"\s+"([^"]+)"'
    match = re.match(pattern, text)
    if match:
        return match.groups()
    return None, None, None, None


def convert_link_to_format(first_link, last_link):
    first_match = re.search(r't\.me/c/(\d+)/(\d+)', first_link)
    last_match = re.search(r't\.me/c/(\d+)/(\d+)', last_link)

    if first_match and last_match:
        channel_id = first_match.group(1)
        first_msg_id = int(first_match.group(2))
        last_msg_id = int(last_match.group(2))

        adjusted_first = first_msg_id + 1
        adjusted_last = last_msg_id - 1

        return f"get_{channel_id}_{adjusted_first}_{adjusted_last}"

    return None


async def send_to_bot_and_wait(userbot):
    global first_link, last_link, series_name, language, season, quality

    converted_format = convert_link_to_format(first_link, last_link)
    if converted_format:
        await userbot.send_message(
            BOT_USERNAME,
            text=f"/quality {series_name} \"{language}\" \"{season}\" \"{quality}\" {converted_format}"
        )

    first_link = None
    last_link = None
    series_name = None
    language = None
    season = None
    quality = None


@Client.on_message(filters.channel & filters.chat(CHANNELS) & filters.text)
async def listen_channel(client: Client, message: Message):
    global first_link, last_link, series_name, language, season, quality
    text = message.text
    if text.startswith("SADD"):
        first_link = message.link
        series_name, language, season, quality = extract_series_details(text)
    elif text.startswith("SEND"):
        last_link = message.link
        await send_to_bot_and_wait(userbot)
