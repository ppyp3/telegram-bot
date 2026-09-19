import asyncio
import html
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

import yt_dlp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import filters

logger = logging.getLogger(__name__)

MAX_MEDIA_SIZE = 49 * 1024 * 1024
COOKIES_FILE = os.path.join(os.path.dirname(__file__), "cookies.txt")

YOUTUBE_REGEX = re.compile(
    r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/(watch\?v=|shorts/|embed/)?([a-zA-Z0-9_-]+)"
)


class DownloadTooLarge(Exception):
    pass


class YoutubeFilter(filters.MessageFilter):
    def filter(self, message):
        text = message.text or message.caption or ""
        return bool(YOUTUBE_REGEX.search(text.strip()))


YOUTUBE_FILTER = YoutubeFilter()


def is_valid_youtube_url(url: str) -> bool:
    if not url:
        return False
    return bool(YOUTUBE_REGEX.search(url.strip()))


def extract_youtube_url(text: str) -> str:
    """Return only the YouTube link when it is sent alongside other text."""
    match = YOUTUBE_REGEX.search(text or "")
    if not match:
        raise ValueError("Invalid YouTube URL")
    return match.group(0)


def format_views(views):
    if not views:
        return "0"
    if views >= 1_000_000:
        return f"{views / 1_000_000:.1f}M"
    if views >= 1_000:
        return f"{int(views / 1_000)}K"
    return str(views)


def _ydl_base_options():
    options = {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "noplaylist": True,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        },
    }
    if os.path.exists(COOKIES_FILE):
        options["cookiefile"] = COOKIES_FILE
    return options


def get_youtube_info(url: str):
    """استخراج معلومات الفيديو بدون فرض أي صيغة محددة لتجنب Requested format is not available"""
    ydl_opts = _ydl_base_options()
    ydl_opts["skip_download"] = True

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info:
            raise ValueError("Could not extract info")

        duration = info.get("duration", 0) or 0
        minutes, seconds = divmod(int(duration), 60)
        return {
            "title": info.get("title") or "فيديو يوتيوب",
            "uploader": info.get("uploader") or info.get("channel") or "غير معروف",
            "duration": duration,
            "duration_string": f"{minutes:02d}:{seconds:02d}",
            "view_count_formatted": format_views(info.get("view_count")),
            "thumbnail": info.get("thumbnail"),
            "url": url,
        }


def download_youtube_media(url: str, mode: str = "video"):
    temp_dir = tempfile.mkdtemp()
    outtmpl = os.path.join(temp_dir, "%(title)s.%(ext)s")
    ydl_opts = _ydl_base_options()
    ydl_opts.update({"outtmpl": outtmpl, "writethumbnail": True})

    if mode in ["audio", "yt_audio", "yt_voice"]:
        ydl_opts.update(
            {
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    },
                    {"key": "FFmpegThumbnailsConvertor", "format": "jpg"},
                ],
            }
        )
    else:
        ydl_opts.update(
            {
                "format": "bestvideo+bestaudio/best",
                "merge_output_format": "mp4",
            }
        )

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        title = info.get("title", "فيديو يوتيوب")
        duration = info.get("duration", 0) or 0
        media_files = [
            path
            for path in Path(temp_dir).glob("*")
            if path.suffix.lower() in [".mp3", ".mp4", ".m4a", ".webm", ".ogg", ".mkv"]
        ]
        if not media_files:
            raise FileNotFoundError("لم يتم العثور على الملف المحمل.")

        # Prefer the final expected format when yt-dlp leaves an intermediate file.
        preferred_suffix = ".mp3" if mode in ["audio", "yt_audio", "yt_voice"] else ".mp4"
        file_path = next((path for path in media_files if path.suffix.lower() == preferred_suffix), media_files[0])
        thumb_path = next(
            (
                path
                for path in Path(temp_dir).glob("*")
                if path.suffix.lower() in [".jpg", ".jpeg", ".png"]
            ),
            None,
        )

        if file_path.stat().st_size > MAX_MEDIA_SIZE:
            raise DownloadTooLarge("حجم الملف يتجاوز الحد المسموح.")

        return file_path, title, duration, thumb_path
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


async def handle_youtube_message(update, context):
    message = update.effective_message
    url = extract_youtube_url(message.text or message.caption or "")
    user_id = update.effective_user.id

    processing_msg = await message.reply_text("⏰┇يرجى الانتظار، جاري معالجة رابط يوتيوب...")

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
        safe_url = html.escape(info["url"], quote=True)
        safe_title = html.escape(info["title"])
        safe_uploader = html.escape(info["uploader"])
        caption = (
            f'🎬 <a href="{safe_url}">'
            f"{safe_title}</a>\n"
            f"👤 {safe_uploader}\n"
            f'⏱ {info["duration_string"]} - 👁 {info["view_count_formatted"]}'
        )

        if info["thumbnail"]:
            try:
                sent_msg = await message.reply_photo(
                    photo=info["thumbnail"], caption=caption, parse_mode="HTML", reply_markup=reply_markup
                )
            except Exception:
                logger.warning("Unable to send YouTube thumbnail; sending text card instead", exc_info=True)
                sent_msg = await message.reply_text(
                    text=caption, parse_mode="HTML", reply_markup=reply_markup
                )
        else:
            sent_msg = await message.reply_text(
                text=caption, parse_mode="HTML", reply_markup=reply_markup
            )

        sessions = context.application.bot_data.setdefault("yt_sessions", {})
        sessions[(sent_msg.chat_id, sent_msg.message_id)] = {
            "user_id": user_id,
            "url": url,
            "title": info["title"],
        }
        await processing_msg.delete()
    except Exception:
        logger.exception("Error handling YouTube message")
        await processing_msg.edit_text("❌ حدث خطأ أثناء معالجة رابط يوتيوب.")


async def handle_youtube_callback(query, context, session_data, mode):
    chat_id = query.message.chat_id
    url = session_data["url"]
    await query.answer()

    try:
        await query.message.delete()
    except Exception:
        pass

    status_msg = await context.bot.send_message(chat_id=chat_id, text="🔄 جاري التحميل، يرجى الانتظار...")
    file_path = None
    thumb_path = None

    try:
        file_path, title, duration, thumb_path = await asyncio.to_thread(download_youtube_media, url, mode)
        share_keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔀 | شارك.", switch_inline_query=f"{title}")]]
        )
        file_size_mb = f"{os.path.getsize(file_path) / (1024 * 1024):.1f}MB"
        minutes, seconds = divmod(int(duration), 60)
        time_str = f"{minutes:02d}:{seconds:02d}"

        if mode == "yt_voice":
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
            with open(file_path, "rb") as voice_file:
                await context.bot.send_voice(
                    chat_id=chat_id, voice=voice_file, caption=f"@G66Gbot - {time_str}",
                    duration=int(duration), reply_markup=share_keyboard
                )
        elif mode == "yt_audio":
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VOICE)
            with open(file_path, "rb") as audio_file:
                with open(thumb_path, "rb") if thumb_path and thumb_path.exists() else _NullContext() as thumb_file:
                    await context.bot.send_audio(
                        chat_id=chat_id, audio=audio_file, title=title, performer="@G66Gbot",
                        duration=int(duration), thumbnail=thumb_file,
                        caption=f"@G66Gbot - {time_str}, {file_size_mb}", reply_markup=share_keyboard
                    )
        else:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
            with open(file_path, "rb") as video_file:
                await context.bot.send_video(
                    chat_id=chat_id, video=video_file, caption=f"@G66Gbot - {time_str}, {file_size_mb}",
                    duration=int(duration), reply_markup=share_keyboard
                )
        await status_msg.delete()
    except DownloadTooLarge:
        await status_msg.edit_text("⚠️┇هذا الملف لا يمكنني تحميله، لأن حجمه يتجاوز ( 50 MB ).")
    except Exception:
        logger.exception("Error in YouTube callback process")
        await status_msg.edit_text("❌ حدث خطأ أثناء التحميل.")
    finally:
        if file_path:
            shutil.rmtree(file_path.parent, ignore_errors=True)


class _NullContext:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc_value, traceback):
        return False
