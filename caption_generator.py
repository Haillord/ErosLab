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

# Технические теги которые не несут смысла для текста
TECHNICAL_TAGS = {
    "3d", "3d_(artwork)", "3d_animation", "3d_model", "ai_generated",
    "tagme", "animated", "video", "gif", "source_filmmaker", "sfm",
    "blender", "koikatsu", "honey_select", "daz3d", "mmd",
    "high_quality", "best_quality", "masterpiece", "absurdres",
    "highres", "score_9", "score_8", "score_7", "rating_explicit",
    "stable_diffusion", "novelai", "midjourney", "lora"
}

def _safe_tags(tags):
    """Только для хэштегов — убираем NSFW и технические теги."""
    result = []
    for t in tags:
        t_lower = t.lower()
        if t_lower in NSFW_TRIGGER_TAGS:
            continue
        if t_lower in TECHNICAL_TAGS:
            continue
        # Убираем теги длиннее 3 слов (технические описания)
        if t_lower.count("_") > 2:
            continue
        # Убираем теги с цифрами
        if any(c.isdigit() for c in t_lower):
            continue
        result.append(t)
    return result

def _prompt_tags(tags):
    """Теги для промпта — фильтруем технический мусор, переводим в читаемый вид."""
    result = []
    for t in tags:
        t_lower = t.lower()
        if t_lower in TECHNICAL_TAGS:
            continue
        # Убираем теги длиннее 3 слов
        if t_lower.count("_") > 2:
            continue
        # Убираем теги с цифрами
        if any(c.isdigit() for c in t_lower):
            continue
        # Убираем скобки из тегов типа 3d_(artwork)
        clean = t.replace("_(artwork)", "").replace("_(character)", "")
        # Заменяем подчёркивания на пробелы для читаемости
        human = clean.replace("_", " ").strip()
        if human:
            result.append(human)
    return result[:8]


# ==================== ПЕРСОНА ====================

PERSONA = [
    "Ты дерзкая альтушка-анимешница, которая видела столько хентая что уже ничему не удивляется.",
    "Ты говоришь как девочка из аниме-тусовки — с сарказмом, лёгким матом и тёмным юмором.",
    "Ты циничная, немного грязная на язык, но с шармом. Иногда вырывается лёгкий мат.",
    "Ты провоцируешь читателя — дерзко, с намёком, иногда пошловато но со стилем.",
    "Ты как та самая альтушка из аниме-клуба которая знает всё но делает вид что ей похер.",
    "Холодная снаружи, огонь внутри. Иногда вырывается что-то такое что не сотрёшь из памяти.",
]


# ==================== ФОРМАТЫ ====================

FORMAT_TYPES = {
    "single": (
        "Напиши ОДНО короткое предложение (не длиннее 15 слов). Без пояснений, без кавычек."
    ),
    "double": (
        "Напиши ДВЕ короткие строки. Вторая переворачивает или продолжает смысл первой. "
        "Каждая строка — отдельная законченная мысль. Без кавычек."
    ),
    "single_question": (
        "Напиши ОДНО короткое провокационное предложение которое заканчивается вопросом. "
        "Без кавычек, не длиннее 15 слов."
    ),
}


# ==================== ПРОМПТ ====================

def _build_prompt(tags):
    """
    Промпт строится из очищенных читаемых тегов.
    NSFW-контекст передаётся через атмосферу, не через прямые слова.
    """
    if not tags:
        return None

    human_tags = _prompt_tags(tags)

    if not human_tags:
        # Если все теги технические — используем нейтральный промпт
        tags_str = "соблазн, страсть, интрига"
    else:
        tags_str = ", ".join(human_tags)

    persona_line = random.choice(PERSONA)
    format_key = random.choice(list(FORMAT_TYPES.keys()))
    format_instruction = FORMAT_TYPES[format_key]

    prompt = f"""Ты — дерзкая альтушка-анимешница, пишешь провокационные подписи для Telegram-канала.
Ты не просто описываешь — ты дразнишь, цепляешь и играешь с читателем.

Характер: {persona_line}

Поведение:
— обращаешься как будто лично к читателю
— иногда дразнишь, иногда будто позволяешь больше, чем стоит
— создаёшь ощущение "почти, но не до конца"
— текст должен вызывать желание досмотреть/пересмотреть

Правила:
— никогда не описывай внешность напрямую
— никаких упоминаний "арт", "картинка" и т.п.
— никакой технической лексики
— только живой человеческий язык
— лёгкий мат можно, но редко и точно в цель
— избегай прямого описания действий — лучше намёк

Стиль:
— короткие строки (1–2 предложения максимум)
— можно разбивать на 2–4 строки
— первая строка — крючок (должна цеплять сразу)
— последняя — добивающая/двусмысленная

Атмосфера: {tags_str}

Формат: {format_instruction}

Добавь 1–2 эмодзи, не больше. Только текст, без пояснений."""

    return prompt


# ==================== ВАЛИДАЦИЯ ====================

def trim_to_sentence(text, max_len=250):
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
        "не могу выполнить", "не могу ответить", "не могу сгенерировать",
        "как ИИ", "как языковая модель"
    ]
    return bool(text) and len(text) > 10 and not any(p in text for p in bad_phrases)


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
                "max_tokens": 120,
                "temperature": 0.95
            }),
            timeout=15
        )
        if response.status_code == 200:
            data = response.json()
            text = data["choices"][0]["message"]["content"].strip()
            if _is_valid_response(text):
                text = trim_to_sentence(text, max_len=250)
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
                text = trim_to_sentence(text, max_len=250)
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
                text = trim_to_sentence(text, max_len=250)
                logger.info("✅ Pollinations POST caption generated")
                return text
            else:
                logger.warning(f"Pollinations POST bad response: {text[:80]}")
    except requests.exceptions.Timeout:
        logger.warning("Pollinations POST timeout")
    except Exception as e:
        logger.error(f"Pollinations POST failed: {e}")
    return None


# ==================== FALLBACK ТЕКСТЫ ====================

FALLBACK_TEXTS = [
    "Некоторые вещи лучше видеть, чем описывать 🔥",
    "Слов не нужно 😏",
    "Просто смотри 👀",
    "Без комментариев. Почти 🌙",
    "Ты сам всё понимаешь 🖤",
]


# ==================== СБОРКА ====================

def _format_caption(ai_text, tags, footer):
    safe_tags = _safe_tags(tags)
    hashtags = " ".join(f"#{t}" for t in safe_tags[:6]) if safe_tags else ""
    if hashtags:
        return f"{ai_text}\n\n{hashtags}\n\n{footer}"
    return f"{ai_text}\n\n{footer}"

def fallback_caption(tags, footer):
    text = random.choice(FALLBACK_TEXTS)
    safe_tags = _safe_tags(tags)
    tags_line = " ".join(f"#{t}" for t in safe_tags[:6]) if safe_tags else ""
    if tags_line:
        return f"{text}\n\n{tags_line}\n\n{footer}"
    return f"{text}\n\n{footer}"

def generate_caption(tags, rating, likes, image_data=None, image_url=None,
                     watermark="📢 @eroslabai", suggestion="💬 Предложка: @Haillord"):
    footer = f"{watermark}\n{suggestion}"

    if not tags:
        return fallback_caption(tags, footer)

    prompt = _build_prompt(tags)
    if not prompt:
        return fallback_caption(tags, footer)

    text = _try_groq(prompt)
    if not text:
        text = _try_pollinations(prompt)

    if not text:
        return fallback_caption(tags, footer)

    return _format_caption(text, tags, footer)