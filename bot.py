import os
import logging
import random
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.environ.get("TOKEN")

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
        f"▫︎ بوت تحميل التيك توك السريع (دعم ضغط عالي) 📥\n"
        f"▫︎ فيديوهات بدون حقوق • صور • صوتيات\n\n"
        f"⚡ أرسل الرابط الآن للبدء 🔻"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

async def fetch_tiktok_data(url):
    try:
        current_ua = random.choice(USER_AGENTS)
        headers = {'User-Agent': current_ua, 'Accept-Language': 'en-US,en;q=0.9'}

        async with httpx.AsyncClient(headers=headers, timeout=15.0, follow_redirects=True) as client:
            if "vm.tiktok.com" in url or "vt.tiktok.com" in url:
                r = await client.get(url)
                url = str(r.url)

            alt_api = f"https://tikwm.com/api/?url={url}&music=1"
            resp = await client.get(alt_api)
            alt_resp = resp.json()
            
            if alt_resp.get('code') == 0:
                data = alt_resp.get('data', {})
                return {
                    'title': data.get('title', 'محتوى تيك توك'),
                    'author': data.get('author', {}).get('nickname', 'مستخدم تيك توك'),
                    'music': data.get('music', None),
                    'images': data.get('images', []),
                    'play': data.get('play', None)
                }
        return None
    except Exception as e:
        print(f"Error fetching tiktok data: {e}")
        return None

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text if update.message and update.message.text else ""
    if not ("tiktok.com" in url):
        await update.message.reply_text("❌ أرسل رابط تيك توك صحيحاً من فضلك.")
        return

    processing_msg = await update.message.reply_text("⏰┇يرجى الانتظار، يتم جلب البيانات بسرعة...")

    try:
        context.user_data['current_url'] = url
        tiktok_data = await fetch_tiktok_data(url)
        
        if tiktok_data:
            images = tiktok_data['images']
            video_url = tiktok_data['play']
            
            keyboard = [
                [InlineKeyboardButton("🎵 تحميل كملف صوتي.", callback_data="audio")],
                [InlineKeyboardButton("📥 تحميل باعلى دقه HD.", callback_data="hd_video")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            if images:
                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO)
                total_images = len(images)
                for i in range(0, total_images, 10):
                    batch = images[i:i+10]
                    media_group = [InputMediaPhoto(media=img_url) for img_url in batch]
                    if media_group:
                        await update.message.reply_media_group(media=media_group)
                await processing_msg.delete()
                return

            elif video_url:
                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VIDEO)
                await update.message.reply_video(video=video_url, caption="- @G66Gbot", reply_markup=reply_markup)
                await processing_msg.delete()
                return

        await processing_msg.edit_text("⚠️ لم نتمكن من جلب البيانات، حاول مرة أخرى.")
    except Exception as e:
        print(f"Error in handle_message: {e}")
        await processing_msg.edit_text("⚠️ حدث ضغط عالٍ أو خطأ مؤقت، أعد المحاولة.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    url = context.user_data.get('current_url')
    
    if not url:
        await query.message.reply_text("❌ انتهت صلاحية الجلسة، أرسل الرابط مرة أخرى.")
        return

    if query.data == "audio":
        status_msg = await query.message.reply_text("🔄 جاري إرسال الملف الصوتي...")
        try:
            tiktok_data = await fetch_tiktok_data(url)
            audio_link = tiktok_data.get('music') if tiktok_data else None

            if audio_link:
                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VOICE)
                await context.bot.send_audio(chat_id=chat_id, audio=audio_link, caption="- @G66Gbot")
                await status_msg.delete()
                return
        except:
            pass
        await status_msg.edit_text("❌ حدث خطأ أثناء إرسال الصوت.")

    elif query.data == "hd_video":
        status_msg = await query.message.reply_text("🔄 جاري إرسال الفيديو...")
        try:
            tiktok_data = await fetch_tiktok_data(url)
            video_url = tiktok_data.get('play') if tiktok_data else None

            if video_url:
                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
                await context.bot.send_video(chat_id=chat_id, video=video_url, caption="- @G66Gbot")
                await status_msg.delete()
            else:
                await status_msg.edit_text("⚠️ تعذر إرسال الفيديو.")
        except:
            await status_msg.edit_text("⚠️ خطأ في الاتصال.")

def main():
    if not TOKEN:
        print("Error: TOKEN environment variable is not set!")
        return

    app = ApplicationBuilder().token(TOKEN).concurrent_updates(True).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    print("بوت تيك توك فائق السرعة يعمل الآن 24/7...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
