"""
e6ai.net API parser for ErosLab Bot.
e6ai — дочерний сайт e621, специализированный ТОЛЬКО на AI-арте.
Использует тот же API формат что и e621.
Регистрация: https://e6ai.net/users/new
"""

import os
import random
import logging
import requests
from typing import List, Dict, Any

logger = logging.getLogger("ErosLab.E6ai")

E6AI_LOGIN   = os.getenv("E6AI_LOGIN", "")
E6AI_API_KEY = os.getenv("E6AI_API_KEY", "")
E6AI_MIN_SCORE = int(os.getenv("E6AI_MIN_SCORE", "3"))

BASE_URL = "https://e6ai.net"

# На e6ai весь контент — AI-арт, поэтому теги проще
# Блэклистим только нежелательный контент
TAG_SETS = [
    # Explicit без мужских и нежелательных тегов
    "rating:explicit -male/male -yaoi -loli -shota -anthro order:score",
    "rating:explicit -male/male -yaoi -loli -shota -anthro order:favcount",
    # Топ недели (e6ai поддерживает date фильтры)
    "rating:explicit -male/male -yaoi -loli -shota order:score date:>=2025-01-01",
    # Animated explicit (много качественной анимации)
    "rating:explicit animated -male/male -yaoi -loli -shota order:score",
    "rating:explicit webm -male/male -yaoi -loli order:score",
]

E6AI_BLACKLIST = {
    "loli", "shota", "child", "minor", "cub",
    "gore", "scat", "vore", "snuff",
    "male/male", "yaoi",
    "anthro",  # антропоморфные (фурри)
}


def _flatten_tags(tags_dict: dict) -> list:
    """e621/e6ai возвращает теги по категориям — объединяем в плоский список."""
    flat = []
    for category_tags in tags_dict.values():
        if isinstance(category_tags, list):
            flat.extend(str(t).lower() for t in category_tags)
    return flat


def _build_item(post: dict) -> dict | None:
    """Конвертирует пост e6ai в унифицированный формат ErosLab."""
    file_data = post.get("file", {})
    file_url  = file_data.get("url")
    if not file_url:
        return None

    # e6ai: "e" = explicit, "q" = questionable, "s" = safe
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
    elif ext in ("png", "jpg", "jpeg", "webp"):
        mime = f"image/{ext}"
    else:
        mime = "image/jpeg"

    score_data = post.get("score", {})
    score = int(score_data.get("total", 0)) if isinstance(score_data, dict) else int(score_data or 0)

    fav_count = int(post.get("fav_count", 0))
    # Используем сумму score + favcount как аналог likes для весового выбора
    likes = score + fav_count

    rating_mapped = "XXX" if rating_raw == "e" else "X"

    return {
        "id":        f"e6ai_{post['id']}",
        "url":       file_url,
        "tags":      tags[:20],
        "likes":     likes,
        "rating":    rating_mapped,
        "post_id":   post.get("id"),
        "mime":      mime,
        "createdAt": post.get("created_at"),
        "source":    "e6ai",
        "prompt":    None,
    }


def fetch_e6ai(limit: int = 75, max_pages: int = 4) -> List[Dict[str, Any]]:
    """
    Парсит e6ai.net через REST API (формат e621).

    Args:
        limit:     постов на страницу (макс 320, рекомендуется 75)
        max_pages: страниц для обхода
    Returns:
        Список унифицированных item-словарей
    """
    if not E6AI_LOGIN or not E6AI_API_KEY:
        logger.error("e6ai: E6AI_LOGIN и E6AI_API_KEY обязательны! Добавь в GitHub Secrets.")
        return []

    tag_set = random.choice(TAG_SETS)
    logger.info(f"e6ai: tags = '{tag_set}'")

    all_results: List[Dict[str, Any]] = []
    seen_ids: set = set()
    start_page = random.randint(1, 8)

    for page_offset in range(max_pages):
        page = start_page + page_offset

        params = {
            "tags":  tag_set,
            "limit": min(limit, 320),
            "page":  page,
            "login": E6AI_LOGIN,
            "api_key": E6AI_API_KEY,
        }

        try:
            r = requests.get(
                f"{BASE_URL}/posts.json",
                params=params,
                headers={
                    # e621 требует осмысленный User-Agent с контактом
                    "User-Agent": "ErosLabBot/2.0 (by ErosLab on e6ai)",
                },
                timeout=30,
            )

            if r.status_code == 429:
                logger.warning("e6ai: rate limited, stopping")
                break
            if r.status_code == 403:
                logger.error("e6ai: 403 Forbidden — проверь E6AI_LOGIN и E6AI_API_KEY")
                break
            r.raise_for_status()

            data = r.json()
            posts = data.get("posts", [])

            if not posts:
                logger.info(f"e6ai page {page}: empty, stopping")
                break

            logger.info(f"e6ai page {page}: got {len(posts)} posts")

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

    logger.info(f"e6ai: fetched {len(all_results)} items total")
    return all_results
