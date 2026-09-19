import os
import re
import tempfile
from pathlib import Path
import yt_dlp

MAX_MEDIA_SIZE = 49 * 1024 * 1024

YOUTUBE_REGEX = re.compile(
    r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/(watch\?v=|shorts/|embed/)?([a-zA-Z0-9_-]+)'
)

YOUTUBE_FILTER = None

class DownloadTooLarge(Exception):
    pass

def is_valid_youtube_url(url: str) -> bool:
    if not url:
        return False
    return bool(YOUTUBE_REGEX.search(url.strip()))

def format_views(views):
    if not views:
        return "0"
    if views >= 1_000_000:
        return f"{views / 1_000_000:.1f}M"
    elif views >= 1_000:
        return f"{int(views / 1_000)}K"
    return str(views)

def get_youtube_info(url: str):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'nocheckcertificate': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'web'],
            }
        },
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        duration = info.get('duration', 0)
        minutes, seconds = divmod(duration, 60)
        
        return {
            "title": info.get('title', 'فيديو يوتيوب'),
            "uploader": info.get('uploader', 'غير معروف'),
            "duration_string": f"{minutes:02d}:{seconds:02d}",
            "view_count_formatted": format_views(info.get('view_count')),
            "thumbnail": info.get('thumbnail'),
        }

def download_youtube(url: str, mode: str = "video"):
    temp_dir = tempfile.mkdtemp()
    outtmpl = os.path.join(temp_dir, '%(title)s.%(ext)s')

    ydl_opts = {
        'outtmpl': outtmpl,
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': False,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'web', 'mweb', 'tv'],
                'player_skip': ['webpage', 'configs'],
            }
        },
    }

    if mode in ["audio", "voice"]:
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
            'format': 'bestvideo[max_filesize<=49M][ext=mp4]+bestaudio[ext=m4a]/best[max_filesize<=49M][ext=mp4]/best[max_filesize<=49M]/best',
        })

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get('title', 'فيديو يوتيوب')

        downloaded_files = list(Path(temp_dir).glob('*'))
        if not downloaded_files:
            raise FileNotFoundError("لم يتم العثور على الملف المحمل.")

        file_path = downloaded_files[0]

        if file_path.stat().st_size > MAX_MEDIA_SIZE:
            file_path.unlink(missing_ok=True)
            raise DownloadTooLarge("حجم الملف يتجاوز الحد المسموح.")

        return file_path, title
