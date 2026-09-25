import asyncio
import logging
import os
from pathlib import Path
import re
import tempfile

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import filters
import requests
import yt_dlp

logger = logging.getLogger(__name__)

# حد أقصى 49 ميغابايت
MAX_MEDIA_SIZE = 49 * 1024 * 1024

YOUTUBE_REGEX = re.compile(
    r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/(watch\?v=|shorts/|embed/)?([a-zA-Z0-9_-]+)'
)

COOKIES_FILE = "cookies.txt"


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
  match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration_str)
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
              "url": url,
          }
    except Exception:
      pass

  ydl_opts = {
      "quiet": True,
      "no_warnings": True,
      "skip_download": True,
      "nocheckcertificate": True,
      "geo_bypass": True,
      "extractor_args": {
          "youtube": {
              "player_client": ["android", "ios", "web"],
          }
      },
      "http_headers": {
          "User-Agent": (
              "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
              " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
          ),
      },
  }

  if os.path.exists(COOKIES_FILE):
    ydl_opts["cookiefile"] = COOKIES_FILE

  try:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
      info = ydl.extract_info(url, download=False)
      if not info:
        raise ValueError("Could not extract info")

      duration = info.get("duration", 0) or 0
      minutes, seconds = divmod(int(duration), 60)

      return {
          "title": info.get("title") or "فيديو يوتيوب",
          "uploader": info.get("uploader")
          or info.get("channel")
          or "غير معروف",
          "duration": duration,
          "duration_string": f"{minutes:02d}:{seconds:02d}",
          "view_count_formatted": format_views(info.get("view_count")),
          "thumbnail": info.get("thumbnail"),
          "url": url,
      }
  except Exception:
    return {
        "title": "فيديو يوتيوب",
        "uploader": "غير معروف",
        "duration": 0,
        "duration_string": "00:00",
        "view_count_formatted": "0",
        "thumbnail": None,
        "url": url,
    }


def check_media_size_before_download(url: str, mode: str = "video") -> bool:
  ydl_opts = {
      "quiet": True,
      "no_warnings": True,
      "skip_download": True,
      "nocheckcertificate": True,
      "geo_bypass": True,
      "extractor_args": {
          "youtube": {
              "player_client": ["android", "ios", "web"],
          }
      },
      "http_headers": {
          "User-Agent": (
              "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
              " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
          ),
      },
  }

  if os.path.exists(COOKIES_FILE):
    ydl_opts["cookiefile"] = COOKIES_FILE

  if mode in ["audio", "yt_audio", "yt_voice"]:
    ydl_opts["format"] = "bestaudio/best"
  else:
    ydl_opts["format"] = "best[ext=mp4]/best"

  try:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
      info = ydl.extract_info(url, download=False)
      if not info:
        return True

      filesize = info.get("filesize") or info.get("filesize_approx") or 0
      if filesize and filesize > MAX_MEDIA_SIZE:
        return False
  except Exception:
    pass
  return True


def download_youtube_media(url: str, mode: str = "video"):
  temp_dir = tempfile.mkdtemp()
  outtmpl = os.path.join(temp_dir, "%(title)s.%(ext)s")

  ydl_opts = {
      "outtmpl": outtmpl,
      "quiet": False,
      "no_warnings": False,
      "ignoreerrors": False,
      "nocheckcertificate": True,
      "geo_bypass": True,
      "writethumbnail": True,
      "extractor_args": {
          "youtube": {
              "player_client": ["android", "ios", "web"],
          }
      },
      "http_headers": {
          "User-Agent": (
              "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
              " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
          ),
      },
  }

  if os.path.exists(COOKIES_FILE):
    ydl_opts["cookiefile"] = COOKIES_FILE

  if mode == "yt_voice":
    ydl_opts.update({
        "format": "bestaudio/best",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "opus",
            "preferredquality": "128",
        }],
    })
  elif mode in ["audio", "yt_audio"]:
    ydl_opts.update({
        "format": "bestaudio/best",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            },
            {
                "key": "FFmpegThumbnailsConvertor",
                "format": "jpg",
            },
        ],
    })
  else:
    ydl_opts.update({
        "format": "best[ext=mp4]/best",
    })

  try:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
      info = ydl.extract_info(url, download=True)
      title = info.get("title", "فيديو يوتيوب")
      duration = info.get("duration", 0)

      media_files = [
          p
          for p in Path(temp_dir).glob("*")
          if p.suffix.lower()
          in [".mp3", ".mp4", ".m4a", ".webm", ".ogg", ".opus"]
      ]
      if not media_files:
        raise FileNotFoundError("لم يتم العثور على الملف المحمل.")

      file_path = media_files[0]
      thumb_files = [
          p
          for p in Path(temp_dir).glob("*")
          if p.suffix.lower() in [".jpg", ".jpeg", ".png"]
      ]
      thumb_path = thumb_files[0] if thumb_files else None

      if file_path.stat().st_size > MAX_MEDIA_SIZE:
        file_path.unlink(missing_ok=True)
        raise DownloadTooLarge("حجم الملف يتجاوز الحد المسموح.")

      return file_path, title, duration, thumb_path
  except Exception as e:
    logger.error(f"Detailed Download Error: {str(e)}")
    raise e


async def handle_youtube_message(update, context):
  url = update.message.text.strip()
  user_id = update.effective_user.id

  processing_msg = await update.message.reply_text(
      "⏰┇يرجى الانتظار، يتم قياس حجم التحميل..."
  )

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

    caption = (
        f'🎬 <a href="{info["url"]}">{info["title"]}</a>\n'
        f'👤 {info["uploader"]}\n'
        f'⏱ {info["duration_string"]} - 👁 {info["view_count_formatted"]}'
    )

    sent_msg = None
    if info["thumbnail"]:
      sent_msg = await update.message.reply_photo(
          photo=info["thumbnail"],
          caption=caption,
          parse_mode="HTML",
          reply_markup=reply_markup,
      )
    else:
      sent_msg = await update.message.reply_text(
          text=caption, parse_mode="HTML", reply_markup=reply_markup
      )

    sessions = context.application.bot_data.setdefault("yt_sessions", {})
    key = (sent_msg.chat_id, sent_msg.message_id)
    sessions[key] = {"user_id": user_id, "url": url, "title": info["title"]}

    await processing_msg.delete()

  except Exception:
    logger.exception("Error handling YouTube message")
    await processing_msg.edit_text("❌ حدث خطأ أثناء معالجة رابط يوتيوب.")


async def handle_youtube_callback(query, context, session_data, mode):
  chat_id = query.message.chat_id
  url = session_data["url"]

  try:
    await query.message.delete()
  except Exception:
    pass

  status_msg = await context.bot.send_message(
      chat_id=chat_id, text="♻️┇جاري التحميل..."
  )
  file_path = None
  thumb_path = None

  try:
    is_size_ok = await asyncio.to_thread(
        check_media_size_before_download, url, mode
    )
    if not is_size_ok:
      await status_msg.edit_text(
          "⚠️┇عذراً، هذا الملف كبير جداً ولا يمكن تحميله لأن حجمه يتجاوز ( 50"
          " MB )."
      )
      return

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
      await context.bot.send_chat_action(
          chat_id=chat_id, action=ChatAction.RECORD_VOICE
      )
      voice_caption = f"@G66Gbot - {time_str}"

      with open(file_path, "rb") as voice_file:
        await context.bot.send_voice(
            chat_id=chat_id,
            voice=voice_file,
            caption=voice_caption,
            duration=int(duration),
            reply_markup=share_keyboard,
        )

    elif mode == "yt_audio":
      await context.bot.send_chat_action(
          chat_id=chat_id, action=ChatAction.UPLOAD_VOICE
      )
      audio_caption = f"@G66Gbot - {time_str}, {file_size_mb}"

      with open(file_path, "rb") as audio_file:
        thumb_file = (
            open(thumb_path, "rb")
            if thumb_path and os.path.exists(thumb_path)
            else None
        )

        await context.bot.send_audio(
            chat_id=chat_id,
            audio=audio_file,
            title=title,
            performer="@G66Gbot",
            duration=int(duration),
            thumbnail=thumb_file,
            caption=audio_caption,
            reply_markup=share_keyboard,
        )

        if thumb_file:
          thumb_file.close()

    else:
      await context.bot.send_chat_action(
          chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO
      )
      video_caption = f"@G66Gbot - {time_str}, {file_size_mb}"

      with open(file_path, "rb") as video_file:
        await context.bot.send_video(
            chat_id=chat_id,
            video=video_file,
            caption=video_caption,
            duration=int(duration),
            reply_markup=share_keyboard,
        )

    await status_msg.delete()

  except DownloadTooLarge:
    await status_msg.edit_text(
        "⚠️┇هذا الملف لا يمكنني تحميله، لأن حجمه يتجاوز ( 50 MB )."
    )
  except Exception:
    logger.exception("Error in YouTube callback process")
    await status_msg.edit_text("❌ حدث خطأ أثناء التحميل.")
  finally:
    if file_path and os.path.exists(file_path):
      os.remove(file_path)
    if thumb_path and os.path.exists(thumb_path):
      os.remove(thumb_path)
 
