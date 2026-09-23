import re
import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, MessageHandler, filters

# فلتر الروابط لليوتيوب
YOUTUBE_FILTER = filters.TEXT & ~filters.COMMAND & filters.Regex(
    r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+"
)

COBALT_API_URL = "https://cobalt-production-5277.up.railway.app"

async def handle_youtube_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    
    keyboard = [
        [InlineKeyboardButton("🎬 فيديو (دقة عالية)", callback_data="yt_video")],
        [InlineKeyboardButton("🎵 ملف صوتي (MP3)", callback_data="yt_audio")],
        [InlineKeyboardButton("🎙️ بصمة صوتية (Voice)", callback_data="yt_voice")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # حفظ الجلسة مؤقتاً
    yt_sessions = context.application.bot_data.setdefault("yt_sessions", {})
    sent_msg = await update.message.reply_text("📺 اختر طريقة التحميل المناسبة:", reply_markup=reply_markup)
    
    session_key = (update.effective_chat.id, sent_msg.message_id)
    yt_sessions[session_key] = {
        "user_id": update.effective_user.id,
        "url": url,
    }

async def handle_youtube_callback(query, context, session, mode):
    url = session["url"]
    status_msg = await query.message.reply_text("🔄 جاري جلب الرابط من سيرفر التحميل...")

    try:
        payload = {
            "url": url,
            "vQuality": "720"
        }
        
        if mode in ["yt_audio", "yt_voice"]:
            payload["audioFormat"] = "mp3"

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        response = requests.post(COBALT_API_URL, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

        download_url = data.get("url") or data.get("picker", [{}])[0].get("url")
        
        if not download_url:
            await status_msg.edit_text("❌ لم يتم العثور على رابط مباشر للتحميل.")
            return

        await status_msg.edit_text("📥 جاري رفع الملف إلى تيليجرام...")

        if mode == "yt_audio":
            await query.message.reply_audio(audio=download_url, caption="- @G66Gbot")
        elif mode == "yt_voice":
            await query.message.reply_voice(voice=download_url, caption="- @G66Gbot")
        else:
            await query.message.reply_video(video=download_url, caption="- @G66Gbot")

        await status_msg.delete()

    except Exception as e:
        print(f"YouTube Error: {e}")
        await status_msg.edit_text("⚠️ حدث خطأ أثناء المعالجة، يرجى المحاولة لاحقاً.")
