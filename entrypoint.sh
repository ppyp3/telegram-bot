#!/bin/bash

# تشغيل خادم Telegram Bot API المحلي في الخلفية باستخدام متغيرات البيئة من Railway
telegram-bot-api --api-id="$API_ID" --api-hash="$API_HASH" --local &

# الانتظار لثوانٍ حتى يستقر الخادم المحلي تماماً
sleep 3

# تشغيل بوت البايثون
python3 bot.py
