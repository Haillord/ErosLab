"""
Posts short "aggressive style" news digests to Telegram channel.

Flow:
1) Fetch RSS entries.
2) Filter by relevance keywords.
3) Deduplicate against local state.
4) Build aggressive post format (AI-assisted with fallback).
5) Send one news post.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import requests
from telegram import Bot, InputMediaPhoto

from news_sources import get_news_sources


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = (
    os.environ.get("NEWS_TARGET_CHAT")
    or os.environ.get("ADMIN_USER_ID")
    or os.environ.get("TELEGRAM_CHANNEL_ID", "@eroslabai")
)
WATERMARK_TEXT = os.environ.get("NEWS_WATERMARK", "📣 @eroslabai")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
AI_PROVIDER = os.environ.get("AI_PROVIDER", "auto").strip().lower()
AI_TIMEOUT_SEC = int(os.environ.get("AI_TIMEOUT_SEC", "12"))
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
ENABLE_AI_NEWS = os.environ.get("ENABLE_AI_NEWS", "true").lower() in ("1", "true", "yes", "on")

NEWS_STATE_FILE = os.environ.get("NEWS_STATE_FILE", "news_state.json")
NEWS_MAX_POSTED_LINKS = int(os.environ.get("NEWS_MAX_POSTED_LINKS", "3000"))
NEWS_LOOKBACK_HOURS = int(os.environ.get("NEWS_LOOKBACK_HOURS", "96"))
NEWS_FETCH_LIMIT = int(os.environ.get("NEWS_FETCH_LIMIT", "80"))
NEWS_MAX_PER_RUN = int(os.environ.get("NEWS_MAX_PER_RUN", "1"))
NEWS_REQUIRE_IMAGE = os.environ.get("NEWS_REQUIRE_IMAGE", "true").lower() in ("1", "true", "yes", "on")
NEWS_MIN_IMAGE_WIDTH = int(os.environ.get("NEWS_MIN_IMAGE_WIDTH", "700"))
NEWS_MIN_IMAGE_HEIGHT = int(os.environ.get("NEWS_MIN_IMAGE_HEIGHT", "390"))
NEWS_IMAGE_CHECK_TIMEOUT = int(os.environ.get("NEWS_IMAGE_CHECK_TIMEOUT", "8"))
NEWS_MEDIA_MAX_IMAGES = int(os.environ.get("NEWS_MEDIA_MAX_IMAGES", "3"))
NEWS_MAX_REDDIT_STREAK = int(os.environ.get("NEWS_MAX_REDDIT_STREAK", "1"))
NEWS_FEED_TIMEOUT = int(os.environ.get("NEWS_FEED_TIMEOUT", "10"))
NEWS_FILTER_MODE = os.environ.get("NEWS_FILTER_MODE", "thematic").strip().lower()
NEWS_REVIEW_MODE = os.environ.get("NEWS_REVIEW_MODE", "false").lower() in ("1", "true", "yes", "on")
ADMIN_USER_ID = str(os.environ.get("ADMIN_USER_ID", "")).strip()
NEWS_PENDING_DRAFT_FILE = os.environ.get("NEWS_PENDING_DRAFT_FILE", "news_pending_draft.json")
NEWS_REVIEW_STATE_FILE = os.environ.get("NEWS_REVIEW_STATE_FILE", "news_review_state.json")
NEWS_REVIEW_FORCE_POLLING = os.environ.get("NEWS_REVIEW_FORCE_POLLING", "true").lower() in ("1", "true", "yes", "on")


RELEVANCE_ERO_KEYWORDS = {
    "nsfw", "adult", "18+", "erotic", "hentai", "ecchi", "lewd",
    "uncensor", "uncensored", "censored", "visual novel", "dating sim",
    "sex game", "porn game", "bdsm", "fetish", "mature", "16+", "17+",
    "r18", "r-18", "ero", "adult mod", "nsfw mod", "romance",
}

RELEVANCE_GLOBAL_NSFW_KEYWORDS = {
    # Core adult / porn
    "nsfw", "adult", "18+", "17+", "r18", "r-18", "porn", "xxx", "erotic", "erotica",
    "sex", "sexual", "hentai", "ecchi", "lewd", "bdsm", "fetish", "camgirl", "cams",
    "onlyfans", "fansly", "adult performer", "pornstar", "nude", "nudes", "uncensored",
    # Adult content verticals
    "vr porn", "ai porn", "deepfake", "doujin", "ero", "eroge", "adult game",
    "sex game", "porn game", "visual novel", "dating sim", "adult mod", "nsfw mod",
}

HARD_BLOCK_ILLEGAL_KEYWORDS = {
    "loli", "shota", "minor", "underage", "child", "cp", "teenage",
}

GENERIC_NEWS_TITLES = {
    "visual novels",
    "latest posts",
    "new posts",
    "hot posts",
    "top posts",
    "community",
}

RELEVANCE_GAME_KEYWORDS = {
    "steam", "itch.io", "patreon", "dlsite", "mod", "modding", "workshop",
    "release", "demo", "wishlist", "patch", "update", "build", "game",
}

RELEVANCE_AI_KEYWORDS = {
    "ai", "neural", "llm", "stable diffusion", "lora", "model",
    "image generation", "video generation", "text-to-image", "text-to-video",
}

EXCLUDE_KEYWORDS = {
    "politics", "election", "war", "stock market",
}

POLICY_PAYMENT_EXCLUDE = {
    "visa", "mastercard", "payment provider", "payment processors",
    "processor", "ftc", "commission", "regulation", "regulator",
    "lawsuit", "legal", "law", "censorship", "compliance",
    "bank", "banking", "policy change", "policy",
}

RELEASE_SIGNAL_KEYWORDS = {
    "release", "released", "launch", "launched", "demo", "out now",
    "patch", "update", "updated", "hotfix", "roadmap", "devlog",
    "new build", "build", "v0.", "v1.", "alpha", "beta", "steam page",
    "wishlist", "mod", "modding", "workshop", "dlc",
}


@dataclass
class NewsItem:
    title: str
    link: str
    summary: str
    source: str
    published_ts: float
    image_url: str
    image_candidates: list[str]
    source_kind: str


def _load_state() -> dict:
    if not Path(NEWS_STATE_FILE).exists():
        return {"posted_links": [], "last_post_source_kind": "", "reddit_streak": 0}
    try:
        with open(NEWS_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"posted_links": [], "last_post_source_kind": "", "reddit_streak": 0}
        data.setdefault("posted_links", [])
        data.setdefault("last_post_source_kind", "")
        data.setdefault("reddit_streak", 0)
        return data
    except Exception as e:
        logger.warning(f"Failed to load {NEWS_STATE_FILE}: {e}")
        return {"posted_links": [], "last_post_source_kind": "", "reddit_streak": 0}


def _save_state(state: dict) -> None:
    posted = list(dict.fromkeys(state.get("posted_links", [])))
    if len(posted) > NEWS_MAX_POSTED_LINKS:
        posted = posted[-NEWS_MAX_POSTED_LINKS:]
    state["posted_links"] = posted
    with open(NEWS_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _load_pending_draft() -> dict:
    if not Path(NEWS_PENDING_DRAFT_FILE).exists():
        return {}
    try:
        with open(NEWS_PENDING_DRAFT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_pending_draft(data: dict) -> None:
    with open(NEWS_PENDING_DRAFT_FILE, "w", encoding="utf-8") as f:
        json.dump(data if isinstance(data, dict) else {}, f, ensure_ascii=False, indent=2)


def _load_review_state() -> dict:
    if not Path(NEWS_REVIEW_STATE_FILE).exists():
        return {"last_update_id": 0}
    try:
        with open(NEWS_REVIEW_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"last_update_id": 0}
        data.setdefault("last_update_id", 0)
        return data
    except Exception:
        return {"last_update_id": 0}


def _save_review_state(data: dict) -> None:
    with open(NEWS_REVIEW_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data if isinstance(data, dict) else {"last_update_id": 0}, f, ensure_ascii=False, indent=2)


def _normalize_link(link: str) -> str:
    parsed = urlparse(str(link).strip())
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return base.rstrip("/")


def _is_generic_reddit_or_index_link(item: NewsItem) -> bool:
    """
    Filters out low-value links like subreddit root pages or generic index pages.
    """
    link = str(item.link or "").lower().strip()
    title = str(item.title or "").lower().strip()

    # Reddit root/subreddit links without concrete post/comment target.
    if "reddit.com/r/" in link and "/comments/" not in link:
        return True

    # Generic forum/feed index pages.
    if re.search(r"/(forums?|community|tag|tags|categories|index)(/|$)", link):
        if "/threads/" not in link and "/posts/" not in link and "/comments/" not in link:
            return True

    # Too generic title cards.
    if title in GENERIC_NEWS_TITLES:
        return True
    if len(title) < 10:
        return True
    return False


def _detect_source_kind(feed_url: str, item_link: str) -> str:
    blob = f"{feed_url} {item_link}".lower()
    if "store.steampowered.com/feeds/news/app/" in blob or "steamcommunity.com" in blob:
        return "steam"
    if "itch.io" in blob:
        return "itch"
    if "reddit.com" in blob:
        return "reddit"
    return "other"


def _source_priority(kind: str) -> int:
    if kind == "steam":
        return 4
    if kind == "itch":
        return 3
    if kind == "reddit":
        return 2
    return 1


def _to_text(value: object) -> str:
    txt = str(value or "")
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def _parse_published_ts(entry) -> float:
    dt = None
    published = getattr(entry, "published", None) or getattr(entry, "updated", None)
    if published:
        try:
            dt = parsedate_to_datetime(published)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            dt = None
    if not dt:
        dt = datetime.now(timezone.utc)
    return dt.timestamp()


def _extract_image_url(entry) -> str:
    """
    Tries to get a representative image from RSS entry.
    Supports common feed fields and HTML summary fallbacks.
    """
    # media_content / media_thumbnail
    media_content = getattr(entry, "media_content", None) or []
    for m in media_content:
        url = str((m or {}).get("url", "")).strip()
        if url and url.startswith("http"):
            return url

    media_thumb = getattr(entry, "media_thumbnail", None) or []
    for m in media_thumb:
        url = str((m or {}).get("url", "")).strip()
        if url and url.startswith("http"):
            return url

    # links: enclosure image/*
    links = getattr(entry, "links", None) or []
    for lnk in links:
        rel = str((lnk or {}).get("rel", "")).lower()
        ltype = str((lnk or {}).get("type", "")).lower()
        href = str((lnk or {}).get("href", "")).strip()
        if href and href.startswith("http") and (rel == "enclosure" or ltype.startswith("image/")):
            return href

    # generic image field
    image_obj = getattr(entry, "image", None)
    if isinstance(image_obj, dict):
        href = str(image_obj.get("href", "")).strip()
        if href and href.startswith("http"):
            return href

    # summary HTML <img src="...">
    summary = str(getattr(entry, "summary", "") or "")
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary, flags=re.IGNORECASE)
    if m:
        url = m.group(1).strip()
        if url.startswith("http"):
            return url

    return ""


def _extract_image_candidates(entry) -> list[str]:
    candidates = []

    def push(url: str):
        u = str(url or "").strip()
        if u.startswith("http") and u not in candidates:
            candidates.append(u)

    media_content = getattr(entry, "media_content", None) or []
    for m in media_content:
        push((m or {}).get("url", ""))

    media_thumb = getattr(entry, "media_thumbnail", None) or []
    for m in media_thumb:
        push((m or {}).get("url", ""))

    links = getattr(entry, "links", None) or []
    for lnk in links:
        rel = str((lnk or {}).get("rel", "")).lower()
        ltype = str((lnk or {}).get("type", "")).lower()
        if rel == "enclosure" or ltype.startswith("image/"):
            push((lnk or {}).get("href", ""))

    image_obj = getattr(entry, "image", None)
    if isinstance(image_obj, dict):
        push(image_obj.get("href", ""))

    summary = str(getattr(entry, "summary", "") or "")
    for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', summary, flags=re.IGNORECASE):
        push(m.group(1))

    return candidates


def _keyword_hits(blob: str, keywords: set[str]) -> int:
    return sum(1 for k in keywords if k in blob)


def _is_relevant(item: NewsItem) -> bool:
    """
    Strict mode:
    - erotica context required
    - release/update/mod signal required
    """
    blob = f"{item.title} {item.summary}".lower()
    title_blob = item.title.lower()
    if _is_generic_reddit_or_index_link(item):
        return False
    if any(x in blob for x in EXCLUDE_KEYWORDS):
        return False
    if any(x in blob for x in POLICY_PAYMENT_EXCLUDE):
        return False

    ero_hits = _keyword_hits(blob, RELEVANCE_ERO_KEYWORDS)
    game_hits = _keyword_hits(blob, RELEVANCE_GAME_KEYWORDS)
    ai_hits = _keyword_hits(blob, RELEVANCE_AI_KEYWORDS)
    title_ero_hits = _keyword_hits(title_blob, RELEVANCE_ERO_KEYWORDS)
    release_hits = _keyword_hits(blob, RELEASE_SIGNAL_KEYWORDS)
    title_release_hits = _keyword_hits(title_blob, RELEASE_SIGNAL_KEYWORDS)

    # Strict by default: keep only erotica-related news with gaming/AI context.
    # This prevents random generic gaming posts from slipping in.
    if title_ero_hits == 0 and ero_hits < 2:
        return False
    # For this channel we prefer practical news (release/update/mod/demo).
    if release_hits == 0 and title_release_hits == 0:
        return False
    if ero_hits >= 1 and (game_hits >= 1 or ai_hits >= 1):
        return True
    if ero_hits >= 2:
        return True
    return False


def _is_relevant_soft(item: NewsItem) -> bool:
    """
    Thematic mode:
    - erotica + game/ai context
    - no mandatory release/update signal
    """
    blob = f"{item.title} {item.summary}".lower()
    if _is_generic_reddit_or_index_link(item):
        return False
    if any(x in blob for x in EXCLUDE_KEYWORDS):
        return False
    if any(x in blob for x in POLICY_PAYMENT_EXCLUDE):
        return False

    ero_hits = _keyword_hits(blob, RELEVANCE_ERO_KEYWORDS)
    game_hits = _keyword_hits(blob, RELEVANCE_GAME_KEYWORDS)
    ai_hits = _keyword_hits(blob, RELEVANCE_AI_KEYWORDS)
    release_hits = _keyword_hits(blob, RELEASE_SIGNAL_KEYWORDS)
    # allow broader "channel-topic" posts:
    # nsfw/mature + (game|ai) OR explicit release/mod/update signals.
    if ero_hits >= 1 and (game_hits >= 1 or ai_hits >= 1):
        return True
    if ero_hits >= 1 and release_hits >= 1:
        return True
    return False


def _is_relevant_nsfw_only(item: NewsItem) -> bool:
    """
    Very loose mode for review inbox:
    any erotica/nsfw signal passes (except hard excluded policy topics).
    """
    blob = f"{item.title} {item.summary}".lower()
    if _is_generic_reddit_or_index_link(item):
        return False
    if any(x in blob for x in EXCLUDE_KEYWORDS):
        return False
    if any(x in blob for x in HARD_BLOCK_ILLEGAL_KEYWORDS):
        return False
    global_hits = _keyword_hits(blob, RELEVANCE_GLOBAL_NSFW_KEYWORDS)
    return global_hits >= 1


def _fetch_news() -> list[NewsItem]:
    lookback = (datetime.now(timezone.utc) - timedelta(hours=NEWS_LOOKBACK_HOURS)).timestamp()
    collected: list[NewsItem] = []
    seen_links = set()

    for src in get_news_sources():
        try:
            logger.info(f"Fetching feed: {src}")
            # Use explicit HTTP fetch with timeout so one broken source can't stall the whole run.
            resp = requests.get(
                src,
                timeout=NEWS_FEED_TIMEOUT,
                headers={"User-Agent": "ErosLabNewsBot/1.0 (+https://t.me/eroslabai)"},
            )
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            entries = getattr(feed, "entries", []) or []
            logger.info(f"Feed entries: {len(entries)} ({src})")
            for entry in entries[:NEWS_FETCH_LIMIT]:
                title = _to_text(getattr(entry, "title", ""))
                link = _normalize_link(getattr(entry, "link", ""))
                summary = _to_text(getattr(entry, "summary", ""))[:600]
                if not title or not link:
                    continue
                if link in seen_links:
                    continue
                seen_links.add(link)
                published_ts = _parse_published_ts(entry)
                if published_ts < lookback:
                    continue
                item = NewsItem(
                    title=title,
                    link=link,
                    summary=summary,
                    source=urlparse(src).netloc,
                    published_ts=published_ts,
                    image_url=_extract_image_url(entry),
                    image_candidates=_extract_image_candidates(entry),
                    source_kind=_detect_source_kind(src, link),
                )
                collected.append(item)
        except Exception as e:
            logger.warning(f"Failed to parse feed {src}: {e}")

    strict = [x for x in collected if _is_relevant(x)]
    soft = [x for x in collected if _is_relevant_soft(x)]

    if NEWS_FILTER_MODE == "strict":
        selected = strict
        selected_mode = "strict"
    elif NEWS_FILTER_MODE == "nsfw_only":
        selected = [x for x in collected if _is_relevant_nsfw_only(x)]
        selected_mode = "nsfw_only"
    elif NEWS_FILTER_MODE == "thematic":
        # Prefer broader thematic flow, fallback to strict if needed.
        selected = soft if soft else strict
        selected_mode = "thematic" if soft else "strict-fallback"
    else:
        # auto: keep previous behavior.
        selected = strict if strict else soft
        selected_mode = "strict" if strict else "soft-fallback"

    selected.sort(key=lambda x: (_source_priority(x.source_kind), x.published_ts), reverse=True)
    logger.info(f"Relevant fresh news items: {len(selected)} (mode={selected_mode})")
    return selected


def _available_ai_provider() -> str | None:
    if AI_PROVIDER in {"groq", "openrouter"}:
        return AI_PROVIDER
    if GROQ_API_KEY:
        return "groq"
    if OPENROUTER_API_KEY:
        return "openrouter"
    return None


def _call_ai_chat(prompt: str, system_prompt: str, max_tokens: int = 220, temperature: float = 0.7) -> str | None:
    provider = _available_ai_provider()
    if not provider:
        return None

    if provider == "groq":
        url = "https://api.groq.com/openai/v1/chat/completions"
        api_key = GROQ_API_KEY
        model = GROQ_MODEL
    else:
        url = "https://openrouter.ai/api/v1/chat/completions"
        api_key = OPENROUTER_API_KEY
        model = OPENROUTER_MODEL

    payload = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=AI_TIMEOUT_SEC)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return str(content).strip() or None
    except Exception as e:
        logger.warning(f"AI news call failed ({provider}): {e}")
        return None


def _fallback_hook(item: NewsItem) -> str:
    title = item.title
    if len(title) > 86:
        title = title[:83].rstrip() + "..."
    prefixes = [
        "Громкий апдейт:",
        "Свежее в ленту:",
        "Залетела новость:",
        "Новый движ:",
    ]
    return f"{random.choice(prefixes)} {title}"


def _fallback_bullets(item: NewsItem) -> tuple[str, str, str, str, str]:
    summary = item.summary or item.title
    chunks = re.split(r"[.!?]\s+", summary)
    chunks = [c.strip(" -•") for c in chunks if c.strip()]
    while len(chunks) < 4:
        chunks.append(item.title)
    lead = chunks[0][:170]
    b1 = chunks[0][:110]
    b2 = chunks[1][:110]
    b3 = chunks[2][:110]
    b4 = chunks[3][:110]
    return lead, b1, b2, b3, b4


def _generate_aggressive_parts(item: NewsItem) -> tuple[str, str, str, str, str, str]:
    if not ENABLE_AI_NEWS:
        hook = _fallback_hook(item)
        lead, b1, b2, b3, b4 = _fallback_bullets(item)
        return hook, lead, b1, b2, b3, b4

    prompt = (
        "Сделай Telegram-пост в стиле игрового NSFW-медиа: живо, дорого, без кринжа.\n"
        "Верни строго 6 строк в формате:\n"
        "HOOK: ...\n"
        "LEAD: ...\n"
        "B1: ...\n"
        "B2: ...\n"
        "B3: ...\n"
        "B4: ...\n\n"
        "Требования:\n"
        "- Русский язык, энергично, но адекватно.\n"
        "- Без матов.\n"
        "- HOOK до 90 символов, как афиша релиза.\n"
        "- LEAD 1-2 предложения до 180 символов.\n"
        "- B1/B2/B3 короткие и конкретные факты/детали.\n"
        "- B4 про фичу/контент/платформу.\n"
        "- Не выдумывай факты.\n\n"
        f"TITLE: {item.title}\n"
        f"SUMMARY: {item.summary}\n"
        f"SOURCE: {item.source}\n"
    )
    system = "Ты редактор премиальных news-постов для Telegram-канала."
    raw = _call_ai_chat(prompt, system, max_tokens=260, temperature=0.65)
    if not raw:
        hook = _fallback_hook(item)
        lead, b1, b2, b3, b4 = _fallback_bullets(item)
        return hook, lead, b1, b2, b3, b4

    lines = [x.strip() for x in str(raw).splitlines() if x.strip()]
    parsed = {}
    for ln in lines:
        if ":" not in ln:
            continue
        k, v = ln.split(":", 1)
        parsed[k.strip().upper()] = v.strip()

    hook = parsed.get("HOOK") or _fallback_hook(item)
    fb = _fallback_bullets(item)
    lead = parsed.get("LEAD") or fb[0]
    b1 = parsed.get("B1") or fb[1]
    b2 = parsed.get("B2") or fb[2]
    b3 = parsed.get("B3") or fb[3]
    b4 = parsed.get("B4") or fb[4]

    return hook[:90], lead[:180], b1[:120], b2[:120], b3[:120], b4[:120]


def _infer_platforms(item: NewsItem) -> str:
    blob = f"{item.title} {item.summary}".lower()
    platforms = []
    if "android" in blob:
        platforms.append("Android")
    if "ios" in blob:
        platforms.append("iOS")
    if any(x in blob for x in ("pc", "windows", "win")):
        platforms.append("PC")
    if "linux" in blob:
        platforms.append("Linux")
    if "mac" in blob:
        platforms.append("Mac")
    if not platforms:
        return "PC / Mobile"
    return ", ".join(dict.fromkeys(platforms))


def _infer_locale(item: NewsItem) -> str:
    blob = f"{item.title} {item.summary}".lower()
    if any(x in blob for x in ("рус", "russian", "ru ", " ru", "ru-")):
        return "русский"
    if any(x in blob for x in ("english", "en ", " en", "en-")):
        return "английский"
    return "уточняется"


def _build_post_text(item: NewsItem) -> str:
    hook, lead, b1, b2, b3, b4 = _generate_aggressive_parts(item)
    kind_label = "Dev Update" if item.source_kind in ("steam", "itch", "reddit") else "News Drop"
    source_label = "F95 / community thread" if "f95zone.to" in item.link.lower() else item.source
    platforms = _infer_platforms(item)
    locale = _infer_locale(item)
    return (
        f"🎮 {hook}\n\n"
        f"<blockquote>{lead}</blockquote>\n\n"
        f"✦ {b1}\n"
        f"✦ {b2}\n"
        f"✦ {b3}\n\n"
        f"✦ {b4}\n\n"
        f"✦ Формат: {kind_label}\n"
        f"✦ Источник: {source_label}\n"
        f"✦ Платформы: {platforms}\n"
        f"✦ Локализация: {locale}\n"
        f"✦ Материал: {item.title[:120]}\n\n"
        f"🔗 {item.link}\n"
        f"{WATERMARK_TEXT}"
    )


def _score_image_size(width: int, height: int) -> float:
    if width < NEWS_MIN_IMAGE_WIDTH or height < NEWS_MIN_IMAGE_HEIGHT:
        return -1.0
    area_score = min((width * height) / (1280 * 720), 4.0)
    ratio = width / max(1, height)
    if 1.2 <= ratio <= 1.9:
        ratio_bonus = 1.0
    elif 0.9 <= ratio <= 2.1:
        ratio_bonus = 0.6
    else:
        ratio_bonus = 0.1
    return area_score + ratio_bonus


def _pick_best_image_url(item: NewsItem) -> str:
    candidates = list(item.image_candidates or [])
    if item.image_url and item.image_url not in candidates:
        candidates.insert(0, item.image_url)
    if not candidates:
        return ""

    # Lazy import to keep start-up lightweight.
    from io import BytesIO
    from PIL import Image

    best_url = ""
    best_score = -1.0

    for url in candidates[:6]:
        try:
            resp = requests.get(url, timeout=NEWS_IMAGE_CHECK_TIMEOUT)
            if resp.status_code != 200:
                continue
            ctype = str(resp.headers.get("Content-Type", "")).lower()
            if "image" not in ctype:
                continue
            data = resp.content
            if not data:
                continue
            img = Image.open(BytesIO(data))
            width, height = img.size
            score = _score_image_size(width, height)
            if score > best_score:
                best_score = score
                best_url = url
        except Exception:
            continue

    if best_score < 0:
        return ""
    return best_url


def _pick_best_image_urls(item: NewsItem, limit: int = 3) -> list[str]:
    candidates = list(item.image_candidates or [])
    if item.image_url and item.image_url not in candidates:
        candidates.insert(0, item.image_url)
    if not candidates:
        return []

    from io import BytesIO
    from PIL import Image

    scored = []
    for url in candidates[:8]:
        try:
            resp = requests.get(url, timeout=NEWS_IMAGE_CHECK_TIMEOUT)
            if resp.status_code != 200:
                continue
            ctype = str(resp.headers.get("Content-Type", "")).lower()
            if "image" not in ctype:
                continue
            data = resp.content
            if not data:
                continue
            img = Image.open(BytesIO(data))
            width, height = img.size
            score = _score_image_size(width, height)
            if score >= 0:
                scored.append((score, url))
        except Exception:
            continue

    if not scored:
        return []

    scored.sort(key=lambda x: x[0], reverse=True)
    ordered = []
    seen = set()
    for _, url in scored:
        if url in seen:
            continue
        seen.add(url)
        ordered.append(url)
        if len(ordered) >= max(1, limit):
            break
    return ordered


def _parse_review_command(text: str):
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return None, "", ""

    lines = raw.splitlines()
    head = lines[0].strip()
    parts = head.split(maxsplit=2)
    cmd = parts[0].lower()
    draft_id = parts[1].strip() if len(parts) >= 2 else ""
    inline_text = parts[2].strip() if len(parts) >= 3 else ""
    extra_text = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
    custom_text = extra_text or inline_text or ""
    return cmd, draft_id, custom_text


async def _poll_review_action(bot: Bot, review_state: dict):
    if not ADMIN_USER_ID:
        return None

    last_update_id = int(review_state.get("last_update_id", 0))
    try:
        updates = await bot.get_updates(offset=last_update_id + 1, limit=50, timeout=0)
    except Exception as e:
        logger.warning(f"Could not fetch review commands: {e}")
        return None

    action = None
    for upd in updates:
        review_state["last_update_id"] = max(int(review_state.get("last_update_id", 0)), int(upd.update_id))
        msg = getattr(upd, "message", None)
        if not msg or not msg.text:
            continue
        from_user = getattr(msg, "from_user", None)
        if not from_user or str(from_user.id) != ADMIN_USER_ID:
            continue

        cmd, draft_id, custom_text = _parse_review_command(msg.text)
        if cmd in ("/approve", "/news_approve"):
            action = {"cmd": "approve", "draft_id": draft_id, "text": custom_text}
        elif cmd in ("/reject", "/news_reject"):
            action = {"cmd": "reject", "draft_id": draft_id, "text": ""}

    _save_review_state(review_state)
    return action


def _build_payload_for_item(item: NewsItem, allow_no_image: bool = False):
    text = _build_post_text(item)
    if len(text) > 1000:
        text = text[:997].rstrip() + "..."

    best_images = _pick_best_image_urls(item, limit=NEWS_MEDIA_MAX_IMAGES)
    if not best_images and NEWS_REQUIRE_IMAGE and not allow_no_image:
        return None
    return {"text": text, "image_urls": best_images}


async def _send_payload(bot: Bot, chat_id: str, payload: dict, is_draft: bool = False):
    text = str(payload.get("text", "") or "")
    if is_draft:
        text = f"[DRAFT]\n{text}"
    image_urls = list(payload.get("image_urls", []) or [])

    if image_urls:
        if len(image_urls) == 1:
            await bot.send_photo(chat_id=chat_id, photo=image_urls[0], caption=text)
            return
        media = []
        for idx, url in enumerate(image_urls):
            if idx == 0:
                media.append(InputMediaPhoto(media=url, caption=text))
            else:
                media.append(InputMediaPhoto(media=url))
        await bot.send_media_group(chat_id=chat_id, media=media)
        return

    await bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=True)


async def _send_review_help(bot: Bot, draft_id: str):
    if not ADMIN_USER_ID:
        return
    text = (
        f"🧪 News draft: <code>{draft_id}</code>\n"
        f"<code>/approve {draft_id}</code> — опубликовать как есть\n"
        f"<code>/approve {draft_id}\\nТВОЙ_ТЕКСТ</code> — опубликовать с твоим текстом\n"
        f"<code>/reject {draft_id}</code> — отклонить\n"
        "<code>/approve</code> или <code>/reject</code> — для текущего черновика"
    )
    await bot.send_message(chat_id=ADMIN_USER_ID, text=text, parse_mode="HTML")


async def _ensure_review_polling_mode(bot: Bot):
    """
    getUpdates cannot work while webhook is active (409 Conflict).
    For CI review mode we switch bot to polling mode once per run.
    """
    if not NEWS_REVIEW_FORCE_POLLING:
        return
    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except Exception as e:
        logger.warning(f"Could not delete webhook for polling mode: {e}")


async def _post_news_items(items: list[NewsItem], posted_links: set[str], state: dict) -> int:
    if not TELEGRAM_BOT_TOKEN:
        logger.error("No TELEGRAM_BOT_TOKEN; abort.")
        return 0

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    sent = 0
    reddit_streak = int(state.get("reddit_streak", 0))
    last_kind = str(state.get("last_post_source_kind", ""))
    for item in items:
        normalized = _normalize_link(item.link)
        if normalized in posted_links:
            continue
        if item.source_kind == "reddit" and reddit_streak >= NEWS_MAX_REDDIT_STREAK:
            logger.info(f"Skip reddit due to streak limit ({NEWS_MAX_REDDIT_STREAK}): {item.title[:90]}")
            continue
        payload = _build_payload_for_item(item)
        if payload is None:
            logger.info(f"Skip news without quality image: {item.title[:90]}")
            continue
        try:
            await _send_payload(bot, TELEGRAM_CHANNEL_ID, payload, is_draft=False)
            posted_links.add(normalized)
            sent += 1
            logger.info(f"News posted: {item.title[:90]}")
            last_kind = item.source_kind
            if item.source_kind == "reddit":
                reddit_streak += 1
            else:
                reddit_streak = 0
        except Exception as e:
            logger.warning(f"Failed to send news post: {e}")
        if sent >= NEWS_MAX_PER_RUN:
            break
    state["last_post_source_kind"] = last_kind
    state["reddit_streak"] = reddit_streak
    return sent


async def main() -> None:
    logger.info("=" * 50)
    logger.info("Starting ErosLab News Poster (aggressive style)")
    logger.info(f"Channel: {TELEGRAM_CHANNEL_ID}")
    logger.info("=" * 50)

    state = _load_state()
    posted_links = set(_normalize_link(x) for x in state.get("posted_links", []))
    review_state = _load_review_state()
    pending_draft = _load_pending_draft()

    all_items = _fetch_news()
    fresh_items = [x for x in all_items if _normalize_link(x.link) not in posted_links]
    logger.info(f"Fresh news items: {len(fresh_items)}")

    if NEWS_REVIEW_MODE:
        if not ADMIN_USER_ID:
            logger.error("NEWS_REVIEW_MODE enabled but ADMIN_USER_ID is empty")
            return

        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await _ensure_review_polling_mode(bot)
        action = await _poll_review_action(bot, review_state)

        if pending_draft and action:
            pending_id = str(pending_draft.get("id", ""))
            action_id = str(action.get("draft_id", "") or pending_id)
            if action_id.strip().upper() == "DRAFT_ID":
                action_id = pending_id
            if action_id != pending_id:
                await bot.send_message(
                    chat_id=ADMIN_USER_ID,
                    text=f"Черновик <code>{action_id}</code> не найден. Текущий: <code>{pending_id}</code>",
                    parse_mode="HTML",
                )
            elif action["cmd"] == "reject":
                posted_links.add(_normalize_link(pending_draft.get("link", "")))
                pending_draft.clear()
                _save_pending_draft(pending_draft)
                await bot.send_message(chat_id=ADMIN_USER_ID, text=f"Отклонено: {pending_id}")
                logger.info(f"Rejected draft: {pending_id}")
                state["posted_links"] = list(posted_links)
                _save_state(state)
                return
            elif action["cmd"] == "approve":
                final_text = action.get("text") or str(pending_draft.get("text", ""))
                payload = {
                    "text": final_text,
                    "image_urls": list(pending_draft.get("image_urls", []) or []),
                }
                try:
                    await _send_payload(bot, TELEGRAM_CHANNEL_ID, payload, is_draft=False)
                    posted_links.add(_normalize_link(pending_draft.get("link", "")))
                    await bot.send_message(chat_id=ADMIN_USER_ID, text=f"Опубликовано: {pending_id}")
                    logger.info(f"Approved and published: {pending_id}")
                except Exception as e:
                    logger.warning(f"Failed to publish approved draft: {e}")
                pending_draft.clear()
                _save_pending_draft(pending_draft)
                state["posted_links"] = list(posted_links)
                _save_state(state)
                return

        if pending_draft:
            logger.info(f"Waiting for review decision on draft: {pending_draft.get('id')}")
            return

        # Prepare a new draft candidate.
        reddit_streak = int(state.get("reddit_streak", 0))
        candidate = None
        candidate_payload = None
        for item in fresh_items:
            # In review mode we should not over-filter candidate drafts.
            if item.source_kind == "reddit" and reddit_streak >= NEWS_MAX_REDDIT_STREAK:
                continue
            # In review mode allow text-only draft when image quality filter is too strict.
            payload = _build_payload_for_item(item, allow_no_image=True)
            if payload is None:
                continue
            candidate = item
            candidate_payload = payload
            break

        # Fallback: if streak rule removed all candidates, try again without streak restriction.
        if not candidate:
            for item in fresh_items:
                payload = _build_payload_for_item(item, allow_no_image=True)
                if payload is None:
                    continue
                candidate = item
                candidate_payload = payload
                break

        if not candidate or not candidate_payload:
            logger.info("No suitable item for review draft")
            return

        pending_draft = {
            "id": f"news_{int(candidate.published_ts)}",
            "item_title": candidate.title,
            "link": candidate.link,
            "source_kind": candidate.source_kind,
            "text": candidate_payload["text"],
            "image_urls": candidate_payload["image_urls"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_pending_draft(pending_draft)

        await _send_payload(bot, ADMIN_USER_ID, candidate_payload, is_draft=True)
        await _send_review_help(bot, pending_draft["id"])
        logger.info(f"Draft sent to admin: {pending_draft['id']}")
        return

    sent_count = await _post_news_items(fresh_items, posted_links, state)
    logger.info(f"Sent news posts: {sent_count}")

    state["posted_links"] = list(posted_links)
    _save_state(state)


if __name__ == "__main__":
    asyncio.run(main())
