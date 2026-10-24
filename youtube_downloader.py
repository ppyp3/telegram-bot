import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes, filters

# فلتر روابط اليوتيوب لحل مشكلة الاستيراد في bot.py
YOUTUBE_FILTER = filters.TEXT & filters.Regex(
    r"(?i)^(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+"
)

logger = logging.getLogger(__name__)

MAX_MEDIA_SIZE = 49 * 1024 * 1024
COOKIES_FILE = os.getenv("YOUTUBE_COOKIES_FILE", "cookies.txt")

# ضع المفتاح في Railway Variables إذا أردت استخدام YouTube Data API.
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY").strip()


def normalize_mode(mode: str) -> str:
    """وحّد أسماء أزرار التحميل القديمة والجديدة."""
    aliases = {
        "video": "video",
        "yt_video": "video",
        "audio": "audio",
        "yt_audio": "audio",
        "voice": "voice",
        "yt_voice": "voice",
    }
    normalized = aliases.get(str(mode).lower().strip())
    if not normalized:
        raise ValueError(f"Unknown YouTube mode: {mode}")
    return normalized


def is_youtube_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower()
        return host in {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "music.youtube.com",
            "youtu.be",
            "www.youtube-nocookie.com",
        }
    except Exception:
        return False


def base_ydl_options() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,
        "socket_timeout": 30,
        "ignoreerrors": False,
    }

    cookie_path = Path(COOKIES_FILE)
    if cookie_path.is_file():
        opts["cookiefile"] = str(cookie_path)

    return opts


def get_download_info(url: str) -> dict:
    """استخراج معلومات الفيديو بدون تنزيله."""
    if not is_youtube_url(url):
        raise ValueError("أرسل رابط YouTube صحيحاً.")

    opts = base_ydl_options()
    opts["skip_download"] = True

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        raise RuntimeError("لم أتمكن من الحصول على معلومات الفيديو.")

    return {
        "id": info.get("id", ""),
        "title": info.get("title") or "YouTube video",
        "uploader": info.get("uploader") or "Unknown",
        "duration": info.get("duration") or 0,
        "view_count": info.get("view_count") or 0,
        "thumbnail": info.get("thumbnail"),
        "webpage_url": info.get("webpage_url") or url,
    }


def download_youtube_media(url: str, mode: str, output_dir: str) -> str:
    """
    ينزّل ملفاً واحداً:
    video = فيديو MP4 قدر الإمكان
    audio = ملف MP3
    voice = ملف OGG/Opus مناسب للرسائل الصوتية
    """
    mode = normalize_mode(mode)

    if not is_youtube_url(url):
        raise ValueError("رابط YouTube غير صحيح.")

    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "FFmpeg غير مثبت على الاستضافة. ثبّته باستخدام Dockerfile."
        )

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    opts = base_ydl_options()
    opts.update({
        "outtmpl": str(output_path / "%(title).100B-%(id)s.%(ext)s"),
        "overwrites": True,
    })

    if mode == "video":
        opts.update({
            "format": (
                "bestvideo*+bestaudio/"
                "best[ext=mp4]/best"
            ),
            "merge_output_format": "mp4",
        })

    elif mode == "audio":
        opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })

    elif mode == "voice":
        opts.update({
            "format": "bestaudio/best",
        })

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    if not info:
        raise RuntimeError("فشل تنزيل الوسائط من YouTube.")

    video_id = info.get("id", "")
    candidates = [
        p for p in output_path.iterdir()
        if p.is_file() and video_id in p.name
    ]

    if mode == "audio":
        candidates = [
            p for p in candidates if p.suffix.lower() == ".mp3"
        ]

    elif mode == "video":
        candidates = [
            p for p in candidates
            if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
        ]

    elif mode == "voice":
        candidates = [
            p for p in candidates
            if p.suffix.lower() not in {".part", ".ytdl", ".json"}
        ]

    if not candidates:
        raise RuntimeError(
            "اكتمل طلب التنزيل لكن لم أعثر على الملف الناتج. "
            "راجع سجل Railway."
        )

    downloaded_file = max(candidates, key=lambda p: p.stat().st_size)

    if mode == "voice":
        voice_file = output_path / f"{video_id}-voice.ogg"
        command = [
            "ffmpeg", "-y", "-i", str(downloaded_file),
            "-vn", "-c:a", "libopus", "-b:a", "48k",
            "-vbr", "on", "-application", "voip",
            str(voice_file),
        ]

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
        )

        if result.returncode != 0 or not voice_file.is_file():
            logger.error("FFmpeg voice conversion failed: %s", result.stderr[-3000:])
            raise RuntimeError("فشل تحويل الملف إلى رسالة صوتية.")

        downloaded_file = voice_file

    if downloaded_file.stat().st_size > MAX_MEDIA_SIZE:
        raise RuntimeError(
            "حجم الملف أكبر من حد الإرسال المحدد (49 MB)."
        )

    return str(downloaded_file)


async def handle_youtube_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """يتعامل مع رسالة تحتوي على رابط YouTube."""
    message = update.effective_message
    if not message or not message.text:
        return

    words = message.text.split()
    url = next((word for word in words if is_youtube_url(word)), None)

    if not url:
        return

    await message.reply_text("⏳ أفحص رابط YouTube...")

    try:
        info = await asyncio.to_thread(get_download_info, url)

        duration = int(info.get("duration") or 0)
        minutes, seconds = divmod(duration, 60)

        caption = (
            f"🎬 {info['title']}\n"
            f"👤 القناة: {info['uploader']}\n"
            f"⏱️ المدة: {minutes}:{seconds:02d}\n\n"
            "اختَر نوع التحميل:"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🎥 فيديو",
                    callback_data=f"yt_video|{url}",
                ),
                InlineKeyboardButton(
                    "🎵 MP3",
                    callback_data=f"yt_audio|{url}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🎙️ رسالة صوتية",
                    callback_data=f"yt_voice|{url}",
                ),
            ],
        ])

        await message.reply_text(
            caption,
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )

    except Exception as exc:
        logger.exception("YouTube info extraction failed")
        await message.reply_text(
            f"❌ تعذّر قراءة الفيديو.\n"
            f"{str(exc)[:800]}"
        )


async def handle_youtube_callback(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    session_data=None,
    mode=None,
):
    """
    يدعم الاستدعاء المباشر:
    handle_youtube_callback(query, context, session_data, mode)

    ويدعم أيضاً زر callback_data بصيغة:
    yt_video|URL
    """
    await query.answer()

    try:
        if mode is None:
            data = query.data or ""
            parts = data.split("|", 1)
            mode = parts[0]
            url = parts[1] if len(parts) > 1 else ""
        else:
            data = query.data or ""
            parts = data.split("|", 1)
            url = parts[1] if len(parts) > 1 else ""

            if not url and isinstance(session_data, dict):
                url = (
                    session_data.get("url")
                    or session_data.get("youtube_url")
                    or ""
                )

        mode = normalize_mode(mode)

        if not url or not is_youtube_url(url):
            await query.edit_message_text(
                "❌ الرابط غير موجود أو غير صالح. أرسل الرابط مرة ثانية."
            )
            return

        await query.edit_message_text(
            "⏳ جارٍ تحميل الوسائط، انتظر..."
        )

        chat = query.message.chat
        bot = context.bot

        with tempfile.TemporaryDirectory(prefix="yt_download_") as temp_dir:
            file_path = await asyncio.to_thread(
                download_youtube_media,
                url,
                mode,
                temp_dir,
            )

            size = os.path.getsize(file_path)
            if size > MAX_MEDIA_SIZE:
                raise RuntimeError("الملف أكبر من الحد المسموح للإرسال.")

            if mode == "video":
                await bot.send_chat_action(
                    chat_id=chat.id,
                    action=ChatAction.UPLOAD_VIDEO,
                )
                with open(file_path, "rb") as media:
                    await bot.send_video(
                        chat_id=chat.id,
                        video=media,
                        caption=Path(file_path).stem[:900],
                        supports_streaming=True,
                        read_timeout=180,
                        write_timeout=180,
                        connect_timeout=30,
                        pool_timeout=30,
                    )

            elif mode == "audio":
                await bot.send_chat_action(
                    chat_id=chat.id,
                    action=ChatAction.UPLOAD_AUDIO,
                )
                with open(file_path, "rb") as media:
                    await bot.send_audio(
                        chat_id=chat.id,
                        audio=media,
                        title=Path(file_path).stem[:64],
                        read_timeout=180,
                        write_timeout=180,
                        connect_timeout=30,
                        pool_timeout=30,
                    )

            elif mode == "voice":
                await bot.send_chat_action(
                    chat_id=chat.id,
                    action=ChatAction.UPLOAD_VOICE,
                )
                with open(file_path, "rb") as media:
                    await bot.send_voice(
                        chat_id=chat.id,
                        voice=media,
                        read_timeout=180,
                        write_timeout=180,
                        connect_timeout=30,
                        pool_timeout=30,
                    )

        await query.message.reply_text("✅ تم إرسال الملف.")

    except Exception as exc:
        logger.exception("YouTube download/callback failed")
        error_text = str(exc).strip() or type(exc).__name__

        try:
            await query.message.reply_text(
                "❌ فشل تحميل الوسائط من YouTube.\n\n"
                f"{error_text[:1200]}"
            )
        except Exception:
            logger.exception("Could not send error message to Telegram")
 
