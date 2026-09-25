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
    try:
        stat = file_path.stat()
    except OSError:
        stat = None
    cache_key = (
        (file_path, stat.st_mtime, stat.st_size)
        if stat is not None
        else None
    )
    if cache_key in PROBE_VIDEO_CACHE:
        return PROBE_VIDEO_CACHE[cache_key]

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
        return store_in_cache(
            PROBE_VIDEO_CACHE,
            cache_key,
            (UNKNOWN_CODEC, UNKNOWN_CODEC, None, None, None),
        )

    if not data.get("streams"):
        return store_in_cache(
            PROBE_VIDEO_CACHE,
            cache_key,
            (UNKNOWN_CODEC, UNKNOWN_CODEC, None, None, None),
        )

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

    return store_in_cache(
        PROBE_VIDEO_CACHE, cache_key, (video_codec, audio_codec, width, height, duration)
    )


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
        output_path.unlink(missing_ok=True)
        raise VideoProcessingError(f"Video processing failed (exit {result.returncode})")


def normalize_video_for_telegram(source_path):
    video_codec, audio_codec, _, _, _ = probe_video(source_path)
    if not video_codec:
        raise VideoProcessingError("Downloaded file has no video stream")
    if not audio_codec:
        raise VideoProcessingError("Downloaded reel has no audio stream")
    output_path = source_path.with_name(f"{source_path.stem}_telegram.mp4")
    
    # حل نهائي لإجبار FFmpeg على تضمين وتوليد الصوت بنظام AAC لضمان عمله نهائياً مع الحفاظ على الحجم الصغير والدقة الأصلية
    command = [
        "ffmpeg",
        "-y",
        "-threads",
        "4",
        "-i",
        str(source_path),
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "28",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",         # إجبار تحويل وتوليد الصوت بصيغة AAC المتوافقة كلياً مع تليجرام
        "-b:a",
        "128k",        # رفع معدل بت الصوت قليلاً لضمان نقائه ووضوحه التام
        "-map",
        "0:v:0?",      # اختيار مسار الفيديو الإجباري
        "-map",
        "0:a:0",      # اختيار مسار الصوت الإجباري حتى لو كان منفصلاً
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    run_ffmpeg(command, output_path, timeout=600)
    _, output_audio_codec, _, _, _ = probe_video(output_path)
    if not output_audio_codec:
        output_path.unlink(missing_ok=True)
        raise VideoProcessingError("FFmpeg output is missing its audio stream")

    if output_path.stat().st_size > MAX_MEDIA_SIZE::
    if output_path.stat().st_size > MAX_MEDIA_SIZE:
        output_path.unlink(missing_ok=True)
        raise InstagramMediaTooLarge

    return output_path


def create_video_thumbnail(file_path):
    try:
        stat = file_path.stat()
    except OSError:
        stat = None
    cache_key = (
        (file_path, stat.st_mtime, stat.st_size)
        if stat is not None
        else None
    )
    if cache_key in VIDEO_THUMBNAIL_CACHE:
        return VIDEO_THUMBNAIL_CACHE[cache_key]

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
        return store_in_cache(VIDEO_THUMBNAIL_CACHE, cache_key, None)

    return store_in_cache(VIDEO_THUMBNAIL_CACHE, cache_key, thumbnail_path)


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
                prepared_files.append(file_path)
                continue
            if converted_path != file_path:
                file_path.unlink(missing_ok=True)
            prepared_files.append(converted_path)
        else:
            prepared_files.append(file_path)

    return prepared_files


def collect_downloaded(output_dir, prefix, suffixes):
    return sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file()
        and path.name.startswith(prefix)
        and not path.name.endswith((".part", ".ytdl"))
        and path.suffix.lower() in suffixes
    )


def select_reel_media(candidates):
    videos = [path for path in candidates if probe_video(path)[0] is not None]
    if not videos:
        return []
    with_audio = [path for path in videos if probe_video(path)[1]]
    chosen = with_audio or videos
    return [max(chosen, key=lambda path: path.stat().st_size)]


def download_reel_with_audio(url, output_dir):
    options = {
        "outtmpl": str(output_dir / "reel_%(id)s.%(ext)s"),
        "format": "bestvideo+bestaudio/best",  # جلب أعلى دقة فيديو مع الصوت بدقة تامة
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "socket_timeout": 15,
    }

    for stale_file in output_dir.iterdir():
        if stale_file.is_file():
            stale_file.unlink(missing_ok=True)

    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as error:
        logger.error("فشل تحميل الرابط: %s", error)
        raise error

    media_files = select_reel_media(
        collect_downloaded(output_dir, "reel_", {".mp4", ".mkv", ".webm"})
    )

    if not media_files:
        raise InstagramDownloadError("لم يتم العثور على أي ملف فيديو قابل للتحميل")

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
        url_kind = get_url_kind(url)
        if url_kind == "reel":
            try:
                reel_files = download_reel_with_audio(url, output_dir)
                return output_dir, normalize_media_files(reel_files)
            except yt_dlp.utils.DownloadError:
                logger.warning("Falling back to direct Instagram reel URL", exc_info=True)

        loader = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            save_metadata=False,
            compress_json=False,
            post_metadata_txt_pattern="",
        )
        post = instaloader.Post.from_shortcode(loader.context, shortcode)

        if (
            url_kind == "post"
            and post.is_video
            and post.typename != "GraphSidecar"
        ):
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


def media_caption(index, total):
    return f"- @G66Gbot - {index}/{total}"


async def send_instagram_file(message, chat_id, context, file_path, index, total):
    is_video = is_video_file(file_path)
    caption = media_caption(index, total)

    if not is_video:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
        with file_path.open("rb") as media_file:
            sent_message = await message.reply_photo(photo=media_file, caption=caption)
        return [sent_message]

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
            sent_message = await message.reply_video(video=media_file, **video_arguments)
    finally:
        if thumbnail_file:
            thumbnail_file.close()
    return [sent_message]


async def send_instagram_album(message, context, media_files):
    total_files = len(media_files)
    sent_messages = []

    for start in range(0, total_files, 10):
        batch = media_files[start : start + 10]

        if len(batch) == 1:
            sent_messages.extend(
                await send_instagram_file(
                    message,
                    message.chat_id,
                    context,
                    batch[0],
                    start + 1,
                    total_files,
                )
            )
            continue

        open_files = []
        media_group = []
        try:
            for offset, file_path in enumerate(batch, start=1):
                media_file = file_path.open("rb")
                open_files.append(media_file)
                absolute_index = start + offset
                is_video = is_video_file(file_path)
                caption = (
                    media_caption(absolute_index, total_files)
                    if absolute_index == total_files
                    else None
                )

                if not is_video:
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

            sent_messages.extend(await message.reply_media_group(media=media_group))
        finally:
            for media_file in open_files:
                media_file.close()

    return sent_messages


def get_sent_media_id(message):
    video = getattr(message, "video", None)
    if video is not None and getattr(video, "file_id", None):
        return "video", video.file_id

    photos = getattr(message, "photo", None)
    if photos:
        file_id = getattr(photos[-1], "file_id", None)
        if file_id:
            return "photo", file_id

    return None


def cache_sent_media(shortcode, sent_messages):
    media_ids = [
        media_id
        for sent_message in sent_messages
        if (media_id := get_sent_media_id(sent_message)) is not None
    ]
    if len(media_ids) != len(sent_messages):
        return

    store_in_cache(MEDIA_ID_CACHE, shortcode, media_ids)


async def send_cached_media(message, context, media_ids):
    total_files = len(media_ids)
    await context.bot.send_chat_action(
        chat_id=message.chat_id,
        action=ChatAction.UPLOAD_PHOTO,
    )

    for start in range(0, total_files, 10):
        batch = media_ids[start : start + 10]
        if len(batch) == 1:
            kind, file_id = batch[0]
            caption = media_caption(start + 1, total_files)
            if kind == "photo":
                await message.reply_photo(photo=file_id, caption=caption)
            else:
                await message.reply_video(
                    video=file_id,
                    caption=caption,
                    supports_streaming=True,
                )
            continue

        media_group = []
        for offset, (kind, file_id) in enumerate(batch, start=1):
            absolute_index = start + offset
            caption = (
                media_caption(absolute_index, total_files)
                if absolute_index == total_files
                else None
            )
            if kind == "photo":
                media_group.append(InputMediaPhoto(media=file_id, caption=caption))
            else:
                media_group.append(
                    InputMediaVideo(
                        media=file_id,
                        caption=caption,
                        supports_streaming=True,
                    )
                )
        await message.reply_media_group(media=media_group)


async def handle_instagram_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    url = (update.message.text or "").strip()
    shortcode = get_shortcode(url)
    if not shortcode:
        return

    status_message = await update.message.reply_text(
        "⏰┇يرجى الانتظار، يتم التحميل بأعلى دقة..."
    )
    output_dir = None

    try:
        cached_media = MEDIA_ID_CACHE.get(shortcode)
        if cached_media is not None:
            await send_cached_media(update.message, context, cached_media)
            await status_message.delete()
            return

        output_dir, media_files = await asyncio.to_thread(download_instagram_media, url)
        
        action = ChatAction.UPLOAD_VIDEO if (media_files and is_video_file(media_files[0])) else ChatAction.UPLOAD_PHOTO

        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=action,
        )
        sent_messages = await send_instagram_album(
            update.message, context, media_files
        )
        cache_sent_media(shortcode, sent_messages)

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


log_media_tools_status()


