"""
ErosLab Bot — CivitAI (только X и XXX рейтинг)
Оптимизирован для GitHub Actions с защитой от повторов.
"""

import asyncio
import hashlib
import json
import logging
import os
import random
import re
import subprocess
import tempfile
import time
import requests
from io import BytesIO
from gist_storage import load_all_state, save_all_state
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont
import telegram
from telegram import Bot
from caption_generator import generate_caption
from rule34_api import fetch_rule34
from watermark import add_watermark, add_watermark_to_video, should_add_watermark

# ==================== НАСТРОЙКИ ====================
BOT_MODE = os.environ.get("BOT_MODE", "nsfw").lower()  # nsfw / wallpapers
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "@eroslabai")
ADMIN_USER_ID = str(os.environ.get("ADMIN_USER_ID", "")).strip()
REVIEW_MODE = os.environ.get("REVIEW_MODE", "false").lower() in ("1", "true", "yes", "on")
CIVITAI_API_KEY     = os.environ.get("CIVITAI_API_KEY", "")

WATERMARK_TEXT   = "📣 @eroslabai"
WATERMARK_IMAGE_TEXT = os.environ.get("WATERMARK_IMAGE_TEXT", "@eroslabai")
WATERMARK_IMAGE_OPACITY = float(os.environ.get("WATERMARK_IMAGE_OPACITY", "0.3"))
MIN_LIKES        = 10
MIN_CIVITAI_LIKES = int(os.environ.get("MIN_CIVITAI_LIKES", "1"))
ALLOW_MATURE_FALLBACK = os.environ.get("ALLOW_MATURE_FALLBACK", "false").lower() in ("1", "true", "yes", "on")
MIN_IMAGE_SIZE   = 720
ENABLE_VIDEO_QOS = os.environ.get("ENABLE_VIDEO_QOS", "true").lower() in ("1", "true", "yes", "on")
MIN_BITRATE_480P  = int(os.environ.get("MIN_BITRATE_480P", "900"))
MIN_BITRATE_720P  = int(os.environ.get("MIN_BITRATE_720P", "1400"))
MIN_BITRATE_1080P = int(os.environ.get("MIN_BITRATE_1080P", "2200"))
IMAGE_PACK_ENABLED = os.environ.get("IMAGE_PACK_ENABLED", "true").lower() in ("1", "true", "yes", "on")
IMAGE_PACK_SIZE = max(1, int(os.environ.get("IMAGE_PACK_SIZE", "3")))
IMAGE_PACK_CANDIDATE_POOL = max(IMAGE_PACK_SIZE, int(os.environ.get("IMAGE_PACK_CANDIDATE_POOL", "18")))
# True: отправлять пак отдельными постами, False: одним media_group
IMAGE_PACK_SPLIT_POSTS = os.environ.get("IMAGE_PACK_SPLIT_POSTS", "false").lower() in ("1", "true", "yes", "on")

# Временно отключить Rule34 (True = только CivitAI для тестов)
TEST_CIVITAI_ONLY = False

HISTORY_FILE = "posted_ids.json"
HASHES_FILE  = "posted_hashes.json"
CONTENT_STATE_FILE = "content_state.json"
PENDING_DRAFT_FILE = "pending_draft.json"
REVIEW_STATE_FILE = "review_state.json"
STATS_FILE = "stats.json"
MAX_HISTORY_SIZE = 5000
STATS_TZ = os.environ.get("STATS_TZ", "Europe/Moscow")

BLACKLIST_TAGS = {
    # Gore/violence
    "gore", "guro", "scat", "vore", "snuff", "necrophilia",
    # Bestiality
    "bestiality", "zoo",
    # Age restrictions
    "loli", "shota", "child", "minor", "underage", "infant", "toddler",
    # Gay content (male-only)
    "gay", "yaoi", "bara", "2boys", "3boys", "multiple_boys",
    "male_only", "male_male", "gay_male", "bl", "boy_love",
    # Explicit male-only focus markers
    "1boy", "solo_male", "male_focus", "male_pov",
    "handsome_muscular_man", "muscular_man", "handsome_man",
    "old_man", "young_man", "dilf", "twink", "femboy",
    # Other
    "furry_male", "anthro",
}

# Паттерны только для явного male-only фокуса (без среза mixed male+female сцен).
MALE_ONLY_PATTERNS = (
    r"(^|_)solo_male(_|$)",
    r"(^|_)male_only(_|$)",
    r"(^|_)male_focus(_|$)",
    r"(^|_)male_pov(_|$)",
    r"(^|_)1boy(_|$)",
    r"(^|_)\d+boy(s)?(_|$)",
    r"(^|_)2boys(_|$)",
    r"(^|_)3boys(_|$)",
    r"(^|_)multiple_boys(_|$)",
    r"(^|_)male_male(_|$)",
    r"(^|_)all_male(_|$)",
    r"(^|_)male_group(_|$)",
    r"(^|_)gay_male(_|$)",
    r"(^|_)boy_love(_|$)",
)

HASHTAG_STOP_WORDS = {
    "score", "source", "rating", "version", "step", "steps", "cfg", "seed",
    "sampler", "model", "lora", "vae", "clip", "unet", "fp16", "safetensors",
    "checkpoint", "embedding", "none", "null", "true", "false", "and", "the",
    "for", "with", "masterpiece", "best", "quality", "high", "ultra", "detail",
    "detailed", "8k", "4k", "hd", "resolution", "simple", "background",
    # Rule34 служебные теги
    "generated_by_ai", "animated", "rating_explicit", "rating_questionable",
    "rating_safe", "rating_suggestive", "tagme",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# ==================== ХРАНИЛИЩА ====================
def load_json(path, default):
    if Path(path).exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {path}: {e}")
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

_state = load_all_state()
posted_ids    = set(_state.get("posted_ids.json", []))
posted_hashes = set(_state.get("posted_hashes.json", []))
content_state = _state.get("content_state.json", {"last_type": "3d", "last_media": "video"})
pending_draft = _state.get("pending_draft.json", {})
review_state  = _state.get("review_state.json", {"last_update_id": 0})

def _get_stats_day_key():
    try:
        return datetime.now(ZoneInfo(STATS_TZ)).date().isoformat()
    except Exception:
        return datetime.utcnow().date().isoformat()

def _load_stats():
    data = load_json(STATS_FILE, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("schema_version", 2)
    data.setdefault("daily", {})
    data.setdefault("lifetime", {})
    data.setdefault("report", {})
    return data

def _increment_metrics(target: dict, metrics: dict):
    for key, value in metrics.items():
        if isinstance(value, (int, float)):
            target[key] = target.get(key, 0) + value

def record_run_stats(metrics: dict):
    stats = _load_stats()
    day_key = _get_stats_day_key()
    daily = stats["daily"].setdefault(day_key, {})
    lifetime = stats["lifetime"]

    _increment_metrics(daily, metrics)
    _increment_metrics(lifetime, metrics)

    # Совместимость со старым форматом.
    if metrics.get("posted", 0) > 0:
        stats["total_posts"] = stats.get("total_posts", 0) + int(metrics["posted"])

    # Держим только последние 45 дней daily-статистики.
    try:
        keys_sorted = sorted(stats["daily"].keys())
        while len(keys_sorted) > 45:
            oldest = keys_sorted.pop(0)
            stats["daily"].pop(oldest, None)
    except Exception:
        pass

    save_json(STATS_FILE, stats)

def get_next_content_type():
    """Чередует между 3d и ai контентом"""
    global content_state
    next_type = "ai" if content_state["last_type"] == "3d" else "3d"
    content_state["last_type"] = next_type
    save_json(CONTENT_STATE_FILE, content_state)
    return next_type

def get_next_media_type():
    """Строгое распределение: 70% video, 30% image."""
    global content_state
    media_type = "video" if random.random() < 0.7 else "image"
    content_state["last_media"] = media_type
    save_json(CONTENT_STATE_FILE, content_state)
    return media_type

def save_all():
    trimmed_ids    = list(posted_ids)[-MAX_HISTORY_SIZE:]
    trimmed_hashes = list(posted_hashes)[-MAX_HISTORY_SIZE:]
    save_all_state({
        "posted_ids.json":    trimmed_ids,
        "posted_hashes.json": trimmed_hashes,
        "content_state.json": content_state,
        "pending_draft.json": pending_draft,
        "review_state.json":  review_state,
        "stats.json":         _load_stats(),
    })


def save_review_state():
    save_all()


def save_pending_draft():
    save_all()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def clean_tags(tags):
    clean, seen = [], set()
    for t in tags:
        t = re.sub(r"[^\w]", "", str(t).strip().lower().replace(" ", "_").replace("-", "_"))
        if re.search(r'\d+$', t):
            continue
        if t and t not in HASHTAG_STOP_WORDS and t not in seen and 3 <= len(t) <= 30:
            clean.append(t)
            seen.add(t)
    return clean

def _normalize_tag(tag: str) -> str:
    return str(tag).strip().lower().replace(" ", "_").replace("-", "_")

def _has_male_only_pattern(tag: str) -> bool:
    for pattern in MALE_ONLY_PATTERNS:
        if re.search(pattern, tag):
            return True
    return False

def has_blacklisted(tags):
    normalized_tags = [_normalize_tag(t) for t in tags]
    blacklisted = set(normalized_tags) & BLACKLIST_TAGS

    if not blacklisted:
        for tag in normalized_tags:
            if _has_male_only_pattern(tag):
                blacklisted.add(tag)

    if blacklisted:
        logger.debug(f"Blacklisted: {blacklisted}")
        return True
    return False

def check_media_size(data, url):
    try:
        if not url.lower().endswith((".mp4", ".webm", ".gif")):
            img = Image.open(BytesIO(data))
            width, height = img.size
            if width >= MIN_IMAGE_SIZE and height >= MIN_IMAGE_SIZE:
                return True
            else:
                logger.warning(f"Image too small: {width}x{height}")
                return False
        else:
            logger.info("Video file, skipping size check")
            return True
    except Exception as e:
        logger.error(f"Error checking media size: {e}")
        return False

def get_video_duration(data: bytes) -> float:
    """Возвращает длительность или 0.0 если видео битое"""
    tmp_path = None
    duration_str = "N/A"
    try:
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
               '-of', 'default=noprint_wrappers=1:nokey=1', tmp_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

        if result.returncode != 0:
            logger.warning("ffprobe failed to read video")
            return 0.0

        duration_str = result.stdout.strip()
        
        # 🔥 ФИКС: проверяем, что вернулось не 'N/A'
        if not duration_str or duration_str == 'N/A':
            logger.warning(f"ffprobe returned: '{duration_str}'")
            return 0.0
        
        duration = float(duration_str)
        return duration

    except ValueError as e:
        logger.error(f"Error converting duration '{duration_str}' to float: {e}")
        return 0.0
    except Exception as e:
        logger.error(f"Error: {e}")
        return 0.0
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

def get_video_dimensions(data: bytes):
    """Возвращает (width, height) видео или (None, None) при ошибке."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'csv=s=x:p=0',
            tmp_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return None, None

        raw = result.stdout.strip()
        if not raw or "x" not in raw:
            return None, None

        width_str, height_str = raw.split("x", 1)
        return int(width_str), int(height_str)
    except Exception as e:
        logger.warning(f"Could not read video dimensions: {e}")
        return None, None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def normalize_video_aspect_ratio(data: bytes) -> bytes:
    """
    Нормализует соотношение сторон видео для корректного отображения в Телеграм.
    Добавляет минимальные чёрные паддинги только если видео выходит за безопасные границы 1:1.3 - 1.3:1
    Оригинальное видео не масштабируется и не обрезается.
    Возвращает оригинальные данные если исправление не требуется.
    """
    width, height = get_video_dimensions(data)
    if not width or not height:
        return data
    
    ratio = width / height
    MIN_SAFE_RATIO = 1 / 1.3  # ~0.769 = 1:1.3
    MAX_SAFE_RATIO = 1.3      # 1.3:1
    
    if MIN_SAFE_RATIO <= ratio <= MAX_SAFE_RATIO:
        # Соотношение в безопасных пределах, ничего не делаем
        return data
    
    tmp_in = None
    tmp_out = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp.write(data)
            tmp_in = tmp.name
        
        tmp_out = tmp_in + "_fixed.mp4"
        
        if ratio < MIN_SAFE_RATIO:
            # Слишком вертикальное видео, добавляем паддинги по бокам
            target_width = int(height * MIN_SAFE_RATIO)
            pad = int((target_width - width) / 2)
            vf_filter = f"pad=w={target_width}:h={height}:x={pad}:y=0:color=black"
            logger.info(f"Video aspect ratio fix: vertical {width}x{height} ratio={ratio:.3f}, adding {pad}px side padding")
        else:
            # Слишком горизонтальное видео, добавляем паддинги сверху/снизу
            target_height = int(width / MAX_SAFE_RATIO)
            pad = int((target_height - height) / 2)
            vf_filter = f"pad=w={width}:h={target_height}:x=0:y={pad}:color=black"
            logger.info(f"Video aspect ratio fix: horizontal {width}x{height} ratio={ratio:.3f}, adding {pad}px top/bottom padding")
        
        # Используем быстрый пресет и увеличиваем таймаут для больших видео
        cmd = [
            'ffmpeg', '-y', '-i', tmp_in,
            '-vf', vf_filter,
            '-c:v', 'libx264', '-crf', '24', '-preset', 'fast',
            '-c:a', 'copy',
            tmp_out
        ]
        
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode != 0:
            logger.warning(f"Video aspect ratio fix failed, using original")
            return data
        
        with open(tmp_out, 'rb') as f:
            fixed_data = f.read()
        
        logger.info(f"Video aspect ratio fixed successfully, size: {len(data)} -> {len(fixed_data)} bytes")
        return fixed_data
        
    except Exception as e:
        logger.error(f"Error fixing video aspect ratio: {e}")
        return data
    finally:
        if tmp_in and os.path.exists(tmp_in):
            os.unlink(tmp_in)
        if tmp_out and os.path.exists(tmp_out):
            os.unlink(tmp_out)

def get_min_bitrate_kbps_for_height(height):
    """Адаптивный порог минимального битрейта по высоте видео."""
    if height is None:
        return MIN_BITRATE_720P
    if height >= 1080:
        return MIN_BITRATE_1080P
    if height >= 720:
        return MIN_BITRATE_720P
    return MIN_BITRATE_480P

def validate_video(data: bytes) -> dict:
    """
    Проверяет видео на совместимость с мобильным Telegram.
    Возвращает: {"is_valid": bool, "issues": list}
    """
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name,pix_fmt,width,height',
            '-of', 'default=noprint_wrappers=1:nokey=0',
            tmp_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return {"is_valid": False, "issues": ["ffprobe failed to read video stream"]}

        issues = []
        codec_name = ""
        pix_fmt = ""
        width = 0
        height = 0

        for line in result.stdout.strip().splitlines():
            if '=' not in line:
                continue
            key, value = line.split('=', 1)
            value = value.strip()
            
            if key == 'codec_name':
                codec_name = value
                if value not in ('h264', 'hevc', 'h265') or value == 'wrapped_avframe':
                    issues.append(f"Неподдерживаемый кодек: {value}")
            elif key == 'pix_fmt':
                pix_fmt = value
                if value not in ('yuv420p', 'yuvj420p') or '10le' in value or '12le' in value or '444p' in value:
                    issues.append(f"Несовместимый формат пикселей: {value}")
            elif key == 'width':
                width = int(value) if value.isdigit() else 0
                if width > 1080:
                    issues.append(f"Ширина больше лимита: {width}px")
            elif key == 'height':
                height = int(value) if value.isdigit() else 0
                if height > 1080:
                    issues.append(f"Высота больше лимита: {height}px")

        return {
            "is_valid": len(issues) == 0,
            "issues": issues,
            "codec": codec_name,
            "pix_fmt": pix_fmt,
            "width": width,
            "height": height
        }

    except Exception as e:
        logger.error(f"Video validation error: {e}")
        return {"is_valid": False, "issues": [f"Validation error: {str(e)}"]}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def normalize_video_format(data: bytes) -> bytes:
    """
    Автоматически исправляет несовместимые видео:
    - Конвертирует в yuv420p 8bit
    - Даунскейлит до 1080px по большей стороне
    - Кодек libx264 профиль main максимальная совместимость
    - Аудио копируется как есть
    """
    validation = validate_video(data)
    if validation["is_valid"]:
        return data

    logger.info(f"Видео требует конвертации, проблемы: {', '.join(validation['issues'])}")
    
    tmp_in = None
    tmp_out = None
    try:
        start_time = time.time()
        
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp.write(data)
            tmp_in = tmp.name
        
        tmp_out = tmp_in + "_fixed.mp4"
        
        cmd = [
            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
            '-i', tmp_in,
            '-c:v', 'libx264',
            '-crf', '22',
            '-preset', 'fast',
            '-profile:v', 'main',
            '-level', '4.0',
            '-pix_fmt', 'yuv420p',
            '-vf', "scale='if(gt(iw,ih),1080,-2)':'if(gt(iw,ih),-2,1080)'",
            '-c:a', 'copy',
            '-movflags', '+faststart',
            tmp_out
        ]
        
        result = subprocess.run(cmd, capture_output=True, timeout=180)
        if result.returncode != 0:
            logger.warning(f"Не удалось сконвертировать видео, отправляю оригинал. ffmpeg ошибка: {result.stderr.decode(errors='ignore')[:200]}")
            return data
        
        with open(tmp_out, 'rb') as f:
            fixed_data = f.read()
        
        elapsed = time.time() - start_time
        logger.info(f"✅ Видео успешно конвертировано за {elapsed:.1f}с, размер: {len(data)} -> {len(fixed_data)} байт")
        
        return fixed_data
        
    except Exception as e:
        logger.error(f"Ошибка конвертации видео: {e}")
        return data
    finally:
        if tmp_in and os.path.exists(tmp_in):
            os.unlink(tmp_in)
        if tmp_out and os.path.exists(tmp_out):
            os.unlink(tmp_out)


def get_video_thumbnail(data: bytes, seek_sec: float = 2.0) -> bytes:
    """Извлекает кадр видео как JPEG bytes для vision."""
    tmp_in = None
    tmp_out = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp.write(data)
            tmp_in = tmp.name

        tmp_out = tmp_in + "_thumb.jpg"
        seek_value = max(0.0, float(seek_sec))

        cmd = [
            'ffmpeg', '-y', '-i', tmp_in,
            '-ss', str(seek_value), '-vframes', '1',
            '-vf', 'scale=512:-1',
            '-q:v', '3',
            tmp_out
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=10)

        if result.returncode != 0:
            logger.warning("ffmpeg thumbnail extraction failed")
            return None

        with open(tmp_out, 'rb') as f:
            thumb_data = f.read()

        logger.info(f"Thumbnail extracted at {seek_value:.1f}s: {len(thumb_data)} bytes")
        return thumb_data

    except Exception as e:
        logger.error(f"Thumbnail error: {e}")
        return None
    finally:
        if tmp_in and os.path.exists(tmp_in):
            os.unlink(tmp_in)
        if tmp_out and os.path.exists(tmp_out):
            os.unlink(tmp_out)


# ==================== RETRY ДЛЯ TELEGRAM ====================
async def send_with_retry(func, *args, retries=3, **kwargs):
    def _rewind_file_like(obj):
        if obj is None:
            return
        try:
            if hasattr(obj, "seek"):
                obj.seek(0)
        except Exception:
            pass

    def _rewind_payload():
        for value in args:
            _rewind_file_like(value)
        for key in ("photo", "video", "animation", "document", "thumbnail"):
            _rewind_file_like(kwargs.get(key))
        media = kwargs.get("media")
        if isinstance(media, list):
            for item in media:
                media_obj = getattr(item, "media", None)
                _rewind_file_like(media_obj)

    for attempt in range(retries):
        try:
            _rewind_payload()
            return await func(*args, **kwargs)
        except Exception as e:
            if attempt == retries - 1:
                raise
            logger.warning(f"Telegram send failed (attempt {attempt + 1}/{retries}): {e}")
            await asyncio.sleep(2)


def _fit_photo_size_for_telegram(image_data: bytes, max_size: int = 10 * 1024 * 1024) -> bytes:
    """
    Telegram sendPhoto hard-limit is 10 MB.
    If payload is larger, flatten to JPEG and reduce quality/resolution gradually.
    """
    if not image_data or len(image_data) <= max_size:
        return image_data

    try:
        img = Image.open(BytesIO(image_data))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        # Try quality-only first.
        for quality in (92, 88, 84, 80, 76, 72, 68):
            out = BytesIO()
            img.save(out, format="JPEG", quality=quality, optimize=True)
            candidate = out.getvalue()
            if len(candidate) <= max_size:
                logger.info(f"Photo recompressed to fit Telegram limit: {len(candidate)} bytes (q={quality})")
                return candidate

        # If still too large, downscale progressively.
        width, height = img.size
        for scale in (0.95, 0.9, 0.85, 0.8, 0.75):
            new_w = max(1, int(width * scale))
            new_h = max(1, int(height * scale))
            resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            out = BytesIO()
            resized.save(out, format="JPEG", quality=76, optimize=True)
            candidate = out.getvalue()
            if len(candidate) <= max_size:
                logger.info(
                    "Photo downscaled to fit Telegram limit: "
                    f"{len(candidate)} bytes ({width}x{height} -> {new_w}x{new_h})"
                )
                return candidate
    except Exception as e:
        logger.warning(f"Could not fit photo size for Telegram: {e}")

    # Keep original on failure; sender will still handle/report.
    return image_data

# ==================== ТЕГИ ====================
def extract_tags(item):
    raw_tags = []

    civitai_tags = item.get("tags", [])
    if civitai_tags:
        for t in civitai_tags:
            name = t.get("name", "") if isinstance(t, dict) else str(t)
            if name:
                raw_tags.append(name)
        logger.debug(f"CivitAI tags found: {len(raw_tags)}")

    if not raw_tags:
        prompt = item.get("meta", {}).get("prompt", "") if item.get("meta") else ""
        if prompt:
            tokens = re.split(r"[,\(\)\[\]|<>]+", prompt)
            for token in tokens:
                token = token.strip()
                if token:
                    raw_tags.append(token)
            logger.debug(f"Parsed {len(raw_tags)} tokens from meta.prompt")
        else:
            logger.debug("No tags and no prompt available")

    return clean_tags(raw_tags)


# ==================== CIVITAI API ====================
def _request_with_backoff(url, params, headers, max_retries=3):
    last_error = None
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            if r.status_code == 429:
                wait = 2 ** attempt * 7
                logger.warning(f"Rate limited (429), waiting {wait}s before retry {attempt + 1}/{max_retries}")
                time.sleep(wait)
                continue
            if r.status_code == 400:
                return r
            r.raise_for_status()
            return r
        except requests.exceptions.Timeout:
            last_error = "Timeout"
            logger.warning(f"Timeout on attempt {attempt + 1}/{max_retries}")
            if attempt < max_retries - 1:
                time.sleep(5 + attempt * 3)
        except requests.exceptions.HTTPError as e:
            last_error = f"HTTP {r.status_code}"
            if r.status_code >= 500:
                logger.warning(f"Server error {r.status_code}, retry {attempt + 1}/{max_retries}")
                time.sleep(5 + (2 ** attempt) * 5)
            else:
                raise
        except Exception as e:
            last_error = str(e)
            logger.error(f"Request error: {e}")
            if attempt < max_retries - 1:
                time.sleep(5)
    logger.warning(f"All {max_retries} attempts failed, last error: {last_error}")
    return None

def _is_x_or_xxx(nsfw_level):
    """Проверяет, что nsfwLevel соответствует X/XXX (или числовому эквиваленту)."""
    if isinstance(nsfw_level, str):
        value = nsfw_level.strip().lower()
        return value in {"x", "xxx"}
    if isinstance(nsfw_level, (int, float)):
        # На старых/внутренних форматах высокий уровень соответствует explicit.
        return nsfw_level >= 8
    return False

def _is_mature_or_higher(nsfw_level):
    """Более мягкий фильтр: Mature/X/XXX (для случаев, когда X мало в выдаче)."""
    if isinstance(nsfw_level, str):
        value = nsfw_level.strip().lower()
        return value in {"mature", "x", "xxx"}
    if isinstance(nsfw_level, (int, float)):
        # Консервативный порог для "Mature и выше" на числовых форматах.
        return nsfw_level >= 4
    return False

def _to_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default

def _extract_civitai_likes(item):
    """
    Пытается достать реакцию из разных версий/вариантов полей CivitAI.
    Возвращает максимум найденного, чтобы не занизить популярность поста.
    """
    stats = item.get("stats") or {}
    stats_total = 0
    if isinstance(stats, dict):
        for key, value in stats.items():
            key_lower = str(key).lower()
            if "count" in key_lower:
                stats_total += _to_int(value, 0)

    candidates = [
        stats.get("likeCount"),
        stats.get("heartCount"),
        stats.get("reactionCount"),
        stats.get("favoriteCount"),
        stats_total,
        item.get("likeCount"),
        item.get("heartCount"),
        item.get("reactionCount"),
    ]
    numeric = [_to_int(v, 0) for v in candidates]
    return max(numeric) if numeric else 0

def fetch_civitai(max_pages: int = 5):
    # Используем browsingLevel=31 для максимального охвата + nsfw=X для explicit.
    # Newest проверяем первым для более быстрого нахождения свежего контента.
    variations = [
        {"browsingLevel": 31, "nsfw": "X", "sort": "Newest"},
        {"browsingLevel": 31, "nsfw": "X", "sort": "Newest", "period": "Week"},
        {"browsingLevel": 31, "nsfw": "X", "sort": "Newest", "period": "Month"},
        {"browsingLevel": 31, "nsfw": "X", "sort": "Most Reactions", "period": "Day"},
        {"browsingLevel": 31, "nsfw": "X", "sort": "Most Reactions", "period": "Week"},
        {"browsingLevel": 31, "nsfw": "X", "sort": "Most Reactions", "period": "Month"},
    ]

    headers = {"Authorization": f"Bearer {CIVITAI_API_KEY}"} if CIVITAI_API_KEY else {}
    max_pages = max(1, int(max_pages))
    
    consecutive_errors = 0
    total_errors = 0

    for base_params in variations:
        all_items = []
        seen_ids = set()
        next_page_url = None
        
        # CivitAI paginates через metadata.nextPage (cursor-based).
        for page in range(1, max_pages + 1):
            request_url = next_page_url or "https://civitai.com/api/v1/images"
            params = None if next_page_url else {**base_params, "limit": 100}
            
            try:
                r = _request_with_backoff(
                    request_url,
                    params=params,
                    headers=headers
                )
                if r is None:
                    logger.warning(f"CivitAI page {page}: no response")
                    consecutive_errors += 1
                    total_errors += 1
                    
                    # Если больше 2 ошибок подряд - прекращаем пытаться
                    if consecutive_errors >= 2:
                        logger.warning("Too many consecutive errors, stopping CivitAI requests")
                        break
                    
                    # Задержка перед следующей попыткой
                    time.sleep(3)
                    continue
                
                consecutive_errors = 0

                # Handle 400 Bad Request
                if r.status_code == 400:
                    logger.debug(f"CivitAI page {page}: skipping invalid params {params}")
                    continue

                data = r.json()
                items = data.get("items", [])
                
                if not items:
                    logger.debug(f"CivitAI page {page}: no items")
                    continue

                for item in items:
                    item_id = item.get("id")
                    if item_id in seen_ids:
                        continue
                    seen_ids.add(item_id)
                    all_items.append(item)
                logger.info(f"CivitAI page {page}: got {len(items)} items (total: {len(all_items)})")

                metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
                next_page_url = metadata.get("nextPage")
                if not next_page_url:
                    break

            except Exception as e:
                logger.error(f"CivitAI page {page} error: {e}")
                continue

        if not all_items:
            logger.info(f"No items for params {base_params}")
            continue

        items = all_items
        period = base_params.get("period", "N/A")
        logger.info(
            f"Got {len(items)} items total "
            f"(browsingLevel={base_params['browsingLevel']}, sort={base_params['sort']}, period={period})"
        )
        precomputed_likes = [_extract_civitai_likes(i) for i in items]
        likes_filter_enabled = any(v > 0 for v in precomputed_likes)
        if not likes_filter_enabled:
            logger.warning(
                "CivitAI reactions unavailable (all zero). "
                "Likes filter will be disabled for this batch."
            )

        erotic_items = []
        skipped_nsfw = 0
        skipped_blacklist = 0
        skipped_likes = 0
        accepted_mature = 0
        nsfw_distribution = {}
        likes_observed = []
        
        # Автоматически определяем есть ли вообще X контент в выдаче
        x_count = 0
        mature_count = 0
        soft_count = 0
        none_count = 0
        
        for debug_item in items:
            debug_nsfw = debug_item.get("nsfwLevel")
            if _is_x_or_xxx(debug_nsfw):
                x_count +=1
            elif _is_mature_or_higher(debug_nsfw):
                mature_count +=1
            else:
                if str(debug_nsfw).strip().lower() == "soft":
                    soft_count +=1
                else:
                    none_count +=1
        
        # Автоматический фоллбек: если X контента меньше 2% от всего - включаем Mature
        auto_enable_mature = (x_count / len(items)) < 0.02
        if auto_enable_mature and not ALLOW_MATURE_FALLBACK:
            logger.warning(f"⚠️ CivitAI X контент почти исчез ({x_count}/{len(items)}), автоматически включаем Mature fallback")
        
        for item in items:
            try:
                nsfw_level = item.get("nsfwLevel")
                nsfw_key = str(nsfw_level).strip() if nsfw_level is not None else "None"
                nsfw_distribution[nsfw_key] = nsfw_distribution.get(nsfw_key, 0) + 1

                is_allowed_nsfw = _is_x_or_xxx(nsfw_level)
                if not is_allowed_nsfw and (ALLOW_MATURE_FALLBACK or auto_enable_mature) and _is_mature_or_higher(nsfw_level):
                    is_allowed_nsfw = True
                    accepted_mature += 1

                if not is_allowed_nsfw:
                    skipped_nsfw += 1
                    continue

                tags = extract_tags(item)

                if has_blacklisted(tags):
                    skipped_blacklist += 1
                    continue

                stats_data = item.get("stats", {})
                likes = _extract_civitai_likes(item)
                likes_observed.append(likes)

                if likes_filter_enabled and likes < MIN_CIVITAI_LIKES:
                    skipped_likes += 1
                    continue

                erotic_items.append({
                    "id":      f"civitai_{item['id']}",
                    "url":     item.get("url", ""),
                    "tags":    tags[:15],
                    "likes":   likes,
                    "rating":  nsfw_level,
                    "post_id": item.get("postId"),
                    "mime":    (item.get("mimeType") or "").lower(),
                    "createdAt": item.get("createdAt"),
                    "source":  "civitai",
                })

            except Exception as e:
                logger.error(f"Error processing item {item.get('id')}: {e}")
                continue

        if erotic_items:
            logger.info(f"Found {len(erotic_items)} posts from CivitAI (mature_fallback_used={accepted_mature})")
            return erotic_items

        logger.info(
            f"No suitable posts: skipped_nsfw={skipped_nsfw}, "
            f"skipped_blacklist={skipped_blacklist}, skipped_likes={skipped_likes}, "
            f"civitai_min_likes={MIN_CIVITAI_LIKES}, "
            f"allow_mature_fallback={ALLOW_MATURE_FALLBACK}, "
            f"likes_filter_enabled={likes_filter_enabled}"
        )
        logger.info(f"CivitAI nsfw distribution: {nsfw_distribution}")
        if likes_observed:
            likes_sorted = sorted(likes_observed)
            median_like = likes_sorted[len(likes_sorted) // 2]
            logger.info(
                f"CivitAI likes diagnostics: min={likes_sorted[0]}, median={median_like}, max={likes_sorted[-1]}"
            )

        # Если CivitAI полностью лежит - фоллбек на Rule34
        if total_errors >= 4 and not erotic_items:
            logger.warning("⚠️ CivitAI is completely unreachable, falling back to Rule34")
            try:
                return fetch_rule34(limit=150, content_type="mixed", media_type="any")
            except Exception as e:
                logger.error(f"Rule34 fallback failed: {e}")
    
    return []

VIDEO_EXTENSIONS = (".mp4", ".webm")
GIF_EXTENSION = ".gif"

def _url_path(url: str) -> str:
    try:
        return urlparse(url).path.lower()
    except Exception:
        return (url or "").lower()

def _is_video(url: str) -> bool:
    return _url_path(url).endswith(VIDEO_EXTENSIONS)

def _is_gif(url: str) -> bool:
    return _url_path(url).endswith(GIF_EXTENSION)

def _is_video_item(item: dict) -> bool:
    mime = (item.get("mime") or "").lower()
    if mime.startswith("video/"):
        return True
    # GIF отправляем отдельно через send_animation
    if mime == "image/gif":
        return False
    return _is_video(item.get("url", ""))


def _is_photo_item(item: dict) -> bool:
    mime = (item.get("mime") or "").lower()
    if mime == "image/gif" or _is_gif(item.get("url", "")):
        return False
    return not _is_video_item(item)


def _collect_pack_candidates(seed_item: dict, limit: int) -> list[dict]:
    source = str(seed_item.get("source") or "").strip().lower()
    if source not in ("civitai", "rule34") or limit <= 0:
        return []

    try:
        if source == "civitai":
            items = fetch_civitai(max_pages=2)
        else:
            items = fetch_rule34(limit=100, content_type="mixed", media_type="image")
    except Exception as e:
        logger.warning(f"Could not fetch candidates for image pack: {e}")
        return []

    excluded_ids = set(posted_ids)
    excluded_ids.add(seed_item.get("id"))

    fresh = [
        i for i in items
        if i.get("id") not in excluded_ids
        and _is_photo_item(i)
        and not has_blacklisted(i.get("tags", []))
    ]

    # Берем более популярные элементы, чтобы пак был релевантнее.
    fresh.sort(key=lambda x: max(0, int(x.get("likes", 0))), reverse=True)
    return fresh[:limit]

def _pick_by_content_type(fresh):
    """70/30 видео или фото. Если нужного типа нет — берём что есть."""
    content_type = "video" if random.random() < 0.7 else "image"
    logger.info(f"Content type selection: {content_type}")

    if content_type == 'video':
        typed = [i for i in fresh if _is_video_item(i)]
        fallback = [i for i in fresh if not _is_video_item(i)]
    else:
        typed = [i for i in fresh if not _is_video_item(i)]
        fallback = [i for i in fresh if _is_video_item(i)]

    logger.info(f"Items of selected type ({content_type}): {len(typed)}")

    if typed:
        return weighted_choice(typed)

    fallback_type = 'video' if content_type == 'image' else 'image'
    logger.info(f"No {content_type} items, falling back to {fallback_type}: {len(fallback)}")
    return weighted_choice(fallback) if fallback else None


def fetch_and_pick():
    if TEST_CIVITAI_ONLY:
        source = "civitai"
        logger.info("Source selection: CivitAI only (TEST_CIVITAI_ONLY=True)")
        items = fetch_civitai()
        if not items:
            logger.warning("TEST_CIVITAI_ONLY=True and CivitAI returned nothing")
            return None
    else:
        # Возвращаем монетку 50/50 между источниками.
        source = random.choice(["civitai", "rule34"])
        logger.info(f"Source selection: {source} (50/50 coin)")

        if source == "civitai":
            items = fetch_civitai()
            if not items:
                logger.warning("CivitAI returned nothing, falling back to Rule34")
                source = "rule34"
                content_type = get_next_content_type()
                media_type = get_next_media_type()
                logger.info(f"Rule34 content_type={content_type}, media_type={media_type}")
                items = fetch_rule34(limit=100, content_type=content_type, media_type=media_type)
        else:
            content_type = get_next_content_type()
            media_type = get_next_media_type()
            logger.info(f"Rule34 content_type={content_type}, media_type={media_type}")
            items = fetch_rule34(limit=100, content_type=content_type, media_type=media_type)
            if not items:
                logger.warning("Rule34 returned nothing, falling back to CivitAI")
                source = "civitai"
                items = fetch_civitai()

    if not items:
        logger.warning("No items found from any source")
        return None

    fresh = [i for i in items if i["id"] not in posted_ids]
    # Фильтруем blacklist для всех источников (CivitAI уже фильтрует внутри fetch_civitai)
    fresh = [i for i in fresh if not has_blacklisted(i["tags"])]
    logger.info(f"Fresh items: {len(fresh)} out of {len(items)} (source: {source})")

    if not fresh:
        logger.info("No fresh items")
        return None

    if source == "rule34":
        selected = _pick_by_content_type(fresh)
    else:
        content_type = "video" if random.random() < 0.7 else "image"
        logger.info(f"Content type selection (civitai): {content_type}")

        if content_type == 'image':
            type_items = [i for i in fresh if not _is_video_item(i)]
            fallback_items = [i for i in fresh if _is_video_item(i)]
        else:
            type_items = [i for i in fresh if _is_video_item(i)]
            fallback_items = [i for i in fresh if not _is_video_item(i)]

        logger.info(f"Items of selected type ({content_type}): {len(type_items)}")

        if not type_items:
            fallback_type = 'video' if content_type == 'image' else 'image'
            logger.info(f"No {content_type} items found, trying {fallback_type}: {len(fallback_items)}")
            type_items = fallback_items

        if not type_items:
            logger.info("No suitable items found")
            return None

        selected = weighted_choice(type_items)

    if not selected:
        logger.info("No suitable items found after type filtering")
        return None

    logger.info(
        f"Selected: {selected['id']} "
        f"(source:{source}, rating:{selected['rating']}, "
        f"likes:{selected['likes']}, tags:{len(selected['tags'])})"
    )
    return selected


def weighted_choice(items):
    if not items:
        return None

    weights = [max(1, item["likes"]) for item in items]
    selected = random.choices(items, weights=weights, k=1)[0]

    logger.info(
        f"Weighted selection: {selected['id']} "
        f"(likes:{selected['likes']})"
    )

    return selected


def detect_content_type_by_tags(item):
    ai_tags = {
        "ai", "ai_art", "ai_video", "ai_generated", "ai_animation",
        "stable_diffusion", "novelai", "midjourney", "generated",
        "synthetic", "machine_learning", "neural_network"
    }
    three_d_tags = {
        "3d", "3d_(artwork)", "3d_video", "3d_animation", "3d_model",
        "blender", "source_filmmaker", "sfm", "daz3d", "koikatsu",
        "honey_select", "mmd", "3d_render"
    }

    tags = item.get("tags", [])
    has_ai = any(str(t).lower() in ai_tags for t in tags)
    has_3d = any(str(t).lower() in three_d_tags for t in tags)

    if has_3d and not has_ai:
        return "3d"
    if has_ai and not has_3d:
        return "ai"
    if has_ai and has_3d:
        return "ai"
    return "ai" if item.get("source") == "civitai" else "3d"


def build_caption_from_item(item, width=None, height=None, file_size=None):
    return generate_caption(
        tags=item.get("tags", []),
        rating=item.get("rating"),
        likes=item.get("likes", 0),
        image_data=None,
        image_url=item.get("url"),
        watermark=WATERMARK_TEXT,
        suggestion="💬 Предложка: @Haillord",
        content_type=detect_content_type_by_tags(item),
        width=width,
        height=height,
        file_size=file_size,
        date=item.get("createdAt"),
    )


def _build_pack_caption_meta(image_pack: list[dict]) -> dict:
    """
    Агрегирует метаданные для общего caption альбома.
    Приоритет:
    - теги: общие по всем + топ уникальных
    - likes: медиана по паку
    - rating/date: от первого элемента (seed), чтобы сохранить контекст источника
    """
    if not image_pack:
        return {"tags": [], "likes": 0, "rating": None, "date": None}

    items = [entry.get("item", {}) for entry in image_pack if isinstance(entry, dict)]
    items = [i for i in items if isinstance(i, dict)]
    if not items:
        return {"tags": [], "likes": 0, "rating": None, "date": None}

    normalized_lists = []
    for item in items:
        tags = clean_tags(item.get("tags", []) or [])
        normalized_lists.append(tags)

    common_tags = set(normalized_lists[0]) if normalized_lists else set()
    for tag_list in normalized_lists[1:]:
        common_tags &= set(tag_list)

    tag_scores = {}
    for item in items:
        likes = max(0, int(item.get("likes", 0) or 0))
        for tag in clean_tags(item.get("tags", []) or []):
            tag_scores[tag] = tag_scores.get(tag, 0) + (likes + 1)

    shared_sorted = sorted(common_tags, key=lambda t: tag_scores.get(t, 0), reverse=True)
    unique_sorted = sorted(
        [t for t in tag_scores.keys() if t not in common_tags],
        key=lambda t: tag_scores.get(t, 0),
        reverse=True
    )

    # Даем caption-генератору компактный, но информативный набор тегов.
    merged_tags = (shared_sorted[:10] + unique_sorted[:12])[:18]

    likes_values = sorted(max(0, int(i.get("likes", 0) or 0)) for i in items)
    likes_median = likes_values[len(likes_values) // 2] if likes_values else 0

    seed = items[0]
    return {
        "tags": merged_tags,
        "likes": likes_median,
        "rating": seed.get("rating"),
        "date": seed.get("createdAt"),
    }


def _apply_watermark_for_image_bytes(image_data: bytes, url: str) -> bytes:
    if not image_data or not should_add_watermark(url or ""):
        return image_data
    try:
        opacity = max(0.0, min(1.0, WATERMARK_IMAGE_OPACITY))
        return add_watermark(
            image_data=image_data,
            text=WATERMARK_IMAGE_TEXT,
            opacity=opacity,
        )
    except Exception as e:
        logger.warning(f"Watermark apply failed, using original image: {e}")
        return image_data


def _parse_admin_command(text: str):
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return None, None, None

    lines = raw.splitlines()
    head = lines[0].strip()
    parts = head.split(maxsplit=2)
    cmd = parts[0].lower()
    draft_id = parts[1].strip() if len(parts) >= 2 else ""
    inline_caption = parts[2].strip() if len(parts) >= 3 else ""
    extra_caption = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
    custom_caption = extra_caption or inline_caption or ""
    return cmd, draft_id, custom_caption


async def send_review_instructions(bot: Bot, chat_id: str, draft_id: str):
    text = (
        f"🧪 Черновик готов: <code>{draft_id}</code>\n"
        "Команды:\n"
        "<code>/approve DRAFT_ID</code> — опубликовать как есть\n"
        "<code>/approve DRAFT_ID\\nТВОЙ_ТЕКСТ</code> — опубликовать с твоим текстом\n"
        "<code>/reject DRAFT_ID</code> — отклонить"
    )
    await send_with_retry(bot.send_message, chat_id=chat_id, text=text, parse_mode="HTML")


async def send_draft_to_admin(bot: Bot, item: dict, caption: str):
    chat_id = ADMIN_USER_ID
    if not chat_id:
        logger.error("REVIEW_MODE requires ADMIN_USER_ID")
        return

    is_gif = _is_gif(item.get("url", "")) or (item.get("mime") or "").lower() == "image/gif"
    is_video = _is_video_item(item) and not is_gif

    draft_caption = f"[DRAFT]\n{caption}"
    if len(draft_caption) > 1024:
        draft_caption = draft_caption[:1021] + "..."

    if is_video:
        await send_with_retry(
            bot.send_video,
            chat_id=chat_id,
            video=item.get("url"),
            caption=draft_caption,
            parse_mode="HTML",
            supports_streaming=True,
            write_timeout=60,
            read_timeout=60,
        )
    elif is_gif:
        await send_with_retry(
            bot.send_animation,
            chat_id=chat_id,
            animation=item.get("url"),
            caption=draft_caption,
            parse_mode="HTML",
            write_timeout=60,
            read_timeout=60,
        )
    else:
        try:
            r = requests.get(item.get("url"), timeout=60)
            r.raise_for_status()
            image_data = _apply_watermark_for_image_bytes(r.content, item.get("url", ""))
            image_data = _fit_photo_size_for_telegram(image_data)
            photo_io = BytesIO(image_data)
            photo_io.name = "draft_image.jpg"
            await send_with_retry(
                bot.send_photo,
                chat_id=chat_id,
                photo=photo_io,
                caption=draft_caption,
                parse_mode="HTML",
                write_timeout=60,
                read_timeout=60,
            )
        except Exception as e:
            logger.warning(f"Draft watermark flow failed, fallback to URL send: {e}")
            await send_with_retry(
                bot.send_photo,
                chat_id=chat_id,
                photo=item.get("url"),
                caption=draft_caption,
                parse_mode="HTML",
                write_timeout=60,
                read_timeout=60,
            )

    await send_review_instructions(bot, chat_id, item["id"])


async def publish_item_to_channel(bot: Bot, item: dict, caption: str):
    is_gif = _is_gif(item.get("url", "")) or (item.get("mime") or "").lower() == "image/gif"
    is_video = _is_video_item(item) and not is_gif

    if is_video:
        await send_with_retry(
            bot.send_video,
            chat_id=TELEGRAM_CHANNEL_ID,
            video=item.get("url"),
            caption=caption,
            parse_mode="HTML",
            supports_streaming=True,
            write_timeout=60,
            read_timeout=60,
        )
    elif is_gif:
        await send_with_retry(
            bot.send_animation,
            chat_id=TELEGRAM_CHANNEL_ID,
            animation=item.get("url"),
            caption=caption,
            parse_mode="HTML",
            write_timeout=60,
            read_timeout=60,
        )
    else:
        try:
            r = requests.get(item.get("url"), timeout=60)
            r.raise_for_status()
            image_data = _apply_watermark_for_image_bytes(r.content, item.get("url", ""))
            image_data = _fit_photo_size_for_telegram(image_data)
            photo_io = BytesIO(image_data)
            photo_io.name = "image.jpg"
            await send_with_retry(
                bot.send_photo,
                chat_id=TELEGRAM_CHANNEL_ID,
                photo=photo_io,
                caption=caption,
                parse_mode="HTML",
                write_timeout=60,
                read_timeout=60,
            )
        except Exception as e:
            logger.warning(f"Publish watermark flow failed, fallback to URL send: {e}")
            await send_with_retry(
                bot.send_photo,
                chat_id=TELEGRAM_CHANNEL_ID,
                photo=item.get("url"),
                caption=caption,
                parse_mode="HTML",
                write_timeout=60,
                read_timeout=60,
            )


async def process_admin_updates(bot: Bot):
    if not ADMIN_USER_ID:
        return None

    last_update_id = int(review_state.get("last_update_id", 0))
    try:
        updates = await bot.get_updates(offset=last_update_id + 1, limit=50, timeout=0)
    except Exception as e:
        logger.warning(f"Could not fetch admin updates: {e}")
        return None

    action = None
    for upd in updates:
        review_state["last_update_id"] = max(int(review_state.get("last_update_id", 0)), int(upd.update_id))
        msg = getattr(upd, "message", None)
        if not msg or not msg.text:
            continue
        from_user = getattr(msg, "from_user", None)
        if not from_user or str(from_user.id) != ADMIN_USER_ID:
            continue

        cmd, draft_id, custom_caption = _parse_admin_command(msg.text)
        if cmd not in ("/approve", "/reject"):
            continue
        action = {"cmd": cmd, "draft_id": draft_id, "caption": custom_caption}

    save_review_state()
    return action

# ==================== MAIN ====================
async def main():
    global posted_ids, posted_hashes, content_state, pending_draft, review_state
    posted_ids    = set(_state.get("posted_ids.json", []))
    posted_hashes = set(_state.get("posted_hashes.json", []))
    content_state = _state.get("content_state.json", {"last_type": "3d", "last_media": "video"})
    pending_draft = _state.get("pending_draft.json", {})
    review_state  = _state.get("review_state.json", {"last_update_id": 0})

    run_started = time.time()
    run_metrics = {
        "runs": 1,
        "posted": 0,
        "source_civitai_selected": 0,
        "source_rule34_selected": 0,
        "skip_no_item": 0,
        "skip_download_error": 0,
        "skip_file_too_large": 0,
        "skip_small_image": 0,
        "skip_bad_video_duration": 0,
        "skip_low_video_quality": 0,
        "skip_duplicate_hash": 0,
        "send_errors": 0,
    }
    stats_flushed = False

    def flush_stats_once():
        nonlocal stats_flushed
        if stats_flushed:
            return
        run_metrics["runtime_sec"] = round(time.time() - run_started, 2)
        record_run_stats(run_metrics)
        stats_flushed = True

    if not TELEGRAM_BOT_TOKEN:
        logger.error("No TELEGRAM_BOT_TOKEN found!")
        flush_stats_once()
        return

    if not CIVITAI_API_KEY:
        logger.error("No CIVITAI_API_KEY found!")
        flush_stats_once()
        return

    logger.info("=" * 50)
    logger.info("Starting ErosLab Bot")
    logger.info(f"Channel: {TELEGRAM_CHANNEL_ID}")
    logger.info(f"Min likes: {MIN_LIKES}")
    logger.info(f"Min image size: {MIN_IMAGE_SIZE}x{MIN_IMAGE_SIZE}")
    logger.info(
        "Video QoS: "
        f"enabled={ENABLE_VIDEO_QOS}, "
        f"min_bitrate_480p={MIN_BITRATE_480P}, "
        f"min_bitrate_720p={MIN_BITRATE_720P}, "
        f"min_bitrate_1080p={MIN_BITRATE_1080P}"
    )
    logger.info("=" * 50)

    target_chat_id = TELEGRAM_CHANNEL_ID

    if REVIEW_MODE:
        if not ADMIN_USER_ID:
            logger.error("REVIEW_MODE enabled but ADMIN_USER_ID is empty")
            flush_stats_once()
            return

        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        action = await process_admin_updates(bot)

        if pending_draft and action:
            pd = pending_draft
            pd_id = str(pd.get("id", ""))
            if action.get("draft_id") and action["draft_id"] != pd_id:
                await send_with_retry(
                    bot.send_message,
                    chat_id=ADMIN_USER_ID,
                    text=f"Черновик <code>{action['draft_id']}</code> не найден. Текущий: <code>{pd_id}</code>",
                    parse_mode="HTML",
                )
            elif action["cmd"] == "/reject":
                posted_ids.add(pd_id)
                pending_draft.clear()
                save_pending_draft()
                save_all()
                await send_with_retry(
                    bot.send_message,
                    chat_id=ADMIN_USER_ID,
                    text=f"Отклонено: <code>{pd_id}</code>",
                    parse_mode="HTML",
                )
                flush_stats_once()
                return
            elif action["cmd"] == "/approve":
                final_caption = action.get("caption") or pd.get("caption", "")
                try:
                    await publish_item_to_channel(bot, pd["item"], final_caption)
                    posted_ids.add(pd_id)
                    save_all()
                    run_metrics["posted"] += 1
                    await send_with_retry(
                        bot.send_message,
                        chat_id=ADMIN_USER_ID,
                        text=f"Опубликовано: <code>{pd_id}</code>",
                        parse_mode="HTML",
                    )
                    logger.info(f"Successfully posted from review: {pd_id}")
                except Exception as e:
                    run_metrics["send_errors"] += 1
                    logger.error(f"Review publish failed: {e}")
                finally:
                    pending_draft.clear()
                    save_pending_draft()
                    flush_stats_once()
                return

        if pending_draft:
            await send_with_retry(
                bot.send_message,
                chat_id=ADMIN_USER_ID,
                text=(
                    f"Есть ожидающий черновик: <code>{pending_draft.get('id')}</code>\n"
                    "Отправь /approve ID или /reject ID"
                ),
                parse_mode="HTML",
            )
            flush_stats_once()
            return

        item = fetch_and_pick()
        if not item:
            logger.info("No item for review draft")
            run_metrics["skip_no_item"] += 1
            flush_stats_once()
            return

        draft_caption = build_caption_from_item(item)
        pending_draft.clear()
        pending_draft.update({
            "id": item["id"],
            "item": item,
            "caption": draft_caption,
            "created_at": datetime.utcnow().isoformat() + "Z",
        })
        save_pending_draft()
        await send_draft_to_admin(bot, item, draft_caption)
        logger.info(f"Draft sent to admin: {item['id']}")
        flush_stats_once()
        return

    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
    MAX_ATTEMPTS  = 10

    for attempt in range(MAX_ATTEMPTS):
        item = fetch_and_pick()

        if not item:
            logger.info("No more fresh posts available")
            run_metrics["skip_no_item"] += 1
            flush_stats_once()
            return

        source_key = f"source_{item.get('source', 'unknown')}_selected"
        run_metrics[source_key] = run_metrics.get(source_key, 0) + 1

        try:
            logger.info(f"Downloading: {item['url']}")
            r = requests.get(item["url"], timeout=60)
            r.raise_for_status()
            data = r.content
            logger.info(f"Downloaded {len(data)} bytes")
            download_content_type = (r.headers.get("Content-Type") or "").lower()
        except Exception as e:
            logger.error(f"Download Error: {e}")
            run_metrics["skip_download_error"] += 1
            posted_ids.add(item["id"])
            save_all()
            continue

        if len(data) > MAX_FILE_SIZE:
            logger.warning(f"File too large ({len(data)} bytes > 50MB), skipping")
            run_metrics["skip_file_too_large"] += 1
            posted_ids.add(item["id"])
            save_all()
            continue

        item_mime = (item.get("mime") or "").lower()
        is_gif = (
            "image/gif" in download_content_type
            or item_mime == "image/gif"
            or _is_gif(item["url"])
        )
        is_video = (
            (download_content_type.startswith("video/") or item_mime.startswith("video/") or _is_video(item["url"]))
            and not is_gif
        )

        # Получаем технические данные для caption
        img_width = None
        img_height = None
        file_size_bytes = len(data)

        if not is_video:
            if not check_media_size(data, item["url"]):
                logger.warning("Image size too small, skipping")
                run_metrics["skip_small_image"] += 1
                posted_ids.add(item["id"])
                save_all()
                continue
            # Получаем размеры изображения
            try:
                img = Image.open(BytesIO(data))
                img_width, img_height = img.size
                logger.info(f"Image dimensions: {img_width}x{img_height}")
            except Exception as e:
                logger.warning(f"Could not get image dimensions: {e}")
        else:
            duration = get_video_duration(data)
            if duration < 0.5 or duration > 60:
                logger.warning(f"Video too short ({duration:.2f}s) or too long, skipping")
                run_metrics["skip_bad_video_duration"] += 1
                posted_ids.add(item["id"])
                save_all()
                continue
            logger.info(f"Video duration: {duration:.2f}s")

            # Получаем размер кадра для caption и QoS-фильтра
            img_width, img_height = get_video_dimensions(data)

            avg_bitrate_kbps = (len(data) * 8) / duration / 1000 if duration > 0 else 0
            min_bitrate_kbps = get_min_bitrate_kbps_for_height(img_height)
            logger.info(
                "Video QoS stats: "
                f"resolution={img_width}x{img_height}, "
                f"avg_bitrate={avg_bitrate_kbps:.0f} kbps, "
                f"required_min={min_bitrate_kbps} kbps"
            )

            if ENABLE_VIDEO_QOS and avg_bitrate_kbps < min_bitrate_kbps:
                logger.warning(
                    f"Skipping low-quality video: {avg_bitrate_kbps:.0f} < {min_bitrate_kbps} kbps"
                )
                run_metrics["skip_low_video_quality"] += 1
                posted_ids.add(item["id"])
                save_all()
                continue
            
            # Скипаем видео с экстремальными соотношениями сторон
            if img_width and img_height:
                ratio = img_width / img_height
                if ratio < 0.4 or ratio > 4.0:
                    logger.warning(f"Skipping extreme aspect ratio: {img_width}x{img_height} ratio={ratio:.3f}")
                    run_metrics["skip_bad_video_ratio"] = run_metrics.get("skip_bad_video_ratio", 0) + 1
                    posted_ids.add(item["id"])
                    save_all()
                    continue
            
            # ✅ Автоматическая проверка и исправление формата видео для мобильного Telegram
            data = normalize_video_format(data)

            # Добавляем водяной знак ФИНАЛЬНЫМ ШАГОМ после всех конвертаций
            if should_add_watermark(item.get("url", "")):
                try:
                    opacity = max(0.0, min(1.0, WATERMARK_IMAGE_OPACITY))
                    data = add_watermark_to_video(
                        video_data=data,
                        text=WATERMARK_IMAGE_TEXT,
                        opacity=opacity,
                    )
                except Exception as e:
                    logger.warning(f"Video watermark apply failed, using original video: {e}")

        img_hash = hashlib.sha256(data).hexdigest()
        if img_hash in posted_hashes:
            logger.warning("Duplicate content detected")
            run_metrics["skip_duplicate_hash"] += 1
            posted_ids.add(item["id"])
            save_all()
            continue

        # Добавляем вотермарк для GIF
        if is_gif and should_add_watermark(item.get("url", "")):
            try:
                opacity = max(0.0, min(1.0, WATERMARK_IMAGE_OPACITY))
                data = add_watermark_to_video(
                    video_data=data,
                    text=WATERMARK_IMAGE_TEXT,
                    opacity=opacity,
                )
            except Exception as e:
                logger.warning(f"GIF watermark apply failed, using original: {e}")

        break
    else:
        logger.error(f"No suitable post found after {MAX_ATTEMPTS} attempts")
        flush_stats_once()
        return

    # ========== СБОРКА ПАКА ФОТО (только CivitAI/Rule34) ==========
    image_pack = [{"item": item, "data": data, "hash": img_hash}]
    use_image_pack = False

    if IMAGE_PACK_ENABLED and _is_photo_item(item) and item.get("source") in ("civitai", "rule34") and IMAGE_PACK_SIZE > 1:
        pack_hashes = {img_hash}
        candidates = _collect_pack_candidates(item, IMAGE_PACK_CANDIDATE_POOL)
        logger.info(f"Image pack candidates collected: {len(candidates)}")

        for candidate in candidates:
            if len(image_pack) >= IMAGE_PACK_SIZE:
                break

            try:
                r_extra = requests.get(candidate["url"], timeout=60)
                r_extra.raise_for_status()
                extra_data = r_extra.content
                extra_ctype = (r_extra.headers.get("Content-Type") or "").lower()
            except Exception as e:
                logger.warning(f"Image pack skip (download error): {candidate.get('id')} ({e})")
                continue

            if len(extra_data) > MAX_FILE_SIZE:
                logger.warning(f"Image pack skip (too large): {candidate.get('id')}")
                continue

            candidate_mime = (candidate.get("mime") or "").lower()
            candidate_is_gif = (
                "image/gif" in extra_ctype
                or candidate_mime == "image/gif"
                or _is_gif(candidate.get("url", ""))
            )
            candidate_is_video = (
                (extra_ctype.startswith("video/") or candidate_mime.startswith("video/") or _is_video(candidate.get("url", "")))
                and not candidate_is_gif
            )
            if candidate_is_gif or candidate_is_video:
                continue

            if not check_media_size(extra_data, candidate["url"]):
                continue

            extra_hash = hashlib.sha256(extra_data).hexdigest()
            if extra_hash in posted_hashes or extra_hash in pack_hashes:
                continue

            pack_hashes.add(extra_hash)
            image_pack.append({"item": candidate, "data": extra_data, "hash": extra_hash})

        use_image_pack = len(image_pack) >= IMAGE_PACK_SIZE
        logger.info(
            f"Image pack mode: enabled={IMAGE_PACK_ENABLED}, "
            f"target={IMAGE_PACK_SIZE}, built={len(image_pack)}, use_pack={use_image_pack}"
        )

    caption_image_data = None
    caption_secondary_image_data = None

    if is_video and data:
        thumb = get_video_thumbnail(data, seek_sec=2.0)
        if thumb:
            caption_image_data = thumb
            logger.info(f"Video thumbnail extracted for vision: {len(thumb)} bytes")

    # ========== ОТПРАВКА В TELEGRAM ==========
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    
    # Определяем тип контента (3D или AI) на основе тегов
    content_type = detect_content_type_by_tags(item)
    
    # Получаем дату из метаданных
    post_date = item.get("createdAt")

    caption_tags = item["tags"]
    caption_rating = item["rating"]
    caption_likes = item["likes"]
    caption_date = post_date
    caption_width = img_width
    caption_height = img_height
    caption_file_size = file_size_bytes

    if use_image_pack:
        pack_meta = _build_pack_caption_meta(image_pack)
        caption_tags = pack_meta["tags"] or caption_tags
        caption_rating = pack_meta["rating"] if pack_meta["rating"] is not None else caption_rating
        caption_likes = pack_meta["likes"]
        caption_date = pack_meta["date"] or caption_date
        # Для альбома не фиксируем одно разрешение/размер, чтобы не вводить в заблуждение.
        caption_width = None
        caption_height = None
        caption_file_size = None

    caption = generate_caption(
        tags=caption_tags,
        rating=caption_rating,
        likes=caption_likes,
        image_data=caption_image_data,
        image_url=item["url"] if not is_video else None,
        secondary_image_data=caption_secondary_image_data,
        watermark=WATERMARK_TEXT,
        suggestion="💬 Предложка: @Haillord",
        content_type=content_type,
        width=caption_width,
        height=caption_height,
        file_size=caption_file_size,
        date=caption_date
    )

    if use_image_pack:
        caption += f"\n\n📦 Пак: {len(image_pack)} фото"

    logger.info(f"Tags for caption ({len(caption_tags)}): {caption_tags[:8]}")
    logger.info(f"Caption preview: {caption[:100]}")

    try:
        if is_video:
            logger.info("Sending as video")
            logger.info("Using original video (no optimization)")
            video_io = BytesIO(data)
            video_io.name = "video.mp4"
            await send_with_retry(
                bot.send_video,
                chat_id=target_chat_id,
                video=video_io,
                caption=caption,
                parse_mode="HTML",
                supports_streaming=True,
                write_timeout=60,
                read_timeout=60
            )
        elif _is_gif(item["url"]):
            logger.info("Sending as GIF animation")
            anim_io = BytesIO(data)
            anim_io.name = "animation.gif"
            await send_with_retry(
                bot.send_animation,
                chat_id=target_chat_id,
                animation=anim_io,
                caption=caption,
                parse_mode="HTML",
                write_timeout=60,
                read_timeout=60
            )
        elif use_image_pack:
            if IMAGE_PACK_SPLIT_POSTS:
                logger.info(f"Sending image pack as separate posts ({len(image_pack)} photos)")
                for index, pack_entry in enumerate(image_pack):
                    watermarked_data = _apply_watermark_for_image_bytes(
                        pack_entry["data"],
                        pack_entry["item"].get("url", ""),
                    )
                    watermarked_data = _fit_photo_size_for_telegram(watermarked_data)
                    photo_io = BytesIO(watermarked_data)
                    photo_io.name = f"image_{index + 1}.jpg"
                    await send_with_retry(
                        bot.send_photo,
                        chat_id=target_chat_id,
                        photo=photo_io,
                        caption=caption if index == 0 else None,
                        parse_mode="HTML" if index == 0 else None,
                        write_timeout=60,
                        read_timeout=60
                    )
            else:
                logger.info(f"Sending as image pack ({len(image_pack)} photos)")
                media = []
                for index, pack_entry in enumerate(image_pack):
                    watermarked_data = _apply_watermark_for_image_bytes(
                        pack_entry["data"],
                        pack_entry["item"].get("url", ""),
                    )
                    watermarked_data = _fit_photo_size_for_telegram(watermarked_data)
                    photo_io = BytesIO(watermarked_data)
                    photo_io.name = f"image_{index + 1}.jpg"
                    if index == 0:
                        media.append(telegram.InputMediaPhoto(media=photo_io, caption=caption, parse_mode="HTML"))
                    else:
                        media.append(telegram.InputMediaPhoto(media=photo_io))

                await send_with_retry(
                    bot.send_media_group,
                    chat_id=target_chat_id,
                    media=media,
                    write_timeout=60,
                    read_timeout=60
                )
        else:
            logger.info("Sending as image with watermark")
            watermarked_data = _apply_watermark_for_image_bytes(data, item["url"])
            watermarked_data = _fit_photo_size_for_telegram(watermarked_data)
            photo_io = BytesIO(watermarked_data)
            photo_io.name = "image.jpg"
            await send_with_retry(
                bot.send_photo,
                chat_id=target_chat_id,
                photo=photo_io,
                caption=caption,
                parse_mode="HTML",
                write_timeout=60,
                read_timeout=60
            )

        for pack_entry in image_pack if use_image_pack else [{"item": item, "hash": img_hash}]:
            entry_item = pack_entry["item"]
            entry_hash = pack_entry["hash"]
            if entry_item.get("id"):
                posted_ids.add(entry_item["id"])
            posted_hashes.add(entry_hash)
        save_all()
        logger.info(
            f"Successfully posted: {item['id']}"
            + (f" (image pack size={len(image_pack)})" if use_image_pack else "")
        )
        run_metrics["posted"] += 1
        flush_stats_once()

    except Exception as e:
        logger.error(f"Telegram Send Error: {e}")
        run_metrics["send_errors"] += 1
        flush_stats_once()

if __name__ == "__main__":
    asyncio.run(main())
