import logging
import requests
from typing import List, Dict, Any

logger = logging.getLogger("ErosLab.Rule34")

def fetch_rule34(api_key: str, user_id: str, tags: str = "3d animated -low_res", limit: int = 100) -> List[Dict[str, Any]]:
    """
    Парсинг Rule34 с использованием API-ключа для надежности.
    """
    if not api_key or not user_id:
        logger.error("Rule34 API Key or User ID is missing!")
        return []

    url = "https://api.rule34.xxx/index.php"
    params = {
        "page": "dapi",
        "s": "post",
        "q": "index",
        "json": 1,
        "limit": limit,
        "tags": tags,
        "api_key": api_key,
        "id": user_id  # В API Rule34 параметр 'id' используется для User ID
    }
    
    try:
        # Используем таймаут, чтобы Actions не зависал
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        
        posts = r.json()
        # ЗАЩИТА: Если пришла строка или не список, выходим без ошибки
        if not isinstance(posts, list):
            # Эта строка покажет нам реальный текст ошибки от Rule34 (например, "Unauthorized")
            logger.error(f"Rule34 Error Response: {r.text[:200]}")
            return []
            
        results = []
        for post in posts:
            # Теперь .get() безопасен, так как мы знаем, что post внутри списка
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
            
        logger.info(f"Rule34: Found {len(results)} posts with API Auth")
        return results
    except Exception as e:
        logger.error(f"Rule34 API Error: {e}")
        return []