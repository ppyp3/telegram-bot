FROM aiogram/telegram-bot-api

# تثبيت بايثون وأدوات البيئة الافتراضية
RUN apk update && apk add --no-cache python3 py3-pip py3-virtualenv bash curl

WORKDIR /app

# نسخ ملفات المشروع
COPY . /app/

# إنشاء بيئة افتراضية لتثبيت المكتبات بحرية تامة
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# تحديث وتثبيت مكتبات بايثون المطلوبة داخل البيئة الافتراضية
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir requests python-telegram-bot

# إعطاء صلاحية التشغيل لملف الإقلاع
RUN chmod +x entrypoint.sh

# نقطة التشغيل
ENTRYPOINT ["./entrypoint.sh"]
