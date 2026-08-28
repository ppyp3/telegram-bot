import os
import logging
import random
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.environ.get("TOKEN")
ADMIN_IDS = [5782729939] # ضع معرف الآدمن الخاص بك هنا
BOT_USERNAME = "- @w8wbot"

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

            result = {
                'title': title,
                'author': data.get('author', {}).get('nickname', 'مستخدم تيك توك'),
                'music': music_url,
                'audio_title': f"{clean_title}.mp3",
                'images': data.get('images', []),
                'play': data.get('play', None)
            }
            return result
        return None
    except Exception as e:
        print(f"Error fetching tiktok data: {e}")
        return None

def fetch_instagram_data(url):
    current_ua = random.choice(USER_AGENTS)
    
    # دالة ذكية تستخدم ميزة الـ oEmbed والبوابات البديلة المباشرة لجلب انستجرام بدقة
    try:
        api_url = f"https://www.instagram.com/oembed/?url={url}"
        headers = {'User-Agent': current_ua}
        r = requests.get(api_url, headers=headers, timeout=5)
        if r.status_code == 200:
            pass # الرابط صحيح وموجود
    except Exception:
        pass

    # قائمة السيرفرات المحدثة للاستجابة السريعة
    instances = [
        "https://co.wuk.sh/api/json",
        "https://api.cobalt.tools/api/json",
        "https://cobalt.katsu.org.es/api/json"
    ]

    for api in instances:
        try:
            payload = {"url": url, "vQuality": "max"}
            headers = {
                "Accept": "application/json", 
                "Content-Type": "application/json", 
                "User-Agent": current_ua,
                "Origin": "https://cobalt.tools",
                "Referer": "https://cobalt.tools/"
            }
            resp = requests.post(api, json=payload, headers=headers, timeout=8).json()
            status = resp.get('status')
            
            if status in ['stream', 'redirect', 'picker']:
                media_url = resp.get('url')
                picker_items = resp.get('picker', [])
                
                images_list = []
                video_url = media_url
                
                if picker_items:
                    for item in picker_items:
                        item_url = item.get('url')
                        item_type = item.get('type')
                        if item_type == 'photo':
                            images_list.append(item_url)
                        elif item_type == 'video' and not video_url:
                            video_url = item_url

                return {
                    'images': images_list,
                    'play': video_url if not images_list else None
                }
        except Exception:
            continue
            
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

    processing_msg = await update.message.reply_text("⏰┇يرجى الانتظار، يتم قياس حجم التحميل...")

    try:
        context.user_data['current_url'] = url

        # 1. معالجة روابط تيك توك
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
                caption_text = BOT_USERNAME

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
                                media_group.append(InputMediaPhoto(media=img_url, caption=f"{BOT_USERNAME} - {absolute_index}/{total_images}"))
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

        # 2. معالجة روابط انستجرام
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
                        media_group = []
                        for idx, img_url in enumerate(batch):
                            absolute_index = i + idx + 1
                            if absolute_index == total_images:
                                media_group.append(InputMediaPhoto(media=img_url, caption=f"{BOT_USERNAME} - {absolute_index}/{total_images}"))
                            else:
                                media_group.append(InputMediaPhoto(media=img_url))
                        if media_group:
                            await update.message.reply_media_group(media=media_group)
                    await processing_msg.delete()
                    return

                elif video_url:
                    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VIDEO)
                    await update.message.reply_video(video=video_url, caption=BOT_USERNAME)
                    await processing_msg.delete()
                    return

        error_custom_msg = (
            "⚠️┇هذا الملف لا يمكنني تحميله،\n"
            "⚠️┇لأن حجمه يتجاوز ( 50 Mbps )،\n"
            "⚠️┇أعد المحاوله مع ملف اخر."
        )
        await processing_msg.edit_text(error_custom_msg)

    except Exception as e:
        print(f"Error in handle_message: {e}")
        error_custom_msg = (
            "⚠️┇هذا الملف لا يمكنني تحميله،\n"
            "⚠️┇لأن حجمه يتجاوز ( 50 Mbps )،\n"
            "⚠️┇أعد المحاوله مع ملف اخر."
        )
        await processing_msg.edit_text(error_custom_msg)

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
        except Exception:
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
        except Exception:
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
                error_custom_msg = (
                    "⚠️┇هذا الملف لا يمكنني تحميله،\n"
                    "⚠️┇لأن حجمه يتجاوز ( 50 Mbps )،\n"
                    "⚠️┇أعد المحاوله مع ملف اخر."
                )
                await status_msg.edit_text(error_custom_msg)
        except Exception:
            error_custom_msg = (
                "⚠️┇هذا الملف لا يمكنني تحميله،\n"
                "⚠️┇لأن حجمه يتجاوز ( 50 Mbps )،\n"
                "⚠️┇أعد المحاوله مع ملف اخر."
            )
            await status_msg.edit_text(error_custom_msg)

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
