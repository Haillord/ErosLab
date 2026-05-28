"""
rule34gen.com scraper
Движок: KVS (тот же что rule34video.com).
Стратегия:
  1. AJAX API для листинга (как у rule34video) — быстро, без Playwright
  2. Playwright для открытия попапа и перехвата mp4 с acctoken
  3. Скачивание mp4 через Playwright (context.request.fetch) — acctoken валиден
"""

import asyncio
import logging
import os
import random
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("ErosLab.Rule34Gen")

BASE_URL = "https://rule34gen.com"

# KVS AJAX endpoint — тот же паттерн что у rule34video
API_URL = (
    "https://rule34gen.com/?mode=async&function=get_block"
    "&block_id=custom_list_videos_most_recent_videos"
)

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

# Минимальный score
R34G_MIN_SCORE = int(os.getenv("R34G_MIN_SCORE", "0"))

# Куки авторизации из ENV (если есть аккаунт)
R34G_PHPSESSID    = os.getenv("R34G_PHPSESSID", "")
R34G_KT_ACCTOKEN  = os.getenv("R34G_KT_ACCTOKEN", "")

# Глобальная сессия
_session = requests.Session()
_session.headers.update(HEADERS)
_session_initialized = False

STOP_WORDS = {
    "ai", "generated", "ai_generated", "rule34", "r34", "xxx", "porn",
    "hentai", "video", "the", "and", "with", "for", "this", "that",
    "animated", "animation", "hd", "full", "rule", "gen",
}

# Варианты сортировки (KVS стандарт)
VARIATIONS = [
    {"sort_by": "video_date",   "post_date_from": "",         "label": "Newest"},
    {"sort_by": "video_viewed", "post_date_from": "",         "label": "All Time"},
    {"sort_by": "video_viewed", "post_date_from": "weekago",  "label": "Week"},
    {"sort_by": "video_viewed", "post_date_from": "monthago", "label": "Month"},
]

DURATION_FROM = 5
DURATION_TO   = 120


# ── Сессия ────────────────────────────────────────────────────────────────────

def _init_session():
    global _session_initialized
    if _session_initialized:
        return
    try:
        _session.get(BASE_URL, timeout=15)
        if R34G_PHPSESSID:
            requests.utils.add_dict_to_cookiejar(
                _session.cookies, {"PHPSESSID": R34G_PHPSESSID}
            )
            logger.info("r34gen: PHPSESSID установлен")
        _session_initialized = True
        logger.debug("r34gen: сессия инициализирована")
    except Exception as e:
        logger.warning(f"r34gen: не удалось инициализировать сессию: {e}")


def _get(url: str, params: dict = None, retries: int = 3) -> Optional[requests.Response]:
    _init_session()
    for attempt in range(retries):
        try:
            r = _session.get(url, params=params, timeout=20)
            if r.status_code == 200:
                return r
            if r.status_code == 429:
                wait = 5 * (attempt + 1)
                logger.warning(f"r34gen: rate limit, ждём {wait}s")
                time.sleep(wait)
                continue
            logger.warning(f"r34gen: HTTP {r.status_code} для {url}")
            return None
        except requests.exceptions.Timeout:
            logger.warning(f"r34gen: timeout попытка {attempt + 1}/{retries}")
            time.sleep(2)
        except Exception as e:
            logger.error(f"r34gen: ошибка запроса: {e}")
            return None
    return None


# ── Парсинг листинга ───────────────────────────────────────────────────────────

def _parse_listing(html: str) -> list[dict]:
    """
    Парсит HTML ответа AJAX API.
    Структура: div.item.thumb.video_N > a.th.js-open-popup[href]
                                        div.thumb_title
                                        div.thumb_info
    """
    soup = BeautifulSoup(html, "lxml")
    items = []

    for block in soup.select("div.item.thumb"):
        try:
            link = block.select_one("a.th")
            if not link:
                continue

            href = link.get("href", "")
            if not href:
                continue
            if href.startswith("/"):
                href = BASE_URL + href

            # ID из класса div (video_N) или из URL
            video_id = None
            for cls in block.get("class", []):
                m = re.match(r"video_(\d+)$", cls)
                if m:
                    video_id = m.group(1)
                    break
            if not video_id:
                m = re.search(r"/video(?:s)?/(\d+)", href)
                video_id = m.group(1) if m else re.sub(r"\W", "_", href[-15:])

            # Заголовок
            title = ""
            title_tag = block.select_one("div.thumb_title")
            if title_tag:
                title = title_tag.get_text(strip=True)
            if not title:
                title = link.get("title", "")

            # Лайки / просмотры из thumb_info
            likes = 0
            views = 0
            info_tag = block.select_one("div.thumb_info")
            if info_tag:
                text = info_tag.get_text(" ", strip=True)
                nums = re.findall(r"[\d,]+", text)
                if nums:
                    views = int(nums[0].replace(",", ""))
                if len(nums) > 1:
                    likes = int(nums[1].replace(",", ""))

            items.append({
                "id":       f"r34gen_{video_id}",
                "page_url": href,
                "title":    title,
                "likes":    likes,
                "views":    views,
            })
        except Exception as e:
            logger.debug(f"r34gen: ошибка парсинга карточки: {e}")
            continue

    return items


# ── Детали видео через Playwright ─────────────────────────────────────────────

async def _fetch_video_details_playwright(entries: list[dict]) -> list[dict]:
    """
    Открывает страницы видео через Playwright и перехватывает mp4 с acctoken.
    Скачивает mp4 через тот же browser context (acctoken работает только из браузера).
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("r34gen: playwright не установлен — pip install playwright && playwright install chromium")
        return []

    results = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 720},
        )

        # Передаём PHPSESSID в Playwright, если есть
        if R34G_PHPSESSID:
            await context.add_cookies([{
                "name": "PHPSESSID", "value": R34G_PHPSESSID,
                "domain": "rule34gen.com", "path": "/"
            }])

        # Загружаем главную страницу чтобы получить актуальные куки (kt_acctoken и др.)
        init_page = await context.new_page()
        await init_page.goto(BASE_URL, timeout=15_000, wait_until="domcontentloaded")
        await init_page.close()

        # Синхронизируем куки из браузера в requests-сессию
        pw_cookies = await context.cookies()
        _session_initialized = True  # сессия уже инициализирована
        for c in pw_cookies:
            _session.cookies.set(c["name"], c["value"], domain=c.get("domain", "rule34gen.com"))
        logger.info(f"r34gen: синхронизировано {len(pw_cookies)} кук из Playwright → requests")

        for entry in entries:
            mp4_urls: list[str] = []
            page = await context.new_page()

            def on_response(response):
                url = response.url
                if "remote_control.php" in url and ".mp4" in url:
                    mp4_urls.append(url)
                elif ".mp4" in url and "rule34gen" in url and response.status == 200:
                    mp4_urls.append(url)

            page.on("response", on_response)

            try:
                await page.goto(entry["page_url"], timeout=25_000, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)  # ждём загрузку видео-запроса

                # Если попап — пробуем кликнуть по .th
                if not mp4_urls:
                    thumb = await page.query_selector("a.th, a.js-open-popup")
                    if thumb:
                        await thumb.click()
                        await page.wait_for_timeout(2000)

                if not mp4_urls:
                    logger.debug(f"r34gen: mp4 не перехвачен для {entry['page_url']}")
                    continue

                # Берём первый перехваченный (с acctoken уже внутри)
                direct_url = mp4_urls[0]

                # Теги из попапа/страницы
                tags = await _extract_tags_playwright(page, entry.get("title", ""))

                # Скачиваем mp4 через Playwright (та же сессия браузера, acctoken валиден)
                video_data: bytes | None = None
                try:
                    logger.info(f"r34gen: перехвачен URL: {direct_url}")
                    resp = await context.request.fetch(direct_url)
                    content_type = resp.headers.get('content-type', '???')
                    logger.info(f"r34gen: статус={resp.status}, Content-Type={content_type}")
                    if resp.ok:
                        video_data = await resp.body()
                        if len(video_data) < 200:
                            logger.warning(f"r34gen: подозрительно мало байт ({len(video_data)}), тело: {video_data}")
                        else:
                            logger.info(f"r34gen: скачано {len(video_data)} байт для {entry['id']}")
                    else:
                        logger.warning(f"r34gen: HTTP {resp.status} при скачивании {entry['id']}")
                except Exception as e:
                    logger.warning(f"r34gen: ошибка скачивания {entry['id']}: {e}")

                results.append({
                    **entry,
                    "url":   direct_url,
                    "tags":  tags,
                    "data":  video_data,  # сырые байты mp4, None если не удалось
                })
                logger.debug(f"r34gen: получен mp4 для {entry['id']}")

            except Exception as e:
                logger.warning(f"r34gen: ошибка при открытии {entry['page_url']}: {e}")
            finally:
                await page.close()

            await asyncio.sleep(random.uniform(0.5, 1.0))

        await context.close()
        await browser.close()

    return results


async def _extract_tags_playwright(page, title: str = "") -> list[str]:
    """Извлекает теги через Playwright — ищет a.button внутри попапа/страницы."""
    raw: list[str] = []

    selectors = [
        "a.button[href*='/tags/']",
        "a.button[href*='/tag/']",
        ".popup a.button",
        ".video-page a.button",
        "a.button",
    ]
    for selector in selectors:
        els = await page.query_selector_all(selector)
        if els:
            for el in els:
                try:
                    t = await el.inner_text()
                    t = t.strip().lower()
                    t = re.sub(r"\s+", "_", t)
                    if t and len(t) <= 40 and t not in STOP_WORDS:
                        raw.append(t)
                except Exception:
                    continue
            if raw:
                break

    return _clean_tags(raw, title)


# ── Утилиты ───────────────────────────────────────────────────────────────────

def _clean_tags(raw: list[str], title: str = "") -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for t in raw:
        if t and t not in STOP_WORDS and t not in seen and len(t) <= 40:
            seen.add(t)
            result.append(t)
    if title:
        for word in re.findall(r"[a-zA-Z]{3,}", title.lower()):
            if word not in STOP_WORDS and word not in seen:
                result.append(word)
                seen.add(word)
                if len(result) >= 20:
                    break
    return result[:20]


# ── Сбор одной вариации ────────────────────────────────────────────────────────

def _fetch_variation(variation: dict, pages: int, seen_ids: set) -> list[dict]:
    label = variation["label"]
    collected: list[dict] = []

    for page_num in range(pages):
        offset = page_num * 20
        params = {
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

        entries = _parse_listing(r.text)
        if not entries:
            logger.debug(f"r34gen [{label}] стр.{page_num}: пусто")
            break

        new = 0
        for e in entries:
            if e["id"] not in seen_ids:
                seen_ids.add(e["id"])
                collected.append(e)
                new += 1

        logger.info(f"r34gen [{label}] стр.{page_num}: {len(entries)} карточек, новых: {new}")

        if new == 0:
            break

        time.sleep(random.uniform(0.4, 0.8))

    return collected


# ── Основная функция ───────────────────────────────────────────────────────────

async def fetch_rule34gen(limit: int = 20) -> list[dict]:
    """
    Парсит rule34gen.com.
    1. AJAX API (requests) для листинга — быстро
    2. Playwright для получения mp4 URL с acctoken и скачивания
    """
    seen_ids: set[str] = set()
    all_raw: list[dict] = []

    for variation in VARIATIONS:
        entries = _fetch_variation(variation, pages=3, seen_ids=seen_ids)
        all_raw.extend(entries)

    if not all_raw:
        logger.warning("r34gen: ничего не нашли на листингах")
        return []

    logger.info(f"r34gen: всего карточек: {len(all_raw)}")

    # Скоринг: просмотры + лайки
    for e in all_raw:
        e["_score"] = e.get("views", 0) + e.get("likes", 0) * 10
    all_raw.sort(key=lambda x: x["_score"], reverse=True)

    # Фильтр по минскору
    if R34G_MIN_SCORE:
        all_raw = [e for e in all_raw if e.get("likes", 0) >= R34G_MIN_SCORE]

    candidates = all_raw[:limit * 3]
    detailed = await _fetch_video_details_playwright(candidates)

    items: list[dict] = []
    for entry in detailed:
        if len(items) >= limit:
            break
        url = entry.get("url", "")
        if not url or not url.startswith("http"):
            continue
        items.append({
            "id":        entry["id"],
            "url":       url,
            "data":      entry.get("data"),  # предзагруженные mp4 байты, может быть None
            "tags":      entry.get("tags", []),
            "likes":     entry.get("likes", 0),
            "rating":    "xxx",
            "mime":      "video/mp4",
            "createdAt": None,
            "source":    "rule34gen",
            "prompt":    None,
        })

    logger.info(f"r34gen: итого items: {len(items)}")
    return items


# ── Скачивание файла через сессию (для eroslab_bot.py) ─────────────────────────

def download_file(url: str, timeout: int = 60) -> tuple[Optional[bytes], Optional[str]]:
    """
    Скачивает файл через авторизованную сессию rule34gen.
    Возвращает (data, content_type).
    Используется как fallback, если data из Playwright недоступен.
    """
    _init_session()
    try:
        r = _session.get(url, timeout=timeout)
        r.raise_for_status()
        return r.content, r.headers.get("Content-Type", "").lower()
    except Exception as e:
        logger.error(f"r34gen: ошибка скачивания {url}: {e}")
        return None, None