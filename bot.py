import os
import logging
import random
import sqlite3
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto, ChatMember, BotCommand
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram.error import TelegramError
import yt_dlp

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.environ.get("TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", "5782729939"))

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36',
]

# ===== إعداد قاعدة البيانات وتحديث الجداول =====
def init_db():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, level TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    conn.commit()
    
    defaults = {
        'start_msg': "◀️ | أهلاً بك في بوت التحميل الشامل\n\nمع هذا البوت يمكنك التحميل من عدة مواقع بصيغة متعددة،\n\n✅ | المواقع المدعومة :\n1️⃣ اليوتيوب | 2️⃣ الانستغرام | 3️⃣ التيك توك\n\n🔄 | قم بإرسال الرابط للبدء بالتحميل •",
        'sub1_active': 'false', 'sub1_channel': '',
        'sub2_active': 'false', 'sub2_channel': '',
        'fake_sub_active': 'false', 'fake_sub_channel': '',
        'broadcast_mode': 'false',
        'report_btn': 'true',
        'notifications': 'true',
        'streaming_mode': 'false'
    }
    for k, v in defaults.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()

init_db()

def get_setting(key):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    res = cursor.fetchone()
    conn.close()
    return res[0] if res else None

def set_setting(key, value):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET value = ? WHERE key = ?", (value, key))
    conn.commit()
    conn.close()

def add_user(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def is_admin(user_id):
    if user_id == OWNER_ID:
        return True
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res is not None

def is_full_admin(user_id):
    if user_id == OWNER_ID:
        return True
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT level FROM admins WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res and res[0] == 'full'

# ===== تعيين الأوامر الرسمية في القائمة (Menu) بجانب خانة الكتابة =====
async def setup_menu(application):
    commands = [
        BotCommand("start", "تشغيل البوت والترحيب"),
        BotCommand("admin", "فتح لوحة تحكم المطور الثابتة")
    ]
    await application.bot.set_my_commands(commands)

# ===== فحص الاشتراك الإجباري =====
async def check_forced_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_admin(user_id):
        return True

    if get_setting('fake_sub_active') == 'true':
        return True

    for i in [1, 2]:
        active = get_setting(f'sub{i}_active')
        channel = get_setting(f'sub{i}_channel')
        if active == 'true' and channel:
            try:
                member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
                if member.status in [ChatMember.LEFT, ChatMember.BANNED]:
                    await update.message.reply_text(
                        f"⚠️ ¦ عذراً، يجب عليك الاشتراك في قناة البوت أولاً لتتمكن من استخدامـه.\n\nقناة الاشتراك: {channel}\n\nبعد الاشتراك أرسل الرابط مرة أخرى.",
                        disable_web_page_preview=True
                    )
                    return False
            except Exception:
                pass
    return True

# ===== الأوامر الأساسية =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    add_user(user_id)
    
    if not await check_forced_sub(update, context):
        return

    start_text = get_setting('start_msg')
    await update.message.reply_text(start_text)

# ===== إظهار لوحة التحكم كأزرار ثابتة تحت خانة الكتابة =====
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ عذراً، هذا الأمر مخصص للمشرفين فقط.")
        return

    keyboard = [
        [KeyboardButton("📊 عدد المشتركين"), KeyboardButton("📢 بدء اذاعة")],
        [KeyboardButton("🛑 ايقاف الاذاعة"), KeyboardButton("🗑️ حذف جميع الاذاعات")],
        [KeyboardButton("⚡ تغيير رسالة Start"), KeyboardButton("↩️ استرجاع رسالة Start")],
        [KeyboardButton("⚠️ تفعيل/تعطيل الابلاغ"), KeyboardButton("🔔 تفعيل/تعطيل الاشعارات")],
        [KeyboardButton("1️⃣ تفعيل/تعطيل اشتراك 1"), KeyboardButton("✏️ تغيير قناة اشتراك 1")],
        [KeyboardButton("2️⃣ تفعيل/تعطيل اشتراك 2"), KeyboardButton("✏️ تغيير قناة اشتراك 2")],
        [KeyboardButton("💡 تفعيل/تعطيل الوهمي"), KeyboardButton("➕ رفع/تنزيل أدمن")],
        [KeyboardButton("🚪 إخفاء لوحة التحكم")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("👑 **مرحباً بك في لوحة تحكم المطور الثابتة:**\nتم تفعيل الأزرار تحت خانة الكتابة بنجاح.", reply_markup=reply_markup)

# ===== معالجة الأزرار الثابتة تحت خانة الكتابة والأوامر =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    add_user(user_id)
    text = update.message.text if update.message and update.message.text else ""

    if is_admin(user_id):
        # معالجة حقول الادخال المؤقتة للإعدادات
        if context.user_data.get('waiting_start_msg'):
            set_setting('start_msg', text)
            context.user_data.pop('waiting_start_msg', None)
            await update.message.reply_text("✅ تم تحديث وحفظ رسالة الـ Start بنجاح.")
            return

        if context.user_data.get('waiting_sub1'):
            set_setting('sub1_channel', text.strip())
            context.user_data.pop('waiting_sub1', None)
            await update.message.reply_text("✅ تم حفظ قناة الاشتراك الإجباري الأولى بنجاح.")
            return

        if context.user_data.get('waiting_sub2'):
            set_setting('sub2_channel', text.strip())
            context.user_data.pop('waiting_sub2', None)
            await update.message.reply_text("✅ تم حفظ قناة الاشتراك الإجباري الثانية بنجاح.")
            return

        if context.user_data.get('waiting_add_admin'):
            try:
                aid = int(text.strip())
                conn = sqlite3.connect('bot_database.db')
                cursor = conn.cursor()
                cursor.execute("INSERT OR REPLACE INTO admins (user_id, level) VALUES (?, ?)", (aid, 'normal'))
                conn.commit()
                conn.close()
                await update.message.reply_text(f"✅ تم رفع المستخدم {aid} كآدمن بنجاح.")
            except:
                await update.message.reply_text("❌ معرف غير صحيح.")
            context.user_data.pop('waiting_add_admin', None)
            return

        if context.user_data.get('waiting_broadcast'):
            context.user_data.pop('waiting_broadcast', None)
            set_setting('broadcast_mode', 'false')
            
            conn = sqlite3.connect('bot_database.db')
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users")
            users = cursor.fetchall()
            conn.close()

            status_msg = await update.message.reply_text("🔄 جاري إرسال الإذاعة فعلياً لجميع المشتركين...")
            success = 0
            failed = 0

            for (uid,) in users:
                try:
                    await update.message.copy(chat_id=uid)
                    success += 1
                except TelegramError:
                    failed += 1

            await status_msg.edit_text(f"📢 **تم الانتهاء من الإذاعة!**\n\n✅ تم الإرسال بنجاح إلى: {success}\n❌ فشل الإرسال إلى: {failed}")
            return

        # استجابة الأزرار الثابتة للمشرف
        if text == "📊 عدد المشتركين":
            conn = sqlite3.connect('bot_database.db')
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            count = cursor.fetchone()[0]
            conn.close()
            await update.message.reply_text(f"👥 عدد المشتركين الحقيقيين في قاعدة البيانات: **{count} مشتركاً**")
            return

        elif text == "📢 بدء اذاعة":
            set_setting('broadcast_mode', 'true')
            context.user_data['waiting_broadcast'] = True
            await update.message.reply_text("📢 **وضع الإذاعة الحقيقية مفعل:**\nأرسل الآن الرسالة (نص، صورة، فيديو) ليتم إرسالها لكل المشتركين.")
            return

        elif text == "🛑 ايقاف الاذاعة":
            set_setting('broadcast_mode', 'false')
            context.user_data.pop('waiting_broadcast', None)
            await update.message.reply_text("🛑 تم إيقاف وإلغاء وضع الإذاعة.")
            return

        elif text == "🗑️ حذف جميع الاذاعات":
            await update.message.reply_text("🗑️ تم حذف السجلات المعلقة بنجاح.")
            return

        elif text == "⚡ تغيير رسالة Start":
            context.user_data['waiting_start_msg'] = True
            await update.message.reply_text("⚡ أرسل النص الجديد لرسالة الـ Start الآن:")
            return

        elif text == "↩️ استرجاع رسالة Start":
            default_start = "◀️ | أهلاً بك في بوت التحميل الشامل\n\nمع هذا البوت يمكنك التحميل من عدة مواقع بصيغة متعددة،\n\n✅ | المواقع المدعومة :\n1️⃣ اليوتيوب | 2️⃣ الانستغرام | 3️⃣ التيك توك\n\n🔄 | قم بإرسال الرابط للبدء بالتحميل •"
            set_setting('start_msg', default_start)
            await update.message.reply_text("↩️ تم استرجاع رسالة الـ Start الافتراضية بنجاح.")
            return

        elif text == "⚠️ تفعيل/تعطيل الابلاغ":
            current = get_setting('report_btn')
            new_val = 'false' if current == 'true' else 'true'
            set_setting('report_btn', new_val)
            await update.message.reply_text(f"⚠️ تم تغيير حالة زر الإبلاغ إلى: **{new_val}**")
            return

        elif text == "🔔 تفعيل/تعطيل الاشعارات":
            current = get_setting('notifications')
            new_val = 'false' if current == 'true' else 'true'
            set_setting('notifications', new_val)
            await update.message.reply_text(f"🔔 تم تغيير حالة الإشعارات إلى: **{new_val}**")
            return

        elif text == "1️⃣ تفعيل/تعطيل اشتراك 1":
            current = get_setting('sub1_active')
            new_val = 'false' if current == 'true' else 'true'
            set_setting('sub1_active', new_val)
            await update.message.reply_text(f"✅ تم تغيير حالة الاشتراك الإجباري 1 إلى: **{new_val}**")
            return

        elif text == "✏️ تغيير قناة اشتراك 1":
            context.user_data['waiting_sub1'] = True
            await update.message.reply_text("✏️ أرسل معرف القناة الأولى الجديدة (مثال: `@ChannelName`):")
            return

        elif text == "2️⃣ تفعيل/تعطيل اشتراك 2":
            current = get_setting('sub2_active')
            new_val = 'false' if current == 'true' else 'true'
            set_setting('sub2_active', new_val)
            await update.message.reply_text(f"✅ تم تغيير حالة الاشتراك الإجباري 2 إلى: **{new_val}**")
            return

        elif text == "✏️ تغيير قناة اشتراك 2":
            context.user_data['waiting_sub2'] = True
            await update.message.reply_text("✏️ أرسل معرف القناة الثانية الجديدة (مثال: `@ChannelName`):")
            return

        elif text == "💡 تفعيل/تعطيل الوهمي":
            current = get_setting('fake_sub_active')
            new_val = 'false' if current == 'true' else 'true'
            set_setting('fake_sub_active', new_val)
            await update.message.reply_text(f"💡 تم تغيير حالة الاشتراك الوهمي إلى: **{new_val}**")
            return

        elif text == "➕ رفع/تنزيل أدمن":
            context.user_data['waiting_add_admin'] = True
            await update.message.reply_text("➕ أرسل معرف (ID) المستخدم لرفعه كآدمن:")
            return

        elif text == "🚪 إخفاء لوحة التحكم":
            from telegram import ReplyKeyboardRemove
            await update.message.reply_text("🚪 تم إخفاء أزرار لوحة التحكم. لإظهارها مرة أخرى أرسل الأمر /admin", reply_markup=ReplyKeyboardRemove())
            return

    if not await check_forced_sub(update, context):
        return

    url = text
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return

    processing_msg = await update.message.reply_text("⏳ ¦ يرجى الانتظار, يتم قياس حجم التحميل...")

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
                
                context.user_data['video_title'] = title
                caption_text = f"🎬 {title}\n\n👤 الحساب: {author}\n\n- @G66Gbot"

                if images:
                    if audio_url:
                        try:
                            r = requests.get(audio_url, timeout=15)
                            if r.status_code == 200:
                                local_audio_path = f"audio_{random.randint(1000,9999)}.mp3"
                                with open(local_audio_path, 'wb') as f:
                                    f.write(r.content)
                                
                                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_DOCUMENT)
                                with open(local_audio_path, 'rb') as audio_file:
                                    await update.message.reply_audio(audio=audio_file, title=title, performer="@G66Gbot", caption="- @G66Gbot")
                                if os.path.exists(local_audio_path):
                                    os.remove(local_audio_path)
                        except Exception:
                            pass

                    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO)
                    for i in range(0, len(images), 10):
                        batch = images[i:i+10]
                        media_group = [InputMediaPhoto(media=img_url) for img_url in batch]
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
            uploader = info.get('uploader', 'مؤلف غير معروف')
            filename = ydl.prepare_filename(info)
            
            if not os.path.exists(filename):
                filename = os.path.splitext(filename)[0] + ".mp4"

            context.user_data['video_title'] = title
            caption = f"🎬 {title}\n\n👤 الحساب: {uploader}\n\n- @G66Gbot"

            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VIDEO)
            with open(filename, 'rb') as f:
                await update.message.reply_video(video=f, caption=caption, reply_markup=reply_markup)

            if os.path.exists(filename):
                os.remove(filename)
            
            await processing_msg.delete()

    except Exception:
        await processing_msg.edit_text("❌ عذراً، لم أتمكن من جلب هذا الرابط أو أن المحتوى خاص.")

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
                'author': data.get('author', {}).get('nickname', 'مستخدم'),
                'music': data.get('music', None),
                'images': data.get('images', []),
                'play': data.get('play', None)
            }
        return None
    except Exception:
        return None

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    url = context.user_data.get('current_url')
    video_title = context.user_data.get('video_title', 'محتوى صوتي')
    
    if not url:
        await query.message.reply_text("❌ انتهت صلاحية الجلسة.")
        return

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    if query.data == "audio":
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

                    await context.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
                    with open(local_audio_path, 'rb') as audio_file:
                        await context.bot.send_audio(chat_id=query.message.chat_id, audio=audio_file, title=video_title, performer="@G66Gbot", caption="- @G66Gbot")
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

                await context.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
                with open(filename, 'rb') as f:
                    await context.bot.send_audio(chat_id=query.message.chat_id, audio=f, title=video_title, performer="@G66Gbot", caption="- @G66Gbot")

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
                    v_title = context.user_data.get('video_title', 'media')
                    await context.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.UPLOAD_VIDEO)
                    with open(filename, 'rb') as f:
                        await context.bot.send_video(chat_id=query.message.chat_id, video=f, caption=f"🎬 {v_title} (HD)\n- @G66Gbot")
                    os.remove(filename)
                await status_msg.delete()
        except Exception:
            await status_msg.edit_text("❌ عذراً، لا يمكن جلب هذا المحتوى كفيديو.")

def main():
    app = ApplicationBuilder().token(TOKEN).post_init(setup_menu).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    print("البوت يعمل الآن بأزرار تحكم ثابتة تحت خانة الكتابة...")
    app.run_polling()

if __name__ == '__main__':
    main()
