import logging
from urllib.parse import urlparse
import requests
from telegram import Update, InputMediaPhoto
from telegram.constants import ChatAction
from media_helper import download_media, request_headers

logger = logging.getLogger(__name__)

def is_valid_pinterest_url(url):
    try:
        parsed = urlparse(url.strip())
        hostname = (parsed.hostname or "").lower().rstrip(".")
        return "pinterest" in hostname or "pin.it" in hostname
    except Exception:
        return False

def fetch_pinterest_data(url):
    try:
        headers = request_headers()
        headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
        headers["X-Requested-With"] = "XMLHttpRequest"

        # إذا كان الرابط المختصر pin.it، نقوم بفك الروابط القصيرة أولاً للحصول على الرابط الأصلي
        if "pin.it" in url:
            with requests.get(url, headers=headers, allow_redirects=True, timeout=(5, 15)) as resp:
                url = resp.url

        # استخدام API عام مجاني ومستقر لجلب تفاصيل بينترست (فيديو أو صور)
        api_url = f"https://www.pinterest._/resource/PinResource/get/?source_url={url}&data={%7B%22id%22:%22%22,%22field_set_key%22:%22detailed%22%7D"
        # بديل api موثوق للعموم أو استخراج مباشر باستخدام الـ scraper البسيط
        
        # سنستخدم طريقة دقيقة وموثوقة عبر الـ scraping السريع لصفحة بينترست لاستخراج روابط الصور أو الفيديو
        with requests.get(url, headers=headers, timeout=(8, 20)) as response:
            response.raise_for_status()
            html_content = response.text

        import re
        
        # البحث عن روابط الفيديو (mp4)
        video_match = re.search(r'"contentUrl"\s*:\s*"([^"]+\.mp4[^"]*)"', html_content)
        if not video_match:
            video_match = re.search(r'https?://[^"\s]+\.mp4[^"\s]*', html_content)

        if video_match:
            video_url = video_match.group(1) if '"contentUrl"' in video_match.string else video_match.group(0)
            video_url = video_url.replace(r'\u0026', '&')
            return {"type": "video", "url": video_url}

        # البحث عن الصور (عالية الدقة)
        images = []
        # البحث عن صور الـ originals أو العادية
        img_matches = re.findall(r'https?://i\.pinimg\.com/originals/[^"\'\s]+', html_content)
        if not img_matches:
            img_matches = re.findall(r'https?://i\.pinimg\.com/736x/[^"\'\s]+', html_content)

        # إزالة التكرار مع الحفاظ على الترتيب
        seen = set()
        unique_images = [img for img in img_matches if not (img in seen or seen.add(img))]

        if unique_images:
            # إذا وجدت صور متعددة أو صورة واحدة
            return {"type": "images", "urls": unique_images[:10]} # حد أقصى 10 صور كألبوم

        return None

    except Exception:
        logger.exception("Error fetching Pinterest data")
        return None

async def handle_pinterest_message(update: Update, context):
    message = update.message
    if not message or not message.text:
        return

    url = message.text.strip()
    if not is_valid_pinterest_url(url):
        return

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
                # صورة واحدة فقط
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
                # عدة صور (ألبوم ميديا جروب)
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
