import asyncio
import logging
from io import BytesIO

from PIL import Image


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


def strip_metadata(image_data: bytes) -> bytes:
    """
    Полностью удаляет EXIF и другие метаданные из изображения.
    Возвращает чистое изображение без метаданных.
    """
    try:
        img = Image.open(BytesIO(image_data))
        
        # Конвертируем в RGB (удаляем альфа-канал если есть)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        
        # Создаем новое изображение без метаданных
        data = list(img.getdata())
        clean_img = Image.new(img.mode, img.size)
        clean_img.putdata(data)
        
        # Сохраняем без метаданных
        output = BytesIO()
        clean_img.save(output, format="JPEG", quality=95, optimize=True)
        return output.getvalue()
    except Exception as e:
        return image_data


def fit_photo_size_for_telegram(
    image_data: bytes,
    logger: logging.Logger | None = None,
    max_size: int = 10 * 1024 * 1024,
) -> bytes:
    if not image_data:
        return image_data

    try:
        # Всегда очищаем метаданные
        clean_data = strip_metadata(image_data)
        
        # Если размер уже в норме - возвращаем очищенное
        if len(clean_data) <= max_size:
            return clean_data
        
        img = Image.open(BytesIO(clean_data))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        for quality in (92, 88, 84, 80, 76, 72, 68):
            out = BytesIO()
            img.save(out, format="JPEG", quality=quality, optimize=True)
            candidate = out.getvalue()
            if len(candidate) <= max_size:
                if logger:
                    logger.info(f"Photo recompressed: {len(candidate)} bytes (q={quality})")
                return candidate

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
                        f"Photo downscaled: {len(candidate)} bytes ({width}x{height} -> {new_w}x{new_h})"
                    )
                return candidate
    except Exception as e:
        if logger:
            logger.warning(f"Could not fit photo size: {e}")

    return image_data
