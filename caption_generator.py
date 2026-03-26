"""
Генератор описаний: Groq Vision → Groq (текст) → Pollinations → fallback
"""

import requests
import logging
import random
import urllib.parse
import os
from vision_analyzer import VisionAnalyzer

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# Инициализируем Vision анализатор
vision = VisionAnalyzer(GROQ_API_KEY) if GROQ_API_KEY else None

# Теги, которые триггерят отказ у AI — скрываем из промпта, но в пост идут все
NSFW_TRIGGER_TAGS = {
    "slut", "sex", "nude", "naked", "penis", "vagina", "cock",
    "pussy", "cum", "anal", "blowjob", "nsfw", "explicit", "porn",
    "hentai", "xxx", "nipple", "nipples", "breast", "breasts", "ass",
    "bondage", "bdsm", "fetish", "gangbang", "creampie", "ahegao",
    "spread_legs", "pussy_juice", "uncensored", "censored", "genitals"
}

# Шаблоны промптов — чередуем для разнообразия
PROMPT_TEMPLATES = [
    (
        "Ты автор горячего телеграм-канала. Напиши одно короткое соблазнительное "
        "предложение на русском языке для поста с аниме-артом. "
        "Не описывай внешность буквально. Передай настроение, желание, атмосферу. "
        "Вдохновение: {tags}. Добавь 1-2 эмодзи. Только текст, без кавычек."
    ),
    (
        "Придумай одну короткую дерзкую подпись на русском для аниме-поста в телеграме. "
        "Стиль: игривый, соблазнительный, с характером. "
        "Атмосфера: {tags}. Добавь эмодзи. Только текст ответа."
    ),
    (
        "Напиши одно предложение на русском — короткое, чувственное, с интригой. "
        "Как будто описываешь момент, от которого перехватывает дыхание. "
        "Настроение задают слова: {tags}. Добавь эмодзи. Без кавычек."
    ),
]


def _safe_tags(tags):
    """Убирает теги, которые триггерят отказ AI"""
    return [t for t in tags if t.lower() not in NSFW_TRIGGER_TAGS]


def _is_valid_response(text):
    """Проверяет что AI не отказал и вернул нормальный текст"""
    bad_phrases = ["I'm sorry", "I can't", "I cannot", "<!DOCTYPE", "<html", "As an AI"]
    return (
        bool(text)
        and len(text) > 5
        and not any(p in text for p in bad_phrases)
    )


def _build_prompt(tags):
    """Собирает промпт из безопасных тегов"""
    safe = _safe_tags(tags)
    if not safe:
        return None
    tags_str = ", ".join(safe[:8])
    return random.choice(PROMPT_TEMPLATES).format(tags=tags_str)


def _format_caption(ai_text, tags):
    """Форматирует финальный текст поста"""
    hashtags = " ".join(f"#{t}" for t in tags[:8]) if tags else ""
    return (
        f"{ai_text}\n\n"
        f"{hashtags}\n\n"
        f"📢 @eroslabai"
    )


def _try_groq(prompt):
    """Запрос к Groq API — быстро и надёжно"""
    if not GROQ_API_KEY:
        logger.info("No GROQ_API_KEY, skipping Groq")
        return None

    try:
        import json
        
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            data=json.dumps({
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 100,
                "temperature": 0.9
            }),
            timeout=15
        )

        if response.status_code == 200:
            data = response.json()
            text = data["choices"][0]["message"]["content"].strip()
            if _is_valid_response(text):
                if len(text) > 250:
                    text = text[:250] + "..."
                logger.info("✅ Groq caption generated")
                return text
            else:
                logger.warning(f"Groq bad response: {text[:80]}")

        else:
            logger.warning(f"Groq status {response.status_code}: {response.text[:100]}")

    except requests.exceptions.Timeout:
        logger.warning("Groq timeout")
    except Exception as e:
        logger.error(f"Groq error: {e}")

    return None


def _try_pollinations(prompt):
    """Запрос к Pollinations — бесплатный fallback"""
    try:
        encoded = urllib.parse.quote(prompt)
        response = requests.get(
            f"https://text.pollinations.ai/{encoded}",
            timeout=20
        )
        if response.status_code == 200:
            text = response.text.strip()
            if _is_valid_response(text):
                if len(text) > 250:
                    text = text[:250] + "..."
                logger.info("✅ Pollinations GET caption generated")
                return text
            else:
                logger.warning(f"Pollinations GET bad response: {text[:80]}")
    except requests.exceptions.Timeout:
        logger.warning("Pollinations GET timeout, trying POST...")
    except Exception as e:
        logger.warning(f"Pollinations GET failed: {e}")

    try:
        response = requests.post(
            "https://text.pollinations.ai/",
            json={
                "messages": [{"role": "user", "content": prompt}],
                "model": "openai",
                "private": True
            },
            headers={"Content-Type": "application/json"},
            timeout=20
        )
        if response.status_code == 200:
            text = response.text.strip()
            if _is_valid_response(text):
                if len(text) > 250:
                    text = text[:250] + "..."
                logger.info("✅ Pollinations POST caption generated")
                return text
            else:
                logger.warning(f"Pollinations POST bad response: {text[:80]}")
    except requests.exceptions.Timeout:
        logger.warning("Pollinations POST timeout")
    except Exception as e:
        logger.error(f"Pollinations POST failed: {e}")

    return None


def generate_caption(tags, rating, likes, image_data=None, image_url=None):
    """
    Генерирует описание:
      1. Если есть image_data и тегов мало (<3) и это картинка — пробуем Groq Vision
      2. Если теги есть — Groq/Pollinations с тегами
      3. Если тегов нет — нейтральное описание через AI
    """
    
    # ========== VISION: если тегов мало и это изображение ==========
    use_vision = (
        image_data is not None 
        and image_url 
        and not image_url.lower().endswith((".mp4", ".webm", ".gif"))
        and len(tags) < 3  # тегов мало или нет
        and vision is not None
    )
    
    if use_vision:
        logger.info(f"Tags count: {len(tags)}, trying Groq Vision...")
        vision_text = vision.analyze(image_data, language="ru")
        if vision_text:
            hashtags = " ".join(f"#{t}" for t in tags[:8]) if tags else ""
            return (
                f"👁️ {vision_text}\n\n"
                f"{hashtags}\n\n"
                f"📢 @eroslabai"
            )
        else:
            logger.info("Vision failed, falling back to text generation")
    
    # ========== ТЕКСТОВАЯ ГЕНЕРАЦИЯ ==========
    
    # Если тегов нет — используем нейтральный промпт
    if not tags:
        prompt = (
            "Напиши одно короткое атмосферное предложение на русском языке "
            "для поста с красивым изображением. Никаких тегов, просто настроение. "
            "Добавь 1-2 эмодзи. Без кавычек."
        )
        
        text = _try_groq(prompt)
        if not text:
            text = _try_pollinations(prompt)
        
        if text:
            return f"{text}\n\n📢 @eroslabai"
        else:
            return fallback_caption(tags)

    # Если теги есть — используем текущую логику
    prompt = _build_prompt(tags)
    if not prompt:
        logger.info("No safe tags for AI, using fallback")
        return fallback_caption(tags)

    text = _try_groq(prompt)
    if not text:
        logger.info("Groq failed, trying Pollinations...")
        text = _try_pollinations(prompt)

    if not text:
        logger.info("All AI failed, using fallback")
        return fallback_caption(tags)

    return _format_caption(text, tags)


def fallback_caption(tags):
    """Запасной вариант — только теги и водяной знак"""
    tags_line = " ".join(f"#{t}" for t in tags[:8]) if tags else ""
    return f"{tags_line}\n\n📢 @eroslabai"