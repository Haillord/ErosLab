import os
import random
import requests
import logging
import time
from typing import List, Dict, Any

# Получаем данные из секретов GitHub (или ENV сервера)
R34_USER_ID = os.getenv("R34_USER_ID") or os.getenv("RULE34_USER_ID")
R34_API_KEY = os.getenv("R34_API_KEY") or os.getenv("RULE34_API_KEY")
RULE34_MIN_SCORE = int(os.getenv("RULE34_MIN_SCORE", "50"))
RULE34_REQUIRE_COMMENTS = os.getenv("RULE34_REQUIRE_COMMENTS", "false").lower() in ("1", "true", "yes", "on")

logger = logging.getLogger("ErosLab.Rule34")

# Разнообразные наборы тегов — выбираем случайный каждый раз
TAG_SETS = [
    # Базовые качественные 3D/анимация (самые рабочие в 2026)
    "3d_(artwork) animated rating:explicit",
    "3d_(artwork) video rating:explicit",

    # Для чистой анимации (не обязательно 3D)
    "animated rating:explicit",
    "gif rating:explicit",
    "webm rating:explicit"
]

# Теги для ИИ-контента (AI generated) — обновлено под 2026
AI_TAG_SETS = [
    # Изображения
    "ai_generated rating:explicit",
    
    # Анимированные AI (самое важное для видео)
    "ai_generated animated rating:explicit",
    "ai_generated webm rating:explicit",
    "ai_generated video rating:explicit",
]

# Теги для чистого 3D (с сильным исключением 2D и low-quality)
THREE_D_TAG_SETS = [
    "3d_(artwork) animated rating:explicit",
    "3d_(artwork) video rating:explicit"
]


def _filter_tags_by_media_type(tag_sets: list[str], media_type: str) -> list[str]:
    """
    Фильтрует наборы тегов по типу медиа.
    - media_type="video" → только теги с animated/gif/webm/video
    - media_type="image" → только теги БЕЗ animated/gif/webm/video
    - media_type="mixed" → все теги как есть
    """
    if media_type == "mixed":
        return tag_sets

    video_keywords = {"animated", "gif", "webm", "video"}
    result = []
    for tags_str in tag_sets:
        words = set(tags_str.lower().split())
        is_video_tags = bool(words & video_keywords)
        if media_type == "video" and is_video_tags:
            result.append(tags_str)
        elif media_type == "image" and not is_video_tags:
            result.append(tags_str)
    return result or tag_sets  # fallback на все если после фильтрации пусто


def _detect_mime_from_url(file_url: str) -> str:
    """Определяет MIME-тип по расширению URL."""
    url_lower = file_url.lower().split('?')[0]
    if url_lower.endswith(('.mp4', '.webm')):
        return "video/mp4"
    elif url_lower.endswith('.gif'):
        return "image/gif"
    elif url_lower.endswith('.png'):
        return "image/png"
    else:
        return "image/jpeg"


def _request_with_backoff(url, params, headers, max_retries=3):
    """Request с retry при 429 и 500, как в CivitAI."""
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            if r.status_code == 429:
                wait = 2 ** attempt * 5
                logger.warning(f"Rule34 rate limited (429), waiting {wait}s before retry {attempt + 1}/{max_retries}")
                time.sleep(wait)
                continue
            if r.status_code >= 500:
                wait = 2 + attempt * 2
                logger.warning(f"Rule34 server error {r.status_code}, retry {attempt + 1}/{max_retries}")
                if attempt >= max_retries - 1:
                    return None
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except requests.exceptions.Timeout:
            logger.warning(f"Rule34 timeout on attempt {attempt + 1}/{max_retries}")
            if attempt < max_retries - 1:
                time.sleep(3)
        except requests.exceptions.HTTPError as e:
            if r.status_code >= 500:
                logger.warning(f"Rule34 server error {r.status_code}, retry {attempt + 1}/{max_retries}")
                time.sleep(2 ** attempt * 2)
            else:
                raise
        except Exception as e:
            logger.error(f"Rule34 request error: {e}")
            raise
    return None


def fetch_rule34(tags: str = None, limit: int = 100, content_type: str = "mixed", media_type: str = "mixed") -> List[Dict[str, Any]]:
    """
    Парсинг Rule34 через API с авторизацией и пагинацией
    
    Args:
        tags: конкретные теги (если None, выбираются случайно)
        limit: количество постов
        content_type: "mixed", "3d", "ai" — тип контента
        media_type: "mixed", "video", "image" — тип медиа
    """
    
    # Выбор тегов на основе типа контента
    if tags is None:
        if content_type == "ai":
            if media_type == "video":
                animated_tags = [t for t in AI_TAG_SETS if "animated" in t.lower()]
                tags = random.choice(animated_tags) if animated_tags else random.choice(AI_TAG_SETS)
            else:
                tags = random.choice(AI_TAG_SETS)
        elif content_type == "3d":
            filtered = _filter_tags_by_media_type(THREE_D_TAG_SETS, media_type)
            tags = random.choice(filtered)
        else:
            filtered = _filter_tags_by_media_type(TAG_SETS, media_type)
            tags = random.choice(filtered)
    
    # Добавляем rating:explicit если нет
    if "rating:explicit" not in tags:
        tags = tags + " rating:explicit"

    if not R34_USER_ID or not R34_API_KEY:
        logger.error("API credentials are missing in environment variables!")
        return []
  

    logger.info(f"Rule34: using tags = '{tags}'")

    url = "https://api.rule34.xxx/index.php"
    headers = {"User-Agent": "ErosLabBot/1.0 (Windows NT 10.0; Win64; x64)"}
    
    all_results = []
    # Начинаем с первой страницы, собираем топ
    max_pages = 5  # Собираем 5 страниц с самых свежих
    min_posts = 50  # Минимум постов для выбора
    
    logger.info(f"Rule34: scanning first {max_pages} pages (start_page=0)")
    
    # Rule34 API: pid=0 — первая страница, pid=1 — вторая, и т.д.
    pages_scanned = 0
    for page in range(0, max_pages):
        pages_scanned += 1
        params = {
            "page": "dapi",
            "s": "post",
            "q": "index",
            "json": 1,
            "limit": limit,
            "pid": page,  # Номер страницы (начинается с 0)
            "tags": tags,
            "user_id": R34_USER_ID,
            "api_key": R34_API_KEY
        }

        try:
            r = _request_with_backoff(url, params=params, headers=headers)
            if r is None:
                logger.warning(f"Rule34 page {page}: no response after retries")
                continue

            if not r.text.strip():
                logger.warning(f"Rule34 page {page}: empty response, stopping")
                break  # Early break — если страница пуста, дальше тоже пусто

            posts = r.json()

            if not isinstance(posts, list):
                logger.warning(f"Rule34 page {page}: unexpected response format, stopping")
                break  # Early break

            logger.info(f"Rule34 page {page}: got {len(posts)} posts")

            for post in posts:
                if not isinstance(post, dict):
                    continue

                rating = post.get("rating", "")
                mapped_rating = "XXX" if rating == "e" else "X"

                file_url = post.get("file_url")
                if not file_url:
                    continue

                # Фильтруем по минимальному score
                try:
                    score = int(post.get("score", 0))
                except (TypeError, ValueError):
                    score = 0
                if score < RULE34_MIN_SCORE:
                    continue

                # Опционально: пропускаем посты без комментариев
                if RULE34_REQUIRE_COMMENTS:
                    if post.get("has_comments") != "true":
                        continue

                post_tags = post.get("tags", "").split()

                # Определяем MIME по расширению URL
                mime = _detect_mime_from_url(file_url)

                all_results.append({
                    "id":        f"r34_{post['id']}",
                    "url":       file_url,
                    "tags":      post_tags[:15],
                    "likes":     score,
                    "rating":    mapped_rating,
                    "post_id":   post.get("id"),
                    "source":    "rule34",
                    "mime":      mime,
                    "createdAt": post.get("change"),
                    "prompt":    None,
                })

            # Если набрали достаточно постов — останавливаемся
            if len(all_results) >= min_posts:
                logger.info(f"Rule34: collected {len(all_results)} posts from {pages_scanned} scanned pages")
                break

        except Exception as e:
            logger.error(f"Rule34 page {page} error: {e}")
            continue

    # Сортируем по score (лучшие — первые) и возвращаем
    all_results.sort(key=lambda x: x["likes"], reverse=True)
    logger.info(f"Rule34: Found {len(all_results)} total posts, top score: {all_results[0]['likes'] if all_results else 0}")
    return all_results