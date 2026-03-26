"""
Генератор описаний через Pollinations.ai (AI, без ключа)
"""

import requests
import logging
import random

logger = logging.getLogger(__name__)

def generate_caption(tags, rating, likes):
    """Генерирует описание через Pollinations.ai"""
    
    # Если нет тегов, сразу fallback
    if not tags:
        return fallback_caption(tags, rating, likes)
    
    tags_str = ", ".join(tags[:12])
    
    prompt = f"""Напиши короткое, горячее описание для NSFW поста на русском языке.
Теги: {tags_str}
Рейтинг: {rating}
Лайков: {likes}
Требования:
- 1 предложение максимум
- Добавь эмодзи
- Пиши в разговорном стиле
- Без кавычек
- Только текст ответа
"""
    
    try:
        # POST запрос (вместо GET) — может быть стабильнее
        response = requests.post(
            "https://text.pollinations.ai/",
            json={"prompt": prompt},
            timeout=30
        )
        
        if response.status_code == 200:
            ai_text = response.text.strip()
            
            if ai_text and "<!DOCTYPE" not in ai_text and "<html" not in ai_text and len(ai_text) > 5:
                if len(ai_text) > 250:
                    ai_text = ai_text[:250] + "..."
                
                return f"""{ai_text}

⭐ **Рейтинг:** {rating} | ❤️ **Лайков:** {likes}

{" ".join(f"#{t}" for t in tags[:8])}

📢 @eroslabai"""
        
        return fallback_caption(tags, rating, likes)
            
    except requests.exceptions.Timeout:
        logger.warning("AI request timeout, using fallback")
        return fallback_caption(tags, rating, likes)
    except Exception as e:
        logger.error(f"AI error: {e}")
        return fallback_caption(tags, rating, likes)

def fallback_caption(tags, rating, likes):
    """Запасной вариант на случай ошибки"""
    tags_line = " ".join(f"#{t}" for t in tags[:8]) if tags else ""
    
    # Более разнообразные фразы
    phrases = [
        "🔥 Горячий кадр для твоей ленты",
        "💖 Нежный образ с оттенком игривости",
        "🍑 Задний план, который заставляет улыбнуться",
        "✨ Эстетика и соблазн в одном кадре",
        "💋 Когда искусство встречается с откровенностью",
        "🌟 Настроение поднимает этот пост",
        "🎀 Соблазнительный образ для настоящих ценителей"
    ]
    
    return f"""{random.choice(phrases)}

⭐ **Рейтинг:** {rating} | ❤️ **Лайков:** {likes}

{tags_line}

📢 @eroslabai"""