"""
Генератор описаний: только хэштеги + footer.
Без AI-подписей, без кринжа.
"""

import logging
import os

logger = logging.getLogger(__name__)


# ==================== ФИЛЬТРЫ ====================

NSFW_TRIGGER_TAGS = {
    "slut", "sex", "nude", "naked", "penis", "vagina", "cock",
    "pussy", "cum", "anal", "blowjob", "nsfw", "explicit", "porn",
    "hentai", "xxx", "nipple", "nipples", "breast", "breasts", "ass",
    "bondage", "bdsm", "fetish", "gangbang", "creampie", "ahegao",
    "spread_legs", "pussy_juice", "uncensored", "censored", "genitals"
}

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
        if t_lower.count("_") > 2:
            continue
        if any(c.isdigit() for c in t_lower):
            continue
        result.append(t)
    return result


# ==================== СБОРКА ====================

def _format_caption(tags, footer, content_header=None):
    safe_tags = _safe_tags(tags)
    hashtags = " ".join(f"#{t}" for t in safe_tags[:6]) if safe_tags else ""

    header_line = f"{content_header}\n" if content_header else ""
    if hashtags:
        return f"{header_line}\n{hashtags}\n\n{footer}"
    return f"{header_line}\n{footer}"


def generate_caption(tags, rating, likes, image_data=None, image_url=None,
                     watermark="📢 @eroslabai", suggestion="💬 Предложка: @Haillord",
                     content_type="ai"):
    # Экранируем специальные HTML-символы в watermark
    safe_watermark = watermark.replace("&", "&").replace("<", "<").replace(">", ">")
    # Используем HTML-ссылку для "Предложка"
    clickable_suggestion = '💬 <a href="https://t.me/Haillord">Предложка</a>'
    footer = f"{safe_watermark}\n{clickable_suggestion}"

    # Форматируем тип контента с цветными кружками
    if content_type == "ai":
        content_header = "🟢 AI Art | 🔴 3D"
    else:
        content_header = "🔴 AI Art | 🟢 3D"

    return _format_caption(tags, footer, content_header)