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
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 300.0.0.0.0 (iPhone14,2; iOS 16_6; ar_SA; ar; Scale=3.00; 1170x2532)",
    "Referer": "https://www.instagram.com/",
}

INSTAGRAM_FILTER = filters.TEXT & filters.Regex(
    r"(?i)^https?://(?:www\.)?instagram\.com/(?:p|reel|reels)/"
)


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
            logger.error("%s is NOT installed; videos cannot be prepared", tool)
            continue
        try:
            result = subprocess.run(
                [executable, "-version"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            logger.error("%s is installed but failed to run", tool, exc_info=True)
            continue
        first_line = (result.stdout or result.stderr or "").splitlines()
        logger.info("%s available: %s", tool, first_line[0] if first_line else "unknown")


def _get_instagram_url_parts(url):
    parsed = urlparse(url.strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    parts = [part for part in parsed.path.split("/") if part]

    if (
        parsed.scheme not in {"http", "https"}
        or hostname not in {"instagram.com", "www.instagram.com"}
        or len(parts) < 2
        or parts[0] not in {"p", "reel", "reels"}
    ):
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


def get_direct_video_url(url):
    options = {
        "format": "best[ext=mp4]/best",
        "extractor_args": {
            "instagram": {
                "api_hostname": "www.instagram.com",
            }
        },
        "geo_bypass": True,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 15,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                direct_url = info.get("url")
                if direct_url:
                    return direct_url
                formats = info.get("formats", [])
                if formats:
                    best_f = max(formats, key=lambda f: f.get("filesize") or f.get("tbr") or 0)
                    return best_f.get("url")
    except Exception as e:
        logger.error("فشل استخراج الرابط المباشر: %s", e)
    return None


def media_caption(index, total, is_reel=False):
    if is_reel:
        return "- @G66GBOT"
    return f"- @G66GBOT - {index}/{total}"


async def handle_instagram_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    url = (update.message.text or "").strip()
    shortcode = get_shortcode(url)
    if not shortcode:
        return

    status_message = await update.message.reply_text("♻┇جاري التحميل...")

    try:
        # جلب الرابط المباشر ليقوم سيرفر تيليجرام بالتحميل والمعالجة بنفسه
        direct_video_url = await asyncio.to_thread(get_direct_video_url, url)
        
        if not direct_video_url:
            loader = instaloader.Instaloader(
                download_pictures=False,
                download_videos=False,
                save_metadata=False,
            )
            post = await asyncio.to_thread(instaloader.Post.from_shortcode, loader.context, shortcode)
            if post.is_video:
                direct_video_url = post.video_url

        if not direct_video_url:
            raise InstagramDownloadError("تعذر العثور على رابط الفيديو المباشر")

        is_reel = (get_url_kind(url) == "reel")
        caption = media_caption(1, 1, is_reel=is_reel)

        reply_markup = None
        if is_reel:
            keyboard = [
                [InlineKeyboardButton("🎵┇تحميل كملف صوتي", callback_data="audio")],
                [InlineKeyboardButton("📥┇تحميل باعلى دقه HD", callback_data="hd_video")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=ChatAction.UPLOAD_VIDEO,
        )

        # تيليجرام سيتولى عملية سحب الفيديو وعرضه ومعالجته بالكامل عبر الرابط المباشر
        sent_message = await update.message.reply_video(
            video=direct_video_url,
            caption=caption,
            supports_streaming=True,
            reply_markup=reply_markup
        )

        if is_reel and sent_message:
            user_id = update.effective_user.id
            sessions = context.application.bot_data.setdefault("download_sessions", {})
            sessions[(sent_message.chat_id, sent_message.message_id)] = {
                "user_id": user_id,
                "url": url,
                "title": "محتوى انستغرام",
                "created_at": asyncio.get_event_loop().time() if hasattr(asyncio, 'get_event_loop') else 0,
            }

        await status_message.delete()

    except (InstagramDownloadError, yt_dlp.utils.DownloadError, TelegramError):
        logger.exception("Instagram direct stream failed")
        await status_message.edit_text(
            "❌ تعذر تحميل هذا الرابط. تأكد أن الحساب والمنشور عام ثم أعد المحاولة."
        )
    except Exception:
        logger.exception("Unexpected Instagram handler error")
        await status_message.edit_text("❌ حدث خطأ أثناء معالجة الطلب.")


log_media_tools_status()
