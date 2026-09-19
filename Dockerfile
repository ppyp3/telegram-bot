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

# إنشاء بيئة افتراضية لتثبيت مكتبات البايثون بداخلها بعيداً عن قيود النظام
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# نسخ وتثبيت متطلبات البايثون داخل البيئة الافتراضية
COPY requirements.txt .
RUN pip3 install --no-cache-dir --upgrade pip && \
    pip3 install --no-cache-dir -r requirements.txt

# نسخ باقي الملفات
COPY . .

# إعداد ملف التشغيل
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
