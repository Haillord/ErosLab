#!/usr/bin/env python3
"""
Интеллектуальный фильтр качества контента
Оценивает изображения по техническим и визуальным критериям
"""

import logging
from PIL import Image
import io
import numpy as np
from caption_generator import _describe_image

logger = logging.getLogger(__name__)

class QualityFilter:
    """Фильтр качества изображений"""
    
    def __init__(self, min_resolution=512, min_score=7.0):
        self.min_resolution = min_resolution
        self.min_score = min_score
    
    def analyze_image(self, image_data: bytes) -> dict:
        """Полный анализ качества изображения"""
        try:
            # Загружаем изображение
            image = Image.open(io.BytesIO(image_data))
            width, height = image.size
            
            # 1. Технический анализ
            technical_score = self._analyze_technical(image, width, height)
            
            # 2. Визуальный анализ (через Vision)
            visual_score = self._analyze_visual(image_data)
            
            # 3. Композиционный анализ
            composition_score = self._analyze_composition(image)
            
            # 4. Общая оценка
            total_score = (technical_score + visual_score + composition_score) / 3
            
            result = {
                'score': round(total_score, 1),
                'pass': total_score >= self.min_score,
                'technical_score': technical_score,
                'visual_score': visual_score,
                'composition_score': composition_score,
                'resolution': f"{width}x{height}",
                'reasons': []
            }
            
            # Собираем причины отказа
            if technical_score < 6.0:
                result['reasons'].append(f"Низкое техническое качество: {technical_score}")
            if visual_score < 6.0:
                result['reasons'].append(f"Слабая визуальная привлекательность: {visual_score}")
            if composition_score < 6.0:
                result['reasons'].append(f"Плохая композиция: {composition_score}")
            
            logger.info(f"Quality analysis: {result['score']}/10 ({result['resolution']})")
            return result
            
        except Exception as e:
            logger.error(f"Quality analysis failed: {e}")
            return {
                'score': 0.0,
                'pass': False,
                'reasons': [f"Ошибка анализа: {str(e)}"]
            }
    
    def _analyze_technical(self, image: Image.Image, width: int, height: int) -> float:
        """Технический анализ: разрешение, резкость, цвета"""
        score = 0.0
        
        # 1. Разрешение
        min_dim = min(width, height)
        if min_dim >= 1024:
            score += 4.0
        elif min_dim >= 768:
            score += 3.0
        elif min_dim >= 512:
            score += 2.0
        elif min_dim >= 256:
            score += 1.0
        else:
            score += 0.0
        
        # 2. Резкость (упрощенный анализ)
        try:
            # Конвертируем в numpy для анализа
            img_array = np.array(image.convert('L'))
            # Вычисляем градиенты (резкость)
            grad_x = np.abs(np.diff(img_array, axis=1))
            grad_y = np.abs(np.diff(img_array, axis=0))
            sharpness = (np.mean(grad_x) + np.mean(grad_y)) / 2
            
            if sharpness > 20:
                score += 3.0
            elif sharpness > 10:
                score += 2.0
            elif sharpness > 5:
                score += 1.0
            else:
                score += 0.0
        except:
            score += 1.0  # Если не удалось проанализировать резкость
        
        # 3. Цветовой баланс
        try:
            # Проверяем, не слишком ли яркие или тусклые цвета
            img_rgb = np.array(image.convert('RGB'))
            brightness = np.mean(img_rgb)
            
            if 80 <= brightness <= 180:
                score += 2.0
            elif 50 <= brightness <= 220:
                score += 1.0
            else:
                score += 0.0
        except:
            score += 1.0
        
        return min(score, 10.0)
    
    def _analyze_visual(self, image_data: bytes) -> float:
        """Визуальный анализ через Vision модель"""
        try:
            # Запрашиваем у Vision оценку визуальной привлекательности
            vision_prompt = (
                "Оцени визуальную привлекательность этого изображения по 10-балльной шкале. "
                "Учитывай: композицию, цветовую гармонию, эстетичность, общее впечатление. "
                "Ответ дай только числом от 1 до 10."
            )
            
            description = _describe_image(image_data=image_data)
            if description:
                # Пытаемся извлечь оценку из описания
                # Это упрощенный вариант - в реальности можно использовать отдельный API
                return 7.0  # Базовая оценка для упрощения
            else:
                return 5.0
        except:
            return 5.0
    
    def _analyze_composition(self, image: Image.Image) -> float:
        """Анализ композиции: правила третей, баланс, гармония"""
        score = 0.0
        
        try:
            width, height = image.size
            
            # Проверяем, не находится ли главный объект в центре (плохо)
            # Упрощенный анализ - в реальности можно использовать object detection
            center_weight = 0.5
            
            # Проверяем баланс света и тени
            img_array = np.array(image.convert('L'))
            histogram = np.histogram(img_array, bins=10)[0]
            
            # Хорошо если есть и светлые, и темные участки
            dark_pixels = np.sum(histogram[:3])
            light_pixels = np.sum(histogram[7:])
            mid_pixels = np.sum(histogram[3:7])
            
            if mid_pixels > dark_pixels and mid_pixels > light_pixels:
                score += 3.0
            elif dark_pixels > 0 and light_pixels > 0:
                score += 2.0
            else:
                score += 1.0
            
            # Проверяем симметрию (иногда хорошо, иногда плохо)
            left_half = img_array[:, :width//2]
            right_half = img_array[:, width//2:]
            
            symmetry = np.corrcoef(left_half.flatten(), right_half.flatten())[0, 1]
            if -0.5 < symmetry < 0.5:  # Не слишком симметрично
                score += 2.0
            else:
                score += 1.0
            
            # Размер изображения
            if width * height > 500000:
                score += 2.0
            elif width * height > 200000:
                score += 1.0
            else:
                score += 0.5
            
        except Exception as e:
            logger.warning(f"Composition analysis error: {e}")
            score = 4.0  # Базовая оценка при ошибке
        
        return min(score, 10.0)

def filter_posts_by_quality(posts, image_data_list, min_score=7.0):
    """Фильтрация постов по качеству"""
    quality_filter = QualityFilter(min_score=min_score)
    
    for i, (post, image_data) in enumerate(zip(posts, image_data_list)):
        logger.info(f"Analyzing quality of post {post.get('id', i)}...")
        
        quality_result = quality_filter.analyze_image(image_data)
        
        if quality_result['pass']:
            logger.info(f"Post {post.get('id')} accepted: quality {quality_result['score']}")
            return post, image_data, quality_result
        else:
            reasons = ', '.join(quality_result['reasons'])
            logger.info(f"Post {post.get('id')} rejected: {reasons}")
    
    logger.warning("No posts passed quality filter")
    return None, None, None

if __name__ == "__main__":
    # Тестирование фильтра
    import requests
    
    # Пример использования
    test_url = "https://example.com/test-image.jpg"
    
    try:
        response = requests.get(test_url, timeout=10)
        if response.status_code == 200:
            quality_filter = QualityFilter()
            result = quality_filter.analyze_image(response.content)
            print(f"Quality result: {result}")
        else:
            print("Failed to download test image")
    except Exception as e:
        print(f"Test failed: {e}")