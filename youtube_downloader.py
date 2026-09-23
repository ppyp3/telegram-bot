import asyncio
import html
import json
import logging
import os
import re
import shutil
import tempfile
import traceback
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from pathlib import Path

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import filters

logger = logging.getLogger(__name__)

MAX_MEDIA_SIZE = 49 * 1024 * 1024
YOUTUBE_API_KEY_VARIABLE = "YOUTUBE_API_KEY"

MAX_CONCURRENT_DOWNLOADS = 2
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
USER_DOWNLOAD_LOCKS = {}

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
    match = YOUTUBE_REGEX.search(text or "")
    if not match:
        raise ValueError("Invalid YouTube URL")
    return match.group(0)

def get_youtube_video_id(url: str) -> str:
    match = YOUTUBE_REGEX.search(url)
    if not match:
        raise ValueError("Invalid YouTube URL")
    return match.group(5)

def parse_iso8601_duration(value: str) -> int:
    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?",
        value or "",
    )
    if not match:
        return 0
    parts = match.groupdict(default="0")
    return (
        int(parts["days"]) * 86400
        + int(parts["hours"]) * 3600
        + int(parts["minutes"]) * 60
        + int(parts["seconds"])
    )

def get_user_download_lock(user_id: int) -> asyncio.Lock:
    lock = USER_DOWNLOAD_LOCKS.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        USER_DOWNLOAD_LOCKS[user_id] = lock
    return lock

def format_views(views):
    if not views:
        return "0"
    if views >= 1_000_000:
        return f"{views / 1_000_000:.1f}M"
    if views >= 1_000:
        return f"{int(views / 1_000)}K"
    return str(views)

def get_youtube_info(url: str):
    api_key = os.getenv(YOUTUBE_API_KEY_VARIABLE)
    if not api_key:
        raise RuntimeError("YOUTUBE_API_KEY is not configured")

    query = urlencode(
        {
            "part": "snippet,contentDetails,statistics",
            "id": get_youtube_video_id(url),
            "key": api_key,
        }
    )
    request = Request(
        f"https://www.googleapis.com/youtube/v3/videos?{query}",
        headers={"Accept": "application/json"},
    )
    with urlopen(request, timeout=15) as response:
        payload = json.load(response)

    items = payload.get("items", [])
    if not items:
        raise ValueError("Video was not found or is not publicly available")

    item = items[0]
    snippet = item.get("snippet", {})
    thumbnails = snippet.get("thumbnails", {})
    thumbnail = next(
        (
            thumbnails[size].get("url")
            for size in ("maxres", "standard", "high", "medium", "default")
            if thumbnails.get(size, {}).get("url")
        ),
        None,
    )
    duration = parse_iso8601_duration(item.get("contentDetails", {}).get("duration", ""))
    minutes, seconds = divmod(duration, 60)

    return {
        "title": snippet.get("title") or "فيديو يوتيوب",
        "uploader": snippet.get("channelTitle")  or "غير معروف",
        "duration": duration,
        "duration_string": f"{minutes:02d}:{seconds:02d}",
        "view_count_formatted": format_views(int(item.get("statistics", {}).get("viewCount", 0))),
        "thumbnail": thumbnail,
        "url": url,
    }

def download_youtube_media(url: str, mode: str = "video"):
    format_type = "mp3" if mode in ["audio", "yt_audio", "yt_voice"] else "mp4"
    
    # الرابط المباشر الصحيح مع مسار api/json المتوافق مع إصدار v11.5
    api_url = "https://cobalt-production-5277.up.railway.app"
    
    payload = {
        "url": url,
        "vQuality": "720"
    }
    
    if format_type == "mp3":
        payload["audioFormat"] = "mp3"

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    temp_dir = tempfile.mkdtemp()
    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        res_data = response.json()
        
        status = res_data.get("status")
        if status not in ["stream", "redirect", "success"]:
            raise ValueError(f"فشل جلب الرابط من الخادم: {res_data}")
            
        direct_download_url = res_data.get("url")
        if not direct_download_url:
            raise ValueError("لم يتم العثور على رابط التحميل المباشر.")

        suffix = ".mp3" if format_type == "mp3" else ".mp4"
        file_path = Path(temp_dir) / f"media{suffix}"
        
        with requests.get(direct_download_url, stream=True, timeout=60) as media_resp:
            media_resp.raise_for_status()
            downloaded_size = 0
            
            with open(file_path, "wb") as f:
                for chunk in media_resp.iter_content(chunk_size=128 * 1024):
                    if chunk:
                        downloaded_size += len(chunk)
                        if downloaded_size > MAX_MEDIA_SIZE:
                            raise DownloadTooLarge("حجم الملف يتجاوز الحد المسموح.")
                        f.write(chunk)

        title = res_data.get("filename") or "فيديو يوتيوب"
        duration = 180  
        thumb_path = None

        return file_path, title, duration, thumb_path

    except Exception as e:
        print("=" * 40)
        print("❌ [DEBUG ERROR] حدث خطأ:")
        traceback.print_exc()
        print("=" * 40)
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
    user_id = session_data["user_id"]
    await query.answer()

    try:
        await query.message.delete()
    except Exception:
        pass

    status_msg = await context.bot.send_message(chat_id=chat_id, text="🔄 جاري التحميل، يرجى الانتظار...")
    file_path = None
    thumb_path = None

    try:
        async with get_user_download_lock(user_id):
            async with DOWNLOAD_SEMAPHORE:
                file_path, title, duration, thumb_path = await asyncio.to_thread(
                    download_youtube_media, url, mode
                )
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
                await context.bot.send_audio(
                    chat_id=chat_id, audio=audio_file, title=title, performer="@G66Gbot",
                    duration=int(duration),
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
