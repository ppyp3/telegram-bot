import os
import logging
import random
import requests
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler

# إعداد السجلات
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.environ.get("TOKEN")
BOT_USERNAME = "@G66GBOT"
ADMIN_IDS = [5782729939] # ضع معرف الآدمن الخاص بك هنا

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
        f"▫︎ بوت تحميل يوتيوب وتيك توك السريع 📥\n"
        f"▫︎ فيديوهات • صور • صوتيات\n\n"
        f"⚡ أرسل الرابط أو ابحث بالاسم الآن للبدء 🔻"
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

# ==================== قسم يوتيوب (روابط ومعاينة) ====================
async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    if "youtube.com" not in url and "youtu.be" not in url:
        return

    sent_msg = await update.message.reply_text("⏳ جاري جلب معلومات الفيديو...")

    ydl_opts = {"quiet": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title", "فيديو يوتيوب")
            uploader = info.get("uploader", "قناة غير معروفة")
            duration_sec = info.get("duration", 0)
            views = info.get("view_count", 0)
            thumbnail = info.get("thumbnail", None)

            minutes = duration_sec // 60
            seconds = duration_sec % 60
            duration_str = f"{minutes:02d}:{seconds:02d}"

            if views and views >= 1_000_000:
                views_str = f"{views / 1_000_000:.1f}M"
            elif views and views >= 1_000:
                views_str = f"{views / 1_000:.1f}K"
            else:
                views_str = str(views or 0)
    except Exception as e:
        await sent_msg.edit_text("❌ عذراً، لم أتمكن من جلب معلومات هذا الرابط.")
        return

    caption = f"🎬 {title}\n"
    caption += f"👤 {uploader}\n"
    caption += f"⏱ {duration_str} - 👁 {views_str}\n"

    keyboard = [
        [
            InlineKeyboardButton("🎞 | مقطع فيديو.", callback_data=f"yt_vid|{url}"),
        ],
        [
            InlineKeyboardButton("🔊 | بصمة صوتية.", callback_data=f"yt_voice|{url}"),
            InlineKeyboardButton("🎵 | ملف صوتي.", callback_data=f"yt_audio|{url}"),
        ],
        [
            InlineKeyboardButton("🔄 | شارك.", url=f"https://t.me/share/url?url={url}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await sent_msg.delete()
    if thumbnail:
        await update.message.reply_photo(
            photo=thumbnail, caption=caption, reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(caption, reply_markup=reply_markup)

# ==================== قسم يوتيوب (البحث المتقدم) ====================
async def search_youtube_paginated(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1, query: str = None):
    is_callback = update.callback_query is not None

    if not query:
        query = update.message.text
        if query.startswith("/"):
            return
        sent_msg = await update.message.reply_text("🔍 | جاري البحث في اليوتيوب...")
    else:
        sent_msg = update.callback_query.message

    results_per_page = 5
    offset = (page - 1) * results_per_page

    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "default_search": f"ytsearch{offset + results_per_page}",
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            results = ydl.extract_info(query, download=False)
            all_entries = results.get("entries", [])
    except Exception as e:
        if is_callback:
            await update.callback_query.answer("❌ حدث خطأ أثناء البحث.")
        else:
            await sent_msg.edit_text("❌ حدث خطأ أثناء البحث، حاول مرة أخرى.")
        return

    if not all_entries:
        if is_callback:
            await update.callback_query.answer("❌ لم يتم العثور على نتائج.")
        else:
            await sent_msg.edit_text("❌ لم يتم العثور على نتائج مطابقة لبحثك.")
        return

    entries = all_entries[offset:offset + results_per_page]
    if not entries:
        if is_callback:
            await update.callback_query.answer("هذه هي الصفحة الأخيرة.")
        return

    response_text = f"🔎 | نتائج بحث اليوتيوب لـ \"{query}\"\n\n"

    for item in entries:
        title = item.get("title", "بدون عنوان")
        duration_sec = item.get("duration", 0)
        views = item.get("view_count", 0)
        video_id = item.get("id", "")

        if duration_sec:
            minutes = duration_sec // 60
            seconds = duration_sec % 60
            duration_str = f"{minutes:02d}:{seconds:02d}"
        else:
            duration_str = "00:00"

        if views and views >= 1_000_000:
            views_str = f"{views / 1_000_000:.1f}M"
        elif views and views >= 1_000:
            views_str = f"{views / 1_000:.1f}K"
        else:
            views_str = str(views or 0)

        response_text += f"🎬 {title}\n"
        response_text += f"👤 {BOT_USERNAME}\n"
        response_text += f"⏱ {duration_str} - 👁 {views_str}\n"
        response_text += f"🔗 https://youtu.be/{video_id}\n\n"

    keyboard = []
    nav_buttons = []

    if page > 1:
        nav_buttons.append(InlineKeyboardButton("« السابق", callback_data=f"search_page|{query}|{page - 1}"))

    if len(all_entries) > offset + results_per_page:
        nav_buttons.append(InlineKeyboardButton("التالي »", callback_data=f"search_page|{query}|{page + 1}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)

    if is_callback:
        await update.callback_query.edit_message_text(response_text, reply_markup=reply_markup)
        await update.callback_query.answer()
    else:
        await sent_msg.edit_text(response_text, reply_markup=reply_markup)

# ==================== قسم تيك توك (بدون أي تعديل على كودك الأساسي) ====================
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

async def handle_tiktok_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    processing_msg = await update.message.reply_text("⏰┇يرجى الانتظار، يتم قياس حجم التحميل...")

    try:
        context.user_data['current_url'] = url
        
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

        error_custom_msg = (
            "⚠️┇هذا الملف لا يمكنني تحميله،\n"
            "⚠️┇لأن حجمه يتجاوز ( 50 Mbps )،\n"
            "⚠️┇أعد المحاوله مع ملف اخر."
        )
        await processing_msg.edit_text(error_custom_msg)

    except Exception as e:
        print(f"Error in handle_tiktok_message: {e}")
        error_custom_msg = (
            "⚠️┇هذا الملف لا يمكنني تحميله،\n"
            "⚠️┇لأن حجمه يتجاوز ( 50 Mbps )،\n"
            "⚠️┇أعد المحاوله مع ملف اخر."
        )
        await processing_msg.edit_text(error_custom_msg)

# ==================== الموجه العام للرسائل ====================
async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text if update.message and update.message.text else ""

    if user_id in ADMIN_IDS:
        if text == "🚪 إخفاء لوحة التحكم":
            await update.message.reply_text("🚪 تم إخفاء لوحة التحكم. لإظهارها أرسل /admin", reply_markup=ReplyKeyboardRemove())
            return
        elif text.startswith("📊") or text.startswith("📢") or text.startswith("🛑") or text.startswith("🗑️") or "-------------------------------------" in text:
            await update.message.reply_text(f"⚙️ تم استقبال الأمر: {text}")
            return

    if "tiktok.com" in text:
        await handle_tiktok_message(update, context)
    elif "youtube.com" in text or "youtu.be" in text:
        await handle_youtube_link(update, context)
    else:
        # إذا مو رابط تيك توك أو يوتيوب، يعتبره بحث في يوتيوب
        await search_youtube_paginated(update, context)

# ==================== معالج الأزرار الموحد (يوتيوب + تيك توك) ====================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    chat_id = query.message.chat_id

    # 1. معالجة صفحات البحث لليوتيوب
    if data.startswith("search_page|"):
        _, search_query, page_str = data.split("|", 2)
        await search_youtube_paginated(update, context, page=int(page_str), query=search_query)
        return

    # 2. معالجة تحميل أزرار يوتيوب
    if data.startswith("yt_"):
        try:
            action, url = data.split("|", 1)
        except ValueError:
            return

        await query.answer("⏳ جاري التحميل والمعالجة، يرجى الانتظار...")
        os.makedirs("downloads", exist_ok=True)

        if action == "yt_vid":
            ydl_opts = {
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'outtmpl': 'downloads/%(id)s.%(ext)s',
                'quiet': True
            }
        elif action in ["yt_audio", "yt_voice"]:
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': 'downloads/%(id)s.%(ext)s',
                'quiet': True
            }
        else:
            return

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if action in ["yt_audio", "yt_voice"]:
                    filename = os.path.splitext(filename)[0] + ".mp3"
                
                title = info.get('title', 'media')
                duration_sec = info.get('duration', 0)

                minutes = duration_sec // 60
                seconds = duration_sec % 60
                duration_str = f"{minutes:02d}:{seconds:02d}"

                file_size_bytes = os.path.getsize(filename)
                file_size_mb = f"{file_size_bytes / (1024 * 1024):.1f}MB"

            footer_caption = f"{BOT_USERNAME} - {duration_str}, {file_size_mb}"

            share_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 | شارك.", url=f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME.replace('@','')}")]
            ])

            if action == "yt_vid":
                await query.message.reply_video(
                    video=open(filename, 'rb'),
                    caption=f"🎬 {title}\n{footer_caption}",
                    reply_markup=share_keyboard,
                    supports_streaming=True
                )
            elif action == "yt_voice":
                await query.message.reply_voice(
                    voice=open(filename, 'rb'),
                    caption=f"🎵 {title}\n{footer_caption}",
                    reply_markup=share_keyboard
                )
            elif action == "yt_audio":
                await query.message.reply_audio(
                    audio=open(filename, 'rb'),
                    title=title,
                    caption=f"🎵 {title}\n{footer_caption}",
                    reply_markup=share_keyboard
                )

            if os.path.exists(filename):
                os.remove(filename)

        except Exception as e:
            await query.message.reply_text("❌ حدث خطأ أثناء تحميل الملف، يرجى المحاولة لاحقاً.")
        return

    # 3. معالجة أزرار تيك توك الأساسية (كما هي بدون تغيير)
    await query.answer()
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
                            performer="@G66Gbot", 
                            caption="- @G66Gbot"
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
                    caption="- @G66Gbot", 
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
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_router))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("بوت يوتيوب وتيك توك يعمل الآن بكفاءة وسرعة عالية...")
    app.run_polling()

if __name__ == '__main__':
    main()
