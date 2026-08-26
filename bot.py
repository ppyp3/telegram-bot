import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
import yt_dlp

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.environ.get("TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    welcome_msg = (
        f"‌▪️ | أهلاً بك يا {user_name} في بوت التحميل الشامل\n"
        f"G66Gbot@\n\n"
        "• أرسل أي رابط (يوتيوب، تيك توك، إنستجرام)\n"
        "• أو اكتب اسم أي أغنية للبحث والتحميل المباشر! 🔍"
    )
    await update.message.reply_text(welcome_msg)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    if url.startswith("http://") or url.startswith("https://"):
        processing_msg = await update.message.reply_text("⏳ جاري جلب تفاصيل الرابط...")
        
        ydl_opts = {'quiet': True, 'no_warnings': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                title = info.get('title', 'فيديو بدون عنوان')
                uploader = info.get('uploader', 'مؤلف غير معروف')
                duration = info.get('duration_string', '0:00')
            except Exception:
                await processing_msg.edit_text("❌ عذراً، لم أتمكن من جلب معلومات هذا الرابط.")
                return

        context.user_data['current_url'] = url
        context.user_data['video_title'] = title

        caption = (
            f"🎬 {title}\n\n"
            f"👤 القناة: {uploader}\n"
            f"⏱ المدة: {duration}\n\n"
            f"- @G66Gbot"
        )

        keyboard = [
            [
                InlineKeyboardButton("🎵 تحميل كملف صوتي.", callback_data="audio"),
            ],
            [
                InlineKeyboardButton("📥 تحميل بأعلى دقة HD.", callback_data="video")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await processing_msg.delete()
        await update.message.reply_text(caption, reply_markup=reply_markup)
    else:
        await update.message.reply_text("❌ يرجى إرسال رابط صالح أو استخدم أمر /start")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    url = context.user_data.get('current_url')
    title = context.user_data.get('video_title', 'media')
    if not url:
        await query.edit_message_text("❌ انتهت صلاحية الجلسة، أرسل الرابط مرة أخرى.")
        return

    await query.edit_message_text("⬇️ جاري التحميل، يرجى الانتظار...")

    output_template = '%(id)s.%(ext)s'
    
    if query.data == "audio":
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_template,
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
        }
    else:
        ydl_opts = {'format': 'best[ext=mp4]/best', 'outtmpl': output_template}

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            if query.data == "audio":
                filename = os.path.splitext(filename)[0] + ".mp3"
                with open(filename, 'rb') as f:
                    await context.bot.send_audio(chat_id=query.message.chat_id, audio=f, title=title, caption=f"🎵 {title}\n- @G66Gbot")
            else:
                with open(filename, 'rb') as f:
                    await context.bot.send_video(chat_id=query.message.chat_id, video=f, caption=f"🎬 {title}\n- @G66Gbot")

            if os.path.exists(filename):
                os.remove(filename)
            await query.message.delete()
            
    except Exception as e:
        await query.message.edit_text(f"❌ حدث خطأ أثناء التحميل: {str(e)}")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    print("البوت يعمل الآن...")
    app.run_polling()

if __name__ == '__main__':
    main()
