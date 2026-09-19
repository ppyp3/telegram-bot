#!/bin/bash

echo "=== Starting Telegram Bot API Server ==="
echo "API ID is set: ${TELEGRAM_API_ID:+yes}"

# تشغيل الخادم المحلي مع تمرير المتغيرات بشكل صريح وتحديد المنفذ والمجلدات
telegram-bot-api \
  --api-id="$TELEGRAM_API_ID" \
  --api-hash="$TELEGRAM_API_HASH" \
  --local \
  --http-port=8081 \
  --dir=/var/lib/telegram-bot-api \
  --temp-dir=/tmp/telegram-bot-api &

SERVER_PID=$!

echo "Waiting 6 seconds for the local server to initialize..."
sleep 6

echo "=== Starting Python Bot Process ==="
python3 bot.py

# إبقاء الحاوية متصلة في حال توقف أي عملية
wait $SERVER_PID
