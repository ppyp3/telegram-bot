import asyncio
import logging
import os
import random
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
import yt_dlp
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
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
from pinterest_downloader import is_valid_pinterest_url, handle_pinterest_message

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
        hostname == "tiktok.com" or hostname.endswith(".tiktok.com") or hostname in {"vm.tiktok.com", "vt.tiktok.com"}
    )

def request_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
    }

def fetch_tiktok_data(url):
    """دالة آمنة لمعالجة روابط تيك توك وتجنب أخطاء روابط الصور"""
    if "/photo/" in url or "photo" in url:
        try:
            headers = request_headers()
            with requests.get(
                "https://tikwm.com/api/",
                params={"url": url, "music": 1},
                headers=headers,
                timeout=(8, 20),
            ) as response:
                if response.status_code == 200:
                    alt_resp = response.json()
                    if alt_resp.get("code") == 0:
                        data = alt_resp.get("data", {})
                        images = data.get("images", [])
                        if images:
                            return {
                                "title": data.get("title", "محتوى تيك توك"),
                                "author": data.get("author", {}).get("nickname", "مستخدم تيك توك"),
                                "music": data.get("music"),
                                "images": images,
                                "play": None,
                            }
        except Exception:
            logger.exception("Error fetching TikTok photo via alternative API")

    if "/photo/" in url:
        return None

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'nocheckcertificate': True,
        'geo_bypass': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None
            
            return {
                "title": info.get('title') or "محتوى تيك توك",
                "author": info.get('uploader') or "مستخدم تيك توك",
                "music": info.get('url'),
                "images": [],
                "play": info.get('url') or info.get('webpage_url'),
            }
    except Exception:
        logger.exception("Error fetching TikTok data via yt-dlp")
        return None

def download_media(url, suffix):
    temp_dir = tempfile.mkdtemp()
    ydl_opts = {
        'outtmpl': os.path.join(temp_dir, '%(id)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'geo_bypass': True,
    }
    
    if suffix == ".mp3":
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
    else:
        ydl_opts.update({
            'format': 'best/bestvideo+bestaudio/best',
        })
        
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
            media_files = [p for p in Path(temp_dir).glob('*') if p.suffix.lower() in ['.mp4', '.webm', '.m4a', '.mp3', '.ogg']]
            if not media_files:
                raise FileNotFoundError("لم يتم العثور على الملف المحمل.")
            
            file_path = media_files[0]
            if file_path.stat().st_size > MAX_MEDIA_SIZE:
                file_path.unlink(missing_ok=True)
                raise DownloadTooLarge
            
            return file_path
    except Exception:
        if temp_dir and os.path.exists(temp_dir):
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
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

    url = text.strip()

    if is_valid_pinterest_url(url):
        await handle_pinterest_message(update, context)
        return

    if not is_valid_tiktok_url(url):
        await update.message.reply_text("❌ أرسل رابط تيك توك أو بينترست صحيحاً من فضلك.")
        return

    processing_msg = await update.message.reply_text(
        "⏰┇يرجى الانتظار، يتم قياس حجم التحميل..."
    )

    try:
        keyboard = [
            [InlineKeyboardButton("🎵┇تحميل كملف صوتي", callback_data="audio")],
            [InlineKeyboardButton("📥┇تحميل باعلى دقه HD", callback_data="hd_video")],
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
                    download_media, url, ".mp4"
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

    except DownloadTooLarge:
        await processing_msg.edit_text(
            "⚠️┇هذا الملف لا يمكنني تحميله،\n"
            "⚠️┇لأن حجمه يتجاوز ( 50 MB )،\n"
            "⚠️┇أعد المحاوله مع ملف اخر."
        )
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

        status_msg = await query.message.reply_text("♻️┇جاري التحميل...")
        local_audio_path = None

        try:
            local_audio_path = await asyncio.to_thread(
                download_media, url, ".mp3"
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

        status_msg = await query.message.reply_text("♻️┇جاري التحميل...")
        local_video_path = None

        try:
            audio_only_keyboard = [
                [InlineKeyboardButton("🎵 تحميل كملف صوتي.", callback_data="audio")]
            ]

            audio_reply_markup = InlineKeyboardMarkup(audio_only_keyboard)

            local_video_path = await asyncio.to_thread(
                download_media, url, ".mp4"
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
            sessions.pop(session_key, None)

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
 
