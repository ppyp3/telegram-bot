FROM aiogram/telegram-bot-api:latest

# تثبيت بايثون وأدوات البناء اللازمة لمكتبات البايثون على نظام Alpine
RUN apk update && apk add --no-cache \
    python3 \
    py3-pip \
    ffmpeg \
    bash \
    gcc \
    musl-dev \
    python3-dev \
    libffi-dev \
    openssl-dev

WORKDIR /app

# نسخ وتثبيت متطلبات البايثون مع تحديث الـ pip أولاً
COPY requirements.txt .
RUN pip3 install --no-cache-dir --upgrade pip && \
    pip3 install --no-cache-dir --break-system-packages -r requirements.txt || pip3 install --no-cache-dir -r requirements.txt

# نسخ باقي الملفات
COPY . .

# إعداد ملف التشغيل
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
