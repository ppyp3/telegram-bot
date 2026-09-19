FROM aiogram/telegram-bot-api

RUN apk update && apk add --no-cache python3 py3-pip py3-virtualenv bash curl

WORKDIR /app

COPY . /app/

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip

# تثبيت كافة المكتبات المطلوبة للبوت هنا
RUN pip install --no-cache-dir requests python-telegram-bot instaloader

RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
