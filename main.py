# run_bot.py
import asyncio
from bot import Bot  # Import the Bot class from bot.py

async def main():
    app = Bot()  # Initialize the bot
    await app.start()  # Start the bot
    await app.idle()  # Keep the bot running
    await app.stop()  # Stop the bot when done

if __name__ == "__main__":
    asyncio.run(main())
