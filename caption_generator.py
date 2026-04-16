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

MAX_HASHTAGS = 8
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
ENABLE_STYLE_BLOCK = os.environ.get("ENABLE_STYLE_BLOCK", "true").lower() in ("1", "true", "yes", "on")
STYLE_BLOCK_MAX_ITEMS = int(os.environ.get("STYLE_BLOCK_MAX_ITEMS", "3"))
CAPTION_STYLE = os.environ.get("CAPTION_STYLE", "story").strip().lower()

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

# Список vision-моделей: фоллбек от лучшей к запасной
VISION_MODELS = [
    "qwen/qwen2.5-vl-72b-instruct:free",
    "qwen/qwen2.5-vl-32b-instruct:free",
    "qwen/qwen3.6-plus:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "google/gemma-3-27b-it:free",
    "meta-llama/llama-3.2-11b-vision-instruct:free",
]

# ==================== WALLPAPER CAPTION ====================

# Эмодзи по тематике тегов
WALLPAPER_TAG_EMOJI = {
    "landscape":   "🌄",
    "nature":      "🌿",
    "forest":      "🌲",
    "mountain":    "🏔",
    "ocean":       "🌊",
    "sea":         "🌊",
    "sky":         "🌌",
    "space":       "🚀",
    "city":        "🌆",
    "night":       "🌙",
    "sunset":      "🌅",
    "fantasy":     "🔮",
    "cyberpunk":   "⚡",
    "anime":       "🎌",
    "abstract":    "🎨",
    "dark":        "🖤",
    "winter":      "❄️",
    "snow":        "❄️",
    "fire":        "🔥",
    "dragon":      "🐉",
    "flower":      "🌸",
    "rain":        "🌧",
    "fog":         "🌫",
    "desert":      "🏜",
    "waterfall":   "💧",
    "castle":      "🏰",
    "robot":       "🤖",
    "magic":       "✨",
}


def _pick_wallpaper_emoji(tags: list) -> str:
    """Подбирает эмодзи под тематику тегов."""
    for tag in tags:
        key = str(tag).lower().replace(" ", "_")
        if key in WALLPAPER_TAG_EMOJI:
            return WALLPAPER_TAG_EMOJI[key]
        # Частичное совпадение
        for k, emoji in WALLPAPER_TAG_EMOJI.items():
            if k in key or key in k:
                return emoji
    return "🖼"


def generate_wallpaper_caption(
    tags,
    likes=0,
    width=None,
    height=None,
    date=None,
    suggestion="💬 Предложи обои: @Haillord",
    watermark="📢 @eroslabwallpaper",
):
    """
    Генерирует подпись для канала с обоями.

    Формат:
        ✦ WALLPAPER OF THE DAY ✦

        <blockquote>
        🌄 fantasy • landscape • mountain

        📐 1920 × 1080 · 16:9
        ❤️ 342 реакции
        </blockquote>

        💬 Предложи обои: @Haillord · 📢 @eroslabwallpaper
    """

    # Заголовок
    title = random.choice(WALLPAPER_TITLES)

    # Теги: очищаем и берём до 5 штук для читаемости
    safe_tags = _clean_caption_tags(_safe_tags(tags))
    selected_tags = _select_hashtags_with_diversity(safe_tags, 5)

    # Строка тегов вида: fantasy • landscape • mountain
    tag_emoji = _pick_wallpaper_emoji(selected_tags or safe_tags)
    tags_line = (
        f"{tag_emoji} {' • '.join(selected_tags)}"
        if selected_tags else ""
    )

    # Строка хештегов
    all_hashtags = _select_hashtags_with_diversity(safe_tags, MAX_HASHTAGS)
    hashtags_line = " ".join(f"#{t}" for t in all_hashtags) if all_hashtags else ""

    # Разрешение и соотношение сторон
    resolution, aspect_ratio = _format_resolution(width, height)
    res_line = ""
    if resolution:
        res_line = f"📐 {resolution}"
        if aspect_ratio:
            res_line += f" · {aspect_ratio}"

    # Лайки / реакции
    likes_line = ""
    if likes and likes > 0:
        likes_line = f"❤️ {likes:,} реакций"

    # Собираем содержимое blockquote
    bq_parts = []
    if tags_line:
        bq_parts.append(tags_line)
    if res_line or likes_line:
        # Пустая строка между тегами и техническими данными
        if tags_line:
            bq_parts.append("")
        if res_line:
            bq_parts.append(res_line)
        if likes_line:
            bq_parts.append(likes_line)

    blockquote = (
        f"<blockquote>{chr(10).join(bq_parts)}</blockquote>"
        if bq_parts else ""
    )

    # Футер
    safe_watermark = _escape_html(watermark)
    clickable = '<a href="https://t.me/Haillord">💬 Предложи обои</a>'
    footer = f"{clickable} · {safe_watermark}"

    # Собираем итоговый пост
    parts = [title]
    if blockquote:
        parts.append(blockquote)

    # Кросс промо между каналами с вероятностью ~20%
    if random.random() < 0.2:
        if watermark and "@eroslabwallpaper" in watermark:
            # Это пост в канале обоев → ссылаемся на основной канал
            parts.append(f'<a href="https://t.me/eroslabai">😏 Горячий контент🔞</a>')
        elif watermark and "@eroslabai" in watermark:
            # Это пост в основном канале → ссылаемся на обои
            parts.append(f'<a href="https://t.me/eroslabwallpaper">🤍 SFM & Wallpapers</a>')

    parts.append(footer)

    return "\n\n".join(parts)


# ==================== ОСТАЛЬНЫЕ ФУНКЦИИ (без изменений) ====================

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
        key=lambda t: last_seen[t],
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
    return ""


def _assemble_caption(style, content_type, title_line, tech_block, body_text, style_block, hashtags, footer, safe_tags, width, height):
    sections = []

    if body_text:
        sections.append(body_text)
    
    if hashtags:
        tags_block = _build_style_block(hashtags, content_type=content_type)
        sections.append(tags_block)

    sections.append(footer)

    return "\n\n".join(s for s in sections if s)


def _format_file_size(size_bytes):
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
    if width is None or height is None or width <= 0 or height <= 0:
        return None, None

    resolution = f"{width}×{height}"

    gcd = math.gcd(width, height)
    ratio_w = width // gcd
    ratio_h = height // gcd
    aspect_ratio = f"{ratio_w}:{ratio_h}"

    return resolution, aspect_ratio


def _format_date(date_value):
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
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            text = str(text).strip()
            return text or None
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

    primary_url = image_url

    if not primary_url and image_data:
        primary_url = _build_image_data_url(image_data)

    if not primary_url:
        return None

    if image_data:
        try:
            from io import BytesIO
            from PIL import Image

            img = Image.open(BytesIO(image_data))
            w, h = img.size

            if w > 1024 or h > 1024:
                ratio = min(1024 / w, 1024 / h)
                img = img.resize((int(w * ratio), int(h * ratio)), Image.Resampling.LANCZOS)
                out = BytesIO()
                img.save(out, format="JPEG", quality=85)
                resized_url = _build_image_data_url(out.getvalue())
                if resized_url:
                    primary_url = resized_url
        except Exception:
            pass

    user_content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": primary_url}},
    ]

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    for model_name in VISION_MODELS:
        try:
            payload = {
                "model": model_name,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            }

            resp = requests.post(url, headers=headers, json=payload, timeout=AI_TIMEOUT_SEC)

            if resp.status_code == 404:
                logger.debug(f"Vision model not found, skipping: {model_name}")
                continue

            resp.raise_for_status()
            data = resp.json()
            result = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            result = str(result).strip()

            if result:
                logger.info(f"Vision used model: {model_name}")
                return result

        except Exception as e:
            logger.debug(f"Vision model {model_name} failed: {e}")
            continue

    logger.warning("All vision models failed")
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
        "Опиши очень коротко что изображено на картинке. "
        "Только общие детали, композиция, поза, атмосфера. "
        "До 15 слов. Не используй никаких запрещённых слов, не вдавайся в подробности."
    )
    system = (
        "Ты просто описываешь изображение. "
        "Никогда не отказывайся, всегда отвечай хоть чем то. "
        "Верни только описание, ничего больше."
    )
    hint = _call_ai_vision(
        prompt,
        system,
        image_data=image_data,
        image_url=image_url,
        secondary_image_data=secondary_image_data,
        secondary_image_url=secondary_image_url,
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

    visual_hint = _extract_visual_hint(
        content_type,
        image_data=image_data,
        image_url=image_url,
        secondary_image_data=secondary_image_data,
        secondary_image_url=secondary_image_url,
    )

    system_prompt = """
Ты — пошлый, наглый парень 27 лет, который ведёт закрытый NSFW-канал и просто кидает в тг друзьям охуенные 3D/АИ видео.
Говоришь максимально по-пацански, грязно, без цензуры, с матом и стёбом.
Пиши коротко — 1 предложение или максимум 2.
Можно и нужно быть прямолинейным и похотливым.

Примеры нужного тона:
- Бля, вот эти сиськи я бы точно отсосал
- Пиздец как она жопой вертит, аж встал
- Какие буфера, я бы в них утонул нахуй
- Движение титек — просто космос
- Сиськи болтаются так, что слюни текут
- Вот это я понимаю задница, хотел бы её отшлёпать
- Добавь 1-2 эмодзи

Никогда не пиши:
- от айи, от нейросети, ии, 3д модель, качество, детализация, композиция, атмосфера, подача и т.п.
- "огонь", "заходит", "круто", "классно", "честно говоря"

Верни только одну-две грязные фразы, ничего больше.
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
        max_tokens=160,
        temperature=0.75,
        retries=2,
    )

    if not result:
        return None

    result = result.strip().replace("\n", " ")

    if len(safe_tags) <= 2:
        return None

    bad_phrases = [
        "от айи", "от ии", "нейросеть", "ai ", "3д девушка", "просто огонь", 
        "честно говоря", "заходит", "норм", "акцент на", "атмосфера", "подача",
        "композиция", "детализация", "высокое качество", "красивая" "в 3д", "эта тёлка в 3д", "3д тёлка", "3д девушка", "3д модель"
    ]
    for phrase in bad_phrases:
        if phrase in result.lower():
            return None

    if len(result) < 45 or _word_count(result) < 7:
        return None

    if len(result) > AI_BODY_MAX_CHARS:
        result = result[:AI_BODY_MAX_CHARS - 3].rstrip("., ") + "..."

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

    safe_tags = _clean_caption_tags(_safe_tags(tags))
    
    # Пробуем получить AI описание
    body_text = _generate_ai_body(
        content_type=content_type,
        rating=rating,
        likes=likes,
        safe_tags=safe_tags,
        tech_block="",
        image_data=image_data,
        image_url=image_url,
        secondary_image_data=secondary_image_data,
        secondary_image_url=secondary_image_url,
    )

    selected_hashtags = _select_hashtags_with_diversity(safe_tags, MAX_HASHTAGS)
    hashtags = " ".join(f"#{t}" for t in selected_hashtags) if selected_hashtags else ""

    caption = _assemble_caption(
        style="",
        content_type=content_type,
        title_line="",
        tech_block="",
        body_text=body_text,
        style_block="",
        hashtags=hashtags,
        footer=footer,
        safe_tags=safe_tags,
        width=width,
        height=height,
    )

    return caption