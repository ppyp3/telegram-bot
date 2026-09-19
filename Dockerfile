FROM aiogram/telegram-bot-api:latest

# تثبيت بايثون وأدوات البناء ونظام البيئة الافتراضية
RUN apk update && apk add --no-cache \
    python3 \
    py3-pip \
    py3-virtualenv \
    ffmpeg \
    bash \
    gcc \
    musl-dev \
    python3-dev \
    libffi-dev \
    openssl-dev

WORKDIR /app

# إنشاء البيئة الافتراضية وتفعيلها
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# نسخ ملف المتطلبات أولاً
COPY requirements.txt .

# تحديث أداة pip بمعزل عن الحزم
RUN pip3 install --no-cache-dir --upgrade pip

# تثبيت الحزم المطلوبة من الملف
RUN pip3 install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات المشروع
COPY . .

# إعداد ملف التشغيل
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
