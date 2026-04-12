"""
ErosLab Bot Base
Общий базовый модуль для всех ботов проекта
Содержит всю общую логику, константы и вспомогательные функции
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
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime
from zoneinfo import ZoneInfo
from PIL import Image
import telegram
from telegram import Bot

from gist_storage import load_all_state, save_all_state


# ==================== ОБЩИЕ КОНСТАНТЫ ====================
MAX_HISTORY_SIZE = 5000
STATS_TZ = os.environ.get("STATS_TZ", "Europe/Moscow")

# Общий блэклист тегов для всех ботов
BLACKLIST_TAGS = {
    "loli", "shota", "child", "minor", "underage", "infant", "toddler",
    "gore", "guro", "scat", "vore", "snuff", "necrophilia", "bestiality", "zoo"
}

# Общие стоп слова для хэштегов
HASHTAG_STOP_WORDS = {
    "score", "source", "rating", "version", "step", "steps", "cfg", "seed",
    "sampler", "model", "lora", "vae", "clip", "unet", "fp16", "safetensors",
    "checkpoint", "embedding", "none", "null", "true", "false", "and", "the",
    "for", "with", "masterpiece", "best", "quality", "high", "ultra", "detail",
    "detailed", "8k", "4k", "hd", "resolution", "simple", "background",
    "generated_by_ai", "animated", "rating_explicit", "rating_questionable",
    "rating_safe", "rating_suggestive", "tagme",
}


# ==================== ИНИЦИАЛИЗАЦИЯ ЛОГГЕРА ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


# ==================== РАБОТА С JSON ====================
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


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def calculate_image_hash(image_data: bytes) -> str:
    """Рассчитывает SHA256 хеш изображения для детекции дублей"""
    return hashlib.sha256(image_data).hexdigest()


def validate_image_size(image: Image.Image, min_size: int = 720) -> bool:
    """Проверяет минимальное разрешение изображения"""
    width, height = image.size
    return width >= min_size and height >= min_size


def validate_aspect_ratio(image: Image.Image, min_ratio: float = 0.5, max_ratio: float = 2.0) -> bool:
    """Проверяет соотношение сторон изображения"""
    width, height = image.size
    ratio = width / height
    return min_ratio <= ratio <= max_ratio


def clean_tags(tags: list[str]) -> list[str]:
    """Очищает список тегов от стоп слов и мусора"""
    cleaned = []
    for tag in tags:
        tag = tag.strip().lower()
        if not tag:
            continue
        if tag in HASHTAG_STOP_WORDS:
            continue
        if any(black in tag for black in BLACKLIST_TAGS):
            continue
        cleaned.append(tag)
    return list(set(cleaned))


# ==================== БАЗОВЫЙ КЛАСС БОТА ====================
class BaseBot:
    """Базовый абстрактный класс для всех ботов ErosLab"""
    
    # Эти параметры переопределяются в дочерних классах
    BOT_NAME = "base"
    TELEGRAM_BOT_TOKEN = ""
    TELEGRAM_CHANNEL_ID = ""
    ADMIN_USER_ID = ""
    
    MIN_LIKES = 5
    MIN_IMAGE_SIZE = 720
    MIN_ASPECT_RATIO_MIN = 0.5
    MIN_ASPECT_RATIO_MAX = 2.0
    IMAGE_PACK_SIZE = 3
    IMAGE_PACK_CANDIDATE_POOL = 18
    
    WATERMARK_ENABLED = False

    # Общие константы которые можно переопределить
    MAX_HISTORY_SIZE = 5000
    STATS_TZ = os.environ.get("STATS_TZ", "Europe/Moscow")

    HASHTAG_STOP_WORDS = {
        "score", "source", "rating", "version", "step", "steps", "cfg", "seed",
        "sampler", "model", "lora", "vae", "clip", "unet", "fp16", "safetensors",
        "checkpoint", "embedding", "none", "null", "true", "false", "and", "the",
        "for", "with", "masterpiece", "best", "quality", "high", "ultra", "detail",
        "detailed", "8k", "4k", "hd", "resolution", "simple", "background",
        "generated_by_ai", "animated", "rating_explicit", "rating_questionable",
        "rating_safe", "rating_suggestive", "tagme",
    }
    
    def __init__(self):
        # Загружаем общее состояние из Gist
        self._state = load_all_state()
        
        # Инициализируем хранилища конкретно для этого бота
        self.posted_ids = set(self._state.get(f"posted_ids_{self.BOT_NAME}.json", []))
        self.posted_hashes = set(self._state.get(f"posted_hashes_{self.BOT_NAME}.json", []))
        self.content_state = self._state.get(f"content_state_{self.BOT_NAME}.json", {"last_type": "landscape"})
        self.stats = self._state.get(f"stats_{self.BOT_NAME}.json", {})
        
        # Инициализируем телеграм бот только если токен есть
        self.bot = None
        if self.TELEGRAM_BOT_TOKEN and self.TELEGRAM_BOT_TOKEN.strip():
            self.bot = Bot(token=self.TELEGRAM_BOT_TOKEN)
        
        logger.info(f"✅ Bot {self.BOT_NAME} инициализирован")
        logger.info(f"📊 В истории: {len(self.posted_ids)} записей, {len(self.posted_hashes)} хешей")

    def clean_tags(self, tags):
        clean, seen = [], set()
        for t in tags:
            t = re.sub(r"[^\w]", "", str(t).strip().lower().replace(" ", "_").replace("-", "_"))
            if re.search(r'\d+$', t):
                continue
            if t and t not in self.HASHTAG_STOP_WORDS and t not in seen and 3 <= len(t) <= 30:
                clean.append(t)
                seen.add(t)
        return clean
    
    async def save_state(self):
        """Сохраняет состояние бота обратно в Gist"""
        self._state[f"posted_ids_{self.BOT_NAME}.json"] = list(self.posted_ids)[-MAX_HISTORY_SIZE:]
        self._state[f"posted_hashes_{self.BOT_NAME}.json"] = list(self.posted_hashes)[-MAX_HISTORY_SIZE:]
        self._state[f"content_state_{self.BOT_NAME}.json"] = self.content_state
        self._state[f"stats_{self.BOT_NAME}.json"] = self.stats
        
        save_all_state(self._state)
        logger.info("💾 Состояние сохранено в Gist")
    
    async def send_photo(self, photo_bytes: bytes, caption: str = "") -> bool:
        """Отправляет фото в канал"""
        try:
            await self.bot.send_photo(
                chat_id=self.TELEGRAM_CHANNEL_ID,
                photo=BytesIO(photo_bytes),
                caption=caption,
                parse_mode="HTML"
            )
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка отправки фото: {e}")
            return False
    
    async def send_media_group(self, media_items: list) -> bool:
        """Отправляет группу медиа файлов"""
        try:
            await self.bot.send_media_group(
                chat_id=self.TELEGRAM_CHANNEL_ID,
                media=media_items
            )
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка отправки медиа группы: {e}")
            return False


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


def check_media_size(data, url, min_image_size: int = 720) -> bool:
    try:
        if not url.lower().endswith((".mp4", ".webm", ".gif")):
            img = Image.open(BytesIO(data))
            width, height = img.size
            if width >= min_image_size and height >= min_image_size:
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


def get_min_bitrate_kbps_for_height(height, bitrate_480p=900, bitrate_720p=1400, bitrate_1080p=2200):
    """Адаптивный порог минимального битрейта по высоте видео."""
    if height is None:
        return bitrate_720p
    if height >= 1080:
        return bitrate_1080p
    if height >= 720:
        return bitrate_720p
    return bitrate_480p


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


def _url_path(url: str) -> str:
    try:
        return urlparse(url).path.lower()
    except Exception:
        return (url or "").lower()


def _is_video(url: str) -> bool:
    return _url_path(url).endswith((".mp4", ".webm"))


def _is_gif(url: str) -> bool:
    return _url_path(url).endswith(".gif")


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


