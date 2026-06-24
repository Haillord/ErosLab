"""
Steam Workshop API wrapper for Wallpaper Engine (App ID: 431960)
Парсит популярные обои из мастерской Steam Wallpaper Engine.
Возвращает items в формате совместимом с wallpapers_bot.py.
"""

import logging
import os
import time
import requests
import json

logger = logging.getLogger("ErosLab.SteamWorkshop")

# Wallpaper Engine App ID
WALLPAPER_ENGINE_APPID = 431960

# Steam Web API Key (получить на https://steamcommunity.com/dev/apikey)
STEAM_API_KEY = os.environ.get("STEAM_API_KEY", "")

# Настройки фильтрации
MIN_SUBSCRIPTIONS = int(os.environ.get("STEAM_MIN_SUBSCRIPTIONS", "10"))
MAX_RESULTS = int(os.environ.get("STEAM_MAX_RESULTS", "200"))
ALLOW_NSFW = os.environ.get("STEAM_ALLOW_NSFW", "false").lower() in ("1", "true", "yes", "on")


def _request_with_backoff(url, params, headers, max_retries=3):
    """Request с retry при 429 и 500."""
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            if r.status_code == 429:
                wait = 2 ** attempt * 5
                logger.warning(f"Steam rate limited (429), waiting {wait}s before retry {attempt + 1}/{max_retries}")
                time.sleep(wait)
                continue
            if r.status_code >= 500:
                wait = 2 + attempt * 2
                logger.warning(f"Steam server error {r.status_code}, retry {attempt + 1}/{max_retries}")
                if attempt >= max_retries - 1:
                    return None
                time.sleep(wait)
                continue
            if r.status_code == 403:
                logger.error(f"Steam API 403 Forbidden - check API key or permissions")
                return None
            r.raise_for_status()
            return r
        except requests.exceptions.Timeout:
            logger.warning(f"Steam timeout on attempt {attempt + 1}/{max_retries}")
            if attempt < max_retries - 1:
                time.sleep(3)
        except requests.exceptions.HTTPError as e:
            if r.status_code >= 500:
                logger.warning(f"Steam server error {r.status_code}, retry {attempt + 1}/{max_retries}")
                time.sleep(2 ** attempt * 2)
            else:
                raise
        except Exception as e:
            logger.error(f"Steam request error: {e}")
            raise
    return None


def _is_safe_content(item: dict) -> bool:
    """
    Проверяет, является ли контент безопасным (16+ sexy, без 18+ порно).
    Steam Workshop использует content descriptors для маркировки контента.
    
    Пропускаем: mild nudity, suggestive, sexy (но не явное)
    Блокируем: explicit nudity, sexual content, porn, hentai, adult
    """
    # Если NSFW разрешен - пропускаем фильтрацию по тегам
    if ALLOW_NSFW:
        # Все равно проверяем visibility и banned статус
        if item.get("visibility") != 0:  # 0 = public
            return False
        if item.get("banned") == 1 or item.get("banned") is True:
            return False
        return True
    
    # Проверяем теги контента (content descriptors)
    tags = item.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    
    # Строго блокируемые теги (18+ порно)
    blocked_keywords = {
        "porn", "hentai", "explicit", "adult only", "hardcore",
        "sexual violence", "non-consensual", "rape", "incest"
    }
    
    # Теги которые блокируем только если есть "explicit" или "sexual"
    # (mild nudity, suggestive, sexy - OK)
    conditional_blocked = {
        "nudity", "sexual content", "erotic", "mature"
    }
    
    tag_names = [tag.get("name", "").lower() for tag in tags if isinstance(tag, dict)]
    tag_string = " ".join(tag_names)
    
    # Строго блокируем
    for keyword in blocked_keywords:
        if keyword in tag_string:
            return False
    
    # Условно блокируем - только если есть explicit/sexual
    for keyword in conditional_blocked:
        if keyword in tag_string:
            # Если есть "explicit" или "sexual" - блокируем
            if "explicit" in tag_string or "sexual" in tag_string:
                return False
    
    # Проверяем visibility - только public контент
    if item.get("visibility") != 0:  # 0 = public
        return False
    
    # Проверяем banned/rejected статус
    if item.get("banned") == 1 or item.get("banned") is True:
        return False
    
    return True


def _extract_preview_url(item: dict, prefer_video: bool = True) -> tuple:
    """
    Извлекает URL превью и MIME-тип.
    Приоритет: видео > высокое качество превью > обычное превью.
    
    Returns:
        (url, mime_type)
    """
    preview_url = None
    mime_type = "image/jpeg"
    
    # Сначала проверяем video_preview если есть (несколько вариантов полей)
    if prefer_video:
        video_preview = (
            item.get("video_preview_url") or 
            item.get("preview_video_url") or
            item.get("video_url") or
            item.get("youtube_preview_url")
        )
        if video_preview:
            return video_preview, "video/mp4"
    
    # Пробуем получить URL на полный файл (file_url)
    file_url = item.get("file_url")
    if file_url:
        # Проверяем что это изображение или видео
        if file_url.lower().endswith(('.mp4', '.webm', '.gif')):
            return file_url, "video/mp4" if file_url.lower().endswith(('.mp4', '.webm')) else "image/gif"
        if file_url.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
            return file_url, "image/jpeg" if file_url.lower().endswith(('.jpg', '.jpeg')) else "image/png"
    
    # Steam Workshop возвращает превью в разных форматах
    # Пробуем получить высококачественное превью из списка previews
    previews = item.get("previews", [])
    if previews and isinstance(previews, list):
        # Сначала ищем видео превью в списке
        if prefer_video:
            for preview in previews:
                if not isinstance(preview, dict):
                    continue
                url = preview.get("url")
                if url and url.lower().endswith(('.mp4', '.webm', '.gif')):
                    return url, "video/mp4" if url.lower().endswith(('.mp4', '.webm')) else "image/gif"
        
        # Ищем превью с максимальным разрешением
        best_preview = None
        max_size = 0
        
        for preview in previews:
            if not isinstance(preview, dict):
                continue
            
            url = preview.get("url")
            if not url:
                continue
            
            # Steam URL может содержать размер в имени файла, например:
            # 192x192, 616x353, 1920x1080 и т.д.
            # Ищем максимальный размер
            import re
            size_match = re.search(r'(\d+)x(\d+)', url)
            if size_match:
                width = int(size_match.group(1))
                height = int(size_match.group(2))
                size = width * height
                if size > max_size:
                    max_size = size
                    best_preview = url
            else:
                # Если размер не указан, берем как есть
                if not best_preview:
                    best_preview = url
        
        if best_preview:
            preview_url = best_preview
    
    # Если не нашли в previews, пробуем preview_url
    if not preview_url:
        preview_url = item.get("preview_url")
    
    # Fallback: пробуем извлечь из preview_file если есть
    if not preview_url:
        preview_file = item.get("preview_file")
        if preview_file:
            # preview_file может быть числом (UGCHandle) или строкой
            if isinstance(preview_file, str):
                preview_url = preview_file
    
    # Fallback: конструируем URL из publishedfileid
    if not preview_url:
        publishedfileid = item.get("publishedfileid")
        if publishedfileid:
            # Steam CDN format для превью
            preview_url = f"https://steamuserimages-a.akamaihd.net/ugc/{publishedfileid}/"
    
    if preview_url:
        # Определяем MIME по расширению
        url_lower = preview_url.lower()
        if url_lower.endswith('.mp4') or url_lower.endswith('.webm'):
            mime_type = "video/mp4"
        elif url_lower.endswith('.png'):
            mime_type = "image/png"
        elif url_lower.endswith('.gif'):
            mime_type = "image/gif"
        else:
            mime_type = "image/jpeg"
    
    return preview_url, mime_type


def _extract_tags(item: dict) -> list:
    """Извлекает теги из workshop item."""
    tags = []
    raw_tags = item.get("tags", [])
    
    if isinstance(raw_tags, list):
        for tag in raw_tags:
            if isinstance(tag, dict):
                tag_name = tag.get("name", "")
                if tag_name:
                    tags.append(tag_name)
            elif isinstance(tag, str):
                tags.append(tag)
    
    # Также добавляем теги из short_description если есть
    description = item.get("short_description", "")
    if description and len(description) < 200:
        words = description.split()
        tags.extend([w for w in words if len(w) > 3])
    
    return tags[:15]  # Ограничиваем количество тегов


def fetch_steam_workshop(max_pages: int = 30):
    """
    Парсит популярные обои из Steam Workshop Wallpaper Engine.
    
    Стратегия:
    1. QueryFiles с сортировкой по подписчикам (RANKED_BY_TOTAL_UNIQUE_SUBSCRIPTIONS)
    2. Только ALL_TIME (без временных фильтров для разнообразия)
    3. Фильтруем NSFW контент
    4. Рандомизируем результаты для разнообразия
    5. Возвращаем результаты
    
    Args:
        max_pages: количество страниц для парсинга
        
    Returns:
        list of dict в формате совместимом с wallpapers_bot.py
    """
    import random
    
    if not STEAM_API_KEY:
        logger.warning("STEAM_API_KEY not set in environment variables")
        logger.info("You can get a free API key at https://steamcommunity.com/dev/apikey")
        return []
    
    logger.info(f"Fetching Steam Workshop for Wallpaper Engine (AppID: {WALLPAPER_ENGINE_APPID})")
    
    url = "https://api.steampowered.com/IPublishedFileService/QueryFiles/v1/"
    
    all_items = []
    
    # Query types для разнообразия
    # 0 = RANKED_BY_VOTE, 1 = RANKED_BY_PUBLICATION_DATE, 2 = RANKED_BY_LAST_UPDATED_DATE
    # 3 = RANKED_BY_TOTAL_UNIQUE_SUBSCRIPTIONS, 4 = RANKED_BY_TIMES_SUBSCRIBED, 5 = RANKED_BY_FAVORITES
    query_types = [1, 3, 4, 5]  # Дата публикации, подписчики, фавориты
    
    for query_type in query_types:
        logger.info(f"Fetching with query_type={query_type}")
        
        cursor = "*"  # Начальный курсор для пагинации
        page_count = 0
        
        while cursor and page_count < max_pages:
            params = {
                "key": STEAM_API_KEY,
                "appid": WALLPAPER_ENGINE_APPID,
                "query_type": query_type,
                "cursor": cursor,
                "numperpage": 50,
                "return_details": True,
                "return_previews": True,
            }
            
            try:
                r = _request_with_backoff(url, params=params, headers={})
                if r is None:
                    logger.warning(f"Steam Workshop cursor request failed")
                    break
                
                data = r.json()
                response = data.get("response", {})
                items = response.get("publishedfiledetails", [])
                total = response.get("total", 0)
                
                # Получаем следующий курсор для пагинации
                cursor = response.get("next_cursor")
                
                if not items:
                    logger.info(f"Steam Workshop: no items for cursor request")
                    break
                
                page_count += 1
                logger.info(f"Steam Workshop page {page_count}: got {len(items)} items (total: {total})")
                
                # Логируем первый item для отладки (подробно)
                if items and page_count == 1:
                    logger.debug(f"Sample item keys: {list(items[0].keys())}")
                    logger.debug(f"Sample item: {json.dumps(items[0], indent=2, default=str)[:1000]}")
                
                for item in items:
                    # Проверяем безопасность контента
                    if not _is_safe_content(item):
                        continue
                    
                    # Фильтруем по минимальному количеству подписок
                    subscriptions = item.get("subscriptions", 0)
                    if subscriptions < MIN_SUBSCRIPTIONS:
                        continue
                    
                    # Извлекаем превью
                    preview_url, mime_type = _extract_preview_url(item, prefer_video=True)
                    if not preview_url:
                        logger.debug(f"No preview URL for item {item.get('publishedfileid')}")
                        continue
                    
                    # Извлекаем теги
                    tags = _extract_tags(item)
                    
                    # Формируем item в совместимом формате
                    workshop_item = {
                        "id": f"steam_{item['publishedfileid']}",
                        "url": preview_url,
                        "tags": tags,
                        "likes": subscriptions,  # Используем подписчики как "лайки"
                        "rating": "safe",  # Мы уже отфильтровали NSFW
                        "post_id": item.get("publishedfileid"),
                        "mime": mime_type,
                        "createdAt": item.get("time_created"),
                        "source": "steam_workshop",
                        "title": item.get("title", ""),
                        "author": item.get("creator", ""),
                        "file_size": item.get("file_size", 0),
                    }
                    
                    all_items.append(workshop_item)
            
            except Exception as e:
                logger.error(f"Steam Workshop cursor request error: {e}")
                break
        
        # Если набрали достаточно результатов, прерываем
        if len(all_items) >= MAX_RESULTS:
            logger.info(f"Collected {len(all_items)} items, stopping early")
            break
    
    # Рандомизируем результаты для разнообразия
    random.shuffle(all_items)
    
    # Ограничиваем количество результатов
    all_items = all_items[:MAX_RESULTS]
    
    logger.info(f"Steam Workshop: found {len(all_items)} suitable wallpapers (randomized)")
    if all_items:
        logger.info(f"Sample wallpaper: {all_items[0]['title']} (subscriptions: {all_items[0]['likes']})")
    
    return all_items


def fetch_steam_workshop_by_ids(publishedfileids: list):
    """
    Получает детальную информацию о конкретных workshop items по их ID.
    Использует GetPublishedFileDetails API (требует POST).
    
    Args:
        publishedfileids: список ID workshop items
        
    Returns:
        list of dict с детальной информацией
    """
    if not STEAM_API_KEY:
        logger.warning("STEAM_API_KEY not set")
        return []
    
    if not publishedfileids:
        return []
    
    url = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
    
    # Steam API требует POST с JSON body
    payload = {
        "key": STEAM_API_KEY,
        "publishedfileids": publishedfileids
    }
    
    try:
        r = requests.post(url, json=payload, timeout=30)
        r.raise_for_status()
        
        data = r.json()
        items = data.get("response", {}).get("publishedfiledetails", [])
        
        logger.info(f"Got details for {len(items)} workshop items")
        return items
        
    except Exception as e:
        logger.error(f"Error fetching workshop details: {e}")
        return []
