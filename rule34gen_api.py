"""
rule34gen.com scraper
Движок: KVS (тот же что rule34video.com).
Стратегия:
  1. AJAX API для листинга (как у rule34video) — быстро, без Playwright
  2. Playwright для открытия попапа и перехвата mp4 с acctoken
  3. Скачивание mp4 через page.route() — перехват тела запроса с Sec-Fetch-Dest: video
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
    "login", "signup", "register", "upload", "search", "home",
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

            video_id = None
            for cls in block.get("class", []):
                m = re.match(r"video_(\d+)$", cls)
                if m:
                    video_id = m.group(1)
                    break
            if not video_id:
                m = re.search(r"/video(?:s)?/(\d+)", href)
                video_id = m.group(1) if m else re.sub(r"\W", "_", href[-15:])

            title = ""
            title_tag = block.select_one("div.thumb_title")
            if title_tag:
                title = title_tag.get_text(strip=True)
            if not title:
                title = link.get("title", "")

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


async def _try_download_quality(
    context, page, entry: dict, qualities: list[str]
) -> tuple[str, bytes] | None:
    """
    Пытается скачать видео в указанных качествах через download-ссылки на странице.
    Возвращает (url, data) для первого успешно загруженного качества.
    """
    logger.info(f"r34gen: ищем download-ссылки для {entry['id']}")

    # Собираем все ссылки на .mp4 на странице
    mp4_links = await page.evaluate("""
        () => {
            const links = [];
            document.querySelectorAll('a[href*=".mp4"], a[href*="get_file"], a[href*="download"]').forEach(a => {
                const href = a.href || a.getAttribute('href') || '';
                if (href) links.push({ url: href, text: (a.textContent || '').trim().toLowerCase() });
            });
            // Также ищем source/iframe с mp4
            document.querySelectorAll('source[src*=".mp4"], iframe[src*=".mp4"]').forEach(el => {
                const src = el.src || el.getAttribute('src') || '';
                if (src) links.push({ url: src, text: '' });
            });
            return links;
        }
    """)
    logger.info(f"r34gen: найдено {len(mp4_links)} mp4-ссылок")

    if not mp4_links:
        return None

    # Сортируем ссылки по приоритету качества (сначала 1080p)
    quality_order = {"1080": 4, "720": 3, "480": 2, "360": 1}
    def _quality_priority(link: dict) -> int:
        url = link["url"].lower()
        text = link["text"].lower()
        for q_name, priority in quality_order.items():
            if q_name in url or q_name in text:
                return priority
        return 0

    mp4_links.sort(key=_quality_priority, reverse=True)

    # Пробуем загрузить каждую ссылку, пока не получим >100KB
    for link in mp4_links:
        url = link["url"]
        if not url.startswith("http"):
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = BASE_URL + url
            else:
                continue

        logger.info(f"r34gen: пробуем загрузить: {url[:100]}")
        try:
            resp = await context.request.fetch(
                url,
                headers={
                    "Referer": entry["page_url"],
                    "User-Agent": HEADERS["User-Agent"],
                }
            )
            if resp.ok:
                body = await resp.body()
                if len(body) > 100_000:
                    logger.info(f"r34gen: ✅ загружено {len(body)} байт: {url[:80]}")
                    return url, body
                else:
                    logger.info(f"r34gen: слишком мало байт ({len(body)}), скип")
        except Exception as e:
            logger.info(f"r34gen: ошибка загрузки {url[:60]}: {e}")

    logger.info(f"r34gen: ни одна mp4-ссылка не дала >100KB")
    return None


# ── Детали видео через Playwright ─────────────────────────────────────────────

async def _fetch_video_details_playwright(entries: list[dict]) -> list[dict]:
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

        if R34G_PHPSESSID:
            await context.add_cookies([{
                "name": "PHPSESSID", "value": R34G_PHPSESSID,
                "domain": "rule34gen.com", "path": "/"
            }])

        init_page = await context.new_page()
        await init_page.goto(BASE_URL, timeout=15_000, wait_until="domcontentloaded")
        await init_page.close()

        pw_cookies = await context.cookies()
        global _session_initialized
        _session_initialized = True
        for c in pw_cookies:
            _session.cookies.set(c["name"], c["value"], domain=c.get("domain", "rule34gen.com"))
        logger.info(f"r34gen: синхронизировано {len(pw_cookies)} кук из Playwright → requests")

        for entry in entries:
            mp4_bodies: dict[str, bytes] = {}
            page = await context.new_page()

            async def capture_mp4(route, request, _bodies=mp4_bodies):
                response = await route.fetch()
                try:
                    body = await response.body()
                    if len(body) > 1000:
                        _bodies[request.url] = body
                        logger.info(f"r34gen: route захватил {len(body)} байт: {request.url[:80]}")
                except Exception as e:
                    logger.debug(f"r34gen: route body failed: {e}")
                await route.fulfill(response=response)

            await page.route("**/get_file/**", capture_mp4)

            try:
                await page.goto(entry["page_url"], timeout=25_000, wait_until="domcontentloaded")

                # Читаем src из video тега — там нормальный URL с _360.mp4/?v-acctoken=...
                video_src = await page.evaluate("""
                    () => {
                        const v = document.querySelector('video source, video');
                        return v ? (v.src || v.getAttribute('src')) : null;
                    }
                """)
                logger.info(f"r34gen: video src из DOM: {video_src}")

                # Инициализируем переменные
                best_url = video_src
                best_data = None

                # Пробуем получить лучшее качество через download-ссылки на странице
                if video_src and not any(q in video_src for q in ['_720p', '_1080p', '_480p']):
                    higher = await _try_download_quality(context, page, entry, ["1080p", "720p", "480p"])
                    if higher:
                        best_url, best_data = higher
                        logger.info(f"r34gen: ✅ получено качество выше 360p")
                    else:
                        logger.info(f"r34gen: качество не выше 360p, используем 360p")
                        # Не пропускаем видео, используем 360p
                elif video_src:
                    # Если в URL уже есть 720p/1080p/480p — используем как есть
                    logger.info(f"r34gen: video_src уже с хорошим качеством, используем DOM src")

                await page.wait_for_timeout(5000)

                # Если данные не загружены через download link, пробуем через route (попап/клик)
                if not best_data:
                    if not mp4_bodies:
                        thumb = await page.query_selector("a.th, a.js-open-popup")
                        if thumb:
                            await thumb.click()
                            await page.wait_for_timeout(4000)
                    if mp4_bodies:
                        for q in ["_1080p", "_720p", "_480p"]:
                            for url, data in mp4_bodies.items():
                                if q in url:
                                    best_url, best_data = url, data
                                    logger.info(f"r34gen: выбрано качество {q} из route")
                                    break
                            if best_data:
                                break
                        if not best_data:
                            url, data = next(iter(mp4_bodies.items()))
                            best_url, best_data = url, data
                            logger.info(f"r34gen: базовое качество из route")

                if not best_data:
                    logger.debug(f"r34gen: mp4 не получен для {entry['page_url']}")
                    continue

                tags = await _extract_tags_playwright(page, entry.get("title", ""))

                results.append({
                    **entry,
                    "url":  best_url,
                    "tags": tags,
                    "data": best_data,
                })
                logger.info(f"r34gen: ✅ {entry['id']} — {best_url.split('?')[0][-40:]} — {len(best_data)} байт")

            except Exception as e:
                logger.warning(f"r34gen: ошибка {entry['page_url']}: {e}")
            finally:
                await page.unroute("**/get_file/**")
                await page.close()

            await asyncio.sleep(random.uniform(1.0, 2.0))

        await context.close()
        await browser.close()

    return results


async def _extract_tags_playwright(page, title: str = "") -> list[str]:
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


# ── Сбор одной вариации ────────────────────────────────────────────────────────

def _fetch_variation(variation: dict, pages: int) -> list[dict]:
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

        collected.extend(entries)
        logger.info(f"r34gen [{label}] стр.{page_num}: {len(entries)} карточек, всего: {len(collected)}")
        time.sleep(random.uniform(0.4, 0.8))

    return collected


# ── Основная функция ───────────────────────────────────────────────────────────

async def fetch_rule34gen(limit: int = 20) -> list[dict]:
    all_raw: list[dict] = []

    for variation in VARIATIONS:
        entries = _fetch_variation(variation, pages=3)
        all_raw.extend(entries)

    if not all_raw:
        logger.warning("r34gen: ничего не нашли на листингах")
        return []

    # Дедупликация по id
    seen_ids: set[str] = set()
    deduped: list[dict] = []
    for e in all_raw:
        eid = e.get("id", "")
        if eid and eid not in seen_ids:
            seen_ids.add(eid)
            deduped.append(e)
    all_raw = deduped
    logger.info(f"r34gen: после дедупликации: {len(all_raw)}")

    # Скоринг: просмотры + лайки
    for e in all_raw:
        e["_score"] = e.get("views", 0) + e.get("likes", 0) * 10
    all_raw.sort(key=lambda x: x["_score"], reverse=True)

    if R34G_MIN_SCORE:
        all_raw = [e for e in all_raw if e.get("likes", 0) >= R34G_MIN_SCORE]

    candidates = all_raw[:15]
    detailed = await _fetch_video_details_playwright(candidates)

    items: list[dict] = []
    for entry in detailed:
        if len(items) >= limit:
            break
        url = entry.get("url", "")
        if not url or not url.startswith("http"):
            continue

        # Фильтр: только mp4
        if '.mp4' not in url.lower():
            logger.debug(f"r34gen: не mp4, пропускаем: {url.split('?')[0][-50:]}")
            continue

        items.append({
            "id":        entry["id"],
            "url":       url,
            "data":      entry.get("data"),
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
    _init_session()
    try:
        r = _session.get(url, timeout=timeout)
        r.raise_for_status()
        return r.content, r.headers.get("Content-Type", "").lower()
    except Exception as e:
        logger.error(f"r34gen: ошибка скачивания {url}: {e}")
        return None, None