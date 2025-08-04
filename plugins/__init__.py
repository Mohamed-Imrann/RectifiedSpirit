import os
import importlib
from aiohttp import web
from .route import routes

# Get the directory of the current file (plugins folder)
plugins_dir = os.path.dirname(__file__)

# List to keep track of imported modules (optional, for debugging)
imported_modules = []

# Iterate over files in the plugins directory
for filename in os.listdir(plugins_dir):
    if filename.endswith(".py") and not filename.startswith("__"):
        module_name = filename[:-3] # Remove .py extension

        # Skip 'craz_old.py' if 'crazy.py' is present, to prioritize the newer series management
        if module_name == "craz_old" and "crazy" in os.listdir(plugins_dir):
            print(f"Skipping import of {filename} as crazy.py is preferred.")
            continue

        try:
            # Import the module dynamically
            module = importlib.import_module(f".{module_name}", package="plugins")
            imported_modules.append(module)
            print(f"Successfully imported plugin: {module_name}")
        except Exception as e:
            print(f"Failed to import plugin {module_name}: {e}")

async def web_server():
    web_app = web.Application(client_max_size=30000000)
    web_app.add_routes(routes)
    return web_app
