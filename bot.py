import os
import logging
import random
import requests
from urllib.parse import urlparse, urlunparse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.environ.get("TOKEN")
ADMIN_IDS = [5782729939]
BOT_USERNAME = "- @G66GBOT"

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

def clean_instagram_url(url):
    try:
        parsed = urlparse(url)
        clean_path = parsed._replace(query='')
        return urlunparse(clean_path)
    except:
        return url

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
        print(f"Error fetching tiktok data: {e}")
        return None

def fetch_instagram_data(original_url):
    current_ua = random.choice(USER_AGENTS)
    clean_url = clean_instagram_url(original_url)
    
    # محاولة سحب البيانات عبر عدة بوابات قوية مخصصة للصور والفيديوهات
    endpoints = [
        ("https://api.cobalt.tools/api/json", {"url": clean_url, "vQuality": "max"}),
        ("https://co.wuk.sh/api/json", {"url": clean_url, "vQuality": "max"}),
        ("https://ssinstagram.com/api/convert", {"url": clean_url})
    ]

    for api, payload in endpoints:
        try:
            headers = {
                "Accept": "application/json", 
                "Content-Type": "application/json", 
                "User-Agent": current_ua,
                "Origin": "https://cobalt.tools",
                "Referer": "https://cobalt.tools/"
            }
            resp = requests.post(api, json=payload, headers=headers, timeout=10).json()
            
            if resp.get('status') in ['stream', 'redirect', 'picker']:
                media_url = resp.get('url')
                picker_items = resp.get('picker', [])
                
                images_list = []
                video_url = media_url
                
                if picker_items:
                    for item in picker_items:
                        item_url = item.get('url')
                        if item.get('type') == 'photo':
                            images_list.append(item_url)
                        elif item.get('type') == 'video' and not video_url:
                            video_url = item_url

                return {
                    'images': images_list,
                    'play': video_url if not images_list else None
                }
            
            if 'url' in resp and resp['url']:
                return {'images': [], 'play': resp['url']}
                
        except Exception:
            continue

    # بديل إضافي مباشر لسحب صور انستجرام بدقة عالية جداً
    try:
        fallback_api = f"https://saveig.app/api/ajaxSearch"
        headers = {'User-Agent': current_ua, 'X-Requested-With': 'XMLHttpRequest'}
        fb_resp = requests.post(fallback_api, data={"q": clean_url, "t": "media", "lang": "en"}, headers=headers, timeout=10).json()
        
        if fb_resp.get('status') == 'ok':
            # استخراج روابط الصور من الرد المباشر إن وجد
            import re
            html_content = fb_resp.get('data', '')
            img_urls = re.findall(r'href="(https://[^"]+instagram[^"]+?)"', html_content)
            if not img_urls:
                img_urls = re.findall(r'src="(https://[^"]+cdninstagram[^"]+?)"', html_content)
            if img_urls:
                clean_imgs = list(set(img_urls))
                return {'images': clean_imgs, 'play': None}
    except Exception as e:
        print(f"Fallback insta error: {e}")

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

        if "tiktok.com" in url:
            keyboard = [
                [InlineKeyboardButton("🎵 تحميل كملف صوتي.", callback_data="audio")],
                [InlineKeyboardButton("📥 تحميل باعلى دقه HD.", callback_data="hd_video")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            tiktok_data = fetch_tiktok_data(url)
            if tiktok_data:
                title = tiktok_data['title']
                images = tiktok_data['images']
                video_url = tiktok_data['play']
                audio_url = tiktok_data['music']
                
                context.user_data['video_title'] = title
                
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
                                        performer=BOT_USERNAME,
                                        caption=f"{BOT_USERNAME} - 1/1"
                                    )
                                if os.path.exists(local_audio_path):
                                    os.remove(local_audio_path)
                        except:
                            pass

                    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO)
                    total_images = len(images)
                    for i in range(0, total_images, 10):
                        batch = images[i:i+10]
                        media_group = [InputMediaPhoto(media=img_url, caption=f"{BOT_USERNAME} - {i+idx+1}/{total_images}" if i+idx+1 == total_images else None) for idx, img_url in enumerate(batch)]
                        if media_group:
                            await update.message.reply_media_group(media=media_group)
                    await processing_msg.delete()
                    return

                elif video_url:
                    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VIDEO)
                    await update.message.reply_video(video=video_url, caption=BOT_USERNAME, reply_markup=reply_markup)
                    await processing_msg.delete()
                    return

        elif "instagram.com" in url:
            insta_data = fetch_instagram_data(url)
            if insta_data:
                images = insta_data.get('images', [])
                video_url = insta_data.get('play')

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

                elif video_url:
                    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VIDEO)
                    await update.message.reply_video(video=video_url, caption=BOT_USERNAME)
                    await processing_msg.delete()
                    return

        await processing_msg.edit_text("❌ عذراً، لم أتمكن من جلب هذا الرابط. تأكد من صحة الرابط أو أن الحساب عام.")

    except Exception as e:
        print(f"Error in handle_message: {e}")
        await processing_msg.edit_text("❌ حدث خطأ أثناء معالجة الطلب، حاول مرة أخرى.")

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
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except:
            pass

        status_msg = await query.message.reply_text("🔄 جاري تحميل الملف الصوتي...")
        try:
            tiktok_data = fetch_tiktok_data(url)
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
                            performer=BOT_USERNAME, 
                            caption=BOT_USERNAME
                        )
                    if os.path.exists(local_audio_path):
                        os.remove(local_audio_path)
                    await status_msg.delete()
                    return
        except:
            pass
        await status_msg.edit_text("❌ حدث خطأ أثناء تحميل الملف الصوتي.")

    elif query.data == "hd_video":
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except:
            pass

        status_msg = await query.message.reply_text("🔄 جاري إرسال الفيديو...")
        try:
            tiktok_data = fetch_tiktok_data(url)
            video_url = tiktok_data.get('play') if tiktok_data else None

            if video_url:
                audio_only_keyboard = [
                    [InlineKeyboardButton("🎵 تحميل كملف صوتي.", callback_data="audio")]
                ]
                audio_reply_markup = InlineKeyboardMarkup(audio_only_keyboard)

                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
                await context.bot.send_video(
                    chat_id=chat_id, 
                    video=video_url, 
                    caption=BOT_USERNAME, 
                    reply_markup=audio_reply_markup
                )
                await status_msg.delete()
            else:
                await status_msg.edit_text("❌ تعذر تحميل الفيديو بجودة HD.")
        except:
            await status_msg.edit_text("❌ حدث خطأ أثناء تحميل الفيديو.")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    print("بوت التحميل يعمل الآن بكفاءة وسرعة عالية...")
    app.run_polling()

if __name__ == '__main__':
    main()
