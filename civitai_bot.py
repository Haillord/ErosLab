"""
ErosLab Bot — CivitAI (только X и XXX рейтинг)
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
from caption_generator import generate_caption

# ==================== НАСТРОЙКИ ====================
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "@eroslabai")
CIVITAI_API_KEY     = os.environ.get("CIVITAI_API_KEY", "")

WATERMARK_TEXT   = "@eroslabai"
MIN_LIKES        = 20   # Минимум лайков для качественного контента
MIN_IMAGE_SIZE   = 512  # Минимальный размер изображения

HISTORY_FILE = "posted_ids.json"
HASHES_FILE  = "posted_hashes.json"
STATS_FILE   = "stats.json"

# Черный список тегов (запрещенный контент)
BLACKLIST_TAGS = {
    "gore", "guro", "scat", "vore", "snuff", "necrophilia",
    "bestiality", "zoo", "loli", "shota", "child", "minor",
    "underage", "infant", "toddler"
}

# Стоп-слова для хэштегов
HASHTAG_STOP_WORDS = {
    "score", "source", "rating", "version", "step", "steps", "cfg", "seed",
    "sampler", "model", "lora", "vae", "clip", "unet", "fp16", "safetensors",
    "checkpoint", "embedding", "none", "null", "true", "false", "and", "the",
    "for", "with", "masterpiece", "best", "quality", "high", "ultra", "detail",
    "detailed", "8k", "4k", "hd", "resolution", "simple", "background"
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# ==================== ХРАНИЛИЩА ====================
def load_json(path, default):
    """Безопасная загрузка JSON"""
    if Path(path).exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {path}: {e}")
    return default

def save_json(path, data):
    """Сохранение JSON с отступами"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

posted_ids    = set(load_json(HISTORY_FILE, []))
posted_hashes = set(load_json(HASHES_FILE, []))
stats         = load_json(STATS_FILE, {"total_posts": 0, "sources": {}, "top_tags": {}})

def save_all():
    """Сохранение всей истории"""
    save_json(HISTORY_FILE, list(posted_ids))
    save_json(HASHES_FILE,  list(posted_hashes))
    save_json(STATS_FILE,   stats)

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def clean_tags(tags):
    """Очистка и фильтрация тегов для хэштегов"""
    clean, seen = [], set()
    for t in tags:
        t = re.sub(r"[^\w]", "", str(t).strip().lower().replace(" ", "_").replace("-", "_"))
        if t and t not in HASHTAG_STOP_WORDS and t not in seen and 3 <= len(t) <= 30:
            clean.append(t)
            seen.add(t)
    return clean

def has_blacklisted(tags):
    """Проверка на запрещенные теги"""
    blacklisted = set(t.lower() for t in tags) & BLACKLIST_TAGS
    if blacklisted:
        logger.debug(f"Blacklisted: {blacklisted}")
        return True
    return False

def check_media_size(data, url):
    """Проверка размера медиафайла"""
    try:
        if not url.lower().endswith((".mp4", ".webm", ".gif")):
            img = Image.open(BytesIO(data))
            width, height = img.size
            if width >= MIN_IMAGE_SIZE and height >= MIN_IMAGE_SIZE:
                return True
            else:
                logger.warning(f"Image too small: {width}x{height}")
                return False
        else:
            logger.info("Video file, skipping size check")
            return True
    except Exception as e:
        logger.error(f"Error checking media size: {e}")
        return False

def add_watermark(data, text):
    """Добавление водяного знака (только для изображений)"""
    try:
        img = Image.open(BytesIO(data)).convert("RGBA")
        w, h = img.size
        layer = Image.new("RGBA", img.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(layer)
        fsize = max(24, int(w * 0.045))

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

# ==================== ТЕГИ ====================
def extract_tags(item):
    """
    Извлекает теги из поста CivitAI.
    Приоритет: item["tags"] (массив объектов) → meta.prompt
    """
    raw_tags = []

    # 1. Теги из официального поля CivitAI — самый надёжный источник
    civitai_tags = item.get("tags", [])
    if civitai_tags:
        for t in civitai_tags:
            if isinstance(t, dict):
                name = t.get("name", "")
            else:
                name = str(t)
            if name:
                raw_tags.append(name)
        logger.debug(f"CivitAI tags found: {len(raw_tags)}")

    # 2. Теги из AI-промпта (дополнение)
    meta = item.get("meta", {})
    prompt = meta.get("prompt", "") if meta else ""
    if prompt:
        for tag in prompt.split(","):
            tag = tag.strip()
            tag = re.sub(r'[\(\)\[\]\{\}]', '', tag)
            if tag and len(tag) > 2:
                raw_tags.append(tag)

    return clean_tags(raw_tags)

# ==================== CIVITAI API ====================
def fetch_civitai():
    """Запрос к API CivitAI — только X и XXX рейтинг"""

    variations = [
        {"limit": 100, "nsfw": "X",   "sort": "Most Reactions", "period": "Day"},
        {"limit": 100, "nsfw": "X",   "sort": "Most Reactions", "period": "Week"},
        {"limit": 100, "nsfw": "X",   "sort": "Newest",         "period": "Day"},
    ]

    for params in variations:
        try:
            headers = {"Authorization": f"Bearer {CIVITAI_API_KEY}"} if CIVITAI_API_KEY else {}
            r = requests.get(
                "https://civitai.com/api/v1/images",
                params=params,
                headers=headers,
                timeout=30
            )
            r.raise_for_status()
            data = r.json()
            items = data.get("items", [])

            logger.info(
                f"Got {len(items)} items "
                f"(nsfw={params['nsfw']}, sort={params['sort']}, period={params['period']})"
            )

            erotic_items = []
            for item in items:
                try:
                    nsfw_level = item.get("nsfwLevel")

                    # Берём только X и XXX
                    is_x_rating = False
                    if isinstance(nsfw_level, str) and nsfw_level.upper() in ["X", "XXX"]:
                        is_x_rating = True
                    elif isinstance(nsfw_level, (int, float)) and nsfw_level >= 4:
                        is_x_rating = True

                    if not is_x_rating:
                        continue

                    # Извлекаем теги (исправленная логика)
                    tags = extract_tags(item)

                    # Проверка на запрещённый контент
                    if has_blacklisted(tags):
                        continue

                    # Лайки
                    stats_data = item.get("stats", {})
                    likes = 0
                    if stats_data:
                        likes = (
                            stats_data.get("likeCount", 0)
                            + stats_data.get("heartCount", 0)
                        )

                    if likes < MIN_LIKES:
                        continue

                    erotic_items.append({
                        "id":     f"civitai_{item['id']}",
                        "url":    item.get("url", ""),
                        "tags":   tags[:15],
                        "likes":  likes,
                        "rating": nsfw_level
                    })

                    logger.debug(
                        f"✓ Added {item['id']} "
                        f"(rating:{nsfw_level}, likes:{likes}, tags:{len(tags)})"
                    )

                except Exception as e:
                    logger.error(f"Error processing item {item.get('id')}: {e}")
                    continue

            if erotic_items:
                logger.info(f"Found {len(erotic_items)} X/XXX rated posts")
                return erotic_items

        except Exception as e:
            logger.error(f"Error with params {params}: {e}")
            continue

    return []

def fetch_and_pick():
    """Получение и выбор случайного поста"""
    items = fetch_civitai()

    if not items:
        logger.warning("No items found from API")
        return None

    fresh = [i for i in items if i["id"] not in posted_ids]
    logger.info(f"Fresh items: {len(fresh)} out of {len(items)}")

    if not fresh:
        logger.info("No fresh items")
        return None

    selected = random.choice(fresh)
    logger.info(
        f"Selected: {selected['id']} "
        f"(rating:{selected['rating']}, likes:{selected['likes']}, tags:{len(selected['tags'])})"
    )
    return selected

# ==================== MAIN ====================
async def main():
    """Основная функция"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("No TELEGRAM_BOT_TOKEN found!")
        return

    if not CIVITAI_API_KEY:
        logger.error("No CIVITAI_API_KEY found!")
        return

    logger.info("=" * 50)
    logger.info("Starting ErosLab Bot")
    logger.info(f"Channel: {TELEGRAM_CHANNEL_ID}")
    logger.info(f"Min likes: {MIN_LIKES}")
    logger.info(f"Min image size: {MIN_IMAGE_SIZE}x{MIN_IMAGE_SIZE}")
    logger.info("=" * 50)

    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
    MAX_ATTEMPTS  = 10

    for attempt in range(MAX_ATTEMPTS):
        item = fetch_and_pick()

        if not item:
            logger.info("No more fresh posts available")
            return

        # Скачивание
        try:
            logger.info(f"Downloading: {item['url']}")
            r = requests.get(item["url"], timeout=60)
            r.raise_for_status()
            data = r.content
            logger.info(f"Downloaded {len(data)} bytes")
        except Exception as e:
            logger.error(f"Download Error: {e}")
            posted_ids.add(item["id"])
            save_all()
            continue

        # Проверка размера файла
        if len(data) > MAX_FILE_SIZE:
            logger.warning(f"File too large ({len(data)} bytes > 50MB), skipping")
            posted_ids.add(item["id"])
            save_all()
            continue

        # Проверка размера изображения
        if not item["url"].lower().endswith((".mp4", ".webm", ".gif")):
            if not check_media_size(data, item["url"]):
                logger.warning("Image size too small, skipping")
                posted_ids.add(item["id"])
                save_all()
                continue

        # Проверка на дубликат по хэшу
        img_hash = hashlib.md5(data).hexdigest()
        if img_hash in posted_hashes:
            logger.warning("Duplicate content detected")
            posted_ids.add(item["id"])
            save_all()
            continue

        break
    else:
        logger.error(f"No suitable post found after {MAX_ATTEMPTS} attempts")
        return

    # ========== ОТПРАВКА В TELEGRAM ==========
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    caption = generate_caption(item["tags"], item["rating"], item["likes"])

    logger.info(f"Tags for caption ({len(item['tags'])}): {item['tags'][:8]}")
    logger.info(f"Caption preview: {caption[:100]}")

    try:
        url_lower = item["url"].lower()
        if url_lower.endswith((".mp4", ".webm", ".gif")):
            logger.info("Sending as video/gif")
            await bot.send_video(
                chat_id=TELEGRAM_CHANNEL_ID,
                video=BytesIO(data),
                caption=caption,
                supports_streaming=True,
                write_timeout=60,
                read_timeout=60
            )
        else:
            logger.info("Sending as image with watermark")
            final_data = add_watermark(data, WATERMARK_TEXT)
            await bot.send_photo(
                chat_id=TELEGRAM_CHANNEL_ID,
                photo=BytesIO(final_data),
                caption=caption,
                write_timeout=60,
                read_timeout=60
            )

        posted_ids.add(item["id"])
        posted_hashes.add(img_hash)
        stats["total_posts"] = stats.get("total_posts", 0) + 1

        for tag in item["tags"][:5]:
            stats["top_tags"][tag] = stats["top_tags"].get(tag, 0) + 1

        save_all()
        logger.info(f"✅ Successfully posted: {item['id']}")
        logger.info(f"📊 Total posts: {stats['total_posts']}")

    except Exception as e:
        logger.error(f"Telegram Send Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())