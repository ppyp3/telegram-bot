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
        "aac",
        "-b:a",
        "128k",
        "-map",
        "0:v:0?",
        "-map",
        "0:a:0",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    run_ffmpeg(command, output_path, timeout=600)
    _, output_audio_codec, _, _, _ = probe_video(output_path)
    if not output_audio_codec:
        output_path.unlink(missing_ok=True)
        raise VideoProcessingError("FFmpeg output is missing its audio stream")

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


def download_instagram_media_with_audio(url):
    shortcode = get_shortcode(url)
    if not shortcode:
        raise InstagramDownloadError("Invalid Instagram URL")

    output_dir = Path(tempfile.mkdtemp(prefix="instagram_media_"))
    post_caption = ""
    audio_file_path = None

    try:
        # استخدام yt_dlp لسحب الوسائط والأغنية المرفقة (سواء بوست صور مع أغنية أو ريلز)
        options = {
            "outtmpl": str(output_dir / "media_%(id)s.%(ext)s"),
            "format": "bestvideo+bestaudio/best/best",
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 15,
        }

        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(url, download=True)
                if info:
                    post_caption = (info.get("description") or info.get("title") or "").strip()
        except Exception:
            pass

        # استخدام Instaloader لضمان جلب كافة صور الألبوم (Sidecar) والوصف بدقة
        loader = instaloader.Instaloader(
            download_pictures=True,
            download_videos=True,
            download_video_thumbnails=False,
            save_metadata=False,
            compress_json=False,
            post_metadata_txt_pattern="",
        )
        post = instaloader.Post.from_shortcode(loader.context, shortcode)
        if post.caption and not post_caption:
            post_caption = post.caption.strip()

        if post.typename == "GraphSidecar":
            for index, node in enumerate(post.get_sidecar_nodes(), start=1):
                media_url = node.video_url if node.is_video else node.display_url
                if media_url:
                    suffix = ".mp4" if node.is_video else ".jpg"
                    out_path = output_dir / f"sidecar_{index:03d}{suffix}"
                    if not out_path.exists():
                        download_file(media_url, out_path)
        else:
            media_url = post.video_url if post.is_video else post.url
            if media_url:
                suffix = ".mp4" if post.is_video else ".jpg"
                out_path = output_dir / f"single_001{suffix}"
                if not out_path.exists():
                    download_file(media_url, out_path)

        # جمع الملفات المصنفة
        all_files = sorted([p for p in output_dir.iterdir() if p.is_file() and p.suffix.lower() in {".mp4", ".jpg", ".jpeg", ".png", ".webm", ".m4a", ".mp3"}])
        
        media_files = []
        for path in all_files:
            _, a_codec, _, _, duration = probe_video(path)
            # إذا كان هناك ملف صوتي منفصل للأغنية
            if path.suffix.lower() in {".m4a", ".mp3"} or (a_codec and not is_video_file(path) and duration and duration < 120):
                audio_file_path = path
            else:
                media_files.append(path)

        # استخراج الصوت من أول فيديو أو من ملف yt_dlp إذا لم يتم العثور على ملف صوتي مستقل
        if not audio_file_path:
            for path in media_files:
                if is_video_file(path):
                    _, a_codec, _, _, _ = probe_video(path)
                    if a_codec and a_codec != UNKNOWN_CODEC:
                        extracted_audio = output_dir / f"{path.stem}_audio.m4a"
                        cmd = ["ffmpeg", "-y", "-i", str(path), "-vn", "-acodec", "copy", str(extracted_audio)]
                        try:
                            subprocess.run(cmd, capture_output=True, timeout=30, check=True)
                            if extracted_audio.exists():
                                audio_file_path = extracted_audio
                                break
                        except Exception:
                            pass

        return output_dir, media_files, audio_file_path, post_caption

    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


def media_caption(index, total):
    return f"- @G66GBOT - {index}/{total}"


async def handle_instagram_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    url = (update.message.text or "").strip()
    shortcode = get_shortcode(url)
    if not shortcode:
        return

    status_message = await update.message.reply_text("♻️┇جاري التحميل...")
    output_dir = None

    try:
        output_dir, media_files, audio_file_path, post_caption = await asyncio.to_thread(
            download_instagram_media_with_audio, url
        )

        if not media_files and not audio_file_path:
            await status_message.edit_text("❌ لم يتم العثور على وسائط قابلة للتحميل.")
            return

        title_text = post_caption.split("\n")[0][:60] if post_caption else "محتوى انستغرام"
        bot_signature = "- @G66GBOT"

        # 1. إرسال الأغنية أولاً كملف صوتي تماماً مثل تيك توك
        if audio_file_path and audio_file_path.exists():
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VOICE)
            with audio_file_path.open("rb") as audio_f:
                await update.message.reply_audio(
                    audio=audio_f,
                    title=title_text,
                    caption=f"{post_caption}\n\n{bot_signature}" if post_caption else bot_signature
                )

        # 2. إرسال ألبوم الصور أو الوسائط بعدها بدون أي أزرار
        total_files = len(media_files)
        if total_files > 0:
            prepared_media = normalize_media_files(media_files)
            for start in range(0, total_files, 10):
                batch = prepared_media[start : start + 10]

                if len(batch) == 1:
                    file_path = batch[0]
                    caption = media_caption(start + 1, total_files)
                    if is_video_file(file_path):
                        with file_path.open("rb") as vf:
                            await update.message.reply_video(video=vf, caption=caption, supports_streaming=True)
                    else:
                        with file_path.open("rb") as pf:
                            await update.message.reply_photo(photo=pf, caption=caption)
                    continue

                open_files = []
                media_group = []
                try:
                    for offset, file_path in enumerate(batch, start=1):
                        media_file = file_path.open("rb")
                        open_files.append(media_file)
                        absolute_index = start + offset
                        caption = media_caption(absolute_index, total_files) if absolute_index == total_files else None

                        if not is_video_file(file_path):
                            media_group.append(InputMediaPhoto(media=media_file, caption=caption))
                        else:
                            _, _, width, height, duration = await asyncio.to_thread(probe_video, file_path)
                            media_group.append(
                                InputMediaVideo(
                                    media=media_file,
                                    caption=caption,
                                    supports_streaming=True,
                                    width=width,
                                    height=height,
                                    duration=duration,
                                )
                            )

                    await update.message.reply_media_group(media=media_group)
                finally:
                    for f in open_files:
                        f.close()

        await status_message.delete()
    except Exception:
        logger.exception("Instagram download with audio failed")
        await status_message.edit_text("❌ تعذر تحميل هذا الرابط. تأكد أن الحساب عام ثم أعد المحاولة.")
    finally:
        if output_dir:
            await asyncio.to_thread(shutil.rmtree, output_dir, True)


log_media_tools_status()
 
