FROM python:3.10

WORKDIR /app
RUN apt update && apt upgrade -y
RUN apt install git -y
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["bash", "start.sh"]
