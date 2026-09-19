import os
import re
import tempfile
import asyncio
import logging
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

def format_views(views):
    if not views:
        return "0"
    if views >= 1_000_000:
        return f"{views / 1_000_000:.1f}M"
    elif views >= 1_000:
        return f"{int(views / 1_000)}K"
    return str(views)

def get_youtube_options(download=False, outtmpl=None):
    """إعدادات yt-dlp محصنة بكوكيز جلسة حسابك الكاملة لمنع الحظر"""
    
    sid_token = "g.a000CwkTGceaTSWVp9g8NdyNQ4zB-EmTTTT6eMk6FBv87o4x_XY8X9LdSgADScZACiP-edliMAACgYKAWISARQSFQHGX2MiZeRCMtav2cTXd57u1ufqjBoVAUF8yKqdWN5dIBArMSHOSxno_Wr_0076"
    login_info = "AFmmF2swRQIhAKWSpYjDL8f7GV2yFbFgC98Rwx4GWGo0wU9RRj9G4hjiAiBfolPLJDk55blSolU0zmieXhVeSIJvFyfbzjDb3wwFpQ:QUQ3MjNmenZYY25TbzVMZ2E0OTJzbFZDeFZkZjRYa01WZHhLZ2NNMmVqR196cGhTQjU5UFJfQUtrbVFLVHgtNGpDMEpJSVR4aER0YUx0eWZDckJDWXFMbjJlYmFPaHlkSktrTUNuMjFEOWlyZXEtbjNHWWYxWmNOQ2d5QTdEa0YtZ0dPTkV1aTZZVHU4aFoxSldreDJtV05FRzNUWEF3bnRn"
    sidcc_yt = "AKEyXzU07ZQ0OaVa-UUD_H-z2P4CG3K32M4fcpnABVUdTOX3fsNQgUo7XyWITmmmRW_-R1vL-Q"
    sidcc_google = "AKEyXzWtTFhPC-Lsx5RFCeUK1ZYjPiO38vT0Wo4yIBoMOAbNVVUZGSO6ccuRf8S0LYtA4PrJTw"

    cookies_str = (
        f"SID={sid_token}; "
        f"LOGIN_INFO={login_info}; "
        f"SIDCC={sidcc_yt}; "
        f"__Secure-1PSIDCC={sidcc_google}; "
        "HSID=ANO9NnOmEem-ItYpf; "
        "PREF=tz=Asia.Baghdad&f4=4000000; "
        "SAPISID=KmIE_qoMNytclrs-/AiIPreKYYGcCQyb69; "
        "SSID=AD4UIb9hQQfd2Itq7; "
        "VISITOR_INFO1_LIVE=mNVd4wf1pR0; "
        "YSC=BF5b20fDJPo;"
    )

    opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': not download,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Cookie': cookies_str,
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['web', 'tvhtml5', 'android'],
            }
        },
    }

    if outtmpl:
        opts['outtmpl'] = outtmpl
        opts['writethumbnail'] = True

    return opts

def get_youtube_info(url: str):
    ydl_opts = get_youtube_options(download=False)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                raise ValueError("Could not extract info")
                
            duration = info.get('duration', 0) or 0
            minutes, seconds = divmod(int(duration), 60)
            
            return {
                "title": info.get('title') or "فيديو يوتيوب",
                "uploader": info.get('uploader') or info.get('channel') or "غير معروف",
                "duration": duration,
                "duration_string": f"{minutes:02d}:{seconds:02d}",
                "view_count_formatted": format_views(info.get('view_count')),
                "thumbnail": info.get('thumbnail'),
                "url": url
            }
    except Exception:
        return {
            "title": "فيديو يوتيوب",
            "uploader": "غير معروف",
            "duration": 0,
            "duration_string": "00:00",
            "view_count_formatted": "0",
            "thumbnail": None,
            "url": url
        }

def download_youtube_media(url: str, mode: str = "video"):
    temp_dir = tempfile.mkdtemp()
    outtmpl = os.path.join(temp_dir, '%(title)s.%(ext)s')

    ydl_opts = get_youtube_options(download=True, outtmpl=outtmpl)
    ydl_opts['ignoreerrors'] = False

    if mode in ["audio", "yt_audio", "yt_voice"]:
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [
                {
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                },
                {
                    'key': 'FFmpegThumbnailsConvertor',
                    'format': 'jpg',
                }
            ],
        })
    else:
        # استخدام صيغة مرنة لضمان تحميل الفيديو بدون خطأ عدم توفر الصيغة
        ydl_opts.update({
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        })

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get('title', 'فيديو يوتيوب')
        duration = info.get('duration', 0)

        media_files = [p for p in Path(temp_dir).glob('*') if p.suffix.lower() in ['.mp3', '.mp4', '.m4a', '.webm', '.ogg']]
        if not media_files:
            raise FileNotFoundError("لم يتم العثور على الملف المحمل.")

        file_path = media_files[0]
        thumb_files = [p for p in Path(temp_dir).glob('*') if p.suffix.lower() in ['.jpg', '.jpeg', '.png']]
        thumb_path = thumb_files[0] if thumb_files else None

        # الفحص المرن لحجم الملف المحمل قبل الإرسال
        if file_path.stat().st_size > MAX_MEDIA_SIZE:
            file_path.unlink(missing_ok=True)
            raise DownloadTooLarge("حجم الملف يتجاوز الحد المسموح.")

        return file_path, title, duration, thumb_path

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
            "title": info["title"]
        }

        await processing_msg.delete()

    except Exception:
        logger.exception("Error handling YouTube message")
        await processing_msg.edit_text("❌ حدث خطأ أثناء معالجة رابط يوتيوب.")

async def handle_youtube_callback(query, context, session_data, mode):
    chat_id = query.message.chat_id
    url = session_data["url"]
    
    # إخفاء رسالة المعاينة والبطاقة الأصلية بمجرد الضغط على الزر
    try:
        await query.message.delete()
    except Exception:
        pass

    status_msg = await context.bot.send_message(chat_id=chat_id, text="🔄 جاري التحميل، يرجى الانتظار...")
    file_path = None
    thumb_path = None

    try:
        file_path, title, duration, thumb_path = await asyncio.to_thread(download_youtube_media, url, mode)

        # زر المشاركة المباشرة
        share_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔀 | شارك.", switch_inline_query=f"{title}")]
        ])

        # حساب صيغة الوقت والحجم
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
                thumb_file = open(thumb_path, 'rb') if thumb_path and os.path.exists(thumb_path) else None

                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=audio_file,
                    title=title,
                    performer="@G66Gbot",
                    duration=int(duration),
                    thumbnail=thumb_file,
                    caption=audio_caption,
                    reply_markup=share_keyboard
                )
                
                if thumb_file:
                    thumb_file.close()

        else:  # فيديو
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
            video_caption = f"@G66Gbot - {time_str}, {file_size_mb}"
            
            with open(file_path, 'rb') as video_file:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=video_file,
                    caption=video_caption,
                    duration=int(duration),
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
