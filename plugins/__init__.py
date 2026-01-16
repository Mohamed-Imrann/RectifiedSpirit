from aiohttp import web
from .route import routes
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Plugins package initialization

All files in this directory will be automatically loaded as plugins
"""

import logging

logger = logging.getLogger(__name__)
logger.info("📦 Plugins package loaded")

async def web_server():
    web_app = web.Application(client_max_size=30000000)
    web_app.add_routes(routes)
    return web_app
