"""
Генератор описаний: Vision (OpenRouter) → Groq → Pollinations → fallback
Стиль: дерзкая альтушка-анимешница. Без описания внешности напрямую.
"""

import sys
import io
import requests
import logging
import random
import urllib.parse
import base64
import os

# Если проблема с выводом в консоль
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

VISION_MODEL = "google/gemini-2.0-flash-001"


# ==================== ФИЛЬТРЫ ====================

NSFW_TRIGGER_TAGS = {
    "slut", "sex", "nude", "naked", "penis", "vagina", "cock",
    "pussy", "cum", "anal", "blowjob", "nsfw", "explicit", "porn",
    "hentai", "xxx", "nipple", "nipples", "breast", "breasts", "ass",
    "bondage", "bdsm", "fetish", "gangbang", "creampie", "ahegao",
    "spread_legs", "pussy_juice", "uncensored", "censored", "genitals"
}

TECHNICAL_TAGS = {
    "3d", "3d_(artwork)", "3d_animation", "3d_model", "ai_generated",
    "tagme", "animated", "video", "gif", "source_filmmaker", "sfm",
    "blender", "koikatsu", "honey_select", "daz3d", "mmd",
    "high_quality", "best_quality", "masterpiece", "absurdres",
    "highres", "score_9", "score_8", "score_7", "rating_explicit",
    "stable_diffusion", "novelai", "midjourney", "lora"
}

def _safe_tags(tags):
    """Только для хэштегов — убираем NSFW и технические теги."""
    result = []
    for t in tags:
        t_lower = t.lower()
        if t_lower in NSFW_TRIGGER_TAGS:
            continue
        if t_lower in TECHNICAL_TAGS:
            continue
        if t_lower.count("_") > 2:
            continue
        if any(c.isdigit() for c in t_lower):
            continue
        result.append(t)
    return result

def _prompt_tags(tags):
    """Теги для промпта — фильтруем мусор, переводим в читаемый вид."""
    result = []
    for t in tags:
        t_lower = t.lower()
        if t_lower in TECHNICAL_TAGS:
            continue
        if t_lower.count("_") > 2:
            continue
        if any(c.isdigit() for c in t_lower):
            continue
        clean = t.replace("_(artwork)", "").replace("_(character)", "")
        human = clean.replace("_", " ").strip()
        if human:
            result.append(human)
    return result[:8]


# ==================== ПЕРСОНА ====================

PERSONA = [
    "Ты дерзкая альтушка-анимешница, которая видела столько хентая что уже ничему не удивляется.",
    "Ты говоришь как девочка из аниме-тусовки — с сарказмом, лёгким матом и тёмным юмором.",
    "Ты циничная, немного грязная на язык, но с шармом. Иногда вырывается лёгкий мат.",
    "Ты провоцируешь читателя — дерзко, с намёком, иногда пошловато но со стилем.",
    "Ты как та самая альтушка из аниме-клуба которая знает всё но делает вид что ей похер.",
    "Холодная снаружи, огонь внутри. Иногда вырывается что-то такое что не сотрёшь из памяти.",
]


# ==================== ФОРМАТЫ (ОПТИМИЗИРОВАННЫЕ) ====================

# 70% утверждения / 15% вопросы / 15% двусмысленные фразы
FORMAT_TYPES = {
    # Утверждения с восклицанием (40%)
    "statement_exclaim": (
        "Напиши ОДНО короткое утверждение, которое заканчивается на '!' или '...'. "
        "Без вопросов. Дразни, провоцируй, будь дерзкой. Не длиннее 15 слов. Без кавычек."
    ),
    # Короткие цеплялки (20%)
    "hook": (
        "Напиши ОДНУ короткую фразу-крючок (5-10 слов) которая заставляет задержаться взглядом. "
        "Никаких вопросов. Только дерзкое утверждение или многозначительное многоточие."
    ),
    # Двусмысленные намёки (10%)
    "double_meaning": (
        "Напиши ОДНУ короткую двусмысленную фразу. Без вопросов. Намёк, игра слов, недосказанность. "
        "Читатель должен додумать сам. Не длиннее 12 слов."
    ),
    # Две строки (10%)
    "double": (
        "Напиши ДВЕ короткие строки. Первая — привлекает внимание. Вторая — добивает или переворачивает смысл. "
        "Никаких вопросов. Каждая строка — законченная мысль."
    ),
    # Вопросы — редко, только когда очень уместно (15%)
    "question_rare": (
        "Напиши ОДИН риторический вопрос (можно только если он реально усиливает эффект). "
        "Вопрос должен быть острым, провокационным, без банальностей вроде 'ну что?'. "
        "Не длиннее 12 слов. Без кавычек."
    ),
    # Добивающая фраза с многоточием (5%)
    "trailing": (
        "Напиши ОДНУ фразу которая заканчивается на '...' и оставляет чувство незавершённости. "
        "Без вопросов. Читатель должен хотеть продолжения. Не длиннее 10 слов."
    )
}

# Веса для выбора формата (чтобы вопросы выпадали редко)
FORMAT_WEIGHTS = {
    "statement_exclaim": 0.40,  # 40%
    "hook": 0.20,               # 20%
    "double_meaning": 0.10,     # 10%
    "double": 0.10,             # 10%
    "question_rare": 0.15,      # 15% (было 100%)
    "trailing": 0.05            # 5%
}


# ==================== VISION ====================

class VisionDetails:
    """Структурированные данные от Vision-модели"""
    def __init__(self):
        self.appearance = []      # детали внешности
        self.pose = []            # поза и жесты
        self.emotions = []        # эмоции и выражение лица
        self.background = []      # фон и окружение
        self.lighting = []        # свет и освещение
        self.props = []           # props и реквизит
        self.mood = []            # общая атмосфера и настроение

def _describe_image_structured(image_data: bytes = None, image_url: str = None) -> VisionDetails:
    """Получает структурированные данные от Vision-модели"""
    
    if not OPENROUTER_API_KEY:
        logger.warning("Vision: no OPENROUTER_API_KEY, skipping")
        return None

    if not image_data and not image_url:
        logger.warning("Vision: no image data or url provided")
        return None

    logger.info("Vision: attempting structured analysis...")

    try:
        # === Формируем image content ===
        if image_data:
            try:
                b64 = base64.b64encode(image_data).decode("utf-8")

                if image_data.startswith(b'\x89PNG'):
                    mime = "image/png"
                elif image_data.startswith(b'GIF'):
                    mime = "image/gif"
                else:
                    mime = "image/jpeg"

                img_content = {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,{b64}"
                    }
                }

            except Exception as e:
                logger.error(f"Vision: base64 encoding failed: {e}")
                return None

        else:
            img_content = {
                "type": "image_url",
                "image_url": {
                    "url": image_url
                }
            }

        # === Запрос с structured prompt ===
        structured_prompt = (
            "Проанализируй изображение и выдели следующие элементы:\n"
            "1. Внешность: цвет волос, глаз, одежда, аксессуары\n"
            "2. Поза: положение тела, жесты, поза\n"
            "3. Эмоции: выражение лица, настроение персонажа\n"
            "4. Фон: окружение, интерьер/экстерьер, детали\n"
            "5. Свет: тип освещения, тени, блики\n"
            "6. Props: предметы, реквизит, атрибуты\n"
            "7. Атмосфера: общее настроение сцены\n\n"
            "Ответ дай в формате JSON с полями: appearance, pose, emotions, background, lighting, props, mood.\n"
            "Каждое поле - массив из 2-3 кратких описательных фраз на русском языке.\n"
            "Избегай прямых упоминаний эротики, делай акцент на визуальных деталях и атмосфере."
        )

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": VISION_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            img_content,
                            {
                                "type": "text",
                                "text": structured_prompt
                            }
                        ]
                    }
                ],
                "max_tokens": 300
            },
            timeout=25
        )

        logger.info(f"Vision status: {response.status_code}")

        if response.status_code != 200:
            logger.warning(f"Vision API error {response.status_code}: {response.text[:200]}")
            return None

        # === Безопасный разбор ===
        try:
            data = response.json()
        except Exception as e:
            logger.error(f"Vision: JSON decode error: {e}")
            return None

        choices = data.get("choices")
        if not choices:
            logger.warning("Vision: no choices in response")
            return None

        message = choices[0].get("message", {})
        content = message.get("content")

        if not content or not isinstance(content, str):
            logger.warning("Vision: empty or invalid content")
            return None

        # === Парсим JSON ответ ===
        try:
            import json as json_module
            vision_data = json_module.loads(content.strip())
            
            details = VisionDetails()
            details.appearance = vision_data.get("appearance", [])
            details.pose = vision_data.get("pose", [])
            details.emotions = vision_data.get("emotions", [])
            details.background = vision_data.get("background", [])
            details.lighting = vision_data.get("lighting", [])
            details.props = vision_data.get("props", [])
            details.mood = vision_data.get("mood", [])
            
            # Фильтр пустых списков
            if not any([details.appearance, details.pose, details.emotions, 
                       details.background, details.lighting, details.props, details.mood]):
                logger.warning("Vision: no structured data extracted")
                return None
                
            logger.info(f"Vision structured data: {len(details.appearance)} appearance, "
                       f"{len(details.pose)} pose, {len(details.emotions)} emotions")
            return details
            
        except Exception as e:
            logger.error(f"Vision: JSON parsing error: {e}")
            return None

    except requests.exceptions.Timeout:
        logger.warning("Vision: request timeout")
        return None

    except Exception as e:
        logger.error(f"Vision error: {e}")
        return None

def _describe_image(image_data: bytes = None, image_url: str = None) -> str:
    """Описывает изображение через OpenRouter vision модель (устойчиво к ошибкам)."""

    if not OPENROUTER_API_KEY:
        logger.warning("Vision: no OPENROUTER_API_KEY, skipping")
        return None

    if not image_data and not image_url:
        logger.warning("Vision: no image data or url provided")
        return None

    logger.info("Vision: attempting image description...")

    try:
        # === Формируем image content ===
        if image_data:
            try:
                b64 = base64.b64encode(image_data).decode("utf-8")

                if image_data.startswith(b'\x89PNG'):
                    mime = "image/png"
                elif image_data.startswith(b'GIF'):
                    mime = "image/gif"
                else:
                    mime = "image/jpeg"

                img_content = {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,{b64}"
                    }
                }

            except Exception as e:
                logger.error(f"Vision: base64 encoding failed: {e}")
                return None

        else:
            img_content = {
                "type": "image_url",
                "image_url": {
                    "url": image_url
                }
            }

        # === Запрос ===
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": VISION_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            img_content,
                            {
                                "type": "text",
                                "text": (
                                    "Describe this image in Russian. "
                                    "Focus on mood, tension and key elements. "
                                    "Write 1-2 short evocative sentences. "
                                    "Avoid explicit words."
                                )
                            }
                        ]
                    }
                ],
                "max_tokens": 120
            },
            timeout=20
        )

        logger.info(f"Vision status: {response.status_code}")

        if response.status_code != 200:
            logger.warning(f"Vision API error {response.status_code}: {response.text[:200]}")
            return None

        # === Безопасный разбор ===
        try:
            data = response.json()
        except Exception as e:
            logger.error(f"Vision: JSON decode error: {e}")
            return None

        choices = data.get("choices")
        if not choices:
            logger.warning("Vision: no choices in response")
            return None

        message = choices[0].get("message", {})
        content = message.get("content")

        if not content or not isinstance(content, str):
            logger.warning("Vision: empty or invalid content")
            return None

        description = content.strip()

        if not description:
            logger.warning("Vision: content empty after strip")
            return None

        # === Фильтр отказов ===
        bad_phrases = [
            "cannot", "can't", "nsfw", "explicit", "sorry",
            "unable", "not allowed", "refuse", "i cannot"
        ]

        if any(p in description.lower() for p in bad_phrases):
            logger.warning(f"Vision rejected content: {description[:100]}")
            return None

        logger.info(f"Vision description: {description[:120]}")
        return description

    except requests.exceptions.Timeout:
        logger.warning("Vision: request timeout")
        return None

    except Exception as e:
        logger.error(f"Vision error: {e}")
        return None



# ==================== ПРОМПТ ====================

def _build_prompt(tags, vision_description=None, vision_details=None):
    persona_line = random.choice(PERSONA)
    # Выбираем формат с учётом весов
    format_key = random.choices(
        list(FORMAT_WEIGHTS.keys()),
        weights=list(FORMAT_WEIGHTS.values()),
        k=1
    )[0]
    format_instruction = FORMAT_TYPES[format_key]

    # Формируем атмосферу на основе Vision-данных
    atmosphere = _build_atmosphere(tags, vision_description, vision_details)

    prompt = f"""Ты — дерзкая альтушка-анимешница, пишешь провокационные подписи для Telegram-канала.
Ты не просто описываешь — ты дразнишь, цепляешь и играешь с читателем.

Характер: {persona_line}

Поведение:
— обращаешься как будто лично к читателю
— иногда дразнишь, иногда будто позволяешь больше, чем стоит
— создаёшь ощущение "почти, но не до конца"
— текст должен вызывать желание досмотреть/пересмотреть

Правила:
— никогда не описывай внешность напрямую
— никаких упоминаний "арт", "картинка" и т.п.
— никакой технической лексики
— только живой человеческий язык
— лёгкий мат можно, но редко и точно в цель
— избегай прямого описания действий — лучше намёк

Стиль:
— короткие строки (1–2 предложения максимум)
— можно разбивать на 2–4 строки
— первая строка — крючок (должна цеплять сразу)
— последняя — добивающая/двусмысленная

{atmosphere}

Формат: {format_instruction}

Добавь 1–2 эмодзи, не больше. Только текст, без пояснений."""

    return prompt

def _build_atmosphere(tags, vision_description=None, vision_details=None):
    """Строит атмосферу на основе Vision-данных и тегов"""
    
    if vision_details and isinstance(vision_details, VisionDetails):
        # Используем структурированные Vision-данные
        atmosphere_parts = []
        
        # Детали внешности
        if vision_details.appearance:
            appearance_str = ", ".join(vision_details.appearance[:2])
            atmosphere_parts.append(f"Внешность: {appearance_str}")
        
        # Поза и жесты
        if vision_details.pose:
            pose_str = ", ".join(vision_details.pose[:2])
            atmosphere_parts.append(f"Поза: {pose_str}")
        
        # Эмоции
        if vision_details.emotions:
            emotion_str = ", ".join(vision_details.emotions[:2])
            atmosphere_parts.append(f"Эмоции: {emotion_str}")
        
        # Фон
        if vision_details.background:
            bg_str = ", ".join(vision_details.background[:2])
            atmosphere_parts.append(f"Фон: {bg_str}")
        
        # Свет
        if vision_details.lighting:
            light_str = ", ".join(vision_details.lighting[:2])
            atmosphere_parts.append(f"Свет: {light_str}")
        
        # Props
        if vision_details.props:
            props_str = ", ".join(vision_details.props[:2])
            atmosphere_parts.append(f"Реквизит: {props_str}")
        
        # Общая атмосфера
        if vision_details.mood:
            mood_str = ", ".join(vision_details.mood[:2])
            atmosphere_parts.append(f"Настроение: {mood_str}")
        
        # Добавляем теги для контекста
        human_tags = _prompt_tags(tags)
        if human_tags:
            tags_str = ", ".join(human_tags[:3])
            atmosphere_parts.append(f"Теги: {tags_str}")
        
        if atmosphere_parts:
            return "Детали сцены:\n" + "\n".join(atmosphere_parts)
    
    # Fallback к старому поведению
    if vision_description:
        return f"Атмосфера от увиденного: {vision_description}"
    
    human_tags = _prompt_tags(tags)
    if human_tags:
        return f"Атмосфера: {', '.join(human_tags)}"
    
    return "Атмосфера: соблазн, страсть, интрига"


# ==================== ВАЛИДАЦИЯ ====================

def trim_to_sentence(text, max_len=250):
    if len(text) <= max_len:
        return text
    truncated = text[:max_len]
    last_punct = max(truncated.rfind('.'), truncated.rfind('!'), truncated.rfind('?'))
    if last_punct > max_len * 0.7:
        return truncated[:last_punct + 1]
    last_space = truncated.rfind(' ')
    if last_space > max_len * 0.7:
        return truncated[:last_space] + '...'
    return truncated + '...'

def _is_valid_response(text):
    bad_phrases = [
        "I'm sorry", "I can't", "I cannot", "<!DOCTYPE", "<html", "As an AI",
        "Не могу выполнить этот запрос", "Извините, я не могу", "Я не могу",
        "не могу выполнить", "не могу ответить", "не могу сгенерировать",
        "как ИИ", "как языковая модель"
    ]
    return bool(text) and len(text) > 10 and not any(p in text for p in bad_phrases)


# ==================== ПРОВАЙДЕРЫ ====================

def _try_groq(prompt):
    if not GROQ_API_KEY:
        logger.warning("No GROQ_API_KEY, skipping Groq")
        return None
    
    logger.info("Attempting Groq API call...")
    
    try:
        import json
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            data=json.dumps({
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 120,
                "temperature": 0.95
            }),
            timeout=15
        )
        
        logger.info(f"Groq API response status: {response.status_code}")
        
        if response.status_code == 200:
            try:
                data = response.json()
                # Безопасное извлечение текста
                try:
                    text = data["choices"][0]["message"]["content"]
                    if text and isinstance(text, str):
                        text = text.strip()
                        if _is_valid_response(text):
                            text = trim_to_sentence(text, max_len=250)
                            logger.info("Groq caption generated successfully")
                            return text
                        else:
                            logger.warning(f"Groq invalid response: {text[:100]}")
                    else:
                        logger.warning("Groq empty content")
                except (KeyError, IndexError, TypeError) as e:
                    logger.error(f"Groq parse error: {e}")
            except Exception as e:
                logger.error(f"Groq JSON decode error: {e}")
        else:
            logger.warning(f"Groq status {response.status_code}: {response.text[:100]}")
    except Exception as e:
        logger.error(f"Groq error: {e}")
    return None

def _try_pollinations(prompt):
    try:
        encoded = urllib.parse.quote(prompt)
        response = requests.get(f"https://text.pollinations.ai/{encoded}", timeout=20)
        if response.status_code == 200:
            text = response.text.strip()
            if _is_valid_response(text):
                text = trim_to_sentence(text, max_len=250)
                logger.info("Pollinations GET caption generated")
                return text
    except Exception as e:
        logger.warning(f"Pollinations GET failed: {e}")

    try:
        response = requests.post(
            "https://text.pollinations.ai/",
            json={"messages": [{"role": "user", "content": prompt}], "model": "openai", "private": True},
            headers={"Content-Type": "application/json"},
            timeout=20
        )
        if response.status_code == 200:
            text = response.text.strip()
            if _is_valid_response(text):
                text = trim_to_sentence(text, max_len=250)
                logger.info("Pollinations POST caption generated")
                return text
    except Exception as e:
        logger.error(f"Pollinations POST failed: {e}")
    return None


# ==================== FALLBACK ====================

FALLBACK_TEXTS = [
    "Ну давай… сделай вид, что тебе не интересно 😏",
    "Я молчу. Ты сам дальше знаешь 🖤",
    "Слова тут только мешают… правда? 🔥",
    "Ты ведь не случайно задержался 👀",
    "Не проси объяснений. Просто смотри 😈",
    "Я уже сказала достаточно… остальное сам додумаешь 😉",
    "Иногда лучше, когда я ничего не говорю 😌",
]


# ==================== СБОРКА ====================

def _format_caption(ai_text, tags, footer, content_header=None):
    safe_tags = _safe_tags(tags)
    hashtags = " ".join(f"#{t}" for t in safe_tags[:6]) if safe_tags else ""
    
    # Форматируем с разделителями и заголовком типа контента
    header_line = f"{content_header}\n" if content_header else ""
    if hashtags:
        return f"{header_line}{ai_text}\n━━━━━━━━━━━━━━━━━━━━━━\nTags: {hashtags}\n────────────────────\n{footer}"
    return f"{header_line}{ai_text}\n────────────────────\n{footer}"

def fallback_caption(tags, footer, content_header=None):
    text = random.choice(FALLBACK_TEXTS)
    safe_tags = _safe_tags(tags)
    tags_line = " ".join(f"#{t}" for t in safe_tags[:6]) if safe_tags else ""
    
    # Форматируем с разделителями и заголовком типа контента
    header_line = f"{content_header}\n" if content_header else ""
    if tags_line:
        return f"{header_line}{text}\n━━━━━━━━━━━━━━━━━━━━━━\nTags: {tags_line}\n────────────────────\n{footer}"
    return f"{header_line}{text}\n────────────────────\n{footer}"

def generate_caption(tags, rating, likes, image_data=None, image_url=None,
                     watermark="📢 @eroslabai", suggestion="💬 Предложка: @Haillord",
                     content_type="ai"):
    # Делаем "Предложка" кликабельной ссылкой на профиль
    clickable_suggestion = f"💬 [Предложка](tg://resolve?domain=Haillord)"
    footer = f"{watermark}\n{clickable_suggestion}"
    
    # Форматируем тип контента с цветными кружками
    if content_type == "ai":
        content_header = "🟢 AI Art | 🔴 3D"
    else:  # 3d
        content_header = "🔴 AI Art | 🟢 3D"
    
    # Пробуем структурированный vision анализ
    vision_details = None
    vision_description = None
    
    if image_data:
        logger.info(f"Attempting structured vision with image_data ({len(image_data)} bytes)")
        vision_details = _describe_image_structured(image_data=image_data)
        if not vision_details:
            # Fallback к простому описанию
            logger.info("Structured vision failed, trying simple description")
            vision_description = _describe_image(image_data=image_data)
    elif image_url:
        logger.info(f"Attempting structured vision with image_url: {image_url[:50]}...")
        vision_details = _describe_image_structured(image_url=image_url)
        if not vision_details:
            # Fallback к простому описанию
            logger.info("Structured vision failed, trying simple description")
            vision_description = _describe_image(image_url=image_url)
    else:
        logger.warning("No image_data or image_url provided for vision")
    
    # Логируем результаты vision анализа
    if vision_details:
        logger.info(f"Vision structured data: {len(vision_details.appearance)} appearance, "
                   f"{len(vision_details.pose)} pose, {len(vision_details.emotions)} emotions")
    elif vision_description:
        logger.info(f"Vision simple description: {vision_description[:100]}...")
    else:
        logger.info("Vision failed completely, using tags only")
    
    # Формируем промпт с приоритетом структурированных данных
    prompt = _build_prompt(tags, vision_description, vision_details)
    
    # Логируем промпт для отладки (только первые 200 символов)
    logger.debug(f"Prompt: {prompt[:200]}...")
    
    text = _try_groq(prompt)
    if not text:
        logger.info("Groq failed, trying Pollinations...")
        text = _try_pollinations(prompt)
    
    if not text:
        logger.warning("All caption generators failed, using fallback")
        return fallback_caption(tags, footer, content_header)
    
    return _format_caption(text, tags, footer, content_header)
