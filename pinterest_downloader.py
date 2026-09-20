import logging
from urllib.parse import urlparse
import requests
import re
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
        
        # فك الروابط المختصرة pin.it
        if "pin.it" in url:
            with requests.get(url, headers=headers, allow_redirects=True, timeout=(5, 15)) as resp:
                url = resp.url

        with requests.get(url, headers=headers, timeout=(8, 20)) as response:
            response.raise_for_status()
            html_content = response.text

        # البحث عن روابط الفيديو (mp4)
        video_match = re.search(r'"contentUrl"\s*:\s*"([^"]+\.mp4[^"]*)"', html_content)
        if not video_match:
            video_match = re.search(r'https?://[^"\s]+\.mp4[^"\s]*', html_content)

        if video_match:
            video_url = video_match.group(1) if '"contentUrl"' in video_match.string else video_match.group(0)
            video_url = video_url.replace(r'\u0026', '&')
            return {"type": "video", "url": video_url}

        # البحث عن الصور بجودة عالية
        img_matches = re.findall(r'https?://i\.pinimg\.com/originals/[^"\'\s]+', html_content)
        if not img_matches:
            img_matches = re.findall(r'https?://i\.pinimg\.com/736x/[^"\'\s]+', html_content)

        # إزالة التكرار
        seen = set()
        unique_images = [img for img in img_matches if not (img in seen or seen.add(img))]

        if unique_images:
            return {"type": "images", "urls": unique_images[:10]}

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
