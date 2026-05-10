"""
Gelbooru API parser for ErosLab Bot.
Требует регистрацию на gelbooru.com → Settings → API Access Credentials.
"""

import os
import random
import logging
import requests
from typing import List, Dict, Any

logger = logging.getLogger("ErosLab.Gelbooru")

GELBOORU_API_KEY   = os.getenv("GELBOORU_API_KEY", "")
GELBOORU_USER_ID   = os.getenv("GELBOORU_USER_ID", "")
GELBOORU_MIN_SCORE = int(os.getenv("GELBOORU_MIN_SCORE", "5"))

BASE_URL = "https://gelbooru.com/index.php"

# ── Видео (animated / webm) ───────────────────────────────────────────────────
VIDEO_TAG_SETS = [
    "ai_generated animated rating:explicit -loli -shota -1boy -solo_male -yaoi sort:score:desc",
    "ai_generated webm rating:explicit -loli -shota -1boy -solo_male -yaoi sort:score:desc",
    "ai_generated animated rating:explicit -loli -shota -1boy -solo_male sort:updated:desc",
    "3d_(artwork) animated rating:explicit -loli -shota -1boy -solo_male -yaoi sort:score:desc",
    "3d_(artwork) webm rating:explicit -loli -shota -1boy -solo_male sort:score:desc",
    "animated rating:explicit -loli -shota -1boy -solo_male -yaoi sort:score:desc",
]

# ── Фото (без animated) ───────────────────────────────────────────────────────
IMAGE_TAG_SETS = [
    "ai_generated rating:explicit -animated -loli -shota -1boy -solo_male -yaoi sort:score:desc",
    "ai_generated rating:explicit -animated -loli -shota -1boy -solo_male sort:updated:desc",
    "3d_(artwork) rating:explicit -animated -loli -shota -1boy -solo_male -yaoi sort:score:desc",
    "rating:explicit -animated -loli -shota -1boy -solo_male -yaoi -gore sort:score:desc",
]

GELBOORU_BLACKLIST = {
    "loli", "shota", "child", "minor", "underage",
    "gore", "guro", "scat", "vore", "snuff", "necrophilia",
    "1boy", "solo_male", "male_focus", "male_pov",
    "yaoi", "bara", "2boys", "3boys", "multiple_boys",
    "bestiality", "zoo", "furry_male", "anthro",
}


def _build_item(post: dict) -> dict | None:
    file_url = post.get("file_url")
    if not file_url:
        return None

    rating_raw = post.get("rating", "")
    if rating_raw not in ("explicit", "questionable"):
        return None

    tags = [t.lower() for t in post.get("tags", "").split() if t]
    if set(tags) & GELBOORU_BLACKLIST:
        return None

    url_lower = file_url.lower()
    if url_lower.endswith(".mp4"):
        mime = "video/mp4"
    elif url_lower.endswith(".webm"):
        mime = "video/webm"
    elif url_lower.endswith(".gif"):
        mime = "image/gif"
    elif url_lower.endswith(".png"):
        mime = "image/png"
    elif url_lower.endswith(".webp"):
        mime = "image/webp"
    else:
        mime = "image/jpeg"

    return {
        "id":        f"gelbooru_{post['id']}",
        "url":       file_url,
        "tags":      tags[:20],
        "likes":     int(post.get("score", 0)),
        "rating":    "XXX" if rating_raw == "explicit" else "X",
        "post_id":   post.get("id"),
        "mime":      mime,
        "createdAt": post.get("created_at"),
        "source":    "gelbooru",
        "prompt":    None,
    }


def fetch_gelbooru(
    limit: int = 100,
    max_pages: int = 5,
    media_type: str = "video",
) -> List[Dict[str, Any]]:
    """
    Args:
        media_type: "video" → animated/webm теги, "image" → фото теги
    """
    if not GELBOORU_API_KEY or not GELBOORU_USER_ID:
        logger.error("Gelbooru: нужны GELBOORU_API_KEY и GELBOORU_USER_ID в Secrets")
        return []

    tag_pool = VIDEO_TAG_SETS if media_type == "video" else IMAGE_TAG_SETS
    tag_set  = random.choice(tag_pool)
    logger.info(f"Gelbooru: media_type={media_type}, tags='{tag_set}'")

    all_results: List[Dict[str, Any]] = []
    seen_ids: set = set()
    start_pid = random.randint(0, 5)   # не уходим глубоко — там 401

    for page_offset in range(max_pages):
        pid = start_pid + page_offset
        params = {
            "page":    "dapi",
            "s":       "post",
            "q":       "index",
            "json":    1,
            "tags":    tag_set,
            "limit":   min(limit, 100),
            "pid":     pid,
            "api_key": GELBOORU_API_KEY,
            "user_id": GELBOORU_USER_ID,
        }

        try:
            r = requests.get(
                BASE_URL, params=params,
                headers={"User-Agent": "ErosLabBot/2.0"},
                timeout=30,
            )
            if r.status_code == 401:
                logger.error("Gelbooru 401 — проверь ключи в Secrets")
                break
            if r.status_code == 429:
                logger.warning("Gelbooru rate limited")
                break
            r.raise_for_status()

            data  = r.json()
            posts = data.get("post", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])

            if not posts:
                logger.info(f"Gelbooru page {pid}: empty")
                break

            logger.info(f"Gelbooru page {pid}: {len(posts)} posts")

            for post in posts:
                if not isinstance(post, dict):
                    continue
                pid_ = post.get("id")
                if pid_ in seen_ids:
                    continue
                seen_ids.add(pid_)
                if int(post.get("score", 0)) < GELBOORU_MIN_SCORE:
                    continue
                item = _build_item(post)
                if item:
                    all_results.append(item)

            if len(all_results) >= 60:
                break

        except Exception as e:
            logger.error(f"Gelbooru page {pid} error: {e}")
            continue

    logger.info(f"Gelbooru: итого {len(all_results)} items (media_type={media_type})")
    return all_results