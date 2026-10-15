FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# База данных хранится в /data (смонтируйте том, чтобы не терять сообщения).
ENV DB_PATH=/data/messages.db
VOLUME ["/data"]

CMD ["python", "-m", "app.bot"]
