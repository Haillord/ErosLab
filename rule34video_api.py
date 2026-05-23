"""
rule34video.com scraper
Парсит видео с rule34video.com, возвращает список items
в формате совместимом с civitai_bot.py.
"""

import logging
import random
import re
import time

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("ErosLab.Rule34Video")

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

# Страницы тегов — прямые URL, работают без авторизации
# offset кратен 20 (по 20 видео на страницу)
TAG_URLS = [
    "https://rule34video.com/tags/source-filmmaker/?sort_by=rating&from_videos={offset}",
    "https://rule34video.com/tags/3d/?sort_by=rating&from_videos={offset}",
    "https://rule34video.com/tags/blender-sfm/?sort_by=rating&from_videos={offset}",
    "https://rule34video.com/tags/animated/?sort_by=rating&from_videos={offset}",
    "https://rule34video.com/tags/sfm/?sort_by=rating&from_videos={offset}",
]

R34V_STOP_WORDS = {
    "3d", "animated", "sfm", "blender", "hentai", "video",
    "rule34", "r34", "xxx", "porn", "hd", "source_filmmaker",
    "koikatsu", "honey_select", "animation",
}


def _get(url: str, retries: int = 3) -> requests.Response | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
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
    Парсит страницу с видео.
    Реальная структура (из браузера):
      div.item.thumb > a.th.js-open-popup[href=/video/ID/title/]
        div.thumb_title  → название
        div.rating       → "83% (6)"
        div.views        → "774"
        div.time         → "0:10"
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

        # Рейтинг — "83% (6)" → берём число голосов как likes
        likes = 0
        rating_pct = 0
        rating_tag = block.select_one("div.rating")
        if rating_tag:
            text = rating_tag.get_text(strip=True)
            # Процент
            m = re.search(r"(\d+)%", text)
            if m:
                rating_pct = int(m.group(1))
            # Количество голосов
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

        # Превью-видео URL (data-preview на div.img.wrap_image)
        preview = ""
        img_wrap = block.select_one("div.img.wrap_image")
        if img_wrap:
            preview = img_wrap.get("data-preview", "")

        # Превью-картинка
        thumb = ""
        img_tag = block.select_one("img.thumb")
        if img_tag:
            thumb = img_tag.get("src") or img_tag.get("data-original") or ""

        items.append({
            "id":         f"r34v_{video_id}",
            "page_url":   href if href.startswith("http") else BASE_URL + href,
            "title":      title,
            "thumb":      thumb,
            "preview":    preview,
            "likes":      likes,
            "rating_pct": rating_pct,
            "views":      views,
        })

    return items


def _extract_direct_url(page_html: str) -> str | None:
    """Извлекает прямую ссылку на mp4 со страницы видео."""
    soup = BeautifulSoup(page_html, "lxml")

    # Метод 1: <source src="...mp4">
    for source in soup.select("source"):
        src = source.get("src", "")
        if src and ".mp4" in src:
            return src

    # Метод 2: <video src="...">
    video_tag = soup.select_one("video[src]")
    if video_tag:
        src = video_tag.get("src", "")
        if ".mp4" in src:
            return src

    # Метод 3: JS-переменные в script-тегах
    for script in soup.find_all("script"):
        text = script.string or ""

        # "file":"https://...mp4"
        m = re.search(r'"file"\s*:\s*"([^"]+\.mp4[^"]*)"', text)
        if m:
            return m.group(1).replace("\\/", "/")

        # video_url = "..."
        m = re.search(r'video_url\s*[=:]\s*["\']([^"\']+\.mp4[^"\']*)["\']', text)
        if m:
            return m.group(1)

        # sources:[{file:"..."}]
        m = re.search(r'sources\s*:\s*\[.*?file\s*:\s*["\']([^"\']+\.mp4[^"\']*)["\']', text, re.DOTALL)
        if m:
            return m.group(1)

    return None


def _extract_tags_from_page(page_html: str, title: str = "") -> list[str]:
    """Извлекает теги со страницы видео."""
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
        # Иногда прямой URL есть в data-preview превью-блока
        if entry.get("preview") and ".mp4" in entry["preview"]:
            direct_url = entry["preview"]
        else:
            logger.debug(f"r34video: нет прямого URL для {entry['page_url']}")
            return None

    tags = _extract_tags_from_page(r.text, entry.get("title", ""))

    return {**entry, "url": direct_url, "tags": tags}


def fetch_rule34video(limit: int = 20, max_pages: int = 3) -> list[dict]:
    """
    Парсит rule34video.com и возвращает items в формате civitai_bot.py.
    """
    tag_url_template = random.choice(TAG_URLS)
    logger.info(f"r34video: шаблон URL: {tag_url_template.split('?')[0]}")

    # ── Шаг 1: собираем список видео ──────────────────────────────────────
    raw_entries = []
    seen_ids: set[str] = set()

    for page in range(max_pages):
        offset = page * 20
        url = tag_url_template.format(offset=offset)
        r = _get(url)
        if not r:
            logger.warning(f"r34video: нет ответа, страница {page + 1}")
            break

        entries = _parse_video_list(r.text)
        if not entries:
            logger.info(f"r34video: страница {page + 1} пустая, стоп")
            break

        new = 0
        for e in entries:
            if e["id"] not in seen_ids:
                seen_ids.add(e["id"])
                raw_entries.append(e)
                new += 1

        logger.info(f"r34video: страница {page + 1}: {new} новых, итого {len(raw_entries)}")

        if len(raw_entries) >= limit * 3:
            break

        time.sleep(random.uniform(0.5, 1.0))

    if not raw_entries:
        logger.warning("r34video: список видео пуст")
        return []

    # ── Шаг 2: сортируем по рейтингу × голоса ─────────────────────────────
    raw_entries.sort(
        key=lambda x: x.get("rating_pct", 0) * max(x.get("likes", 0), 1),
        reverse=True,
    )
    candidates = raw_entries[:limit * 2]
    logger.info(f"r34video: кандидатов для парсинга деталей: {len(candidates)}")

    # ── Шаг 3: получаем прямые URL ─────────────────────────────────────────
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

        logger.debug(f"r34video: ✅ {detailed['id']}")
        time.sleep(random.uniform(0.3, 0.7))

    logger.info(f"r34video: итого items: {len(items)}")
    return items