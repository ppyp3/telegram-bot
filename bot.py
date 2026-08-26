import os
import logging
import random
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
import yt_dlp

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.environ.get("TOKEN")
ADMIN_IDS = [123456789]

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36',
]

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
    await update.message.reply_text("👑 لوحة تحكم الآدمن: البوت يعمل بكفاءة عالية ✅")

def fetch_tiktok_data(url):
    try:
        current_ua = random.choice(USER_AGENTS)
        headers = {'User-Agent': current_ua, 'Accept-Language': 'en-US,en;q=0.9'}

        if "vm.tiktok.com" in url or "vt.tiktok.com" in url:
            r = requests.get(url, allow_redirects=True, timeout=10, headers=headers)
            url = r.url

        alt_api = f"https://tikwm.com/api/?url={url}&music=1"
        alt_resp = requests.get(alt_api, headers=headers, timeout=10).json()
        
        if alt_resp.get('code') == 0:
            data = alt_resp.get('data', {})
            music_url = data.get('music', None)
            
            audio_filename = f"{random.randint(100000000, 999999999)}_tk.mp3"

            result = {
                'title': data.get('title', 'محتوى تيك توك'),
                'author': data.get('author', {}).get('nickname', 'مستخدم تيك توك'),
                'music': music_url,
                'audio_title': audio_filename,
                'images': data.get('images', []),
                'play': data.get('play', None)
            }
            return result
        return None
    except Exception as e:
        print(f"Error fetching tiktok data: {e}")
        return None

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

    processing_msg = await update.message.reply_text("⏳ جاري جلب المحتوى وترتيبه...")

    try:
        context.user_data['current_url'] = url
        
        keyboard = [
            [InlineKeyboardButton("🎵 تحميل كملف صوتي.", callback_data="audio")],
            [InlineKeyboardButton("📥 تحميل باعلى دقه HD.", callback_data="hd_video")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if "tiktok.com" in url:
            tiktok_data = fetch_tiktok_data(url)
            if tiktok_data:
                title = tiktok_data['title']
                author = tiktok_data['author']
                images = tiktok_data['images']
                video_url = tiktok_data['play']
                audio_url = tiktok_data['music']
                audio_title = tiktok_data['audio_title']
                
                context.user_data['video_title'] = title
                context.user_data['audio_title'] = audio_title
                caption_text = f"🎬 {title}\n\n👤 الحساب: {author}\n\n- @G66Gbot"

                if images:
                    if audio_url:
                        try:
                            await update.message.reply_audio(
                                audio=audio_url, 
                                title=audio_title, 
                                performer="المؤدي غير معروف",
                                caption="- @G66Gbot"
                            )
                        except Exception:
                            pass

                    for i in range(0, len(images), 10):
                        batch = images[i:i+10]
                        media_group = [InputMediaPhoto(media=img_url) for img_url in batch]
                        if media_group:
                            await update.message.reply_media_group(media=media_group)

                    await processing_msg.delete()
                    return

                elif video_url:
                    await update.message.reply_video(video=video_url, caption=caption_text, reply_markup=reply_markup)
                    await processing_msg.delete()
                    return

        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': '%(id)s.%(ext)s',
            'quiet': True,
            'http_headers': {'User-Agent': random.choice(USER_AGENTS)}
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'فيديو بدون عنوان')
            uploader = info.get('uploader', 'مؤلف غير معروف')
            filename = ydl.prepare_filename(info)
            
            if not os.path.exists(filename):
                filename = os.path.splitext(filename)[0] + ".mp4"

            context.user_data['video_title'] = title

            caption = f"🎬 {title}\n\n👤 الحساب: {uploader}\n\n- @G66Gbot"

            with open(filename, 'rb') as f:
                await update.message.reply_video(video=f, caption=caption, reply_markup=reply_markup)

            if os.path.exists(filename):
                os.remove(filename)
            
            await processing_msg.delete()

    except Exception as e:
        await processing_msg.edit_text("❌ عذراً، لم أتمكن من جلب هذا الرابط أو أن المحتوى خاص/يتطلب تسجيل دخول.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    url = context.user_data.get('current_url')
    saved_title = context.user_data.get('audio_title', f"{random.randint(100000000, 999999999)}_tk.mp3")
    
    if not url:
        await query.message.reply_text("❌ انتهت صلاحية الجلسة، أرسل الرابط مرة أخرى.")
        return

    if query.data == "audio":
        status_msg = await query.message.reply_text("🔄 جاري تحميل الملف الصوتي...")
        try:
            tiktok_data = fetch_tiktok_data(url) if "tiktok.com" in url else None
            audio_link = tiktok_data.get('music') if tiktok_data else None

            if audio_link:
                await context.bot.send_audio(
                    chat_id=query.message.chat_id, 
                    audio=audio_link, 
                    title=saved_title, 
                    performer="المؤدي غير معروف", 
                    caption="- @G66Gbot"
                )
                await status_msg.delete()
                return
        except:
            pass

        ydl_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'outtmpl': '%(id)s.%(ext)s',
            'quiet': True,
            'http_headers': {'User-Agent': random.choice(USER_AGENTS)}
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
                        title=saved_title, 
                        performer="المؤدي غير معروف", 
                        caption="- @G66Gbot"
                    )

                if os.path.exists(filename):
                    os.remove(filename)
                await status_msg.delete()
        except Exception:
            await status_msg.edit_text("❌ حدث خطأ أثناء تحميل الملف الصوتي.")

    elif query.data == "hd_video":
        status_msg = await query.message.reply_text("🔄 جاري إرسال المحتوى بأعلى دقة...")
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': '%(id)s.%(ext)s',
            'quiet': True,
            'http_headers': {'User-Agent': random.choice(USER_AGENTS)}
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if not os.path.exists(filename):
                    filename = os.path.splitext(filename)[0] + ".mp4"

                if os.path.exists(filename):
                    video_title = context.user_data.get('video_title', 'media')
                    with open(filename, 'rb') as f:
                        await context.bot.send_video(chat_id=query.message.chat_id, video=f, caption=f"🎬 {video_title} (HD)\n- @G66Gbot")
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
    
    print("البوت يعمل الآن بكامل طاقته...")
    app.run_polling()

if __name__ == '__main__':
    main()
