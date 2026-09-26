import asyncio
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

import requests
import yt_dlp

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import filters


logger = logging.getLogger(__name__)

# Telegram bot limit used by this bot
MAX_MEDIA_SIZE = 49 * 1024 * 1024

COOKIES_FILE = "cookies.txt"

YOUTUBE_REGEX = re.compile(
    r"https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtube\.com/shorts/|"
    r"youtube\.com/embed/|youtu\.be/)[A-Za-z0-9_-]+",
    re.IGNORECASE,
)


class DownloadTooLarge(Exception):
    pass


class YoutubeFilter(filters.MessageFilter):
    def filter(self, message):
        text = message.text or message.caption or ""
        return bool(YOUTUBE_REGEX.search(text))


YOUTUBE_FILTER = YoutubeFilter()


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def extract_youtube_url(text: str):
    if not text:
        return None

    match = YOUTUBE_REGEX.search(text)

    if not match:
        return None

    return match.group(0)


def format_views(views):
    if not views:
        return "0"

    try:
        views = int(views)
    except (ValueError, TypeError):
        return "0"

    if views >= 1_000_000:
        return f"{views / 1_000_000:.1f}M"

    if views >= 1_000:
        return f"{views / 1_000:.1f}K"

    return str(views)


def format_duration(seconds):
    if not seconds:
        return "00:00"

    try:
        seconds = int(seconds)
    except (ValueError, TypeError):
        return "00:00"

    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    return f"{minutes:02d}:{seconds:02d}"


def safe_filename(name):
    if not name:
        name = "youtube"

    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", name)
    name = name.strip(". ")

    if not name:
        name = "youtube"

    return name[:150]


def get_common_ydl_opts():
    opts = {
        "quiet": True,
        "no_warnings": False,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "file_access_retries": 3,
        "concurrent_fragment_downloads": 4,
        "noprogress": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["web_embedded", "web", "-tv_downgraded"]
            }
        },
    }

    if os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE

    return opts


# ---------------------------------------------------------
# YouTube information
# ---------------------------------------------------------

def get_youtube_info(url: str):
    ydl_opts = get_common_ydl_opts()
    ydl_opts.update({
        "skip_download": True,
        "extract_flat": False,
    })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            if not info:
                raise ValueError("yt-dlp returned empty information")

            return {
                "title": info.get("title") or "فيديو يوتيوب",
                "uploader": (
                    info.get("uploader")
                    or info.get("channel")
                    or "غير معروف"
                ),
                "duration": int(info.get("duration") or 0),
                "duration_string": format_duration(info.get("duration")),
                "view_count_formatted": format_views(
                    info.get("view_count")
                ),
                "thumbnail": info.get("thumbnail"),
                "url": url,
            }

    except Exception:
        logger.exception("YouTube information extraction failed")
        raise


# ---------------------------------------------------------
# Find downloadable format
# ---------------------------------------------------------

def get_download_info(url: str, mode: str):
    ydl_opts = get_common_ydl_opts()
    ydl_opts["skip_download"] = True

    if mode in ("audio", "yt_audio", "yt_voice"):
        ydl_opts["format"] = "bestaudio/best"
    else:
        ydl_opts["format"] = "best/bestvideo+bestaudio"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            if not info:
                raise ValueError("Could not extract YouTube information")

            return info

    except Exception:
        logger.exception("Failed to inspect YouTube media")
        raise


# ---------------------------------------------------------
# Size check
# ---------------------------------------------------------

def check_media_size_before_download(url: str, mode: str = "video"):
    try:
        info = get_download_info(url, mode)

        filesize = (
            info.get("filesize")
            or info.get("filesize_approx")
        )

        if filesize:
            return filesize <= MAX_MEDIA_SIZE

        formats = info.get("formats") or []
        candidates = []

        for fmt in formats:
            if mode in ("audio", "yt_audio", "yt_voice"):
                if fmt.get("acodec") not in (None, "none"):
                    size = fmt.get("filesize") or fmt.get("filesize_approx")
                    if size:
                        candidates.append(size)
            else:
                if fmt.get("vcodec") not in (None, "none"):
                    size = fmt.get("filesize") or fmt.get("filesize_approx")
                    if size:
                        candidates.append(size)

        if candidates:
            smallest = min(candidates)
            if smallest > MAX_MEDIA_SIZE:
                return False

        return True

    except Exception:
        logger.exception("Size check failed")
        return True


# ---------------------------------------------------------
# Download
# ---------------------------------------------------------

def download_youtube_media(url: str, mode: str = "video"):
    temp_dir = tempfile.mkdtemp(prefix="yt_")

    logger.info("Temporary directory: %s", temp_dir)

    try:
        outtmpl = os.path.join(
            temp_dir,
            "%(title).150s.%(ext)s"
        )

        ydl_opts = get_common_ydl_opts()

        ydl_opts.update({
            "outtmpl": outtmpl,
            "quiet": False,
            "no_warnings": False,
            "noprogress": False,
        })

        if mode == "video":
            ydl_opts["format"] = "best/bestvideo+bestaudio"
            ydl_opts["writethumbnail"] = False

        elif mode in ("audio", "yt_audio"):
            ydl_opts["format"] = "bestaudio/best"
            ydl_opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]
            ydl_opts["writethumbnail"] = True

        elif mode == "yt_voice":
            ydl_opts["format"] = "bestaudio/best"
            ydl_opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "opus",
                    "preferredquality": "128",
                }
            ]
            ydl_opts["writethumbnail"] = False

        else:
            raise ValueError(f"Unknown YouTube mode: {mode}")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

            if not info:
                raise ValueError("yt-dlp returned no information after download")

            title = info.get("title", "فيديو يوتيوب")
            duration = int(info.get("duration") or 0)

        allowed_media = {
            ".mp3",
            ".mp4",
            ".m4a",
            ".webm",
            ".ogg",
            ".opus",
            ".mkv",
        }

        media_files = [
            p
            for p in Path(temp_dir).glob("*")
            if p.is_file() and p.suffix.lower() in allowed_media
        ]

        if not media_files:
            raise FileNotFoundError("لم يتم العثور على الملف بعد التحميل.")

        file_path = max(
            media_files,
            key=lambda p: p.stat().st_size
        )

        file_size = file_path.stat().st_size

        if file_size > MAX_MEDIA_SIZE:
            raise DownloadTooLarge("حجم الملف أكبر من 49MB")

        thumb_path = None
        if mode == "yt_audio":
            thumbnails = [
                p
                for p in Path(temp_dir).glob("*")
                if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}
            ]
            if thumbnails:
                thumb_path = thumbnails[0]

        return file_path, title, duration, thumb_path, temp_dir

    except Exception:
        logger.exception("YouTube download failed for URL: %s", url)
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


# ---------------------------------------------------------
# Handle YouTube message
# ---------------------------------------------------------

async def handle_youtube_message(update, context):
    text = update.message.text or update.message.caption or ""
    url = extract_youtube_url(text)

    if not url:
        return

    user_id = update.effective_user.id
    processing_msg = await update.message.reply_text("⏳┇جاري قراءة معلومات الفيديو...")

    try:
        info = await asyncio.to_thread(get_youtube_info, url)

        keyboard = [
            [InlineKeyboardButton("🎬 فيديو", callback_data="yt_video")],
            [
                InlineKeyboardButton("🎧 ملف صوتي", callback_data="yt_audio"),
                InlineKeyboardButton("🎙 بصمة صوتية", callback_data="yt_voice"),
            ],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        title = info["title"]

        import html
        safe_title = html.escape(title)
        safe_uploader = html.escape(info["uploader"])
        safe_url = html.escape(info["url"])

        caption = (
            f'🎬 <a href="{safe_url}">{safe_title}</a>\n'
            f"👤 {safe_uploader}\n"
            f'⏱ {info["duration_string"]} - 👁 {info["view_count_formatted"]}'
        )

        sent_msg = None
        if info.get("thumbnail"):
            try:
                sent_msg = await update.message.reply_photo(
                    photo=info["thumbnail"],
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
            except Exception:
                logger.exception("Failed to send YouTube thumbnail")

        if sent_msg is None:
            sent_msg = await update.message.reply_text(
                text=caption,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )

        sessions = context.application.bot_data.setdefault("yt_sessions", {})
        key = (sent_msg.chat_id, sent_msg.message_id)
        sessions[key] = {"user_id": user_id, "url": url, "title": title}

        await processing_msg.delete()

    except Exception as e:
        logger.exception("Error handling YouTube message")
        await processing_msg.edit_text(f"❌ حدث خطأ أثناء معالجة الرابط.\n\nالخطأ: {str(e)[:500]}")


# ---------------------------------------------------------
# Callback
# ---------------------------------------------------------

async def handle_youtube_callback(query, context, session_data, mode):
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
        text="♻️┇جاري تحميل الملف..."
    )

    file_path = None
    thumb_path = None
    temp_dir = None

    try:
        is_size_ok = await asyncio.to_thread(check_media_size_before_download, url, mode)
        if not is_size_ok:
            await status_msg.edit_text("⚠️┇هذا الملف أكبر من الحد المسموح (49 MB).")
            return

        (
            file_path,
            title,
            duration,
            thumb_path,
            temp_dir,
        ) = await asyncio.to_thread(download_youtube_media, url, mode)

        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        time_str = format_duration(duration)

        share_keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔀 | شارك", switch_inline_query=title[:100])]]
        )

        if mode == "yt_voice":
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
            with open(file_path, "rb") as voice_file:
                await context.bot.send_voice(
                    chat_id=chat_id,
                    voice=voice_file,
                    caption=f"@G66Gbot - {time_str}",
                    duration=int(duration),
                    reply_markup=share_keyboard,
                )

        elif mode == "yt_audio":
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VOICE)
            thumb_file = None
            try:
                if thumb_path and thumb_path.exists():
                    thumb_file = open(thumb_path, "rb")

                with open(file_path, "rb") as audio_file:
                    await context.bot.send_audio(
                        chat_id=chat_id,
                        audio=audio_file,
                        title=title[:200],
                        performer="@G66Gbot",
                        duration=int(duration),
                        thumbnail=thumb_file,
                        caption=f"@G66Gbot - {time_str}, {file_size_mb:.1f}MB",
                        reply_markup=share_keyboard,
                    )
            finally:
                if thumb_file:
                    thumb_file.close()

        else:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
            with open(file_path, "rb") as video_file:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=video_file,
                    caption=f"@G66Gbot - {time_str}, {file_size_mb:.1f}MB",
                    duration=int(duration),
                    supports_streaming=True,
                    reply_markup=share_keyboard,
                )

        try:
            await status_msg.delete()
        except Exception:
            pass

    except DownloadTooLarge:
        await status_msg.edit_text("⚠️┇تم تحميل الملف لكنه أكبر من الحد المسموح (49 MB).")
    except yt_dlp.utils.DownloadError as e:
        logger.exception("yt-dlp DownloadError")
        await status_msg.edit_text(f"❌ فشل تحميل فيديو يوتيوب.\n\n{str(e)[:700]}")
    except FileNotFoundError as e:
        logger.exception("File not found")
        await status_msg.edit_text(f"❌ {str(e)}")
    except Exception as e:
        logger.exception("Unexpected YouTube callback error")
        await status_msg.edit_text(f"❌ حدث خطأ أثناء التحميل.\n\nالخطأ: {str(e)[:700]}")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        else:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
            if thumb_path and os.path.exists(thumb_path):
                try:
                    os.remove(thumb_path)
                except Exception:
                    pass
 
