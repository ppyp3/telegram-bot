import os
import logging
import random
import requests
from telegram import Update, InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.environ.get("TOKEN")
ADMIN_IDS = [5782729939]
BOT_USERNAME = "- @w8wbot"  # يوزر البوت الذي سيظهر حصراً تحت الملفات

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36',
]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    welcome_msg = (
        f"*أهلاً بك عزيزي {user_name} في بوت التحميل السريع* 🖤\n\n"
        f"> قم بتنزيل فيديوهات وصور *تيك توك* و*انستجرام* (ريلز وبوستات) بدقة عالية وبدون حقوق فوراً.\n\n"
        f"⚡ *أرسل الرابط الآن للبدء*"
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

def fetch_media_data(url):
    current_ua = random.choice(USER_AGENTS)
    headers = {'User-Agent': current_ua, 'Accept-Language': 'en-US,en;q=0.9', 'Accept': 'application/json'}

    if "tiktok.com" in url:
        try:
            if "vm.tiktok.com" in url or "vt.tiktok.com" in url:
                r = requests.get(url, allow_redirects=True, timeout=10, headers=headers)
                url = r.url
            api_url = f"https://tikwm.com/api/?url={url}&music=1"
            resp = requests.get(api_url, headers=headers, timeout=10).json()
            if resp.get('code') == 0:
                data = resp.get('data', {})
                return {
                    'images': data.get('images', []),
                    'play': data.get('play', None)
                }
        except Exception as e:
            print(f"TikTok error: {e}")

    cobalt_instances = [
        "https://co.wuk.sh/api/json",
        "https://cobalt.katsu.org.es/api/json",
        "https://api.cobalt.tools/api/json"
    ]

    for cobalt_api in cobalt_instances:
        try:
            payload = {"url": url, "vQuality": "max"}
            cobalt_headers = {
                "Accept": "application/json", 
                "Content-Type": "application/json", 
                "User-Agent": current_ua,
                "Origin": "https://cobalt.tools",
                "Referer": "https://cobalt.tools/"
            }
            
            resp = requests.post(cobalt_api, json=payload, headers=cobalt_headers, timeout=8).json()
            
            if resp.get('status') in ['stream', 'redirect', 'picker']:
                media_url = resp.get('url')
                picker_items = resp.get('picker', [])
                
                images_list = []
                video_url = media_url
                
                if picker_items:
                    for item in picker_items:
                        if item.get('type') == 'photo':
                            images_list.append(item.get('url'))
                        elif item.get('type') == 'video' and not video_url:
                            video_url = item.get('url')

                return {
                    'images': images_list,
                    'play': video_url if not images_list else None
                }
        except Exception as e:
            print(f"Cobalt instance error ({cobalt_api}): {e}")
            continue

    try:
        fallback_api = f"https://apis.davidcyriltech.my.id/instagram?url={url}"
        resp = requests.get(fallback_api, timeout=10).json()
        if resp.get('status') == 200 and resp.get('success'):
            result_data = resp.get('result', [])
            if isinstance(result_data, list) and len(result_data) > 0:
                first_item = result_data[0]
                video_url = first_item.get('url') if isinstance(first_item, dict) else first_item
                if video_url:
                    return {
                        'images': [],
                        'play': video_url
                    }
    except Exception as e:
        print(f"Fallback API error: {e}")

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
        media_data = fetch_media_data(url)
        if media_data:
            images = media_data.get('images', [])
            video_url = media_data.get('play')

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
                # إرسال الفيديو مع يوزر البوت حصراً وبدون أزرار
                await update.message.reply_video(video=video_url, caption=BOT_USERNAME)
                await processing_msg.delete()
                return

        await processing_msg.edit_text(
            "⚠️┇عذراً، تعذر جلب رابط الفيديو من انستجرام.\n"
            "⚠️┇تأكد أن الحساب عام وليس خاصاً، أو أعد المحاولة."
        )

    except Exception as e:
        print(f"Error in handle_message: {e}")
        await processing_msg.edit_text(
            "⚠️┇حدث خطأ أثناء الاتصال بسيرفر التحميل.\n"
            "⚠️┇أعد المحاولة لاحقاً."
        )

def main():
    if not TOKEN:
        print("Error: TOKEN is not set!")
        return
        
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("بوت التحميل يعمل الآن بكفاءة عالية...")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
