import logging
import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# فلتر لالتقاط روابط يوتيوب بمختلف أنواعها
def is_valid_youtube_url(url: str) -> bool:
    if not url:
        return False
    u = url.strip()
    return "youtube.com" in u or "youtu.be" in u

from telegram.ext import filters
YOUTUBE_FILTER = filters.TEXT & ~filters.COMMAND & filters.Regex(r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/')

def fetch_youtube_data(url: str):
    """
    جلب بيانات يوتيوب عبر API خارجي مستقر وآمن
    """
    try:
        api_url = "https://apis.davidcyriltech.my.id/youtube/mp4"
        params = {"url": url}
        
        response = requests.get(api_url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") == 200 or data.get("success") == True or "result" in data:
            res = data.get("result", data)
            return {
                "title": res.get("title", "فيديو يوتيوب"),
                "duration": res.get("duration", "غير معروف"),
                "author": res.get("author", res.get("channel", "يوتيوب")),
                "thumbnail": res.get("thumbnail", res.get("image", "")),
                "download_url": res.get("download_url", res.get("dl_url", res.get("url", ""))),
            }
    except Exception:
        logger.exception("Error fetching YouTube data from primary API")
        
    # مصدر احتياطي ثانٍ لضمان عدم توقف الخدمة أبداً
    try:
        backup_api = f"https://kaiz-apis.gleeze.com/api/ytdl?url={url}"
        resp = requests.get(backup_api, timeout=15)
        resp.raise_for_status()
        res = resp.json()
        if "downloadUrl" in res or "url" in res:
            return {
                "title": res.get("title", "فيديو يوتيوب"),
                "duration": res.get("duration", "00:00"),
                "author": res.get("channel", "يوتيوب"),
                "thumbnail": res.get("thumbnail", ""),
                "download_url": res.get("downloadUrl", res.get("url", "")),
            }
    except Exception:
        logger.exception("Error fetching YouTube data from backup API")
        
    return None

async def handle_youtube_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    url = message.text.strip()
    if not is_valid_youtube_url(url):
        return

    processing_msg = await message.reply_text("⏰┇جاري معالجة رابط يوتيوب وجلب المعلومات...")

    try:
        yt_data = fetch_youtube_data(url)
        if not yt_data or not yt_data.get("download_url"):
            await processing_msg.edit_text("❌ عذراً، لم نتمكن من جلب هذا الفيديو. تأكد أن الرابط عام وصحيح.")
            return

        title = yt_data["title"]
        duration = yt_data["duration"]
        author = yt_data["author"]
        thumbnail = yt_data["thumbnail"]
        download_url = yt_data["download_url"]

        # تخزين الجلسة للضغطات اللاحقة
        chat_id = message.chat_id
        yt_sessions = context.application.bot_data.setdefault("yt_sessions", {})
        
        # إرسال أزرار التحميل
        keyboard = [
            [InlineKeyboardButton("📥 تحميل الفيديو (MP4)", callback_data="yt_video")],
            [InlineKeyboardButton("🎵 تحميل كملف صوتي (MP3)", callback_data="yt_audio")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        caption = (
            f"🎬 **يوتيوب**\n"
            f"👤 **القناة:** {author}\n"
            f"⏳ **المدة:** {duration}\n\n"
            f"📌 **العنوان:** {title}\n"
            f"- @G66Gbot"
        )

        sent_msg = None
        if thumbnail:
            sent_msg = await message.reply_photo(photo=thumbnail, caption=caption, reply_markup=reply_markup)
        else:
            sent_msg = await message.reply_text(caption, reply_markup=reply_markup)

        # حفظ الرابط في الجلسة
        session_key = (chat_id, sent_msg.message_id)
        yt_sessions[session_key] = {
            "download_url": download_url,
            "title": title
        }

        await processing_msg.delete()

    except Exception:
        logger.exception("Error in handle_youtube_message")
        await processing_msg.edit_text("⚠️ حدث خطأ أثناء معالجة الرابط، حاول مرة أخرى لاحقاً.")

async def handle_youtube_callback(query, context, session, action):
    download_url = session.get("download_url")
    title = session.get("title", "youtube_media")

    if not download_url:
        await query.message.reply_text("❌ انتهت صلاحية الرابط، أرسله من جديد.")
        return

    status_msg = await query.message.reply_text("🔄 جاري إرسال الملف المطلوب...")

    try:
        if action == "yt_video":
            await query.message.reply_video(video=download_url, caption="- @G66Gbot")
        elif action == "yt_audio":
            await query.message.reply_audio(audio=download_url, title=title, performer="@G66Gbot", caption="- @G66Gbot")
        
        await status_msg.delete()
    except Exception:
        logger.exception("Error in YouTube callback execution")
        await status_msg.edit_text("❌ فشل إرسال الملف، ربما حجمه كبير جداً أو الرابط منتهي.")
