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
from quality_filter import QualityFilter, filter_posts_by_quality
from watermark import add_watermark, should_add_watermark

# ==================== НАСТРОЙКИ ====================
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "@eroslabai")
CIVITAI_API_KEY     = os.environ.get("CIVITAI_API_KEY", "")

WATERMARK_TEXT   = "@eroslabai"
MIN_LIKES        = 5
MIN_IMAGE_SIZE   = 512

HISTORY_FILE = "posted_ids.json"
HASHES_FILE  = "posted_hashes.json"
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
    """Возвращает длительность видео в секундах или 0.0 если файл нечитаем."""
    tmp_path = None
    # FIX: инициализируем duration_str заранее, чтобы избежать NameError в except ValueError
    duration_str = "N/A"
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

        duration_str = result.stdout.strip()

        if not duration_str or duration_str == 'N/A':
            logger.warning(f"ffprobe returned: '{duration_str}'")
            return 0.0

        duration = float(duration_str)
        return duration

    except ValueError as e:
        logger.error(f"Error converting duration '{duration_str}' to float: {e}")
        return 0.0
    except Exception as e:
        logger.error(f"Error getting video duration: {e}")
        return 0.0
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

def get_video_thumbnail(data: bytes) -> bytes:
    """Извлекает первый кадр видео как JPEG bytes для vision."""
    tmp_in = None
    tmp_out = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp.write(data)
            tmp_in = tmp.name

        tmp_out = tmp_in + "_thumb.jpg"

        cmd = [
            'ffmpeg', '-y', '-i', tmp_in,
            '-ss', '2', '-vframes', '1',
            '-vf', 'scale=512:-1',
            '-q:v', '3',
            tmp_out
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=10)

        if result.returncode != 0:
            logger.warning("ffmpeg thumbnail extraction failed")
            return None

        with open(tmp_out, 'rb') as f:
            thumb_data = f.read()

        logger.info(f"Thumbnail extracted: {len(thumb_data)} bytes")
        return thumb_data

    except Exception as e:
        logger.error(f"Thumbnail error: {e}")
        return None
    finally:
        if tmp_in and os.path.exists(tmp_in):
            os.unlink(tmp_in)
        if tmp_out and os.path.exists(tmp_out):
            os.unlink(tmp_out)

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
    """
    HTTP GET с экспоненциальным backoff при 429 и 5xx.
    Переменная r объявлена до цикла, чтобы избежать NameError в except-ветках.
    """
    r = None
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
            # r гарантированно не None здесь, потому что HTTPError бросает raise_for_status()
            if r is not None and r.status_code >= 500:
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
        {"limit": 100, "nsfwLevel": 31, "browsingLevel": 31, "sort": "Most Reactions", "period": "Day"},
        {"limit": 100, "nsfwLevel": 31, "browsingLevel": 31, "sort": "Most Reactions", "period": "Week"},
        {"limit": 100, "nsfwLevel": 31, "browsingLevel": 31, "sort": "Most Reactions", "period": "Month"},
        {"limit": 100, "nsfwLevel": 31, "browsingLevel": 31, "sort": "Newest",         "period": "Day"},
        {"limit": 100, "nsfwLevel": 31, "browsingLevel": 31, "sort": "Newest",         "period": "Week"},
        {"limit": 100, "nsfwLevel": 31, "browsingLevel": 31, "sort": "Newest",         "period": "Month"},
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

            # FIX: используем правильные имена ключей из словаря params
            logger.info(
                f"Got {len(items)} items "
                f"(nsfwLevel={params['nsfwLevel']}, sort={params['sort']}, period={params.get('period', 'All')})"
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


def fetch_and_pick_with_quality():
    """
    Выбор поста с фильтром качества + категория AI.
    Возвращает (item, data) или None.
    Данные скачиваются ОДИН РАЗ здесь, чтобы main() не делал повторный запрос.
    """
    source = random.choice(["civitai", "rule34", "rule34_ai"])
    logger.info(f"Source selected: {source}")

    if source == "rule34_ai":
        from rule34_api import AI_TAG_SETS
        tags = random.choice(AI_TAG_SETS)
        logger.info(f"AI Category mode: using tags '{tags}'")
        items = fetch_rule34(tags=tags, limit=100)
        if items:
            for i in items:
                i["source"] = "rule34_ai"

    elif source == "civitai":
        items = fetch_civitai()
        if not items:
            logger.warning("CivitAI returned nothing, falling back to Rule34")
            items = fetch_rule34(limit=100)
    else:
        items = fetch_rule34(limit=100)

    if not items:
        logger.warning("No items found from any source")
        return None

    fresh = [i for i in items if i["id"] not in posted_ids]
    logger.info(f"Fresh items: {len(fresh)} out of {len(items)} (source: {source})")

    if not fresh:
        logger.info("No fresh items")
        return None

    video_posts = [i for i in fresh if _is_video(i["url"])]
    image_posts = [i for i in fresh if not _is_video(i["url"])]

    prefer_video = random.choice([True, False])

    if prefer_video and video_posts:
        selected_video = weighted_choice(video_posts)
        if selected_video:
            try:
                logger.info(f"Downloading video candidate: {selected_video['url']}")
                r = requests.get(selected_video["url"], timeout=30)
                r.raise_for_status()
                data = r.content
                duration = get_video_duration(data)
                if 0.5 <= duration <= 60:
                    logger.info(f"Video accepted: duration={duration:.2f}s, size={len(data)} bytes")
                    return selected_video, data
                else:
                    logger.warning(f"Video rejected: duration={duration:.2f}s (out of 0.5-60s range)")
            except Exception as e:
                logger.warning(f"Video download failed: {e}")

    if image_posts:
        quality_filter = QualityFilter(min_score=6.0)
        valid_posts, image_data_list = [], []

        for item in image_posts[:20]:
            try:
                logger.info(f"Downloading image candidate: {item['url']}")
                r = requests.get(item["url"], timeout=30)
                r.raise_for_status()
                data = r.content
                img_hash = hashlib.sha256(data).hexdigest()
                if img_hash not in posted_hashes:
                    valid_posts.append(item)
                    image_data_list.append(data)
            except Exception as e:
                logger.warning(f"Image download failed ({item['url']}): {e}")
                continue

        if valid_posts:
            selected_post, selected_image_data, quality_result = filter_posts_by_quality(
                valid_posts, image_data_list, min_score=6.0
            )
            if selected_post:
                return selected_post, selected_image_data

    logger.warning("No suitable post found after quality filtering")
    return None


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
        logger.info(f"--- Attempt {attempt + 1}/{MAX_ATTEMPTS} ---")

        # FIX: fetch_and_pick_with_quality уже скачивает файл.
        # main() больше НЕ делает повторный requests.get.
        result = fetch_and_pick_with_quality()

        if result is None:
            logger.info("No suitable posts available")
            return

        item, data = result

        if data is None:
            logger.warning("Got item but no data, skipping")
            posted_ids.add(item["id"])
            save_all()
            continue

        logger.info(f"Working with: {item['id']} ({len(data)} bytes)")

        if len(data) > MAX_FILE_SIZE:
            logger.warning(f"File too large ({len(data)} bytes > 50MB), skipping")
            posted_ids.add(item["id"])
            save_all()
            continue

        is_video = _is_video(item["url"])

        if not is_video:
            if not check_media_size(data, item["url"]):
                logger.warning("Image size too small, skipping")
                posted_ids.add(item["id"])
                save_all()
                continue
        else:
            # Для видео duration уже проверена в fetch_and_pick_with_quality,
            # но делаем повторную проверку на случай edge-кейсов
            duration = get_video_duration(data)
            if duration < 0.5 or duration > 60:
                logger.warning(f"Video duration check failed: {duration:.2f}s, skipping")
                posted_ids.add(item["id"])
                save_all()
                continue
            logger.info(f"Video duration confirmed: {duration:.2f}s")

        img_hash = hashlib.sha256(data).hexdigest()
        if img_hash in posted_hashes:
            logger.warning("Duplicate content detected by hash, skipping")
            posted_ids.add(item["id"])
            save_all()
            continue

        # Дошли до сюда — пост подходит
        break
    else:
        logger.error(f"No suitable post found after {MAX_ATTEMPTS} attempts")
        return

    # ========== THUMBNAIL ДЛЯ ВИДЕО (для vision) ==========
    caption_image_data = data  # для фото — оригинал, для видео — fallback

    if is_video:
        thumbnail = get_video_thumbnail(data)
        if thumbnail:
            caption_image_data = thumbnail
            logger.info(f"Using video thumbnail for vision caption ({len(thumbnail)} bytes)")
        else:
            caption_image_data = data[:500000] if len(data) > 500000 else data
            logger.warning(f"Thumbnail failed, using first {len(caption_image_data)} bytes for vision")

    # ========== CAPTION ==========
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    caption = generate_caption(
        tags=item["tags"],
        rating=item["rating"],
        likes=item["likes"],
        image_data=caption_image_data,
        image_url=item["url"] if not is_video else None,
        watermark=WATERMARK_TEXT,
        suggestion="💬 Предложка: @Haillord"
    )

    logger.info(f"Tags for caption ({len(item['tags'])}): {item['tags'][:8]}")
    logger.info(f"Caption preview: {caption[:100]}")

    # ========== ОТПРАВКА В TELEGRAM ==========
    try:
        if is_video:
            logger.info("Creating video thumbnail with watermark...")
            thumbnail = get_video_thumbnail(data)
            if thumbnail:
                watermarked_thumbnail = add_watermark(thumbnail, text=WATERMARK_TEXT, opacity=0.3)
                logger.info("Sending video with watermark thumbnail")
                await send_with_retry(
                    bot.send_video,
                    chat_id=TELEGRAM_CHANNEL_ID,
                    video=BytesIO(data),
                    thumbnail=BytesIO(watermarked_thumbnail),
                    caption=caption,
                    supports_streaming=True,
                    write_timeout=60,
                    read_timeout=60
                )
            else:
                logger.warning("Thumbnail extraction failed, sending video without watermark thumbnail")
                await send_with_retry(
                    bot.send_video,
                    chat_id=TELEGRAM_CHANNEL_ID,
                    video=BytesIO(data),
                    caption=caption,
                    supports_streaming=True,
                    write_timeout=60,
                    read_timeout=60
                )
        else:
            logger.info("Adding watermark to image...")
            watermarked_data = add_watermark(data, text=WATERMARK_TEXT, opacity=0.3)
            logger.info("Sending image with watermark")
            await send_with_retry(
                bot.send_photo,
                chat_id=TELEGRAM_CHANNEL_ID,
                photo=BytesIO(watermarked_data),
                caption=caption,
                write_timeout=60,
                read_timeout=60
            )

        posted_ids.add(item["id"])
        posted_hashes.add(img_hash)
        save_all()
        logger.info(f"Successfully posted: {item['id']}")

    except Exception as e:
        logger.error(f"Telegram Send Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())