from aiohttp import web
from .route import routes

# Explicitly import all plugin modules
from . import auto
from . import banned
from . import broadcast
from . import commands
from . import crazy # Using the more advanced 'crazy.py' for series management
from . import eval
from . import fsub
from . import genlink
from . import get_file_id
from . import gfilters
from . import inline
from . import join_req
from . import p_ttishow
from . import ping
from . import pmfilter
from . import request_forcesub


async def web_server():
    web_app = web.Application(client_max_size=30000000)
    web_app.add_routes(routes)
    return web_app
