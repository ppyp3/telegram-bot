import requests
from bs4 import BeautifulSoup

def download_pinterest(url):
    try:
        # التعامل مع الروابط المختصرة pin.it
        if "pin.it" in url:
            response = requests.get(url, allow_redirects=True)
            url = response.url

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, headers=headers)
        soup = BeautifulSoup(resp.text, 'html.parser')

        # البحث عن الفيديو
        video_tag = soup.find("meta", property="og:video")
        if video_tag and video_tag.get("content"):
            return {"type": "video", "url": video_tag["content"]}

        # البحث عن الصورة بجودة أصلية
        image_tag = soup.find("meta", property="og:image")
        if image_tag and image_tag.get("content"):
            img_url = image_tag["content"]
            img_url = img_url.replace("236x", "originals").replace("474x", "originals")
            return {"type": "photo", "url": img_url}

    except Exception as e:
        print(f"Pinterest Error: {e}")
    
    return None
