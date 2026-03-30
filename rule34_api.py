import os
import random
import requests
import logging
from typing import List, Dict, Any

# Получаем данные из секретов GitHub (или ENV сервера)
R34_USER_ID = os.getenv("R34_USER_ID") or os.getenv("RULE34_USER_ID")
R34_API_KEY = os.getenv("R34_API_KEY") or os.getenv("RULE34_API_KEY")

logger = logging.getLogger("ErosLab.Rule34")

# Разнообразные наборы тегов — выбираем случайный каждый раз
TAG_SETS = [
    "animated",
    "3d_(artwork)",
    "animated 3d_(artwork)",
    "animated tagme",
    "3d_(artwork) tagme",
]

# Теги для ИИ-контента (AI generated) - улучшенные
AI_TAG_SETS = [
    # Базовые теги
    "stable_diffusion",
    "ai_generated",
    "generated_by_ai",
    "novelai",
    
    # Видео теги
    "stable_diffusion video",
    "ai_generated video",
    "generated_by_ai video",
    "novelai video",
    
    # Анимированные теги
    "stable_diffusion animated",
    "ai_generated animated",
    "generated_by_ai animated",
]

# Теги для 3D контента (с исключением 2D)
THREE_D_TAG_SETS = [
    "3d_(artwork) rating:explicit -2d -hand_drawn -drawn",
    "3d_video rating:explicit -2d",
    "3d_(artwork) animated rating:explicit -2d",
]

def fetch_rule34(tags: str = None, limit: int = 100, content_type: str = "mixed", media_type: str = "mixed") -> List[Dict[str, Any]]:
    """
    Парсинг Rule34 через API с авторизацией
    
    Args:
        tags: конкретные теги (если None, выбираются случайно)
        limit: количество постов
        content_type: "mixed", "3d", "ai" — тип контента
        media_type: "mixed", "video", "image" — тип медиа (70% video, 30% image)
    """
    
    # Выбор тегов на основе типа контента
    if tags is None:
        if content_type == "ai":
            tags = random.choice(AI_TAG_SETS)
        elif content_type == "3d":
            tags = random.choice(THREE_D_TAG_SETS)
        else:
            tags = random.choice(TAG_SETS)
    
    # Добавляем тег для видео или фото если нужно
    if media_type == "video" and "video" not in tags and "animated" not in tags:
        tags = tags + " video"
    elif media_type == "image" and "video" not in tags and "animated" not in tags:
        tags = tags + " photo"
    
    # Добавляем rating:explicit если нет
    if "rating:explicit" not in tags:
        tags = tags + " rating:explicit"

    if not R34_USER_ID or not R34_API_KEY:
        logger.error("API credentials are missing in environment variables!")
        return []

    if tags is None:
        tags = random.choice(TAG_SETS)

    logger.info(f"Rule34: using tags = '{tags}'")

    url = "https://api.rule34.xxx/index.php"
    params = {
        "page": "dapi",
        "s": "post",
        "q": "index",
        "json": 1,
        "limit": limit,
        "tags": tags,
        "user_id": R34_USER_ID,
        "api_key": R34_API_KEY
    }

    headers = {"User-Agent": "ErosLabBot/1.0 (Windows NT 10.0; Win64; x64)"}

    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
        r.raise_for_status()

        if not r.text.strip():
            logger.warning("Rule34 returned empty response")
            return []

        posts = r.json()

        if not isinstance(posts, list):
            logger.error(f"Rule34 unexpected response format: {type(posts)}")
            return []

        logger.info(f"Rule34 raw posts count: {len(posts)}")

        # Логируем первые посты чтобы видеть структуру
        if posts:
            logger.info(f"Rule34 sample keys: {list(posts[0].keys())}")
            logger.info(f"Rule34 sample ratings: {[p.get('rating') for p in posts[:5]]}")

        results = []
        for post in posts:
            if not isinstance(post, dict):
                continue

            # Принимаем все рейтинги
            rating = post.get("rating", "")
            mapped_rating = "XXX" if rating == "e" else "X"

            file_url = post.get("file_url")
            if not file_url:
                continue

            post_tags = post.get("tags", "").split()

            results.append({
                "id":      f"r34_{post['id']}",
                "url":     file_url,
                "tags":    post_tags[:15],
                "likes":   int(post.get("score", 0)),
                "rating":  mapped_rating,
                "post_id": post.get("id"),
                "source":  "rule34"
            })

        logger.info(f"Rule34: Found {len(results)} posts after filtering")
        return results

    except Exception as e:
        logger.error(f"Rule34 API Error: {e}")
        return []