async def handle_youtube_callback(query, context, session, mode):
    url = session["url"]
    status_msg = await query.message.reply_text("🔄 جاري المعالجة وسحب الرابط...")

    try:
        payload = {
            "url": url,
            "vQuality": "720"
        }
        
        if mode in ["yt_audio", "yt_voice"]:
            payload["audioFormat"] = "mp3"

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        # طباعة معلومات للتشخيص في السجلات
        print(f"Sending request to Cobalt for URL: {url} with mode: {mode}")

        response = requests.post(COBALT_API_URL, json=payload, headers=headers, timeout=30)
        
        # طباعة حالة الاستجابة لتصحيح الأخطاء إن وجدت
        print(f"Cobalt response status: {response.status_code}")
        print(f"Cobalt response text: {response.text}")

        response.raise_for_status()
        data = response.json()

        download_url = data.get("url") or data.get("picker", [{}])[0].get("url")
        
        if not download_url:
            await status_msg.edit_text("❌ لم يتم العثور على رابط مباشر للتحميل من سيرفر كوبالت.")
            return

        await status_msg.edit_text("📥 جاري رفع الملف إلى تيليجرام...")

        if mode == "yt_audio":
            await query.message.reply_audio(audio=download_url, caption="- @G66Gbot")
        elif mode == "yt_voice":
            await query.message.reply_voice(voice=download_url, caption="- @G66Gbot")
        else:
            await query.message.reply_video(video=download_url, caption="- @G66Gbot")

        await status_msg.delete()

    except Exception as e:
        import traceback
        traceback.print_exc()  # هذا سيطبع الخطأ التفصيلي الكامل في لوحة السجلات (Logs)
        await status_msg.edit_text(f"⚠️ حدث خطأ تقني: {str(e)}")
