"""
Gelbooru API parser for ErosLab Bot.
Огромная база, бесплатный API без обязательного ключа.
Ключ нужен только для снятия rate-limit (опционально).
"""

import os
import random
import logging
import requests
from typing import List, Dict, Any

logger = logging.getLogger("ErosLab.Gelbooru")

# Опционально — снимает rate-limit
GELBOORU_API_KEY = os.getenv("GELBOORU_API_KEY", "")
GELBOORU_USER_ID = os.getenv("GELBOORU_USER_ID", "")
GELBOORU_MIN_SCORE = int(os.getenv("GELBOORU_MIN_SCORE", "5"))

BASE_URL = "https://gelbooru.com/index.php"

# Наборы тегов — чередуем случайным образом
# Gelbooru не ограничивает кол-во тегов (в отличие от Danbooru без подписки)
TAG_SETS = [
    # AI-generated explicit, без male-only
    "ai_generated rating:explicit -loli -shota -1boy -solo_male -yaoi sort:score:desc",
    "ai_generated rating:explicit -loli -shota -1boy -solo_male -yaoi sort:updated:desc",

    # Анимированный AI
    "ai_generated animated rating:explicit -loli -shota -1boy -solo_male sort:score:desc",
    "ai_generated webm rating:explicit -loli -shota -1boy -solo_male sort:score:desc",

    # 3D artwork explicit
    "3d_(artwork) rating:explicit -loli -shota -1boy -solo_male -yaoi sort:score:desc",
    "3d_(artwork) animated rating:explicit -loli -shota -1boy -solo_male sort:score:desc",

    # Смешанный топ
    "rating:explicit -loli -shota -1boy -solo_male -yaoi -gore sort:score:desc",
]

GELBOORU_BLACKLIST = {
    "loli", "shota", "child", "minor", "underage",
    "gore", "guro", "scat", "vore", "snuff", "necrophilia",
    "1boy", "solo_male", "male_focus", "male_pov",
    "yaoi", "bara", "2boys", "3boys", "multiple_boys",
    "bestiality", "zoo",
    "furry_male", "anthro",
}


def _build_item(post: dict) -> dict | None:
    """Конвертирует пост Gelbooru в унифицированный формат ErosLab."""
    file_url = post.get("file_url")
    if not file_url:
        return None

    rating_raw = post.get("rating", "")
    # Gelbooru: "explicit", "questionable", "sensitive", "general"
    if rating_raw not in ("explicit", "questionable"):
        return None

    tag_string = post.get("tags", "")
    tags = [t.lower() for t in tag_string.split() if t]

    if set(tags) & GELBOORU_BLACKLIST:
        return None

    # mime по расширению URL
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

    score = int(post.get("score", 0))
    rating_mapped = "XXX" if rating_raw == "explicit" else "X"

    return {
        "id":        f"gelbooru_{post['id']}",
        "url":       file_url,
        "tags":      tags[:20],
        "likes":     score,
        "rating":    rating_mapped,
        "post_id":   post.get("id"),
        "mime":      mime,
        "createdAt": post.get("created_at"),
        "source":    "gelbooru",
        "prompt":    None,
    }


def fetch_gelbooru(limit: int = 100, max_pages: int = 5) -> List[Dict[str, Any]]:
    """
    Парсит Gelbooru через публичный dapi.

    Args:
        limit:     постов на страницу (макс 100)
        max_pages: страниц для обхода
    Returns:
        Список унифицированных item-словарей
    """
    tag_set = random.choice(TAG_SETS)
    logger.info(f"Gelbooru: tags = '{tag_set}'")

    all_results: List[Dict[str, Any]] = []
    seen_ids: set = set()
    # pid у Gelbooru = номер страницы (0-based)
    start_pid = random.randint(0, 20)

    for page_offset in range(max_pages):
        pid = start_pid + page_offset

        params = {
            "page":  "dapi",
            "s":     "post",
            "q":     "index",
            "json":  1,
            "tags":  tag_set,
            "limit": min(limit, 100),
            "pid":   pid,
        }
        if GELBOORU_API_KEY and GELBOORU_USER_ID:
            params["api_key"] = GELBOORU_API_KEY
            params["user_id"] = GELBOORU_USER_ID

        try:
            r = requests.get(
                BASE_URL,
                params=params,
                headers={"User-Agent": "ErosLabBot/2.0"},
                timeout=30,
            )

            if r.status_code == 429:
                logger.warning("Gelbooru: rate limited, stopping")
                break
            r.raise_for_status()

            data = r.json()
            # Gelbooru возвращает либо {"post": [...]} либо просто список
            if isinstance(data, dict):
                posts = data.get("post", [])
            elif isinstance(data, list):
                posts = data
            else:
                logger.warning(f"Gelbooru page {pid}: unexpected format")
                break

            if not posts:
                logger.info(f"Gelbooru page {pid}: empty, stopping")
                break

            logger.info(f"Gelbooru page {pid}: got {len(posts)} posts")

            for post in posts:
                if not isinstance(post, dict):
                    continue
                post_id = post.get("id")
                if post_id in seen_ids:
                    continue
                seen_ids.add(post_id)

                score = int(post.get("score", 0))
                if score < GELBOORU_MIN_SCORE:
                    continue

                item = _build_item(post)
                if item:
                    all_results.append(item)

            if len(all_results) >= 60:
                break

        except Exception as e:
            logger.error(f"Gelbooru page {pid} error: {e}")
            continue

    logger.info(f"Gelbooru: fetched {len(all_results)} items total")
    return all_results
