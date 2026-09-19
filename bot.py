import asyncio
import logging
import os
import random
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
import yt_dlp
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from instagram_public_downloader import INSTAGRAM_FILTER, handle_instagram_message
from youtube_downloader import YOUTUBE_FILTER, handle_youtube_message, handle_youtube_callback

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TOKEN")
ADMIN_IDS = [5782729939]
MAX_MEDIA_SIZE = 49 * 1024 * 1024
SESSION_TTL_SECONDS = 20 * 60

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
]

class DownloadTooLarge(Exception):
    pass

def is_valid_tiktok_url(url):
    parsed = urlparse(url.strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme == "https" and (
        hostname == "tiktok.com" or hostname.endswith(".tiktok.com")
    )

def is_valid_pinterest_url(url):
    parsed = urlparse(url.strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    return "pinterest." in hostname or hostname == "pin.it"

def request_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
    }

def fetch_tiktok_data(url):
    try:
        headers = request_headers()
        parsed_url = urlparse(url)

        if parsed_url.hostname in {"vm.tiktok.com", "vt.tiktok.com"}:
            with requests.get(
                url, allow_redirects=True, timeout=(8, 20), headers=headers
            ) as response:
                response.raise_for_status()
                url = response.url

        if not is_valid_tiktok_url(url):
            return None

        with requests.get(
            "https://tikwm.com/api/",
            params={"url": url, "music": 1},
            headers=headers,
            timeout=(8, 20),
        ) as response:
            response.raise_for_status()
            alt_resp = response.json()

        if alt_resp.get("code") != 0:
            return None

        data = alt_resp.get("data")
        if not isinstance(data, dict):
            return None

        title = str(data.get("title") or "محتوى تيك توك")
        clean_title = "".join(
            character
            for character in title
            if character.isalnum() or character in (" ", "_", "-", "🔥")
        ).strip()

        if not clean_title:
            clean_title = "tiktok_audio"

        author = data.get("author")
        if not isinstance(author, dict):
            author = {}

        images = data.get("images")
        if not isinstance(images, list):
            images = []

        return {
            "title": title,
            "author": author.get("nickname", "مستخدم تيك توك"),
            "music": data.get("music"),
            "audio_title": f"{clean_title}.mp3",
            "images": images,
            "play": data.get("play"),
        }

    except (requests.RequestException, ValueError, TypeError):
        logger.exception("Error fetching TikTok data")
        return None

def download_pinterest_with_ytdlp(url):
    """استخدام yt-dlp لجلب كافة الفيديوهات والصور المتعددة من بينترست"""
    temp_dir = tempfile.mkdtemp()
    ydl_opts = {
        'outtmpl': os.path.join(temp_dir, '%(id)s_%(autonumber)s.%(ext)s'),
        'format': 'best',
        'noplaylist': False,  # السماح بجلب القوائم أو العناصر المتعددة إن وجدت
    }
    files = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if 'entries' in info:
                for entry in info['entries']:
                    if entry:
                        filename = ydl.prepare_filename(entry)
                        if os.path.exists(filename):
                            ext = entry.get('ext', '')
                            m_type = "video" if ext in ['mp4', 'mkv', 'webm', 'mov'] else "photo"
                            files.append((Path(filename), m_type))
            else:
                filename = ydl.prepare_filename(info)
                if os.path.exists(filename):
                    ext = info.get('ext', '')
                    m_type = "video" if ext in ['mp4', 'mkv', 'webm', 'mov'] else "photo"
                    files.append((Path(filename), m_type))
    except Exception:
        logger.exception("yt-dlp failed for Pinterest, falling back to multi-scraper")

    # نظام بديل لجلب عدة صور في حال كان المنشور يضم أكثر من صورة عبر BeautifulSoup
    if not files:
        try:
            headers = request_headers()
            target_url = url
            if "pin.it" in url:
                with requests.get(url, allow_redirects=True, timeout=(10, 25), headers=headers) as resp:
                    resp.raise_for_status()
                    target_url = resp.url

            with requests.get(target_url, headers=headers, timeout=(10, 25)) as resp:
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, 'html.parser')

            # جمع كافة روابط الصور المرتبطة بـ pinimg
            image_urls = set()
            for tag in soup.find_all("meta", property="og:image") + soup.find_all("meta", attrs={"name": "og:image"}):
                img_url = tag.get("content")
                if img_url and "pinimg.com" in img_url:
                    image_urls.add(img_url)

            # البحث عن صور إضافية داخل الصفحة إن وجدت
            for img in soup.find_all("img"):
                src = img.get("src")
                if src and "pinimg.com" in src and ("/originals/" in src or "/736x/" in src):
                    image_urls.add(src)

            for img_url in list(image_urls)[:10]:  # حد أقصى 10 صور للحزمة الواحدة
                img_path = download_media(img_url, ".jpg")
                if img_path:
                    files.append((img_path, "photo"))

        except Exception:
            logger.exception("Fallback multi-scraper also failed")

    return files

def download_media(url, suffix):
    temporary_path = None
    headers = request_headers()
    
    if "pinterest" in url or "pinimg" in url:
        headers["Referer"] = "https://www.pinterest.com/"

    try:
        with requests.get(
            url, headers=headers, timeout=(8, 30), stream=True
        ) as response:
            response.raise_for_status()

            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > MAX_MEDIA_SIZE:
                        raise DownloadTooLarge
                except ValueError:
                    pass

            with tempfile.NamedTemporaryFile(
                delete=False, suffix=suffix
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                downloaded = 0

                for chunk in response.iter_content(chunk_size=128 * 1024):
                    if not chunk:
                        continue

                    downloaded += len(chunk)

                    if downloaded > MAX_MEDIA_SIZE:
                        raise DownloadTooLarge

                    temporary_file.write(chunk)

        return temporary_path

    except Exception:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)
        raise

def remember_session(context, message, user_id, url, title):
    sessions = context.application.bot_data.setdefault("download_sessions", {})
    now = time.monotonic()

    expired = [
        key
        for key, session in sessions.items()
        if now - session["created_at"] > SESSION_TTL_SECONDS
    ]

    for key in expired:
        sessions.pop(key, None)

    key = (message.chat_id, message.message_id)

    sessions[key] = {
        "user_id": user_id,
        "url": url,
        "title": title,
        "created_at": now,
    }

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name

    welcome_msg = (
        f"✦ أهلاً بك ⦗ {user_name} ⦘ 🖤\n\n"
        f"▫︎ بوت التحميل السريع 📥\n"
        f"▫︎ يوتيوب • تيك توك • إنستغرام • بينترست\n\n"
        f"⚡ أرسل الرابط الآن للبدء 🔻"
    )

    await update.message.reply_text(welcome_msg)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ عذراً، هذا الأمر مخصص للمشرفين فقط.")
        return

    keyboard = [
        [KeyboardButton("📊 عدد المشتركين"), KeyboardButton("📢 بدء إذاعة 🔊")],
        [KeyboardButton("🛑 إيقاف الإذاعة 🔊"), KeyboardButton("🗑️ حذف جميع الإذاعات 🔊")],
        [KeyboardButton("-------------------------------------")],
        [KeyboardButton("🚪 إخفاء لوحة التحكم")],
    ]

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "👑 **مرحباً بك في لوحة تحكم البوت:**",
        reply_markup=reply_markup,
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text if update.message and update.message.text else ""

    if user_id in ADMIN_IDS:
        if text == "🚪 إخفاء لوحة التحكم":
            await update.message.reply_text(
                "🚪 تم إخفاء لوحة التحكم. لإظهارها أرسل /admin",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        elif (
            text.startswith("📊")
            or text.startswith("📢")
            or text.startswith("🛑")
            or text.startswith("🗑️")
            or "-------------------------------------" in text
        ):
            await update.message.reply_text(f"⚙️ تم استقبال الأمر: {text}")
            return

    words = text.split()
    url = ""
    for word in words:
        if word.startswith("http://") or word.startswith("https://"):
            url = word.strip()
            break
    
    if not url:
        url = text.strip()

    print(f"📥 Extracted URL: {url}")

    if is_valid_pinterest_url(url):
        print("📌 Matched Pinterest URL pattern.")
        processing_msg = await update.message.reply_text("⏰┇يرجى الانتظار، يتم تحميل المحتوى المتعدد من بينترست...")
        local_files = []
        try:
            local_files = await asyncio.to_thread(download_pinterest_with_ytdlp, url)
            if not local_files:
                await processing_msg.edit_text("❌ عذراً، لم أتمكن من تحميل المحتوى من بينترست. تأكد من صحة الرابط.")
                return

            # تقسيم الملفات إلى مجموعات (Media Group) للصور إذا كانت متعددة، أو إرسالها بشكل فردي منظم
            photos_media = []
            for path, m_type in local_files:
                if m_type == "video":
                    # إذا وُجد فيديو، يتم إرساله مباشرة مع الإجراء المناسب
                    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VIDEO)
                    with path.open("rb") as f:
                        await update.message.reply_video(video=f, caption="- @G66Gbot")
                elif m_type == "photo":
                    photos_media.append(path)

            if photos_media:
                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO)
                total_photos = len(photos_media)
                
                # إرسال الصور دفعة واحدة على شكل مجموعات ميديا (Media Group) إذا كانت أكثر من صورة
                for i in range(0, total_photos, 10):
                    batch = photos_media[i:i + 10]
                    media_group = []
                    
                    for idx, path_p in enumerate(batch):
                        abs_index = i + idx + 1
                        with path_p.open("rb") as f_img:
                            # حفظ البيانات مؤقتاً أو استخدام الروابط / الملفات المفتوحة
                            pass
                    
                    # طريقة إرسال الألبوم البرمجي الصحيحة لملفات محلية
                    media_group = []
                    file_objects = []
                    try:
                        for idx, path_p in enumerate(batch):
                            abs_index = i + idx + 1
                            f_img = path_p.open("rb")
                            file_objects.append(f_img)
                            
                            caption_str = f"- @G66Gbot - {abs_index}/{total_photos}" if abs_index == total_photos and i + len(batch) == total_photos else None
                            if abs_index == 1 and total_photos > 1:
                                caption_str = "- @G66Gbot"

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
            logger.exception("Error handling Pinterest multi-message")
            await processing_msg.edit_text(f"❌ حدث خطأ: {str(e)}")
            return
        finally:
            for path, _ in local_files:
                if path and path.exists():
                    path.unlink(missing_ok=True)
                    try:
                        path.parent.rmdir()
                    except Exception:
                        pass

    if not is_valid_tiktok_url(url):
        print(f"❌ Rejected URL: {url}")
        await update.message.reply_text("❌ أرسل رابط تيك توك أو بينترست صحيحاً من فضلك.")
        return

    print("🎵 Matched TikTok URL pattern.")
    processing_msg = await update.message.reply_text(
        "⏰┇يرجى الانتظار، يتم قياس حجم التحميل..."
    )

    try:
        keyboard = [
            [InlineKeyboardButton("🎵 تحميل كملف صوتي.", callback_data="audio")],
            [InlineKeyboardButton("📥 تحميل باعلى دقه HD.", callback_data="hd_video")],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        tiktok_data = await asyncio.to_thread(fetch_tiktok_data, url)

        if tiktok_data:
            title = tiktok_data["title"]
            images = tiktok_data["images"]
            video_url = tiktok_data["play"]
            audio_url = tiktok_data["music"]
            caption_text = "- @G66Gbot"

            if images:
                if audio_url:
                    local_audio_path = None

                    try:
                        local_audio_path = await asyncio.to_thread(
                            download_media, audio_url, ".mp3"
                        )

                        await context.bot.send_chat_action(
                            chat_id=update.effective_chat.id,
                            action=ChatAction.UPLOAD_VOICE,
                        )

                        with local_audio_path.open("rb") as audio_file:
                            await update.message.reply_audio(
                                audio=audio_file,
                                title=title,
                                performer="@G66Gbot",
                                caption="- @G66Gbot - 1/1",
                            )

                    except Exception:
                        logger.exception("Audio send error")

                    finally:
                        if local_audio_path:
                            local_audio_path.unlink(missing_ok=True)

                await context.bot.send_chat_action(
                    chat_id=update.effective_chat.id,
                    action=ChatAction.UPLOAD_PHOTO,
                )

                total_images = len(images)

                for i in range(0, total_images, 10):
                    batch = images[i:i + 10]
                    media_group = []

                    for idx, img_url in enumerate(batch):
                        absolute_index = i + idx + 1

                        if absolute_index == total_images:
                            media_group.append(
                                InputMediaPhoto(
                                    media=img_url,
                                    caption=f"- @G66Gbot - {absolute_index}/{total_images}",
                                )
                            )
                        else:
                            media_group.append(InputMediaPhoto(media=img_url))

                    if media_group:
                        await update.message.reply_media_group(media=media_group)

                await processing_msg.delete()
                return

            elif video_url:
                local_video_path = await asyncio.to_thread(
                    download_media, video_url, ".mp4"
                )

                try:
                    await context.bot.send_chat_action(
                        chat_id=update.effective_chat.id,
                        action=ChatAction.UPLOAD_VIDEO,
                    )

                    with local_video_path.open("rb") as video_file:
                        sent_video = await update.message.reply_video(
                            video=video_file,
                            caption=caption_text,
                            reply_markup=reply_markup,
                        )

                    remember_session(
                        context,
                        sent_video,
                        user_id,
                        url,
                        title,
                    )

                finally:
                    local_video_path.unlink(missing_ok=True)

                await processing_msg.delete()
                return

        error_custom_msg = (
            "⚠️┇هذا الملف لا يمكنني تحميله،\n"
            "⚠️┇لأن حجمه يتجاوز ( 50 Mbps )،\n"
            "⚠️┇أعد المحاوله مع ملف اخر."
        )

        await processing_msg.edit_text(error_custom_msg)

    except Exception:
        logger.exception("Error in handle_message")

        error_custom_msg = (
            "⚠️┇هذا الملف لا يمكنني تحميله،\n"
            "⚠️┇لأن حجمه يتجاوز ( 50 Mbps )،\n"
            "⚠️┇أعد المحاوله مع ملف اخر."
        )

        await processing_msg.edit_text(error_custom_msg)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not query or not query.message:
        return

    await query.answer()

    if query.data in ["yt_video", "yt_audio", "yt_voice"]:
        chat_id = query.message.chat_id
        yt_sessions = context.application.bot_data.get("yt_sessions", {})
        session_key = (chat_id, query.message.message_id)
        session = yt_sessions.get(session_key)

        if not session:
            await query.message.reply_text("❌ انتهت صلاحية الجلسة، أرسل الرابط مرة أخرى.")
            return

        await handle_youtube_callback(query, context, session, query.data)
        return

    chat_id = query.message.chat_id
    sessions = context.application.bot_data.setdefault("download_sessions", {})
    session_key = (chat_id, query.message.message_id)
    session = sessions.get(session_key)

    if not session or time.monotonic() - session["created_at"] > SESSION_TTL_SECONDS:
        sessions.pop(session_key, None)
        await query.message.reply_text(
            "❌ انتهت صلاحية الجلسة، أرسل الرابط مرة أخرى."
        )
        return

    if query.from_user.id != session["user_id"]:
        await query.message.reply_text(
            "❌ انتهت صلاحية الجلسة، أرسل الرابط مرة أخرى."
        )
        return

    url = session["url"]
    video_title = session["title"]

    if query.data == "audio":
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except TelegramError:
            logger.exception("Could not remove audio button")

        status_msg = await query.message.reply_text("🔄 جاري تحميل الملف الصوتي...")
        local_audio_path = None

        try:
            tiktok_data = await asyncio.to_thread(fetch_tiktok_data, url)
            audio_link = tiktok_data.get("music") if tiktok_data else None

            if not audio_link:
                raise ValueError("Audio link is unavailable")

            local_audio_path = await asyncio.to_thread(
                download_media, audio_link, ".mp3"
            )

            await context.bot.send_chat_action(
                chat_id=chat_id, action=ChatAction.UPLOAD_VOICE
            )

            with local_audio_path.open("rb") as audio_file:
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=audio_file,
                    title=video_title,
                    performer="@G66Gbot",
                    caption="- @G66Gbot",
                )

            await status_msg.delete()

        except Exception:
            logger.exception("Audio callback error")
            await status_msg.edit_text("❌ حدث خطأ أثناء تحميل الملف الصوتي.")

        finally:
            if local_audio_path:
                local_audio_path.unlink(missing_ok=True)
            sessions.pop(session_key, None)

    elif query.data == "hd_video":
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except TelegramError:
            logger.exception("Could not remove video button")

        status_msg = await query.message.reply_text("🔄 جاري إرسال الفيديو...")
        local_video_path = None

        try:
            tiktok_data = await asyncio.to_thread(fetch_tiktok_data, url)
            video_url = tiktok_data.get("play") if tiktok_data else None

            if not video_url:
                raise ValueError("Video link is unavailable")

            audio_only_keyboard = [
                [InlineKeyboardButton("🎵 تحميل كملف صوتي.", callback_data="audio")]
            ]

            audio_reply_markup = InlineKeyboardMarkup(audio_only_keyboard)

            local_video_path = await asyncio.to_thread(
                download_media, video_url, ".mp4"
            )

            await context.bot.send_chat_action(
                chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO
            )

            with local_video_path.open("rb") as video_file:
                sent_video = await context.bot.send_video(
                    chat_id=chat_id,
                    video=video_file,
                    caption="- @G66Gbot",
                    reply_markup=audio_reply_markup,
                )

            remember_session(
                context,
                sent_video,
                query.from_user.id,
                url,
                video_title,
            )

            await status_msg.delete()

        except Exception:
            logger.exception("HD video callback error")
            error_custom_msg = (
                "⚠️┇هذا الملف لا يمكنني تحميله،\n"
                "⚠️┇لأن حجمه يتجاوز ( 50 Mbps )،\n"
                "⚠️┇أعد المحاوله مع ملف اخر."
            )
            await status_msg.edit_text(error_custom_msg)

        finally:
            if local_video_path:
                local_video_path.unlink(missing_ok=True)
            sessions.pop(session_key, )

def main():
    if not TOKEN:
        raise RuntimeError("TOKEN environment variable is not set.")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))

    app.add_handler(MessageHandler(INSTAGRAM_FILTER, handle_instagram_message))
    app.add_handler(MessageHandler(YOUTUBE_FILTER, handle_youtube_message))

    app.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    )

    app.add_handler(CallbackQueryHandler(button_callback))

    print("بوت التحميل يعمل الآن بكفاءة...")
    app.run_polling()

if __name__ == "__main__":
    main()
