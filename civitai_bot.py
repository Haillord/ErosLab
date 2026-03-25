"""
ErosLab Bot — CivitAI (взрослый контент 16+, без указания лайков)
Оптимизирован для GitHub Actions с защитой от повторов.
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
MIN_LIKES           = 1  # Временно поставил 1 для теста
MIN_WIDTH           = 512
MIN_HEIGHT          = 512

HISTORY_FILE = "posted_ids.json"
HASHES_FILE  = "posted_hashes.json"
STATS_FILE   = "stats.json"

# Временно отключим черный список для теста
BLACKLIST_TAGS = set()  # Пустой набор для теста

HASHTAG_STOP_WORDS = {
    "score", "source", "rating", "version", "step", "steps", "cfg", "seed",
    "sampler", "model", "lora", "vae", "clip", "unet", "fp16", "safetensors",
    "checkpoint", "embedding", "none", "null", "true", "false", "and", "the",
    "for", "with", "masterpiece", "best", "quality", "high", "ultra", "detail",
    "detailed", "8k", "4k", "hd", "resolution", "simple", "background"
}

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
        t = re.sub(r"[^\w]", "", str(t).strip().lower().replace(" ", "_").replace("-", "_"))
        if t and t not in HASHTAG_STOP_WORDS and t not in seen and 3 <= len(t) <= 30:
            clean.append(t)
            seen.add(t)
    return clean

def has_blacklisted(tags):
    return bool(set(t.lower() for t in tags) & BLACKLIST_TAGS)

def is_adult_content(tags, item_data=None):
    # Упрощенная проверка на NSFW
    # Проверяем по тегам
    adult_keywords = ["nsfw", "explicit", "mature", "adult", "r18", "sexy", "erotic"]
    tags_lower = set(t.lower() for t in tags)
    
    # Проверяем по nsfwLevel из API
    nsfw_level = item_data.get("nsfwLevel", 0) if item_data else 0
    
    # nsfwLevel: 1=SFW, 2=Soft, 3=Mature, 4=X
    return nsfw_level >= 2 or bool(tags_lower & set(adult_keywords))

def add_watermark(data, text):
    try:
        img = Image.open(BytesIO(data)).convert("RGBA")
        w, h = img.size
        layer = Image.new("RGBA", img.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(layer)
        fsize = max(24, int(w * 0.045))
        
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
        ]
        font = None
        for fp in font_paths:
            if os.path.exists(fp):
                font = ImageFont.truetype(fp, fsize)
                break
        if not font:
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
        logger.error(f"Watermark Error: {e}")
        return data

# ==================== CIVITAI API ====================
def fetch_civitai():
    # Сначала проверим, работает ли API
    test_url = "https://civitai.com/api/v1/images"
    test_params = {"limit": 1, "nsfw": "X"}
    
    try:
        headers = {"Authorization": f"Bearer {CIVITAI_API_KEY}"} if CIVITAI_API_KEY else {}
        logger.info(f"Testing API connection...")
        
        # Пробуем несколько разных параметров
        variations = [
            {"limit": 50, "nsfw": "X", "sort": "Most Reactions", "period": "Day"},
            {"limit": 50, "nsfw": "X", "sort": "Most Reactions", "period": "Week"},
            {"limit": 50, "nsfw": "X", "sort": "Newest", "period": "Day"},
            {"limit": 50, "nsfw": "All", "sort": "Most Reactions", "period": "Week"},
        ]
        
        for params in variations:
            try:
                logger.info(f"Trying params: {params}")
                r = requests.get(test_url, params=params, headers=headers, timeout=30)
                r.raise_for_status()
                data = r.json()
                items = data.get("items", [])
                
                logger.info(f"Got {len(items)} items from API")
                
                if not items:
                    logger.info("No items in response")
                    continue
                
                # Покажем первый элемент для отладки
                if items:
                    logger.info(f"Sample item: {items[0].get('id')}, NSFW: {items[0].get('nsfwLevel')}")
                
                result = []
                for item in items:
                    # Получаем лайки
                    stats_data = item.get("stats", {})
                    likes = stats_data.get("likeCount", 0) + stats_data.get("heartCount", 0)
                    
                    # Получаем теги
                    raw_tags = []
                    for tag in item.get("tags", []):
                        if isinstance(tag, dict):
                            raw_tags.append(tag.get("name", ""))
                        else:
                            raw_tags.append(str(tag))
                    
                    tags = clean_tags(raw_tags)
                    
                    # Проверка на взрослый контент
                    if not is_adult_content(tags, item):
                        logger.debug(f"Skipping {item['id']} - not adult content")
                        continue
                    
                    # Проверка на черный список
                    if has_blacklisted(tags):
                        logger.debug(f"Skipping {item['id']} - blacklisted tags")
                        continue
                    
                    # Проверка лайков
                    if likes < MIN_LIKES:
                        logger.debug(f"Skipping {item['id']} - low likes: {likes}")
                        continue
                    
                    # Формируем результат
                    result.append({
                        "id": f"civitai_{item['id']}",
                        "url": item.get("url", ""),
                        "tags": tags[:15] if tags else ["nsfw", "ai", "art"],
                        "likes": likes
                    })
                    
                    logger.info(f"Added item {item['id']} with {likes} likes")
                
                if result:
                    logger.info(f"Found {len(result)} valid posts")
                    return result
                else:
                    logger.info(f"No valid posts found with params {params}")
                    
            except Exception as e:
                logger.error(f"Error with params {params}: {e}")
                continue
                
    except Exception as e:
        logger.error(f"API Error: {e}")
        
    return []

def fetch_and_pick():
    items = fetch_civitai()
    
    if not items:
        logger.warning("No items found from API")
        return None
    
    # Фильтруем по истории
    fresh = [i for i in items if i["id"] not in posted_ids]
    logger.info(f"Fresh items: {len(fresh)} out of {len(items)}")
    
    if not fresh:
        logger.info("No fresh items")
        return None
    
    # Выбираем случайный из свежих
    selected = random.choice(fresh)
    logger.info(f"Selected item: {selected['id']} with {selected['likes']} likes")
    return selected

# ==================== MAIN ====================
async def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Нет токена!")
        return
    
    if not CIVITAI_API_KEY:
        logger.error("Нет API ключа CivitAI!")
        return

    logger.info("Starting bot...")
    item = fetch_and_pick()
    
    if not item:
        logger.info("Nothing new to post")
        return

    # Скачивание
    try:
        logger.info(f"Downloading from {item['url']}")
        r = requests.get(item["url"], timeout=60)
        r.raise_for_status()
        data = r.content
        logger.info(f"Downloaded {len(data)} bytes")
    except Exception as e:
        logger.error(f"Download Error: {e}")
        return

    # Проверка на дубликат контента
    img_hash = hashlib.md5(data).hexdigest()
    if img_hash in posted_hashes:
        logger.warning(f"Duplicate content detected")
        posted_ids.add(item["id"])
        save_all()
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    caption = " ".join(f"#{t}" for t in item["tags"]) + f"\n\n📢 {WATERMARK_TEXT}"

    try:
        # Отправка
        if item["url"].lower().endswith((".mp4", ".webm", ".gif")):
            await bot.send_video(chat_id=TELEGRAM_CHANNEL_ID, video=BytesIO(data), caption=caption)
        else:
            final_data = add_watermark(data, WATERMARK_TEXT)
            await bot.send_photo(chat_id=TELEGRAM_CHANNEL_ID, photo=BytesIO(final_data), caption=caption)

        # Сохранение
        posted_ids.add(item["id"])
        posted_hashes.add(img_hash)
        stats["total_posts"] += 1
        save_all()
        logger.info(f"✅ Successfully posted: {item['id']}")

    except Exception as e:
        logger.error(f"Telegram Send Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())