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


def probe_video(file_path):
    """Return (video_codec, audio_codec, width, height, duration) via ffprobe."""
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,codec_name,width,height:format=duration",
        "-of",
        "json",
        str(file_path),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=60, check=False
        )
        data = json.loads(result.stdout or "{}")
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        return None, None, None, None, None

    video_codec = audio_codec = width = height = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and video_codec is None:
            video_codec = stream.get("codec_name")
            width = stream.get("width")
            height = stream.get("height")
        elif stream.get("codec_type") == "audio" and audio_codec is None:
            audio_codec = stream.get("codec_name")

    try:
        duration = int(float(data.get("format", {}).get("duration", 0))) or None
    except (TypeError, ValueError):
        duration = None

    return video_codec, audio_codec, width, height, duration


def run_ffmpeg(command, output_path, timeout=300):
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError as error:
        raise VideoProcessingError("FFmpeg is not installed") from error
    except subprocess.TimeoutExpired as error:
        output_path.unlink(missing_ok=True)
        raise VideoProcessingError("Video processing timed out") from error

    if result.returncode != 0 or not output_path.is_file():
        # A negative return code means the process was killed, usually by the
        # container's out-of-memory killer.
        logger.error(
            "FFmpeg failed (exit %s): %s ... %s",
            result.returncode,
            result.stderr[:1500],
            result.stderr[-1500:],
        )
        output_path.unlink(missing_ok=True)
        raise VideoProcessingError(f"Video processing failed (exit {result.returncode})")


def build_ffmpeg_command(source_path, output_path, copy_video, copy_audio):
    # Limit threads: x264 defaults to one thread per CPU core, which can exhaust
    # a small container's memory and get the process killed.
    command = [
        "ffmpeg",
        "-y",
        "-threads",
        "2",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
    ]

    if copy_video:
        command += ["-c:v", "copy"]
    else:
        command += [
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-profile:v", "high",
            "-level:v", "4.1",
            "-pix_fmt", "yuv420p",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-x264-params", "threads=2:lookahead_threads=1:sliced-threads=0",
        ]

    if copy_audio:
        command += ["-c:a", "copy"]
    else:
        command += ["-c:a", "aac", "-b:a", "192k", "-ac", "2"]

    return command + ["-movflags", "+faststart", str(output_path)]


def normalize_video_for_telegram(source_path):
    """Make the file an Android-friendly H.264/AAC MP4 with a moov atom up front.

    Instagram already serves H.264/AAC, so the streams are normally copied and
    only the container is rebuilt; re-encoding is the last resort because it is
    the step heavy enough to be killed on a small container.
    """
    video_codec, audio_codec, _, _, _ = probe_video(source_path)
    output_path = source_path.with_name(f"{source_path.stem}_telegram.mp4")
    copy_video = video_codec == "h264"
    copy_audio = audio_codec in {None, "aac"}

    try:
        run_ffmpeg(
            build_ffmpeg_command(source_path, output_path, copy_video, copy_audio),
            output_path,
        )
    except VideoProcessingError:
        if not copy_video and not copy_audio:
            raise
        logger.warning("Stream copy failed, re-encoding instead", exc_info=True)
        run_ffmpeg(
            build_ffmpeg_command(source_path, output_path, False, False), output_path
        )

    if output_path.stat().st_size > MAX_MEDIA_SIZE:
        output_path.unlink(missing_ok=True)
        raise InstagramMediaTooLarge

    return output_path


def create_video_thumbnail(file_path):
    """Telegram shows a film icon when no thumbnail is attached; build one."""
    thumbnail_path = file_path.with_name(f"{file_path.stem}_thumb.jpg")
    command = [
        "ffmpeg",
        "-y",
        "-ss",
        "0.5",
        "-i",
        str(file_path),
        "-frames:v",
        "1",
        "-vf",
        "scale=320:-2",
        "-q:v",
        "4",
        str(thumbnail_path),
    ]
    try:
        run_ffmpeg(command, thumbnail_path, timeout=60)
    except VideoProcessingError:
        return None
    return thumbnail_path


def is_video_file(file_path):
    mime_type, _ = mimetypes.guess_type(file_path.name)
    return bool(mime_type and mime_type.startswith("video/"))


def normalize_media_files(media_files):
    prepared_files = []

    for file_path in media_files:
        if is_video_file(file_path):
            try:
                converted_path = normalize_video_for_telegram(file_path)
            except VideoProcessingError:
                # Better to send the original file than to fail the request.
                logger.exception("Falling back to the unprocessed video")
                prepared_files.append(file_path)
                continue
            file_path.unlink(missing_ok=True)
            prepared_files.append(converted_path)
        else:
            prepared_files.append(file_path)

    return prepared_files


MERGED_FORMAT = (
    "bv*[vcodec^=avc1][ext=mp4]+ba[acodec^=mp4a][ext=m4a]/bv*[ext=mp4]+ba/bv*+ba"
)
# A single progressive file already carries its audio, so FFmpeg never has to
# merge anything.
PREMUXED_FORMAT = "b[ext=mp4][acodec!=none]/b[acodec!=none]/b"


def run_reel_download(url, output_dir, media_format):
    options = {
        "outtmpl": str(output_dir / "reel_%(id)s.%(ext)s"),
        "format": media_format,
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

    return sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file()
        and not path.name.endswith((".part", ".ytdl"))
        and path.suffix.lower() in {".mp4", ".mkv", ".webm"}
    )


def download_reel_with_audio(url, output_dir):
    """Download a reel, retrying with a pre-muxed stream when audio is missing."""
    media_files = []

    for media_format in (MERGED_FORMAT, PREMUXED_FORMAT):
        for stale_file in output_dir.iterdir():
            if stale_file.is_file():
                stale_file.unlink(missing_ok=True)

        media_files = run_reel_download(url, output_dir, media_format)
        if media_files and all(probe_video(path)[1] for path in media_files):
            break

        logger.warning("Reel has no audio track, retrying with another format")

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

        if post.is_video and post.typename != "GraphSidecar":
            try:
                reel_files = download_reel_with_audio(url, output_dir)
                return output_dir, normalize_media_files(reel_files)
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

        return output_dir, normalize_media_files(media_files)

    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


async def send_instagram_file(message, chat_id, context, file_path, index, total):
    caption = f"- @G66Gbot - {index}/{total}"

    if not is_video_file(file_path):
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
        with file_path.open("rb") as media_file:
            await message.reply_photo(photo=media_file, caption=caption)
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
    _, _, width, height, duration = await asyncio.to_thread(probe_video, file_path)
    thumbnail_path = await asyncio.to_thread(create_video_thumbnail, file_path)

    video_arguments = {
        "caption": caption,
        "supports_streaming": True,
        "width": width,
        "height": height,
        "duration": duration,
    }

    thumbnail_file = thumbnail_path.open("rb") if thumbnail_path else None
    try:
        if thumbnail_file:
            video_arguments["thumbnail"] = thumbnail_file
        with file_path.open("rb") as media_file:
            await message.reply_video(video=media_file, **video_arguments)
    finally:
        if thumbnail_file:
            thumbnail_file.close()


async def send_instagram_album(message, context, media_files):
    total_files = len(media_files)

    for start in range(0, total_files, 10):
        batch = media_files[start : start + 10]

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

                if not is_video_file(file_path):
                    media_group.append(InputMediaPhoto(media=media_file, caption=caption))
                    continue

                _, _, width, height, duration = await asyncio.to_thread(
                    probe_video, file_path
                )
                thumbnail_path = await asyncio.to_thread(create_video_thumbnail, file_path)
                thumbnail_file = thumbnail_path.open("rb") if thumbnail_path else None
                if thumbnail_file:
                    open_files.append(thumbnail_file)

                media_group.append(
                    InputMediaVideo(
                        media=media_file,
                        caption=caption,
                        supports_streaming=True,
                        width=width,
                        height=height,
                        duration=duration,
                        thumbnail=thumbnail_file,
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
        await status_message.edit_text("❌ تعذر تجهيز الفيديو. حاول مرة أخرى.")
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
