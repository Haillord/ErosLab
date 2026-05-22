import re
from typing import Any


def normalize_tag(tag: str) -> str:
    return str(tag).strip().lower().replace(" ", "_").replace("-", "_")


def clean_tags(tags, hashtag_stop_words: set[str]):
    clean = []
    seen = set()
    for t in tags:
        t = re.sub(r"[^\w]", "", normalize_tag(t))
        if re.search(r"\d+$", t):
            continue
        if t and t not in hashtag_stop_words and t not in seen and 3 <= len(t) <= 30:
            clean.append(t)
            seen.add(t)
    return clean


def extract_tags_from_item(
    item: dict[str, Any],
    hashtag_stop_words: set[str],
    logger=None,
    debug_logs: bool = False,
):
    raw_tags = []

    civitai_tags = item.get("tags", [])
    if civitai_tags:
        for t in civitai_tags:
            name = t.get("name", "") if isinstance(t, dict) else str(t)
            if name:
                raw_tags.append(name)
        if logger and debug_logs:
            logger.debug(f"CivitAI tags found: {len(raw_tags)}")

    if not raw_tags:
        prompt = item.get("meta", {}).get("prompt", "") if item.get("meta") else ""
        if prompt:
            tokens = re.split(r"[,\(\)\[\]|<>]+", prompt)
            for token in tokens:
                token = token.strip()
                if token:
                    raw_tags.append(token)
            if logger and debug_logs:
                logger.debug(f"Parsed {len(raw_tags)} tokens from meta.prompt")
        else:
            if logger and debug_logs:
                logger.debug("No tags and no prompt available")

    return clean_tags(raw_tags, hashtag_stop_words)


def to_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def extract_civitai_likes(item: dict[str, Any]) -> int:
    """
    Извлекает количество реакций (лайков) из элемента CivitAI API.
    
    Приоритет 1: stats от API — likeCount + heartCount + laughCount.
    Приоритет 2: fallback на верхний уровень (старый формат API).
    
    Возвращает 0 если данные недоступны.
    """
    if not isinstance(item, dict):
        return 0

    # Приоритет 1: stats от API
    stats = item.get("stats")
    if isinstance(stats, dict):
        total = (
            to_int(stats.get("likeCount"), 0) +
            to_int(stats.get("heartCount"), 0) +
            to_int(stats.get("laughCount"), 0)
        )
        if total > 0:
            return total

    # Приоритет 2: fallback на верхний уровень (старый формат)
    return (
        to_int(item.get("likeCount"), 0) or
        to_int(item.get("heartCount"), 0)
    )