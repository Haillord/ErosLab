"""
ErosLab Wallpapers Bot — Только красивые безопасные обои
Работает полностью независимо от основного бота
"""

import asyncio
import hashlib
import logging
import os
import random
import time
import requests
from io import BytesIO
from gist_storage import load_all_state, save_all_state
from PIL import Image
from telegram import Bot
from caption_generator import generate_wallpaper_caption
from utils_state import (
    load_json as _shared_load_json,
    save_json as _shared_save_json,
    get_stats_day_key as _shared_get_stats_day_key,
    load_stats as _shared_load_stats,
    increment_metrics as _shared_increment_metrics,
    record_run_stats as _shared_record_run_stats,
)
from utils_telegram_media import (
    send_with_retry as _shared_send_with_retry,
    fit_photo_size_for_telegram as _shared_fit_photo_size_for_telegram,
)
from utils_tags import (
    clean_tags as _shared_clean_tags,
    normalize_tag as _shared_normalize_tag,
    extract_tags_from_item as _shared_extract_tags_from_item,
    to_int as _shared_to_int,
    extract_civitai_likes as _shared_extract_civitai_likes,
)


# ==================== НАСТРОЙКИ ====================
ENABLE_CIVITAI = False  # ✅ Поставь False чтобы отключить CivitAI полностью

TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN_WALLPAPERS", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID_WALLPAPERS", "")
CIVITAI_API_KEY     = os.environ.get("CIVITAI_API_KEY", "")
WALLHAVEN_API_KEY   = os.environ.get("WALLHAVEN_API_KEY", "")

MIN_LIKES        = 5
MIN_IMAGE_SIZE   = 720
MIN_ASPECT_RATIO_MIN = 0.5   # 9:16 вертикальные (телефон)
MIN_ASPECT_RATIO_MAX = 2.0   # 16:9 горизонтальные (монитор)
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
    return _shared_load_json(path, default, logger)

def save_json(path, data):
    _shared_save_json(path, data)

_state = load_all_state()
posted_ids    = set(_state.get("posted_ids_wallpapers.json", []))
posted_hashes = set(_state.get("posted_hashes_wallpapers.json", []))
content_state = _state.get("content_state_wallpapers.json", {"last_type": "landscape"})


def _get_stats_day_key():
    return _shared_get_stats_day_key(STATS_TZ)

def _load_stats():
    return _shared_load_stats(STATS_FILE, logger)

def _increment_metrics(target: dict, metrics: dict):
    _shared_increment_metrics(target, metrics)

def record_run_stats(metrics: dict):
    _shared_record_run_stats(
        stats_file=STATS_FILE,
        stats_tz=STATS_TZ,
        metrics=metrics,
        logger=logger,
        keep_days=45,
    )

def save_all():
    trimmed_ids    = list(posted_ids)[-MAX_HISTORY_SIZE:]
    trimmed_hashes = list(posted_hashes)[-MAX_HISTORY_SIZE:]
    save_all_state({
        "posted_ids_wallpapers.json":    trimmed_ids,
        "posted_hashes_wallpapers.json": trimmed_hashes,
        "content_state_wallpapers.json": content_state,
        "stats_wallpapers.json":         _load_stats(),
    })


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def clean_tags(tags):
    return _shared_clean_tags(tags, HASHTAG_STOP_WORDS)

def _normalize_tag(tag: str) -> str:
    return _shared_normalize_tag(tag)

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
    return await _shared_send_with_retry(func, *args, retries=retries, logger=logger, **kwargs)


def _fit_photo_size_for_telegram(image_data: bytes, max_size: int = 10 * 1024 * 1024) -> bytes:
    return _shared_fit_photo_size_for_telegram(image_data, logger=logger, max_size=max_size)


# ==================== ТЕГИ ====================
def extract_tags(item):
    return _shared_extract_tags_from_item(item, HASHTAG_STOP_WORDS)


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
    return _shared_to_int(value, default)


def _extract_civitai_likes(item):
    return _shared_extract_civitai_likes(item)


def fetch_wallhaven(max_pages: int = 3):
    variations = [
        {"sorting": "toplist", "topRange": "1w"},
        {"sorting": "toplist", "topRange": "1M"},
        {"sorting": "favorites", "topRange": "1w"},
    ]

    for base_params in variations:
        all_items = []

        for page in range(1, max_pages + 1):
            params = {
                "apikey": WALLHAVEN_API_KEY,
                "categories": "111",
                "purity": "110",
                "atleast": "1920x1080",
                "page": page,
                **base_params
            }

            try:
                r = _request_with_backoff("https://wallhaven.cc/api/v1/search", params=params, headers={})
                if r is None:
                    continue

                data = r.json()
                items = data.get("data", [])

                if not items:
                    break

                for item in items:
                    tags = [t["name"] for t in item.get("tags", [])[:10]]
                    logger.info(f"Item {item['id']} tags raw: {item.get('tags', [])} → parsed: {tags}")
                    all_items.append({
                        "id":      f"wallhaven_{item['id']}",
                        "url":     item["path"],
                        "tags":    [t["name"] for t in item.get("tags", [])[:10]],
                        "likes":   item["favorites"],
                        "rating":  "safe",
                        "mime":    f"image/{item['file_type']}",
                        "createdAt": item["created_at"],
                        "source":  "wallhaven",
                    })

                logger.info(f"Wallhaven page {page}: got {len(items)} items")

                if not data.get("meta", {}).get("current_page") < data.get("meta", {}).get("last_page", 1):
                    break

            except Exception as e:
                logger.warning(f"Wallhaven page {page} failed: {e}")
                continue

        if all_items:
            logger.info(f"Found {len(all_items)} wallpapers from Wallhaven")
            return all_items

    return []


def _is_safe_rating(nsfw_level):
    if isinstance(nsfw_level, str):
        return nsfw_level.strip().lower() in {"none", "soft"}
    if isinstance(nsfw_level, (int, float)):
        return nsfw_level <= 2  # None=1, Soft=2
    return False


def fetch_wallhaven_tags(wallpaper_id: str) -> list:
    raw_id = wallpaper_id.replace("wallhaven_", "")
    try:
        r = requests.get(
            f"https://wallhaven.cc/api/v1/w/{raw_id}",
            params={"apikey": WALLHAVEN_API_KEY},
            timeout=10
        )
        data = r.json()
        tags = [t["name"] for t in data.get("data", {}).get("tags", [])[:10]]
        logger.info(f"Fetched tags for {wallpaper_id}: {tags}")
        return tags
    except Exception as e:
        logger.warning(f"Failed to fetch tags for {wallpaper_id}: {e}")
        return []


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
    
    sources = []
    if ENABLE_CIVITAI:
        sources.append(fetch_civitai)
    sources.append(fetch_wallhaven)
    random.shuffle(sources)
    
    items = []
    for source in sources:
        try:
            source_items = source()
            if source_items:
                items.extend(source_items)
                logger.info(f"Got {len(source_items)} items from {source.__name__}")
        except Exception as e:
            logger.warning(f"Source {source.__name__} failed: {e}")
            continue

    if not items:
        logger.warning("No items found from any source")
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

                # Догружаем теги если источник wallhaven и теги пустые
                if candidate.get("source") == "wallhaven" and not candidate.get("tags"):
                    candidate["tags"] = fetch_wallhaven_tags(candidate["id"])

                logger.info(f"Found: {candidate['id']} (likes:{candidate['likes']}, tag:{candidate.get('tag_source')})")
                return candidate, img_hash, image_data

            except Exception as e:
                logger.warning(f"Skip candidate {candidate['id']}: {e}")
                posted_ids.add(candidate['id'])
                continue
        return None, None, None

    result, img_hash, image_data = _try_pick(fresh_photos, strict_orientation=preferred_orientation)

    if result is None:
        logger.info(f"No {preferred_orientation} found, trying any orientation")
        result, img_hash, image_data = _try_pick(fresh_photos, strict_orientation=None)

    if result:
        result["_img_hash"] = img_hash
        result["_image_data"] = image_data

    return result


# ==================== ПУБЛИКАЦИЯ ====================
async def publish_item_to_channel(bot: Bot, item: dict):
    try:
        image_data = item.get("_image_data")
        if image_data is None:
            r = requests.get(item.get("url"), timeout=60)
            r.raise_for_status()
            image_data = r.content

        # Ресайз если изображение слишком большое по пикселям
        img = Image.open(BytesIO(image_data))
        w, h = img.size
        if img.mode in ('RGBA', 'P', 'LA'):
            img = img.convert('RGB')
        max_px = 3840
        if max(w, h) > max_px:
            scale = max_px / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
            out = BytesIO()
            img.save(out, format="JPEG", quality=88)
            image_data = out.getvalue()
            logger.info(f"Resized {w}x{h} -> {int(w*scale)}x{int(h*scale)}")

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