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
from telegram import Bot

from news_sources import get_news_sources


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "@eroslabai")
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


RELEVANCE_ERO_KEYWORDS = {
    "nsfw", "adult", "18+", "erotic", "hentai", "ecchi", "lewd",
    "uncensor", "uncensored", "censored", "visual novel", "dating sim",
    "sex game", "porn game", "bdsm", "fetish",
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


@dataclass
class NewsItem:
    title: str
    link: str
    summary: str
    source: str
    published_ts: float


def _load_state() -> dict:
    if not Path(NEWS_STATE_FILE).exists():
        return {"posted_links": []}
    try:
        with open(NEWS_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"posted_links": []}
        data.setdefault("posted_links", [])
        return data
    except Exception as e:
        logger.warning(f"Failed to load {NEWS_STATE_FILE}: {e}")
        return {"posted_links": []}


def _save_state(state: dict) -> None:
    posted = list(dict.fromkeys(state.get("posted_links", [])))
    if len(posted) > NEWS_MAX_POSTED_LINKS:
        posted = posted[-NEWS_MAX_POSTED_LINKS:]
    state["posted_links"] = posted
    with open(NEWS_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _normalize_link(link: str) -> str:
    parsed = urlparse(str(link).strip())
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return base.rstrip("/")


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


def _keyword_hits(blob: str, keywords: set[str]) -> int:
    return sum(1 for k in keywords if k in blob)


def _is_relevant(item: NewsItem) -> bool:
    blob = f"{item.title} {item.summary}".lower()
    title_blob = item.title.lower()
    if any(x in blob for x in EXCLUDE_KEYWORDS):
        return False

    ero_hits = _keyword_hits(blob, RELEVANCE_ERO_KEYWORDS)
    game_hits = _keyword_hits(blob, RELEVANCE_GAME_KEYWORDS)
    ai_hits = _keyword_hits(blob, RELEVANCE_AI_KEYWORDS)
    title_ero_hits = _keyword_hits(title_blob, RELEVANCE_ERO_KEYWORDS)

    # Strict by default: keep only erotica-related news with gaming/AI context.
    # This prevents random generic gaming posts from slipping in.
    if title_ero_hits == 0 and ero_hits < 2:
        return False
    if ero_hits >= 1 and (game_hits >= 1 or ai_hits >= 1):
        return True
    if ero_hits >= 2:
        return True
    return False


def _fetch_news() -> list[NewsItem]:
    lookback = (datetime.now(timezone.utc) - timedelta(hours=NEWS_LOOKBACK_HOURS)).timestamp()
    collected: list[NewsItem] = []
    seen_links = set()

    for src in get_news_sources():
        try:
            logger.info(f"Fetching feed: {src}")
            feed = feedparser.parse(src)
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
                )
                if _is_relevant(item):
                    collected.append(item)
        except Exception as e:
            logger.warning(f"Failed to parse feed {src}: {e}")

    # Newest first.
    collected.sort(key=lambda x: x.published_ts, reverse=True)
    logger.info(f"Relevant fresh news items: {len(collected)}")
    return collected


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


def _fallback_bullets(item: NewsItem) -> tuple[str, str, str, str]:
    summary = item.summary or item.title
    chunks = re.split(r"[.!?]\s+", summary)
    chunks = [c.strip(" -•") for c in chunks if c.strip()]
    while len(chunks) < 3:
        chunks.append(item.title)
    b1 = chunks[0][:110]
    b2 = chunks[1][:110]
    b3 = chunks[2][:110]
    why = "Если тема тебе близка, это хороший кандидат в вишлист."
    return b1, b2, b3, why


def _generate_aggressive_parts(item: NewsItem) -> tuple[str, str, str, str, str]:
    if not ENABLE_AI_NEWS:
        hook = _fallback_hook(item)
        b1, b2, b3, why = _fallback_bullets(item)
        return hook, b1, b2, b3, why

    prompt = (
        "Сделай Telegram-пост в агрессивном стиле про новость.\n"
        "Верни строго 5 строки в формате:\n"
        "HOOK: ...\n"
        "B1: ...\n"
        "B2: ...\n"
        "B3: ...\n"
        "WHY: ...\n\n"
        "Требования:\n"
        "- Русский язык, живо, без кринжа.\n"
        "- Без матов, без токсичности.\n"
        "- HOOK до 90 символов.\n"
        "- B1/B2/B3 короткие и конкретные.\n"
        "- WHY 1 строка до 110 символов.\n"
        "- Не выдумывай факты.\n\n"
        f"TITLE: {item.title}\n"
        f"SUMMARY: {item.summary}\n"
        f"SOURCE: {item.source}\n"
    )
    system = "Ты редактор вирусных news-постов для Telegram."
    raw = _call_ai_chat(prompt, system, max_tokens=260, temperature=0.65)
    if not raw:
        hook = _fallback_hook(item)
        b1, b2, b3, why = _fallback_bullets(item)
        return hook, b1, b2, b3, why

    lines = [x.strip() for x in str(raw).splitlines() if x.strip()]
    parsed = {}
    for ln in lines:
        if ":" not in ln:
            continue
        k, v = ln.split(":", 1)
        parsed[k.strip().upper()] = v.strip()

    hook = parsed.get("HOOK") or _fallback_hook(item)
    b1 = parsed.get("B1") or _fallback_bullets(item)[0]
    b2 = parsed.get("B2") or _fallback_bullets(item)[1]
    b3 = parsed.get("B3") or _fallback_bullets(item)[2]
    why = parsed.get("WHY") or _fallback_bullets(item)[3]

    return hook[:90], b1[:120], b2[:120], b3[:120], why[:110]


def _build_post_text(item: NewsItem) -> str:
    hook, b1, b2, b3, why = _generate_aggressive_parts(item)
    return (
        f"📰 {hook}\n\n"
        "Что внутри:\n"
        f"• {b1}\n"
        f"• {b2}\n"
        f"• {b3}\n\n"
        "Почему стоит чекнуть:\n"
        f"{why}\n\n"
        f"🔗 Читать: {item.link}\n"
        f"{WATERMARK_TEXT}"
    )


async def _post_news_items(items: list[NewsItem], posted_links: set[str]) -> int:
    if not TELEGRAM_BOT_TOKEN:
        logger.error("No TELEGRAM_BOT_TOKEN; abort.")
        return 0

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    sent = 0
    for item in items:
        normalized = _normalize_link(item.link)
        if normalized in posted_links:
            continue
        text = _build_post_text(item)
        try:
            await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=text, disable_web_page_preview=False)
            posted_links.add(normalized)
            sent += 1
            logger.info(f"News posted: {item.title[:90]}")
        except Exception as e:
            logger.warning(f"Failed to send news post: {e}")
        if sent >= NEWS_MAX_PER_RUN:
            break
    return sent


async def main() -> None:
    logger.info("=" * 50)
    logger.info("Starting ErosLab News Poster (aggressive style)")
    logger.info(f"Channel: {TELEGRAM_CHANNEL_ID}")
    logger.info("=" * 50)

    state = _load_state()
    posted_links = set(_normalize_link(x) for x in state.get("posted_links", []))

    all_items = _fetch_news()
    fresh_items = [x for x in all_items if _normalize_link(x.link) not in posted_links]
    logger.info(f"Fresh news items: {len(fresh_items)}")

    sent_count = await _post_news_items(fresh_items, posted_links)
    logger.info(f"Sent news posts: {sent_count}")

    state["posted_links"] = list(posted_links)
    _save_state(state)


if __name__ == "__main__":
    asyncio.run(main())
