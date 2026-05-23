"""
ErosLab Bot — CivitAI (только X и XXX рейтинг)
Оптимизирован для GitHub Actions с защитой от повторов.
"""

import asyncio
import hashlib
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
from urllib.parse import urlparse
from PIL import Image
import telegram
from telegram import Bot
from caption_generator import generate_caption
from rule34_api import fetch_rule34
from rule34video_api import fetch_rule34video
from watermark import add_watermark, add_watermark_to_video, should_add_watermark
from utils_state import (
    load_json as _shared_load_json,
    save_json as _shared_save_json,
    get_stats_day_key as _shared_get_stats_day_key,
    load_stats as _shared_load_stats,
    increment_metrics as _shared_increment_metrics,
    record_run_stats as _shared_record_run_stats,
)
from utils_telegram_media import (
    send_with_retry as _shared_send_with_retry,
    fit_photo_size_for_telegram as _shared_fit_photo_size_for_telegram,
)
from utils_tags import (
    clean_tags as _shared_clean_tags,
    normalize_tag as _shared_normalize_tag,
    extract_tags_from_item as _shared_extract_tags_from_item,
    to_int as _shared_to_int,
    extract_civitai_likes as _shared_extract_civitai_likes,
)

# ==================== НАСТРОЙКИ ====================
BOT_MODE = os.environ.get("BOT_MODE", "nsfw").lower()  # nsfw / wallpapers
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "@eroslabai")
CIVITAI_API_KEY     = os.environ.get("CIVITAI_API_KEY", "")

WATERMARK_TEXT   = "📣 @eroslabai"
WATERMARK_IMAGE_TEXT = os.environ.get("WATERMARK_IMAGE_TEXT", "@eroslabai")
WATERMARK_IMAGE_OPACITY = float(os.environ.get("WATERMARK_IMAGE_OPACITY", "0.3"))
MIN_LIKES        = 10
MIN_CIVITAI_LIKES = int(os.environ.get("MIN_CIVITAI_LIKES", "50"))
ALLOW_MATURE_FALLBACK = os.environ.get("ALLOW_MATURE_FALLBACK", "true").lower() in ("1", "true", "yes", "on")
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
NSFW_RATIO = float(os.environ.get("NSFW_RATIO", "0.6"))  # 60% XXX, 40% Mature

# Временно отключить Rule34 (True = только CivitAI для тестов)
TEST_CIVITAI_ONLY = False

# Режим отладки: только rule34video (True = только Rule34Video для тестов)
TEST_RULE34VIDEO_ONLY = True

HISTORY_FILE = "posted_ids.json"
HASHES_FILE  = "posted_hashes.json"
CONTENT_STATE_FILE = "content_state.json"
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
    # Fart content
    "fart", "farting", "fart_fetish", "fart_edit",
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
    # Score теги CivitAI
    "score_9", "score_8", "score_7", "score_6", "score_5",
    "score_8_up", "score_7_up", "score_6_up", "score_5_up",
    "score_8_expressiveh", "score_9_up", "score_4", "score_4_up",
    # Rating теги
    "rating_lewd", "rating_adult", "rating_mature",
    # Технические промпт-теги
    "break", "break_apart", "perfect_body", "perfect_face", "perfect_skin",
    "hi_res", "highres", "absurdres", "extremely_detailed", "highly_detailed",
    "best_quality", "high_quality", "ultra_detailed", "ultra_high_res",
    "realistic", "photorealistic", "hyperrealistic",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# ==================== ХРАНИЛИЩА ====================
def load_json(path, default):
    return _shared_load_json(path, default, logger)

def save_json(path, data):
    _shared_save_json(path, data)

_state = load_all_state()
posted_ids    = set(_state.get("posted_ids.json", []))
posted_hashes = set(_state.get("posted_hashes.json", []))
content_state = _state.get("content_state.json", {"last_type": "3d", "last_media": "video"})

def _get_stats_day_key():
    return _shared_get_stats_day_key(STATS_TZ)

def _load_stats():
    return _shared_load_stats(STATS_FILE, logger, extra_defaults={"report": {}})

def _increment_metrics(target: dict, metrics: dict):
    _shared_increment_metrics(target, metrics)

def record_run_stats(metrics: dict):
    _shared_record_run_stats(
        stats_file=STATS_FILE,
        stats_tz=STATS_TZ,
        metrics=metrics,
        logger=logger,
        keep_days=45,
        extra_defaults={"report": {}},
    )

def get_next_content_type():
    """Чередует между 3d и ai контентом"""
    global content_state
    next_type = "ai" if content_state["last_type"] == "3d" else "3d"
    content_state["last_type"] = next_type
    save_json(CONTENT_STATE_FILE, content_state)
    return next_type

def get_next_media_type():
    """Строгое распределение: 85% video, 15% image."""
    global content_state
    media_type = "video" if random.random() < 0.85 else "image"
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
        "stats.json":         _load_stats(),
    })

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def clean_tags(tags):
    return _shared_clean_tags(tags, HASHTAG_STOP_WORDS)

def _normalize_tag(tag: str) -> str:
    return _shared_normalize_tag(tag)

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

def get_video_metadata(data: bytes) -> dict:
    """
    Один ffprobe-вызов для всех метаданных видео.
    Возвращает: {duration, width, height, codec, pix_fmt, is_valid, issues}
    """
    tmp_path = None
    default_result = {
        "duration": 0.0,
        "width": None,
        "height": None,
        "codec": "",
        "pix_fmt": "",
        "is_valid": False,
        "issues": ["ffprobe not executed"],
    }
    try:
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration:stream=codec_name,pix_fmt,width,height',
            '-of', 'default=noprint_wrappers=1:nokey=0',
            '-select_streams', 'v:0',
            tmp_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return {**default_result, "issues": ["ffprobe failed"]}

        duration = 0.0
        width = None
        height = None
        codec = ""
        pix_fmt = ""
        issues = []

        for line in result.stdout.strip().splitlines():
            if '=' not in line:
                continue
            key, value = line.split('=', 1)
            value = value.strip()

            if key == 'duration':
                try:
                    duration = float(value) if value and value != 'N/A' else 0.0
                except ValueError:
                    pass
            elif key == 'codec_name':
                codec = value
                if codec not in ('h264', 'hevc', 'h265') or codec == 'wrapped_avframe':
                    issues.append(f"Неподдерживаемый кодек: {codec}")
            elif key == 'pix_fmt':
                pix_fmt = value
                if pix_fmt not in ('yuv420p', 'yuvj420p') or '10le' in pix_fmt or '12le' in pix_fmt or '444p' in pix_fmt:
                    issues.append(f"Несовместимый формат пикселей: {pix_fmt}")
            elif key == 'width':
                try:
                    width = int(value)
                except (TypeError, ValueError):
                    pass
            elif key == 'height':
                try:
                    height = int(value)
                except (TypeError, ValueError):
                    pass

        if width is not None and height is not None:
            if width > 1080 or height > 1080:
                issues.append(f"Размер больше лимита: {width}x{height}")

        return {
            "duration": duration,
            "width": width,
            "height": height,
            "codec": codec,
            "pix_fmt": pix_fmt,
            "is_valid": len(issues) == 0 and duration > 0,
            "issues": issues,
        }

    except Exception as e:
        logger.error(f"Video metadata error: {e}")
        return {**default_result, "issues": [f"Metadata error: {str(e)}"]}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


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
            # Upscale: если разрешение меньше 480p — поднимаем до 480p для лучшего качества
        '-vf', "scale='if(lt(min(iw\\,ih),480),if(gt(iw\\,ih),854,-2),if(gt(iw\\,ih),1080,-2))':'if(lt(min(iw\\,ih),480),if(gt(iw\\,ih),-2,480),if(gt(iw\\,ih),-2,1080))'",
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


def compress_video_to_limit(input_data: bytes, max_bytes: int = 49 * 1024 * 1024) -> bytes | None:
    """
    Пытается сжать видео до max_bytes через ffmpeg (target bitrate).
    Возвращает сжатые данные или None если не получилось.
    """
    tmp_in = None
    tmp_out = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp.write(input_data)
            tmp_in = tmp.name

        # Узнаём длительность видео
        probe = subprocess.run([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            tmp_in
        ], capture_output=True, text=True, timeout=10)

        try:
            duration = float(probe.stdout.strip())
        except ValueError:
            logger.warning("compress: не удалось получить длительность видео")
            return None

        if duration <= 0:
            logger.warning("compress: нулевая длительность")
            return None

        # Целевой битрейт в kbps (оставляем 5% запас)
        target_size_bits = max_bytes * 8 * 0.95
        target_bitrate_kbps = int(target_size_bits / duration / 1000)

        # Минимальный разумный битрейт — ниже качество будет совсем плохим
        if target_bitrate_kbps < 300:
            logger.warning(f"compress: целевой битрейт {target_bitrate_kbps} kbps слишком мал, скипаем")
            return None

        tmp_out = tmp_in + "_compressed.mp4"
        logger.info(f"compress: пробуем сжать до {target_bitrate_kbps} kbps (лимит {max_bytes // 1024 // 1024} МБ)")

        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", tmp_in,
            "-c:v", "libx264",
            "-b:v", f"{target_bitrate_kbps}k",
            "-maxrate", f"{target_bitrate_kbps}k",
            "-bufsize", f"{target_bitrate_kbps * 2}k",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            tmp_out
        ]

        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            logger.warning(f"compress: ffmpeg завершился с ошибкой: {result.stderr.decode(errors='ignore')[:200]}")
            return None

        actual_size = os.path.getsize(tmp_out)
        if actual_size > max_bytes:
            logger.warning(f"compress: после сжатия всё ещё {actual_size // 1024 // 1024} МБ, скипаем")
            return None

        with open(tmp_out, 'rb') as f:
            compressed_data = f.read()

        logger.info(f"compress: ✅ сжато {len(input_data) // 1024 // 1024} МБ → {actual_size // 1024 // 1024} МБ")
        return compressed_data

    except subprocess.TimeoutExpired:
        logger.warning("compress: ffmpeg timeout")
        return None
    except Exception as e:
        logger.error(f"compress: ошибка: {e}")
        return None
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
    return await _shared_send_with_retry(func, *args, retries=retries, logger=logger, **kwargs)


def _fit_photo_size_for_telegram(image_data: bytes, max_size: int = 10 * 1024 * 1024) -> bytes:
    return _shared_fit_photo_size_for_telegram(image_data, logger=logger, max_size=max_size)

# ==================== ТЕГИ ====================
def extract_tags(item):
    return _shared_extract_tags_from_item(item, HASHTAG_STOP_WORDS, logger=logger, debug_logs=True)


# ==================== CIVITAI API ====================
def _request_with_backoff(url, params, headers, max_retries=3):
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            if r.status_code == 429:
                wait = 2 ** attempt * 5
                logger.warning(f"Rate limited (429), waiting {wait}s before retry {attempt + 1}/{max_retries}")
                time.sleep(wait)
                continue
            if r.status_code == 500:
                # CivitAI может быть нестабилен: не тратим время на длинные ретраи.
                wait = 2 + attempt * 2  # 2, 4, 6
                logger.warning(f"Server error 500, retry {attempt + 1}/{max_retries}")
                if attempt >= max_retries - 1:
                    return None
                time.sleep(wait)
                continue
            if r.status_code == 400:
                return r
            r.raise_for_status()
            return r
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout on attempt {attempt + 1}/{max_retries}")
            if attempt < max_retries - 1:
                time.sleep(3)
        except requests.exceptions.HTTPError as e:
            if r.status_code >= 500:
                logger.warning(f"Server error {r.status_code}, retry {attempt + 1}/{max_retries}")
                time.sleep(2 ** attempt * 2)
            else:
                raise
        except Exception as e:
            logger.error(f"Request error: {e}")
            raise
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
    return _shared_to_int(value, default)

def _extract_civitai_likes(item):
    return _shared_extract_civitai_likes(item)

def _extract_civitai_prompt(item: dict) -> str | None:
    meta = item.get("meta")
    if not isinstance(meta, dict):
        return None
    prompt = (
        meta.get("prompt") or meta.get("Prompt") or meta.get("positive") or ""
    ).strip()
    if not prompt or len(prompt) < 20:
        return None

    prompt = re.sub(r'<[^>]+>', '', prompt)
    prompt = re.sub(
        r'\b(score_\d+[\w_]*|masterpiece|best quality|highres|absurdres'
        r'|ultra[\w ]*|extremely detailed|step\d+|cfg\s*\d+|BREAK)\b',
        '', prompt, flags=re.IGNORECASE
    )
    prompt = re.sub(r',\s*,', ',', prompt)
    prompt = re.sub(r'\s+', ' ', prompt).strip(", ")

    return prompt or None

def _get_adaptive_max_pages(period: str | None) -> int:
    """
    Адаптивное количество страниц в зависимости от периода.
    Day — свежий топ, хватает 5 страниц.
    Week/Month/AllTime — больше контента, глубже копаем.
    """
    if period == "Day":
        return 5
    elif period in ("Week",):
        return 10
    else:  # Month, None (All Time) или неизвестный
        return 15


def _fetch_civitai_variation(base_params: dict, headers: dict, seen_ids: set) -> list[dict]:
    """
    Собирает items по одной вариации (одному запросу к API).
    Возвращает список сырых item-ов.
    """
    all_items = []
    next_page_url = None
    max_pages = _get_adaptive_max_pages(base_params.get("period"))
    
    for page in range(1, max_pages + 1):
        request_url = next_page_url or "https://civitai.com/api/v1/images"
        params = None if next_page_url else {**base_params, "limit": 100}
        
        try:
            r = _request_with_backoff(request_url, params=params, headers=headers)
            if r is None:
                logger.warning(f"CivitAI page {page}: no response for {base_params}")
                if page == 1:
                    return []
                break

            if r.status_code == 400:
                logger.debug(f"CivitAI page {page}: 400 for {params}")
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
    
    return all_items


def _process_civitai_items(items: list[dict]) -> list[dict]:
    """
    Фильтрует сырые items: NSFW-проверка, блэклист, лайки.
    Возвращает готовые erotic_items.
    """
    if not items:
        return []

    # Проверка доступности лайков
    items_with_positive_reactions = 0
    total_checked = 0
    for item in items:
        stats = item.get("stats")
        if isinstance(stats, dict):
            total_checked += 1
            if any(stats.get(k, 0) for k in ("likeCount", "heartCount", "laughCount")):
                items_with_positive_reactions += 1

    likes_filter_enabled = (
        total_checked > 0
        and items_with_positive_reactions > total_checked * 0.1
    )
    logger.info(
        f"Likes filter status: {'enabled' if likes_filter_enabled else 'disabled'} "
        f"(items_with_reactions={items_with_positive_reactions}/{total_checked})"
    )

    erotic_items = []
    for item in items:
        try:
            nsfw_level = item.get("nsfwLevel")
            is_allowed_nsfw = _is_x_or_xxx(nsfw_level)
            if not is_allowed_nsfw and ALLOW_MATURE_FALLBACK and _is_mature_or_higher(nsfw_level):
                if random.random() < NSFW_RATIO:
                    is_allowed_nsfw = True

            if not is_allowed_nsfw:
                continue

            tags = extract_tags(item)
            if has_blacklisted(tags):
                continue

            likes = _extract_civitai_likes(item)
            if likes_filter_enabled and likes < MIN_CIVITAI_LIKES:
                continue

            erotic_items.append({
                "id":        f"civitai_{item['id']}",
                "url":       item.get("url", ""),
                "tags":      tags[:15],
                "likes":     likes,
                "rating":    nsfw_level,
                "post_id":   item.get("postId"),
                "mime":      (item.get("mimeType") or "").lower(),
                "createdAt": item.get("createdAt"),
                "source":    "civitai",
                "prompt":    _extract_civitai_prompt(item),
            })
        except Exception as e:
            logger.error(f"Error processing item {item.get('id')}: {e}")
            continue

    return erotic_items


def fetch_civitai(max_pages: int = 5):
    """
    Собирает топ-контент с CivitAI.

    Стратегия:
    1. Сначала собираем Most Reactions за все периоды (Day, Week, Month, All Time)
       в общий пул, сортируем по лайкам, возвращаем топ.
    2. Если ничего не нашли — fallback на Newest.
    """
    variations = [
        # Most Reactions — главный источник, собираем со всех периодов
        {"browsingLevel": 28, "nsfw": "X", "sort": "Most Reactions", "period": "Day", "mediaType": "video"},
        {"browsingLevel": 28, "nsfw": "X", "sort": "Most Reactions", "period": "Week", "mediaType": "video"},
        {"browsingLevel": 28, "nsfw": "X", "sort": "Most Reactions", "period": "Month", "mediaType": "video"},
        {"browsingLevel": 28, "nsfw": "X", "sort": "Most Reactions", "period": "Day"},
        {"browsingLevel": 28, "nsfw": "X", "sort": "Most Reactions", "period": "Week"},
        {"browsingLevel": 28, "nsfw": "X", "sort": "Most Reactions", "period": "Month"},
        {"browsingLevel": 28, "nsfw": "X", "sort": "Most Reactions"},  # All Time
    ]

    headers = {"Authorization": f"Bearer {CIVITAI_API_KEY}"} if CIVITAI_API_KEY else {}
    seen_ids = set()

    # ── Шаг 1: Most Reactions — собираем со всех периодов ────────────────
    all_collected = []
    for base_params in variations:
        items = _fetch_civitai_variation(base_params, headers, seen_ids)
        if items:
            period = base_params.get("period", "All Time")
            logger.info(
                f"CivitAI {base_params['sort']} ({period}): "
                f"collected {len(items)} raw items"
            )
            erotic = _process_civitai_items(items)
            if erotic:
                logger.info(
                    f"CivitAI {base_params['sort']} ({period}): "
                    f"{len(erotic)} suitable items"
                )
                all_collected.extend(erotic)

    # Если нашли что-то — сортируем по лайкам и возвращаем топ
    if all_collected:
        all_collected.sort(key=lambda x: x["likes"], reverse=True)
        logger.info(
            f"CivitAI Most Reactions total: {len(all_collected)} items, "
            f"top likes: {all_collected[0]['likes']}, "
            f"median: {all_collected[len(all_collected)//2]['likes']}"
        )
        return all_collected

    # ── Шаг 2: Fallback на Newest ────────────────────────────────────────
    logger.info("CivitAI Most Reactions: no suitable items, falling back to Newest")
    newest_variations = [
        {"browsingLevel": 28, "nsfw": "X", "sort": "Newest", "mediaType": "video"},
        {"browsingLevel": 28, "nsfw": "X", "sort": "Newest"},
        {"browsingLevel": 28, "nsfw": "X", "sort": "Newest", "period": "Week"},
        {"browsingLevel": 28, "nsfw": "X", "sort": "Newest", "period": "Month"},
    ]

    for base_params in newest_variations:
        items = _fetch_civitai_variation(base_params, headers, seen_ids)
        if items:
            period = base_params.get("period", "N/A")
            logger.info(f"CivitAI Newest ({period}): {len(items)} raw items")
            erotic = _process_civitai_items(items)
            if erotic:
                logger.info(f"CivitAI Newest ({period}): {len(erotic)} suitable items")
                return erotic

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


def _pick_by_content_type(fresh):
    """70/30 видео или фото. Если нужного типа нет — берём что есть."""
    content_type = "video" if random.random() < 0.85 else "image"
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


def _select_item_from_fresh(source: str, fresh: list[dict]):
    if not fresh:
        return None

    if source == "rule34":
        selected = _pick_by_content_type(fresh)
    else:
        content_type = "video" if random.random() < 0.85 else "image"
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


# ==================== ИСТОЧНИКИ / ВЕСА ====================

def _load_source_weights() -> dict:
    """
    Читает веса источников из ENV SOURCE_WEIGHTS (JSON).
    Пример в GitHub Secrets:
        SOURCE_WEIGHTS = {"civitai":35,"rule34":25}
    Если переменная не задана — дефолт ниже.
    """
    import json
    default = {
        "civitai":  1,
        "rule34":   1,
        "rule34video": 1,
    }
    raw = os.environ.get("SOURCE_WEIGHTS", "").strip()
    if not raw:
        return default
    try:
        loaded = json.loads(raw)
        if isinstance(loaded, dict):
            return {k: int(v) for k, v in loaded.items()}
    except Exception:
        logger.warning("SOURCE_WEIGHTS: невалидный JSON, используем дефолт")
    return default


def fetch_candidates_once():
    """
    Выбирает источник по взвешенной случайности и возвращает (source, fresh_items).

    Логика:
    - TEST_CIVITAI_ONLY=True → только CivitAI, без вариантов.
    - Иначе: взвешенный выбор из доступных источников.
    - Если выбранный источник вернул 0 результатов → автофоллбек по убыванию веса.
    - Блэклист применяется здесь для всех источников кроме CivitAI
      (у него фильтрация встроена внутри fetch_civitai()).
    """

    # ── Режим отладки: только Rule34Video ─────────────────────────────────
    if TEST_RULE34VIDEO_ONLY:
        logger.info("Source: Rule34Video only (TEST_RULE34VIDEO_ONLY=True)")
        items = fetch_rule34video()
        if not items:
            logger.warning("TEST_RULE34VIDEO_ONLY=True и Rule34Video ничего не вернул")
            return "rule34video", []
        fresh = [i for i in items if i["id"] not in posted_ids]
        fresh = [i for i in fresh if not has_blacklisted(i.get("tags", []))]
        logger.info(f"Rule34Video fresh: {len(fresh)} / {len(items)}")
        return "rule34video", fresh

    # ── Режим отладки: только CivitAI ─────────────────────────────────────
    if TEST_CIVITAI_ONLY:
        logger.info("Source: CivitAI only (TEST_CIVITAI_ONLY=True)")
        items = fetch_civitai()
        if not items:
            logger.warning("TEST_CIVITAI_ONLY=True и CivitAI ничего не вернул")
            return "civitai", []
        fresh = [i for i in items if i["id"] not in posted_ids]
        logger.info(f"CivitAI fresh: {len(fresh)} / {len(items)}")
        return "civitai", fresh

    # ── Собираем доступные источники ──────────────────────────────────────
    def _fetch_rule34():
        # Счётчики вызываем только при реальном использовании Rule34
        content_type = get_next_content_type()
        media_type = get_next_media_type()
        logger.info(f"Rule34 content_type={content_type}, media_type={media_type}")
        return fetch_rule34(limit=100, content_type=content_type, media_type=media_type)

    available = {
        "civitai":  fetch_civitai,
        "rule34":   _fetch_rule34,
        "rule34video": fetch_rule34video,
    }

    weights_cfg = _load_source_weights()
    logger.info(f"Source weights: {weights_cfg}")

    # Только те источники, для которых есть вес
    names   = [n for n in available if n in weights_cfg]
    weights = [weights_cfg[n] for n in names]

    if not names:
        logger.error("Нет доступных источников!")
        return "none", []

    # ── Взвешенный выбор + фоллбек-цепочка ───────────────────────────────
    primary = random.choices(names, weights=weights, k=1)[0]
    # Цепочка: сначала выбранный, затем остальные по убыванию веса
    fallback_order = sorted(
        [n for n in names if n != primary],
        key=lambda n: weights_cfg.get(n, 0),
        reverse=True,
    )
    chain = [primary] + fallback_order

    for source in chain:
        is_fallback = source != primary
        logger.info(f"Source: {source}" + (" (fallback)" if is_fallback else ""))

        try:
            items = available[source]()
        except Exception as e:
            logger.error(f"Источник {source} упал с ошибкой: {e}")
            continue

        if not items:
            logger.warning(f"{source}: пустой ответ, пробуем следующий")
            continue

        # Фильтр уже виденного
        fresh = [i for i in items if i["id"] not in posted_ids]

        # Блэклист (CivitAI фильтрует сам внутри)
        if source != "civitai":
            fresh = [i for i in fresh if not has_blacklisted(i.get("tags", []))]

        logger.info(f"{source}: fresh={len(fresh)} / total={len(items)}")

        if fresh:
            return source, fresh

        logger.info(f"{source}: нет свежих постов, пробуем следующий")

    logger.warning("Все источники исчерпаны")
    return "none", []


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


# ==================== MAIN ====================
async def main():
    global posted_ids, posted_hashes, content_state
    posted_ids    = set(_state.get("posted_ids.json", []))
    posted_hashes = set(_state.get("posted_hashes.json", []))
    content_state = _state.get("content_state.json", {"last_type": "3d", "last_media": "video"})

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

    if not CIVITAI_API_KEY and not TEST_RULE34VIDEO_ONLY:
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

    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
    MAX_ATTEMPTS  = 10

    source, fresh_items = fetch_candidates_once()
    if not fresh_items:
        logger.info("No more fresh posts available")
        run_metrics["skip_no_item"] += 1
        flush_stats_once()
        return

    # Приоритет видео: с 85% вероятностью ставим видео первыми в attempts pool
    video_items = [i for i in fresh_items if _is_video_item(i)]
    photo_items = [i for i in fresh_items if not _is_video_item(i)]

    random.shuffle(video_items)
    random.shuffle(photo_items)

    if video_items and random.random() < 0.85:
        attempts_pool = (video_items + photo_items)[:MAX_ATTEMPTS]
        logger.info(
            f"Attempts pool: video-first "
            f"({len(video_items)} videos, {len(photo_items)} photos, "
            f"pool_size={len(attempts_pool)}, total_fresh={len(fresh_items)})"
        )
    else:
        attempts_pool = (photo_items + video_items)[:MAX_ATTEMPTS]
        logger.info(
            f"Attempts pool: photo-first "
            f"({len(photo_items)} photos, {len(video_items)} videos, "
            f"pool_size={len(attempts_pool)}, total_fresh={len(fresh_items)})"
        )

    for attempt, item in enumerate(attempts_pool, start=1):
        logger.info(f"Attempt {attempt}/{len(attempts_pool)} with item {item.get('id')}")

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
            logger.warning(f"File too large ({len(data) // 1024 // 1024} МБ > 50MB), trying to compress...")
            compressed_data = compress_video_to_limit(data)
            if compressed_data is None:
                logger.warning("Compression failed, skipping")
                run_metrics["skip_file_too_large"] += 1
                posted_ids.add(item["id"])
                save_all()
                continue
            data = compressed_data
            logger.info(f"Compressed to {len(data) // 1024 // 1024} MB, continuing with normal processing")

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
            # Один ffprobe-вызов для всех метаданных видео
            meta = get_video_metadata(data)
            if meta["duration"] < 0.5:
                logger.warning(f"Video too short ({meta['duration']:.2f}s), skipping")
                run_metrics["skip_bad_video_duration"] += 1
                posted_ids.add(item["id"])
                save_all()
                continue
            logger.info(f"Video duration: {meta['duration']:.2f}s, "
                        f"resolution: {meta['width']}x{meta['height']}, "
                        f"codec: {meta['codec']}")

            img_width, img_height = meta["width"], meta["height"]

            avg_bitrate_kbps = (len(data) * 8) / meta["duration"] / 1000 if meta["duration"] > 0 else 0
            min_bitrate_kbps = get_min_bitrate_kbps_for_height(img_height)
            logger.info(
                f"Video QoS stats: "
                f"resolution={img_width}x{img_height}, "
                f"avg_bitrate={avg_bitrate_kbps:.0f} kbps, "
                f"required_min={min_bitrate_kbps} kbps"
            )

    if ENABLE_VIDEO_QOS and avg_bitrate_kbps < min_bitrate_kbps:
        # Для rule34video смягчаем порог — там часто только 360p
        effective_min = min_bitrate_kbps
        if item.get("source") == "rule34video":
            effective_min = max(min_bitrate_kbps - 300, 500)
        if avg_bitrate_kbps < effective_min:
            logger.warning(
                f"Skipping low-quality video: {avg_bitrate_kbps:.0f} < {effective_min} kbps"
            )
            run_metrics["skip_low_video_quality"] += 1
            posted_ids.add(item["id"])
            save_all()
            continue
        else:
            logger.info(
                f"Video QoS: {avg_bitrate_kbps:.0f} < {min_bitrate_kbps} (standard), "
                f"but passed softened rule34video threshold ({effective_min} kbps)"
            )
            
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

    # Считаем источник только один раз — по выбранному item
    source_key = f"source_{item.get('source', 'unknown')}_selected"
    run_metrics[source_key] = run_metrics.get(source_key, 0) + 1

    # ========== СБОРКА ПАКА ФОТО (только CivitAI/Rule34) ==========
    image_pack = [{"item": item, "data": data, "hash": img_hash}]
    use_image_pack = False

    if IMAGE_PACK_ENABLED and _is_photo_item(item) and item.get("source") in ("civitai", "rule34") and IMAGE_PACK_SIZE > 1:
        pack_hashes = {img_hash}

        # Используем attempts_pool вместо повторного API-запроса
        pack_candidates = [
            i for i in attempts_pool
            if i.get("id") != item.get("id")
            and _is_photo_item(i)
            and not has_blacklisted(i.get("tags", []))
        ]
        # Сортируем по популярности
        pack_candidates.sort(key=lambda x: max(0, int(x.get("likes", 0))), reverse=True)
        candidates = pack_candidates[:IMAGE_PACK_CANDIDATE_POOL]
        logger.info(f"Image pack candidates from pool: {len(candidates)} (pool has {len(attempts_pool)} items)")

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
        secondary_image_data=None,
        watermark=WATERMARK_TEXT,
        suggestion="💬 Предложка: @Haillord",
        content_type=content_type,
        width=caption_width,
        height=caption_height,
        file_size=caption_file_size,
        date=caption_date,
        prompt_hint=item.get("prompt"),
    )


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
        posted_ids.add(item["id"])
        save_all()
        run_metrics["send_errors"] += 1
        flush_stats_once()

if __name__ == "__main__":
    asyncio.run(main())
