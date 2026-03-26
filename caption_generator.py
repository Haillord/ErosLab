"""
Генератор описаний через Pollinations.ai (AI, без ключа)
"""

import requests
import logging
import random
import urllib.parse

logger = logging.getLogger(__name__)

# Теги, которые триггерят отказ у Pollinations — скрываем из промпта
NSFW_TRIGGER_TAGS = {
    "slut", "sex", "nude", "naked", "penis", "vagina", "cock",
    "pussy", "cum", "anal", "blowjob", "nsfw", "explicit", "porn",
    "hentai", "xxx", "nipple", "nipples", "breast", "breasts", "ass",
    "bondage", "bdsm", "fetish", "gangbang", "creampie", "ahegao",
    "spread_legs", "pussy_juice", "uncensored", "censored", "genitals"
}

def generate_caption(tags, rating, likes):
    """Генерирует описание через Pollinations.ai"""

    # Если нет тегов, сразу fallback
    if not tags:
        return fallback_caption(tags, rating, likes)

    # Фильтруем теги для промпта — AI их не увидит, но в пост они пойдут
    safe_tags = [t for t in tags if t.lower() not in NSFW_TRIGGER_TAGS]

    if not safe_tags:
        logger.info("No safe tags for AI, using fallback")
        return fallback_caption(tags, rating, likes)

    tags_str = ", ".join(safe_tags[:8])

    prompt = (
        f"Напиши короткое соблазнительное описание для поста на русском языке. "
        f"Стиль и настроение: {tags_str}. "
        f"Требования: 1 предложение максимум, добавь эмодзи, "
        f"разговорный стиль, без кавычек, только текст ответа."
    )

    # Метод 1: GET-запрос (самый стабильный у Pollinations)
    try:
        encoded = urllib.parse.quote(prompt)
        response = requests.get(
            f"https://text.pollinations.ai/{encoded}",
            timeout=30
        )

        if response.status_code == 200:
            ai_text = response.text.strip()

            if (
                ai_text
                and "<!DOCTYPE" not in ai_text
                and "<html" not in ai_text
                and "I'm sorry" not in ai_text
                and "I can't" not in ai_text
                and "I cannot" not in ai_text
                and len(ai_text) > 5
            ):
                if len(ai_text) > 250:
                    ai_text = ai_text[:250] + "..."

                logger.info("AI caption generated successfully (GET)")
                return _format_caption(ai_text, tags, rating, likes)
            else:
                logger.warning(f"AI refused or returned bad response: {ai_text[:80]}")

    except requests.exceptions.Timeout:
        logger.warning("GET timeout, trying POST...")
    except Exception as e:
        logger.warning(f"GET failed: {e}, trying POST...")

    # Метод 2: POST с messages (OpenAI-совместимый формат)
    try:
        response = requests.post(
            "https://text.pollinations.ai/",
            json={
                "messages": [{"role": "user", "content": prompt}],
                "model": "openai",
                "private": True
            },
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        if response.status_code == 200:
            ai_text = response.text.strip()

            if (
                ai_text
                and "<!DOCTYPE" not in ai_text
                and "<html" not in ai_text
                and "I'm sorry" not in ai_text
                and "I can't" not in ai_text
                and "I cannot" not in ai_text
                and len(ai_text) > 5
            ):
                if len(ai_text) > 250:
                    ai_text = ai_text[:250] + "..."

                logger.info("AI caption generated successfully (POST)")
                return _format_caption(ai_text, tags, rating, likes)
            else:
                logger.warning(f"AI refused or returned bad response: {ai_text[:80]}")

    except requests.exceptions.Timeout:
        logger.warning("POST timeout, using fallback")
    except Exception as e:
        logger.error(f"POST failed: {e}")

    return fallback_caption(tags, rating, likes)


def _format_caption(ai_text, tags, rating, likes):
    """Форматирует финальный текст поста"""
    hashtags = " ".join(f"#{t}" for t in tags[:8])
    return (
        f"{ai_text}\n\n"
        f"⭐ **Рейтинг:** {rating} | ❤️ **Лайков:** {likes}\n\n"
        f"{hashtags}\n\n"
        f"📢 @eroslabai"
    )


def fallback_caption(tags, rating, likes):
    """Запасной вариант на случай ошибки AI"""
    tags_line = " ".join(f"#{t}" for t in tags[:8]) if tags else ""

    phrases = [
        "🔥 Горячий кадр для твоей ленты",
        "💖 Нежный образ с оттенком игривости",
        "🍑 Образ, который заставляет улыбнуться",
        "✨ Эстетика и соблазн в одном кадре",
        "💋 Когда искусство встречается с откровенностью",
        "🌟 Настроение поднимает этот пост",
        "🎀 Соблазнительный образ для настоящих ценителей",
        "🖤 Тот самый контент, ради которого ты здесь",
        "🌸 Откровенно и красиво — как ты любишь",
    ]

    return (
        f"{random.choice(phrases)}\n\n"
        f"⭐ **Рейтинг:** {rating} | ❤️ **Лайков:** {likes}\n\n"
        f"{tags_line}\n\n"
        f"📢 @eroslabai"
    )