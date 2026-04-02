import os
import random
import requests
import logging
from typing import List, Dict, Any

# Получаем данные из секретов GitHub (или ENV сервера)
R34_USER_ID = os.getenv("R34_USER_ID") or os.getenv("RULE34_USER_ID")
R34_API_KEY = os.getenv("R34_API_KEY") or os.getenv("RULE34_API_KEY")
RULE34_MIN_SCORE = int(os.getenv("RULE34_MIN_SCORE", "10"))

logger = logging.getLogger("ErosLab.Rule34")

# Разнообразные наборы тегов — выбираем случайный каждый раз
TAG_SETS = [
    "animated",
    "3d_(artwork)",
    "animated 3d_(artwork)",
    "animated tagme",
    "3d_(artwork) tagme",
]

# Теги для ИИ-контента (AI generated)
# Примечание: generated_by_ai и ai_animation не работают на Rule34 - нет таких постов
AI_TAG_SETS = [
    # Базовые теги (для изображений)
    "stable_diffusion",
    "ai_generated",
    "novelai",
    
    # Анимированные теги (для видео) - используем рабочие теги
    "stable_diffusion animated",
    "ai_generated animated",
    "novelai animated",
    "ai animated",
]

# Теги для 3D контента (с исключением 2D)
THREE_D_TAG_SETS = [
    "3d_(artwork) rating:explicit -2d -hand_drawn -drawn",
    "3d_(artwork) video rating:explicit -2d",  # 3d_video не существует, используем 3d_(artwork) + video
    "3d_(artwork) animated rating:explicit -2d",
]

def fetch_rule34(tags: str = None, limit: int = 100, content_type: str = "mixed", media_type: str = "mixed") -> List[Dict[str, Any]]:
    """
    Парсинг Rule34 через API с авторизацией и пагинацией
    
    Args:
        tags: конкретные теги (если None, выбираются случайно)
        limit: количество постов
        content_type: "mixed", "3d", "ai" — тип контента
        media_type: "mixed", "video", "image" — тип медиа (70% video, 30% image)
    """
    
    # Выбор тегов на основе типа контента
    if tags is None:
        if content_type == "ai":
            # Для видео выбираем только теги с "animated", для изображений - без
            if media_type == "video":
                animated_tags = [t for t in AI_TAG_SETS if "animated" in t.lower()]
                tags = random.choice(animated_tags) if animated_tags else random.choice(AI_TAG_SETS)
            else:
                tags = random.choice(AI_TAG_SETS)
        elif content_type == "3d":
            tags = random.choice(THREE_D_TAG_SETS)
        else:
            tags = random.choice(TAG_SETS)
    
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
    max_pages = 10  # Ищем по 10 страницам
    min_posts = 50  # Минимум постов для выбора
    
    # Rule34 API: pid=0 — первая страница, pid=1 — вторая, и т.д.
    for page in range(0, max_pages):
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
            r = requests.get(url, params=params, headers=headers, timeout=30)
            r.raise_for_status()

            if not r.text.strip():
                logger.warning(f"Rule34 page {page}: empty response")
                continue

            posts = r.json()

            if not isinstance(posts, list):
                logger.warning(f"Rule34 page {page}: unexpected response format")
                continue

            logger.info(f"Rule34 page {page}: got {len(posts)} posts")

            for post in posts:
                if not isinstance(post, dict):
                    continue

                rating = post.get("rating", "")
                mapped_rating = "XXX" if rating == "e" else "X"

                file_url = post.get("file_url")
                if not file_url:
                    continue

                # Фильтруем по минимальному score (Rule34 score ниже чем CivitAI likes)
                score = int(post.get("score", 0))
                if score < RULE34_MIN_SCORE:
                    continue

                post_tags = post.get("tags", "").split()

                all_results.append({
                    "id":      f"r34_{post['id']}",
                    "url":     file_url,
                    "tags":    post_tags[:15],
                    "likes":   score,
                    "rating":  mapped_rating,
                    "post_id": post.get("id"),
                    "source":  "rule34"
                })

            # Если набрали достаточно постов — останавливаемся
            if len(all_results) >= min_posts:
                logger.info(f"Rule34: collected {len(all_results)} posts from {page} pages")
                break

        except Exception as e:
            logger.error(f"Rule34 page {page} error: {e}")
            continue

    logger.info(f"Rule34: Found {len(all_results)} total posts")
    return all_results
