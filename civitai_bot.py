"""
ErosLab Bot — Только CivitAI (MIN_LIKES = 10)
"""

import asyncio
import hashlib
import json
import logging
import os
import random
import re
import requests
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import telegram
from telegram import Bot

# ==================== НАСТРОЙКИ ====================
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "@eroslabai")
CIVITAI_API_KEY     = os.environ.get("CIVITAI_API_KEY", "")

WATERMARK_TEXT      = "@eroslabai"
MIN_LIKES           = 1
MIN_WIDTH           = 512
MIN_HEIGHT          = 512
FETCH_LIMIT         = 80

HISTORY_FILE = "posted_ids.json"
HASHES_FILE  = "posted_hashes.json"
STATS_FILE   = "stats.json"

BLACKLIST_TAGS = {"gore", "guro", "scat", "vore", "snuff", "necrophilia",
                  "bestiality", "zoo", "loli", "shota", "child", "minor",
                  "underage", "infant", "toddler"}

HASHTAG_STOP_WORDS = {"score", "source", "rating", "version", "step", "steps", "cfg", "seed",
                      "sampler", "model", "lora", "vae", "clip", "unet", "fp16", "safetensors",
                      "checkpoint", "embedding", "none", "null", "true", "false", "and", "the",
                      "for", "with", "masterpiece", "best", "quality", "high", "ultra", "detail",
                      "detailed", "8k", "4k", "hd", "resolution", "simple", "background"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ==================== ХРАНИЛИЩА ====================
def load_json(path, default):
    if Path(path).exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

posted_ids    = set(load_json(HISTORY_FILE, []))
posted_hashes = set(load_json(HASHES_FILE, []))
stats         = load_json(STATS_FILE, {"total_posts": 0, "sources": {}, "top_tags": {}})

def save_all():
    save_json(HISTORY_FILE, list(posted_ids))
    save_json(HASHES_FILE,  list(posted_hashes))
    save_json(STATS_FILE,   stats)

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def clean_tags(tags):
    clean, seen = [], set()
    for t in tags:
        t = re.sub(r"[^\w]", "", t.strip().lower().replace(" ", "_").replace("-", "_"))
        if t and t not in HASHTAG_STOP_WORDS and t not in seen and 3 <= len(t) <= 30:
            clean.append(t)
            seen.add(t)
    return clean

def has_blacklisted(tags):
    return bool(set(t.lower() for t in tags) & BLACKLIST_TAGS)

def download(url):
    try:
        headers = {"User-Agent": "ErosLabBot/1.0 (+https://github.com/Haillord/eroslab-bot)"}
        r = requests.get(url, timeout=60, headers=headers)
        r.raise_for_status()
        return r.content
    except Exception as e:
        logger.error(f"Скачивание: {e}")
        return None

def is_duplicate(data):
    h = hashlib.md5(data).hexdigest()
    if h in posted_hashes:
        return True
    posted_hashes.add(h)
    return False

def check_resolution(data):
    try:
        img = Image.open(BytesIO(data))
        w, h = img.size
        return w >= MIN_WIDTH and h >= MIN_HEIGHT
    except Exception:
        return True

def add_watermark(data, text):
    try:
        img = Image.open(BytesIO(data)).convert("RGBA")
        w, h = img.size
        layer = Image.new("RGBA", img.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(layer)
        fsize = max(24, int(w * 0.045))
        font = None
        for fp in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                   "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]:
            try:
                font = ImageFont.truetype(fp, fsize)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x, y = w - tw - 24, h - th - 24

        draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, 160))
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 230))

        out = BytesIO()
        Image.alpha_composite(img, layer).convert("RGB").save(out, format="JPEG", quality=92)
        return out.getvalue()
    except Exception as e:
        logger.error(f"Watermark: {e}")
        return data

def build_caption(item):
    htags = " ".join(f"#{t}" for t in item["tags"]) if item["tags"] else "#nsfw #ai #art"
    return f"{htags}\n\n❤️ {item['likes']} реакций • {item['source']}\n📢 {WATERMARK_TEXT}"

# ==================== ТОЛЬКО CIVITAI ====================
def fetch_civitai():
    params = {
        "limit": 100,
        "nsfw": "X",                    # Mature даёт хороший баланс NSFW
        "sort": random.choice(["Most Reactions", "Most Comments", "Newest"]),
        "period": "AllTime",
    }

    try:
        headers = {"Authorization": f"Bearer {CIVITAI_API_KEY}"} if CIVITAI_API_KEY else {}
        r = requests.get("https://civitai.com/api/v1/images",
                         params=params, headers=headers, timeout=20)
        r.raise_for_status()
        data = r.json()

        result = []
        for item in data.get("items", []):
            stats = item.get("stats", {})
            likes = (stats.get("likeCount", 0) +
                     stats.get("heartCount", 0) +
                     stats.get("thumbsUpCount", 0))

            if likes < MIN_LIKES:
                continue

            tags = clean_tags(_civitai_tags(item))
            if has_blacklisted(tags):
                continue

            result.append({
                "id": f"civitai_{item['id']}",
                "url": item.get("url", ""),
                "tags": tags[:15],
                "likes": likes,
                "source": "CivitAI"
            })

        logger.info(f"CivitAI: найдено {len(result)} подходящих изображений")
        return result

    except Exception as e:
        logger.error(f"CivitAI: {e}")
        return []

def _civitai_tags(item):
    raw = item.get("tags", [])
    if raw:
        return [t.get("name", "") if isinstance(t, dict) else str(t) for t in raw]

    prompt = (item.get("meta") or {}).get("prompt", "")
    if prompt:
        parts = re.split(r"[,|]", prompt)
        return [re.sub(r"[<>(){}\[\]\\/*\d]+", "", p).strip().lower().replace(" ", "_")
                for p in parts[:25]]
    return []

# ==================== ВЫБОР ПОСТА ====================
def fetch_and_pick():
    items = fetch_civitai()
    fresh = [i for i in items if i["id"] not in posted_ids]

    if not fresh:
        logger.warning("Не найдено новых постов на CivitAI")
        return None

    fresh.sort(key=lambda x: x["likes"], reverse=True)
    return fresh[0]

# ==================== MAIN ====================
async def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не задан!")
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"Бот @{me.username} запущен → {TELEGRAM_CHANNEL_ID}")

    item = fetch_and_pick()
    if not item:
        logger.info("Сегодня ничего не постим")
        return

    data = download(item["url"])
    if not data:
        return

    if is_duplicate(data):
        logger.warning("Дубликат по хэшу")
        save_all()
        return

    is_video = item["url"].lower().endswith((".mp4", ".webm", ".gif"))
    if not is_video and not check_resolution(data):
        logger.warning("Слишком маленькое разрешение")
        return

    caption = build_caption(item)

    try:
        if is_video:
            await bot.send_video(chat_id=TELEGRAM_CHANNEL_ID, video=BytesIO(data),
                                 caption=caption, supports_streaming=True)
        else:
            watermarked = add_watermark(data, WATERMARK_TEXT)
            await bot.send_photo(chat_id=TELEGRAM_CHANNEL_ID, photo=BytesIO(watermarked), caption=caption)

        posted_ids.add(item["id"])
        stats["total_posts"] = stats.get("total_posts", 0) + 1
        stats["sources"]["CivitAI"] = stats["sources"].get("CivitAI", 0) + 1
        for tag in item["tags"]:
            stats["top_tags"][tag] = stats["top_tags"].get(tag, 0) + 1

        save_all()
        logger.info(f"✅ Опубликовано [{item['source']}] ❤️{item['likes']}")

    except telegram.error.TelegramError as e:
        logger.error(f"Telegram ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(main())