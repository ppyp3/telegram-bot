import asyncio
import logging
import mimetypes
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from telegram import Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import ContextTypes, filters


logger = logging.getLogger(__name__)
MAX_MEDIA_SIZE = 49 * 1024 * 1024

# يدعم البوستات والصور والريلز العامة فقط، بلا ستوريات وبلا كوكيز.
INSTAGRAM_FILTER = filters.TEXT & filters.Regex(
    r"(?i)^https?://(?:www\.)?instagram\.com/(?:p|reel|reels)/"
)


class InstagramDownloadError(Exception):
    pass


class InstagramMediaTooLarge(InstagramDownloadError):
    pass


def is_instagram_url(url):
    parsed = urlparse(url.strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    path_parts = [part for part in parsed.path.split("/") if part]

    return (
        parsed.scheme in {"http", "https"}
        and hostname in {"instagram.com", "www.instagram.com"}
        and bool(path_parts)
        and path_parts[0] in {"p", "reel", "reels"}
    )


def download_instagram_media(url):
    output_dir = Path(tempfile.mkdtemp(prefix="instagram_media_"))

    try:
        options = {
            "outtmpl": str(output_dir / "%(autonumber)03d_%(id)s.%(ext)s"),
            "format": "best",
            "max_filesize": MAX_MEDIA_SIZE,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "writethumbnail": False,
            "writesubtitles": False,
            "writeautomaticsub": False,
            "postprocessors": [],
        }

        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.extract_info(url, download=True)

        media_files = sorted(
            path
            for path in output_dir.iterdir()
            if path.is_file() and not path.name.endswith(".part")
        )

        if not media_files:
            raise InstagramDownloadError("No downloadable Instagram media was found")

        for path in media_files:
            if path.stat().st_size > MAX_MEDIA_SIZE:
                raise InstagramMediaTooLarge

        return output_dir, media_files

    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


async def send_instagram_file(message, chat_id, context, file_path, index, total):
    mime_type, _ = mimetypes.guess_type(file_path.name)
    caption = f"- @G66Gbot - {index}/{total}"

    if mime_type and mime_type.startswith("image/"):
        await context.bot.send_chat_action(
            chat_id=chat_id,
            action=ChatAction.UPLOAD_PHOTO
        )

        with file_path.open("rb") as media_file:
            await message.reply_photo(
                photo=media_file,
                caption=caption
            )

    elif mime_type and mime_type.startswith("video/"):
        await context.bot.send_chat_action(
            chat_id=chat_id,
            action=ChatAction.UPLOAD_VIDEO
        )

        with file_path.open("rb") as media_file:
            await message.reply_video(
                video=media_file,
                caption=caption,
                supports_streaming=True,
            )

    else:
        await context.bot.send_chat_action(
            chat_id=chat_id,
            action=ChatAction.UPLOAD_DOCUMENT
        )

        with file_path.open("rb") as media_file:
            await message.reply_document(
                document=media_file,
                caption=caption
            )


async def handle_instagram_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    url = (update.message.text or "").strip()

    if not is_instagram_url(url):
        return

    status_message = await update.message.reply_text(
        "⏳ جاري تحميل محتوى الإنستغرام..."
    )

    output_dir = None

    try:
        output_dir, media_files = await asyncio.to_thread(
            download_instagram_media,
            url
        )

        total_files = len(media_files)

        for index, file_path in enumerate(media_files, start=1):
            await send_instagram_file(
                update.message,
                update.effective_chat.id,
                context,
                file_path,
                index,
                total_files,
            )

        await status_message.delete()

    except InstagramMediaTooLarge:
        await status_message.edit_text(
            "⚠️┇هذا الملف لا يمكنني تحميله،\n"
            "⚠️┇لأن حجمه يتجاوز ( 50 Mbps )،\n"
            "⚠️┇أعد المحاوله مع ملف اخر."
        )

    except (InstagramDownloadError, yt_dlp.utils.DownloadError, TelegramError):
        logger.exception("Instagram download failed")

        await status_message.edit_text(
            "❌ تعذر تحميل هذا الرابط. تأكد أن الحساب والمنشور عامان ثم أعد المحاولة."
        )

    except Exception:
        logger.exception("Unexpected Instagram handler error")

        await status_message.edit_text(
            "❌ حدث خطأ أثناء تحميل محتوى الإنستغرام."
        )

    finally:
        if output_dir:
            await asyncio.to_thread(shutil.rmtree, output_dir, True)
