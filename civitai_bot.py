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
MIN_LIKES           = 1  # Минимальное количество лайков

HISTORY_FILE = "posted_ids.json"
HASHES_FILE  = "posted_hashes.json"
STATS_FILE   = "stats.json"

# Черный список тегов
BLACKLIST_TAGS = {
    "gore", "guro", "scat", "vore", "snuff", "necrophilia",
    "bestiality", "zoo", "loli", "shota", "child", "minor",
    "underage", "infant", "toddler"
}

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
    # Проверяем по тегам
    adult_tags = {
        "nsfw", "nsfw_", "explicit", "mature", "adult", "r18", "r18+", "18+",
        "sexy", "erotic", "seductive", "lingerie", "bikini", "nude", "naked",
        "breasts", "boobs", "tits", "butt", "ass", "pussy", "sex", "hentai",
        "ecchi", "lewd", "porn", "xxx", "sexually_suggestive"
    }
    
    tags_lower = set(t.lower() for t in tags)
    
    # Проверяем nsfwLevel из API (может быть строкой или числом)
    if item_data:
        nsfw_level = item_data.get("nsfwLevel")
        # nsfwLevel может быть: 1=SFW, 2=Soft, 3=Mature, 4=X
        # или строками: "SFW", "Soft", "Mature", "X"
        if nsfw_level:
            # Если это строка
            if isinstance(nsfw_level, str):
                if nsfw_level.upper() in ["X", "MATURE", "SOFT"]:
                    return True
            # Если это число
            elif isinstance(nsfw_level, (int, float)):
                if nsfw_level >= 2:  # Soft, Mature или X
                    return True
    
    # Проверяем по тегам
    return bool(tags_lower & adult_tags)

def add_watermark(data, text):
    try:
        img = Image.open(BytesIO(data)).convert("RGBA")
        w, h = img.size
        layer = Image.new("RGBA", img.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(layer)
        fsize = max(24, int(w * 0.045))
        
        # Поиск шрифта
        font = None
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
        ]
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
    params = {
        "limit": 50,
        "nsfw": "X",  # Запрашиваем только X-rated контент
        "sort": "Most Reactions",
        "period": "Day"
    }
    
    try:
        headers = {"Authorization": f"Bearer {CIVITAI_API_KEY}"} if CIVITAI_API_KEY else {}
        logger.info(f"Fetching images from CivitAI...")
        
        r = requests.get("https://civitai.com/api/v1/images", params=params, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        items = data.get("items", [])
        
        logger.info(f"Got {len(items)} items from API")
        
        if not items:
            logger.warning("No items returned from API")
            return []
        
        # Логируем первый элемент для отладки
        if items:
            first = items[0]
            logger.info(f"Sample item: ID={first.get('id')}, NSFW Level={first.get('nsfwLevel')}, Tags={len(first.get('tags', []))}")
        
        result = []
        for item in items:
            try:
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
                
                logger.info(f"✓ Added item {item['id']} with {likes} likes")
                
            except Exception as e:
                logger.error(f"Error processing item {item.get('id')}: {e}")
                continue
        
        logger.info(f"Found {len(result)} valid posts after filtering")
        return result
        
    except requests.exceptions.RequestException as e:
        logger.error(f"API Request Error: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
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
    logger.info(f"Selected item: {selected['id']} with {selected['likes']} likes and {len(selected['tags'])} tags")
    return selected

# ==================== MAIN ====================
async def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("No TELEGRAM_BOT_TOKEN found!")
        return
    
    if not CIVITAI_API_KEY:
        logger.error("No CIVITAI_API_KEY found!")
        return

    logger.info("Starting ErosLab Bot...")
    logger.info(f"Channel: {TELEGRAM_CHANNEL_ID}")
    logger.info(f"Min likes: {MIN_LIKES}")
    
    item = fetch_and_pick()
    
    if not item:
        logger.info("Nothing new to post")
        return

    # Скачивание изображения
    try:
        logger.info(f"Downloading from {item['url']}")
        r = requests.get(item["url"], timeout=60)
        r.raise_for_status()
        data = r.content
        logger.info(f"Downloaded {len(data)} bytes")
    except Exception as e:
        logger.error(f"Download Error: {e}")
        return

    # Проверка на дубликат контента по хэшу
    img_hash = hashlib.md5(data).hexdigest()
    if img_hash in posted_hashes:
        logger.warning(f"Duplicate content detected (hash: {img_hash[:8]}...)")
        posted_ids.add(item["id"])
        save_all()
        return

    # Отправка в Telegram
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    caption = " ".join(f"#{t}" for t in item["tags"]) + f"\n\n📢 {WATERMARK_TEXT}"

    try:
        # Определяем тип контента по расширению
        url_lower = item["url"].lower()
        if url_lower.endswith((".mp4", ".webm", ".gif")):
            logger.info("Sending as video/gif")
            await bot.send_video(chat_id=TELEGRAM_CHANNEL_ID, video=BytesIO(data), caption=caption)
        else:
            logger.info("Sending as image with watermark")
            final_data = add_watermark(data, WATERMARK_TEXT)
            await bot.send_photo(chat_id=TELEGRAM_CHANNEL_ID, photo=BytesIO(final_data), caption=caption)

        # Сохраняем в историю
        posted_ids.add(item["id"])
        posted_hashes.add(img_hash)
        stats["total_posts"] = stats.get("total_posts", 0) + 1
        
        # Обновляем статистику по тегам
        for tag in item["tags"][:5]:  # Топ-5 тегов
            stats["top_tags"][tag] = stats["top_tags"].get(tag, 0) + 1
        
        save_all()
        logger.info(f"✅ Successfully posted: {item['id']} (Total posts: {stats['total_posts']})")

    except Exception as e:
        logger.error(f"Telegram Send Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())