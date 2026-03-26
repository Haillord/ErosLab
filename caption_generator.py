"""
Генератор описаний: Groq → Pollinations → fallback
Стиль: циничная, провокационная, с характером. Без описания внешности напрямую.
"""

import requests
import logging
import random
import urllib.parse
import os

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")


# ==================== ФИЛЬТРЫ ====================

NSFW_TRIGGER_TAGS = {
    "slut", "sex", "nude", "naked", "penis", "vagina", "cock",
    "pussy", "cum", "anal", "blowjob", "nsfw", "explicit", "porn",
    "hentai", "xxx", "nipple", "nipples", "breast", "breasts", "ass",
    "bondage", "bdsm", "fetish", "gangbang", "creampie", "ahegao",
    "spread_legs", "pussy_juice", "uncensored", "censored", "genitals"
}

def _safe_tags(tags):
    """Только для хэштегов — убираем NSFW-теги."""
    return [t for t in tags if t.lower() not in NSFW_TRIGGER_TAGS]


# ==================== ПЕРСОНА ====================

PERSONA = [
    "Ты говоришь так, будто уже всё видела и тебе слегка скучно.",
    "Ты слегка издеваешься над читателем, но не грубо.",
    "Ты не просишь — ты провоцируешь.",
    "Иногда холодная, иногда игривая — читатель никогда не знает, чего ждать.",
]


# ==================== ФОРМАТЫ ====================

FORMAT_TYPES = {
    "single": (
        "Напиши ОДНО короткое предложение. Без пояснений, без кавычек."
    ),
    "double": (
        "Напиши ДВЕ короткие строки. Вторая — продолжает или переворачивает смысл первой. "
        "Каждая строка — отдельная мысль. Без кавычек."
    ),
    "dialog": (
        "Напиши короткий диалог из двух реплик. Формат:\n"
        "— реплика 1\n"
        "— реплика 2\n"
        "Создай интригу или напряжение между репликами."
    ),
}


# ==================== ENGAGEMENT ====================

ENGAGEMENT_LINES = [
    "И что дальше? 😈",
    "Оценка? 1–10",
    "Ты бы остановился?",
    "Слабовато или норм?",
    "Продолжение хочешь?",
    "Угадай, что будет дальше 👀",
    "Молчишь — значит зацепило 😏",
]

def maybe_add_engagement(text):
    """С вероятностью 20% добавляем крючок в конце."""
    if random.random() < 0.20:
        return text + "\n\n" + random.choice(ENGAGEMENT_LINES)
    return text


# ==================== ПРОМПТ ====================

def _build_prompt(tags):
    """
    Промпт строится из ПОЛНЫХ тегов (включая NSFW) — чтобы AI понимал контекст.
    Чистые теги идут только в хэштеги, не сюда.
    """
    if not tags:
        return None

    prompt_tags = tags[:10]  # полные, грязные — AI должен понимать атмосферу
    tags_str = ", ".join(prompt_tags)

    persona_line = random.choice(PERSONA)
    format_key = random.choice(list(FORMAT_TYPES.keys()))
    format_instruction = FORMAT_TYPES[format_key]

    prompt = f"""Ты — дерзкая, уверенная, слегка циничная девушка. Пишешь подписи к откровенным аниме-артам.

Характер: {persona_line}

Стиль:
— провокация и намёк, без описания внешности напрямую
— уверенность, иногда холодность
— сексуальное напряжение без грубости

Настроение задают слова: {tags_str}

Формат ответа: {format_instruction}

Добавь 1–3 эмодзи по смыслу. Только текст ответа, без пояснений."""

    return prompt


# ==================== ВАЛИДАЦИЯ ====================

def trim_to_sentence(text, max_len=300):
    if len(text) <= max_len:
        return text
    truncated = text[:max_len]
    last_punct = max(truncated.rfind('.'), truncated.rfind('!'), truncated.rfind('?'))
    if last_punct > max_len * 0.7:
        return truncated[:last_punct + 1]
    last_space = truncated.rfind(' ')
    if last_space > max_len * 0.7:
        return truncated[:last_space] + '...'
    return truncated + '...'

def _is_valid_response(text):
    bad_phrases = [
        "I'm sorry", "I can't", "I cannot", "<!DOCTYPE", "<html", "As an AI",
        "Не могу выполнить этот запрос", "Извините, я не могу", "Я не могу",
        "не могу выполнить", "не могу ответить", "не могу сгенерировать"
    ]
    return bool(text) and len(text) > 5 and not any(p in text for p in bad_phrases)


# ==================== ПРОВАЙДЕРЫ ====================

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
                "max_tokens": 150,
                "temperature": 0.92
            }),
            timeout=15
        )
        if response.status_code == 200:
            data = response.json()
            text = data["choices"][0]["message"]["content"].strip()
            if _is_valid_response(text):
                text = trim_to_sentence(text, max_len=300)
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
                text = trim_to_sentence(text, max_len=300)
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
                text = trim_to_sentence(text, max_len=300)
                logger.info("✅ Pollinations POST caption generated")
                return text
            else:
                logger.warning(f"Pollinations POST bad response: {text[:80]}")
    except requests.exceptions.Timeout:
        logger.warning("Pollinations POST timeout")
    except Exception as e:
        logger.error(f"Pollinations POST failed: {e}")
    return None


# ==================== СБОРКА ====================

def _format_caption(ai_text, tags, footer):
    safe_tags = _safe_tags(tags)
    hashtags = " ".join(f"#{t}" for t in safe_tags[:8]) if safe_tags else ""
    return f"{ai_text}\n\n{hashtags}\n\n{footer}"

def fallback_caption(tags, footer):
    safe_tags = _safe_tags(tags)
    tags_line = " ".join(f"#{t}" for t in safe_tags[:8]) if safe_tags else ""
    return f"{tags_line}\n\n{footer}"

def generate_caption(tags, rating, likes, image_data=None, image_url=None,
                     watermark="📢 @eroslabai", suggestion="💬 Предложка: @Haillord"):
    footer = f"{watermark}\n{suggestion}"

    if not tags:
        return fallback_caption(tags, footer)

    # Разделяем теги:
    # raw_tags — полные, грязные (для контекста AI)
    # safe_tags — чистые (только для хэштегов)
    raw_tags = tags  # сохраняем оригинальные, без фильтрации
    safe_tags = _safe_tags(tags)  # чистим только для хэштегов

    # Промпт строится из ПОЛНЫХ тегов — AI должен понимать контекст
    prompt = _build_prompt(raw_tags)
    if not prompt:
        return fallback_caption(raw_tags, footer)

    text = _try_groq(prompt)
    if not text:
        text = _try_pollinations(prompt)

    if not text:
        return fallback_caption(raw_tags, footer)

    # Добавляем engagement-крючок с вероятностью 20%
    text = maybe_add_engagement(text)

    # В caption идут чистые теги (хэштеги)
    return _format_caption(text, safe_tags, footer)