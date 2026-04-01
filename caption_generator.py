"""
Caption generator: hashtags + technical block + footer.
Supports optional AI-enhanced copy with safe fallback.
"""

import logging
import math
import os
from datetime import datetime

import requests

logger = logging.getLogger(__name__)


# ==================== FILTERS ====================

NSFW_TRIGGER_TAGS = {
    "slut", "sex", "nude", "naked", "penis", "vagina", "cock",
    "pussy", "cum", "anal", "blowjob", "nsfw", "explicit", "porn",
    "hentai", "xxx", "nipple", "nipples", "breast", "breasts", "ass",
    "bondage", "bdsm", "fetish", "gangbang", "creampie", "ahegao",
    "spread_legs", "pussy_juice", "uncensored", "censored", "genitals", "d0gg1e"
}

TECHNICAL_TAGS = {
    "3d", "3d_(artwork)", "3d_animation", "3d_model", "ai_generated",
    "tagme", "animated", "video", "gif", "source_filmmaker", "sfm",
    "blender", "koikatsu", "honey_select", "daz3d", "mmd",
    "high_quality", "best_quality", "masterpiece", "absurdres",
    "highres", "score_9", "score_8", "score_7", "rating_explicit",
    "stable_diffusion", "novelai", "midjourney", "lora"
}

MAX_HASHTAGS = 6

ENABLE_AI_CAPTION = os.environ.get("ENABLE_AI_CAPTION", "false").lower() in ("1", "true", "yes", "on")
AI_DRY_RUN = os.environ.get("AI_DRY_RUN", "false").lower() in ("1", "true", "yes", "on")
AI_PROVIDER = os.environ.get("AI_PROVIDER", "auto").strip().lower()
AI_TIMEOUT_SEC = int(os.environ.get("AI_TIMEOUT_SEC", "12"))
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
ENABLE_STYLE_BLOCK = os.environ.get("ENABLE_STYLE_BLOCK", "true").lower() in ("1", "true", "yes", "on")
STYLE_BLOCK_MAX_ITEMS = int(os.environ.get("STYLE_BLOCK_MAX_ITEMS", "3"))

CRINGE_TAG_HINTS = {
    "dynamic", "moments", "details", "fidelity", "thrust", "shaking",
    "jiggle", "ultra", "cinematic", "masterpiece", "quality"
}

STYLE_TAG_STOP = {
    "solo", "woman", "girl", "female", "image", "video", "clip",
    "high", "quality", "detail", "best", "art", "ai", "3d"
}


def _safe_tags(tags):
    """Only for hashtags: remove NSFW and technical tags."""
    result = []
    for t in tags:
        t_lower = str(t).lower()
        if t_lower in NSFW_TRIGGER_TAGS:
            continue
        if t_lower in TECHNICAL_TAGS:
            continue
        if t_lower.count("_") > 2:
            continue
        if any(c.isdigit() for c in t_lower):
            continue
        result.append(str(t))
    return result


def _clean_caption_tags(tags):
    """Extra cleanup for caption readability."""
    result = []
    seen = set()
    for t in tags:
        t = str(t).strip().lower()
        if not t or t in seen:
            continue
        if len(t) > 22:
            continue
        if t.count("_") > 2:
            continue
        parts = [p for p in t.split("_") if p]
        if any(part in CRINGE_TAG_HINTS for part in parts):
            continue
        result.append(t)
        seen.add(t)
    return result


def _humanize_tag(tag):
    text = str(tag).replace("_", " ").strip()
    if not text:
        return ""
    return text[0].upper() + text[1:]


def _build_style_block(tags):
    if not ENABLE_STYLE_BLOCK:
        return ""

    picked = []
    seen = set()
    for tag in tags:
        low = str(tag).lower()
        if low in STYLE_TAG_STOP:
            continue
        if len(low) < 4 or len(low) > 24:
            continue
        if low.count("_") > 2:
            continue
        words = [w for w in low.split("_") if w]
        if any(w in STYLE_TAG_STOP for w in words):
            continue
        if low in seen:
            continue
        seen.add(low)
        picked.append(_humanize_tag(low))
        if len(picked) >= max(1, STYLE_BLOCK_MAX_ITEMS):
            break

    if not picked:
        return ""

    bullet_lines = "\n".join(f"• {_escape_html(item)}" for item in picked)
    return f"Что внутри:\n<blockquote>{bullet_lines}</blockquote>"


def _format_file_size(size_bytes):
    """Formats file size in readable form."""
    if size_bytes is None or size_bytes <= 0:
        return None
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def _format_resolution(width, height):
    """Formats resolution and aspect ratio."""
    if width is None or height is None or width <= 0 or height <= 0:
        return None, None

    resolution = f"{width}×{height}"

    gcd = math.gcd(width, height)
    ratio_w = width // gcd
    ratio_h = height // gcd
    aspect_ratio = f"{ratio_w}:{ratio_h}"

    return resolution, aspect_ratio


def _format_date(date_value):
    """Formats date to dd.mm.yyyy."""
    if date_value is None:
        return None

    if isinstance(date_value, datetime):
        return date_value.strftime("%d.%m.%Y")

    if isinstance(date_value, str):
        for fmt in ["%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d", "%m/%d/%Y"]:
            try:
                dt = datetime.strptime(date_value, fmt)
                return dt.strftime("%d.%m.%Y")
            except ValueError:
                continue

    return None


def _escape_html(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _available_ai_provider():
    if AI_PROVIDER in {"groq", "openrouter"}:
        return AI_PROVIDER
    if GROQ_API_KEY:
        return "groq"
    if OPENROUTER_API_KEY:
        return "openrouter"
    return None


def _call_ai_chat(prompt, system_prompt, max_tokens=140, temperature=0.8):
    provider = _available_ai_provider()
    if not provider:
        return None

    if provider == "groq":
        url = "https://api.groq.com/openai/v1/chat/completions"
        api_key = GROQ_API_KEY
        model = GROQ_MODEL
    else:
        url = "https://openrouter.ai/api/v1/chat/completions"
        api_key = OPENROUTER_API_KEY
        model = OPENROUTER_MODEL

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=AI_TIMEOUT_SEC)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        content = str(content).strip()
        return content or None
    except Exception as e:
        logger.warning(f"AI caption call failed ({provider}): {e}")
        return None


def _generate_ai_body(content_type, rating, likes, safe_tags, tech_block):
    if not ENABLE_AI_CAPTION:
        return None

    base_prompt = (
        "Сделай короткий пост на русском для NSFW Telegram канала.\n"
        "Тон: живой, уверенный, без кринжа и без канцелярита.\n"
        "Ограничения: 1-2 коротких предложения, без markdown, без ссылок, без эмодзи.\n"
        f"Контент: {content_type.upper()}, rating={rating}, likes={likes}.\n"
        f"Теги: {', '.join(safe_tags[:10]) if safe_tags else 'нет'}.\n"
        f"Тех.данные: {tech_block if tech_block else 'нет'}.\n"
        "Верни только текст подписи."
    )

    system_1 = (
        "Ты редактор коротких NSFW-постов. "
        "Пиши естественно и лаконично, без странных AI-фраз."
    )
    draft = _call_ai_chat(base_prompt, system_1, max_tokens=140, temperature=0.8)
    if not draft:
        return None

    # Second pass: anti-cringe cleanup.
    system_2 = (
        "Очисти текст от неестественных и повторяющихся формулировок. "
        "Оставь смысл. Максимум 220 символов. "
        "Верни только итоговый текст."
    )
    refined = _call_ai_chat(draft, system_2, max_tokens=120, temperature=0.3)
    final_text = refined or draft

    if len(final_text) > 280:
        final_text = final_text[:277].rstrip() + "..."

    return final_text.strip() if final_text else None


# ==================== BUILD ====================

def generate_caption(tags, rating, likes, image_data=None, image_url=None,
                     watermark="📢 @eroslabai", suggestion="💬 Предложка: @Haillord",
                     content_type="ai", width=None, height=None,
                     file_size=None, date=None):
    """
    Builds caption with technical details.

    Params:
    - width, height: image/video dimensions in pixels
    - file_size: bytes
    - date: datetime or string format YYYY-MM-DD
    """
    safe_watermark = _escape_html(watermark)
    clickable_suggestion = '💬 <a href="https://t.me/Haillord">Предложка</a>'
    footer = f"{safe_watermark}\n{clickable_suggestion}"

    content_header = "🟢 AI Art | 🔴 3D" if content_type == "ai" else "🔴 AI Art | 🟢 3D"

    resolution, aspect_ratio = _format_resolution(width, height)
    formatted_size = _format_file_size(file_size)
    formatted_date = _format_date(date)

    tech_lines = []
    if resolution and aspect_ratio:
        tech_lines.append(f"📐 {resolution} | {aspect_ratio}")
    elif resolution:
        tech_lines.append(f"📐 {resolution}")

    if formatted_size:
        tech_lines.append(f"💾 {formatted_size}")

    if formatted_date:
        tech_lines.append(f"📅 {formatted_date}")

    tech_block = "\n".join(tech_lines) if tech_lines else ""

    safe_tags = _clean_caption_tags(_safe_tags(tags))
    hashtags = " ".join(f"#{t}" for t in safe_tags[:MAX_HASHTAGS]) if safe_tags else ""
    style_block = _build_style_block(safe_tags)

    fallback_parts = [content_header]
    if tech_block:
        fallback_parts.append(tech_block)
    if style_block:
        fallback_parts.append(style_block)
    if hashtags:
        fallback_parts.append(hashtags)
    fallback_parts.append(footer)
    fallback_caption = "\n\n".join(fallback_parts)

    ai_body = _generate_ai_body(content_type, rating, likes, safe_tags, tech_block)
    if not ai_body:
        return fallback_caption

    ai_parts = [content_header]
    if tech_block:
        ai_parts.append(tech_block)
    ai_parts.append(_escape_html(ai_body))
    if style_block:
        ai_parts.append(style_block)
    if hashtags:
        ai_parts.append(hashtags)
    ai_parts.append(footer)
    ai_caption = "\n\n".join(ai_parts)

    if AI_DRY_RUN:
        logger.info(f"AI_DRY_RUN fallback caption: {fallback_caption[:240]}")
        logger.info(f"AI_DRY_RUN ai caption: {ai_caption[:240]}")
        return fallback_caption

    return ai_caption
