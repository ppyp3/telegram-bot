import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
import yt_dlp

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.environ.get("TOKEN")
ADMIN_IDS = [123456789] # استبدل الأيدي بأيديك إذا أردت

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    welcome_msg = (
        f"‌▪️ | أهلاً بك يا {user_name} في بوت التحميل الشامل\n"
        f"G66Gbot@\n\n"
        "• أرسل أي رابط (تيك توك، يوتيوب، إنستجرام)\n"
        "• سيتم إرسال الفيديو مباشرة بدقة SD مع خيار الصوت! 📥"
    )
    await update.message.reply_text(welcome_msg)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ عذراً، هذا الأمر مخصص للمشرفين فقط.")
        return
    await update.message.reply_text("👑 لوحة تحكم الآدمن: البوت يعمل بكفاءة 24/7 ✅")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # تجاهل أي رسالة لا تحتوي على رابط مباشر
    url = update.message.text
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return

    # منع التكرار: التحقق من معالجة نفس الرابط لنفس المستخدم خلال ثوانٍ معدودة
    user_id = update.effective_user.id
    if 'last_processed_url' in context.user_data and context.user_data.get('last_user') == user_id:
        if context.user_data['last_processed_url'] == url:
            return  # إذا أرسل نفس الرابط مرتين وراء بعض يتم تجاهل التكرار

    context.user_data['last_processed_url'] = url
    context.user_data['last_user'] = user_id

    processing_msg = await update.message.reply_text("⏳ جاري تحميل الفيديو (SD) وإعداده...")
    
    output_template = '%(id)s.%(ext)s'
    ydl_opts = {
        'format': 'best[height<=720][ext=mp4]/best[ext=mp4]/best',
        'outtmpl': output_template,
        'quiet': True
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'فيديو بدون عنوان')
            uploader = info.get('uploader', 'مؤلف غير معروف')
            filename = ydl.prepare_filename(info)
            
            if not os.path.exists(filename):
                filename = os.path.splitext(filename)[0] + ".mp4"

            context.user_data['current_url'] = url
            context.user_data['video_title'] = title

            caption = (
                f"🎬 {title}\n\n"
                f"👤 الحساب: {uploader}\n\n"
                f"- @G66Gbot"
            )

            keyboard = [
                [
                    InlineKeyboardButton("🎵 تحويل وتحميل كملف صوتي (MP3)", callback_data="audio"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            with open(filename, 'rb') as f:
                await update.message.reply_video(
                    video=f, 
                    caption=caption, 
                    reply_markup=reply_markup
                )

            if os.path.exists(filename):
                os.remove(filename)
            
            await processing_msg.delete()

    except Exception as e:
        await processing_msg.edit_text("❌ عذراً، حدث خطأ أثناء تحميل الرابط أو أن المحتوى خاص / محمي.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    url = context.user_data.get('current_url')
    title = context.user_data.get('video_title', 'media')
    if not url:
        await query.edit_message_text("❌ انتهت صلاحية الجلسة، أرسل الرابط مرة أخرى.")
        return

    status_msg = await query.message.reply_text("🔄 جاري استخراج الصوت (MP3)...")

    output_template = '%(id)s.%(ext)s'
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_template,
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
        'quiet': True
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            filename = os.path.splitext(filename)[0] + ".mp3"

            with open(filename, 'rb') as f:
                await context.bot.send_audio(
                    chat_id=query.message.chat_id, 
                    audio=f, 
                    title=title, 
                    caption=f"🎵 {title}\n- @G66Gbot"
                )

            if os.path.exists(filename):
                os.remove(filename)
            await status_msg.delete()
            
    except Exception as e:
        await status_msg.edit_text("❌ حدث خطأ أثناء تحويل الملف الصوتي.")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    print("البوت يعمل الآن...")
    app.run_polling()

if __name__ == '__main__':
    main()
