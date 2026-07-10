#!/bin/bash
set -e

# If YT_COOKIES is set (Render Secret File or env var), write it to disk
# so yt-dlp can use it. Never commit an actual cookies.txt to the repo.
if [ -n "$YT_COOKIES" ]; then
  echo "$YT_COOKIES" > /tmp/cookies.txt
  echo "cookies loaded"
else
  echo "WARNING: no YT_COOKIES set, downloads will likely hit the bot-check wall"
fi

exec gunicorn -w 2 --threads 4 -b 0.0.0.0:${PORT:-5000} --timeout 300 app:app
