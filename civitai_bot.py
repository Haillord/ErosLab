"""
ErosLab Bot — CivitAI (взрослый контент 16+, без указания лайков)
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

# Чёрный список — контент, который никогда не постим
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
    """Проверка на чёрный список (жесть, детское и т.д.)"""
    return bool(set(t.lower() for t in tags) & BLACKLIST_TAGS)

def is_adult_content(tags):
    """
    Определяет, является ли контент взрослым (16+)
    Возвращает True — постим, False — SFW, не постим
    """
    # Расширенный список взрослых тегов
    adult_tags = {
        # Базовые NSFW/эротика
        "nsfw", "nsfw_", "explicit", "mature", "adult", "r18", "r18+", "18+",
        
        # Эротика / сексуальная привлекательность
        "sexy", "erotic", "seductive", "alluring", "voluptuous", "curvy", "sensual", "provocative",
        "lingerie", "bikini", "swimsuit", "underwear", "panties", "bra", "stockings", "garter",
        "skimpy", "revealing", "lowcut", "plunging", "cleavage", "sideboob", "underboob",
        
        # Эччи / лёгкая эротика
        "lewd", "ecchi", "suggestive", "risque", "naughty", "playful", "teasing", "flirty",
        
        # Обнажёнка
        "nude", "naked", "topless", "bare_chest", "bare_breasts", "exposed", "uncensored",
        "nudity", "full_nudity", "partial_nudity", "implied_nudity",
        
        # Части тела
        "breasts", "boobs", "tits", "nipples", "areola", "cleavage_focus", "big_breasts", "small_breasts",
        "butt", "ass", "booty", "buttocks", "pussy", "vagina", "penis", "cock", "dick", "balls",
        "abs", "muscular", "toned", "athletic", "curves",
        
        # Сексуальные действия
        "sex", "fucking", "intercourse", "penetration", "blowjob", "bj", "oral", "cunnilingus",
        "handjob", "masturbation", "orgasm", "cum", "creampie", "facial", "cumshot", "splitting",
        "anal", "ahegao", "facial_expression", "orgasm_face",
        
        # BDSM / фетиш
        "bdsm", "bondage", "shibari", "rope", "restrained", "handcuffs", "blindfold", "gag",
        "dom", "sub", "dominant", "submissive", "leather", "latex", "pvc", "collar", "leash",
        "spanking", "whip", "flogger", "choking", "breathplay", "mask", "fetish",
        
        # Порно / хардкор
        "porn", "xxx", "hardcore", "hard", "hentai", "yaoi", "yuri", "futanari", "futa",
        "tentacles", "gangbang", "threesome", "group", "orgy", "public", "exhibitionism",
        "voyeurism", "gloryhole", "prostitution",
        
        # Специфические / фэнтези
        "furry", "anthro", "scalie", "monster", "demon", "succubus", "incubus", "alien",
        "tentacle", "mind_break", "corruption", "impregnation", "pregnancy", "milf", "dilf",
        
        # Разное
        "wet", "sweaty", "glossy", "shiny", "oiled", "tattoo", "piercing", "choker",
        "barely_clothed", "see_through", "transparent", "wet_shirt", "wrapped_towel",
        "bedroom_eyes", "come_hither", "inviting", "seductive_look"
    }
    
    # SFW теги (безопасный контент)
    sfw_tags = {
        "sfw", "cute", "wholesome", "smile", "happy", "family_friendly",
        "children", "kid", "family", "dog", "cat", "animal", "landscape",
        "scenery", "architecture", "food", "meal", "portrait", "realistic"
    }
    
    tags_lower = set(t.lower() for t in tags)
    
    # Если есть adult-теги — это взрослый контент
    if tags_lower & adult_tags:
        return True
    
    # Если есть только sfw-теги и нет adult — это SFW
    if tags_lower & sfw_tags:
        return False
    
    # Неопределённый случай — пропускаем (лучше больше, чем меньше)
    return True

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
    """Формирует подпись к посту (без указания лайков)"""
    htags = " ".join(f"#{t}" for t in item["tags"]) if item["tags"] else "#nsfw #ai #art"
    return f"{htags}\n\n📢 {WATERMARK_TEXT}"

# ==================== CIVITAI API ====================
def fetch_civitai():
    params = {
        "limit": 100,
        "nsfw": "X",
        "sort": random.choice(["Most Reactions", "Most Comments"]),
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
            
            if not is_adult_content(tags):
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
        logger.info(f"✅ Опубликовано [{item['source']}]")

    except telegram.error.TelegramError as e:
        logger.error(f"Telegram ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(main())