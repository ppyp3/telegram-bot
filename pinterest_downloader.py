import logging
from urllib.parse import urlparse
import requests
import re
from telegram import Update, InputMediaPhoto
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

def fetch_pinterest_data(raw_url):
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

        # 1. البحث عن روابط الفيديو (mp4)
        video_match = re.search(r'"contentUrl"\s*:\s*"([^"]+\.mp4[^"]*)"', html_content)
        if not video_match:
            video_match = re.search(r'https?://[^"\s]+\.mp4[^"\s]*', html_content)

        if video_match:
            video_url = video_match.group(1) if '"contentUrl"' in video_match.string else video_match.group(0)
            video_url = video_url.replace(r'\u0026', '&')
            return {"type": "video", "url": video_url}

        # 2. البحث الشامل عن روابط الصور في بينترست (تشمل originals, 736x, 564x, وغيرها)
        img_matches = re.findall(r'https?://i\.pinimg\.com/(?:originals|736x|564x|470x|236x)/[0-9a-f/]+[^\s"\'<>]+', html_content)
        
        # إذا لم يتم العثور بالطريقة الأولى، نلتقط أي رابط يحتوي على pinimg.com/originals أو 736x
        if not img_matches:
            img_matches = re.findall(r'https?://i\.pinimg\.com/[^"\'\s>]+', html_content)

        # تصفية الروابط لاستبعاد الأيقونات والصور الصغيرة جداً (مثل الـ avatars أو الـ emojis)
        filtered_images = []
        for img in img_matches:
            # استبعاد الروابط الصغيرة أو الأيقونات الشخصية المعتادة
            if any(x in img for x in ["avatars", "profile", "icon", "16x16", "32x32", "60x60"]):
                continue
            # التأكد من أنها صورة صالحة (تهدُف للصور الكبيرة)
            if any(ext in img.lower() for ext in [".jpg", ".png", ".webp", "/originals/", "/736x/", "/564x/"]):
                filtered_images.append(img)

        # إزالة التكرار مع الحفاظ على الترتيب
        seen = set()
        unique_images = [img for img in filtered_images if not (img in seen or seen.add(img))]

        if unique_images:
            # إعادة ترتيب الروابط بحيث تكون صور الـ originals أو الدقة العالية في المقدمة إن وجدت
            unique_images.sort(key=lambda x: 0 if "originals" in x else (1 if "736x" in x else 2))
            return {"type": "images", "urls": unique_images[:10]}

        return None

    except Exception:
        logger.exception("Error fetching Pinterest data")
        return None

async def handle_pinterest_message(update: Update, context):
    message = update.message
    if not message or not message.text:
        return

    raw_text = message.text.strip()
    if not is_valid_pinterest_url(raw_text):
        return

    url = extract_url(raw_text)
    processing_msg = await message.reply_text("⏰┇جاري جلب المحتوى من بينترست...")

    try:
        data = fetch_pinterest_data(url)

        if not data:
            await processing_msg.edit_text("❌ لم يتم العثور على محتوى قابل للتحميل في هذا الرابط.")
            return

        media_type = data.get("type")

        if media_type == "video":
            video_url = data.get("url")
            local_path = download_media(video_url, ".mp4")

            try:
                await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.UPLOAD_VIDEO)
                with open(local_path, "rb") as vid_file:
                    await message.reply_video(video=vid_file, caption="- @G66Gbot")
                await processing_msg.delete()
            finally:
                if local_path:
                    local_path.unlink(missing_ok=True)

        elif media_type == "images":
            image_urls = data.get("urls", [])
            
            if len(image_urls) == 1:
                img_url = image_urls[0]
                local_path = download_media(img_url, ".jpg")
                try:
                    await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.UPLOAD_PHOTO)
                    with open(local_path, "rb") as img_file:
                        await message.reply_photo(photo=img_file, caption="- @G66Gbot")
                    await processing_msg.delete()
                finally:
                    if local_path:
                        local_path.unlink(missing_ok=True)
            else:
                await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.UPLOAD_PHOTO)
                media_group = []
                for idx, img_url in enumerate(image_urls):
                    if idx == len(image_urls) - 1:
                        media_group.append(InputMediaPhoto(media=img_url, caption="- @G66Gbot"))
                    else:
                        media_group.append(InputMediaPhoto(media=img_url))

                await message.reply_media_group(media=media_group)
                await processing_msg.delete()
        else:
            await processing_msg.edit_text("❌ عذراً، لم نتمكن من معالجة هذا النوع من روابط بينترست.")

    except Exception:
        logger.exception("Error in handle_pinterest_message")
        await processing_msg.edit_text("⚠️ حدث خطأ أثناء تحميل الملف، يجدر المحاولة مع رابط آخر.")
