"""
rule34video.com scraper
Использует нативный AJAX API сайта для получения топ-видео
по рейтингу, просмотрам и дате — аналогично CivitAI.
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

# Периоды для фильтрации по дате (параметр post_date_from)
# Аналог CivitAI Day/Week/Month/AllTime
DATE_FILTERS = [
    {"post_date_from": "",       "label": "All Time"},
    {"post_date_from": "today",  "label": "Today"},
    {"post_date_from": "2daysago", "label": "2 Days"},
    {"post_date_from": "weekago",  "label": "Week"},
    {"post_date_from": "monthago", "label": "Month"},
]

R34V_STOP_WORDS = {
    "3d", "animated", "sfm", "blender", "hentai", "video",
    "rule34", "r34", "xxx", "porn", "hd", "source_filmmaker",
    "koikatsu", "honey_select", "animation", "the", "and",
    "with", "for", "this", "that",
}


# ── HTTP ───────────────────────────────────────────────────────────────────────

def _get(url: str, params: dict = None, retries: int = 3) -> requests.Response | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=20)
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

        # Превью-mp4 (запасной источник прямого URL)
        preview = ""
        img_wrap = block.select_one("div.img.wrap_image")
        if img_wrap:
            preview = img_wrap.get("data-preview", "")

        items.append({
            "id":         f"r34v_{video_id}",
            "page_url":   href if href.startswith("http") else BASE_URL + href,
            "title":      title,
            "preview":    preview,
            "likes":      likes,
            "rating_pct": rating_pct,
            "views":      views,
        })

    return items


# ── Детали видео ───────────────────────────────────────────────────────────────

def _upgrade_video_quality(url: str) -> str:
    """Пробует заменить низкое качество на 1080p или 720p."""
    for quality in ["1080", "720"]:
        upgraded = re.sub(r'_\d+\.mp4', f'_{quality}.mp4', url)
        if upgraded == url:
            break
        try:
            r = requests.head(upgraded, headers=HEADERS, timeout=5, allow_redirects=True)
            if r.status_code == 200:
                logger.debug(f"r34video: качество → {quality}p")
                return upgraded
        except Exception:
            continue
    return url


def _extract_direct_url(page_html: str) -> str | None:
    """Извлекает прямую ссылку на mp4 со страницы видео."""
    soup = BeautifulSoup(page_html, "lxml")

    # Метод 1: <source src="...mp4">
    for source in soup.select("source"):
        src = source.get("src", "")
        if src and ".mp4" in src:
            return _upgrade_video_quality(src)

    # Метод 2: <video src="...">
    video_tag = soup.select_one("video[src]")
    if video_tag:
        src = video_tag.get("src", "")
        if ".mp4" in src:
            return _upgrade_video_quality(src)

    # Метод 3: JS-переменные
    for script in soup.find_all("script"):
        text = script.string or ""

        m = re.search(r'"file"\s*:\s*"([^"]+\.mp4[^"]*)"', text)
        if m:
            return _upgrade_video_quality(m.group(1).replace("\\/", "/"))

        m = re.search(r'video_url\s*[=:]\s*["\']([^"\']+\.mp4[^"\']*)["\']', text)
        if m:
            return _upgrade_video_quality(m.group(1))

        m = re.search(r'sources\s*:\s*\[.*?file\s*:\s*["\']([^"\']+\.mp4[^"\']*)["\']', text, re.DOTALL)
        if m:
            return _upgrade_video_quality(m.group(1))

    return None


def _extract_tags_from_page(page_html: str, title: str = "") -> list[str]:
    """Извлекает теги со страницы видео для caption."""
    soup = BeautifulSoup(page_html, "lxml")
    tags = []

    for tag_link in soup.select(".tag a, .tags a, .video-tags a, ul.tags li a"):
        tag_text = tag_link.get_text(strip=True).lower()
        tag_text = re.sub(r"\s+", "_", tag_text)
        if tag_text and tag_text not in R34V_STOP_WORDS and len(tag_text) <= 40:
            tags.append(tag_text)

    # Fallback — из заголовка
    if not tags and title:
        words = re.findall(r"[a-zA-Z]{3,}", title.lower())
        tags = [w for w in words if w not in R34V_STOP_WORDS][:10]

    return tags[:20]


def _fetch_video_details(entry: dict) -> dict | None:
    """Загружает страницу видео, возвращает обогащённый entry или None."""
    r = _get(entry["page_url"])
    if not r:
        return None

    direct_url = _extract_direct_url(r.text)
    if not direct_url:
        # Fallback: превью-mp4 из data-preview
        if entry.get("preview") and ".mp4" in entry["preview"]:
            direct_url = _upgrade_video_quality(entry["preview"])
        else:
            logger.debug(f"r34video: нет прямого URL для {entry['page_url']}")
            return None

    tags = _extract_tags_from_page(r.text, entry.get("title", ""))

    return {**entry, "url": direct_url, "tags": tags}


# ── Сбор по одной вариации API ─────────────────────────────────────────────────

def _fetch_variation(sort_by: str, date_filter: dict, pages: int, seen_ids: set) -> list[dict]:
    """
    Запрашивает AJAX API для одной комбинации sort_by + период.
    Возвращает список сырых записей.
    """
    label = date_filter.get("label", "")
    post_date_from = date_filter.get("post_date_from", "")
    collected = []

    for page in range(pages):
        offset = page * 20
        params = {
            "tag_ids":        "",
            "sort_by":        sort_by,
            "from_videos":    offset,
        }
        if post_date_from:
            params["post_date_from"] = post_date_from

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
            break  # все уже видели

        time.sleep(random.uniform(0.3, 0.7))

    if collected:
        logger.info(f"r34video: sort={sort_by} period={label}: {len(collected)} видео")

    return collected


# ── Основная функция ───────────────────────────────────────────────────────────

def fetch_rule34video(limit: int = 20) -> list[dict]:
    """
    Парсит rule34video.com через нативный AJAX API.
    Стратегия аналогична CivitAI:
      1. Собираем топ по рейтингу за разные периоды
      2. Добавляем топ по просмотрам
      3. Объединяем, сортируем по score, берём лучшие
      4. Для каждого получаем прямой URL видео
    """

    seen_ids: set[str] = set()
    all_raw: list[dict] = []

    # ── Шаг 1: топ по рейтингу за разные периоды ─────────────────────────
    for date_filter in DATE_FILTERS:
        entries = _fetch_variation("rating", date_filter, pages=2, seen_ids=seen_ids)
        all_raw.extend(entries)

    # ── Шаг 2: топ по просмотрам (All Time) ──────────────────────────────
    entries = _fetch_variation("video_viewed", {"label": "All Time", "post_date_from": ""}, pages=2, seen_ids=seen_ids)
    all_raw.extend(entries)

    if not all_raw:
        logger.warning("r34video: ничего не нашли")
        return []

    logger.info(f"r34video: всего собрано {len(all_raw)} сырых записей")

    # ── Шаг 3: скоринг и сортировка ──────────────────────────────────────
    # score = rating_pct * log(votes+1) * log(views+1)
    # Аналог CivitAI: топ по лайкам с учётом популярности
    for e in all_raw:
        votes = max(e.get("likes", 0), 0)
        views = max(e.get("views", 0), 0)
        pct   = max(e.get("rating_pct", 0), 0)
        e["_score"] = pct * math.log(votes + 1) * math.log(views + 1)

    all_raw.sort(key=lambda x: x["_score"], reverse=True)

    top_score = all_raw[0]["_score"] if all_raw else 0
    med_score = all_raw[len(all_raw) // 2]["_score"] if all_raw else 0
    logger.info(
        f"r34video: top_score={top_score:.1f}, "
        f"median_score={med_score:.1f}, "
        f"кандидатов для деталей: {min(len(all_raw), limit * 2)}"
    )

    candidates = all_raw[:limit * 2]

    # ── Шаг 4: получаем прямые URL и теги ─────────────────────────────────
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