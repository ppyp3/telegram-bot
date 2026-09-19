#!/bin/bash

echo "Starting Telegram Bot API Server..."
telegram-bot-api --api-id="$TELEGRAM_API_ID" --api-hash="$TELEGRAM_API_HASH" --local &

echo "Waiting for server to be ready..."
sleep 5

echo "Starting Python Bot..."
python3 bot.py
