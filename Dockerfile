FROM python:3.9.7-slim-buster

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# System deps
RUN apt update && apt upgrade -y \
    && apt install -y git build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python deps first (better cache)
COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.txt

# App directory
WORKDIR /app
COPY . /app

# Start bot
CMD ["python", "main.py"]

