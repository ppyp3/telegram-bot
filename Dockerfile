FROM aiogram/telegram-bot-api:latest

# تثبيت الحزم الأساسية ونظام بايثون مباشرة من مستودعات Alpine الموثوقة
RUN apk update && apk add --no-cache \
    python3 \
    py3-pip \
    py3-requests \
    py3-setuptools \
    py3-wheel \
    ffmpeg \
    bash \
    gcc \
    musl-dev \
    python3-dev

WORKDIR /app

# إنشاء البيئة الافتراضية
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# تحديث pip وتثبيت المكتبات الأساسية المطلوبة للبوت مباشرة لتجنب أخطاء التحميل
RUN pip3 install --no-cache-dir --upgrade pip && \
    pip3 install --no-cache-dir python-telegram-bot yt-dlp requests ffmpeg-python

# نسخ ملف الإقلاع وإعطاؤه صلاحية التشغيل
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# تحديد نقطة الدخول لتشغيل السكريبت الخاص بنا
ENTRYPOINT ["/entrypoint.sh"]
