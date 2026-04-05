"""
ErosLab Wallpapers Bot — Только красивые безопасные обои
Работает полностью независимо от основного бота
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
from urllib.parse import urlparse
from datetime import datetime
from zoneinfo import ZoneInfo
from PIL import Image
import telegram
from telegram import Bot
from caption_generator import generate_wallpaper_caption
from watermark import should_add_watermark


# ==================== НАСТРОЙКИ ====================
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN_WALLPAPERS", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID_WALLPAPERS", "")
ADMIN_USER_ID = str(os.environ.get("ADMIN_USER_ID", "")).strip()
CIVITAI_API_KEY     = os.environ.get("CIVITAI_API_KEY", "")

WATERMARK_ENABLED = False
MIN_LIKES        = 25
MIN_IMAGE_SIZE   = 720
MIN_ASPECT_RATIO_MIN = 0.5   # 9:16 вертикальные (телефон)
MIN_ASPECT_RATIO_MAX = 2.0   # 16:9 горизонтальные (монитор)
IMAGE_PACK_SIZE = 4
IMAGE_PACK_CANDIDATE_POOL = 24

HISTORY_FILE = "posted_ids_wallpapers.json"
HASHES_FILE  = "posted_hashes_wallpapers.json"
CONTENT_STATE_FILE = "content_state_wallpapers.json"
STATS_FILE = "stats_wallpapers.json"
MAX_HISTORY_SIZE = 5000
STATS_TZ = os.environ.get("STATS_TZ", "Europe/Moscow")


BLACKLIST_TAGS = {
    "loli", "shota", "child", "minor", "underage", "infant", "toddler",
    "gore", "guro", "scat", "vore", "snuff", "necrophilia", "bestiality", "zoo"
}

HASHTAG_STOP_WORDS = {
    "score", "source", "rating", "version", "step", "steps", "cfg", "seed",
    "sampler", "model", "lora", "vae", "clip", "unet", "fp16", "safetensors",
    "checkpoint", "embedding", "none", "null", "true", "false", "and", "the",
    "for", "with", "masterpiece", "best", "quality", "high", "ultra", "detail",
    "detailed", "8k", "4k", "hd", "resolution", "simple", "background",
    "generated_by_ai", "animated", "rating_explicit", "rating_questionable",
    "rating_safe", "rating_suggestive", "tagme",
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
content_state = load_json(CONTENT_STATE_FILE, {"last_type": "landscape"})


def _get_stats_day_key():
    try:
        return datetime.now(ZoneInfo(STATS_TZ)).date().isoformat()
    except Exception:
        return datetime.utcnow().date().isoformat()

def _load_stats():
    data = load_json(STATS_FILE, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("schema_version", 2)
    data.setdefault("daily", {})
    data.setdefault("lifetime", {})
    return data

def _increment_metrics(target: dict, metrics: dict):
    for key, value in metrics.items():
        if isinstance(value, (int, float)):
            target[key] = target.get(key, 0) + value

def record_run_stats(metrics: dict):
    stats = _load_stats()
    day_key = _get_stats_day_key()
    daily = stats["daily"].setdefault(day_key, {})
    lifetime = stats["lifetime"]

    _increment_metrics(daily, metrics)
    _increment_metrics(lifetime, metrics)

    if metrics.get("posted", 0) > 0:
        stats["total_posts"] = stats.get("total_posts", 0) + int(metrics["posted"])

    try:
        keys_sorted = sorted(stats["daily"].keys())
        while len(keys_sorted) > 45:
            oldest = keys_sorted.pop(0)
            stats["daily"].pop(oldest, None)
    except Exception:
        pass

    save_json(STATS_FILE, stats)

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

def _normalize_tag(tag: str) -> str:
    return str(tag).strip().lower().replace(" ", "_").replace("-", "_")

def has_blacklisted(tags):
    normalized_tags = [_normalize_tag(t) for t in tags]
    blacklisted = set(normalized_tags) & BLACKLIST_TAGS
    return bool(blacklisted)

def get_preferred_orientation() -> str:
    """Возвращает предпочтительную ориентацию и переключает на следующую."""
    last_type = content_state.get("last_type", "landscape")
    preferred = "portrait" if last_type == "landscape" else "landscape"
    content_state["last_type"] = preferred
    logger.info(f"Orientation: last={last_type}, preferred={preferred}")
    return preferred

def check_media_size(data, url, preferred_orientation: str = None):
    try:
        if not url.lower().endswith((".mp4", ".webm", ".gif")):
            img = Image.open(BytesIO(data))
            width, height = img.size
            aspect = width / height

            if max(width, height) < MIN_IMAGE_SIZE:
                logger.warning(f"Image too small: {width}x{height}")
                return False

            if not (MIN_ASPECT_RATIO_MIN <= aspect <= MIN_ASPECT_RATIO_MAX):
                logger.warning(f"Bad aspect ratio: {width}x{height} ratio={aspect:.2f}")
                return False

            if preferred_orientation:
                is_portrait = aspect < 1.0
                if preferred_orientation == "portrait" and not is_portrait:
                    logger.info(f"Preferred portrait but got landscape {width}x{height}, still accepted")
                elif preferred_orientation == "landscape" and is_portrait:
                    logger.info(f"Preferred landscape but got portrait {width}x{height}, still accepted")

            return True
        return False
    except Exception as e:
        logger.error(f"Error checking media size: {e}")
        return False

def compute_image_hash(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


# ==================== RETRY ДЛЯ TELEGRAM ====================
async def send_with_retry(func, *args, retries=3, **kwargs):
    def _rewind_file_like(obj):
        if obj is None:
            return
        try:
            if hasattr(obj, "seek"):
                obj.seek(0)
        except Exception:
            pass

    def _rewind_payload():
        for value in args:
            _rewind_file_like(value)
        for key in ("photo", "media"):
            _rewind_file_like(kwargs.get(key))
        media = kwargs.get("media")
        if isinstance(media, list):
            for item in media:
                media_obj = getattr(item, "media", None)
                _rewind_file_like(media_obj)

    for attempt in range(retries):
        try:
            _rewind_payload()
            return await func(*args, **kwargs)
        except Exception as e:
            if attempt == retries - 1:
                raise
            logger.warning(f"Telegram send failed (attempt {attempt + 1}/{retries}): {e}")
            await asyncio.sleep(2)


def _fit_photo_size_for_telegram(image_data: bytes, max_size: int = 10 * 1024 * 1024) -> bytes:
    if not image_data or len(image_data) <= max_size:
        return image_data

    try:
        img = Image.open(BytesIO(image_data))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        for quality in (92, 88, 84, 80, 76, 72, 68):
            out = BytesIO()
            img.save(out, format="JPEG", quality=quality, optimize=True)
            candidate = out.getvalue()
            if len(candidate) <= max_size:
                logger.info(f"Photo recompressed: {len(candidate)} bytes (q={quality})")
                return candidate

        width, height = img.size
        for scale in (0.95, 0.9, 0.85, 0.8, 0.75):
            new_w = max(1, int(width * scale))
            new_h = max(1, int(height * scale))
            resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            out = BytesIO()
            resized.save(out, format="JPEG", quality=76, optimize=True)
            candidate = out.getvalue()
            if len(candidate) <= max_size:
                logger.info(f"Photo downscaled: {len(candidate)} bytes ({width}x{height} -> {new_w}x{new_h})")
                return candidate
    except Exception as e:
        logger.warning(f"Could not fit photo size: {e}")

    return image_data


# ==================== ТЕГИ ====================
def extract_tags(item):
    raw_tags = []

    civitai_tags = item.get("tags", [])
    if civitai_tags:
        for t in civitai_tags:
            name = t.get("name", "") if isinstance(t, dict) else str(t)
            if name:
                raw_tags.append(name)

    if not raw_tags:
        prompt = item.get("meta", {}).get("prompt", "") if item.get("meta") else ""
        if prompt:
            tokens = re.split(r"[,\(\)\[\]|<>]+", prompt)
            for token in tokens:
                token = token.strip()
                if token:
                    raw_tags.append(token)

    return clean_tags(raw_tags)


# ==================== CIVITAI API ====================
def _request_with_backoff(url, params, headers, max_retries=3):
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            if r.status_code == 429:
                wait = 2 ** attempt * 5
                logger.warning(f"Rate limited, waiting {wait}s")
                time.sleep(wait)
                continue
            if r.status_code == 400:
                return r
            r.raise_for_status()
            return r
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout on attempt {attempt + 1}")
            if attempt < max_retries - 1:
                time.sleep(3)
        except requests.exceptions.HTTPError as e:
            if r.status_code >= 500:
                logger.warning(f"Server error, retry")
                time.sleep(2 ** attempt * 2)
            else:
                raise
        except Exception as e:
            logger.error(f"Request error: {e}")
            raise
    return None


def _to_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _extract_civitai_likes(item):
    stats = item.get("stats") or {}
    stats_total = 0
    if isinstance(stats, dict):
        for key, value in stats.items():
            key_lower = str(key).lower()
            if "count" in key_lower:
                stats_total += _to_int(value, 0)

    candidates = [
        stats.get("likeCount"),
        stats.get("heartCount"),
        stats.get("reactionCount"),
        stats.get("favoriteCount"),
        stats_total,
        item.get("likeCount"),
        item.get("heartCount"),
        item.get("reactionCount"),
    ]
    numeric = [_to_int(v, 0) for v in candidates]
    return max(numeric) if numeric else 0


def _is_safe_rating(nsfw_level):
    if isinstance(nsfw_level, str):
        return nsfw_level.strip().lower() in {"none", "soft"}
    if isinstance(nsfw_level, (int, float)):
        return nsfw_level <= 2  # None=1, Soft=2
    return False


def fetch_civitai(max_pages: int = 5):
    variations = [
        # Приоритет: сначала свежее за неделю
    {"browsingLevel": 3, "nsfw": "Soft", "sort": "Most Reactions", "period": "Week"},
    {"browsingLevel": 3, "nsfw": "Soft", "sort": "Most Comments", "period": "Week"},
    {"browsingLevel": 3, "nsfw": "Soft", "sort": "Newest", "period": "Week"},
    # За месяц
    {"browsingLevel": 3, "nsfw": "Soft", "sort": "Most Reactions", "period": "Month"},
    {"browsingLevel": 3, "nsfw": "Soft", "sort": "Most Comments", "period": "Month"},
    {"browsingLevel": 3, "nsfw": "Soft", "sort": "Newest", "period": "Month"},
    # За всё время
    {"browsingLevel": 3, "nsfw": "Soft", "sort": "Most Reactions", "period": "AllTime"},
    {"browsingLevel": 3, "nsfw": "Soft", "sort": "Most Reactions", "period": "AllTime", "tags": "wallpaper"},
    ]

    headers = {"Authorization": f"Bearer {CIVITAI_API_KEY}"} if CIVITAI_API_KEY else {}

    for base_params in variations:
        all_items = []
        seen_ids = set()
        next_page_url = None

        tag_label = base_params.get("tags", "no-tag")
        period_label = base_params.get("period", "")
        logger.info(f"Trying variation: tag={tag_label} period={period_label}")

        for page in range(1, max_pages + 1):
            request_url = next_page_url or "https://civitai.com/api/v1/images"
            params = None if next_page_url else {**base_params, "limit": 100}

            try:
                r = _request_with_backoff(request_url, params=params, headers=headers)
                if r is None:
                    continue

                if r.status_code == 400:
                    logger.warning(f"400 Bad Request for params: {base_params}")
                    break

                data = r.json()
                items = data.get("items", [])

                if not items:
                    break

                for item in items:
                    item_id = item.get("id")
                    if item_id in seen_ids:
                        continue
                    seen_ids.add(item_id)
                    all_items.append(item)
                logger.info(f"CivitAI page {page}: got {len(items)} items (total: {len(all_items)})")

                metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
                next_page_url = metadata.get("nextPage")
                if not next_page_url:
                    break

            except Exception as e:
                logger.error(f"CivitAI page {page} error: {e}")
                continue

        if not all_items:
            continue

        precomputed_likes = [_extract_civitai_likes(i) for i in all_items]
        likes_filter_enabled = any(v > 0 for v in precomputed_likes)

        good_items = []
        skipped_rating = 0
        skipped_blacklist = 0
        skipped_likes = 0
        logger.info(f"Sample nsfwLevels: {[i.get('nsfwLevel') for i in all_items[:10]]}")
        for item in all_items:
            try:
                nsfw_level = item.get("nsfwLevel")

                if not _is_safe_rating(nsfw_level):
                    skipped_rating += 1
                    continue

                tags = extract_tags(item)

                if has_blacklisted(tags):
                    skipped_blacklist += 1
                    continue

                likes = _extract_civitai_likes(item)

                if likes_filter_enabled and likes < MIN_LIKES:
                    skipped_likes += 1
                    continue

                good_items.append({
                    "id":        f"civitai_{item['id']}",
                    "url":       item.get("url", ""),
                    "tags":      tags[:15],
                    "likes":     likes,
                    "rating":    nsfw_level,
                    "post_id":   item.get("postId"),
                    "mime":      (item.get("mimeType") or "").lower(),
                    "createdAt": item.get("createdAt"),
                    "source":    "civitai",
                    "tag_source": tag_label,
                })

            except Exception as e:
                logger.error(f"Error processing item {item.get('id')}: {e}")
                continue

        logger.info(
            f"Variation tag={tag_label}: good={len(good_items)} "
            f"skip_rating={skipped_rating} skip_bl={skipped_blacklist} skip_likes={skipped_likes}"
        )

        if good_items:
            return good_items

    return []


def fetch_and_pick():
    preferred_orientation = get_preferred_orientation()
    items = fetch_civitai()

    if not items:
        logger.warning("No items found from CivitAI")
        return None

    fresh = [i for i in items if i["id"] not in posted_ids]
    fresh = [i for i in fresh if not has_blacklisted(i["tags"])]
    logger.info(f"Fresh items: {len(fresh)} out of {len(items)}")

    if not fresh:
        logger.info("No fresh items")
        return None

    fresh_photos = [i for i in fresh if not i["mime"].startswith("video/")]

    if not fresh_photos:
        logger.info("No suitable photos found")
        return None

    def _try_pick(candidates, strict_orientation: str = None):
        for candidate in sorted(candidates, key=lambda x: x["likes"], reverse=True):
            try:
                r = requests.get(candidate.get("url"), timeout=15)
                r.raise_for_status()
                image_data = r.content

                img_hash = compute_image_hash(image_data)
                if img_hash in posted_hashes:
                    logger.info(f"Skip duplicate hash: {candidate['id']}")
                    continue

                if not check_media_size(image_data, candidate.get("url"), strict_orientation):
                    continue

                if strict_orientation:
                    img = Image.open(BytesIO(image_data))
                    w, h = img.size
                    aspect = w / h
                    is_portrait = aspect < 1.0
                    if strict_orientation == "portrait" and not is_portrait:
                        continue
                    if strict_orientation == "landscape" and is_portrait:
                        continue

                logger.info(f"Found: {candidate['id']} (likes:{candidate['likes']}, tag:{candidate.get('tag_source')})")
                return candidate, img_hash

            except Exception as e:
                logger.warning(f"Skip candidate {candidate['id']}: {e}")
                continue
        return None, None

    result, img_hash = _try_pick(fresh_photos, strict_orientation=preferred_orientation)

    if result is None:
        logger.info(f"No {preferred_orientation} found, trying any orientation")
        result, img_hash = _try_pick(fresh_photos, strict_orientation=None)

    if result:
        result["_img_hash"] = img_hash

    return result


# ==================== ПУБЛИКАЦИЯ ====================
async def publish_item_to_channel(bot: Bot, item: dict):
    try:
        r = requests.get(item.get("url"), timeout=60)
        r.raise_for_status()
        image_data = r.content

        if not check_media_size(image_data, item.get("url")):
            return False

        img_hash = item.get("_img_hash") or compute_image_hash(image_data)
        if img_hash in posted_hashes:
            logger.warning(f"Duplicate hash at publish stage, skip: {item['id']}")
            return False

        image_data = _fit_photo_size_for_telegram(image_data)
        photo_io = BytesIO(image_data)
        photo_io.name = "wallpaper.jpg"

        width, height = Image.open(BytesIO(image_data)).size

        caption = generate_wallpaper_caption(
            tags=item.get("tags", []),
            likes=item.get("likes", 0),
            width=width,
            height=height,
            date=item.get("createdAt"),
            suggestion="💬 Предложи обои: @Haillord",
            watermark="📢 @eroslabwallpaper",
        )

        await send_with_retry(
            bot.send_photo,
            chat_id=TELEGRAM_CHANNEL_ID,
            photo=photo_io,
            caption=caption,
            parse_mode="HTML",
            write_timeout=60,
            read_timeout=60,
        )

        posted_ids.add(item["id"])
        posted_hashes.add(img_hash)
        return True

    except Exception as e:
        logger.warning(f"Publish failed: {e}")
        return False


# ==================== MAIN ====================
async def main():
    run_started = time.time()
    run_metrics = {
        "runs": 1,
        "posted": 0,
        "skip_no_item": 0,
        "skip_download_error": 0,
        "skip_bad_image": 0,
        "send_errors": 0,
    }
    stats_flushed = False

    def flush_stats_once():
        nonlocal stats_flushed
        if stats_flushed:
            return
        run_metrics["runtime_sec"] = round(time.time() - run_started, 2)
        record_run_stats(run_metrics)
        stats_flushed = True

    if not TELEGRAM_BOT_TOKEN:
        logger.error("No TELEGRAM_BOT_TOKEN provided")
        flush_stats_once()
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    selected = fetch_and_pick()

    if not selected:
        run_metrics["skip_no_item"] = 1
        logger.info("No suitable wallpaper found this run")
        flush_stats_once()
        save_all()
        return

    success = await publish_item_to_channel(bot, selected)

    if success:
        run_metrics["posted"] = 1
        logger.info(f"Successfully posted wallpaper {selected['id']}")
    else:
        run_metrics["send_errors"] = 1

    flush_stats_once()
    save_all()

    try:
        await bot.close()
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(main())