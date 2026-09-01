"""Telegram bot for downloading public TikTok media.

Environment variables:
  TOKEN     Telegram bot token (required)
  ADMIN_IDS Comma-separated Telegram administrator IDs (optional)
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import secrets
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Update,
)
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TOKEN")
ADMIN_IDS = {
    int(value)
    for value in os.getenv("ADMIN_IDS", "").split(",")
    if value.strip().isdigit()
}

TIKTOK_API_URL = "https://www.tikwm.com/api/"
MAX_DOWNLOAD_BYTES = 49 * 1024 * 1024
REQUEST_TIMEOUT = (8, 30)
CALLBACK_TTL_SECONDS = 20 * 60
USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
)


class TikTokFetchError(Exception):
    """The TikTok service did not return usable media."""


class DownloadTooLargeError(Exception):
    """The remote media is larger than Telegram's configured upload limit."""


@dataclass(frozen=True)
class TikTokMedia:
    title: str
    author: str
    music_url: str | None
    video_url: str | None
    images: tuple[str, ...]


@dataclass(frozen=True)
class DownloadRequest:
    owner_id: int
    url: str
    title: str
    created_at: float


def is_valid_tiktok_url(value: str) -> bool:
    """Accept only HTTPS links hosted by TikTok itself."""
    parsed = urlparse(value.strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme == "https" and (
        hostname == "tiktok.com" or hostname.endswith(".tiktok.com")
    )


def is_http_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def request_headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
    }


def fetch_tiktok_data(url: str) -> TikTokMedia:
    """Fetch metadata from TikWM. This synchronous function runs in a worker thread."""
    headers = request_headers()
    resolved_url = url

    try:
        if urlparse(url).hostname in {"vm.tiktok.com", "vt.tiktok.com"}:
            response = requests.get(
                url,
                allow_redirects=True,
                timeout=REQUEST_TIMEOUT,
                headers=headers,
            )
            response.raise_for_status()
            resolved_url = response.url
            response.close()

        if not is_valid_tiktok_url(resolved_url):
            raise TikTokFetchError("TikTok redirected to an unsupported address")

        response = requests.get(
            TIKTOK_API_URL,
            params={"url": resolved_url, "music": "1"},
            timeout=REQUEST_TIMEOUT,
            headers=headers,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        response.close()
    except (requests.RequestException, ValueError) as error:
        raise TikTokFetchError("Could not retrieve TikTok metadata") from error

    if payload.get("code") != 0 or not isinstance(payload.get("data"), dict):
        raise TikTokFetchError("TikTok service returned no media")

    data: dict[str, Any] = payload["data"]
    author = data.get("author") if isinstance(data.get("author"), dict) else {}
    images = tuple(item for item in data.get("images", []) if is_http_url(item))
    music_url = data.get("music") if is_http_url(data.get("music")) else None
    video_url = data.get("play") if is_http_url(data.get("play")) else None

    if not (images or music_url or video_url):
        raise TikTokFetchError("TikTok response did not contain downloadable media")

    return TikTokMedia(
        title=str(data.get("title") or "محتوى تيك توك")[:200],
        author=str(author.get("nickname") or "مستخدم تيك توك")[:100],
        music_url=music_url,
        video_url=video_url,
        images=images,
    )


def download_to_tempfile(url: str, suffix: str) -> Path:
    """Stream a remote file to a unique temporary file while enforcing a size limit."""
    response: requests.Response | None = None
    temporary_path: Path | None = None

    try:
        response = requests.get(
            url,
            headers=request_headers(),
            timeout=REQUEST_TIMEOUT,
            stream=True,
        )
        response.raise_for_status()

        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_DOWNLOAD_BYTES:
            raise DownloadTooLargeError

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temporary_file:
            temporary_path = Path(temporary_file.name)
            downloaded = 0
            for chunk in response.iter_content(chunk_size=128 * 1024):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > MAX_DOWNLOAD_BYTES:
                    raise DownloadTooLargeError
                temporary_file.write(chunk)

        return temporary_path
    except ValueError as error:
        raise TikTokFetchError("Invalid media size header") from error
    except requests.RequestException as error:
        raise TikTokFetchError("Unable to download media") from error
    except Exception:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)
        raise
    finally:
        if response is not None:
            response.close()


async def delete_quietly(message: Any) -> None:
    try:
        await message.delete()
    except TelegramError:
        logger.debug("Could not delete Telegram status message", exc_info=True)


def store_download_request(
    context: ContextTypes.DEFAULT_TYPE, user_id: int, url: str, title: str
) -> str:
    """Store a short-lived request so callback buttons are tied to their creator."""
    requests_by_id: dict[str, DownloadRequest] = context.application.bot_data.setdefault(
        "download_requests", {}
    )
    now = time.monotonic()
    expired_ids = [
        request_id
        for request_id, request in requests_by_id.items()
        if now - request.created_at > CALLBACK_TTL_SECONDS
    ]
    for request_id in expired_ids:
        requests_by_id.pop(request_id, None)

    request_id = secrets.token_urlsafe(8)
    requests_by_id[request_id] = DownloadRequest(user_id, url, title, now)
    return request_id


def download_keyboard(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎵 تحميل الصوت", callback_data=f"audio:{request_id}")],
            [InlineKeyboardButton("📥 تحميل الفيديو HD", callback_data=f"video:{request_id}")],
        ]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    name = update.effective_user.first_name or "صديقنا"
    await update.message.reply_text(
        f"أهلًا {name} 👋\n\nأرسل رابط فيديو أو صور من TikTok للبدء."
    )


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ هذا الأمر مخصص للمشرفين فقط.")
        return
    await update.message.reply_text(
        "لوحة الإدارة مفعّلة.\n"
        "هذه النسخة لا تعرض أزرار الإذاعة أو الإحصاءات لأنها تحتاج تخزينًا دائمًا للمستخدمين."
    )


async def send_audio(
    message: Any, chat_id: int, context: ContextTypes.DEFAULT_TYPE, media_url: str, title: str
) -> None:
    path = await asyncio.to_thread(download_to_tempfile, media_url, ".mp3")
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VOICE)
        with path.open("rb") as audio_file:
            await message.reply_audio(
                audio=audio_file,
                title=title,
                performer="TikTok",
                caption="تم التحميل من TikTok",
            )
    finally:
        path.unlink(missing_ok=True)


async def send_video(
    message: Any, chat_id: int, context: ContextTypes.DEFAULT_TYPE, media_url: str, title: str
) -> None:
    path = await asyncio.to_thread(download_to_tempfile, media_url, ".mp4")
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
        with path.open("rb") as video_file:
            await message.reply_video(
                video=video_file,
                caption=title,
                supports_streaming=True,
            )
    finally:
        path.unlink(missing_ok=True)


async def send_images(message: Any, chat_id: int, context: ContextTypes.DEFAULT_TYPE, images: tuple[str, ...]) -> None:
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
    total = len(images)
    for first in range(0, total, 10):
        batch = images[first : first + 10]
        media = [
            InputMediaPhoto(
                media=image_url,
                caption=f"TikTok • {first + index + 1}/{total}" if first + index + 1 == total else None,
            )
            for index, image_url in enumerate(batch)
        ]
        await message.reply_media_group(media=media)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not update.effective_chat:
        return

    url = (update.message.text or "").strip()
    if not is_valid_tiktok_url(url):
        await update.message.reply_text("❌ أرسل رابط TikTok صحيحًا يبدأ بـ https://")
        return

    status = await update.message.reply_text("⏳ جارِ فحص الرابط...")
    try:
        media = await asyncio.to_thread(fetch_tiktok_data, url)

        if media.images:
            if media.music_url:
                await send_audio(
                    update.message,
                    update.effective_chat.id,
                    context,
                    media.music_url,
                    media.title,
                )
            await send_images(update.message, update.effective_chat.id, context, media.images)
            await delete_quietly(status)
            return

        request_id = store_download_request(
            context, update.effective_user.id, url, media.title
        )
        await status.edit_text(
            f"✅ {media.title}\nاختر نوع التحميل:",
            reply_markup=download_keyboard(request_id),
        )
    except DownloadTooLargeError:
        await status.edit_text("⚠️ حجم الملف أكبر من الحد المسموح لإرساله عبر البوت.")
    except (TikTokFetchError, TelegramError):
        logger.exception("Unable to process TikTok URL")
        await status.edit_text("❌ تعذر جلب هذا الرابط. تأكد أنه عام ثم أعد المحاولة.")
    except Exception:
        logger.exception("Unexpected error while processing TikTok URL")
        await status.edit_text("❌ حدث خطأ غير متوقع. حاول مرة أخرى لاحقًا.")


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message or not query.from_user:
        return

    action, separator, request_id = (query.data or "").partition(":")
    requests_by_id: dict[str, DownloadRequest] = context.application.bot_data.setdefault(
        "download_requests", {}
    )
    request = requests_by_id.get(request_id) if separator else None

    if not request or time.monotonic() - request.created_at > CALLBACK_TTL_SECONDS:
        requests_by_id.pop(request_id, None)
        await query.answer("انتهت صلاحية هذا الطلب. أرسل الرابط مجددًا.", show_alert=True)
        return
    if query.from_user.id != request.owner_id:
        await query.answer("هذه الأزرار مخصصة لصاحب الطلب.", show_alert=True)
        return

    requests_by_id.pop(request_id, None)
    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError:
        logger.debug("Could not remove download buttons", exc_info=True)

    status = await query.message.reply_text("⏳ جارِ تنزيل الملف...")
    try:
        media = await asyncio.to_thread(fetch_tiktok_data, request.url)
        chat_id = query.message.chat_id
        if action == "audio" and media.music_url:
            await send_audio(query.message, chat_id, context, media.music_url, request.title)
        elif action == "video" and media.video_url:
            await send_video(query.message, chat_id, context, media.video_url, request.title)
        else:
            raise TikTokFetchError("Requested media type is unavailable")
        await delete_quietly(status)
    except DownloadTooLargeError:
        await status.edit_text("⚠️ حجم الملف أكبر من الحد المسموح لإرساله عبر البوت.")
    except (TikTokFetchError, TelegramError):
        logger.exception("Unable to send TikTok media")
        await status.edit_text("❌ تعذر تنزيل الملف أو إرساله. حاول لاحقًا.")
    except Exception:
        logger.exception("Unexpected callback error")
        await status.edit_text("❌ حدث خطأ غير متوقع. حاول مرة أخرى لاحقًا.")


def main() -> None:
    if not TOKEN:
        raise RuntimeError("Set the TOKEN environment variable before starting the bot.")

    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback, pattern=r"^(audio|video):"))

    logger.info("TikTok bot is running")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
