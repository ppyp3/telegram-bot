import asyncio
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
from telegram import InputMediaPhoto, InputMediaVideo, Update
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


class VideoProcessingError(InstagramDownloadError):
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


def get_mp4_dimensions(file_path):
    """Read the encoded MP4 dimensions without converting or re-encoding it."""
    try:
        data = file_path.read_bytes()
        search_from = 0

        while True:
            atom_type_position = data.find(b"tkhd", search_from)
            if atom_type_position == -1:
                return None, None

            payload_position = atom_type_position + 4
            version = data[payload_position]
            dimensions_position = payload_position + (76 if version == 0 else 88)

            if dimensions_position + 8 <= len(data):
                width = int.from_bytes(
                    data[dimensions_position : dimensions_position + 4], "big"
                ) >> 16
                height = int.from_bytes(
                    data[dimensions_position + 4 : dimensions_position + 8], "big"
                ) >> 16

                # Audio tracks have dimensions of 0; keep searching for the video track.
                if width > 0 and height > 0:
                    return width, height

            search_from = atom_type_position + 4
    except (IndexError, OSError):
        return None, None


def normalize_video_for_telegram(source_path):
    """Create an Android- and Telegram-compatible H.264/AAC MP4."""
    output_path = source_path.with_name(f"{source_path.stem}_telegram.mp4")
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-profile:v",
        "high",
        "-level:v",
        "4.1",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-shortest",
        str(output_path),
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except FileNotFoundError as error:
        raise VideoProcessingError("FFmpeg is not installed") from error
    except subprocess.TimeoutExpired as error:
        raise VideoProcessingError("Video conversion timed out") from error

    if result.returncode != 0 or not output_path.is_file():
        logger.error("FFmpeg failed: %s", result.stderr[-1500:])
        output_path.unlink(missing_ok=True)
        raise VideoProcessingError("Video conversion failed")

    if output_path.stat().st_size > MAX_MEDIA_SIZE:
        output_path.unlink(missing_ok=True)
        raise InstagramMediaTooLarge

    return output_path


async def normalize_videos_for_telegram(media_files):
    prepared_files = []

    for file_path in media_files:
        mime_type, _ = mimetypes.guess_type(file_path.name)
        if mime_type and mime_type.startswith("video/"):
            converted_path = await asyncio.to_thread(
                normalize_video_for_telegram, file_path
            )
            file_path.unlink(missing_ok=True)
            prepared_files.append(converted_path)
        else:
            prepared_files.append(file_path)

    return prepared_files


def download_reel_with_audio(url, output_dir):
    """Use Instagram's video and audio formats together when they are separate."""
    options = {
        "outtmpl": str(output_dir / "reel_%(id)s.%(ext)s"),
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "max_filesize": MAX_MEDIA_SIZE,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "writethumbnail": False,
        "writesubtitles": False,
        "writeautomaticsub": False,
    }

    with yt_dlp.YoutubeDL(options) as downloader:
        downloader.extract_info(url, download=True)

    media_files = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file()
        and not path.name.endswith((".part", ".ytdl"))
        and path.suffix.lower() in {".mp4", ".mkv", ".webm"}
    )

    if not media_files:
        raise InstagramDownloadError("No downloadable reel media was found")

    for path in media_files:
        if path.stat().st_size > MAX_MEDIA_SIZE:
            raise InstagramMediaTooLarge

    return media_files


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

        # Reels often expose video and audio as separate streams. Let yt-dlp merge
        # them through FFmpeg; for image posts or unsupported reels we use the
        # direct Instaloader URLs below.
        if post.is_video and post.typename != "GraphSidecar":
            try:
                return output_dir, download_reel_with_audio(url, output_dir)
            except yt_dlp.utils.DownloadError:
                logger.warning("Falling back to direct Instagram reel URL", exc_info=True)

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
        width, height = get_mp4_dimensions(file_path)
        video_arguments = {
            "video": None,
            "caption": caption,
            "supports_streaming": True,
        }
        if width and height:
            video_arguments.update({"width": width, "height": height})

        with file_path.open("rb") as media_file:
            video_arguments["video"] = media_file
            await message.reply_video(**video_arguments)


async def send_instagram_album(message, context, media_files):
    """Send a multi-item post as Telegram albums of up to ten items."""
    total_files = len(media_files)

    for start in range(0, total_files, 10):
        batch = media_files[start : start + 10]

        # Telegram albums must contain at least two items.
        if len(batch) == 1:
            await send_instagram_file(
                message,
                message.chat_id,
                context,
                batch[0],
                start + 1,
                total_files,
            )
            continue

        open_files = []
        media_group = []
        try:
            for offset, file_path in enumerate(batch, start=1):
                media_file = file_path.open("rb")
                open_files.append(media_file)
                absolute_index = start + offset
                caption = (
                    f"- @G66Gbot - {absolute_index}/{total_files}"
                    if absolute_index == total_files
                    else None
                )
                mime_type, _ = mimetypes.guess_type(file_path.name)

                if mime_type and mime_type.startswith("image/"):
                    media_group.append(InputMediaPhoto(media=media_file, caption=caption))
                else:
                    width, height = get_mp4_dimensions(file_path)
                    media_group.append(
                        InputMediaVideo(
                            media=media_file,
                            caption=caption,
                            supports_streaming=True,
                            width=width,
                            height=height,
                        )
                    )

            await message.reply_media_group(media=media_group)
        finally:
            for media_file in open_files:
                media_file.close()


async def handle_instagram_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    url = (update.message.text or "").strip()
    if not get_shortcode(url):
        return

    status_message = await update.message.reply_text(
        "⏰┇يرجى الانتظار، يتم قياس حجم التحميل..."
    )
    output_dir = None

    try:
        output_dir, media_files = await asyncio.to_thread(download_instagram_media, url)
        media_files = await normalize_videos_for_telegram(media_files)
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=ChatAction.UPLOAD_PHOTO,
        )
        await send_instagram_album(update.message, context, media_files)

        await status_message.delete()
    except InstagramMediaTooLarge:
        await status_message.edit_text(
            "⚠️┇هذا الملف لا يمكنني تحميله،\n"
            "⚠️┇لأن حجمه يتجاوز ( 50 Mbps )،\n"
            "⚠️┇أعد المحاوله مع ملف اخر."
        )
    except VideoProcessingError:
        await status_message.edit_text("❌ تعذر تجهيز صوت الريلز. حاول مرة أخرى.")
    except (
        InstagramDownloadError,
        instaloader.exceptions.InstaloaderException,
        requests.RequestException,
        yt_dlp.utils.DownloadError,
        TelegramError,
    ):
        logger.exception("Instagram download failed")
        await status_message.edit_text(
            "❌ تعذر تحميل هذا الرابط. تأكد أن الحساب والمنشور عام ثم أعد المحاولة."
        )
    except Exception:
        logger.exception("Unexpected Instagram handler error")
        await status_message.edit_text("❌ حدث خطأ أثناء تحميل محتوى الإنستغرام.")
    finally:
        if output_dir:
            await asyncio.to_thread(shutil.rmtree, output_dir, True)
