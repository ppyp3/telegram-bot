import os
import random
import tempfile
from pathlib import Path
import requests
import logging

logger = logging.getLogger(__name__)

MAX_MEDIA_SIZE = 49 * 1024 * 1024

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
]

class DownloadTooLarge(Exception):
    pass

def request_headers():
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
    }
    return headers

def download_media(url, suffix):
    temporary_path = None
    headers = request_headers()
    
    if "pinterest" in url or "pinimg" in url:
        headers["Referer"] = "https://www.pinterest.com/"

    try:
        with requests.get(
            url, headers=headers, timeout=(8, 30), stream=True
        ) as response:
            response.raise_for_status()

            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > MAX_MEDIA_SIZE:
                        raise DownloadTooLarge
                except ValueError:
                    pass

            with tempfile.NamedTemporaryFile(
                delete=False, suffix=suffix
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                downloaded = 0

                for chunk in response.iter_content(chunk_size=128 * 1024):
                    if not chunk:
                        continue

                    downloaded += len(chunk)

                    if downloaded > MAX_MEDIA_SIZE:
                        raise DownloadTooLarge

                    temporary_file.write(chunk)

        return temporary_path

    except Exception:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)
        raise
