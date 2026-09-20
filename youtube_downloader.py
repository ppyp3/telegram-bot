import logging
import asyncio
import tempfile
from pathlib import Path
import yt_dlp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, filters
from telegram.constants import ChatAction

logger = logging.getLogger(__name__)

MAX_MEDIA_SIZE = 49 * 1024 * 1024  # حد تيليجرام 50 ميجابايت تقريباً

YOUTUBE_FILTER = filters.TEXT & ~filters.COMMAND & filters.Regex(r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/')

def is_valid_youtube_url(url: str) -> bool:
    if not url:
        return False
    u = url.strip()
    return "youtube.com" in u or "youtu.be" in u

def extract_youtube_info(url: str):
    """
    استخراج معلومات الفيديو باستخدام yt-dlp بدون تحميل الملف
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        # استخدام محاكي متصفح لتجنب حظر الـ IP من يوتيوب
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None
            
            title = info.get('title', 'فيديو يوتيوب')
            duration_sec = info.get('duration', 0)
            
            # تنسيق المدة الزمنية (دقائق:ثواني)
            if duration_sec:
                m, s = divmod(int(duration_sec), 60)
                h, m = divmod(m, 60)
                duration = f"{h:d}:{m:02d}:{s:02d}" if h > f"{m:02d}:{s:02d}" else f"{m:d}:{s:02d}"
            else:
                duration = "غير معروف"

            author = info.get('uploader', info.get('channel', 'يوتيوب'))
            thumbnail = info.get('thumbnail', '')
            
            return {
                "title": title,
                "duration": duration,
                "author": author,
                "thumbnail": thumbnail,
                "webpage_url": info.get('webpage_url', url)
            }
    except Exception:
        logger.exception("Error extracting YouTube info via yt-dlp")
        return None

def download_youtube_media(url: str, is_audio: bool = False):
    """
    تحميل الفيديو أو الصوت بصيغة تناسب تيليجرام
    """
    temp_dir = tempfile.mkdtemp()
    ydl_opts = {
        'outtmpl': f'{temp_dir}/%(id)s.%(ext)s',
        'noplaylist': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
    }

    if is_audio:
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
    else:
        # تحميل أفضل فيديو دقة مقبولة ضمن حدود الحجم المسموح
        ydl_opts.update({
            'format': 'best[filesize<49M]/bestvideo[filesize<40M]+bestaudio/best',
        })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            if is_audio:
                filename = str(Path(filename).with_suffix('.mp3'))
            
            path = Path(filename)
            if path.exists():
                return path
    except Exception:
        logger.exception("Error downloading YouTube media via yt-dlp")
    
    return None

async def handle_youtube_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    url = message.text.strip()
    if not is_valid_youtube_url(url):
        return

    processing_msg = await message.reply_text("⏰┇جاري جلب معلومات الفيديو من يوتيوب...")

    try:
        yt_data = await asyncio.to_thread(extract_youtube_info, url)
        if not yt_data:
            await processing_msg.edit_text("❌ عذراً، لم نتمكن من جلب معلومات الفيديو. تأكد أن الرابط صحيح وعام.")
            return

        title = yt_data["title"]
        duration = yt_data["duration"]
        author = yt_data["author"]
        thumbnail = yt_data["thumbnail"]
        webpage_url = yt_data["webpage_url"]

        chat_id = message.chat_id
        yt_sessions = context.application.bot_data.setdefault("yt_sessions", {})
        
        keyboard = [
            [InlineKeyboardButton("📥 تحميل الفيديو (MP4)", callback_data="yt_video")],
            [InlineKeyboardButton("🎵 تحميل كملف صوتي (MP3)", callback_data="yt_audio")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        caption = (
            f"🎬 **يوتيوب**\n"
            f"👤 **القناة:** {author}\n"
            f"⏳ **المدة:** {duration}\n\n"
            f"📌 **العنوان:** {title}\n"
            f"- @G66Gbot"
        )

        sent_msg = None
        if thumbnail:
            sent_msg = await message.reply_photo(photo=thumbnail, caption=caption, reply_markup=reply_markup)
        else:
            sent_msg = await message.reply_text(caption, reply_markup=reply_markup)

        # حفظ الرابط في الجلسة للضغطات لاحقاً
        session_key = (chat_id, sent_msg.message_id)
        yt_sessions[session_key] = {
            "url": webpage_url,
            "title": title
        }

        await processing_msg.delete()

    except Exception:
        logger.exception("Error in handle_youtube_message")
        await processing_msg.edit_text("⚠️ حدث خطأ أثناء معالجة الرابط، حاول مرة أخرى لاحقاً.")

async def handle_youtube_callback(query, context, session, action):
    url = session.get("url")
    title = session.get("title", "youtube_media")

    if not url:
        await query.message.reply_text("❌ انتهت صلاحية الجلسة، أرسل الرابط من جديد.")
        return

    status_msg = await query.message.reply_text("🔄 جاري التحميل والإرسال، يرجى الانتظار...")

    file_path = None
    try:
        if action == "yt_video":
            file_path = await asyncio.to_thread(download_youtube_media, url, False)
            if not file_path or not file_path.exists():
                raise ValueError("Failed to download video")

            await context.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.UPLOAD_VIDEO)
            with file_path.open("rb") as f:
                await query.message.reply_video(video=f, caption="- @G66Gbot")

        elif action == "yt_audio":
            file_path = await asyncio.to_thread(download_youtube_media, url, True)
            if not file_path or not file_path.exists():
                raise ValueError("Failed to download audio")

            await context.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.UPLOAD_AUDIO)
            with file_path.open("rb") as f:
                await query.message.reply_audio(audio=f, title=title, performer="@G66Gbot", caption="- @G66Gbot")

        await status_msg.delete()
    except Exception:
        logger.exception("Error in YouTube callback execution")
        await status_msg.edit_text("⚠️ حدث خطأ أو أن حجم الفيديو يتجاوز الحد المسموح به (50 ميجابايت).")
    finally:
        if file_path and file_path.exists():
            try:
                file_path.unlink()
                file_path.parent.rmdir()  # حذف المجلد المؤقت
            except Exception:
                pass
