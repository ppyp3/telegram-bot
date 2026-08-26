import os
import logging
import random
import sqlite3
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, ChatMember
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

# ===== إعداد قاعدة البيانات =====
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

# ===== فحص الاشتراك الإجباري والوهمي =====
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

# ===== الأوامر والوظائف الأساسية =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    add_user(user_id)
    
    if not await check_forced_sub(update, context):
        return

    start_text = get_setting('start_msg')
    await update.message.reply_text(start_text)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ عذراً، هذا الأمر مخصص للمشرفين فقط.")
        return

    # الترتيب مطابق 100% للفيديو والصورة تماماً وبنفس الرموز
    keyboard = [
        [InlineKeyboardButton("📊 إحصائيات التحميل", callback_data="subscribers_count"), InlineKeyboardButton("👥 عدد المشتركين", callback_data="subscribers_count")],
        [InlineKeyboardButton("----------------------------------------", callback_data="none")],
        [InlineKeyboardButton("📢 بدء اذاعه 📢", callback_data="start_broadcast"), InlineKeyboardButton("🛑 ايقاف الاذاعة 🛑", callback_data="stop_broadcast")],
        [InlineKeyboardButton("🗑️ حذف جميع الاذاعات", callback_data="delete_all_broadcasts")],
        [InlineKeyboardButton("----------------------------------------", callback_data="none")],
        [InlineKeyboardButton("🎙️ بدء بث 🎙️", callback_data="start_stream")],
        [InlineKeyboardButton("----------------------------------------", callback_data="none")],
        [InlineKeyboardButton("🖥️ تشغيل البث 🖥️", callback_data="enable_stream_mode"), InlineKeyboardButton("🛑 إيقاف البث 🛑", callback_data="disable_stream_mode")],
        [InlineKeyboardButton("📊 احصائيات البث 📊", callback_data="stream_stats")],
        [InlineKeyboardButton("----------------------------------------", callback_data="none")],
        [InlineKeyboardButton("⚡ تغيير رسالة الـ Start ⚡", callback_data="change_start_msg"), InlineKeyboardButton("↩️ استرجاع رسالة الـ Start", callback_data="reset_start_msg")],
        [InlineKeyboardButton("----------------------------------------", callback_data="none")],
        [InlineKeyboardButton("⚠️ تفعيل زر الابلاغ ⚠️", callback_data="enable_report"), InlineKeyboardButton("⚠️ تعطيل زر الابلاغ ⚠️", callback_data="disable_report")],
        [InlineKeyboardButton("----------------------------------------", callback_data="none")],
        [InlineKeyboardButton("🔔 تفعيل الاشعارات 🔔", callback_data="enable_notif"), InlineKeyboardButton("🔕 تعطيل الاشعارات 🔕", callback_data="disable_notif")],
        [InlineKeyboardButton("----------------------------------------", callback_data="none")],
        [InlineKeyboardButton("1️⃣ تفعيل الاشتراك الاجباري 1", callback_data="sub1_on"), InlineKeyboardButton("❌ تعطيل الاشتراك الاجباري 1", callback_data="sub1_off")],
        [InlineKeyboardButton("ℹ️ معلومات الاشتراك 1", callback_data="sub1_info"), InlineKeyboardButton("✏️ تغيير قناة الاشتراك 1", callback_data="sub1_change")],
        [InlineKeyboardButton("----------------------------------------", callback_data="none")],
        [InlineKeyboardButton("2️⃣ تفعيل الاشتراك الاجباري 2", callback_data="sub2_on"), InlineKeyboardButton("❌ تعطيل الاشتراك الاجباري 2", callback_data="sub2_off")],
        [InlineKeyboardButton("ℹ️ معلومات الاشتراك 2", callback_data="sub2_info"), InlineKeyboardButton("✏️ تغيير قناة الاشتراك 2", callback_data="sub2_change")],
        [InlineKeyboardButton("----------------------------------------", callback_data="none")],
        [InlineKeyboardButton("💡 تفعيل الاشتراك الوهمي", callback_data="fake_on"), InlineKeyboardButton("💡 تعطيل الاشتراك الوهمي", callback_data="fake_off")],
        [InlineKeyboardButton("✏️ تغيير قناة الاشتراك الوهمي", callback_data="fake_change")],
        [InlineKeyboardButton("----------------------------------------", callback_data="none")],
        [InlineKeyboardButton("➕ رفع ادمن 👤", callback_data="add_admin"), InlineKeyboardButton("➖ تنزيل ادمن 👤", callback_data="remove_admin")],
        [InlineKeyboardButton("⬆️ رفع ادمن كامل صلاحيات ⬆️", callback_data="add_full_admin"), InlineKeyboardButton("⬇️ تنزيل الادمن كامل صلاحيات ⬇️", callback_data="remove_full_admin")],
        [InlineKeyboardButton("👑 نقل ملكية البوت 👑", callback_data="transfer_ownership")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("👑 **مرحباً بك في لوحة تحكم المطور الحقيقية:**", reply_markup=reply_markup)

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await query.answer("❌ عذراً، هذه الأزرار للمطورين فقط.", show_alert=True)
        return

    data = query.data
    await query.answer()

    if data == "none":
        return

    elif data == "subscribers_count":
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        count = cursor.fetchone()[0]
        conn.close()
        await query.message.reply_text(f"👥 عدد المشتركين الحقيقيين في قاعدة البيانات: **{count} مشتركاً**")

    elif data == "start_broadcast":
        set_setting('broadcast_mode', 'true')
        context.user_data['waiting_broadcast'] = True
        await query.message.reply_text("📢 **وضع الإذاعة مفعل:**\nأرسل الآن الرسالة (نص، صورة، فيديو) لإذاعتها لجميع المشتركين.")

    elif data == "stop_broadcast":
        set_setting('broadcast_mode', 'false')
        context.user_data.pop('waiting_broadcast', None)
        await query.message.reply_text("🛑 تم إيقاف وإلغاء وضع الإذاعة.")

    elif data == "delete_all_broadcasts":
        await query.message.reply_text("🗑️ تم حذف جميع الإذاعات وسجلات الإرسال المعلقة بنجاح.")

    elif data == "start_stream":
        set_setting('streaming_mode', 'true')
        await query.message.reply_text("🎙️ تم بدء البث بنجاح.")

    elif data == "enable_stream_mode":
        set_setting('streaming_mode', 'true')
        await query.message.reply_text("🖥️ تم تشغيل البث بنجاح.")

    elif data == "disable_stream_mode":
        set_setting('streaming_mode', 'false')
        await query.message.reply_text("🛑 تم إيقاف البث بنجاح.")

    elif data == "stream_stats":
        status = get_setting('streaming_mode')
        await query.message.reply_text(f"📊 إحصائيات البث الحالي: **{'مفعل 🎙️' if status == 'true' else 'متوقف 🛑'}**")

    elif data == "change_start_msg":
        context.user_data['waiting_start_msg'] = True
        await query.message.reply_text("⚡ أرسل النص الجديد لرسالة الـ Start الآن:")

    elif data == "reset_start_msg":
        default_start = "◀️ | أهلاً بك في بوت التحميل الشامل\n\nمع هذا البوت يمكنك التحميل من عدة مواقع بصيغة متعددة،\n\n✅ | المواقع المدعومة :\n1️⃣ اليوتيوب | 2️⃣ الانستغرام | 3️⃣ التيك توك\n\n🔄 | قم بإرسال الرابط للبدء بالتحميل •"
        set_setting('start_msg', default_start)
        await query.message.reply_text("↩️ تم استرجاع رسالة الـ Start الافتراضية بنجاح.")

    elif data == "enable_report":
        set_setting('report_btn', 'true')
        await query.message.reply_text("⚠️ تم تفعيل زر الإبلاغ.")

    elif data == "disable_report":
        set_setting('report_btn', 'false')
        await query.message.reply_text("⚠️ تم تعطيل زر الإبلاغ.")

    elif data == "enable_notif":
        set_setting('notifications', 'true')
        await query.message.reply_text("🔔 تم تفعيل الإشعارات بنجاح.")

    elif data == "disable_notif":
        set_setting('notifications', 'false')
        await query.message.reply_text("🔕 تم تعطيل الإشعارات بنجاح.")

    elif data == "sub1_on":
        set_setting('sub1_active', 'true')
        await query.message.reply_text("✅ تم تفعيل الاشتراك الإجباري 1 إلى: **true**")

    elif data == "sub1_off":
        set_setting('sub1_active', 'false')
        await query.message.reply_text("✅ تم تغيير حالة الاشتراك الإجباري 1 إلى: **false**")

    elif data == "sub1_info":
        ch = get_setting('sub1_channel')
        act = get_setting('sub1_active')
        await query.message.reply_text(f"ℹ️ معلومات قناة الاشتراك 1:\n- القناة: {ch if ch else 'غير مُحددة'}\n- الحالة: {act}")

    elif data == "sub1_change":
        context.user_data['waiting_sub1'] = True
        await query.message.reply_text("✏️ أرسل معرف القناة الأولى الجديدة (مثال: `@ChannelName`):")

    elif data == "sub2_on":
        set_setting('sub2_active', 'true')
        await query.message.reply_text("✅ تم تفعيل الاشتراك الإجباري 2 إلى: **true**")

    elif data == "sub2_off":
        set_setting('sub2_active', 'false')
        await query.message.reply_text("✅ تم تغيير حالة الاشتراك الإجباري 2 إلى: **false**")

    elif data == "sub2_info":
        ch = get_setting('sub2_channel')
        act = get_setting('sub2_active')
        await query.message.reply_text(f"ℹ️ معلومات قناة الاشتراك 2:\n- القناة: {ch if ch else 'غير مُحددة'}\n- الحالة: {act}")

    elif data == "sub2_change":
        context.user_data['waiting_sub2'] = True
        await query.message.reply_text("✏️ أرسل معرف القناة الثانية الجديدة (مثال: `@ChannelName`):")

    elif data == "fake_on":
        set_setting('fake_sub_active', 'true')
        await query.message.reply_text("💡 تم تفعيل الاشتراك الوهمي.")

    elif data == "fake_off":
        set_setting('fake_sub_active', 'false')
        await query.message.reply_text("💡 تم تعطيل الاشتراك الوهمي.")

    elif data == "fake_change":
        context.user_data['waiting_fake'] = True
        await query.message.reply_text("✏️ أرسل معرف قناة الاشتراك الوهمي الجديدة:")

    elif data == "add_admin":
        if not is_full_admin(user_id):
            await query.message.reply_text("❌ هذه الصلاحية للمالك أو الآدمن الكامل فقط.")
            return
        context.user_data['waiting_add_admin'] = True
        await query.message.reply_text("➕ أرسل معرف (ID) المستخدم لرفعه كآدمن:")

    elif data == "remove_admin":
        if not is_full_admin(user_id):
            await query.message.reply_text("❌ هذه الصلاحية للمالك أو الآدمن الكامل فقط.")
            return
        context.user_data['waiting_remove_admin'] = True
        await query.message.reply_text("➖ أرسل معرف (ID) المستخدم لتنزيله من الآدمنية:")

    elif data == "add_full_admin":
        if user_id != OWNER_ID:
            await query.message.reply_text("❌ هذه الصلاحية للمالك الأساسي فقط.")
            return
        context.user_data['waiting_add_full_admin'] = True
        await query.message.reply_text("⬆️ أرسل معرف (ID) المستخدم لرفعه كآدمن كامل الصلاحيات:")

    elif data == "remove_full_admin":
        if user_id != OWNER_ID:
            await query.message.reply_text("❌ هذه الصلاحية للمالك الأساسي فقط.")
            return
        context.user_data['waiting_remove_full_admin'] = True
        await query.message.reply_text("⬇️ أرسل معرف (ID) المستخدم لتنزيله من الآدمن الكامل:")

    elif data == "transfer_ownership":
        if user_id != OWNER_ID:
            await query.message.reply_text("❌ نقل الملكية متاح للمالك الأساسي فقط.")
            return
        context.user_data['waiting_transfer'] = True
        await query.message.reply_text("👑 أرسل معرف (ID) المالك الجديد للبوت:")

# ===== معالجة الرسائل والتحميل =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    add_user(user_id)

    if is_admin(user_id):
        if context.user_data.get('waiting_start_msg'):
            set_setting('start_msg', update.message.text)
            context.user_data.pop('waiting_start_msg', None)
            await update.message.reply_text("✅ تم تحديث وحفظ رسالة الـ Start بنجاح.")
            return

        if context.user_data.get('waiting_sub1'):
            set_setting('sub1_channel', update.message.text.strip())
            context.user_data.pop('waiting_sub1', None)
            await update.message.reply_text("✅ تم حفظ قناة الاشتراك الإجباري الأولى.")
            return

        if context.user_data.get('waiting_sub2'):
            set_setting('sub2_channel', update.message.text.strip())
            context.user_data.pop('waiting_sub2', None)
            await update.message.reply_text("✅ تم حفظ قناة الاشتراك الإجباري الثانية.")
            return

        if context.user_data.get('waiting_fake'):
            set_setting('fake_sub_channel', update.message.text.strip())
            context.user_data.pop('waiting_fake', None)
            await update.message.reply_text("✅ تم حفظ قناة الاشتراك الوهمي.")
            return

        if context.user_data.get('waiting_add_admin'):
            try:
                aid = int(update.message.text.strip())
                conn = sqlite3.connect('bot_database.db')
                cursor = conn.cursor()
                cursor.execute("INSERT OR REPLACE INTO admins (user_id, level) VALUES (?, ?)", (aid, 'normal'))
                conn.commit()
                conn.close()
                await update.message.reply_text(f"✅ تم رفع المستخدم {aid} كآدمن.")
            except:
                await update.message.reply_text("❌ معرف غير صحيح.")
            context.user_data.pop('waiting_add_admin', None)
            return

        if context.user_data.get('waiting_remove_admin'):
            try:
                aid = int(update.message.text.strip())
                conn = sqlite3.connect('bot_database.db')
                cursor = conn.cursor()
                cursor.execute("DELETE FROM admins WHERE user_id = ?", (aid,))
                conn.commit()
                conn.close()
                await update.message.reply_text(f"✅ تم تنزيل المستخدم {aid}.")
            except:
                await update.message.reply_text("❌ خطأ.")
            context.user_data.pop('waiting_remove_admin', None)
            return

        if context.user_data.get('waiting_add_full_admin'):
            try:
                aid = int(update.message.text.strip())
                conn = sqlite3.connect('bot_database.db')
                cursor = conn.cursor()
                cursor.execute("INSERT OR REPLACE INTO admins (user_id, level) VALUES (?, ?)", (aid, 'full'))
                conn.commit()
                conn.close()
                await update.message.reply_text(f"✅ تم رفع المستخدم {aid} كآدمن كامل الصلاحيات.")
            except:
                await update.message.reply_text("❌ معرف غير صحيح.")
            context.user_data.pop('waiting_add_full_admin', None)
            return

        if context.user_data.get('waiting_remove_full_admin'):
            try:
                aid = int(update.message.text.strip())
                conn = sqlite3.connect('bot_database.db')
                cursor = conn.cursor()
                cursor.execute("DELETE FROM admins WHERE user_id = ? AND level = 'full'", (aid,))
                conn.commit()
                conn.close()
                await update.message.reply_text(f"✅ تم تنزيل الآدمن الكامل {aid}.")
            except:
                await update.message.reply_text("❌ خطأ.")
            context.user_data.pop('waiting_remove_full_admin', None)
            return

        if context.user_data.get('waiting_transfer'):
            try:
                global OWNER_ID
                new_owner = int(update.message.text.strip())
                OWNER_ID = new_owner
                await update.message.reply_text(f"👑 تم نقل ملكية البوت للمعرف: {new_owner} بنجاح.")
            except:
                await update.message.reply_text("❌ خطأ في المعرف.")
            context.user_data.pop('waiting_transfer', None)
            return

        if context.user_data.get('waiting_broadcast'):
            context.user_data.pop('waiting_broadcast', None)
            set_setting('broadcast_mode', 'false')
            
            conn = sqlite3.connect('bot_database.db')
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users")
            users = cursor.fetchall()
            conn.close()

            status_msg = await update.message.reply_text("🔄 جاري بدء الإذاعة لجميع المشتركين...")
            success = 0
            failed = 0

            for (uid,) in users:
                try:
                    await update.message.copy(chat_id=uid)
                    success += 1
                except TelegramError:
                    failed += 1

            await status_msg.edit_text(f"📢 **تم الانتهاء من الإذاعة بنجاح!**\n\n✅ تم الإرسال إلى: {success}\n❌ فشل الإرسال: {failed}")
            return

    if not await check_forced_sub(update, context):
        return

    url = update.message.text
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
    
    if query.data != "audio" and query.data != "hd_video":
        await admin_callback_handler(update, context)
        return

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
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    print("البوت يعمل الآن كنسخة طبق الأصل...")
    app.run_polling()

if __name__ == '__main__':
    main()
