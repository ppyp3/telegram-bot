import os
import logging
import random
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.environ.get("TOKEN")
ADMIN_IDS = [5782729939]
BOT_USERNAME = "- @w8wbot"

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.15',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1',
]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    welcome_msg = (
        f"✦ أهلاً بك ⦗ {user_name} ⦘ 🖤\n\n"
        f"▫︎ بوت التحميل السريع (تيك توك & انستجرام) 📥\n"
        f"▫︎ فيديوهات بدون حقوق • صور • ريلز • بوستات\n\n"
        f"⚡ أرسل الرابط الآن للبدء 🔻"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ عذراً، هذا الأمر مخصص للمشرفين فقط.")
        return

    keyboard = [
        [KeyboardButton("📊 عدد المشتركين"), KeyboardButton("📢 بدء إذاعة 🔊")],
        [KeyboardButton("🛑 إيقاف الإذاعة 🔊"), KeyboardButton("🗑️ حذف جميع الإذاعات 🔊")],
        [KeyboardButton("-------------------------------------")],
        [KeyboardButton("🚪 إخفاء لوحة التحكم")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("👑 **مرحباً بك في لوحة تحكم البوت:**", reply_markup=reply_markup)

def get_media_info(url):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extractor_args': {'instagram': {'max_comments': 0}},
        'http_headers': {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept-Language': 'en-US,en;q=0.9',
        }
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info
    except Exception as e:
        print(f"yt-dlp error: {e}")
        return None

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text if update.message and update.message.text else ""

    if user_id in ADMIN_IDS:
        if text == "🚪 إخفاء لوحة التحكم":
            await update.message.reply_text("🚪 تم إخفاء لوحة التحكم. لإظهارها أرسل /admin", reply_markup=ReplyKeyboardRemove())
            return
        elif text.startswith("📊") or text.startswith("📢") or text.startswith("🛑") or text.startswith("🗑️") or "-------------------------------------" in text:
            await update.message.reply_text(f"⚙️ تم استقبال الأمر: {text}")
            return

    url = text
    if not url or not ("tiktok.com" in url or "instagram.com" in url):
        await update.message.reply_text("❌ أرسل رابط تيك توك أو انستجرام صحيحاً من فضلك.")
        return

    processing_msg = await update.message.reply_text("⏰┇يرجى الانتظار، جاري معالجة وسحب الملف...")

    try:
        context.user_data['current_url'] = url
        data = get_media_info(url)

        if not data:
            await processing_msg.edit_text("❌ عذراً، لم أتمكن من جلب هذا الرابط. تأكد من أن الرابط صحيح أو الحساب عام.")
            return

        # فحص وجود صور متعددة (Carousel)
        entries = data.get('entries')
        if entries:
            images = [entry.get('url') for entry in entries if entry.get('url')]
            if images:
                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO)
                total_images = len(images)
                for i in range(0, total_images, 10):
                    batch = images[i:i+10]
                    media_group = [InputMediaPhoto(media=img_url, caption=f"{BOT_USERNAME} - {i+idx+1}/{total_images}" if i+idx+1 == total_images else None) for idx, img_url in enumerate(batch)]
                    if media_group:
                        await update.message.reply_media_group(media=media_group)
                await processing_msg.delete()
                return

        # استخراج رابط الفيديو المباشر
        video_url = data.get('url')
        if not video_url and 'formats' in data:
            formats = [f for f in data['formats'] if f.get('url') and f.get('vcodec') != 'none']
            if formats:
                video_url = formats[-1].get('url')

        if video_url:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VIDEO)
            
            keyboard = [
                [InlineKeyboardButton("🎵 تحميل كملف صوتي.", callback_data="audio")],
                [InlineKeyboardButton("📥 تحميل باعلى دقه HD.", callback_data="hd_video")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard) if "tiktok.com" in url else None

            await update.message.reply_video(video=video_url, caption=BOT_USERNAME, reply_markup=reply_markup)
            await processing_msg.delete()
            return

        await processing_msg.edit_text("❌ تعذر استخراج الوسائط من هذا الرابط.")

    except Exception as e:
        print(f"Error in handle_message: {e}")
        await processing_msg.edit_text("❌ حدث خطأ أثناء جلب الرابط، حاول مرة أخرى.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    url = context.user_data.get('current_url')
    
    if not url:
        await query.message.reply_text("❌ انتهت صلاحية الجلسة، أرسل الرابط مرة أخرى.")
        return

    if query.data == "audio":
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

        status_msg = await query.message.reply_text("🔄 جاري استخراج الملف الصوتي...")
        try:
            data = get_media_info(url)
            audio_url = data.get('url')
            if data and 'requested_downloads' in data:
                audio_url = data['requested_downloads'][0].get('url')
            
            if audio_url:
                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VOICE)
                await context.bot.send_audio(chat_id=chat_id, audio=audio_url, performer=BOT_USERNAME, caption=BOT_USERNAME)
                await status_msg.delete()
                return
        except:
            pass
        await status_msg.edit_text("❌ حدث خطأ أثناء تحميل الملف الصوتي.")

    elif query.data == "hd_video":
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

        status_msg = await query.message.reply_text("🔄 جاري إرسال الفيديو بجودة عالية...")
        try:
            data = get_media_info(url)
            video_url = data.get('url')
            if video_url:
                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
                await context.bot.send_video(chat_id=chat_id, video=video_url, caption=BOT_USERNAME)
                await status_msg.delete()
                return
        except:
            pass
        await status_msg.edit_text("❌ تعذر إرسال الفيديو.")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    print("بوت التحميل يعمل الآن بكفاءة عالية جداً عبر محرك yt-dlp...")
    app.run_polling()

if __name__ == '__main__':
    main()
