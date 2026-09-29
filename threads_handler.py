import asyncio
import logging
from pathlib import Path
import shutil
import tempfile
import yt_dlp
from urllib.parse import urlparse
from telegram import Update
from telegram.ext import filters, ContextTypes

logger = logging.getLogger(__name__)

THREADS_MAX_SIZE = 49 * 1024 * 1024

class ThreadsDownloadError(Exception):
    pass

class ThreadsMediaTooLarge(ThreadsDownloadError):
    pass

def is_threads_url(url: str) -> bool:
    """التحقق الذاتي من أن الرابط يتبع لثريدز بشكل مرن ودقيق"""
    try:
        parsed = urlparse(url.strip())
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if hostname not in {"threads.net", "www.threads.net"}:
            return False
        # التأكد من أن الرابط يحتوي على مسار (مثل منشور أو بروفایل)
        path_parts = [p for p in parsed.path.split("/") if p]
        return len(path_parts) > 0
    except Exception:
        return False

# فلتر تيليجرام لروابط ثريدز
THREADS_FILTER = filters.TEXT & ~filters.COMMAND & filters.Regex(r"(https?://)?(www\.)?threads\.net/.*")

async def download_threads_media(url: str):
    """
    دالة التحميل والبحث عن الوسائط عبر yt-dlp
    """
    output_dir = Path(tempfile.mkdtemp(prefix="threads_media_"))
    
    options = {
        "outtmpl": str(output_dir / "thread_%(id)s.%(ext)s"),
        "format": "bv*+ba/b/best",  
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "socket_timeout": 20,
    }

    def _download():
        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.extract_info(url, download=True)

    try:
        await asyncio.to_thread(_download)
    except Exception as error:
        logger.error("فشل تحميل ثريدز: %s", error)
        shutil.rmtree(output_dir, ignore_errors=True)
        raise ThreadsDownloadError("تعذر تحميل محتوى ثريدز") from error

    media_files = sorted(
        path for path in output_dir.iterdir()
        if path.is_file() and not path.name.endswith((".part", ".ytdl"))
        and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".jpg", ".jpeg", ".png", ".webp"}
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
    """
    معالج رسائل تيليجرام الخاص بثريدز ليتم استدعاؤه مباشرة من الملف الرئيسي
    """
    message = update.message
    if not message or not message.text:
        return

    url = message.text.strip()
    if not is_threads_url(url):
        return

    processing_msg = await message.reply_text("⏰┇جاري معالجة رابط ثريدز والتحميل...")
    output_dir = None

    try:
        output_dir, media_files = await download_threads_media(url)
        
        # إرسال الملفات حسب نوعها (صور أو فيديو)
        for file_path in media_files:
            ext = file_path.suffix.lower()
            with open(file_path, "rb") as f:
                if ext in {".jpg", ".jpeg", ".png", ".webp"}:
                    await message.reply_photo(photo=f, caption="- @G66GBOT")
                elif ext in {".mp4", ".mkv", ".webm"}:
                    await message.reply_video(video=f, caption="- @G66GBOT")

        await processing_msg.delete()

    except ThreadsMediaTooLarge:
        await processing_msg.edit_text("⚠️┇حجم الملف يتجاوز الحد المسموح به (50 ميجابايت).")
    except Exception as e:
        logger.exception("Error handling threads message: %s", e)
        await processing_msg.edit_text("⚠️┇حدث خطأ أثناء تحميل محتوى ثريدز، تأكد من صحة الرابط.")
    finally:
        if output_dir and Path(output_dir).exists():
            shutil.rmtree(output_dir, ignore_errors=True)
