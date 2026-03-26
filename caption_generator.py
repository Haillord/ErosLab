"""
Генератор описаний: Groq Vision → Groq (текст) → Pollinations → fallback
Стиль: коротко, сухо, с думерским сарказмом, без лишнего.
"""

import requests
import logging
import random
import urllib.parse
import os
from vision_analyzer import VisionAnalyzer

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

vision = VisionAnalyzer(GROQ_API_KEY) if GROQ_API_KEY else None

NSFW_TRIGGER_TAGS = {
    "slut", "sex", "nude", "naked", "penis", "vagina", "cock",
    "pussy", "cum", "anal", "blowjob", "nsfw", "explicit", "porn",
    "hentai", "xxx", "nipple", "nipples", "breast", "breasts", "ass",
    "bondage", "bdsm", "fetish", "gangbang", "creampie", "ahegao",
    "spread_legs", "pussy_juice", "uncensored", "censored", "genitals"
}

# Шаблоны промптов в стиле Nyx (без упоминания личности, только манера)
PROMPT_TEMPLATES = [
    (
        "Коротко, сухо, с думерским сарказмом. Одно предложение. Без восклицаний. "
        "Эмодзи только если действительно к месту. Вдохновение: {tags}."
    ),
    (
        "Опиши это изображение в манере: коротко, наблюдательно, иногда странно, "
        "без лишних эмоций. Одно-два предложения. Слова: {tags}."
    ),
    (
        "Спокойно, с тихой иронией. Одно предложение. Никаких объяснений. "
        "Настроение: {tags}."
    ),
]

def _safe_tags(tags):
    return [t for t in tags if t.lower() not in NSFW_TRIGGER_TAGS]

def _is_valid_response(text):
    bad_phrases = ["I'm sorry", "I can't", "I cannot", "<!DOCTYPE", "<html", "As an AI"]
    return bool(text) and len(text) > 5 and not any(p in text for p in bad_phrases)

def _build_prompt(tags):
    safe = _safe_tags(tags)
    if not safe:
        return None
    tags_str = ", ".join(safe[:8])
    return random.choice(PROMPT_TEMPLATES).format(tags=tags_str)

def _format_caption(ai_text, tags, footer):
    hashtags = " ".join(f"#{t}" for t in tags[:8]) if tags else ""
    return f"{ai_text}\n\n{hashtags}\n\n{footer}"

def _try_groq(prompt):
    if not GROQ_API_KEY:
        logger.info("No GROQ_API_KEY, skipping Groq")
        return None
    try:
        import json
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            data=json.dumps({
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 70,               # короче, чтобы описания были краткими
                "temperature": 0.6              # немного ниже для стабильности
            }),
            timeout=15
        )
        if response.status_code == 200:
            data = response.json()
            text = data["choices"][0]["message"]["content"].strip()
            if _is_valid_response(text):
                if len(text) > 200:
                    text = text[:200] + "..."
                logger.info("✅ Groq caption generated")
                return text
            else:
                logger.warning(f"Groq bad response: {text[:80]}")
        else:
            logger.warning(f"Groq status {response.status_code}")
    except Exception as e:
        logger.error(f"Groq error: {e}")
    return None

def _try_pollinations(prompt):
    try:
        encoded = urllib.parse.quote(prompt)
        response = requests.get(f"https://text.pollinations.ai/{encoded}", timeout=20)
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
            json={"messages": [{"role": "user", "content": prompt}], "model": "openai", "private": True},
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

def fallback_caption(tags, footer):
    tags_line = " ".join(f"#{t}" for t in tags[:8]) if tags else ""
    return f"{tags_line}\n\n{footer}"

def generate_caption(tags, rating, likes, image_data=None, image_url=None,
                     watermark="📢 @eroslabai", suggestion="💬 Предложка: @Haillord"):
    footer = f"{watermark}\n{suggestion}"

    # Vision только если тегов мало и это картинка
    use_vision = (
        image_data is not None and image_url
        and not image_url.lower().endswith((".mp4", ".webm", ".gif"))
        and len(tags) < 3 and vision is not None
    )
    if use_vision:
        logger.info(f"Tags count: {len(tags)}, trying Groq Vision...")
        vision_text = vision.analyze(image_data, language="ru")
        if vision_text:
            hashtags = " ".join(f"#{t}" for t in tags[:8]) if tags else ""
            return f"👁️ {vision_text}\n\n{hashtags}\n\n{footer}"
        else:
            logger.info("Vision failed, falling back to text generation")

    # Если тегов нет — нейтральный промпт (тоже в стиле)
    if not tags:
        prompt = "Коротко, сухо, одно предложение. Просто настроение. Без эмодзи."
        text = _try_groq(prompt)
        if not text:
            text = _try_pollinations(prompt)
        if text:
            return f"{text}\n\n{footer}"
        else:
            return fallback_caption(tags, footer)

    # Если теги есть
    prompt = _build_prompt(tags)
    if not prompt:
        return fallback_caption(tags, footer)

    text = _try_groq(prompt)
    if not text:
        text = _try_pollinations(prompt)

    if not text:
        return fallback_caption(tags, footer)

    return _format_caption(text, tags, footer)