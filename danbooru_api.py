"""
Danbooru API parser for ErosLab Bot.
Fetches explicit AI-generated anime art via the public REST API.
Requires a free Danbooru account for full access (2 tags unauthenticated, unlimited authenticated).
"""

import os
import random
import logging
import requests
from typing import List, Dict, Any

logger = logging.getLogger("ErosLab.Danbooru")

DANBOORU_LOGIN     = os.getenv("DANBOORU_LOGIN", "")
DANBOORU_API_KEY   = os.getenv("DANBOORU_API_KEY", "")
DANBOORU_MIN_SCORE = int(os.getenv("DANBOORU_MIN_SCORE", "5"))
DANBOORU_MIN_SIZE  = int(os.getenv("DANBOORU_MIN_SIZE", "720"))

BASE_URL = "https://danbooru.donmai.us"

# Наборы тегов — чередуем случайным образом.
# Authenticated аккаунт поддерживает до 6 тегов одновременно.
TAG_SETS = [
    "ai-generated rating:explicit",
    "rating:explicit order:rank",
]

DANBOORU_BLACKLIST = {
    "loli", "shota", "child", "minor", "underage",
    "gore", "guro", "scat", "vore", "snuff", "necrophilia",
    "1boy", "solo_male", "male_focus", "male_pov",
    "yaoi", "bara", "2boys", "3boys", "multiple_boys",
    "bestiality", "zoo",
    "furry_male", "anthro",
}


def _build_item(post: dict, min_size: int = 720) -> dict | None:
    """Конвертирует пост Danbooru в унифицированный формат ErosLab."""

    # ── Фильтр по расширению ──────────────────────────────────────────────────
    ext = post.get("file_ext", "").lower()

    # zip = ugoira-анимации, бот не умеет их отправлять
    if ext == "zip":
        return None

    if ext in ("mp4", "webm"):
        mime = f"video/{ext}"
    elif ext == "gif":
        mime = "image/gif"
    elif ext in ("png", "jpg", "jpeg", "webp"):
        mime = f"image/{ext}"
    else:
        mime = "image/jpeg"

    # ── Фильтр по размеру ─────────────────────────────────────────────────────
    width  = int(post.get("image_width",  0))
    height = int(post.get("image_height", 0))
    if width < min_size or height < min_size:
        return None

    # ── Выбор URL ─────────────────────────────────────────────────────────────
    # large_file_url (~1000px) — доступен без gold даже для explicit
    # file_url (оригинал)      — требует gold для explicit-постов → 403
    # sample_url               — маленький превью, крайний случай
    if post.get("large_file_url"):
        file_url = post["large_file_url"]
        url_type = "large"
    elif post.get("file_url"):
        file_url = post["file_url"]
        url_type = "original"
    elif post.get("sample_url"):
        file_url = post["sample_url"]
        url_type = "sample"
    else:
        return None

    logger.debug(f"Danbooru #{post.get('id')}: using {url_type} url")

    # ── Рейтинг ───────────────────────────────────────────────────────────────
    # Danbooru: "e" = explicit, "q" = questionable, "s" = safe
    rating_raw = post.get("rating", "")
    if rating_raw not in ("e", "q"):
        return None

    # ── Теги и блэклист ───────────────────────────────────────────────────────
    tag_string = post.get("tag_string_general", "") or post.get("tag_string", "")
    tags = [t.lower() for t in tag_string.split() if t]

    if set(tags) & DANBOORU_BLACKLIST:
        return None

    score        = int(post.get("score", 0))
    rating_mapped = "XXX" if rating_raw == "e" else "X"

    return {
        "id":        f"danbooru_{post['id']}",
        "url":       file_url,
        "tags":      tags[:20],
        "likes":     score,
        "rating":    rating_mapped,
        "post_id":   post.get("id"),
        "mime":      mime,
        "width":     width,
        "height":    height,
        "createdAt": post.get("created_at"),
        "source":    "danbooru",
        "prompt":    None,
    }


def fetch_danbooru(limit: int = 100, max_pages: int = 5) -> List[Dict[str, Any]]:
    """
    Парсит Danbooru через REST API.

    Args:
        limit:     постов на страницу (макс 200)
        max_pages: страниц для обхода
    Returns:
        Список унифицированных item-словарей
    """
    if not DANBOORU_LOGIN or not DANBOORU_API_KEY:
        logger.warning("Danbooru: no credentials, using anonymous mode (limited to 2 tags)")

    tag_set = random.choice(TAG_SETS)
    logger.info(f"Danbooru: tags = '{tag_set}'")

    all_results: List[Dict[str, Any]] = []
    seen_ids: set = set()
    start_page = random.randint(1, 10)

    auth = (DANBOORU_LOGIN, DANBOORU_API_KEY) if DANBOORU_LOGIN and DANBOORU_API_KEY else None

    for page_offset in range(max_pages):
        page = start_page + page_offset

        params = {
            "tags":  tag_set,
            "limit": min(limit, 200),
            "page":  page,
        }

        try:
            r = requests.get(
                f"{BASE_URL}/posts.json",
                params=params,
                auth=auth,
                headers={"User-Agent": "ErosLabBot/2.0"},
                timeout=30,
            )

            if r.status_code == 429:
                logger.warning("Danbooru: rate limited, stopping")
                break
            if r.status_code == 422:
                logger.warning(f"Danbooru: invalid tags '{tag_set}', skip")
                break
            r.raise_for_status()

            posts = r.json()
            if not isinstance(posts, list) or not posts:
                logger.info(f"Danbooru page {page}: empty, stopping")
                break

            logger.info(f"Danbooru page {page}: got {len(posts)} posts")

            for post in posts:
                post_id = post.get("id")
                if post_id in seen_ids:
                    continue
                seen_ids.add(post_id)

                if int(post.get("score", 0)) < DANBOORU_MIN_SCORE:
                    continue

                item = _build_item(post, min_size=DANBOORU_MIN_SIZE)
                if item:
                    all_results.append(item)

            if len(all_results) >= 60:
                break

        except Exception as e:
            logger.error(f"Danbooru page {page} error: {e}")
            continue

    logger.info(f"Danbooru: fetched {len(all_results)} items total")
    return all_results