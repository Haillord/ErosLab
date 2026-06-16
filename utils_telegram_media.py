import asyncio
import logging
import os
import subprocess
import tempfile
from io import BytesIO

from PIL import Image


# ---------------------------------------------------------------------------
# Retry wrapper
# ---------------------------------------------------------------------------

async def send_with_retry(func, *args, retries=3, logger: logging.Logger | None = None, **kwargs):
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
        for key in ("photo", "video", "animation", "document", "thumbnail", "media"):
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
            if "invalid_dimensions" in str(e).lower():
                raise
            if attempt == retries - 1:
                raise
            if logger:
                logger.warning(f"Telegram send failed (attempt {attempt + 1}/{retries}): {e}")
            await asyncio.sleep(2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_ffmpeg() -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _run_ffmpeg(args: list[str], logger: logging.Logger | None = None) -> bool:
    """Запускает ffmpeg с заданными аргументами. Возвращает True при успехе."""
    cmd = ["ffmpeg", "-y"] + args
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        if result.returncode != 0 and logger:
            logger.warning(f"ffmpeg stderr: {result.stderr.decode(errors='replace')[-500:]}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        if logger:
            logger.warning("ffmpeg timed out")
        return False
    except Exception as e:
        if logger:
            logger.warning(f"ffmpeg error: {e}")
        return False


# ---------------------------------------------------------------------------
# Photo
# ---------------------------------------------------------------------------

def strip_photo_metadata(image_data: bytes) -> bytes:
    """Удаляет EXIF и все метаданные из JPEG/PNG/WebP/etc."""
    try:
        img = Image.open(BytesIO(image_data))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        output = BytesIO()
        img.save(output, format="JPEG", quality=95, optimize=True)
        return output.getvalue()
    except Exception:
        return image_data


def fit_photo_for_telegram(
    image_data: bytes,
    logger: logging.Logger | None = None,
    max_size: int = 10 * 1024 * 1024,
) -> bytes:
    """
    Очищает метаданные и при необходимости сжимает фото под лимит Telegram (10 MB).
    """
    if not image_data:
        return image_data

    try:
        clean = strip_photo_metadata(image_data)

        if len(clean) <= max_size:
            return clean

        img = Image.open(BytesIO(clean))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        # Шаг 1: снижаем качество
        for quality in (92, 88, 84, 80, 76, 72, 68):
            out = BytesIO()
            img.save(out, format="JPEG", quality=quality, optimize=True)
            candidate = out.getvalue()
            if len(candidate) <= max_size:
                if logger:
                    logger.info(f"Photo recompressed: {len(candidate)} bytes (q={quality})")
                return candidate

        # Шаг 2: уменьшаем размер
        width, height = img.size
        for scale in (0.95, 0.9, 0.85, 0.8, 0.75):
            new_w = max(1, int(width * scale))
            new_h = max(1, int(height * scale))
            resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            out = BytesIO()
            resized.save(out, format="JPEG", quality=76, optimize=True)
            candidate = out.getvalue()
            if len(candidate) <= max_size:
                if logger:
                    logger.info(
                        f"Photo downscaled: {len(candidate)} bytes "
                        f"({width}x{height} -> {new_w}x{new_h})"
                    )
                return candidate

    except Exception as e:
        if logger:
            logger.warning(f"Could not fit photo size: {e}")

    return image_data


# ---------------------------------------------------------------------------
# GIF
# ---------------------------------------------------------------------------

def strip_gif_metadata(gif_data: bytes, logger: logging.Logger | None = None) -> bytes:
    """
    Убирает метаданные из GIF через пересборку кадров через Pillow.
    Если ffmpeg доступен — использует его (быстрее и надёжнее).
    """
    if not gif_data:
        return gif_data

    # Вариант через ffmpeg (лучше сохраняет анимацию)
    if _has_ffmpeg():
        try:
            with tempfile.NamedTemporaryFile(suffix=".gif", delete=False) as src:
                src.write(gif_data)
                src_path = src.name
            dst_path = src_path + "_clean.gif"

            ok = _run_ffmpeg(
                ["-i", src_path, "-map_metadata", "-1", "-f", "gif", dst_path],
                logger=logger,
            )
            if ok and os.path.exists(dst_path):
                with open(dst_path, "rb") as f:
                    result = f.read()
                return result if result else gif_data
        except Exception as e:
            if logger:
                logger.warning(f"GIF ffmpeg strip failed: {e}")
        finally:
            for p in (src_path, dst_path):
                try:
                    os.unlink(p)
                except Exception:
                    pass

    # Фолбек через Pillow — пересобираем кадры
    try:
        src_img = Image.open(BytesIO(gif_data))
        frames = []
        durations = []

        for i in range(getattr(src_img, "n_frames", 1)):
            src_img.seek(i)
            frame = src_img.convert("RGBA")
            frames.append(frame)
            durations.append(src_img.info.get("duration", 100))

        if not frames:
            return gif_data

        output = BytesIO()
        frames[0].save(
            output,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            loop=src_img.info.get("loop", 0),
            duration=durations,
            optimize=False,
        )
        result = output.getvalue()
        if logger:
            logger.info(
                f"GIF metadata stripped via Pillow: "
                f"{len(gif_data)} -> {len(result)} bytes"
            )
        return result
    except Exception as e:
        if logger:
            logger.warning(f"GIF Pillow strip failed: {e}")
        return gif_data


def fit_gif_for_telegram(
    gif_data: bytes,
    logger: logging.Logger | None = None,
    max_size: int = 50 * 1024 * 1024,
) -> bytes:
    """
    Очищает метаданные GIF и при необходимости сжимает под лимит Telegram (50 MB).
    Требует ffmpeg для сжатия.
    """
    if not gif_data:
        return gif_data

    clean = strip_gif_metadata(gif_data, logger=logger)

    if len(clean) <= max_size:
        return clean

    if not _has_ffmpeg():
        if logger:
            logger.warning("GIF too large but ffmpeg not available for compression")
        return clean

    try:
        with tempfile.NamedTemporaryFile(suffix=".gif", delete=False) as src:
            src.write(clean)
            src_path = src.name
        dst_path = src_path + "_small.gif"

        # Уменьшаем fps и разрешение
        ok = _run_ffmpeg(
            [
                "-i", src_path,
                "-vf", "scale=iw*0.75:ih*0.75:flags=lanczos",
                "-r", "15",
                "-map_metadata", "-1",
                dst_path,
            ],
            logger=logger,
        )
        if ok and os.path.exists(dst_path):
            with open(dst_path, "rb") as f:
                result = f.read()
            if result and len(result) <= max_size:
                if logger:
                    logger.info(f"GIF downscaled: {len(clean)} -> {len(result)} bytes")
                return result
    except Exception as e:
        if logger:
            logger.warning(f"GIF compression failed: {e}")
    finally:
        for p in (src_path, dst_path):
            try:
                os.unlink(p)
            except Exception:
                pass

    return clean


# ---------------------------------------------------------------------------
# Video
# ---------------------------------------------------------------------------

def strip_video_metadata(video_data: bytes, logger: logging.Logger | None = None) -> bytes:
    """
    Удаляет метаданные из видео через ffmpeg (map_metadata -1).
    Без перекодирования — только стриппинг контейнера.
    """
    if not video_data:
        return video_data

    if not _has_ffmpeg():
        if logger:
            logger.warning("ffmpeg not available, video metadata not stripped")
        return video_data

    src_path = None
    dst_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as src:
            src.write(video_data)
            src_path = src.name
        dst_path = src_path + "_clean.mp4"

        ok = _run_ffmpeg(
            [
                "-i", src_path,
                "-map_metadata", "-1",
                "-c", "copy",        # без перекодирования
                "-movflags", "+faststart",
                dst_path,
            ],
            logger=logger,
        )
        if ok and os.path.exists(dst_path):
            with open(dst_path, "rb") as f:
                result = f.read()
            if result:
                if logger:
                    logger.info(
                        f"Video metadata stripped: "
                        f"{len(video_data)} -> {len(result)} bytes"
                    )
                return result
    except Exception as e:
        if logger:
            logger.warning(f"Video strip failed: {e}")
    finally:
        for p in (p for p in (src_path, dst_path) if p):
            try:
                os.unlink(p)
            except Exception:
                pass

    return video_data


def fit_video_for_telegram(
    video_data: bytes,
    logger: logging.Logger | None = None,
    max_size: int = 50 * 1024 * 1024,
) -> bytes:
    """
    Очищает метаданные видео и при необходимости сжимает под лимит Telegram (50 MB).
    При сжатии перекодирует в H.264 + AAC.
    """
    if not video_data:
        return video_data

    clean = strip_video_metadata(video_data, logger=logger)

    if len(clean) <= max_size:
        return clean

    if not _has_ffmpeg():
        if logger:
            logger.warning("Video too large but ffmpeg not available")
        return clean

    src_path = None
    dst_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as src:
            src.write(clean)
            src_path = src.name
        dst_path = src_path + "_compressed.mp4"

        # Рассчитываем target bitrate (оставляем 5% буфер)
        # Получаем длительность
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                src_path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        duration = float(probe.stdout.strip() or "0")

        if duration > 0:
            target_bytes = max_size * 0.95
            target_kbps = int((target_bytes * 8) / duration / 1000)
            video_kbps = max(200, target_kbps - 128)  # 128 kbps на аудио
        else:
            video_kbps = 800

        ok = _run_ffmpeg(
            [
                "-i", src_path,
                "-c:v", "libx264",
                "-b:v", f"{video_kbps}k",
                "-c:a", "aac",
                "-b:a", "128k",
                "-map_metadata", "-1",
                "-movflags", "+faststart",
                dst_path,
            ],
            logger=logger,
        )
        if ok and os.path.exists(dst_path):
            with open(dst_path, "rb") as f:
                result = f.read()
            if result and len(result) <= max_size:
                if logger:
                    logger.info(
                        f"Video compressed: {len(clean)} -> {len(result)} bytes "
                        f"(vbr={video_kbps}k)"
                    )
                return result
            if logger:
                logger.warning(
                    f"Compressed video still too large: {len(result)} bytes"
                )
    except Exception as e:
        if logger:
            logger.warning(f"Video compression failed: {e}")
    finally:
        for p in (p for p in (src_path, dst_path) if p):
            try:
                os.unlink(p)
            except Exception:
                pass

    return clean


# ---------------------------------------------------------------------------
# Universal entrypoint
# ---------------------------------------------------------------------------

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
GIF_EXTENSIONS = {".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".flv"}


def strip_metadata(data: bytes, filename: str = "", logger: logging.Logger | None = None) -> bytes:
    """
    Универсальная функция очистки метаданных.
    Определяет тип по расширению файла.

    Если filename не передан — пытается определить тип по magic bytes.
    """
    ext = os.path.splitext(filename.lower())[1] if filename else ""

    # Определение по magic bytes если расширение не передано
    if not ext and data:
        if data[:6] in (b"GIF87a", b"GIF89a"):
            ext = ".gif"
        elif data[:4] == b"\x89PNG":
            ext = ".png"
        elif data[:2] in (b"\xff\xd8",):
            ext = ".jpg"
        elif data[4:8] in (b"ftyp", b"moov", b"mdat"):
            ext = ".mp4"

    if ext in PHOTO_EXTENSIONS:
        return strip_photo_metadata(data)
    elif ext in GIF_EXTENSIONS:
        return strip_gif_metadata(data, logger=logger)
    elif ext in VIDEO_EXTENSIONS:
        return strip_video_metadata(data, logger=logger)
    else:
        if logger:
            logger.warning(f"Unknown file type (ext={ext!r}), metadata not stripped")
        return data


def fit_for_telegram(
    data: bytes,
    filename: str = "",
    logger: logging.Logger | None = None,
) -> bytes:
    """
    Универсальная функция: очищает метаданные + сжимает под лимиты Telegram.

    Лимиты Telegram:
      - фото: 10 MB
      - видео/GIF: 50 MB
    """
    ext = os.path.splitext(filename.lower())[1] if filename else ""

    if not ext and data:
        if data[:6] in (b"GIF87a", b"GIF89a"):
            ext = ".gif"
        elif data[:4] == b"\x89PNG":
            ext = ".png"
        elif data[:2] == b"\xff\xd8":
            ext = ".jpg"
        elif data[4:8] in (b"ftyp", b"moov", b"mdat"):
            ext = ".mp4"

    if ext in PHOTO_EXTENSIONS:
        return fit_photo_for_telegram(data, logger=logger)
    elif ext in GIF_EXTENSIONS:
        return fit_gif_for_telegram(data, logger=logger)
    elif ext in VIDEO_EXTENSIONS:
        return fit_video_for_telegram(data, logger=logger)
    else:
        if logger:
            logger.warning(f"Unknown file type (ext={ext!r}), returning as-is")
        return data