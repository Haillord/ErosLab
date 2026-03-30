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

# Временно отключить Rule34 (True = только CivitAI для тестов)
TEST_CIVITAI_ONLY = True

HISTORY_FILE = "posted_ids.json"
HASHES_FILE  = "posted_hashes.json"
CONTENT_STATE_FILE = "content_state.json"
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
content_state = load_json(CONTENT_STATE_FILE, {"last_type": "3d", "last_media": "video"})

def get_next_content_type():
    """Чередует между 3d и ai контентом"""
    global content_state
    next_type = "ai" if content_state["last_type"] == "3d" else "3d"
    content_state["last_type"] = next_type
    save_json(CONTENT_STATE_FILE, content_state)
    return next_type

def get_next_media_type():
    """70% video, 30% image с чередованием"""
    global content_state
    # Чередование: если последнее было video, следующее с большей вероятностью image
    if content_state.get("last_media") == "video":
        media_type = "video" if random.random() < 0.4 else "image"  # 40% video, 60% image
    else:
        media_type = "video" if random.random() < 0.9 else "image"  # 90% video, 10% image
    content_state["last_media"] = media_type
    save_json(CONTENT_STATE_FILE, content_state)
    return media_type

def save_all():
    trimmed_ids    = list(posted_ids)[-MAX_HISTORY_SIZE:]
    trimmed_hashes = list(posted_hashes)[-MAX_HISTORY_SIZE:]
    save_json(HISTORY_FILE, trimmed_ids)
    save_json(HASHES_FILE,  trimmed_hashes)
    save_json(CONTENT_STATE_FILE, content_state)

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

        duration_str = result.stdout.strip()
        
        # 🔥 ФИКС: проверяем, что вернулось не 'N/A'
        if not duration_str or duration_str == 'N/A':
            logger.warning(f"ffprobe returned: '{duration_str}'")
            return 0.0
        
        duration = float(duration_str)
        return duration

    except ValueError as e:
        logger.error(f"Error converting duration '{duration_str}' to float: {e}")
        return 0.0
    except Exception as e:
        logger.error(f"Error: {e}")
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
    # Full variations with X and XXX (XXX may not work now, but could in future)
    variations = [
        {"limit": 100, "nsfw": "X",   "sort": "Most Reactions", "period": "Day"},
        {"limit": 100, "nsfw": "X",   "sort": "Most Reactions", "period": "Week"},
        {"limit": 100, "nsfw": "X",   "sort": "Most Reactions", "period": "Month"},
        {"limit": 100, "nsfw": "X",   "sort": "Newest",         "period": "Day"},
        {"limit": 100, "nsfw": "X",   "sort": "Newest",         "period": "Week"},
        {"limit": 100, "nsfw": "X",   "sort": "Newest",         "period": "Month"},
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

            # Handle 400 Bad Request (e.g., nsfw=XXX not supported)
            if r.status_code == 400:
                logger.debug(f"Skipping invalid params {params} (400 Bad Request)")
                continue

            data = r.json()
            items = data.get("items", [])

            logger.info(
                f"Got {len(items)} items "
                f"(nsfw={params['nsfw']}, sort={params['sort']}, period={params['period']})"
            )

            erotic_items = []
            skipped_nsfw = 0
            skipped_blacklist = 0
            skipped_likes = 0
            
            # Debug: sample first 5 items nsfwLevel
            for debug_item in items[:5]:
                debug_nsfw = debug_item.get("nsfwLevel")
                debug_id = debug_item.get("id")
                logger.debug(f"Item {debug_id}: nsfwLevel={debug_nsfw} (type={type(debug_nsfw).__name__})")
            
            for item in items:
                try:
                    nsfw_level = item.get("nsfwLevel")

                    is_x_rating = False
                    if isinstance(nsfw_level, str) and nsfw_level.upper() in ["X", "XXX"]:
                        is_x_rating = True
                    elif isinstance(nsfw_level, (int, float)) and nsfw_level >= 4:
                        is_x_rating = True

                    if not is_x_rating:
                        skipped_nsfw += 1
                        continue

                    tags = extract_tags(item)

                    if has_blacklisted(tags):
                        skipped_blacklist += 1
                        continue

                    stats_data = item.get("stats", {})
                    likes = 0
                    if stats_data:
                        likes = (
                            stats_data.get("likeCount", 0)
                            + stats_data.get("heartCount", 0)
                        )

                    if likes < MIN_LIKES:
                        skipped_likes += 1
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

            logger.info(f"No suitable posts: skipped_nsfw={skipped_nsfw}, skipped_blacklist={skipped_blacklist}, skipped_likes={skipped_likes}")

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
    source = "civitai" if TEST_CIVITAI_ONLY else random.choice(["civitai", "rule34"])
    logger.info(f"Source selected: {source}" + (" (TEST_CIVITAI_ONLY mode)" if TEST_CIVITAI_ONLY else ""))

    if source == "civitai":
        items = fetch_civitai()
        if not items:
            logger.warning("CivitAI returned nothing, falling back to Rule34")
            source = "rule34"
            # Чередование между 3D и AI, 70% video / 30% image
            content_type = get_next_content_type()
            media_type = get_next_media_type()
            items = fetch_rule34(limit=100, content_type=content_type, media_type=media_type)
    else:
        # Чередование между 3D и AI, 70% video / 30% image
        content_type = get_next_content_type()
        media_type = get_next_media_type()
        logger.info(f"Rule34 content_type={content_type}, media_type={media_type}")
        items = fetch_rule34(limit=100, content_type=content_type, media_type=media_type)
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

    if source == "rule34":
        selected = _pick_by_content_type(fresh)
    else:
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

        is_video = _is_video(item["url"])

        if not is_video:
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

    # ========== THUMBNAIL ДЛЯ ВИДЕО (для vision) ==========
    caption_image_data = data  # для фото — оригинал, для видео — fallback

    if is_video:
        thumbnail = get_video_thumbnail(data)
        if thumbnail:
            caption_image_data = thumbnail
            logger.info(f"Using video thumbnail for vision caption ({len(thumbnail)} bytes)")
        else:
            # Если thumbnail не получился, пробуем использовать первый фрагмент видео
            # как "изображение" (некоторые vision модели могут его обработать)
            caption_image_data = data[:500000] if len(data) > 500000 else data
            logger.warning(f"Thumbnail failed, using first {len(caption_image_data)} bytes of video for vision")

    # ========== ОТПРАВКА В TELEGRAM ==========
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

    try:
        if is_video:
            logger.info("Sending as video/gif")
            logger.info("Using original video (no optimization)")
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
        logger.info(f"Successfully posted: {item['id']}")

    except Exception as e:
        logger.error(f"Telegram Send Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())