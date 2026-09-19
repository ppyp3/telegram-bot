import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse
import yt_dlp
from telegram.ext import filters

MAX_MEDIA_SIZE = 49 * 1024 * 1024

class DownloadTooLarge(Exception):
    pass

# فليتر للتعرف على روابط يوتيوب تلقائياً
YOUTUBE_FILTER = filters.Regex(r'https?://(www\.)?(youtube\.com|youtu\.be)/.+')

def is_valid_youtube_url(url):
    parsed = urlparse(url.strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme in ("http", "https") and (
        hostname in ("youtube.com", "youtu.be") or hostname.endswith(".youtube.com")
    )

def download_youtube(url, download_type="video"):
    """دالة تحميل مقاطع وصوتيات يوتيوب باستخدام yt-dlp"""
    temp_dir = tempfile.mkdtemp()
    out_tmpl = os.path.join(temp_dir, "%(id)s.%(ext)s")

    if download_type == "audio":
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": out_tmpl,
            "quiet": True,
            "no_warnings": True,
            "max_filesize": MAX_MEDIA_SIZE,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
        }
    else:
        ydl_opts = {
            "format": "best[filesize<=49M]/bestvideo[filesize<=30M]+bestaudio/best",
            "outtmpl": out_tmpl,
            "quiet": True,
            "no_warnings": True,
            "max_filesize": MAX_MEDIA_SIZE,
            "merge_output_format": "mp4",
        }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get("title", "فيديو يوتيوب")
        
        downloaded_files = list(Path(temp_dir).glob("*"))
        if not downloaded_files:
            raise FileNotFoundError("لم يتم العثور على الملف المحمل")

        filepath = downloaded_files[0]
        if filepath.stat().st_size > MAX_MEDIA_SIZE:
            filepath.unlink(missing_ok=True)
            raise DownloadTooLarge

        return filepath, title
