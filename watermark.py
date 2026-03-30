#!/usr/bin/env python3
"""
Модуль для наложения водяных знаков на изображения
"""

import logging
from PIL import Image, ImageDraw, ImageFont
import io

logger = logging.getLogger(__name__)


def add_watermark(image_data: bytes, text: str = "@eroslabai",
                  opacity: float = 0.3, font_size_ratio: float = 0.04) -> bytes:
    """
    Накладывает водяной знак на изображение.

    Args:
        image_data: Исходные данные изображения
        text: Текст водяного знака
        opacity: Прозрачность (0.0 - 1.0)
        font_size_ratio: Размер шрифта относительно высоты изображения

    Returns:
        bytes: Изображение с водяным знаком в оригинальном формате
    """
    try:
        # Определяем оригинальный формат ДО любых конвертаций
        src = Image.open(io.BytesIO(image_data))
        original_format = src.format  # 'JPEG', 'PNG', 'WEBP', 'GIF', None
        has_transparency = src.mode in ('RGBA', 'LA', 'P') or 'transparency' in src.info

        # Конвертируем в RGBA для работы с прозрачным слоем водяного знака
        image = src.convert("RGBA")
        width, height = image.size

        # Создаём прозрачный слой для водяного знака
        watermark_layer = Image.new('RGBA', image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark_layer)

        # Определяем размер шрифта
        font_size = max(20, int(height * font_size_ratio))

        # Пытаемся загрузить шрифт
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except Exception:
            try:
                font = ImageFont.truetype("DejaVuSans.ttf", font_size)
            except Exception:
                font = ImageFont.load_default()

        # Получаем размер текста
        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]

        # Позиция: нижний правый угол с отступом
        margin = 20
        x = width - text_width - margin
        y = height - text_height - margin

        # Цвет текста: белый с прозрачностью
        text_color = (255, 255, 255, int(255 * opacity))

        draw.text((x, y), text, font=font, fill=text_color)

        # Накладываем водяной знак
        result = Image.alpha_composite(image, watermark_layer)

        # Сохраняем в оригинальном формате
        output = io.BytesIO()

        if has_transparency or original_format == 'PNG':
            result.save(output, format='PNG', optimize=True)
            out_format = 'PNG'
        elif original_format == 'WEBP':
            result.convert('RGB').save(output, format='WEBP', quality=90)
            out_format = 'WEBP'
        else:
            # JPEG и всё остальное — сохраняем как JPEG, без альфа-канала
            result.convert('RGB').save(output, format='JPEG', quality=95, optimize=True)
            out_format = 'JPEG'

        logger.info(f"Watermark added: '{text}' (opacity: {int(opacity * 100)}%, format: {out_format})")
        return output.getvalue()

    except Exception as e:
        logger.error(f"Watermark error: {e}")
        return image_data  # Возвращаем оригинал при ошибке


def should_add_watermark(url: str) -> bool:
    """
    Проверяем, нужно ли добавлять водяной знак.

    Args:
        url: URL изображения

    Returns:
        bool: True если нужно добавить водяной знак
    """
    video_extensions = (".mp4", ".webm", ".gif")
    return not url.lower().endswith(video_extensions)


if __name__ == "__main__":
    import requests

    test_url = "https://example.com/test-image.jpg"

    try:
        response = requests.get(test_url, timeout=10)
        if response.status_code == 200:
            watermarked = add_watermark(response.content)
            with open("test_watermarked.jpg", "wb") as f:
                f.write(watermarked)
            print("✅ Watermark test successful")
        else:
            print("❌ Failed to download test image")
    except Exception as e:
        print(f"❌ Test failed: {e}")