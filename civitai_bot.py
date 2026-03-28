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
import subprocess
import tempfile
import time
import requests
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import telegram
from telegram import Bot
from caption_generator import generate_caption
from rule34_api import fetch_rule34

# ==================== НАСТРОЙКИ ====================
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "@eroslabai")
CIVITAI_API_KEY     = os.environ.get("CIVITAI_API_KEY", "")

WATERMARK_TEXT   = "@eroslabai"
MIN_LIKES        = 20
MIN_IMAGE_SIZE   = 512

HISTORY_FILE = "posted_ids.json"
HASHES_FILE  = "posted_hashes.json"
# Максимум хранимых ID — чтобы файл не рос бесконечно
MAX_HISTORY_SIZE = 5000

BLACKLIST_TAGS = {
    "gore", "guro", "scat", "vore", "snuff", "necrophilia",
    "bestiality", "zoo", "loli", "shota", "child", "minor",
    "underage", "infant", "toddler", "1boy",
}

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
    if Path(path).exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {path}: {e}")
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

posted_ids    = set(load_json(HISTORY_FILE, []))
posted_hashes = set(load_json(HASHES_FILE, []))

def save_all():
    trimmed_ids    = list(posted_ids)[-MAX_HISTORY_SIZE:]
    trimmed_hashes = list(posted_hashes)[-MAX_HISTORY_SIZE:]
    save_json(HISTORY_FILE, trimmed_ids)
    save_json(HASHES_FILE,  trimmed_hashes)

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def clean_tags(tags):
    clean, seen = [], set()
    for t in tags:
        t = re.sub(r"[^\w]", "", str(t).strip().lower().replace(" ", "_").replace("-", "_"))
        # Фильтруем технические теги с цифрами в конце (monochrome075, drawn2 и т.д.)
        if re.search(r'\d+$', t):
            continue
        if t and t not in HASHTAG_STOP_WORDS and t not in seen and 3 <= len(t) <= 30:
            clean.append(t)
            seen.add(t)
    return clean

def has_blacklisted(tags):
    blacklisted = set(t.lower() for t in tags) & BLACKLIST_TAGS
    if blacklisted:
        logger.debug(f"Blacklisted: {blacklisted}")
        return True
    return False

def check_media_size(data, url):
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


def get_video_duration(data: bytes) -> float:
    """Возвращает длительность или 0.0 если видео битое"""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
               '-of', 'default=noprint_wrappers=1:nokey=1', tmp_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

        if result.returncode != 0:
            logger.warning("ffprobe failed to read video")
            return 0.0

        duration = float(result.stdout.strip())
        return duration

    except Exception as e:
        logger.error(f"Error: {e}")
        return 0.0
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)



# ==================== RETRY ДЛЯ TELEGRAM ====================
async def send_with_retry(func, *args, retries=3, **kwargs):
    for attempt in range(retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            if attempt == retries - 1:
                raise
            logger.warning(f"Telegram send failed (attempt {attempt + 1}/{retries}): {e}")
            await asyncio.sleep(2)

# ==================== ТЕГИ ====================
def extract_tags(item):
    raw_tags = []

    civitai_tags = item.get("tags", [])
    if civitai_tags:
        for t in civitai_tags:
            name = t.get("name", "") if isinstance(t, dict) else str(t)
            if name:
                raw_tags.append(name)
        logger.debug(f"CivitAI tags found: {len(raw_tags)}")

    if not raw_tags:
        prompt = item.get("meta", {}).get("prompt", "") if item.get("meta") else ""
        if prompt:
            tokens = re.split(r"[,\(\)\[\]|<>]+", prompt)
            for token in tokens:
                token = token.strip()
                if token:
                    raw_tags.append(token)
            logger.debug(f"Parsed {len(raw_tags)} tokens from meta.prompt")
        else:
            logger.debug("No tags and no prompt available")

    return clean_tags(raw_tags)


# ==================== CIVITAI API ====================
def _request_with_backoff(url, params, headers, max_retries=3):
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            if r.status_code == 429:
                wait = 2 ** attempt * 5
                logger.warning(f"Rate limited (429), waiting {wait}s before retry {attempt + 1}/{max_retries}")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout on attempt {attempt + 1}/{max_retries}")
            if attempt < max_retries - 1:
                time.sleep(3)
        except requests.exceptions.HTTPError as e:
            if r.status_code >= 500:
                logger.warning(f"Server error {r.status_code}, retry {attempt + 1}/{max_retries}")
                time.sleep(2 ** attempt * 2)
            else:
                raise
        except Exception as e:
            logger.error(f"Request error: {e}")
            raise
    return None

def fetch_civitai():
    variations = [
        # X рейтинг (6 вариантов)
        {"limit": 100, "nsfw": "X",   "sort": "Most Reactions", "period": "Day"},
        {"limit": 100, "nsfw": "X",   "sort": "Most Reactions", "period": "Week"},
        {"limit": 100, "nsfw": "X",   "sort": "Most Reactions", "period": "Month"},
        {"limit": 100, "nsfw": "X",   "sort": "Newest",         "period": "Day"},
        {"limit": 100, "nsfw": "X",   "sort": "Newest",         "period": "Week"},
        {"limit": 100, "nsfw": "X",   "sort": "Newest",         "period": "Month"},
        
        # XXX рейтинг (6 вариантов)
        {"limit": 100, "nsfw": "XXX", "sort": "Most Reactions", "period": "Day"},
        {"limit": 100, "nsfw": "XXX", "sort": "Most Reactions", "period": "Week"},
        {"limit": 100, "nsfw": "XXX", "sort": "Most Reactions", "period": "Month"},
        {"limit": 100, "nsfw": "XXX", "sort": "Newest",         "period": "Day"},
        {"limit": 100, "nsfw": "XXX", "sort": "Newest",         "period": "Week"},
        {"limit": 100, "nsfw": "XXX", "sort": "Newest",         "period": "Month"},
    ]

    headers = {"Authorization": f"Bearer {CIVITAI_API_KEY}"} if CIVITAI_API_KEY else {}

    for params in variations:
        try:
            r = _request_with_backoff(
                "https://civitai.com/api/v1/images",
                params=params,
                headers=headers
            )
            if r is None:
                logger.warning(f"No response for params {params}, trying next variation")
                continue

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

                    is_x_rating = False
                    if isinstance(nsfw_level, str) and nsfw_level.upper() in ["X", "XXX"]:
                        is_x_rating = True
                    elif isinstance(nsfw_level, (int, float)) and nsfw_level >= 4:
                        is_x_rating = True

                    if not is_x_rating:
                        continue

                    tags = extract_tags(item)

                    if has_blacklisted(tags):
                        continue

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
                        "id":      f"civitai_{item['id']}",
                        "url":     item.get("url", ""),
                        "tags":    tags[:15],
                        "likes":   likes,
                        "rating":  nsfw_level,
                        "post_id": item.get("postId"),
                        "source":  "civitai",
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

            logger.info("No suitable posts in this variation, trying next")

        except Exception as e:
            logger.error(f"Error with params {params}: {e}")
            continue

    return []

VIDEO_EXTENSIONS = (".mp4", ".webm", ".gif")

def _is_video(url: str) -> bool:
    return url.lower().endswith(VIDEO_EXTENSIONS)

def _pick_by_content_type(fresh):
    """50/50 видео или фото. Если нужного типа нет — берём что есть."""
    content_type = random.choice(['image', 'video'])
    logger.info(f"Content type selection: {content_type}")

    if content_type == 'video':
        typed = [i for i in fresh if _is_video(i["url"])]
        fallback = [i for i in fresh if not _is_video(i["url"])]
    else:
        typed = [i for i in fresh if not _is_video(i["url"])]
        fallback = [i for i in fresh if _is_video(i["url"])]

    logger.info(f"Items of selected type ({content_type}): {len(typed)}")

    if typed:
        return weighted_choice(typed)

    fallback_type = 'video' if content_type == 'image' else 'image'
    logger.info(f"No {content_type} items, falling back to {fallback_type}: {len(fallback)}")
    return weighted_choice(fallback) if fallback else None


def fetch_and_pick():
    # ── 50/50 выбор источника ──────────────────────────────────────────────
    source = random.choice(["civitai", "rule34"])
    logger.info(f"Source selected: {source}")

    if source == "civitai":
        items = fetch_civitai()
        if not items:
            logger.warning("CivitAI returned nothing, falling back to Rule34")
            source = "rule34"
            items = fetch_rule34(tags="animated 3d", limit=100)
    else:
        items = fetch_rule34(tags="animated 3d", limit=100)
        if not items:
            logger.warning("Rule34 returned nothing, falling back to CivitAI")
            source = "civitai"
            items = fetch_civitai()

    if not items:
        logger.warning("No items found from any source")
        return None

    fresh = [i for i in items if i["id"] not in posted_ids]
    logger.info(f"Fresh items: {len(fresh)} out of {len(items)} (source: {source})")

    if not fresh:
        logger.info("No fresh items")
        return None

    # ── Для CivitAI тип контента уже выбирается внутри fetch_civitai ──────
    # ── Для Rule34 делаем 50/50 видео/фото здесь ─────────────────────────
    if source == "rule34":
        selected = _pick_by_content_type(fresh)
    else:
        # CivitAI: оставляем старую логику 50/50 через weighted_choice
        content_type = random.choice(['image', 'video'])
        logger.info(f"Content type selection (civitai): {content_type}")

        if content_type == 'image':
            type_items = [i for i in fresh if not _is_video(i["url"])]
            fallback_items = [i for i in fresh if _is_video(i["url"])]
        else:
            type_items = [i for i in fresh if _is_video(i["url"])]
            fallback_items = [i for i in fresh if not _is_video(i["url"])]

        logger.info(f"Items of selected type ({content_type}): {len(type_items)}")

        if not type_items:
            fallback_type = 'video' if content_type == 'image' else 'image'
            logger.info(f"No {content_type} items found, trying {fallback_type}: {len(fallback_items)}")
            type_items = fallback_items

        if not type_items:
            logger.info("No suitable items found")
            return None

        selected = weighted_choice(type_items)

    if not selected:
        logger.info("No suitable items found after type filtering")
        return None

    logger.info(
        f"Selected: {selected['id']} "
        f"(source:{source}, rating:{selected['rating']}, "
        f"likes:{selected['likes']}, tags:{len(selected['tags'])})"
    )
    return selected


def weighted_choice(items):
    if not items:
        return None

    weights = [max(1, item["likes"]) for item in items]
    selected = random.choices(items, weights=weights, k=1)[0]

    logger.info(
        f"Weighted selection: {selected['id']} "
        f"(likes:{selected['likes']})"
    )

    return selected

# ==================== MAIN ====================
async def main():
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

        if len(data) > MAX_FILE_SIZE:
            logger.warning(f"File too large ({len(data)} bytes > 50MB), skipping")
            posted_ids.add(item["id"])
            save_all()
            continue

        if not item["url"].lower().endswith((".mp4", ".webm", ".gif")):
            if not check_media_size(data, item["url"]):
                logger.warning("Image size too small, skipping")
                posted_ids.add(item["id"])
                save_all()
                continue
        else:
            duration = get_video_duration(data)
            if duration < 0.5 or duration > 60:
                logger.warning(f"Video too short ({duration:.2f}s) or too long, skipping")
                posted_ids.add(item["id"])
                save_all()
                continue
            logger.info(f"Video duration: {duration:.2f}s")

        img_hash = hashlib.sha256(data).hexdigest()
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
    caption = generate_caption(
        tags=item["tags"],
        rating=item["rating"],
        likes=item["likes"],
        image_data=data,
        image_url=item["url"],
        watermark=WATERMARK_TEXT,
        suggestion="💬 Предложка: @Haillord"
    )

    logger.info(f"Tags for caption ({len(item['tags'])}): {item['tags'][:8]}")
    logger.info(f"Caption preview: {caption[:100]}")

    try:
        url_lower = item["url"].lower()
        if url_lower.endswith((".mp4", ".webm", ".gif")):
            logger.info("Sending as video/gif")
            
            # Используем видео без оптимизации
            video_data = data
            logger.info("Using original video (no optimization)")
            
            await send_with_retry(
                bot.send_video,
                chat_id=TELEGRAM_CHANNEL_ID,
                video=BytesIO(video_data),
                caption=caption,
                supports_streaming=True,
                write_timeout=60,
                read_timeout=60
            )
        else:
            logger.info("Sending as image without watermark")
            await send_with_retry(
                bot.send_photo,
                chat_id=TELEGRAM_CHANNEL_ID,
                photo=BytesIO(data),
                caption=caption,
                write_timeout=60,
                read_timeout=60
            )

        posted_ids.add(item["id"])
        posted_hashes.add(img_hash)
        save_all()
        logger.info(f"✅ Successfully posted: {item['id']}")

    except Exception as e:
        logger.error(f"Telegram Send Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())