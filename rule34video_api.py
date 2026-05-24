"""
rule34video.com scraper
Использует нативный AJAX API сайта.
Стратегия: only most viewed за разные периоды + фильтр длительности до 120 сек.
"""

import logging
import math
import random
import re
import time

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("ErosLab.Rule34Video")

BASE_URL = "https://rule34video.com"
API_URL  = "https://rule34video.com/?mode=async&function=get_block&block_id=custom_list_videos_most_recent_videos"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE_URL,
    "X-Requested-With": "XMLHttpRequest",
}

# Глобальная сессия с куками
_session = requests.Session()
_session.headers.update(HEADERS)
_session_initialized = False


def _init_session():
    """Инициализирует сессию — получает куки с главной страницы."""
    global _session_initialized
    if _session_initialized:
        return
    try:
        _session.get(BASE_URL, timeout=10)
        _session_initialized = True
        logger.debug(f"r34video: сессия инициализирована, куки: {dict(_session.cookies)}")
    except Exception as e:
        logger.warning(f"r34video: не удалось инициализировать сессию: {e}")

# Только most viewed за разные периоды — там самый сок
VARIATIONS = [
    {"sort_by": "video_viewed", "post_date_from": "",         "label": "All Time"},
    {"sort_by": "video_viewed", "post_date_from": "weekago",  "label": "Week"},
    {"sort_by": "video_viewed", "post_date_from": "monthago", "label": "Month"},
    {"sort_by": "video_viewed", "post_date_from": "yearago",  "label": "Year"},
]

# Фильтр длительности — передаётся прямо в API
DURATION_FROM = 10   # минимум 10 сек (отсеиваем мусор)
DURATION_TO   = 120  # максимум 2 минуты

R34V_STOP_WORDS = {
    "3d", "animated", "sfm", "blender", "hentai", "video",
    "rule34", "r34", "xxx", "porn", "hd", "source_filmmaker",
    "koikatsu", "honey_select", "animation", "the", "and",
    "with", "for", "this", "that",
}


# ── HTTP ───────────────────────────────────────────────────────────────────────

def _get(url: str, params: dict = None, retries: int = 3) -> requests.Response | None:
    _init_session()
    for attempt in range(retries):
        try:
            r = _session.get(url, params=params, timeout=20)
            if r.status_code == 200:
                return r
            if r.status_code == 429:
                wait = 5 * (attempt + 1)
                logger.warning(f"r34video: rate limited, waiting {wait}s")
                time.sleep(wait)
                continue
            logger.warning(f"r34video: HTTP {r.status_code}")
            return None
        except requests.exceptions.Timeout:
            logger.warning(f"r34video: timeout attempt {attempt + 1}/{retries}")
            time.sleep(2)
        except Exception as e:
            logger.error(f"r34video: request error: {e}")
            return None
    return None


# ── Парсинг списка ─────────────────────────────────────────────────────────────

def _parse_video_list(html: str) -> list[dict]:
    """
    Парсит HTML-ответ AJAX API.
    Структура блока (из браузера):
      div.item.thumb > a.th[href=/video/ID/title/]
        div.thumb_title   → название
        div.rating        → "83% (6)"
        div.views         → "774"
        div.time          → "0:10"
        div.img.wrap_image[data-preview] → превью mp4
    """
    soup = BeautifulSoup(html, "lxml")
    items = []

    for block in soup.select("div.item.thumb"):
        link = block.select_one("a.th")
        if not link:
            continue

        href = link.get("href", "")
        match = re.search(r"/video/(\d+)/", href)
        if not match:
            continue
        video_id = match.group(1)

        # Название
        title = ""
        title_tag = block.select_one("div.thumb_title")
        if title_tag:
            title = title_tag.get_text(strip=True)
        if not title:
            title = link.get("title", "")

        # Рейтинг — "83% (6)"
        likes = 0
        rating_pct = 0
        rating_tag = block.select_one("div.rating")
        if rating_tag:
            text = rating_tag.get_text(strip=True)
            m = re.search(r"(\d+)%", text)
            if m:
                rating_pct = int(m.group(1))
            m = re.search(r"\((\d+)\)", text)
            if m:
                likes = int(m.group(1))

        # Просмотры
        views = 0
        views_tag = block.select_one("div.views")
        if views_tag:
            views_text = re.sub(r"[^\d]", "", views_tag.get_text())
            try:
                views = int(views_text)
            except ValueError:
                pass

        # Длительность — "0:10", "1:23", "1:02:03"
        duration_sec = 0
        time_tag = block.select_one("div.time")
        if time_tag:
            parts = time_tag.get_text(strip=True).split(":")
            try:
                if len(parts) == 2:
                    duration_sec = int(parts[0]) * 60 + int(parts[1])
                elif len(parts) == 3:
                    duration_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            except ValueError:
                pass

        # Превью-mp4 (запасной источник прямого URL)
        preview = ""
        img_wrap = block.select_one("div.img.wrap_image")
        if img_wrap:
            preview = img_wrap.get("data-preview", "")

        items.append({
            "id":           f"r34v_{video_id}",
            "page_url":     href if href.startswith("http") else BASE_URL + href,
            "title":        title,
            "preview":      preview,
            "likes":        likes,
            "rating_pct":   rating_pct,
            "views":        views,
            "duration_sec": duration_sec,
        })

    return items


# ── Детали видео ───────────────────────────────────────────────────────────────

def _upgrade_video_quality(url: str) -> str:
    """Пробует заменить низкое качество на 1080p, 720p, 480p."""
    # Паттерн учитывает слеш и параметры после .mp4
    for quality in ["1080", "720", "480"]:
        upgraded = re.sub(r'_(\d+)(\.mp4)', f'_{quality}\\2', url)
        if upgraded == url:
            break
        try:
            r = _session.head(upgraded, timeout=5, allow_redirects=True)
            if r.status_code == 200:
                logger.debug(f"r34video: качество → {quality}p")
                return upgraded
        except Exception:
            continue

    return url


def _extract_direct_url(page_html: str) -> str | None:
    """Извлекает прямую ссылку на mp4 со страницы видео."""
    soup = BeautifulSoup(page_html, "lxml")

    # Метод 1: <video src="..."> — основной, содержит токен и качество
    video_tag = soup.select_one("video[src]")
    if video_tag:
        src = video_tag.get("src", "")
        if ".mp4" in src:
            logger.debug(f"r34video: URL из <video src>: {src[:80]}...")
            return src

    # Метод 2: <source src="..."> (на случай другой вёрстки)
    quality_map = {}
    for source in soup.select("source"):
        src = source.get("src", "")
        if not src or ".mp4" not in src:
            continue
        m = re.search(r'_(\d+p?)\.mp4', src)
        quality_map[int(m.group(1).replace("p", "")) if m else 0] = src

    if quality_map:
        best_url = quality_map[max(quality_map.keys())]
        logger.debug(f"r34video: URL из <source>: {best_url[:80]}...")
        return best_url

    # Метод 3: JS-переменные
    for script in soup.find_all("script"):
        text = script.string or ""

        m = re.search(r'"file"\s*:\s*"([^"]+\.mp4[^"]*)"', text)
        if m:
            return m.group(1).replace("\\/", "/")

        m = re.search(r'video_url\s*[=:]\s*["\']([^"\']+\.mp4[^"\']*)["\']', text)
        if m:
            return m.group(1)

        m = re.search(r'sources\s*:\s*\[.*?file\s*:\s*["\']([^"\']+\.mp4[^"\']*)["\']', text, re.DOTALL)
        if m:
            return m.group(1)

    return None


def _extract_tags_from_page(page_html: str, title: str = "") -> list[str]:
    """Извлекает теги со страницы видео для caption."""
    soup = BeautifulSoup(page_html, "lxml")
    tags = []

    selectors = [
        ".tag a", ".tags a", ".video-tags a", "ul.tags li a",
        ".tags_list a", ".item-tags a", ".info-block a[href*='/tags/']",
        "div[class*='tag'] a", "span[class*='tag'] a",
    ]
    for selector in selectors:
        for tag_link in soup.select(selector):
            tag_text = tag_link.get_text(strip=True).lower()
            tag_text = re.sub(r"\s+", "_", tag_text)
            if tag_text and tag_text not in R34V_STOP_WORDS and len(tag_text) <= 40:
                tags.append(tag_text)

    seen = set()
    tags_dedup = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            tags_dedup.append(t)
    tags = tags_dedup

    if title:
        words = re.findall(r"[a-zA-Z]{3,}", title.lower())
        for w in words:
            if w not in R34V_STOP_WORDS and w not in seen and len(w) <= 40:
                tags.append(w)
                seen.add(w)
                if len(tags) >= 20:
                    break

    return tags[:20]


def _fetch_video_details(entry: dict) -> dict | None:
    """Загружает страницу видео, возвращает обогащённый entry или None."""
    r = _get(entry["page_url"])
    if not r:
        return None

    direct_url = _extract_direct_url(r.text)
    if not direct_url:
        if entry.get("preview") and ".mp4" in entry["preview"]:
            direct_url = _upgrade_video_quality(entry["preview"])
        else:
            logger.debug(f"r34video: нет прямого URL для {entry['page_url']}")
            return None

    tags = _extract_tags_from_page(r.text, entry.get("title", ""))

    return {**entry, "url": direct_url, "tags": tags}


# ── Сбор одной вариации ────────────────────────────────────────────────────────

def _fetch_variation(variation: dict, pages: int, seen_ids: set) -> list[dict]:
    """
    Запрашивает AJAX API для одной комбинации sort_by + период.
    Фильтр длительности передаётся прямо в API.
    """
    label = variation.get("label", "")
    collected = []

    for page in range(pages):
        offset = page * 20
        params = {
            "tag_ids":       "",
            "sort_by":       variation["sort_by"],
            "from_videos":   offset,
            "duration_from": DURATION_FROM,
            "duration_to":   DURATION_TO,
        }
        if variation.get("post_date_from"):
            params["post_date_from"] = variation["post_date_from"]

        r = _get(API_URL, params=params)
        if not r:
            break

        entries = _parse_video_list(r.text)
        if not entries:
            break

        new = 0
        for e in entries:
            if e["id"] not in seen_ids:
                seen_ids.add(e["id"])
                collected.append(e)
                new += 1

        if new == 0:
            break

        time.sleep(random.uniform(0.3, 0.6))

    if collected:
        logger.info(
            f"r34video [{label}]: {len(collected)} видео "
            f"(duration {DURATION_FROM}-{DURATION_TO}s)"
        )

    return collected


# ── Основная функция ───────────────────────────────────────────────────────────

def fetch_rule34video(limit: int = 20) -> list[dict]:
    """
    Парсит rule34video.com через нативный AJAX API.
    Только most viewed за разные периоды, длительность DURATION_FROM..DURATION_TO сек.
    """
    seen_ids: set[str] = set()
    all_raw: list[dict] = []

    for variation in VARIATIONS:
        entries = _fetch_variation(variation, pages=3, seen_ids=seen_ids)
        all_raw.extend(entries)

    if not all_raw:
        logger.warning("r34video: ничего не нашли")
        return []

    logger.info(f"r34video: всего собрано {len(all_raw)} записей")

    # Скоринг: views — главный критерий, лайки и рейтинг усиливают
    for e in all_raw:
        views = max(e.get("views", 0), 0)
        likes = max(e.get("likes", 0), 0)
        pct   = max(e.get("rating_pct", 0), 1)
        e["_score"] = views * math.log(likes + 2) * pct

    all_raw.sort(key=lambda x: x["_score"], reverse=True)

    top = all_raw[0]
    logger.info(
        f"r34video: top score={top['_score']:.0f} "
        f"views={top['views']} likes={top['likes']} "
        f"rating={top['rating_pct']}% dur={top['duration_sec']}s"
    )

    candidates = all_raw[:limit * 2]

    # Получаем прямые URL и теги
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

        time.sleep(random.uniform(0.2, 0.5))

    logger.info(f"r34video: итого items: {len(items)}")
    return items