"""
Caption generator: hashtags + technical block + footer.
Supports optional AI-enhanced copy with safe fallback.
"""

import logging
import math
import os
import random
import time
import json
import base64
from datetime import datetime
from pathlib import Path

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
CAPTION_STATE_FILE = os.environ.get("CAPTION_STATE_FILE", "caption_state.json")
HASHTAG_HISTORY_SIZE = int(os.environ.get("HASHTAG_HISTORY_SIZE", "80"))

ENABLE_AI_CAPTION = os.environ.get("ENABLE_AI_CAPTION", "false").lower() in ("1", "true", "yes", "on")
AI_DRY_RUN = os.environ.get("AI_DRY_RUN", "false").lower() in ("1", "true", "yes", "on")
ENABLE_AI_CTA = os.environ.get("ENABLE_AI_CTA", "true").lower() in ("1", "true", "yes", "on")
UNIVERSAL_CTA = os.environ.get("UNIVERSAL_CTA", "💬 Как тебе этот пост?").strip()
AI_PROVIDER = os.environ.get("AI_PROVIDER", "auto").strip().lower()
AI_TIMEOUT_SEC = int(os.environ.get("AI_TIMEOUT_SEC", "12"))
AI_BODY_MIN_CHARS = int(os.environ.get("AI_BODY_MIN_CHARS", "90"))
AI_BODY_MAX_CHARS = int(os.environ.get("AI_BODY_MAX_CHARS", "150"))
AI_BODY_MIN_WORDS = int(os.environ.get("AI_BODY_MIN_WORDS", "16"))
AI_BODY_MAX_WORDS = int(os.environ.get("AI_BODY_MAX_WORDS", "24"))
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
ENABLE_AI_VISION = os.environ.get("ENABLE_AI_VISION", "false").lower() in ("1", "true", "yes", "on")
OPENROUTER_VISION_MODEL = os.environ.get("OPENROUTER_VISION_MODEL", "nvidia/nemotron-nano-12b-v2-vl:free")
OPENROUTER_VISION_FALLBACK_MODEL = os.environ.get("OPENROUTER_VISION_FALLBACK_MODEL", "google/gemma-3-27b-it:free")
ENABLE_STYLE_BLOCK = os.environ.get("ENABLE_STYLE_BLOCK", "true").lower() in ("1", "true", "yes", "on")
STYLE_BLOCK_MAX_ITEMS = int(os.environ.get("STYLE_BLOCK_MAX_ITEMS", "3"))
CAPTION_STYLE = os.environ.get("CAPTION_STYLE", "story").strip().lower()

CRINGE_TAG_HINTS = {
    "dynamic", "moments", "details", "fidelity", "thrust", "shaking",
    "jiggle", "ultra", "cinematic", "masterpiece", "quality"
}

STYLE_TAG_STOP = {
    "solo", "woman", "girl", "female", "image", "video", "clip",
    "high", "quality", "detail", "best", "art", "ai", "3d",
    "bed", "bedroom", "room", "scene", "background"
}

NSFW_TOKEN_BLOCKLIST = {
    "penis", "cock", "cum", "pussy", "anal", "nude", "naked",
    "blowjob", "fetish", "creampie", "bdsm", "genitals", "balls"
}

STYLE_VARIANTS = ("classic", "story", "minimal")
FRAME_EMOJI_AI = ("✨", "💫", "🌌")
FRAME_EMOJI_3D = ("🔥", "🎯", "🧨")

TITLE_VARIANTS_AI = (
    "💙 Свежий дроп",
    "💙 Новый кадр",
    "💙 Свежак",
    "💙 Прилетело",
    "💙 Отборный контент",
    "💙 Классный кадр",
    "💙 В ленту",
    "💙 Сегодняшний материал",
)

TITLE_VARIANTS_3D = (
    "❤️ Свежий дроп",
    "❤️ Новый кадр",
    "❤️ Свежак",
    "❤️ Прилетело",
    "❤️ Отборный контент",
    "❤️ Классный кадр",
    "❤️ В ленту",
    "❤️ Сегодняшний материал",
)

CTA_VARIANTS = (
    "💬 Как тебе такой формат?",
    "💬 Делись мнением в комментариях",
    "💬 Твой фидбек делает ленту лучше",
    "💬 Оценим пост в реакциях и комментах",
    "💬 Пиши, что добавить в следующий дроп",
)

def _generate_ai_cta(content_type, safe_tags):
    if not ENABLE_AI_CTA:
        return None

    prompt = (
        "Сгенерируй короткий CTA для Telegram-поста.\n"
        "Строго 1 строка, до 55 символов.\n"
        "Тон: живой, дружелюбный, без кринжа.\n"
        "Начни с эмодзи 💬, без ссылок и хэштегов.\n"
        f"Контент: {content_type}. Теги: {', '.join(safe_tags[:6]) if safe_tags else 'нет'}.\n"
        "Верни только итоговую строку."
    )
    system = "Ты пишешь короткие CTA-строки для контент-канала."
    cta = _call_ai_chat(prompt, system, max_tokens=40, temperature=0.7)
    if not cta:
        return None
    cta = str(cta).strip().replace("\n", " ")
    if not cta.startswith("💬"):
        cta = f"💬 {cta.lstrip('•- ')}"
    if len(cta) > 65:
        cta = cta[:62].rstrip() + "..."
    return _escape_html(cta)


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
        parts = [p for p in t_lower.split("_") if p]
        if any(p in NSFW_TOKEN_BLOCKLIST for p in parts):
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


def _load_caption_state():
    path = Path(CAPTION_STATE_FILE)
    if not path.exists():
        return {"recent_hashtags": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"recent_hashtags": []}
        recent = data.get("recent_hashtags", [])
        if not isinstance(recent, list):
            recent = []
        return {"recent_hashtags": [str(x).strip().lower() for x in recent if str(x).strip()]}
    except Exception:
        return {"recent_hashtags": []}


def _save_caption_state(state):
    payload = state if isinstance(state, dict) else {"recent_hashtags": []}
    try:
        with open(CAPTION_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Could not save caption state: {e}")


def _select_hashtags_with_diversity(safe_tags, max_count):
    candidates = [str(t).strip().lower() for t in safe_tags if str(t).strip()]
    unique = list(dict.fromkeys(candidates))
    if not unique or max_count <= 0:
        return []

    state = _load_caption_state()
    recent = list(state.get("recent_hashtags", []))

    last_seen = {}
    for idx, tag in enumerate(recent):
        last_seen[tag] = idx

    unseen = [t for t in unique if t not in last_seen]
    seen = sorted(
        [t for t in unique if t in last_seen],
        key=lambda t: last_seen[t],  # older seen tags first
    )

    selected = (unseen + seen)[:max_count]

    new_recent = recent + selected
    if len(new_recent) > HASHTAG_HISTORY_SIZE:
        new_recent = new_recent[-HASHTAG_HISTORY_SIZE:]
    _save_caption_state({"recent_hashtags": new_recent})
    return selected


def _humanize_tag(tag):
    text = str(tag).replace("_", " ").strip()
    if not text:
        return ""
    return text[0].upper() + text[1:]


def _pick_frame_emoji(content_type):
    if content_type == "ai":
        return random.choice(FRAME_EMOJI_AI)
    return random.choice(FRAME_EMOJI_3D)


def _build_style_block(body_text, content_type=None):
    if not ENABLE_STYLE_BLOCK:
        return ""

    text = str(body_text or "").strip()
    if not text:
        return ""

    prefix = _pick_frame_emoji(content_type) if content_type else "✨"
    return f"<blockquote>{prefix} {_escape_html(text)}</blockquote>"


def _pick_caption_style():
    if CAPTION_STYLE in STYLE_VARIANTS:
        return CAPTION_STYLE
    # auto: случайный, но контролируемый набор шаблонов
    return random.choice(STYLE_VARIANTS)


def _build_title_line(content_type):
    if content_type == "ai":
        return random.choice(TITLE_VARIANTS_AI)
    return random.choice(TITLE_VARIANTS_3D)


def _pick_subject_tag(safe_tags):
    for tag in safe_tags:
        low = str(tag).lower()
        if low in STYLE_TAG_STOP:
            continue
        if len(low) < 4 or len(low) > 24:
            continue
        if any(c.isdigit() for c in low):
            continue
        return _humanize_tag(low)
    return ""


def _build_fallback_body(content_type, likes, safe_tags):
    subject = _pick_subject_tag(safe_tags)
    if content_type == "ai":
        if subject:
            variants = [
                f"Акцент на {subject.lower()} и пластике сцены.\nПодача мягкая, но выразительная.",
                f"В центре — {subject.lower()} и настроение кадра.\nСцена держит внимание до конца.",
                f"Кадр выстроен вокруг {subject.lower()}.\nАтмосфера спокойная, с чётким фокусом.",
            ]
            return random.choice(variants)
        return random.choice([
            "Свежий AI-кадр с аккуратной композицией.\nФокус на атмосфере и подаче.",
            "Новый AI-визуал в ленте.\nСцена собрана спокойно и чисто.",
            "AI-пост с акцентом на настроение.\nБез лишнего шума, только кадр и вайб.",
        ])
    if subject:
        variants = [
            f"Акцент на {subject.lower()} и динамике сцены.\nКадр читается с первого взгляда.",
            f"В центре — {subject.lower()} и движение формы.\nПодача плотная и выразительная.",
            f"3D-сцена с фокусом на {subject.lower()}.\nКомпозиция держится уверенно.",
        ]
        return random.choice(variants)
    return random.choice([
        "Свежая 3D-сцена в ленте.\nАкцент на композиции и движении кадра.",
        "Новый 3D-визуал без лишнего шума.\nЧистая подача и ровный ритм.",
        "3D-пост с акцентом на подачу.\nДетали работают на общее настроение.",
    ])


def _build_hook_line(style, content_type, safe_tags, width, height):
    # Хук отключаем: он добавлял техничный/ломаный вид.
    return ""


def _assemble_caption(style, content_type, title_line, tech_block, body_text, style_block, hashtags, footer, safe_tags, width, height):
    sections = [title_line]

    hook = _build_hook_line(style, content_type, safe_tags, width, height)
    if hook:
        sections.append(hook)

    if body_text:
        sections.append(body_text)
    elif style_block:
        sections.append(style_block)

    if tech_block:
        sections.append(tech_block)

    if hashtags:
        sections.append(hashtags)

    cta_line = UNIVERSAL_CTA or "💬 Как тебе этот пост?"
    sections.append(f"{cta_line}\n{footer}")

    # One empty line between blocks for cleaner, "bigger" visual rhythm.
    return "\n\n".join(s for s in sections if s)


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


def _word_count(text):
    return len([w for w in str(text).replace("\n", " ").split(" ") if w.strip()])


def _available_ai_provider():
    if AI_PROVIDER in {"groq", "openrouter"}:
        return AI_PROVIDER
    if GROQ_API_KEY:
        return "groq"
    if OPENROUTER_API_KEY:
        return "openrouter"
    return None


def _call_ai_chat(prompt, system_prompt, max_tokens=140, temperature=0.8, retries=1):
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

    for attempt in range(max(1, retries)):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=AI_TIMEOUT_SEC)
            resp.raise_for_status()
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            content = str(content).strip()
            return content or None
        except Exception as e:
            if attempt == max(1, retries) - 1:
                logger.warning(f"AI caption call failed ({provider}): {e}")
                return None
            time.sleep(0.6)
    return None


def _guess_image_mime(image_data):
    if not image_data or len(image_data) < 12:
        return "image/jpeg"
    if image_data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_data.startswith(b"GIF87a") or image_data.startswith(b"GIF89a"):
        return "image/gif"
    if image_data[0:4] == b"RIFF" and image_data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _build_image_data_url(image_data):
    if not image_data:
        return None
    if len(image_data) > 2 * 1024 * 1024:
        return None
    mime = _guess_image_mime(image_data)
    b64 = base64.b64encode(image_data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _call_ai_vision(
    prompt,
    system_prompt,
    image_data=None,
    image_url=None,
    secondary_image_data=None,
    secondary_image_url=None,
    model=None,
    max_tokens=110,
    temperature=0.2,
    retries=1,
):
    if not ENABLE_AI_VISION or not OPENROUTER_API_KEY:
        return None

    primary_url = image_url or _build_image_data_url(image_data)
    secondary_url = secondary_image_url or _build_image_data_url(secondary_image_data)

    if not primary_url and not secondary_url:
        return None

    content = [{"type": "text", "text": prompt}]
    if primary_url:
        content.append({"type": "image_url", "image_url": {"url": primary_url}})
    if secondary_url:
        content.append({"type": "image_url", "image_url": {"url": secondary_url}})

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model or OPENROUTER_VISION_MODEL,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
    }

    for attempt in range(max(1, retries)):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=AI_TIMEOUT_SEC)
            resp.raise_for_status()
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            content = str(content).strip()
            return content or None
        except Exception as e:
            if attempt == max(1, retries) - 1:
                logger.warning(f"AI vision call failed (openrouter): {e}")
                return None
            time.sleep(0.6)
    return None


def _extract_visual_hint(
    content_type,
    image_data=None,
    image_url=None,
    secondary_image_data=None,
    secondary_image_url=None,
):
    def _is_non_informative(value):
        if not value:
            return True
        token = str(value).replace("\n", " ").strip().lower()
        return token in {"none", "null", "n/a", "na", "no", "nope", "-"}

    if not ENABLE_AI_VISION:
        logger.info("Vision hint skipped: ENABLE_AI_VISION is disabled")
        return None

    if not OPENROUTER_API_KEY:
        logger.info("Vision hint skipped: OPENROUTER_API_KEY is not set")
        return None

    prompt = (
        "Опиши визуально что в кадре для подписи NSFW-поста: "
        "композиция, свет, настроение, динамика. "
        "Если переданы два кадра, учитывай оба и опиши общий вайб. "
        "До 18 слов, без перечисления телесных деталей и без вульгарности."
    )
    system = (
        "Ты даешь краткий нейтральный визуальный дескриптор для редактора подписи. "
        "Верни одну строку без хэштегов."
    )
    hint = _call_ai_vision(
        prompt,
        system,
        image_data=image_data,
        image_url=image_url,
        secondary_image_data=secondary_image_data,
        secondary_image_url=secondary_image_url,
        model=OPENROUTER_VISION_MODEL,
        max_tokens=80,
        temperature=0.1,
        retries=1,
    )

    if _is_non_informative(hint) and OPENROUTER_VISION_FALLBACK_MODEL:
        logger.info(
            "Vision primary model returned empty/non-informative response. "
            f"Trying fallback model: {OPENROUTER_VISION_FALLBACK_MODEL}"
        )
        hint = _call_ai_vision(
            prompt,
            system,
            image_data=image_data,
            image_url=image_url,
            secondary_image_data=secondary_image_data,
            secondary_image_url=secondary_image_url,
            model=OPENROUTER_VISION_FALLBACK_MODEL,
            max_tokens=80,
            temperature=0.1,
            retries=1,
        )

    if _is_non_informative(hint):
        logger.info("Vision hint unavailable: empty/non-informative response from vision models")
        return None

    normalized = hint.replace("\n", " ").strip()
    logger.info(f"Vision hint used: {normalized[:80]}")
    return normalized


def _generate_ai_body(
    content_type,
    rating,
    likes,
    safe_tags,
    tech_block,
    image_data=None,
    image_url=None,
    secondary_image_data=None,
    secondary_image_url=None,
):
    if not ENABLE_AI_CAPTION:
        return None

    # Пробуем получить визуальный хинт по картинке
    visual_hint = _extract_visual_hint(
        content_type,
        image_data=image_data,
        image_url=image_url,
        secondary_image_data=secondary_image_data,
        secondary_image_url=secondary_image_url,
    )

    system_prompt = """
Ты админ порно Telegram канала.
Пиши как живой человек, как будто скинул другу крутой кадр.
Коротко, по делу, без клише и шаблонов.
Никогда не пиши "выразительная подача", "атмосфера кадра", "акцент на детали".
Без кринжа, без перегибов. 1-2 предложения максимум.
"""

    prompt_parts = [
        "Напиши подпись для этого поста.",
        f"Тип контента: {content_type}",
        f"Темы: {', '.join(safe_tags[:7]) if safe_tags else 'разное'}",
    ]

    if visual_hint:
        prompt_parts.append(f"По картинке: {visual_hint}")

    prompt_parts.append(f"Получилась строка {AI_BODY_MIN_WORDS}-{AI_BODY_MAX_WORDS} слов. Только текст, ничего больше.")

    final_prompt = "\n".join(prompt_parts)

    result = _call_ai_chat(
        final_prompt,
        system_prompt,
        max_tokens=130,
        temperature=0.45,
        retries=2
    )

    if not result:
        return None

    result = result.strip().replace("\n", " ")

    # Если тегов очень мало - ИИ почти всегда генерирует фигню, лучше сразу фоллбек
    if len(safe_tags) <= 2:
        return None

    # Простая постобработка вместо дополнительных вызовов ИИ
    bad_phrases = [
        "выразительная подача", "атмосфера кадра", "акцент на",
        "идеальная фигура", "отличная композиция", "высокое качество",
        "хорошая детализация", "красивая сцена", "искусственный интеллект",
        "нейросеть", "ии создал", "ai сгенерировал", "различные изображения"
    ]
    for phrase in bad_phrases:
        if phrase in result.lower():
            return None

    if len(result) < 45 or _word_count(result) < 7:
        return None

    if len(result) > AI_BODY_MAX_CHARS:
        result = result[:AI_BODY_MAX_CHARS-3].rstrip("., ") + "..."

    return result


# ==================== BUILD ====================

def generate_caption(tags, rating, likes, image_data=None, image_url=None,
                     secondary_image_data=None, secondary_image_url=None,
                     watermark="📣 @eroslabai", suggestion="💬 Предложка: @Haillord",
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
    clickable_suggestion = '<a href="https://t.me/Haillord">💬 Предложка</a>'
    footer = f"{safe_watermark} · {clickable_suggestion}"

    style = _pick_caption_style()
    content_header = _build_title_line(content_type)

    resolution, aspect_ratio = _format_resolution(width, height)
    formatted_size = _format_file_size(file_size)
    formatted_date = _format_date(date)

    tech_lines = []
    if resolution:
        if aspect_ratio:
            tech_lines.append(f"⚡ {resolution} · {aspect_ratio}")
        else:
            tech_lines.append(f"⚡ {resolution}")

    if formatted_date:
        tech_lines.append(f"📅 {formatted_date}")

    tech_block = "\n".join(tech_lines) if tech_lines else ""

    safe_tags = _clean_caption_tags(_safe_tags(tags))
    selected_hashtags = _select_hashtags_with_diversity(safe_tags, MAX_HASHTAGS)
    hashtags = " ".join(f"#{t}" for t in selected_hashtags) if selected_hashtags else ""
    fallback_body = _build_fallback_body(content_type, likes, safe_tags)
    fallback_style_block = _build_style_block(fallback_body, content_type=content_type)
    fallback_body_text = "" if fallback_style_block else fallback_body

    fallback_caption = _assemble_caption(
        style=style,
        content_type=content_type,
        title_line=content_header,
        tech_block=tech_block,
        body_text=fallback_body_text,
        style_block=fallback_style_block,
        hashtags=hashtags,
        footer=footer,
        safe_tags=safe_tags,
        width=width,
        height=height,
    )

    ai_body = _generate_ai_body(
        content_type,
        rating,
        likes,
        safe_tags,
        tech_block,
        image_data=image_data,
        image_url=image_url,
        secondary_image_data=secondary_image_data,
        secondary_image_url=secondary_image_url,
    )
    if not ai_body:
        return fallback_caption

    ai_style_block = _build_style_block(ai_body, content_type=content_type)
    ai_body_text = "" if ai_style_block else _escape_html(ai_body)

    ai_caption = _assemble_caption(
        style=style,
        content_type=content_type,
        title_line=content_header,
        tech_block=tech_block,
        body_text=ai_body_text,
        style_block=ai_style_block,
        hashtags=hashtags,
        footer=footer,
        safe_tags=safe_tags,
        width=width,
        height=height,
    )

    if AI_DRY_RUN:
        logger.info(f"AI_DRY_RUN caption style: {style}")
        logger.info(f"AI_DRY_RUN fallback caption: {fallback_caption[:240]}")
        logger.info(f"AI_DRY_RUN ai caption: {ai_caption[:240]}")
        return fallback_caption

    return ai_caption
