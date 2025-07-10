FROM python:3.9-slim-buster

WORKDIR /app
RUN apt update && apt upgrade -y
RUN apt install git -y
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["bash", "start.sh"]
