FROM aiogram/telegram-bot-api

# تثبيت بايثون ومدير الحزم وباصمات الأمان
RUN apk update && apk add --no-cache python3 py3-pip bash curl

WORKDIR /app

# نسخ ملف المتطلبات أولاً (إن وجد) أو نسخ المشروع كاملاً
COPY . /app/

# تثبيت جميع مكتبات بايثون المطلوبة
RUN pip3 install --no-cache-dir --upgrade pip
RUN pip3 install --no-cache-dir requests python-telegram-bot

# إعطاء صلاحية التشغيل لملف الإقلاع
RUN chmod +x entrypoint.sh

# نقطة التشغيل
ENTRYPOINT ["./entrypoint.sh"]
