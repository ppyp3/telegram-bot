import asyncio
import logging
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from telegram.constants import ChatAction
from telegram import InputMediaPhoto

from media_helper import download_media, request_headers  # أو يمكنك وضع الدوال المشتركة هنا

logger = logging.getLogger(__name__)

def is_valid_pinterest_url(url):
    """التحقق مما إذا كان الرابط يتبع لموقع بينترست"""
    parsed = urlparse(url.strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    return "pinterest." in hostname or hostname == "pin.it"

def download_pinterest_with_ytdlp(url):
    """استخراج الصور المباشر عبر الكشط (Scraping) لدعم اللوحات والمنشورات المتعددة من بينترست"""
    files = []
    try:
        headers = request_headers()
        target_url = url
        
        # تتبع الروابط المختصرة pin.it
        if "pin.it" in url:
            with requests.get(url, allow_redirects=True, timeout=(10, 25), headers=headers) as resp:
                resp.raise_for_status()
                target_url = resp.url

        with requests.get(target_url, headers=headers, timeout=(10, 25)) as resp:
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')

        image_urls = set()
        
        # البحث في وسوم og:image
        for tag in soup.find_all("meta", property="og:image") + soup.find_all("meta", attrs={"name": "og:image"}):
            img_url = tag.get("content")
            if img_url and "pinimg.com" in img_url:
                image_urls.add(img_url)

        # البحث في جميع صور الصفحة وتحويلها للنسخة الأصلية عالية الجودة
        for img in soup.find_all("img"):
            src = img.get("src")
            if src and "pinimg.com" in src:
                high_res_url = src.replace("/236x/", "/originals/").replace("/736x/", "/originals/").replace("/474x/", "/originals/")
                image_urls.add(high_res_url)

        # تحميل الصور المستخرجة (بحد أقصى 15 صورة لضمان السرعة والتوافق مع التليجرام)
        for img_url in list(image_urls)[:15]:
            try:
                img_path = download_media(img_url, ".jpg")
                if img_path:
                    files.append((img_path, "photo"))
            except Exception:
                continue

    except Exception:
        logger.exception("Direct scraping failed for Pinterest URL")

    return files

async def handle_pinterest_message(update, context):
    """معالجة وإرسال وسائط بينترست (صور أو ألبومات)"""
    text = update.message.text if update.message and update.message.text else ""
    words = text.split()
    url = ""
    for word in words:
        if word.startswith("http://") or word.startswith("https://"):
            url = word.strip()
            break
    if not url:
        url = text.strip()

    processing_msg = await update.message.reply_text("⏰┇يرجى الانتظار، يتم كشط وتحميل الصور من بينترست...")
    local_files = []
    try:
        local_files = await asyncio.to_thread(download_pinterest_with_ytdlp, url)
        if not local_files:
            await processing_msg.edit_text("❌ عذراً، لم أتمكن من تحميل المحتوى من بينترست. تأكد من صحة الرابط.")
            return

        photos_media = []
        for path, m_type in local_files:
            if m_type == "video":
                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VIDEO)
                with path.open("rb") as f:
                    await update.message.reply_video(video=f, caption="- @G66Gbot")
            elif m_type == "photo":
                photos_media.append(path)

        if photos_media:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO)
            total_photos = len(photos_media)
            
            # إرسال الصور على دفعات (كل 10 صور كحد أقصى في الألبوم الواحد حسب سياسة تيليجرام)
            for i in range(0, total_photos, 10):
                batch = photos_media[i:i + 10]
                media_group = []
                file_objects = []
                try:
                    for idx, path_p in enumerate(batch):
                        abs_index = i + idx + 1
                        f_img = path_p.open("rb")
                        file_objects.append(f_img)
                        
                        caption_str = "- @G66Gbot" if (abs_index == 1 and total_photos > 1) else None
                        media_group.append(InputMediaPhoto(media=f_img, caption=caption_str))

                    if media_group:
                        await update.message.reply_media_group(media=media_group)
                finally:
                    for f_obj in file_objects:
                        try:
                            f_obj.close()
                        except Exception:
                            pass

        await processing_msg.delete()
        return
    except Exception as e:
        logger.exception("Error handling Pinterest scraping message")
        await processing_msg.edit_text(f"❌ حدث خطأ: {str(e)}")
        return
    finally:
        for path, _ in local_files:
            if path and path.exists():
                path.unlink(missing_ok=True)
