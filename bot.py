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

def upgrade_image_to_hd(img_url):
    if not img_url:
        return img_url
    # استبدال أي حجم متوسط (مثل 736x, 564x, 470x) إلى الدقة الأصلية originals
    hd_url = re.sub(r'/(?:736x|564x|470x|236x|150x|originals)/', '/originals/', img_url)
    return hd_url

def fetch_pinterest_media(raw_url):
    try:
        url = extract_url(raw_url)
        headers = request_headers()
        
        # فك الروابط المختصرة pin.it
        if "pin.it" in url:
            with requests.get(url, headers=headers, allow_redirects=True, timeout=(5, 15)) as resp:
                url = resp.url

        with requests.get(url, headers=headers, timeout=(8, 20)) as response:
            response.raise_for_status()
            html_content = response.text
            soup = BeautifulSoup(html_content, 'html.parser')

        # 1. البحث أولاً عن الفيديو
        video_match = re.search(r'"contentUrl"\s*:\s*"([^"]+\.mp4[^"]*)"', html_content)
        if not video_match:
            og_video = soup.find('meta', property='og:video')
            if og_video and og_video.get('content'):
                return {"type": "video", "url": og_video['content']}
            
            video_match = re.search(r'https?://[^"\s]+\.mp4[^"\s]*', html_content)

        if video_match:
            video_url = video_match.group(1) if '"contentUrl"' in video_match.string else video_match.group(0)
            video_url = video_url.replace(r'\u0026', '&')
            return {"type": "video", "url": video_url}

        # 2. البحث عن الصورة وتحسينها لأعلى دقة (originals)
        img_url = None
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            img_url = og_image['content']
        else:
            twitter_image = soup.find('meta', name='twitter:image')
            if twitter_image and twitter_image.get('content'):
                img_url = twitter_image['content']

        if img_url:
            hd_img_url = upgrade_image_to_hd(img_url)
            return {"type": "image", "url": hd_img_url}

        return None

    except Exception:
        logger.exception("Error fetching Pinterest media")
        return None

async def handle_pinterest_message(update: Update, context):
    message = update.message
    if not message or not message.text:
        return

    raw_text = message.text.strip()
    if not is_valid_pinterest_url(raw_text):
        return

    processing_msg = await message.reply_text("⏰┇جاري جلب المحتوى بأعلى دقة...")

    try:
        media_data = fetch_pinterest_media(raw_text)

        if not media_data:
            await processing_msg.edit_text("❌ لم يتم العثور على محتوى قابل للتحميل في هذا الرابط.")
            return

        media_type = media_data.get("type")
        media_url = media_data.get("url")

        if media_type == "video":
            local_path = download_media(media_url, ".mp4")
            try:
                await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.UPLOAD_VIDEO)
                with open(local_path, "rb") as vid_file:
                    await message.reply_video(video=vid_file, caption="- @G66Gbot")
                await processing_msg.delete()
            finally:
                if local_path:
                    local_path.unlink(missing_ok=True)

        elif media_type == "image":
            local_path = download_media(media_url, ".jpg")
            try:
                await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.UPLOAD_PHOTO)
                with open(local_path, "rb") as img_file:
                    # استخدام reply_photo يرسل الصورة كاملة وصافية (وليس كملف مضغوط أو مصغر)
                    await message.reply_photo(photo=img_file, caption="- @G66Gbot")
                await processing_msg.delete()
            finally:
                if local_path:
                    local_path.unlink(missing_ok=True)
        else:
            await processing_msg.edit_text("❌ عذراً، لم نتمكن من تحديد نوع المحتوى.")

    except Exception:
        logger.exception("Error in handle_pinterest_message")
        await processing_msg.edit_text("⚠️ حدث خطأ أثناء التحميل، جرب رابطاً آخر.")
