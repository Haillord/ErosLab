"""
e6ai.net API parser for ErosLab Bot.
e6ai — дочерний сайт e621, специализированный ТОЛЬКО на AI-арте.
Регистрация: https://e6ai.net/users/new
"""

import os
import random
import logging
import requests
from typing import List, Dict, Any

logger = logging.getLogger("ErosLab.E6ai")

E6AI_LOGIN     = os.getenv("E6AI_LOGIN", "")
E6AI_API_KEY   = os.getenv("E6AI_API_KEY", "")
E6AI_MIN_SCORE = int(os.getenv("E6AI_MIN_SCORE", "3"))

BASE_URL = "https://e6ai.net"

# ── Видео (animated / webm) ───────────────────────────────────────────────────
VIDEO_TAG_SETS = [
    "rating:explicit animated -male/male -yaoi -loli -shota -anthro order:score",
    "rating:explicit webm -male/male -yaoi -loli -shota -anthro order:score",
    "rating:explicit animated -male/male -yaoi -loli -shota order:favcount",
    "rating:explicit webm -male/male -yaoi -loli -shota order:favcount",
]

# ── Фото ──────────────────────────────────────────────────────────────────────
IMAGE_TAG_SETS = [
    "rating:explicit -animated -male/male -yaoi -loli -shota -anthro order:score",
    "rating:explicit -animated -male/male -yaoi -loli -shota -anthro order:favcount",
    "rating:explicit -animated -male/male -yaoi -loli -shota order:score date:>=2025-01-01",
]

E6AI_BLACKLIST = {
    "loli", "shota", "child", "minor", "cub",
    "gore", "scat", "vore", "snuff",
    "male/male", "yaoi", "anthro",
}


def _flatten_tags(tags_dict: dict) -> list:
    flat = []
    for category_tags in tags_dict.values():
        if isinstance(category_tags, list):
            flat.extend(str(t).lower() for t in category_tags)
    return flat


def _build_item(post: dict) -> dict | None:
    file_data = post.get("file", {})
    file_url  = file_data.get("url")
    if not file_url:
        return None

    rating_raw = post.get("rating", "")
    if rating_raw not in ("e", "q"):
        return None

    tags_dict = post.get("tags", {})
    tags = _flatten_tags(tags_dict) if isinstance(tags_dict, dict) else []
    if set(tags) & E6AI_BLACKLIST:
        return None

    ext = file_data.get("ext", "").lower()
    if ext in ("mp4", "webm"):
        mime = f"video/{ext}"
    elif ext == "gif":
        mime = "image/gif"
    else:
        mime = f"image/{ext}" if ext else "image/jpeg"

    score_data = post.get("score", {})
    score = int(score_data.get("total", 0)) if isinstance(score_data, dict) else int(score_data or 0)
    fav_count = int(post.get("fav_count", 0))

    return {
        "id":        f"e6ai_{post['id']}",
        "url":       file_url,
        "tags":      tags[:20],
        "likes":     score + fav_count,
        "rating":    "XXX" if rating_raw == "e" else "X",
        "post_id":   post.get("id"),
        "mime":      mime,
        "createdAt": post.get("created_at"),
        "source":    "e6ai",
        "prompt":    None,
    }


def fetch_e6ai(
    limit: int = 75,
    max_pages: int = 4,
    media_type: str = "video",
) -> List[Dict[str, Any]]:
    """
    Args:
        media_type: "video" → animated/webm теги, "image" → фото теги
    """
    if not E6AI_LOGIN or not E6AI_API_KEY:
        logger.error("e6ai: нужны E6AI_LOGIN и E6AI_API_KEY в Secrets")
        return []

    tag_pool = VIDEO_TAG_SETS if media_type == "video" else IMAGE_TAG_SETS
    tag_set  = random.choice(tag_pool)
    logger.info(f"e6ai: media_type={media_type}, tags='{tag_set}'")

    all_results: List[Dict[str, Any]] = []
    seen_ids: set = set()
    start_page = random.randint(1, 8)

    for page_offset in range(max_pages):
        page = start_page + page_offset
        params = {
            "tags":    tag_set,
            "limit":   min(limit, 320),
            "page":    page,
            "login":   E6AI_LOGIN,
            "api_key": E6AI_API_KEY,
        }

        try:
            r = requests.get(
                f"{BASE_URL}/posts.json",
                params=params,
                headers={"User-Agent": "ErosLabBot/2.0 (by ErosLab on e6ai)"},
                timeout=30,
            )
            if r.status_code == 403:
                logger.error("e6ai: 403 — проверь E6AI_LOGIN и E6AI_API_KEY")
                break
            if r.status_code == 429:
                logger.warning("e6ai: rate limited")
                break
            r.raise_for_status()

            posts = r.json().get("posts", [])
            if not posts:
                logger.info(f"e6ai page {page}: empty")
                break

            logger.info(f"e6ai page {page}: {len(posts)} posts")

            for post in posts:
                post_id = post.get("id")
                if post_id in seen_ids:
                    continue
                seen_ids.add(post_id)

                score_data = post.get("score", {})
                score = int(score_data.get("total", 0)) if isinstance(score_data, dict) else int(score_data or 0)
                if score < E6AI_MIN_SCORE:
                    continue

                item = _build_item(post)
                if item:
                    all_results.append(item)

            if len(all_results) >= 50:
                break

        except Exception as e:
            logger.error(f"e6ai page {page} error: {e}")
            continue

    logger.info(f"e6ai: итого {len(all_results)} items (media_type={media_type})")
    return all_results