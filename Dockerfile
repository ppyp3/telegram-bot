FROM aiogram/telegram-bot-api:latest

# تثبيت بايثون و ffmpeg باستخدام مدير الحزم apk الخاص بنظام Alpine
RUN apk update && apk add --no-cache \
    python3 \
    py3-pip \
    ffmpeg \
    bash

WORKDIR /app

# نسخ وتثبيت متطلبات البايثون
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt || pip3 install --no-cache-dir -r requirements.txt

# نسخ باقي الملفات
COPY . .

# إعداد ملف التشغيل
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
