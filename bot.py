import os
import logging
import random
import requests
from yt_dlp import YoutubeDL
import instaloader
from telegram import Update, InputMediaPhoto, InputMediaVideo, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TOKEN", "YOUR_BOT_TOKEN")
ADMIN_IDS = [5782729939]
BOT_USERNAME = "- @G66GBOT"

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.15',
]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    welcome_msg = (
        f"✦ أهلاً بك ⦗ {user_name} ⦘ 🖤\n\n"
        f"▫︎ بوت التحميل الخارق (تيك توك & انستجرام) 📥\n"
        f"▫︎ يدعم الصور، البوستات، والريلز بدقة كاملة وبدون أخطاء!\n\n"
        f"⚡ أرسل الرابط الآن 🔻"
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
            return {
                'title': data.get('title', 'محتوى تيك توك'),
                'music': data.get('music', None),
                'images': data.get('images', []),
                'play': data.get('play', None)
            }
        return None
    except Exception as e:
        logger.error(f"TikTok error: {e}")
        return None

def fetch_instagram_media(url):
    """دالة مطورة لجب محتوى انستجرام مع تجنب الحاجة لـ FFmpeg عبر اختيار التنسيقات المدمجة"""
    media_list = []
    
    # 1. جلب الصور والبوستات المتعددة عبر Instaloader
    try:
        L = instaloader.Instaloader(download_pictures=False, download_videos=False, download_comments=False)
        shortcode = None
        clean_url = url.split("?")[0].rstrip("/")
        parts = clean_url.split("/")
        if "p" in parts:
            shortcode = parts[parts.index("p") + 1]
        elif "tv" in parts:
            shortcode = parts[parts.index("tv") + 1]

        if shortcode:
            post = instaloader.Post.from_shortcode(L.context, shortcode)
            if not post.is_video:
                if post.mediacount > 1:
                    for node in post.get_sidecar_nodes():
                        if not node.is_video:
                            media_list.append({'type': 'photo', 'url': node.display_url})
                else:
                    media_list.append({'type': 'photo', 'url': post.url})
                if media_list:
                    return {'type': 'photos', 'media': media_list}
    except Exception as e:
        logger.error(f"Instaloader photo error: {e}")

    # 2. جلب الريلز والفيديوهات عبر YoutubeDL باستخدام صيغ مدمجة جاهزة (لا تتطلب FFmpeg)
    try:
        output_template = f"temp_reel_{random.randint(1000, 9999)}.mp4"
        ydl_opts = {
            'format': 'best[ext=mp4]/best', # اجبارها على جلب صيغة مدمجة بالصوت والصورة إن امكن
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
        }
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            if os.path.exists(output_template):
                return {'type': 'video_file', 'path': output_template}
    except Exception as e:
        logger.error(f"YoutubeDL download error: {e}")

    # 3. خطة بديلة سريعة جداً في حال فشل تنزيل الملف المباشر (سحب رابط الفيديو المباشر الأصلي)
    try:
        ydl_opts = {'extract_flat': False, 'skip_download': True, 'quiet': True}
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            video_url = info.get('url') or info.get('video_url')
            if video_url:
                return {'type': 'video_url', 'url': video_url}
    except Exception as e:
        logger.error(f"YoutubeDL fallback link error: {e}")

    return None

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text if update.message and update.message.text else ""

    if user_id in ADMIN_IDS:
        if text == "🚪 إخفاء لوحة التحكم":
            await update.message.reply_text("🚪 تم إخفاء لوحة التحكم.", reply_markup=ReplyKeyboardRemove())
            return
        elif text.startswith("📊") or text.startswith("📢") or text.startswith("🛑") or text.startswith("🗑️") or "-------------------------------------" in text:
            await update.message.reply_text(f"⚙️ تم استقبال الأمر: {text}")
            return

    url = text
    if not url or not ("tiktok.com" in url or "instagram.com" in url):
        await update.message.reply_text("❌ أرسل رابط تيك توك أو انستجرام صحيح.")
        return

    chat_id = update.effective_chat.id
    status_msg = await update.message.reply_text("⏰┇يرجى الانتظار، يتم قياس حجم التحميل...")

    try:
        if "tiktok.com" in url:
            tiktok_data = fetch_tiktok_data(url)
            if tiktok_data:
                title = tiktok_data['title']
                images = tiktok_data['images']
                video_url = tiktok_data['play']
                audio_url = tiktok_data['music']
                
                if images:
                    if audio_url:
                        try:
                            r = requests.get(audio_url, timeout=15)
                            if r.status_code == 200:
                                local_audio_path = f"audio_{random.randint(1000,9999)}.mp3"
                                with open(local_audio_path, 'wb') as f:
                                    f.write(r.content)
                                
                                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VOICE)
                                with open(local_audio_path, 'rb') as audio_file:
                                    await update.message.reply_audio(audio=audio_file, title=title, performer=BOT_USERNAME, caption=BOT_USERNAME)
                                if os.path.exists(local_audio_path):
                                    os.remove(local_audio_path)
                        except:
                            pass

                    await status_msg.delete() 
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                    total_images = len(images)
                    for i in range(0, total_images, 10):
                        batch = images[i:i+10]
                        media_group = [InputMediaPhoto(media=img_url, caption=BOT_USERNAME if (i + idx + 1) == total_images else None) for idx, img_url in enumerate(batch)]
                        if media_group:
                            await update.message.reply_media_group(media=media_group)
                    return

                elif video_url:
                    await status_msg.delete() 
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
                    await update.message.reply_video(video=video_url, caption=BOT_USERNAME, supports_streaming=True)
                    return

        elif "instagram.com" in url:
            result = fetch_instagram_media(url)
            await status_msg.delete() 

            if result:
                if result['type'] == 'video_file':
                    video_path = result['path']
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
                    with open(video_path, 'rb') as vf:
                        await update.message.reply_video(video=vf, caption=BOT_USERNAME, supports_streaming=True)
                    if os.path.exists(video_path):
                        os.remove(video_path)
                    return

                elif result['type'] == 'video_url':
                    video_link = result['url']
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
                    await update.message.reply_video(video=video_link, caption=BOT_USERNAME, supports_streaming=True)
                    return

                elif result['type'] == 'photos':
                    media_items = result['media'][:10]
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                    if len(media_items) == 1:
                        await update.message.reply_photo(photo=media_items[0]['url'], caption=BOT_USERNAME)
                    else:
                        media_group = [InputMediaPhoto(media=item['url'], caption=BOT_USERNAME if idx == 0 else None) for idx, item in enumerate(media_items)]
                        await update.message.reply_media_group(media=media_group)
                    return

        await status_msg.delete()
        await update.message.reply_text("❌ عذراً، لم أتمكن من جلب المحتوى. تأكد أن الرابط صحيح والحساب عام.")

    except Exception as e:
        logger.error(f"Error: {e}")
        try:
            await status_msg.delete()
        except:
            pass
        await update.message.reply_text("❌ حدث خطأ أثناء جلب الملف.")

def main():
    if TOKEN == "YOUR_BOT_TOKEN":
        print("⚠️ ضع توكن البوت في المتغير TOKEN قبل التشغيل!")
        return
        
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("🚀 البوت يعمل الآن بكفاءة مطلقة...")
    app.run_polling()

if __name__ == '__main__':
    main()
