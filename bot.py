import os
import logging
import re
import requests
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
        f"1️⃣ اليوتيوب | 2️⃣ الانستغرام | 3️⃣ التيك توك (فيديوهات وصور)\n"
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

def fetch_tiktok_images(url):
    """مكتبة/دالة خاصة لجلب صور تيك توك بدون الاعتماد على yt-dlp"""
    try:
        # استخراج معرف الفيديو/الصور من الرابط
        match = re.search(r'/photo/(\d+)', url) or re.search(r'/video/(\d+)', url)
        if not match:
            # محاولة تتبع الرابط المختصر
            r = requests.get(url, allow_redirects=True, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            match = re.search(r'/photo/(\d+)', r.url) or re.search(r'/video/(\d+)', r.url)
            if not match:
                return []
        
        item_id = match.group(1)
        api_url = f"https://api16-normal-c-useast1a.tiktokv.com/aweme/v1/feed/?aweme_id={item_id}"
        resp = requests.get(api_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10).json()
        
        aweme_list = resp.get('aweme_list', [])
        if not aweme_list:
            return []
            
        item = aweme_list[0]
        images = []
        
        # التأكد إذا كان المنشور يحتوي على صور (Image Post)
        image_post_info = item.get('image_post_info')
        if image_post_info and 'images' in image_post_info:
            for img in image_post_info['images']:
                display_image = img.get('display_image', {})
                url_list = display_image.get('url_list', [])
                if url_list:
                    # اختيار أعلى رابط دقة متوفر
                    images.append(url_list[0])
        return images
    except Exception as e:
        print(f"Error fetching tiktok images: {e}")
        return []

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

        # 1. فحص هل هو رابط صور تيك توك لتشغيل المكتبة الخاصة المباشرة
        if "tiktok.com" in url and ("/photo/" in url or "slideshow" in url):
            images = fetch_tiktok_images(url)
            if images:
                for img_url in images:
                    await update.message.reply_photo(photo=img_url, caption="- @G66Gbot", reply_markup=reply_markup)
                await processing_msg.delete()
                return

        # 2. التحميل العادي للفيديوهات عبر yt-dlp
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
