import logging
import re
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.constants import ChatAction
from media_helper import download_media, request_headers

logger = logging.getLogger(__name__)

def extract_url(text):
    if not text:
        return None
    match = re.search(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text)
    if match:
        url = match.group(0)
        if url.startswith('www.'):
            url = 'https://' + url
        return url
    return text.strip()

def is_valid_pinterest_url(text):
    if not text:
        return False
    url = extract_url(text)
    if not url:
        return False
    url_lower = url.lower()
    return "pinterest." in url_lower or "pin.it/" in url_lower

def fetch_pinterest_thumbnail(raw_url):
    try:
        url = extract_url(raw_url)
        headers = request_headers()
        
        # فك الروابط المختصرة pin.it
        if "pin.it" in url:
            with requests.get(url, headers=headers, allow_redirects=True, timeout=(5, 15)) as resp:
                url = resp.url

        with requests.get(url, headers=headers, timeout=(8, 20)) as response:
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # 1. البحث عن وسوم og:image أو twitter:image (صورة المعاينة الرسمية للرابط)
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                return og_image['content']

            twitter_image = soup.find('meta', name='twitter:image')
            if twitter_image and twitter_image.get('content'):
                return twitter_image['content']

            # 2. كاحتياط، البحث عن أول صورة واضحة داخل الصفحة
            img_tag = soup.find('img', src=True)
            if img_tag and 'pinimg.com' in img_tag['src']:
                return img_tag['src']

        return None

    except Exception:
        logger.exception("Error fetching Pinterest thumbnail")
        return None

async def handle_pinterest_message(update: Update, context):
    message = update.message
    if not message or not message.text:
        return

    raw_text = message.text.strip()
    if not is_valid_pinterest_url(raw_text):
        return

    processing_msg = await message.reply_text("⏰┇جاري جلب الصورة من بينترست...")

    try:
        img_url = fetch_pinterest_thumbnail(raw_text)

        if not img_url:
            await processing_msg.edit_text("❌ لم يتم العثور على صورة قابلة للتحميل في هذا الرابط.")
            return

        # تنزيل وإرسال الصورة المصغرة بدقة وثبات
        local_path = download_media(img_url, ".jpg")

        try:
            await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.UPLOAD_PHOTO)
            with open(local_path, "rb") as img_file:
                await message.reply_photo(photo=img_file, caption="- @G66Gbot")
            await processing_msg.delete()
        finally:
            if local_path:
                local_path.unlink(missing_ok=True)

    except Exception:
        logger.exception("Error in handle_pinterest_message")
        await processing_msg.edit_text("⚠️ حدث خطأ أثناء تحميل الصورة، جرب رابطاً آخر.")
