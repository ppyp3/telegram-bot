# استخدام صورة جاهزة تحتوي على سيرفر تيليجرام وبايثون
FROM aiogram/telegram-bot-api

# تثبيت بايثون والمكتبات إذا لم تكن موجودة
RUN apt-get update && apt-get install -y python3 python3-pip

# تحديد مجلد العمل داخل الحاوية
WORKDIR /app

# نسخ ملفات المشروع إلى المجلد الحالي
COPY . /app/

# تثبيت متطلبات بايثون إن وجدت
RUN pip3 install --no-cache-dir requests pyrogram tgcrypto || true
# أضف هنا أي مكتبات أخرى يحتاجها بوتك مثل python-telegram-bot

# إعطاء صلاحية التشغيل لملف الإقلاع
RUN chmod +x entrypoint.sh

# تشغيل السكريبت عند بدء الحاوية
ENTRYPOINT ["./entrypoint.sh"]
