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

# ==================== НАСТРОЙКИ ====================
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "@eroslabai")
CIVITAI_API_KEY     = os.environ.get("CIVITAI_API_KEY", "")

WATERMARK_TEXT   = "@eroslabai"
MIN_LIKES        = 20
MIN_IMAGE_SIZE   = 512

HISTORY_FILE = "posted_ids.json"
HASHES_FILE  = "posted_hashes.json"
STATS_FILE   = "stats.json"

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
stats         = load_json(STATS_FILE, {"total_posts": 0, "top_tags": {}})

def save_all():
    trimmed_ids    = list(posted_ids)[-MAX_HISTORY_SIZE:]
    trimmed_hashes = list(posted_hashes)[-MAX_HISTORY_SIZE:]
    save_json(HISTORY_FILE, trimmed_ids)
    save_json(HASHES_FILE,  trimmed_hashes)
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

def add_watermark(data, text):
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

def get_video_duration(data: bytes) -> float:
    """Возвращает длительность или 0.0 если видео битое"""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        
        # Проверяем, можно ли вообще прочитать
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
    """
    Обёртка для отправки в Telegram с повторными попытками.
    При сбое ждёт 2, 4, 6 секунд перед следующей попыткой.
    """
    for attempt in range(retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            if attempt == retries - 1:
                raise
            wait = 2 * (attempt + 1)
            logger.warning(f"Telegram send failed (attempt {attempt + 1}/{retries}): {e}. Retrying in {wait}s...")
            await asyncio.sleep(wait)

# ==================== ТЕГИ ====================
def extract_tags(item):
    """
    Сначала берём официальные теги CivitAI.
    Если их нет (API не вернул) — парсим meta.prompt как fallback.
    Prompt чистится через clean_tags и HASHTAG_STOP_WORDS,
    так что мусор вроде "masterpiece, best quality, 8k" отфильтруется.
    """
    raw_tags = []

    civitai_tags = item.get("tags", [])
    if civitai_tags:
        for t in civitai_tags:
            name = t.get("name", "") if isinstance(t, dict) else str(t)
            if name:
                raw_tags.append(name)
        logger.debug(f"CivitAI tags found: {len(raw_tags)}")

    # Fallback: парсим prompt если официальных тегов нет
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

def fetch_tags_by_post_id(post_id: int, headers: dict, image_id: str = None) -> list:
    """
    Сначала пробуем получить теги через postId.
    Если 404 — fallback на endpoint изображения по image_id.
    """
    # Вариант 1: через пост
    if post_id:
        try:
            r = _request_with_backoff(
                f"https://civitai.com/api/v1/posts/{post_id}",
                params={},
                headers=headers
            )
            if r:
                tags = r.json().get("tags", [])
                if tags:
                    logger.info(f"Fetched {len(tags)} tags from post {post_id}")
                    return tags
        except Exception as e:
            logger.warning(f"Post tags fetch failed ({post_id}): {e}")

    # Вариант 2: через image id
    if image_id:
        # image_id хранится как "civitai_125396362" — берём только число
        raw_id = str(image_id).replace("civitai_", "")
        try:
            r = _request_with_backoff(
                f"https://civitai.com/api/v1/images/{raw_id}",
                params={},
                headers=headers
            )
            if r:
                tags = r.json().get("tags", [])
                if tags:
                    logger.info(f"Fetched {len(tags)} tags from image {raw_id}")
                    return tags
        except Exception as e:
            logger.warning(f"Image tags fetch failed ({raw_id}): {e}")

    return []

# ==================== CIVITAI API ====================
def _request_with_backoff(url, params, headers, max_retries=3):
    """
    GET-запрос с экспоненциальным backoff при 429/5xx.
    Защищает от бана при rate limiting со стороны CivitAI.
    """
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            if r.status_code == 429:
                wait = 2 ** attempt * 5  # 5s, 10s, 20s
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
    """
    Запрос к API CivitAI — только X и XXX рейтинг.
    Возвращаем результат сразу после первого успешного запроса,
    не продолжая перебирать вариации без нужды.
    Теги здесь не запрашиваются — они подтягиваются лениво
    только для выбранного поста в main().
    """
    variations = [
        {"limit": 100, "nsfw": "X",   "sort": "Most Reactions", "period": "Day"},
        {"limit": 100, "nsfw": "X",   "sort": "Most Reactions", "period": "Week"},
        {"limit": 100, "nsfw": "X",   "sort": "Most Reactions", "period": "Month"},
        {"limit": 100, "nsfw": "X",   "sort": "Newest",         "period": "Day"},
        {"limit": 100, "nsfw": "X",   "sort": "Newest",         "period": "Week"},
        {"limit": 100, "nsfw": "XXX", "sort": "Most Reactions", "period": "Day"},
        {"limit": 100, "nsfw": "XXX", "sort": "Newest",         "period": "Day"}, 
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

                    # Теги из основного ответа (обычно пустые — подтянем позже для выбранного)
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
                        "post_id": item.get("postId"),   # сохраняем для lazy-fetch тегов
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

def fetch_and_pick():
    items = fetch_civitai()

    if not items:
        logger.warning("No items found from API")
        return None

    fresh = [i for i in items if i["id"] not in posted_ids]
    logger.info(f"Fresh items: {len(fresh)} out of {len(items)}")

    if not fresh:
        logger.info("No fresh items")
        return None

    # Взвешенный выбор на основе лайков и популярных тегов
    selected = weighted_choice(fresh)
    
    logger.info(
        f"Selected: {selected['id']} "
        f"(rating:{selected['rating']}, likes:{selected['likes']}, tags:{len(selected['tags'])})"
    )
    return selected


def weighted_choice(items):
    """
    Выбирает пост с весом:
    - основа: количество лайков
    - бонус: +5 за каждый популярный тег (из топ-10 статистики)
    """
    if not items:
        return None
    
    # Получаем топ-10 популярных тегов из статистики
    popular_tags = set()
    if stats.get("top_tags"):
        # Берем топ-10 по частоте использования
        top_10 = sorted(stats["top_tags"].items(), key=lambda x: x[1], reverse=True)[:10]
        popular_tags = set(tag for tag, _ in top_10)
        logger.debug(f"Popular tags boost: {popular_tags}")
    
    weights = []
    for item in items:
        # База — количество лайков (минимум 1)
        weight = max(1, item["likes"])
        
        # Бонус за популярные теги (+5 за каждый совпадающий тег)
        bonus = 0
        for tag in item["tags"]:
            if tag in popular_tags:
                bonus += 5
                logger.debug(f"Bonus for {item['id']}: +5 for tag '{tag}'")
        
        weight += bonus
        weights.append(weight)
    
    # Выбираем с учетом весов
    selected = random.choices(items, weights=weights, k=1)[0]
    
    logger.info(
        f"Weighted selection: {selected['id']} "
        f"(likes:{selected['likes']}, bonus:{bonus}, total_weight:{weight})"
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

        # ── Lazy-fetch тегов — только для выбранного поста ──────────────────
        # /api/v1/images не возвращает теги в основном ответе,
        # поэтому запрашиваем их отдельно через postId.
        # Один запрос на весь запуск — никакого лишнего трафика.
        if not item["tags"] and item.get("post_id"):
            headers = {"Authorization": f"Bearer {CIVITAI_API_KEY}"} if CIVITAI_API_KEY else {}
            raw = fetch_tags_by_post_id(item["post_id"], headers, image_id=item["id"])
            fetched_tags = clean_tags([
                t.get("name", t) if isinstance(t, dict) else str(t)
                for t in raw
            ])
            if fetched_tags:
                # Прогоняем через блэклист ещё раз с полными тегами
                if has_blacklisted(fetched_tags):
                    logger.warning(f"Blacklisted tags after fetch, skipping {item['id']}")
                    posted_ids.add(item["id"])
                    save_all()
                    continue
                item["tags"] = fetched_tags[:15]
                logger.info(f"Tags after lazy-fetch ({len(item['tags'])}): {item['tags']}")
            else:
                logger.info("No tags found even after lazy-fetch, proceeding without tags")
        # ────────────────────────────────────────────────────────────────────

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

        # Проверка изображения или видео
        if not item["url"].lower().endswith((".mp4", ".webm", ".gif")):
            if not check_media_size(data, item["url"]):
                logger.warning("Image size too small, skipping")
                posted_ids.add(item["id"])
                save_all()
                continue
        else:
            # Для видео проверяем длительность, чтобы отсеять битые/статичные файлы
            duration = get_video_duration(data)
            if duration < 0.5:
                logger.warning(f"Video too short ({duration:.2f}s), skipping")
                posted_ids.add(item["id"])
                save_all()
                continue
            logger.info(f"Video duration: {duration:.2f}s")

        # SHA256 вместо MD5 — надёжнее, меньше коллизий
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
            logger.info("Sending as image with watermark")
            final_data = add_watermark(data, WATERMARK_TEXT)
            await send_with_retry(
                bot.send_photo,
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