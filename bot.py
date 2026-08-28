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

def fetch_instagram_data(url):
    """استخراج ذكي يدمج Instaloader للصور والبوستات و YoutubeDL للفيديوهات والريلز مع الكوكيز"""
    cookie_file_path = "cookies.txt"
    
    try:
        raw_cookie_url = "https://raw.githubusercontent.com/ppyp3/telegram-bot/refs/heads/main/cookies.txt"
        r = requests.get(raw_cookie_url, timeout=10)
        if r.status_code == 200 and b"Netscape" in r.content:
            with open(cookie_file_path, "wb") as f:
                f.write(r.content)
    except Exception as e:
        logger.error(f"Error auto-updating cookies: {e}")

    media_list = []

    # 1. محاولة استخراج الصور والبوستات باستخدام Instaloader
    try:
        L = instaloader.Instaloader(download_pictures=False, download_videos=False, download_comments=False)
        shortcode = None
        if "/p/" in url:
            shortcode = url.split("/p/")[1].split("/")[0]
        elif "/reel/" in url:
            shortcode = url.split("/reel/")[1].split("/")[0]
        elif "/tv/" in url:
            shortcode = url.split("/tv/")[1].split("/")[0]

        if shortcode:
            post = instaloader.Post.from_shortcode(L.context, shortcode)
            if post.qs: 
                for node in post.get_sidecar_nodes():
                    if node.is_video:
                        media_list.append({'type': 'video', 'url': node.video_url})
                    else:
                        media_list.append({'type': 'photo', 'url': node.display_url})
            else: 
                if post.is_video:
                    media_list.append({'type': 'video', 'url': post.video_url})
                else:
                    media_list.append({'type': 'photo', 'url': post.url})
            
            if media_list:
                return {'media': media_list}
    except Exception as e:
        logger.error(f"Instaloader error: {e}")

    # 2. الطريقة الاحتياطية (YoutubeDL)
    ydl_opts = {
        'extract_flat': False,
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'format': 'best',
    }
    if os.path.exists(cookie_file_path) and os.path.getsize(cookie_file_path) > 100:
        ydl_opts['cookiefile'] = cookie_file_path

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if 'entries' in info and info['entries']:
                for entry in info['entries']:
                    m_type = 'video' if entry.get('_type') == 'video' or entry.get('ext') in ['mp4', 'mov'] or entry.get('duration') else 'photo'
                    m_url = entry.get('url') or entry.get('video_url') or entry.get('thumbnail')
                    if m_url:
                        media_list.append({'type': m_type, 'url': m_url})
            else:
                m_type = 'video' if info.get('ext') in ['mp4', 'mov'] or info.get('duration') else 'photo'
                m_url = info.get('url') or info.get('video_url') or info.get('thumbnail')
                if m_url:
                    media_list.append({'type': m_type, 'url': m_url})

            if media_list:
                return {'media': media_list}
    except Exception as e:
        logger.error(f"YoutubeDL fallback error: {e}")

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

    # إرسال رسالة الانتظار المؤقتة وتخزينها لحذفها لاحقاً
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
                    await update.message.reply_video(video=video_url, caption=BOT_USERNAME)
                    return

        elif "instagram.com" in url:
            insta_data = fetch_instagram_data(url)
            if insta_data and insta_data.get('media'):
                media_items = insta_data['media'][:10]
                
                await status_msg.delete() # حذف رسالة الانتظار فوراً قبل إرسال المحتوى
                
                if len(media_items) == 1:
                    item = media_items[0]
                    if item['type'] == 'video':
                        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
                        await update.message.reply_video(video=item['url'], caption=BOT_USERNAME)
                    else:
                        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                        await update.message.reply_photo(photo=item['url'], caption=BOT_USERNAME)
                else:
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                    media_group = []
                    for idx, item in enumerate(media_items):
                        caption_text = BOT_USERNAME if idx == 0 else None
                        if item['type'] == 'video':
                            media_group.append(InputMediaVideo(media=item['url'], caption=caption_text))
                        else:
                            media_group.append(InputMediaPhoto(media=item['url'], caption=caption_text))
                    
                    if media_group:
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
