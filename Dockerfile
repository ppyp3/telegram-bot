# استخدام صورة خادم تيليجرام الرسمي كقاعدة أساسية لتشغيل الـ Local API
FROM aiogram/telegram-bot-api:latest

# تثبيت بايثون وحزم النظام المطلوبة (مثل ffmpeg) داخل نفس الحاوية
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# تحديد مجلد العمل
WORKDIR /app

# نسخ وتثبيت متطلبات البايثون
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات المشروع
COPY . .

# نسخ وإعطاء صلاحية التنفيذ لملف التشغيل المساعد
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# تشغيل خادم تيليجرام وبوت البايثون معاً
CMD ["/entrypoint.sh"]
