import os
import logging
import random
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
import yt_dlp

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.environ.get("TOKEN")
ADMIN_IDS = [5782729939, 123456789] # ضع معرف الآدمن الخاص بك هنا

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36',
]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    welcome_msg = (
        f"✦ أهلاً بك ⦗ {user_name} ⦘ 🖤\n\n"
        f"▫︎ بوت تحميل التيك توك السريع 📥\n"
        f"▫︎ فيديوهات بدون حقوق • صور • صوتيات\n\n"
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
        [KeyboardButton("📺 بدء بث 🎙️"), KeyboardButton("📻 تشغيل البث 🎙️")],
        [KeyboardButton("🛑 إيقاف البث 🎙️"), KeyboardButton("📊 إحصائيات البث 🎙️")],
        [KeyboardButton("-------------------------------------")],
        [KeyboardButton("⚡ تغيير رسالة الـ Start ⚡"), KeyboardButton("↩️ استرجاع رسالة الـ Start ⚡")],
        [KeyboardButton("-------------------------------------")],
        [KeyboardButton("⚠️ تفعيل زر الإبلاغ ⚠️"), KeyboardButton("⚠️ تعطيل زر الإبلاغ ⚠️")],
        [KeyboardButton("-------------------------------------")],
        [KeyboardButton("🔔 تفعيل الإشعارات 🔔"), KeyboardButton("🔕 تعطيل الإشعارات 🔔")],
        [KeyboardButton("-------------------------------------")],
        [KeyboardButton("✅ تفعيل الاشتراك الإجباري 1"), KeyboardButton("❌ تعطيل الاشتراك الإجباري 1")],
        [KeyboardButton("ℹ️ معلومات الاشتراك 1"), KeyboardButton("✏️ تغيير قناة الاشتراك 1 🔑")],
        [KeyboardButton("-------------------------------------")],
        [KeyboardButton("✅ تفعيل الاشتراك الإجباري 2"), KeyboardButton("❌ تعطيل الاشتراك الإجباري 2")],
        [KeyboardButton("ℹ️ معلومات الاشتراك 2"), KeyboardButton("✏️ تغيير قناة الاشتراك 2 🔑")],
        [KeyboardButton("-------------------------------------")],
        [KeyboardButton("✅ تفعيل الاشتراك الوهمي"), KeyboardButton("❌ تعطيل الاشتراك الوهمي")],
        [KeyboardButton("✏️ تغيير قناة الاشتراك الوهمي 🔑")],
        [KeyboardButton("-------------------------------------")],
        [KeyboardButton("➕ رفع أدمن ⬇️"), KeyboardButton("⬇️ تنزيل أدمن ⬇️")],
        [KeyboardButton("🛡️ رفع أدمن كامل صلاحيات ⬇️"), KeyboardButton("🛡️ تنزيل الأدمن كامل صلاحيات ⬇️")],
        [KeyboardButton("-------------------------------------")],
        [KeyboardButton("👑 نقل ملكية البوت 🔑")],
        [KeyboardButton("🚪 إخفاء لوحة التحكم")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("👑 **مرحباً بك في لوحة تحكم المطور الاحترافية:**", reply_markup=reply_markup)

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
            title = data.get('title', 'محتوى تيك توك')
            
            clean_title = "".join(c for c in title if c.isalnum() or c in (' ', '_', '-', '🔥')).strip()
            if not clean_title:
                clean_title = "tiktok_audio"
            audio_filename = f"{clean_title}.mp3"

            result = {
                'title': title,
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
    user_id = update.effective_user.id
    text = update.message.text if update.message and update.message.text else ""

    if user_id in ADMIN_IDS:
        if text == "🚪 إخفاء لوحة التحكم":
            await update.message.reply_text("🚪 تم إخفاء لوحة التحكم. لإظهارها أرسل /admin", reply_markup=ReplyKeyboardRemove())
            return
        elif text.startswith("📊") or text.startswith("📢") or text.startswith("🛑") or text.startswith("🗑️") or text.startswith("📺") or text.startswith("📻") or text.startswith("⚡") or text.startswith("↩️") or text.startswith("⚠️") or text.startswith("🔔") or text.startswith("🔕") or text.startswith("✅") or text.startswith("❌") or text.startswith("ℹ️") or text.startswith("✏️") or text.startswith("➕") or text.startswith("⬇️") or text.startswith("🛡️") or text.startswith("👑") or "-------------------------------------" in text:
            await update.message.reply_text(f"⚙️ تم استقبال الأمر: {text}")
            return

    url = text
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return

    processing_msg = await update.message.reply_text("⏳ ¦ يرجى الانتظار, يتم قياس حجم التحميل...")

    try:
        context.user_data['current_url'] = url
        
        # الأزرار الأولية (تحميل صوت + تحميل دقة عالية)
        keyboard = [
            [InlineKeyboardButton("🎵 تحميل كملف صوتي.", callback_data="audio")],
            [InlineKeyboardButton("📥 تحميل باعلى دقه HD.", callback_data="hd_video")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if "tiktok.com" in url:
            tiktok_data = fetch_tiktok_data(url)
            if tiktok_data:
                title = tiktok_data['title']
                images = tiktok_data['images']
                video_url = tiktok_data['play']
                audio_url = tiktok_data['music']
                audio_title = tiktok_data['audio_title']
                
                context.user_data['video_title'] = title
                context.user_data['audio_title'] = audio_title
                
                caption_text = "- @G66Gbot"

                if images:
                    if audio_url:
                        try:
                            r = requests.get(audio_url, timeout=15)
                            if r.status_code == 200:
                                local_audio_path = f"audio_{random.randint(1000,9999)}.mp3"
                                with open(local_audio_path, 'wb') as f:
                                    f.write(r.content)
                                
                                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VOICE)
                                with open(local_audio_path, 'rb') as audio_file:
                                    await update.message.reply_audio(
                                        audio=audio_file, 
                                        title=title, 
                                        performer="@G66Gbot",
                                        caption="- @G66Gbot - 1/1"
                                    )
                                if os.path.exists(local_audio_path):
                                    os.remove(local_audio_path)
                        except Exception as ex:
                            print(f"Audio send error: {ex}")

                    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO)
                    
                    total_images = len(images)
                    for i in range(0, total_images, 10):
                        batch = images[i:i+10]
                        media_group = []
                        
                        for idx, img_url in enumerate(batch):
                            absolute_index = i + idx + 1
                            if absolute_index == total_images:
                                media_group.append(InputMediaPhoto(media=img_url, caption=f"- @G66Gbot - {absolute_index}/{total_images}"))
                            else:
                                media_group.append(InputMediaPhoto(media=img_url))

                        if media_group:
                            await update.message.reply_media_group(media=media_group)

                    await processing_msg.delete()
                    return

                elif video_url:
                    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VIDEO)
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
            filename = ydl.prepare_filename(info)
            
            if not os.path.exists(filename):
                filename = os.path.splitext(filename)[0] + ".mp4"

            context.user_data['video_title'] = title
            clean_title = "".join(c for c in title if c.isalnum() or c in (' ', '_', '-', '🔥')).strip()
            context.user_data['audio_title'] = f"{clean_title}.mp3" if clean_title else "audio.mp3"

            caption = "- @G66Gbot"

            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VIDEO)
            with open(filename, 'rb') as f:
                await update.message.reply_video(video=f, caption=caption, reply_markup=reply_markup)

            if os.path.exists(filename):
                os.remove(filename)
            
            await processing_msg.delete()

    except Exception as e:
        print(f"Error in handle_message: {e}")
        await processing_msg.edit_text("❌ عذراً، لم أتمكن من جلب هذا الرابط أو أن المحتوى خاص/يتطلب تسجيل دخول.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    
    url = context.user_data.get('current_url')
    video_title = context.user_data.get('video_title', 'محتوى صوتي')
    
    if not url:
        await query.message.reply_text("❌ انتهت صلاحية الجلسة، أرسل الرابط مرة أخرى.")
        return

    if query.data == "audio":
        # عند الضغط على تحميل صوت، نحذف الأزرار نهائياً من الرسالة الحالية
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

        status_msg = await query.message.reply_text("🔄 جاري تحميل الملف الصوتي...")
        try:
            tiktok_data = fetch_tiktok_data(url) if "tiktok.com" in url else None
            audio_link = tiktok_data.get('music') if tiktok_data else None

            if audio_link:
                r = requests.get(audio_link, timeout=15)
                if r.status_code == 200:
                    local_audio_path = f"audio_{random.randint(1000,9999)}.mp3"
                    with open(local_audio_path, 'wb') as f:
                        f.write(r.content)

                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VOICE)
                    with open(local_audio_path, 'rb') as audio_file:
                        await context.bot.send_audio(
                            chat_id=chat_id, 
                            audio=audio_file, 
                            title=video_title, 
                            performer="@G66Gbot", 
                            caption="- @G66Gbot"
                        )
                    if os.path.exists(local_audio_path):
                        os.remove(local_audio_path)
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

                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VOICE)
                with open(filename, 'rb') as f:
                    await context.bot.send_audio(
                        chat_id=chat_id, 
                        audio=f, 
                        title=video_title, 
                        performer="@G66Gbot", 
                        caption="- @G66Gbot"
                    )

                if os.path.exists(filename):
                    os.remove(filename)
                await status_msg.delete()
        except Exception:
            await status_msg.edit_text("❌ حدث خطأ أثناء تحميل الملف الصوتي.")

    elif query.data == "hd_video":
        # عند الضغط على دقة عالية، نجعل الأزرار تختفي من رسالة الفيديو القديمة، ونترك زر الصوت فقط تحت الفيديو الجديد
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

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
                    v_title = context.user_data.get('video_title', 'media')
                    
                    # زر الصوت فقط ليظهر تحت الفيديو عند تحميله بدقة عالية
                    audio_only_keyboard = [
                        [InlineKeyboardButton("🎵 تحميل كملف صوتي.", callback_data="audio")]
                    ]
                    audio_reply_markup = InlineKeyboardMarkup(audio_only_keyboard)

                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
                    with open(filename, 'rb') as f:
                        await context.bot.send_video(
                            chat_id=chat_id, 
                            video=f, 
                            caption="- @G66Gbot", 
                            reply_markup=audio_reply_markup
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
    
    print("البوت يعمل الآن مع نظام أزرار الفيديو والصوت الاحترافي...")
    app.run_polling()

if __name__ == '__main__':
    main()
