import asyncio
import logging
from pathlib import Path
import shutil
import tempfile
import yt_dlp
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

THREADS_MAX_SIZE = 49 * 1024 * 1024

class ThreadsDownloadError(Exception):
    pass

class ThreadsMediaTooLarge(ThreadsDownloadError):
    pass

def is_threads_url(url: str) -> bool:
    """التحقق الذاتي من أن الرابط يتبع لثريدز"""
    try:
        parsed = urlparse(url.strip())
        hostname = (parsed.hostname or "").lower().rstrip(".")
        return hostname in {"threads.net", "www.threads.net"} and len(parsed.path.split("/")) > 1
    except Exception:
        return False

async def handle_threads_download(url: str):
    """
    دالة شاملة ومستقلة خاصة بثريدز فقط:
    تقوم بالتحقق، التحميل، فحص الحجم، وإرجاع مجلد الحفظ وملفات الوسائط الجاهزة للإرسال.
    """
    if not is_threads_url(url):
        raise ThreadsDownloadError("رابط ثريدز غير صالح")

    output_dir = Path(tempfile.mkdtemp(prefix="threads_media_"))
    
    options = {
        "outtmpl": str(output_dir / "thread_%(id)s.%(ext)s"),
        "format": "bv*+ba/b",  # دمج الصوت والصورة لضمان عمل الصوت
        "merge_output_format": "mp4",
        "concurrent_fragment_downloads": 4,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "socket_timeout": 15,
    }

    def _download():
        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.extract_info(url, download=True)

    try:
        await asyncio.to_thread(_download)
    except yt_dlp.utils.DownloadError as error:
        logger.error("فشل تحميل ثريدز: %s", error)
        shutil.rmtree(output_dir, ignore_errors=True)
        raise ThreadsDownloadError("تعذر تحميل محتوى ثريدز") from error

    media_files = sorted(
        path for path in output_dir.iterdir()
        if path.is_file() and not path.name.endswith((".part", ".ytdl"))
        and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".jpg", ".jpeg", ".png"}
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
