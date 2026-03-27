import logging
import requests
from typing import List, Dict, Any

logger = logging.getLogger("ErosLab.Rule34")

def fetch_rule34(tags: str = "3d animated", limit: int = 100) -> List[Dict[str, Any]]:
    """
    Парсинг Rule34 через публичный API (авторизация не требуется).
    """
    url = "https://api.rule34.xxx/index.php"
    params = {
        "page": "dapi",
        "s": "post",
        "q": "index",
        "json": 1,
        "limit": limit,
        "tags": tags,
    }

    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()

        logger.info(f"Rule34 status: {r.status_code}")
        logger.info(f"Rule34 Content-Type: {r.headers.get('Content-Type')}")

        posts = r.json()

        if not isinstance(posts, list):
            logger.error(f"Rule34 unexpected response: {r.text[:200]}")
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