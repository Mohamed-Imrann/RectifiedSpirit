# main.py
from pyrogram import Client
from info import API_ID, API_HASH, BOT_TOKEN, USER_SESSION

bot = Client(
    "bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins={"root": "plugins"}
)

user = Client(
    "user",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=USER_SESSION,
)

async def main():
    await user.start()          # 🔥 USER FIRST
    bot.user_client = user      # 🔥 ATTACH USER TO BOT
    await bot.start()
    await idle()

if __name__ == "__main__":
    bot.run(main())
