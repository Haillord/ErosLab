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
    Накладывает водяной знак на изображение
    
    Args:
        image_data: Исходные данные изображения
        text: Текст водяного знака
        opacity: Прозрачность (0.0 - 1.0)
        font_size_ratio: Размер шрифта относительно высоты изображения
    
    Returns:
        bytes: Изображение с водяным знаком
    """
    try:
        # Загружаем изображение
        image = Image.open(io.BytesIO(image_data)).convert("RGBA")
        width, height = image.size
        
        # Создаем прозрачный слой для водяного знака
        watermark_layer = Image.new('RGBA', image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark_layer)
        
        # Определяем размер шрифта
        font_size = max(20, int(height * font_size_ratio))
        
        # Пытаемся загрузить шрифт
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except:
            try:
                font = ImageFont.truetype("DejaVuSans.ttf", font_size)
            except:
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
        
        # Рисуем текст
        draw.text((x, y), text, font=font, fill=text_color)
        
        # Накладываем водяной знак
        result = Image.alpha_composite(image, watermark_layer)
        
        # Конвертируем обратно в bytes
        output = io.BytesIO()
        if image.mode in ('RGBA', 'LA') or 'transparency' in image.info:
            result.save(output, format='PNG', optimize=True)
        else:
            result.convert('RGB').save(output, format='JPEG', quality=95, optimize=True)
        
        logger.info(f"Watermark added: {text} (opacity: {opacity*100}%)")
        return output.getvalue()
        
    except Exception as e:
        logger.error(f"Watermark error: {e}")
        return image_data  # Возвращаем оригинальное изображение при ошибке

def should_add_watermark(url: str) -> bool:
    """
    Проверяем, нужно ли добавлять водяной знак
    
    Args:
        url: URL изображения
    
    Returns:
        bool: True если нужно добавить водяной знак
    """
    # Добавляем водяной знак только для изображений, не для видео
    video_extensions = (".mp4", ".webm", ".gif")
    return not url.lower().endswith(video_extensions)

def add_watermark_to_video_thumbnail(video_data: bytes, text: str = "@eroslabai", 
                                   opacity: float = 0.3, font_size_ratio: float = 0.04) -> bytes:
    """
    Накладывает водяной знак на thumbnail видео
    
    Args:
        video_data: Исходные данные видео
        text: Текст водяного знака
        opacity: Прозрачность (0.0 - 1.0)
        font_size_ratio: Размер шрифта относительно высоты thumbnail
    
    Returns:
        bytes: Видео с водяным знаком на thumbnail
    """
    try:
        import tempfile
        import subprocess
        import os
        
        # Создаем временные файлы
        tmp_in = None
        tmp_out = None
        tmp_thumb = None
        
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp.write(video_data)
            tmp_in = tmp.name

        tmp_out = tmp_in + "_watermarked.mp4"
        tmp_thumb = tmp_in + "_thumb.png"

        try:
            # 1. Извлекаем thumbnail из видео
            cmd_thumb = [
                'ffmpeg', '-y', '-i', tmp_in,
                '-ss', '2', '-vframes', '1',
                '-vf', 'scale=512:-1',
                tmp_thumb
            ]
            result = subprocess.run(cmd_thumb, capture_output=True, timeout=10)
            if result.returncode != 0:
                logger.warning("ffmpeg thumbnail extraction failed")
                return video_data

            # 2. Накладываем водяной знак на thumbnail
            thumbnail_with_watermark = add_watermark(
                open(tmp_thumb, 'rb').read(), 
                text=text, 
                opacity=opacity, 
                font_size_ratio=font_size_ratio
            )

            # 3. Создаем временное видео с водяным знаком
            tmp_watermarked_thumb = tmp_in + "_watermarked_thumb.png"
            with open(tmp_watermarked_thumb, 'wb') as f:
                f.write(thumbnail_with_watermark)

            # 4. Накладываем watermark на все видео (но с низкой интенсивностью)
            # чтобы он был виден на thumbnail, но не мешал просмотру
            cmd_watermark = [
                'ffmpeg', '-y', '-i', tmp_in,
                '-i', tmp_watermarked_thumb,
                '-filter_complex', 
                f"[0:v][1:v]overlay=main_w-overlay_w-20:main_h-overlay_h-20:format=auto",
                '-c:a', 'copy',
                '-c:v', 'libx264',
                '-crf', '23',
                '-preset', 'medium',
                tmp_out
            ]
            
            result = subprocess.run(cmd_watermark, capture_output=True, timeout=30)
            if result.returncode != 0:
                logger.warning("ffmpeg watermark failed")
                return video_data

            # 5. Читаем результат
            with open(tmp_out, 'rb') as f:
                watermarked_video = f.read()

            logger.info(f"Video watermark added: {text} (opacity: {opacity*100}%)")
            return watermarked_video

        finally:
            # Удаляем временные файлы
            for tmp_file in [tmp_in, tmp_out, tmp_thumb, tmp_watermarked_thumb]:
                if tmp_file and os.path.exists(tmp_file):
                    try:
                        os.unlink(tmp_file)
                    except:
                        pass

    except Exception as e:
        logger.error(f"Video watermark error: {e}")
        return video_data  # Возвращаем оригинальное видео при ошибке

if __name__ == "__main__":
    # Тестирование
    import requests
    
    test_url = "https://example.com/test-image.jpg"
    
    try:
        response = requests.get(test_url, timeout=10)
        if response.status_code == 200:
            watermarked = add_watermark(response.content)
            with open("test_watermarked.png", "wb") as f:
                f.write(watermarked)
            print("✅ Watermark test successful")
        else:
            print("❌ Failed to download test image")
    except Exception as e:
        print(f"❌ Test failed: {e}")