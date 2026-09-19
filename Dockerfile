FROM aiogram/telegram-bot-api:latest

# تثبيت الحزم الأساسية وأدوات البناء لنظام Alpine
RUN apk update && apk add --no-cache \
    python3 \
    py3-pip \
    py3-virtualenv \
    py3-setuptools \
    py3-wheel \
    ffmpeg \
    bash \
    gcc \
    musl-dev \
    python3-dev \
    libffi-dev \
    openssl-dev

WORKDIR /app

# إنشاء وتفعيل البيئة الافتراضية
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# نسخ ملف المتطلبات
COPY requirements.txt .

# تحديث أدوات التثبيت
RUN pip3 install --no-cache-dir --upgrade pip setuptools wheel

# تثبيت المكتبات مع اختيار النسخ الثنائية الجاهزة حصراً لتجنب أخطاء البناء
RUN pip3 install --no-cache-dir --prefer-binary -r requirements.txt

# نسخ باقي الملفات
COPY . .

# إعداد ملف التشغيل
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
