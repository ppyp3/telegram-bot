#!/bin/bash

# تشغيل الخادم المحلي بالمتغيرات الصحيحة التي يطلبها النظام
telegram-bot-api --api-id="$TELEGRAM_API_ID" --api-hash="$TELEGRAM_API_HASH" --local &

# الانتظار لثوانٍ حتى يستقر الخادم
sleep 3

# تشغيل البوت
python3 bot.py
