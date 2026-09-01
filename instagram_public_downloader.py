import asyncio
import logging
import mimetypes
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import instaloader
import requests
from telegram import Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import ContextTypes, filters


logger = logging.getLogger(__name__)
MAX_MEDIA_SIZE = 49 * 1024 * 1024
DOWNLOAD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.instagram.com/",
}

# الصور والبوستات والريلز العامة فقط. لا يدعم الستوري أو الحسابات الخاصة.
INSTAGRAM_FILTER = filters.TEXT & filters.Regex(
    r"(?i)^https?://(?:www\.)?instagram\.com/(?:p|reel|reels)/"
)


class InstagramDownloadError(Exception):
    pass


class InstagramMediaTooLarge(InstagramDownloadError):
    pass


def get_shortcode(url):
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

    return parts[1]


def download_file(url, output_path):
    response = None
    try:
        response = requests.get(
            url,
            headers=DOWNLOAD_HEADERS,
            timeout=(10, 45),
            stream=True,
        )
        response.raise_for_status()

        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > MAX_MEDIA_SIZE:
                    raise InstagramMediaTooLarge
            except ValueError:
                pass

        downloaded = 0
        with output_path.open("wb") as output_file:
            for chunk in response.iter_content(chunk_size=128 * 1024):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > MAX_MEDIA_SIZE:
                    raise InstagramMediaTooLarge
                output_file.write(chunk)
    finally:
        if response is not None:
            response.close()


def download_instagram_media(url):
    shortcode = get_shortcode(url)
    if not shortcode:
        raise InstagramDownloadError("Invalid Instagram URL")

    output_dir = Path(tempfile.mkdtemp(prefix="instagram_media_"))

    try:
        loader = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            save_metadata=False,
            compress_json=False,
            post_metadata_txt_pattern="",
        )
        post = instaloader.Post.from_shortcode(loader.context, shortcode)

        if post.typename == "GraphSidecar":
            media_items = [
                (node.video_url if node.is_video else node.display_url, node.is_video)
                for node in post.get_sidecar_nodes()
            ]
        else:
            media_items = [
                (post.video_url if post.is_video else post.url, post.is_video)
            ]

        media_files = []
        for index, (media_url, is_video) in enumerate(media_items, start=1):
            if not media_url:
                continue
            suffix = ".mp4" if is_video else ".jpg"
            output_path = output_dir / f"{index:03d}{suffix}"
            download_file(media_url, output_path)
            media_files.append(output_path)

        if not media_files:
            raise InstagramDownloadError("No downloadable Instagram media was found")

        return output_dir, media_files

    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


async def send_instagram_file(message, chat_id, context, file_path, index, total):
    mime_type, _ = mimetypes.guess_type(file_path.name)
    caption = f"- @G66Gbot - {index}/{total}"

    if mime_type and mime_type.startswith("image/"):
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
        with file_path.open("rb") as media_file:
            await message.reply_photo(photo=media_file, caption=caption)
    else:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
        with file_path.open("rb") as media_file:
            await message.reply_video(
                video=media_file,
                caption=caption,
                supports_streaming=True,
            )


async def handle_instagram_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    url = (update.message.text or "").strip()
    if not get_shortcode(url):
        return

    status_message = await update.message.reply_text("⏳ جاري تحميل محتوى الإنستغرام...")
    output_dir = None

    try:
        output_dir, media_files = await asyncio.to_thread(download_instagram_media, url)
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
    except (
        InstagramDownloadError,
        instaloader.exceptions.InstaloaderException,
        requests.RequestException,
        TelegramError,
    ):
        logger.exception("Instagram download failed")
        await status_message.edit_text(
            "❌ تعذر تحميل هذا الرابط. تأكد أن الحساب والمنشور عامان ثم أعد المحاولة."
        )
    except Exception:
        logger.exception("Unexpected Instagram handler error")
        await status_message.edit_text("❌ حدث خطأ أثناء تحميل محتوى الإنستغرام.")
    finally:
        if output_dir:
            await asyncio.to_thread(shutil.rmtree, output_dir, True)
