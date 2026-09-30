import asyncio
import logging
import re
from pathlib import Path
import shutil
import tempfile
import yt_dlp
from urllib.parse import urlparse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import filters, ContextTypes
from telegram.constants import ChatAction

logger = logging.getLogger(__name__)

THREADS_MAX_SIZE = 49 * 1024 * 1024

class ThreadsDownloadError(Exception):
    pass

class ThreadsMediaTooLarge(ThreadsDownloadError):
    pass

def clean_threads_url(url: str) -> str:
    """استخراج كود المنشور بدقة تامة لضمان عمله 100 مع yt-dlp"""
    if not url:
        return url
    url = url.strip()
    
    # البحث عن أي معرف منشور يقع بعد /post/ أو /t/ أو /share/
    match = re.search(r'(?:/post/|/t/|/share/)([A-Za-z0-9_-]+)', url)
    if match:
        post_id = match.group(1)
        # إرجاع رابط نظيف يدعمه yt-dlp بشكل رسمي
        return f"https://www.threads.net/t/{post_id}"

    # حل احتياطي في حال لم يتطابق النمط
    url = url.replace("threads.com", "threads.net")
    return url

def is_valid_threads_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
        hostname = (parsed.hostname or "").lower().rstrip(".")
        return bool(hostname and ("threads.net" in hostname or "threads.com" in hostname))
    except Exception:
        return False

class ThreadsFilter(filters.MessageFilter):
    def filter(self, message):
        text = message.text or message.caption or ""
        return is_valid_threads_url(text)

THREADS_FILTER = ThreadsFilter()

def get_threads_info(url: str):
    # استخدام الرابط النظيف حصرياً لعملية الجلب
    clean_url = clean_threads_url(url)
    
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(clean_url, download=False)
        if not info:
            raise ValueError("Could not extract Threads information")
            
        return {
            "title": info.get("title") or info.get("description") or "منشور ثريدز",
            "url": clean_url,
        }

async def download_threads_media(url: str, mode: str = "video"):
    clean_url = clean_threads_url(url)
    output_dir = Path(tempfile.mkdtemp(prefix="threads_media_"))
    
    options = {
        "outtmpl": str(output_dir / "thread_%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "socket_timeout": 30,
    }

    if mode == "audio":
        options["format"] = "bestaudio/best"
        options["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    else:
        options["format"] = "best/bv*+ba/b"
        options["merge_output_format"] = "mp4"

    def _download():
        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.extract_info(clean_url, download=True)

    try:
        await asyncio.to_thread(_download)
    except Exception as error:
        logger.error("فشل تحميل ثريدز: %s", error)
        shutil.rmtree(output_dir, ignore_errors=True)
        raise ThreadsDownloadError("تعذر تحميل محتوى ثريدز") from error

    media_files = sorted(
        path for path in output_dir.iterdir()
        if path.is_file() and not path.name.endswith((".part", ".ytdl"))
        and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".jpg", ".jpeg", ".png", ".webp", ".mp3", ".m4a"}
    )

    if not media_files:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise ThreadsDownloadError("لم يتم العثور على وسائط في رابط ثريدز")

    checked_files = []
    for file_path in media_files:
        if file_path.stat().st_size > THREADS_MAX_SIZE:
            shutil.rmtree(output_dir, ignore_errors=True)
            raise ThreadsMediaTooLarge("حجم ملف ثريدز أكبر من المسموح به")
        checked_files.append(file_path)

    return output_dir, checked_files

async def handle_threads_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    url = message.text.strip()
    if not is_valid_threads_url(url):
        return

    user_id = update.effective_user.id
    processing_msg = await message.reply_text("⏳┇جاري قراءة معلومات منشور ثريدز...")

    try:
        # هنا نقوم بتنظيف الرابط فور استلامه وحفظ الرابط النظيف للاستخدام لاحقاً
        clean_url = clean_threads_url(url)
        info = await asyncio.to_thread(get_threads_info, clean_url)
        title = info["title"]

        keyboard = [
            [InlineKeyboardButton("🎬 فيديو", callback_data="th_video")],
            [InlineKeyboardButton("🎧 ملف صوتي", callback_data="th_audio")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        import html
        safe_title = html.escape(title)
        safe_url = html.escape(url)

        caption = f'🧵 <a href="{safe_url}">منشور ثريدز</a>\n\n📌 {safe_title[:200]}'

        sent_msg = await message.reply_text(
            text=caption,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )

        sessions = context.application.bot_data.setdefault("threads_sessions", {})
        key = (sent_msg.chat_id, sent_msg.message_id)
        # تخزين الرابط النظيف حصرياً في الجلسة لضمان نجاح التحميل
        sessions[key] = {"user_id": user_id, "url": clean_url, "title": title}

        await processing_msg.delete()

    except Exception as e:
        logger.exception("Error handling threads message: %s", e)
        await processing_msg.edit_text("❌ حدث خطأ أثناء قراءة رابط ثريدز، تأكد من صحته.")

async def handle_threads_callback(query, context, session_data, mode):
    chat_id = query.message.chat_id
    url = session_data["url"]

    try:
        await query.answer()
    except Exception:
        pass

    try:
        await query.message.delete()
    except Exception:
        pass

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text="♻️┇جاري تحميل محتوى ثريدز..."
    )

    output_dir = None

    try:
        output_dir, media_files = await download_threads_media(url, mode)

        for file_path in media_files:
            ext = file_path.suffix.lower()
            with open(file_path, "rb") as f:
                if ext in {".mp3", ".m4a"}:
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VOICE)
                    await context.bot.send_audio(
                        chat_id=chat_id,
                        audio=f,
                        title=session_data["title"][:200],
                        performer="@G66GBOT",
                        caption="- @G66GBOT",
                    )
                elif ext in {".jpg", ".jpeg", ".png", ".webp"}:
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                    await query.message.reply_photo(photo=f, caption="- @G66GBOT")
                else:
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=f,
                        caption="- @G66GBOT",
                        supports_streaming=True,
                    )

        await status_msg.delete()

    except ThreadsMediaTooLarge:
        await status_msg.edit_text("⚠️┇هذا الملف لا يمكنني تحميله،\n⚠️┇لأن حجمه يتجاوز ( 50 Mbps )،\n⚠️┇أعد المحاوله مع ملف اخر.")
    except Exception as e:
        logger.exception("Threads callback error: %s", e)
        await status_msg.edit_text("❌ حدث خطأ أثناء تحميل محتوى ثريدز.")
    finally:
        if output_dir and Path(output_dir).exists():
            shutil.rmtree(output_dir, ignore_errors=True)
