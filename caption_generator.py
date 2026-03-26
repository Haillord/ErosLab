"""
Генератор описаний через Pollinations.ai (AI, без ключа)
"""

import requests
import logging
import random
import urllib.parse

logger = logging.getLogger(__name__)

def generate_caption(tags, rating, likes):
    """Генерирует описание через Pollinations.ai"""

    # Если нет тегов, сразу fallback
    if not tags:
        return fallback_caption(tags, rating, likes)

    tags_str = ", ".join(tags[:12])

    prompt = (
        f"Напиши короткое, горячее описание для NSFW поста на русском языке. "
        f"Теги: {tags_str}. Рейтинг: {rating}. Лайков: {likes}. "
        f"Требования: 1 предложение максимум, добавь эмодзи, "
        f"пиши в разговорном стиле, без кавычек, только текст ответа."
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
                and len(ai_text) > 5
            ):
                if len(ai_text) > 250:
                    ai_text = ai_text[:250] + "..."

                return _format_caption(ai_text, tags, rating, likes)

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
                and len(ai_text) > 5
            ):
                if len(ai_text) > 250:
                    ai_text = ai_text[:250] + "..."

                return _format_caption(ai_text, tags, rating, likes)

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