#!/bin/bash

# تشغيل خادم تيليجرام المحلي في الخلفية
telegram-bot-api --api-id="$TELEGRAM_API_ID" --api-hash="$TELEGRAM_API_HASH" --local &

# الانتظار قليلاً حتى يبدأ السيرفر المحلي ويستقر على المنفذ 8081
sleep 5

# تشغيل بوت البايثون 
python3 bot.py
