from aiohttp import web
from web.routes import routes

async def web_server():
    app = web.Application(client_max_size=30_000_000)
    app.add_routes(routes)
    return app
