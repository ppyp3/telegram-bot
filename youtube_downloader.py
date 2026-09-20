import os
import re
import sys
import tempfile
import asyncio
import logging
import requests
from pathlib import Path
import yt_dlp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import filters

logger = logging.getLogger(__name__)

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

def is_valid_youtube_url(url: str) -> bool:
    if not url:
        return False
    return bool(YOUTUBE_REGEX.search(url.strip()))

def get_youtube_info(url: str):
    """
    جلب معلومات الفيديو عبر عدة مصادر API بديلة لضمان عدم حدوث أي حظر أو توقف
    """
    # المصدر الأول
    try:
        api_url = "https://apis.davidcyriltech.my.id/youtube/mp4"
        response = requests.get(api_url, params={"url": url}, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") == 200 or data.get("success") == True or "result" in data:
            res = data.get("result", data)
            return {
                "title": res.get("title", "فيديو يوتيوب"),
                "uploader": res.get("author", res.get("channel", "غير معروف")),
                "duration": 180,
                "duration_string": res.get("duration", "03:00"),
                "view_count_formatted": "1K",
                "thumbnail": res.get("thumbnail", res.get("image", "")),
                "url": url,
                "direct_download_url": res.get("download_url", res.get("dl_url", res.get("url", "")))
            }
    except Exception:
        pass

    # المصدر الثاني الاحتياطي
    try:
        backup_api = f"https://kaiz-apis.gleeze.com/api/ytdl?url={url}"
        resp = requests.get(backup_api, timeout=10)
        resp.raise_for_status()
        res = resp.json()
        dl_url = res.get("downloadUrl", res.get("url", ""))
        if dl_url:
            return {
                "title": res.get("title", "فيديو يوتيوب"),
                "uploader": res.get("channel", "غير معروف"),
                "duration": 180,
                "duration_string": res.get("duration", "03:00"),
                "view_count_formatted": "1K",
                "thumbnail": res.get("thumbnail", ""),
                "url": url,
                "direct_download_url": dl_url
            }
    except Exception:
        pass

    # المصدر الثالث الاحتياطي (عبر yt-dlp بدون بروكسي مبدئياً)
    try:
        ydl_opts = {'quiet': True, 'no_warnings': True, 'skip_download': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                duration = info.get('duration', 0) or 0
                minutes, seconds = divmod(int(duration), 60)
                return {
                    "title": info.get('title') or "فيديو يوتيوب",
                    "uploader": info.get('uploader') or info.get('channel') or "غير معروف",
                    "duration": duration,
                    "duration_string": f"{minutes:02d}:{seconds:02d}",
                    "view_count_formatted": "1K",
                    "thumbnail": info.get('thumbnail'),
                    "url": url,
                    "direct_download_url": None
                }
    except Exception:
        pass

    return {
        "title": "فيديو يوتيوب",
        "uploader": "قناة يوتيوب",
        "duration": 180,
        "duration_string": "03:00",
        "view_count_formatted": "1K",
        "thumbnail": None,
        "url": url,
        "direct_download_url": None
    }

def download_youtube_media(url: str, mode: str = "video", direct_url: str = None):
    temp_dir = tempfile.mkdtemp()
    
    # تحميل مباشر من الرابط إن توفر
    if direct_url:
        try:
            r = requests.get(direct_url, stream=True, timeout=30)
            r.raise_for_status()
            ext = "mp3" if mode in ["audio", "yt_audio", "yt_voice"] else "mp4"
            file_path = Path(temp_dir) / f"media.{ext}"
            
            with open(file_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            if file_path.stat().st_size > MAX_MEDIA_SIZE:
                file_path.unlink(missing_ok=True)
                raise DownloadTooLarge("حجم الملف يتجاوز الحد المسموح.")
                
            return file_path, "فيديو يوتيوب", 180, None
        except Exception:
            pass

    # الطريقة الاحتياطية باستخدام yt-dlp مع البروكسي الخاص بك
    proxy_url = "http://6ll22fgrjd4i:f5lf2f8bsp73ghd@195.63.31.50:3129"
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'proxy': proxy_url,
        'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
    }

    if mode in ["audio", "yt_audio", "yt_voice"]:
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
        })
    else:
        ydl_opts.update({
            'format': 'best[ext=mp4]/best',
        })

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get('title', 'فيديو يوتيوب')
        duration = info.get('duration', 0)

        media_files = [p for p in Path(temp_dir).glob('*') if p.suffix.lower() in ['.mp3', '.mp4', '.m4a', '.webm', '.ogg']]
        if not media_files:
            raise FileNotFoundError("لم يتم العثور على الملف المحمل.")

        file_path = media_files[0]
        if file_path.stat().st_size > MAX_MEDIA_SIZE:
            file_path.unlink(missing_ok=True)
            raise DownloadTooLarge("حجم الملف يتجاوز الحد المسموح.")

        return file_path, title, duration, None

async def handle_youtube_message(update, context):
    url = update.message.text.strip()
    user_id = update.effective_user.id

    processing_msg = await update.message.reply_text("⏰┇يرجى الانتظار، جاري معالجة رابط يوتيوب...")

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
            "title": info["title"],
            "direct_download_url": info.get("direct_download_url")
        }

        await processing_msg.delete()

    except Exception:
        logger.exception("Error handling YouTube message")
        await processing_msg.edit_text("❌ حدث خطأ أثناء معالجة رابط يوتيوب.")

async def handle_youtube_callback(query, context, session_data, mode):
    chat_id = query.message.chat_id
    url = session_data["url"]
    direct_url = session_data.get("direct_download_url")
    
    try:
        await query.message.delete()
    except Exception:
        pass

    status_msg = await context.bot.send_message(chat_id=chat_id, text="🔄 جاري التحميل، يرجى الانتظار...")
    file_path = None
    thumb_path = None

    try:
        file_path, title, duration, thumb_path = await asyncio.to_thread(download_youtube_media, url, mode, direct_url)

        share_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔀 | شارك.", switch_inline_query=f"{title}")]
        ])

        file_size_mb = f"{os.path.getsize(file_path) / (1024 * 1024):.1f}MB"
        minutes, seconds = divmod(int(duration), 60)
        time_str = f"{minutes:02d}:{seconds:02d}"

        if mode == "yt_voice":
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
            voice_caption = f"@G66Gbot - {time_str}"
            
            with open(file_path, 'rb') as voice_file:
                await context.bot.send_voice(
                    chat_id=chat_id,
                    voice=voice_file,
                    caption=voice_caption,
                    duration=int(duration),
                    reply_markup=share_keyboard
                )

        elif mode == "yt_audio":
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VOICE)
            audio_caption = f"@G66Gbot - {time_str}, {file_size_mb}"
            
            with open(file_path, 'rb') as audio_file:
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=audio_file,
                    title=title,
                    performer="@G66Gbot",
                    duration=int(duration),
                    caption=audio_caption,
                    reply_markup=share_keyboard
                )

        else:  # فيديو MP4
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
            video_caption = f"@G66Gbot - {time_str}, {file_size_mb}"
            
            with open(file_path, 'rb') as video_file:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=video_file,
                    caption=video_caption,
                    duration=int(duration),
                    supports_streaming=True,
                    reply_markup=share_keyboard
                )

        await status_msg.delete()

    except DownloadTooLarge:
        await status_msg.edit_text("⚠️┇هذا الملف لا يمكنني تحميله، لأن حجمه يتجاوز ( 50 MB ).")
    except Exception:
        logger.exception("Error in YouTube callback process")
        await status_msg.edit_text("❌ حدث خطأ أثناء التحميل.")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        if thumb_path and os.path.exists(thumb_path):
            os.remove(thumb_path)
