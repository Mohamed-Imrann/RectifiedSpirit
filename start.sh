#!/bin/bash

python3 bot.py

# ** rest of code here **
gunicorn --worker-class aiohttp.GunicornWebWorker -b 0.0.0.0:8000 app:app
