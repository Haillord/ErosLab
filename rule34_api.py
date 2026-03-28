import os
import requests
import logging
from typing import List, Dict, Any

# Получаем данные из секретов GitHub (или ENV сервера)
R34_USER_ID = os.getenv("R34_USER_ID")
R34_API_KEY = os.getenv("R34_API_KEY")

logger = logging.getLogger("ErosLab.Rule34")

def fetch_rule34(tags: str = "3d animated", limit: int = 100) -> List[Dict[str, Any]]:
    """Парсинг Rule34 через API с авторизацией"""
    
    # Проверка, что секреты загружены
    if not R34_USER_ID or not R34_API_KEY:
        logger.error("API credentials are missing in environment variables!")
        return []

    url = "https://api.rule34.xxx"
    params = {
        "page": "dapi",
        "s": "post",
        "q": "index",
        "json": 1,  # JSON формат
        "limit": limit,
        "tags": tags,
        "user_id": R34_USER_ID,
        "api_key": R34_API_KEY
    }

    headers = {"User-Agent": "ErosLabBot/1.0 (Windows NT 10.0; Win64; x64)"}

    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
        r.raise_for_status()

        # Проверка на пустой ответ
        if not r.text.strip():
            logger.warning("Rule34 returned empty response")
            return []

        posts = r.json()

        # Проверка формата ответа
        if not isinstance(posts, list):
            logger.error(f"Rule34 unexpected response format: {type(posts)}")
            return []

        results = []
        for post in posts:
            if not isinstance(post, dict) or post.get("rating") not in ["e", "q"]:
                continue

            post_tags = post.get("tags", "").split()

            results.append({
                "id":      f"r34_{post['id']}",
                "url":     post.get("file_url"),
                "tags":    post_tags[:15],
                "likes":   int(post.get("score", 0)),
                "rating":  "XXX" if post.get("rating") == "e" else "X",
                "post_id": post.get("id"),
                "source":  "rule34"
            })

        logger.info(f"Rule34: Found {len(results)} posts")
        return results

    except Exception as e:
        logger.error(f"Rule34 API Error: {e}")
        return []