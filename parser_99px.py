"""
Парсер обоев с 99px.ru для ErosLab Wallpapers Bot
Возвращает items в том же формате что fetch_wallhaven
"""

import logging
import random
import re
import time
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE = "https://wallpapers.99px.ru"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
]

NSFW_KEYWORDS = {"обнаженн"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": BASE,
}


def _parse_page(url: str) -> list[dict]:
    """Парсит одну страницу листинга и возвращает список items."""
    try:
        headers = {**HEADERS, "User-Agent": random.choice(USER_AGENTS)}
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
    except Exception as e:
        logger.warning(f"99px fetch error {url}: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    items = []

    for link in soup.select("a[href*='/wallpapers/']"):
        href = link.get("href", "")

        if not re.search(r"/wallpapers/\d+", href):
            continue

        m = re.search(r"/wallpapers/(\d+)", href)
        if not m:
            continue
        item_id_num = m.group(1)
        item_id = f"99px_{item_id_num}"

        img = link.find("img")
        title = ""
        if img:
            title = img.get("alt", "").strip() or img.get("title", "").strip()

        # Чистим "Обои на рабочий стол " из начала alt
        title = re.sub(r"^обои на рабочий стол\s*", "", title, flags=re.IGNORECASE).strip()

        # Фильтр NSFW по названию
        if any(kw in title.lower() for kw in NSFW_KEYWORDS):
            continue

        tags = [t for t in re.split(r"[\s,]+", title.lower()) if len(t) > 2] if title else []

        # Берём прямую ссылку на оригинальное изображение
        page_url = href if href.startswith("http") else BASE + href
        download_url = f"{BASE}/wallpapers/download/{item_id_num}/"
        
        try:
            r = requests.get(page_url, headers={**HEADERS, "User-Agent": random.choice(USER_AGENTS)}, timeout=10)
            page_soup = BeautifulSoup(r.text, "html.parser")
            main_img = page_soup.select_one("img#mainImage") or page_soup.select_one("div.wallpaper_block img")
            if main_img and main_img.get("src"):
                img_src = main_img["src"]
                # Убираем tmb_ префикс чтобы получить оригинал
                img_src = img_src.replace("/tmb_", "/")
                download_url = img_src if img_src.startswith("http") else BASE + img_src
        except Exception:
            # Фолбэк если что-то сломалось
            pass

        items.append({
            "id":        item_id,
            "url":       download_url,
            "page_url":  page_url,
            "tags":      tags[:10],
            "likes":     0,
            "rating":    "safe",
            "mime":      "image/jpeg",
            "createdAt": None,
            "source":    "99px",
        })

    logger.info(f"99px parsed {len(items)} items from {url}")
    return items


def fetch_99px(max_pages: int = 5) -> list[dict]:
    """
    Основная функция — совместима с fetch_wallhaven.
    Возвращает список items готовых к публикации.
    """
    all_items = []

    for base_url in [f"{BASE}/new/", f"{BASE}/best/"]:
        for page in range(1, max_pages + 1):
            url = base_url if page == 1 else f"{base_url}?page={page}"
            time.sleep(3)  # пауза ПЕРЕД каждым запросом
            page_items = _parse_page(url)
            if not page_items:
                break
            all_items.extend(page_items)
        time.sleep(3)  # пауза между /new/ и /best/

    # Убираем дубли по id
    seen = set()
    unique = []
    for item in all_items:
        if item["id"] not in seen:
            seen.add(item["id"])
            unique.append(item)

    logger.info(f"99px total unique items: {len(unique)}")
    return unique