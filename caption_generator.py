"""
Генератор описаний: хэштеги + техническая информация + footer.
Без AI-подписей, без кринжа.
"""

import logging
import math
from datetime import datetime

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

MAX_HASHTAGS = 6


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


def _format_file_size(size_bytes):
    """Форматирует размер файла в читаемый вид."""
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
    """Форматирует разрешение и соотношение сторон."""
    if width is None or height is None or width <= 0 or height <= 0:
        return None, None

    resolution = f"{width}×{height}"

    gcd = math.gcd(width, height)
    ratio_w = width // gcd
    ratio_h = height // gcd
    aspect_ratio = f"{ratio_w}:{ratio_h}"

    return resolution, aspect_ratio


def _format_date(date_value):
    """Форматирует дату в читаемый вид."""
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


# ==================== СБОРКА ====================

def generate_caption(tags, rating, likes, image_data=None, image_url=None,
                     watermark="📢 @eroslabai", suggestion="💬 Предложка: @Haillord",
                     content_type="ai", width=None, height=None,
                     file_size=None, date=None):
    """
    Генерирует подпись с технической информацией.

    Параметры:
    - width, height: размеры изображения в пикселях
    - file_size: размер файла в байтах
    - date: дата создания (datetime или строка в формате YYYY-MM-DD)
    """
    # Фикс: правильное HTML-экранирование
    safe_watermark = watermark.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    clickable_suggestion = '💬 <a href="https://t.me/Haillord">Предложка</a>'
    footer = f"{safe_watermark}\n{clickable_suggestion}"

    # Фикс: показываем только актуальный тип контента
    content_header = "🤖 AI Art" if content_type == "ai" else "🎨 3D Art"

    # Техническая информация
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

    # Хэштеги
    safe_tags = _safe_tags(tags)
    hashtags = " ".join(f"#{t}" for t in safe_tags[:MAX_HASHTAGS]) if safe_tags else ""

    # Сборка подписи
    parts = [content_header]

    if tech_block:
        parts.append(tech_block)

    if hashtags:
        parts.append(hashtags)

    parts.append(footer)

    return "\n\n".join(parts)