import asyncio
import html
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

MAX_MEDIA_SIZE = 49 * 1024 * 1024
COOKIES_FILE = "cookies.txt"

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()

YOUTUBE_REGEX = re.compile(
    r"https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtube\.com/shorts/|"
    r"youtube\.com/embed/|youtu\.be/)([A-Za-z0-9_-]+)",
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

def normalize_mode(mode):
    aliases = {
        "yt_video": "video",
        "video": "video",
        "yt_audio": "yt_audio",
        "audio": "yt_audio",
        "yt_voice": "yt_voice",
    }

    normalized = aliases.get(mode)

    if normalized is None:
        raise ValueError(f"Unknown YouTube mode: {mode}")

    return normalized


def extract_youtube_url(text: str):
    if not text:
        return None

    match = YOUTUBE_REGEX.search(text)
    return match.group(0) if match else None


def extract_video_id(url: str):
    match = YOUTUBE_REGEX.search(url)
    return match.group(1) if match else None


def format_views(views):
    try:
        views = int(views or 0)
    except (ValueError, TypeError):
        return "0"

    if views >= 1_000_000:
        return f"{views / 1_000_000:.1f}M"

    if views >= 1_000:
        return f"{views / 1_000:.1f}K"

    return str(views)


def parse_iso8601_duration(duration_str):
    match = re.match(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
        duration_str or "",
    )

    if not match:
        return 0

    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)

    return hours * 3600 + minutes * 60 + seconds


def format_duration(seconds):
    try:
        seconds = int(seconds or 0)
    except (ValueError, TypeError):
        seconds = 0

    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    return f"{minutes:02d}:{seconds:02d}"


def get_common_ydl_opts():
    opts = {
        "quiet": True,
        "no_warnings": False,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "file_access_retries": 3,
        "concurrent_fragment_downloads": 4,
        "noprogress": True,
    }

    if os.path.isfile(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE

    return opts


# ---------------------------------------------------------
# YouTube information through Google API v3
# ---------------------------------------------------------

def get_youtube_info(url: str):
    video_id = extract_video_id(url)

    if not video_id:
        raise ValueError("رابط يوتيوب غير صالح.")

    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()

    if not api_key:
        raise ValueError(
            "مفتاح YOUTUBE_API_KEY غير موجود في Railway Variables."
        )

    api_url = "https://www.googleapis.com/youtube/v3/videos"

    params = {
        "part": "snippet,contentDetails,statistics",
        "id": video_id,
        "key": api_key,
    }

    try:
        response = requests.get(
            api_url,
            params=params,
            timeout=15,
        )

        try:
            data = response.json()
        except ValueError as error:
            raise ValueError(
                "Google API رجّع استجابة غير مفهومة."
            ) from error

        if response.status_code != 200:
            error_data = data.get("error", {})
            errors = error_data.get("errors", [])

            reason = (
                errors[0].get("reason", "")
                if errors
                else ""
            )

            message = error_data.get(
                "message",
                "خطأ غير معروف",
            )

            logger.error(
                "YouTube API error: status=%s reason=%s message=%s",
                response.status_code,
                reason,
                message,
            )

            raise ValueError(
                f"YouTube API: {reason or message}"
            )

        items = data.get("items", [])

        if not items:
            raise ValueError(
                "لم يتم العثور على معلومات الفيديو عبر Google API."
            )

        item = items[0]
        snippet = item.get("snippet", {})
        details = item.get("contentDetails", {})
        statistics = item.get("statistics", {})
        thumbnails = snippet.get("thumbnails", {})

        thumbnail = (
            thumbnails.get("maxres", {}).get("url")
            or thumbnails.get("high", {}).get("url")
            or thumbnails.get("medium", {}).get("url")
            or thumbnails.get("default", {}).get("url")
        )

        duration = parse_iso8601_duration(
            details.get("duration", "PT0S")
        )

        return {
            "title": snippet.get("title", "فيديو يوتيوب"),
            "uploader": snippet.get("channelTitle", "غير معروف"),
            "duration": duration,
            "duration_string": format_duration(duration),
            "view_count_formatted": format_views(
                statistics.get("viewCount", 0)
            ),
            "thumbnail": thumbnail,
            "url": url,
        }

    except requests.RequestException as error:
        logger.exception("Connection to YouTube API failed")
        raise ValueError(
            f"تعذر الاتصال بـ Google API: {error}"
        ) from error


# ---------------------------------------------------------
# Download information
# ---------------------------------------------------------

def get_download_info(url: str, mode: str):
    mode = normalize_mode(mode)
    opts = get_common_ydl_opts()
    opts["skip_download"] = True

    if mode in ("yt_audio", "yt_voice"):
        opts["format"] = "bestaudio/best"
    else:
        opts["format"] = "bestvideo*+bestaudio/best"

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        raise ValueError("لم يتمكن yt-dlp من قراءة معلومات الفيديو.")

    return info


# ---------------------------------------------------------
# Size check
# ---------------------------------------------------------

def check_media_size_before_download(url: str, mode: str = "video"):
    mode = normalize_mode(mode)

    try:
        info = get_download_info(url, mode)

        # إذا حجم الصيغة المختارة معروف، نفحصه.
        filesize = info.get("filesize") or info.get("filesize_approx")

        if filesize:
            return int(filesize) <= MAX_MEDIA_SIZE

        # إذا الحجم غير معروف، لا نرفض الفيديو مباشرة.
        return True

    except Exception:
        logger.exception("Size check failed")
        # السماح بمحاولة التنزيل، ثم فحص الحجم الفعلي.
        return True


# ---------------------------------------------------------
# Download media
# ---------------------------------------------------------

def download_youtube_media(url: str, mode: str = "video"):
    mode = normalize_mode(mode)

    temp_dir = tempfile.mkdtemp(prefix="yt_")
    logger.info("Temporary directory created")

    try:
        outtmpl = os.path.join(
            temp_dir,
            "%(title).150s.%(ext)s",
        )

        opts = get_common_ydl_opts()

        opts.update({
            "outtmpl": outtmpl,
            "quiet": True,
            "noprogress": True,
            "overwrites": True,
        })

        if mode == "video":
            # أفضل فيديو مع الصوت، مع صيغة احتياطية جاهزة.
            opts["format"] = "bestvideo*+bestaudio/best"
            opts["merge_output_format"] = "mp4"

        elif mode == "yt_audio":
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]

        elif mode == "yt_voice":
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "opus",
                }
            ]

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)

            if not info:
                raise ValueError(
                    "yt-dlp لم يرجع معلومات بعد التنزيل."
                )

            title = info.get("title", "فيديو يوتيوب")
            duration = int(info.get("duration") or 0)

        # البحث عن الملفات الناتجة.
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
            p for p in Path(temp_dir).glob("*")
            if p.is_file()
            and p.suffix.lower() in allowed_media
        ]

        if not media_files:
            raise FileNotFoundError(
                "لم يتم العثور على الملف الناتج. "
                "تحقق من تثبيت FFmpeg في Railway."
            )

        # اختيار الملف الناتج المناسب لنوع الطلب.
        if mode == "video":
            candidates = [
                p for p in media_files
                if p.suffix.lower() in {
                    ".mp4", ".mkv", ".webm"
                }
            ]
        elif mode == "yt_audio":
            candidates = [
                p for p in media_files
                if p.suffix.lower() == ".mp3"
            ]
        else:
            candidates = [
                p for p in media_files
                if p.suffix.lower() in {".opus", ".ogg"}
            ]

        if not candidates:
            raise FileNotFoundError(
                "لم يتم العثور على صيغة الملف المطلوبة بعد التحويل."
            )

        file_path = max(
            candidates,
            key=lambda p: p.stat().st_size,
        )

        # ملفات Opus الناتجة تكون عادةً داخل حاوية Ogg.
        # نغيّر الامتداد فقط لتناسب إرسال الرسالة الصوتية.
        if mode == "yt_voice" and file_path.suffix.lower() == ".opus":
            ogg_path = file_path.with_suffix(".ogg")
            file_path.rename(ogg_path)
            file_path = ogg_path

        file_size = file_path.stat().st_size

        if file_size > MAX_MEDIA_SIZE:
            raise DownloadTooLarge(
                "حجم الملف أكبر من الحد المسموح (49 MB)."
            )

        return (
            file_path,
            title,
            duration,
            None,
            temp_dir,
        )

    except Exception:
        logger.exception("YouTube download failed")
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


# ---------------------------------------------------------
# Handle YouTube message
# ---------------------------------------------------------

async def handle_youtube_message(update, context):
    message = update.effective_message

    if not message:
        return

    text = message.text or message.caption or ""
    url = extract_youtube_url(text)

    if not url:
        return

    user = update.effective_user
    user_id = user.id if user else 0

    processing_msg = await message.reply_text(
        "⏳┇جاري قراءة معلومات الفيديو..."
    )

    try:
        info = await asyncio.to_thread(
            get_youtube_info,
            url,
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "🎬 فيديو",
                    callback_data="yt_video",
                )
            ],
            [
                InlineKeyboardButton(
                    "🎧 ملف صوتي",
                    callback_data="yt_audio",
                ),
                InlineKeyboardButton(
                    "🎙 بصمة صوتية",
                    callback_data="yt_voice",
                ),
            ],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        safe_title = html.escape(info["title"])
        safe_uploader = html.escape(info["uploader"])
        safe_url = html.escape(info["url"])

        caption = (
            f'🎬 <a href="{safe_url}">{safe_title}</a>\n'
            f"👤 {safe_uploader}\n"
            f'⏱ {info["duration_string"]} - '
            f'👁 {info["view_count_formatted"]}'
        )

        sent_msg = None

        if info.get("thumbnail"):
            try:
                sent_msg = await message.reply_photo(
                    photo=info["thumbnail"],
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
            except Exception:
                logger.exception("Failed to send YouTube thumbnail")

        if sent_msg is None:
            sent_msg = await message.reply_text(
                text=caption,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )

        sessions = context.application.bot_data.setdefault(
            "yt_sessions",
            {},
        )

        sessions[(sent_msg.chat_id, sent_msg.message_id)] = {
            "user_id": user_id,
            "url": url,
            "title": info["title"],
        }

        await processing_msg.delete()

    except Exception as error:
        logger.exception("Error handling YouTube message")

        await processing_msg.edit_text(
            "❌ حدث خطأ أثناء معالجة الرابط.\n\n"
            f"الخطأ: {str(error)[:500]}"
        )


# ---------------------------------------------------------
# Callback
# ---------------------------------------------------------

async def handle_youtube_callback(
    query,
    context,
    session_data,
    mode,
):
    mode = normalize_mode(mode)

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
        text="♻️┇جاري تحميل الملف...",
    )

    temp_dir = None
    file_path = None

    try:
        is_size_ok = await asyncio.to_thread(
            check_media_size_before_download,
            url,
            mode,
        )

        if not is_size_ok:
            await status_msg.edit_text(
                "⚠️┇الملف أكبر من الحد المسموح (49 MB)."
            )
            return

        (
            file_path,
            title,
            duration,
            thumb_path,
            temp_dir,
        ) = await asyncio.to_thread(
            download_youtube_media,
            url,
            mode,
        )

        file_size_mb = (
            os.path.getsize(file_path) / (1024 * 1024)
        )

        time_str = format_duration(duration)

        share_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔀 | شارك",
                    switch_inline_query=title[:100],
                )
            ]
        ])

        if mode == "yt_voice":
            await context.bot.send_chat_action(
                chat_id=chat_id,
                action=ChatAction.UPLOAD_VOICE,
            )

            with open(file_path, "rb") as voice_file:
                await context.bot.send_voice(
                    chat_id=chat_id,
                    voice=voice_file,
                    caption=f"@G66Gbot - {time_str}",
                    duration=int(duration),
                    reply_markup=share_keyboard,
                    filename="audio.ogg",
                    read_timeout=120,
                    write_timeout=120,
                )

        elif mode == "yt_audio":
            await context.bot.send_chat_action(
                chat_id=chat_id,
                action=ChatAction.UPLOAD_DOCUMENT,
            )

            with open(file_path, "rb") as audio_file:
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=audio_file,
                    title=title[:200],
                    performer="@G66Gbot",
                    duration=int(duration),
                    caption=(
                        f"@G66Gbot - {time_str}, "
                        f"{file_size_mb:.1f}MB"
                    ),
                    reply_markup=share_keyboard,
                    filename="audio.mp3",
                    read_timeout=120,
                    write_timeout=120,
                )

        else:
            await context.bot.send_chat_action(
                chat_id=chat_id,
                action=ChatAction.UPLOAD_VIDEO,
            )

            with open(file_path, "rb") as video_file:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=video_file,
                    caption=(
                        f"@G66Gbot - {time_str}, "
                        f"{file_size_mb:.1f}MB"
                    ),
                    duration=int(duration),
                    supports_streaming=True,
                    reply_markup=share_keyboard,
                    filename="video.mp4",
                    read_timeout=120,
                    write_timeout=120,
                )

        try:
            await status_msg.delete()
        except Exception:
            pass

    except DownloadTooLarge:
        await status_msg.edit_text(
            "⚠️┇حجم الملف أكبر من الحد المسموح (49 MB)."
        )

    except yt_dlp.utils.DownloadError as error:
        logger.exception("yt-dlp DownloadError")

        await status_msg.edit_text(
            "❌ فشل تحميل الوسائط من يوتيوب.\n\n"
            f"{str(error)[:700]}"
        )

    except FileNotFoundError as error:
        logger.exception("Media file not found")

        await status_msg.edit_text(
            f"❌ {str(error)[:700]}"
        )

    except Exception as error:
        logger.exception("Unexpected YouTube callback error")

        await status_msg.edit_text(
            "❌ حدث خطأ أثناء التحميل أو الإرسال.\n\n"
            f"الخطأ: {str(error)[:700]}"
        )

    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

        elif file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                logger.warning("Could not remove temporary media file")
 
