"""
rule34video.com scraper
Парсит видео с rule34video.com, возвращает список items
в формате совместимом с civitai_bot.py.

Установка зависимостей:
    pip install requests beautifulsoup4 lxml
"""

import logging
import random
import re
import time

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("ErosLab.Rule34Video")

# ── Константы ──────────────────────────────────────────────────────────────────

BASE_URL = "https://rule34video.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE_URL,
}

# Теги для поиска — несколько вариантов, выбираем случайный для разнообразия
SEARCH_TAG_SETS = [
    "3d animated",
    "sfm animated",
    "blender animated",
    "3d hentai",
    "animated sfm",
]

# Теги-стоп-слова специфичные для rule34video
R34V_STOP_WORDS = {
    "3d", "animated", "sfm", "blender", "hentai", "video",
    "rule34", "rule34video", "r34", "xxx", "porn", "hd",
    "source_filmmaker", "koikatsu", "honey_select",
}


# ── Вспомогательные функции ───────────────────────────────────────────────────

def _get(url: str, params: dict = None, retries: int = 3) -> requests.Response | None:
    """GET-запрос с ретраями и задержкой."""
    for attempt in range(retries):
        try:
            r = requests.get(
                url,
                params=params,
                headers=HEADERS,
                timeout=20,
                allow_redirects=True,
            )
            if r.status_code == 200:
                return r
            if r.status_code == 429:
                wait = 5 * (attempt + 1)
                logger.warning(f"r34video: rate limited, waiting {wait}s")
                time.sleep(wait)
                continue
            logger.warning(f"r34video: HTTP {r.status_code} for {url}")
            return None
        except requests.exceptions.Timeout:
            logger.warning(f"r34video: timeout attempt {attempt + 1}/{retries}")
            time.sleep(2)
        except Exception as e:
            logger.error(f"r34video: request error: {e}")
            return None
    return None


def _parse_video_list(html: str) -> list[dict]:
    """
    Парсит страницу поиска/категории и возвращает список:
    [{"id": "r34v_12345", "page_url": "...", "title": "...", "thumb": "..."}]
    """
    soup = BeautifulSoup(html, "lxml")
    items = []

    # rule34video использует div.item для каждого видео в списке
    for block in soup.select("div.item"):
        link_tag = block.select_one("a.th")
        if not link_tag:
            # Попробуем альтернативный селектор
            link_tag = block.select_one("a[href*='/videos/']")
        if not link_tag:
            continue

        href = link_tag.get("href", "")
        if "/videos/" not in href:
            continue

        # Вытащим ID из URL вида /videos/123456/title/
        match = re.search(r"/videos/(\d+)/", href)
        if not match:
            continue
        video_id = match.group(1)

        title = ""
        title_tag = block.select_one(".thumb_title") or block.select_one("span.title")
        if title_tag:
            title = title_tag.get_text(strip=True)

        thumb = ""
        img_tag = block.select_one("img")
        if img_tag:
            thumb = img_tag.get("data-src") or img_tag.get("src") or ""

        # Рейтинг/лайки если есть
        likes = 0
        rating_tag = block.select_one(".rate-box .score") or block.select_one(".rating")
        if rating_tag:
            try:
                likes = int(re.sub(r"[^\d]", "", rating_tag.get_text()))
            except (ValueError, TypeError):
                pass

        # Продолжительность
        duration = ""
        dur_tag = block.select_one(".duration") or block.select_one("span.dur")
        if dur_tag:
            duration = dur_tag.get_text(strip=True)

        items.append({
            "id": f"r34v_{video_id}",
            "page_url": href if href.startswith("http") else BASE_URL + href,
            "title": title,
            "thumb": thumb,
            "likes": likes,
            "duration": duration,
        })

    return items


def _extract_direct_url(page_html: str) -> str | None:
    """
    Извлекает прямую ссылку на mp4 со страницы видео.
    rule34video хранит URL в <source> или в JS-переменной.
    """
    soup = BeautifulSoup(page_html, "lxml")

    # Метод 1: <source src="...mp4">
    for source in soup.select("source[type='video/mp4'], source[src*='.mp4']"):
        src = source.get("src", "")
        if src and ".mp4" in src:
            return src

    # Метод 2: <video src="...">
    video_tag = soup.select_one("video[src*='.mp4']")
    if video_tag:
        return video_tag.get("src")

    # Метод 3: JS переменная — ищем в script-тегах
    for script in soup.find_all("script"):
        text = script.string or ""

        # Паттерн: video_url = "https://...mp4"
        m = re.search(r'["\']?video_url["\']?\s*[=:]\s*["\']([^"\']+\.mp4[^"\']*)["\']', text)
        if m:
            return m.group(1)

        # Паттерн: "file":"https://...mp4"
        m = re.search(r'"file"\s*:\s*"([^"]+\.mp4[^"]*)"', text)
        if m:
            url = m.group(1).replace("\\", "")
            return url

        # Паттерн: sources:[{file:"..."}]
        m = re.search(r'sources\s*:\s*\[\s*\{[^}]*file\s*:\s*["\']([^"\']+\.mp4[^"\']*)["\']', text)
        if m:
            return m.group(1)

        # Паттерн: jwplayer setup с file
        m = re.search(r'jwplayer\([^)]+\)\.setup\([^)]*file["\s]*:["\s]*["\']([^"\']+\.mp4[^"\']*)["\']', text, re.DOTALL)
        if m:
            return m.group(1)

    return None


def _extract_tags_from_page(page_html: str, title: str = "") -> list[str]:
    """Извлекает теги со страницы видео."""
    soup = BeautifulSoup(page_html, "lxml")
    tags = []

    # Теги в блоке .tags или ul.tags li a
    for tag_link in soup.select(".tag a, .tags a, ul.tags li a, .video-tags a"):
        tag_text = tag_link.get_text(strip=True).lower()
        tag_text = re.sub(r"\s+", "_", tag_text)  # пробелы → подчёркивание
        if tag_text and tag_text not in R34V_STOP_WORDS and len(tag_text) <= 40:
            tags.append(tag_text)

    # Если тегов нет — вытащим из заголовка
    if not tags and title:
        words = re.findall(r"[a-zA-Z]{3,}", title.lower())
        tags = [w for w in words if w not in R34V_STOP_WORDS][:10]

    return tags[:20]


def _fetch_video_details(entry: dict) -> dict | None:
    """
    Загружает страницу видео и извлекает прямой URL и теги.
    Возвращает обогащённый entry или None при ошибке.
    """
    r = _get(entry["page_url"])
    if not r:
        return None

    direct_url = _extract_direct_url(r.text)
    if not direct_url:
        logger.debug(f"r34video: не удалось извлечь URL для {entry['page_url']}")
        return None

    tags = _extract_tags_from_page(r.text, entry.get("title", ""))

    return {
        **entry,
        "url": direct_url,
        "tags": tags,
    }


# ── Основная функция ──────────────────────────────────────────────────────────

def fetch_rule34video(
    limit: int = 20,
    max_pages: int = 3,
    search_tags: str | None = None,
) -> list[dict]:
    """
    Парсит rule34video.com и возвращает список items в формате civitai_bot.py:

    {
        "id": "r34v_12345",
        "url": "https://...mp4",
        "tags": ["tag1", "tag2"],
        "likes": 0,
        "rating": "xxx",
        "mime": "video/mp4",
        "createdAt": None,
        "source": "rule34video",
        "prompt": None,
    }
    """
    if search_tags is None:
        search_tags = random.choice(SEARCH_TAG_SETS)

    logger.info(f"r34video: поиск по '{search_tags}', max_pages={max_pages}")

    # ── Шаг 1: Собираем список видео ──────────────────────────────────────
    raw_entries = []
    seen_ids = set()

    for page in range(1, max_pages + 1):
        params = {
            "s": "search",
            "q": search_tags,
            "sort_by": "rating",   # rating | post_date | most_viewed
            "from_videos": (page - 1) * 20,
        }
        r = _get(BASE_URL, params=params)
        if not r:
            logger.warning(f"r34video: нет ответа на странице {page}")
            break

        entries = _parse_video_list(r.text)
        if not entries:
            logger.info(f"r34video: страница {page} пустая, стоп")
            break

        new = 0
        for entry in entries:
            if entry["id"] not in seen_ids:
                seen_ids.add(entry["id"])
                raw_entries.append(entry)
                new += 1

        logger.info(f"r34video: страница {page}: {new} новых, итого {len(raw_entries)}")

        if len(raw_entries) >= limit * 3:
            break

        # Вежливая пауза между страницами
        time.sleep(random.uniform(0.5, 1.2))

    if not raw_entries:
        logger.warning("r34video: список видео пуст")
        return []

    # ── Шаг 2: Сортируем по лайкам, берём топ ─────────────────────────────
    raw_entries.sort(key=lambda x: x.get("likes", 0), reverse=True)
    candidates = raw_entries[:limit * 2]  # берём с запасом — часть отвалится

    logger.info(f"r34video: кандидатов для парсинга деталей: {len(candidates)}")

    # ── Шаг 3: Получаем прямые URL для каждого видео ──────────────────────
    items = []
    for entry in candidates:
        if len(items) >= limit:
            break

        detailed = _fetch_video_details(entry)
        if not detailed:
            continue

        url = detailed.get("url", "")
        if not url or not url.startswith("http"):
            continue

        items.append({
            "id":        detailed["id"],
            "url":       url,
            "tags":      detailed.get("tags", []),
            "likes":     detailed.get("likes", 0),
            "rating":    "xxx",
            "mime":      "video/mp4",
            "createdAt": None,
            "source":    "rule34video",
            "prompt":    None,
        })

        logger.debug(f"r34video: ✅ {detailed['id']} — {url[:60]}...")

        # Пауза между запросами страниц видео
        time.sleep(random.uniform(0.3, 0.8))

    logger.info(f"r34video: итого готовых items: {len(items)}")
    return items
