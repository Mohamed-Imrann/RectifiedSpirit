#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from bot import Bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)

if __name__ == "__main__":
    # ✅ This keeps the bot running (Pyrogram loop)
    Bot().run()
