"""
CivitAI API wrapper.
Парсит топ-контент с CivitAI.
Возвращает items в формате совместимом с eroslab_bot.py.
"""

import logging
import os
import random
import re
import time

import requests

logger = logging.getLogger("ErosLab.CivitAI")


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
            if r.status_code == 500:
                wait = 2 + attempt * 2
                logger.warning(f"Server error 500, retry {attempt + 1}/{max_retries}")
                if attempt >= max_retries - 1:
                    return None
                time.sleep(wait)
                continue
            if r.status_code == 400:
                return r
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


def _is_x_or_xxx(nsfw_level):
    if isinstance(nsfw_level, str):
        value = nsfw_level.strip().lower()
        return value in {"x", "xxx"}
    if isinstance(nsfw_level, (int, float)):
        return nsfw_level >= 8
    return False


def _is_mature_or_higher(nsfw_level):
    if isinstance(nsfw_level, str):
        value = nsfw_level.strip().lower()
        return value in {"mature", "x", "xxx"}
    if isinstance(nsfw_level, (int, float)):
        return nsfw_level >= 4
    return False


def _to_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _extract_civitai_likes(item: dict) -> int:
    if not isinstance(item, dict):
        return 0
    stats = item.get("stats")
    if isinstance(stats, dict):
        total = (
            _to_int(stats.get("likeCount"), 0) +
            _to_int(stats.get("heartCount"), 0) +
            _to_int(stats.get("laughCount"), 0)
        )
        if total > 0:
            return total
    return (
        _to_int(item.get("likeCount"), 0) or
        _to_int(item.get("heartCount"), 0)
    )


def _extract_civitai_prompt(item: dict) -> str | None:
    meta = item.get("meta")
    if not isinstance(meta, dict):
        return None
    prompt = (
        meta.get("prompt") or meta.get("Prompt") or meta.get("positive") or ""
    ).strip()
    if not prompt or len(prompt) < 20:
        return None
    prompt = re.sub(r'<[^>]+>', '', prompt)
    prompt = re.sub(
        r'\b(score_\d+[\w_]*|masterpiece|best quality|highres|absurdres'
        r'|ultra[\w ]*|extremely detailed|step\d+|cfg\s*\d+|BREAK)\b',
        '', prompt, flags=re.IGNORECASE
    )
    prompt = re.sub(r',\s*,', ',', prompt)
    prompt = re.sub(r'\s+', ' ', prompt).strip(", ")
    return prompt or None


def _get_adaptive_max_pages(period: str | None) -> int:
    if period == "Day":
        return 5
    elif period in ("Week",):
        return 10
    else:
        return 15


def _fetch_civitai_variation(base_params: dict, headers: dict, seen_ids: set) -> list[dict]:
    all_items = []
    next_page_url = None
    max_pages = _get_adaptive_max_pages(base_params.get("period"))

    for page in range(1, max_pages + 1):
        request_url = next_page_url or "https://civitai.com/api/v1/images"
        params = None if next_page_url else {**base_params, "limit": 100}

        try:
            r = _request_with_backoff(request_url, params=params, headers=headers)
            if r is None:
                logger.warning(f"CivitAI page {page}: no response for {base_params}")
                if page == 1:
                    return []
                break
            if r.status_code == 400:
                logger.debug(f"CivitAI page {page}: 400 for {params}")
                continue

            data = r.json()
            items = data.get("items", [])
            if not items:
                logger.debug(f"CivitAI page {page}: no items")
                continue

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

    return all_items


def _is_nsfw_allowed(nsfw_level) -> bool:
    """
    Проверяет, разрешён ли NSFW уровень для текущего browsingLevel.
    - browsingLevel=3 (SFM/Mature): пропускаем nsfwLevel >= 3
    - browsingLevel=28 (NSFW): пропускаем nsfwLevel >= 8 (как и было)
    """
    browsing_level = get_civitai_browsing_level()
    min_nsfw = 3 if browsing_level <= 3 else 8
    if isinstance(nsfw_level, (int, float)):
        return nsfw_level >= min_nsfw
    if isinstance(nsfw_level, str):
        try:
            return int(nsfw_level) >= min_nsfw
        except (TypeError, ValueError):
            return nsfw_level.strip().lower() in {"x", "xxx"}
    return False


def _process_civitai_items(items: list[dict]) -> list[dict]:
    if not items:
        return []

    items_with_positive_reactions = 0
    total_checked = 0
    for item in items:
        stats = item.get("stats")
        if isinstance(stats, dict):
            total_checked += 1
            if any(stats.get(k, 0) for k in ("likeCount", "heartCount", "laughCount")):
                items_with_positive_reactions += 1

    likes_filter_enabled = (
        total_checked > 0
        and items_with_positive_reactions > total_checked * 0.1
    )
    logger.info(
        f"Likes filter status: {'enabled' if likes_filter_enabled else 'disabled'} "
        f"(items_with_reactions={items_with_positive_reactions}/{total_checked})"
    )

    min_likes = int(os.environ.get("MIN_CIVITAI_LIKES", "50"))

    erotic_items = []
    for item in items:
        try:
            nsfw_level = item.get("nsfwLevel")
            is_allowed_nsfw = _is_nsfw_allowed(nsfw_level)
            if not is_allowed_nsfw:
                continue

            # Теги и блэклист обрабатываются в eroslab_bot.py,
            # здесь мы просто собираем сырые данные.
            likes = _extract_civitai_likes(item)
            if likes_filter_enabled and likes < min_likes:
                continue

            erotic_items.append({
                "id":        f"civitai_{item['id']}",
                "url":       item.get("url", ""),
                "tags":      [],
                "likes":     likes,
                "rating":    nsfw_level,
                "post_id":   item.get("postId"),
                "mime":      (item.get("mimeType") or "").lower(),
                "createdAt": item.get("createdAt"),
                "source":    "civitai",
                "prompt":    _extract_civitai_prompt(item),
            })
        except Exception as e:
            logger.error(f"Error processing item {item.get('id')}: {e}")
            continue

    return erotic_items


def get_civitai_browsing_level() -> int:
    """
    Возвращает browsingLevel для CivitAI из ENV.
    По умолчанию 28 (NSFW). Для SFM режима используется 3 (Mature).
    """
    level = os.environ.get("CIVITAI_BROWSING_LEVEL", "28")
    try:
        return int(level)
    except (TypeError, ValueError):
        return 28


def fetch_civitai(max_pages: int = 5):
    """
    Собирает топ-контент с CivitAI.

    Стратегия:
    1. Сначала собираем Most Reactions за все периоды (Day, Week, Month, All Time)
       в общий пул, сортируем по лайкам, возвращаем топ.
    2. Если ничего не нашли — fallback на Newest.
    """
    browsing_level = get_civitai_browsing_level()
    
    variations = [
        {"browsingLevel": browsing_level, "nsfw": "X", "sort": "Most Reactions", "period": "Day", "mediaType": "video"},
        {"browsingLevel": browsing_level, "nsfw": "X", "sort": "Most Reactions", "period": "Week", "mediaType": "video"},
        {"browsingLevel": browsing_level, "nsfw": "X", "sort": "Most Reactions", "period": "Month", "mediaType": "video"},
        {"browsingLevel": browsing_level, "nsfw": "X", "sort": "Most Reactions", "period": "Day"},
        {"browsingLevel": browsing_level, "nsfw": "X", "sort": "Most Reactions", "period": "Week"},
        {"browsingLevel": browsing_level, "nsfw": "X", "sort": "Most Reactions", "period": "Month"},
        {"browsingLevel": browsing_level, "nsfw": "X", "sort": "Most Reactions"},
    ]

    headers = {}
    if "CIVITAI_API_KEY" in os.environ:
        headers["Authorization"] = f"Bearer {os.environ['CIVITAI_API_KEY']}"
    seen_ids: set = set()

    all_collected = []
    for base_params in variations:
        items = _fetch_civitai_variation(base_params, headers, seen_ids)
        if items:
            period = base_params.get("period", "All Time")
            logger.info(f"CivitAI {base_params['sort']} ({period}): collected {len(items)} raw items")
            erotic = _process_civitai_items(items)
            if erotic:
                logger.info(f"CivitAI {base_params['sort']} ({period}): {len(erotic)} suitable items")
                all_collected.extend(erotic)

    if all_collected:
        all_collected.sort(key=lambda x: x["likes"], reverse=True)
        logger.info(
            f"CivitAI Most Reactions total: {len(all_collected)} items, "
            f"top likes: {all_collected[0]['likes']}"
        )
        return all_collected

    logger.info("CivitAI Most Reactions: no suitable items, falling back to Newest")
    newest_variations = [
        {"browsingLevel": browsing_level, "nsfw": "X", "sort": "Newest", "mediaType": "video"},
        {"browsingLevel": browsing_level, "nsfw": "X", "sort": "Newest"},
        {"browsingLevel": browsing_level, "nsfw": "X", "sort": "Newest", "period": "Week"},
        {"browsingLevel": browsing_level, "nsfw": "X", "sort": "Newest", "period": "Month"},
    ]

    for base_params in newest_variations:
        items = _fetch_civitai_variation(base_params, headers, seen_ids)
        if items:
            period = base_params.get("period", "N/A")
            logger.info(f"CivitAI Newest ({period}): {len(items)} raw items")
            erotic = _process_civitai_items(items)
            if erotic:
                logger.info(f"CivitAI Newest ({period}): {len(erotic)} suitable items")
                return erotic

    return []
