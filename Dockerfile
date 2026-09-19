FROM aiogram/telegram-bot-api

# تثبيت بايثون باستخدام مدير الحزم apk الخاص بـ Alpine
RUN apk update && apk add --no-cache python3 py3-pip bash

WORKDIR /app

COPY . /app/

# تثبيت متطلبات بايثون إن وجدت
RUN pip3 install --no-cache-dir requests python-telegram-bot || true

RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
