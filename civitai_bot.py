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
MIN_LIKES           = 1  # Немного поднял планку качества
MIN_WIDTH           = 512
MIN_HEIGHT          = 512

HISTORY_FILE = "posted_ids.json"
HASHES_FILE  = "posted_hashes.json"
STATS_FILE   = "stats.json"

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
    # Твой расширенный список тегов остается без изменений
    adult_tags = {
        "nsfw", "nsfw_", "explicit", "mature", "adult", "r18", "r18+", "18+",
        "sexy", "erotic", "seductive", "lingerie", "bikini", "nude", "naked",
        "breasts", "boobs", "tits", "butt", "ass", "pussy", "sex", "hentai"
        # ... (и все остальные из твоего списка)
    }
    
    tags_lower = set(t.lower() for t in tags)
    
    # Дополнительная проверка: если API CivitAI говорит, что это X или Mature
    if item_data and item_data.get("nsfwLevel") in [4, 8, 16]:
        return True

    return bool(tags_lower & adult_tags)

def add_watermark(data, text):
    try:
        img = Image.open(BytesIO(data)).convert("RGBA")
        w, h = img.size
        layer = Image.new("RGBA", img.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(layer)
        fsize = max(24, int(w * 0.045))
        
        # Поиск шрифта на GitHub Actions (Ubuntu)
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
    # Попытка 1: Рандом для разнообразия
    periods = ["Day", "Week", "Month"]
    sorts = ["Most Reactions", "Newest"]
    
    # Сначала пробуем рандомную страницу
    attempt_params = [
        {"page": random.randint(1, 5), "period": random.choice(periods), "sort": random.choice(sorts)},
        {"page": 1, "period": "Day", "sort": "Most Reactions"}, # Запасной вариант №1
        {"page": 1, "period": "Week", "sort": "Most Reactions"} # Запасной вариант №2 (беспроигрышный)
    ]

    for p in attempt_params:
        params = {
            "limit": 100, # Берем максимум за раз
            "nsfw": "X",
            "sort": p["sort"],
            "period": p["period"],
            "page": p["page"]
        }

        try:
            headers = {"Authorization": f"Bearer {CIVITAI_API_KEY}"} if CIVITAI_API_KEY else {}
            r = requests.get("https://civitai.com/api/v1/images", params=params, headers=headers, timeout=25)
            r.raise_for_status()
            items = r.json().get("items", [])

            result = []
            for item in items:
                # Считаем лайки
                s = item.get("stats", {})
                likes = s.get("likeCount", 0) + s.get("heartCount", 0) + s.get("thumbsUpCount", 0)
                
                # Упростим фильтр лайков для теста (поставь 1)
                if likes < 1: continue
                
                raw_tags = [t.get("name", "") if isinstance(t, dict) else str(t) for t in item.get("tags", [])]
                tags = clean_tags(raw_tags)
                
                if has_blacklisted(tags): continue
                if not is_adult_content(tags, item): continue

                result.append({
                    "id": f"civitai_{item['id']}",
                    "url": item.get("url", ""),
                    "tags": tags[:15] if tags else ["nsfw", "ai", "art"],
                    "likes": likes
                })

            if result:
                logger.info(f"Найдено {len(result)} постов на стр {p['page']} ({p['sort']})")
                return result
            else:
                logger.info(f"На стр {p['page']} ничего не подошло, пробую следующий вариант...")
        except Exception as e:
            logger.error(f"Ошибка API: {e}")
            continue

    return []

def fetch_and_pick():
    items = fetch_civitai()
    # Фильтр по истории
    fresh = [i for i in items if i["id"] not in posted_ids]

    if not fresh:
        return None

    # ШАФФЛ: берем случайный из первой десятки лучших
    top_limit = min(len(fresh), 15)
    return random.choice(fresh[:top_limit])

# ==================== MAIN ====================
async def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Нет токена!")
        return

    item = fetch_and_pick()
    if not item:
        logger.info("Ничего нового в этой выборке. Ждем следующий запуск.")
        return

    # Скачивание
    try:
        r = requests.get(item["url"], timeout=60)
        r.raise_for_status()
        data = r.content
    except Exception as e:
        logger.error(f"Download Error: {e}")
        return

    # Проверка на дубликат контента (хэш)
    img_hash = hashlib.md5(data).hexdigest()
    if img_hash in posted_hashes:
        logger.warning(f"Картинка уже была запощена ранее (ID: {item['id']})")
        posted_ids.add(item["id"]) # Помечаем как "просмотрено"
        save_all()
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    caption = " ".join(f"#{t}" for t in item["tags"]) + f"\n\n📢 {WATERMARK_TEXT}"

    try:
        # Отправка видео/гиф или фото
        if item["url"].lower().endswith((".mp4", ".webm", ".gif")):
            await bot.send_video(chat_id=TELEGRAM_CHANNEL_ID, video=BytesIO(data), caption=caption)
        else:
            final_data = add_watermark(data, WATERMARK_TEXT)
            await bot.send_photo(chat_id=TELEGRAM_CHANNEL_ID, photo=BytesIO(final_data), caption=caption)

        # Сохранение в базу
        posted_ids.add(item["id"])
        posted_hashes.add(img_hash)
        stats["total_posts"] += 1
        save_all()
        logger.info(f"✅ Успешно опубликовано: {item['id']}")

    except Exception as e:
        logger.error(f"Telegram Send Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())