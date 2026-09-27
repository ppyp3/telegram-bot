import asyncio
import json
import logging
import mimetypes
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import instaloader
import requests
import yt_dlp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo, Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import ContextTypes, filters


logger = logging.getLogger(__name__)
MAX_MEDIA_SIZE = 49 * 1024 * 1024
UNKNOWN_CODEC = "unknown"
MEDIA_ID_CACHE: dict[str, list[tuple[str, str]]] = {}
PROBE_VIDEO_CACHE = {}
VIDEO_THUMBNAIL_CACHE = {}
MAX_CACHE_ENTRIES = 500
DOWNLOAD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.instagram.com/",
}


def store_in_cache(cache, key, value):
    if key is None:
        return value
    cache[key] = value
    while len(cache) > MAX_CACHE_ENTRIES:
        cache.pop(next(iter(cache)))
    return value


class InstagramDownloadError(Exception):
    pass


class InstagramMediaTooLarge(InstagramDownloadError):
    pass


class VideoProcessingError(InstagramDownloadError):
    pass


def log_media_tools_status():
    for tool in ("ffmpeg", "ffprobe"):
        executable = shutil.which(tool)
        if executable is None:
            logger.error("%s is NOT installed", tool)
            continue
        try:
            subprocess.run([executable, "-version"], capture_output=True, text=True, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue


def _get_instagram_url_parts(url):
    parsed = urlparse(url.strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.scheme not in {"http", "https"} or hostname not in {"instagram.com", "www.instagram.com"} or len(parts) < 2 or parts[0] not in {"p", "reel", "reels"}:
        return None
    return parsed, parts


def get_shortcode(url):
    parsed_parts = _get_instagram_url_parts(url)
    if not parsed_parts:
        return None
    _, parts = parsed_parts
    return parts[1]


def get_url_kind(url):
    parsed_parts = _get_instagram_url_parts(url)
    if not parsed_parts:
        return None
    _, parts = parsed_parts
    return "reel" if parts[0] in {"reel", "reels"} else "post"


def download_file(url, output_path):
    response = requests.get(url, headers=DOWNLOAD_HEADERS, timeout=(10, 45), stream=True)
    try:
        response.raise_for_status()
        with output_path.open("wb") as output_file:
            for chunk in response.iter_content(chunk_size=128 * 1024):
                if chunk:
                    output_file.write(chunk)
    finally:
        response.close()


def probe_video(file_path):
    command = ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height:format=duration", "-of", "json", str(file_path)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        data = json.loads(result.stdout or "{}")
    except Exception:
        return UNKNOWN_CODEC, UNKNOWN_CODEC, None, None, None

    video_codec = audio_codec = width = height = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and video_codec is None:
            video_codec, width, height = stream.get("codec_name"), stream.get("width"), stream.get("height")
        elif stream.get("codec_type") == "audio" and audio_codec is None:
            audio_codec = stream.get("codec_name")
    
    try:
        duration = int(float(data.get("format", {}).get("duration", 0))) or None
    except Exception:
        duration = None
    return video_codec, audio_codec, width, height, duration


def is_video_file(file_path):
    mime_type, _ = mimetypes.guess_type(file_path.name)
    return bool(mime_type and mime_type.startswith("video/"))


def download_instagram_media_with_audio(url, output_dir):
    shortcode = get_shortcode(url)
    post_caption = ""
    audio_file_path = None

    # استخدام yt_dlp لسحب الوسائط والأغنية المرفقة إن وجدت
    options = {
        "outtmpl": str(output_dir / "media_%(id)s_%(autonumber)s.%(ext)s"),
        "format": "bestvideo+bestaudio/best/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 15,
    }

    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
            if info:
                post_caption = (info.get("description") or info.get("title") or "").strip()
    except Exception:
        pass

    # استخدام instaloader كبديل لاستخراج الصور والوصف بدقة إذا لم يقم yt_dlp بتحميلها كلها
    try:
        loader = instaloader.Instaloader(download_pictures=True, download_videos=True, download_video_thumbnails=False, save_metadata=False, compress_json=False)
        post = instaloader.Post.from_shortcode(loader.context, shortcode)
        if post.caption and not post_caption:
            post_caption = post.caption.strip()

        # إذا كان المنشور ألبوم صور (GraphSidecar)
        if post.typename == "GraphSidecar":
            for index, node in enumerate(post.get_sidecar_nodes(), start=1):
                media_url = node.video_url if node.is_video else node.display_url
                if media_url:
                    suffix = ".mp4" if node.is_video else ".jpg"
                    out_path = output_dir / f"sidecar_{index:03d}{suffix}"
                    if not out_path.exists():
                        download_file(media_url, out_path)
        else:
            media_url = post.video_url if post.is_video else post.url
            if media_url:
                suffix = ".mp4" if post.is_video else ".jpg"
                out_path = output_dir / f"single_001{suffix}"
                if not out_path.exists():
                    download_file(media_url, out_path)
    except Exception:
        pass

    # جمع الملفات وتنظيمها
    all_files = sorted([p for p in output_dir.iterdir() if p.is_file() and p.suffix.lower() in {".mp4", ".jpg", ".jpeg", ".png", ".webm", ".m4a", ".mp3"}] )
    
    media_files = []
    for path in all_files:
        # إذا كان الملف عبارة عن صوت أو يحتوي على مسار صوتي منفصل للأغنية
        _, a_codec, _, _, duration = probe_video(path)
        if path.suffix.lower() in {".m4a", ".mp3"} or (a_codec and not is_video_file(path) and duration and duration < 120):
            audio_file_path = path
        else:
            media_files.append(path)

    # إذا لم يُعثر على ملف صوتي منفصل، ولكن يوجد فيديو يحتوي على أغنية، نستخرج الصوت منه ليكون مثل تيك توك
    if not audio_file_path:
        for path in media_files:
            if is_video_file(path):
                v_codec, a_codec, _, _, duration = probe_video(path)
                if a_codec and a_codec != UNKNOWN_CODEC:
                    extracted_audio = output_dir / f"{path.stem}_audio.m4a"
                    cmd = ["ffmpeg", "-y", "-i", str(path), "-vn", "-acodec", "copy", str(extracted_audio)]
                    try:
                        subprocess.run(cmd, capture_output=True, timeout=30, check=True)
                        if extracted_audio.exists():
                            audio_file_path = extracted_audio
                            break
                    except Exception:
                        pass

    return media_files, audio_file_path, post_caption


async def handle_instagram_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    url = (update.message.text or "").strip()
    shortcode = get_shortcode(url)
    if not shortcode:
        return

    status_message = await update.message.reply_text("♻️┇جاري التحميل...")
    output_dir = Path(tempfile.mkdtemp(prefix="insta_"))

    try:
        media_files, audio_file_path, post_caption = await asyncio.to_thread(
            download_instagram_media_with_audio, url, output_dir
        )

        if not media_files:
            await status_message.edit_text("❌ لم يتم العثور على وسائط قابلة للتحميل.")
            return

        title_text = post_caption.split("\n")[0][:60] if post_caption else "محتوى انستغرام"
        bot_signature = "- @G66GBOT"

        # 1. إذا توفرت أغنية أو صوت للمنشور، يتم إرساله أولاً كملف صوتي بالبداية تماماً مثل تيك توك
        if audio_file_path and audio_file_path.exists():
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VOICE)
            with audio_file_path.open("rb") as audio_f:
                await update.message.reply_audio(
                    audio=audio_f,
                    title=title_text,
                    caption=f"{post_caption}\n\n{bot_signature}" if post_caption else bot_signature
                )
        
        # 2. إرسال الألبوم أو الصور بعدها بشكل طبيعي وبدون أزرار
        total = len(media_files)
        for start in range(0, total, 10):
            batch = media_files[start : start + 10]
            if len(batch) == 1:
                file_path = batch[0]
                caption = f"{post_caption}\n\n{bot_signature} - 1/1" if post_caption else f"{bot_signature} - 1/1"
                if is_video_file(file_path):
                    with file_path.open("rb") as vf:
                        await update.message.reply_video(video=vf, caption=caption, supports_streaming=True)
                else:
                    with file_path.open("rb") as pf:
                        await update.message.reply_photo(photo=pf, caption=caption)
            else:
                media_group = []
                open_files = []
                try:
                    for offset, file_path in enumerate(batch, start=1):
                        f_open = file_path.open("rb")
                        open_files.append(f_open)
                        abs_idx = start + offset
                        cap = f"{post_caption}\n\n{bot_signature} - {abs_idx}/{total}" if (abs_idx == total and post_caption) else None
                        
                        if is_video_file(file_path):
                            media_group.append(InputMediaVideo(media=f_open, caption=cap, supports_streaming=True))
                        else:
                            media_group.append(InputMediaPhoto(media=f_open, caption=cap))
                    
                    await update.message.reply_media_group(media=media_group)
                finally:
                    for f in open_files:
                        f.close()

        await status_message.delete()
    except Exception:
        logger.exception("Error handling instagram media with audio")
        await status_message.edit_text("❌ حدث خطأ أثناء تحميل المنشور.")
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)
 
