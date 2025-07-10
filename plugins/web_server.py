import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

from aiohttp import web
from info import PORT
from database.ia_filterdb import get_file_details
import os

routes = web.RouteTableDef()

async def root_handler(request):
    return web.Response(text="Bot is running!")

@routes.get("/dl/{file_id}")
async def download_file(request):
    file_id = request.match_info['file_id']
    file_details = await get_file_details(file_id)
    
    if not file_details:
        return web.Response(text="File not found", status=404)
    
    file_details = file_details[0]
    
    # This is a placeholder. In a real scenario, you would serve the file
    # either by streaming it from Telegram (if the bot has access)
    # or by providing a direct link to a storage service.
    # For now, we'll just return a placeholder response.
    
    # Example: If you had a local downloads directory and files were saved there
    # file_path = os.path.join("DOWNLOADS", file_details.file_name)
    # if os.path.exists(file_path):
    #     return web.FileResponse(file_path, headers={'Content-Disposition': f'attachment; filename="{file_details.file_name}"'})
    
    return web.Response(text=f"Download link for {file_details.file_name} (File ID: {file_id}) is not directly served via web server. Please use the bot to get the file.", status=200)


async def web_server():
    app = web.Application()
    app.router.add_get("/", root_handler)
    app.add_routes(routes)
    return app
