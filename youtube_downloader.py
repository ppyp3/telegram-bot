import os
import re
import tempfile
import asyncio
import logging
from pathlib import Path
import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import filters

logger = logging.getLogger(__name__)

# حد أقصى 49 ميغابايت
MAX_MEDIA_SIZE = 49 * 1024 * 1024

YOUTUBE_REGEX = re.compile(
    r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/(watch\?v=|shorts/|embed/)?([a-zA-Z0-9_-]+)'
)

class DownloadTooLarge(Exception):
    pass

class YoutubeFilter(filters.MessageFilter):
    def filter(self, message):
        text = message.text or message.caption or ""
        return bool(YOUTUBE_REGEX.search(text.strip()))

YOUTUBE_FILTER = YoutubeFilter()

def format_views(views):
    if not views:
        return "0"
    if views >= 1_000_000:
        return f"{views / 1_000_000:.1f}M"
    elif views >= 1_000:
        return f"{int(views / 1_000)}K"
    return str(views)

def parse_iso8601_duration(duration_str):
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
    if not match:
        return 0, "00:00"
    hours = int(match.group(1)) if match.group(1) else 0
    minutes = int(match.group(2)) if match.group(2) else 0
    seconds = int(match.group(3)) if match.group(3) else 0
    
    total_seconds = hours * 3600 + minutes * 60 + seconds
    if hours > 0:
        time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        time_str = f"{minutes:02d}:{seconds:02d}"
        
    return total_seconds, time_str

def get_youtube_info(url: str):
    """جلب معلومات المعاينة حصرياً عبر Google YouTube API"""
    video_id = None
    if "youtu.be/" in url:
        video_id = url.split("youtu.be/")[1].split("?")[0]
    elif "watch?v=" in url:
        video_id = url.split("watch?v=")[1].split("&")[0]
    elif "shorts/" in url:
        video_id = url.split("shorts/")[1].split("?")[0]

    api_key = os.environ.get("YOUTUBE_API_KEY")

    if video_id and api_key:
        try:
            api_url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet,contentDetails,statistics&id={video_id}&key={api_key}"
            response = requests.get(api_url, timeout=5)
            if response.status_code == 200:
                items = response.json().get("items", [])
                if items:
                    item = items[0]
                    snippet = item.get("snippet", {})
                    statistics = item.get("statistics", {})
                    content_details = item.get("contentDetails", {})
                    
                    title = snippet.get("title", "فيديو يوتيوب")
                    uploader = snippet.get("channelTitle", "غير معروف")
                    
                    thumbnails = snippet.get("thumbnails", {})
                    thumb_url = (
                        thumbnails.get("maxres", {}).get("url")
                        or thumbnails.get("high", {}).get("url")
                        or thumbnails.get("medium", {}).get("url")
                        or thumbnails.get("default", {}).get("url")
                    )
                    
                    view_count = int(statistics.get("viewCount", 0))
                    raw_duration = content_details.get("duration", "PT0S")
                    duration, duration_string = parse_iso8601_duration(raw_duration)
                    
                    return {
                        "title": title,
                        "uploader": uploader,
                        "duration": duration,
                        "duration_string": duration_string,
                        "view_count_formatted": format_views(view_count),
                        "thumbnail": thumb_url,
                        "url": url
                    }
        except Exception:
            pass

    return {
        "title": "فيديو يوتيوب",
        "uploader": "غير معروف",
        "duration": 0,
        "duration_string": "00:00",
        "view_count_formatted": "0",
        "thumbnail": None,
        "url": url
    }

def download_via_cobalt(url: str, mode: str = "video"):
    """التحميل الفعلي عبر Cobalt API لتجاوز الحظر نهائياً"""
    api_url = "https://api.cobalt.tools/api/json"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    payload = {
        "url": url,
        "vQuality": "720"
    }
    
    if mode in ["audio", "yt_audio", "yt_voice"]:
        payload["isAudioOnly"] = True
        payload["audioFormat"] = "mp3"

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=20)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") in ["stream", "redirect", "success"]:
                return data.get("url"), data.get("filename", "media.mp4")
            elif data.get("status") == "picker":
                picker_items = data.get("picker", [])
                if picker_items:
                    return picker_items[0].get("url"), "media.mp4"
    except Exception as e:
        logger.error(f"Cobalt API error: {e}")
        
    return None, None

def download_youtube_media(url: str, mode: str = "video"):
    temp_dir = tempfile.mkdtemp()
    
    download_url, filename = download_via_cobalt(url, mode)
    if not download_url:
        raise Exception("فشل جلب رابط التحميل من السيرفر الخارجي.")
    
    file_path = os.path.join(temp_dir, filename)
    
    with requests.get(download_url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(file_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    
    if os.path.getsize(file_path) > MAX_MEDIA_SIZE:
        os.remove(file_path)
        raise DownloadTooLarge("حجم الملف يتجاوز الحد المسموح.")
        
    return Path(file_path), "فيديو يوتيوب", 0

async def handle_youtube_message(update, context):
    url = update.message.text.strip()
    user_id = update.effective_user.id

    processing_msg = await update.message.reply_text("⏰┇يرجى الانتظار، جاري جلب المعاينة...")

    try:
        info = await asyncio.to_thread(get_youtube_info, url)

        keyboard = [
            [InlineKeyboardButton("🎬 فيديو", callback_data="yt_video")],
            [
                InlineKeyboardButton("🎧 ملف صوتي", callback_data="yt_audio"),
                InlineKeyboardButton("🎙 بصمة صوتية", callback_data="yt_voice")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        caption = (
            f'🎬 <a href="{info["url"]}">{info["title"]}</a>\n'
            f'👤 {info["uploader"]}\n'
            f'⏱ {info["duration_string"]} - 👁 {info["view_count_formatted"]}'
        )

        sent_msg = None
        if info['thumbnail']:
            sent_msg = await update.message.reply_photo(
                photo=info['thumbnail'],
                caption=caption,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        else:
            sent_msg = await update.message.reply_text(
                text=caption,
                parse_mode="HTML",
                reply_markup=reply_markup
            )

        sessions = context.application.bot_data.setdefault("yt_sessions", {})
        key = (sent_msg.chat_id, sent_msg.message_id)
        sessions[key] = {
            "user_id": user_id,
            "url": url,
            "title": info["title"]
        }

        await processing_msg.delete()

    except Exception:
        logger.exception("Error handling YouTube message")
        await processing_msg.edit_text("❌ حدث خطأ أثناء جلب المعاينة.")

async def handle_youtube_callback(query, context, session_data, mode):
    chat_id = query.message.chat_id
    url = session_data["url"]
    
    try:
        await query.message.delete()
    except Exception:
        pass

    status_msg = await context.bot.send_message(chat_id=chat_id, text="🔄 جاري التحميل بالطريقة القوية، يرجى الانتظار...")
    file_path = None

    try:
        file_path, title, duration = await asyncio.to_thread(download_youtube_media, url, mode)

        share_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔀 | شارك.", switch_inline_query="فيديو يوتيوب")]
        ])

        file_size_mb = f"{os.path.getsize(file_path) / (1024 * 1024):.1f}MB"

        if mode == "yt_voice":
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
            with open(file_path, 'rb') as voice_file:
                await context.bot.send_voice(chat_id=chat_id, voice=voice_file, caption=f"@G66Gbot", reply_markup=share_keyboard)

        elif mode in ["audio", "yt_audio"]:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VOICE)
            with open(file_path, 'rb') as audio_file:
                await context.bot.send_audio(chat_id=chat_id, audio=audio_file, title=session_data["title"], performer="@G66Gbot", caption=f"@G66Gbot - {file_size_mb}", reply_markup=share_keyboard)

        else:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
            with open(file_path, 'rb') as video_file:
                await context.bot.send_video(chat_id=chat_id, video=video_file, caption=f"@G66Gbot - {file_size_mb}", reply_markup=share_keyboard)

        await status_msg.delete()

    except DownloadTooLarge:
        await status_msg.edit_text("⚠️┇هذا الملف لا يمكنني تحميله، لأن حجمه يتجاوز ( 50 MB ).")
    except Exception:
        logger.exception("Error in YouTube download process")
        await status_msg.edit_text("❌ حدث خطأ أثناء التحميل.")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
 
