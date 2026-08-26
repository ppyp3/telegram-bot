import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
import yt_dlp

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.environ.get("TOKEN")
ADMIN_IDS = [123456789]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    welcome_msg = (
        f"◀️ | أهلاً بك يا {user_name} في بوت التحميل الشامل\n\n"
        f"مع هذا البوت يمكنك التحميل من عدة مواقع بصيغة متعددة،\n\n"
        f"✅ | المواقع المدعومة :\n"
        f"1️⃣ اليوتيوب | 2️⃣ الانستغرام | 3️⃣ التيك توك\n"
        f"4️⃣ التويتر | 5️⃣ السناب شات | 6️⃣ البينترست\n\n"
        f"🔄 | قم بإرسال الرابط للبدء بالتحميل •"
    )
    await update.message.reply_text(welcome_msg)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ عذراً، هذا الأمر مخصص للمشرفين فقط.")
        return
    await update.message.reply_text("👑 لوحة تحكم الآدمن: البوت يعمل بكفاءة 24/7 ✅")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return

    user_id = update.effective_user.id
    if 'last_processed_url' in context.user_data and context.user_data.get('last_user') == user_id:
        if context.user_data['last_processed_url'] == url:
            return

    context.user_data['last_processed_url'] = url
    context.user_data['last_user'] = user_id

    processing_msg = await update.message.reply_text("⏳ جاري جلب المحتوى...")

    try:
        context.user_data['current_url'] = url
        
        keyboard = [
            [InlineKeyboardButton("🎵 تحميل كملف صوتي.", callback_data="audio")],
            [InlineKeyboardButton("📥 تحميل باعلى دقه HD.", callback_data="hd_video")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # فحص شامل لتحديد إذا كان الرابط يحتوي على صور أو منشور متعدد
        is_slideshow = False
        if "tiktok.com" in url and ("/photo/" in url or "slideshow" in url):
            is_slideshow = True

        if not is_slideshow:
            try:
                ydl_opts_meta = {'extract_flat': True, 'quiet': True, 'cookiefile': 'cookies.txt'}
                with yt_dlp.YoutubeDL(ydl_opts_meta) as ydl:
                    meta = ydl.extract_info(url, download=False)
                    if meta and ('entries' in meta or meta.get('_type') == 'playlist'):
                        is_slideshow = True
            except:
                pass

        if is_slideshow:
            image_opts = {
                'format': 'best',
                'outtmpl': 'img_%(id)s_%(autonumber)s.%(ext)s',
                'quiet': True,
                'cookiefile': 'cookies.txt',
                'skip_download': False,
            }
            
            downloaded_images = []
            with yt_dlp.YoutubeDL(image_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info:
                    if 'entries' in info:
                        for entry in info['entries']:
                            if entry:
                                img_url = entry.get('url') or entry.get('webpage_url')
                                if img_url:
                                    downloaded_images.append(img_url)
                    else:
                        filename = ydl.prepare_filename(info)
                        if os.path.exists(filename):
                            downloaded_images.append(filename)

            if downloaded_images:
                for img in downloaded_images:
                    if img.startswith("http"):
                        await update.message.reply_photo(photo=img, caption="- @G66Gbot", reply_markup=reply_markup)
                    elif os.path.exists(img):
                        with open(img, 'rb') as img_f:
                            await update.message.reply_photo(photo=img_f, caption="- @G66Gbot", reply_markup=reply_markup)
                        os.remove(img)
                await processing_msg.delete()
                return

        # محاولة تحميل الفيديو العادي أو كـ Fallback
        output_template = '%(id)s.%(ext)s'
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': output_template,
            'cookiefile': 'cookies.txt',
            'quiet': True
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'فيديو بدون عنوان')
            uploader = info.get('uploader', 'مؤلف غير معروف')
            filename = ydl.prepare_filename(info)
            
            if not os.path.exists(filename):
                filename = os.path.splitext(filename)[0] + ".mp4"

            context.user_data['video_title'] = title

            caption = (
                f"🎬 {title}\n\n"
                f"👤 الحساب: {uploader}\n\n"
                f"- @G66Gbot"
            )

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
        # محاولة أخيرة مرنة في حال فشل الاستخراج المباشر
        try:
            ydl_opts_fallback = {'format': 'best', 'quiet': True, 'cookiefile': 'cookies.txt', 'outtmpl': 'fallback_%(id)s.%(ext)s'}
            with yt_dlp.YoutubeDL(ydl_opts_fallback) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if os.path.exists(filename):
                    if filename.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                        with open(filename, 'rb') as f:
                            await update.message.reply_photo(photo=f, caption="- @G66Gbot")
                    else:
                        with open(filename, 'rb') as f:
                            await update.message.reply_video(video=f, caption="- @G66Gbot")
                    os.remove(filename)
                    await processing_msg.delete()
                    return
        except:
            pass
            
        await processing_msg.edit_text("❌ عذراً، لم أتمكن من جلب هذا الرابط أو أن المحتوى خاص/يتطلب تسجيل دخول.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    url = context.user_data.get('current_url')
    title = context.user_data.get('video_title', 'media')
    if not url:
        await query.message.reply_text("❌ انتهت صلاحية الجلسة، أرسل الرابط مرة أخرى.")
        return

    if query.data == "audio":
        status_msg = await query.message.reply_text("🔄 جاري تحميل الملف الصوتي...")
        output_template = '%(id)s.%(ext)s'
        ydl_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'outtmpl': output_template,
            'cookiefile': 'cookies.txt',
            'quiet': True
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                
                if not os.path.exists(filename):
                    base, _ = os.path.splitext(filename)
                    for ext in ['.m4a', '.mp3', '.aac', '.opus', '.webm']:
                        if os.path.exists(base + ext):
                            filename = base + ext
                            break

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
        except Exception:
            await status_msg.edit_text("❌ حدث خطأ أثناء تحميل الملف الصوتي.")

    elif query.data == "hd_video":
        status_msg = await query.message.reply_text("🔄 جاري إرسال المحتوى بأعلى دقة...")
        output_template = '%(id)s.%(ext)s'
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': output_template,
            'cookiefile': 'cookies.txt',
            'quiet': True
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if not os.path.exists(filename):
                    filename = os.path.splitext(filename)[0] + ".mp4"

                if os.path.exists(filename):
                    with open(filename, 'rb') as f:
                        await context.bot.send_video(
                            chat_id=query.message.chat_id, 
                            video=f, 
                            caption=f"🎬 {title} (HD)\n- @G66Gbot"
                        )
                    os.remove(filename)
                await status_msg.delete()
        except Exception:
            await status_msg.edit_text("❌ عذراً، لا يمكن جلب هذا المحتوى كفيديو.")

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
