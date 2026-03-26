"""
Vision анализатор через Groq API
Анализирует изображения и возвращает описание
"""

import base64
import logging
import requests
from io import BytesIO

logger = logging.getLogger(__name__)

class VisionAnalyzer:
    """Анализ изображений через Groq Vision API"""
    
    def __init__(self, api_key):
        self.api_key = api_key
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
        self.model = "llama-3.2-90b-vision-preview"  # Бесплатная vision-модель
        
    def analyze(self, image_data, language="ru"):
        """
        Анализирует изображение и возвращает описание
        
        Args:
            image_data: байты изображения
            language: язык описания (ru/en)
        
        Returns:
            str: описание изображения или None при ошибке
        """
        if not self.api_key:
            logger.warning("Groq API key not set")
            return None
            
        try:
            # Кодируем картинку в base64
            base64_image = base64.b64encode(image_data).decode('utf-8')
            
            # Определяем промпт в зависимости от языка
            if language == "ru":
                prompt = "Опиши это изображение коротко, 5-10 слов, только ключевые детали. На русском."
            else:
                prompt = "Describe this image briefly, 5-10 words, key details only."
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 100,
                "temperature": 0.7
            }
            
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                description = result["choices"][0]["message"]["content"]
                logger.info(f"Groq analysis: {description}")
                return description.strip()
            else:
                logger.error(f"Groq API error: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Vision analysis error: {e}")
            return None
    
    def analyze_and_generate_tags(self, image_data):
        """
        Анализирует изображение и возвращает хэштеги
        
        Returns:
            list: список тегов или None
        """
        if not self.api_key:
            return None
            
        try:
            base64_image = base64.b64encode(image_data).decode('utf-8')
            
            prompt = """Опиши это изображение в виде коротких хэштегов на русском.
            Пример: #девушка #бикини #море #закат
            Только хэштеги, без лишнего текста."""
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 100
            }
            
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                tags_text = result["choices"][0]["message"]["content"]
                # Извлекаем хэштеги
                import re
                tags = re.findall(r'#(\w+)', tags_text)
                return tags[:8]  # максимум 8 тегов
            else:
                return None
                
        except Exception as e:
            logger.error(f"Tag generation error: {e}")
            return None