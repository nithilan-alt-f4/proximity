FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir yt-dlp flask gunicorn

COPY app.py start.sh ./
RUN chmod +x start.sh

EXPOSE 5000
CMD ["./start.sh"]
