"""
ErosLab Bot — NSFW Steam Deals
Парсит CheapShark + Steam API, фильтрует NSFW-игры,
генерирует хайповый текст через AI и постит в Telegram.
Полностью автономный файл, не затрагивает существующие боты.
"""

import asyncio
import hashlib
import json
import logging
import os
import random
import re
import time
from io import BytesIO
from typing import Any

import requests
from telegram import Bot, InputMediaPhoto

from gist_storage import load_all_state, save_all_state

# ==================== НАСТРОЙКИ ====================
STEAM_API_KEY = os.environ.get("STEAM_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "@eroslabai")

# AI
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
AI_PROVIDER = os.environ.get("AI_PROVIDER", "auto").strip().lower()
AI_TIMEOUT_SEC = int(os.environ.get("AI_TIMEOUT_SEC", "20"))

# Настройки
MAX_DEAL_PRICE_USD = float(os.environ.get("MAX_DEAL_PRICE_USD", "15"))
MIN_DISCOUNT_PCT = int(os.environ.get("MIN_DISCOUNT_PCT", "40"))
DEALS_HISTORY_FILE = "steam_deals_history.json"

# NSFW-теги для фильтрации
NSFW_TAGS = {
    "nudity", "sexual content", "mature", "nsfw", "adult",
    "erotic", "sex", "nudity (suggestive)", "sexual violence",
    "nudity (sexual)", "adult content", "18+", "mature content",
    "sexual themes", "explicit", "hentai", "pornographic",
    "lewd", "suggestive", "uncensored", "18+ only",
}

# NSFW-слова для проверки названия и описания (когда теги пустые)
NSFW_TITLE_KEYWORDS = {
    "boob", "hentai", "eroge", "adult", "sex", "nude", "naked",
    "nsfw", "sexy", "seduce", "lewd", "succubus", "waifu",
    "love hotel", "strip", "stripper", "bikini", "lingerie",
    "bondage", "bdsm", "fetish", "mature", "erotic",
    "gal game", "dating sim", "sexual", "panty", "panties",
}

# Теги, которые гарантированно НЕ NSFW (исключаем)
SAFE_TAGS = {
    "family friendly", "kids", "children", "cartoon",
    "comedy", "fantasy", "violence", "gore",
}

# Технические мета-теги Steam (не влияют на NSFW-фильтрацию)
META_TAGS = {
    "single-player", "multi-player", "co-op", "online co-op",
    "lan co-op", "cross-platform", "steam achievements",
    "steam trading cards", "steam cloud", "stats",
    "partial controller support", "full controller support",
    "remote play", "shared/split screen", "captions available",
    "commentary available", "level editor", "vr support",
    "vr only", "tracked controller support", "controller support",
    "downloadable content", "demo", "soundtrack", "mods",
    "mod support", "mods (require htc vive)", "trackpad",
    "tracked motion controllers", "room-scale",
    "seated", "standing", "native", "empathy",
    "nudity (non-sexual)", "nudity (artistic)",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("ErosLab.SteamDeals")


# ==================== CHEAPSHARK API ====================
def fetch_cheapshark_deals(limit: int = 60) -> list[dict]:
    """
    Получает топ скидок из CheapShark.
    Берём 60 лучших сделок по абсолютной экономии без ограничения по цене —
    фильтрацию по цене и проценту делаем сами в process_deals().
    Это нужно потому что upperPrice отрезает дорогие игры с большой % скидкой,
    оставляя только дешёвые игры с маленькой реальной скидкой.
    """
    url = "https://www.cheapshark.com/api/1.0/deals"
    params = {
        "storeID": "1",       # Только Steam
        "pageSize": "60",     # Максимум
        "sortBy": "Savings",  # Сортировка по экономии в долларах
        "desc": "1",
        "onSale": "1",
    }

    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        deals = r.json()
        logger.info(f"CheapShark: got {len(deals)} deals")
        if deals and isinstance(deals, list) and len(deals) > 0:
            first = deals[0]
            logger.info(
                f"CheapShark sample: '{first.get('title')}', "
                f"savings={first.get('savings')} ({type(first.get('savings')).__name__}), "
                f"salePrice={first.get('salePrice')}, "
                f"normalPrice={first.get('normalPrice')}"
            )
        return deals if isinstance(deals, list) else []
    except Exception as e:
        logger.error(f"CheapShark error: {e}")
        return []


# ==================== STEAM API ====================
def _get_steam_app_details(app_id: int) -> dict | None:
    """Получает детали игры из Steam API."""
    url = "https://store.steampowered.com/api/appdetails"
    params = {"appids": app_id, "l": "russian"}
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        app_data = data.get(str(app_id), {})
        if app_data.get("success"):
            return app_data.get("data")
        return None
    except Exception as e:
        logger.warning(f"Steam API error for app {app_id}: {e}")
        return None


def _extract_steam_tags(app_data: dict) -> list[str]:
    """Извлекает теги/жанры из данных Steam API."""
    tags = set()

    # Жанры
    for genre in app_data.get("genres", []):
        desc = genre.get("description", "").lower()
        if desc:
            tags.add(desc)

    # Категории
    for cat in app_data.get("categories", []):
        desc = cat.get("description", "").lower()
        if desc:
            tags.add(desc)

    # Теги (Steam /api/appdetails обычно не возвращает user-теги,
    # но оставляем на случай если они появятся)
    for tag_data in app_data.get("tags", {}).values():
        if isinstance(tag_data, dict):
            name = tag_data.get("name", "").lower()
            if name:
                tags.add(name)

    return list(tags)


def _is_nsfw_game(title: str, app_data: dict) -> bool:
    """
    Проверяет, является ли игра NSFW.
    Порядок проверок: content_descriptors > required_age > теги > название > описание.

    Важно: Steam /api/appdetails НЕ возвращает пользовательские теги (Nudity, Sexual Content
    и т.д.) — они есть только на странице магазина. Поэтому главные сигналы — это
    официальные поля content_descriptors и required_age.
    """
    tags = _extract_steam_tags(app_data)

    # Проверка safe-тегов — если есть явно безопасный тег, пропускаем
    safe_matches = set(t.lower() for t in tags) & SAFE_TAGS
    if safe_matches:
        logger.debug(f"  Safe tags: {safe_matches}")
        return False

    # Проверка 1: content_descriptors (официальные NSFW-дескрипторы Steam)
    # ids: 1=Some Nudity or Sexual Content, 5=General Mature Content и т.д.
    descriptors = app_data.get("content_descriptors", {})
    descriptor_ids = descriptors.get("ids", [])
    descriptor_notes = str(descriptors.get("notes", "")).lower()
    if descriptor_ids:
        logger.info(f"  NSFW: content_descriptor ids={descriptor_ids}")
        return True
    if any(kw in descriptor_notes for kw in ["sexual", "nudity", "mature", "adult"]):
        logger.info("  NSFW: content_descriptor notes contain keywords")
        return True

    # Проверка 2: возрастное ограничение 18+
    required_age = int(app_data.get("required_age", 0) or 0)
    if required_age >= 18:
        logger.info(f"  NSFW: required_age={required_age}")
        return True

    # Проверка 3: NSFW-теги из Steam API (обычно пусто, но на всякий случай)
    nsfw_matches = set(t.lower() for t in tags) & NSFW_TAGS
    if nsfw_matches:
        logger.info(f"  NSFW tags found: {nsfw_matches}")
        return True

    # Проверка 4: NSFW-слова в названии игры
    title_lower = title.lower()
    for kw in NSFW_TITLE_KEYWORDS:
        if kw in title_lower:
            logger.info(f"  NSFW keyword in title: '{kw}'")
            return True

    # Проверка 5: NSFW-слова в описании игры
    desc = _get_steam_description(app_data).lower()
    for kw in NSFW_TITLE_KEYWORDS:
        if kw in desc:
            logger.info(f"  NSFW keyword in description: '{kw}'")
            return True

    return False


def _get_steam_screenshots(app_data: dict, max_count: int = 4) -> list[str]:
    """Возвращает URL скриншотов игры."""
    screenshots = app_data.get("screenshots", [])
    urls = [s.get("path_full", "") for s in screenshots[:max_count] if s.get("path_full")]
    return urls


def _get_steam_description(app_data: dict) -> str:
    """Извлекает короткое описание игры."""
    desc = app_data.get("short_description", "") or ""
    desc = re.sub(r'<[^>]+>', '', desc)
    desc = re.sub(r'\s+', ' ', desc).strip()
    return desc[:500]


# ==================== AI ====================
def _generate_ai_post(game_info: dict) -> str | None:
    """
    Генерирует хайповый текст поста через AI.
    Использует Groq или OpenRouter в зависимости от настроек.
    """
    title = game_info["title"]
    discount = game_info["discount"]
    old_price = game_info["old_price"]
    new_price = game_info["new_price"]
    description = game_info["description"]
    tags = ", ".join(game_info["tags"][:8])

    if "openrouter" in AI_PROVIDER or AI_PROVIDER == "auto":
        api_key = OPENROUTER_API_KEY or GROQ_API_KEY
        base_url = "https://openrouter.ai/api/v1/chat/completions" if OPENROUTER_API_KEY else "https://api.groq.com/openai/v1/chat/completions"
        model = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini") if OPENROUTER_API_KEY else os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    else:
        api_key = GROQ_API_KEY
        base_url = "https://api.groq.com/openai/v1/chat/completions"
        model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

    if not api_key:
        return _generate_fallback_text(game_info)

    system_prompt = (
        "Ты — дерзкий админ Telegram-канала про NSFW игры. "
        "Пиши коротко, сочно, с юмором. Используй эмодзи обильно. "
        "Начинай с кликбейтного заголовка вроде '❗❗ Здесь можно...'. "
        "Обязательно укажи скидку и цену. "
        "Закончи призывом к действию (ссылка на Steam, 'Добавляй в вишку!'). "
        "Максимум 500 символов. Пиши на русском языке."
    )

    user_prompt = (
        f"Игра: {title}\n"
        f"Скидка: {discount}%\n"
        f"Цена: {old_price} → {new_price}\n"
        f"Описание: {description[:400]}\n"
        f"Теги: {tags}\n\n"
        f"Напиши хайповый пост для канала."
    )

    try:
        r = requests.post(
            base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 300,
                "temperature": 0.9,
            },
            timeout=AI_TIMEOUT_SEC,
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
        logger.info(f"AI generated text ({len(text)} chars)")
        return text

    except Exception as e:
        logger.warning(f"AI generation error: {e}")
        return _generate_fallback_text(game_info)


def _generate_fallback_text(game_info: dict) -> str:
    """Генерирует текст поста без AI (шаблонный fallback)."""
    title = game_info["title"]
    discount = game_info["discount"]
    new_price = game_info["new_price"]
    old_price = game_info["old_price"]

    openings = [
        "❗❗ Скидка на то, что ты искал!",
        "🔥 Успей урвать!",
        "🎮 А вот и скидка на NSFW-хит!",
        "💥 Скидка дня!",
    ]

    closings = [
        "🔗 Добавляй в вишку и покупай!",
        "🎯 Отличная цена, не упусти!",
        "⚡ Предложение ограничено по времени!",
    ]

    text = (
        f"{random.choice(openings)}\n\n"
        f"<b>{title}</b>\n"
        f"💰 <b>-{discount}%</b> — {new_price} (было {old_price})\n\n"
        f"{random.choice(closings)}"
    )
    return text


# ==================== ПУБЛИКАЦИЯ ====================
async def send_deal_post(bot: Bot, game_info: dict) -> bool:
    """Отправляет пост с игрой в Telegram."""
    screenshots = game_info["screenshots"]
    caption = game_info["caption"]

    if screenshots:
        media = []
        for i, url in enumerate(screenshots[:4]):
            if i == 0:
                media.append(InputMediaPhoto(media=url, caption=caption, parse_mode="HTML"))
            else:
                media.append(InputMediaPhoto(media=url))

        try:
            await bot.send_media_group(
                chat_id=TELEGRAM_CHANNEL_ID,
                media=media,
                write_timeout=60,
                read_timeout=60,
            )
            logger.info(f"Posted media group: {game_info['title']} ({len(screenshots)} screenshots)")
            return True
        except Exception as e:
            logger.error(f"Media group error: {e}")
            # Fallback: отправляем только текст
            try:
                await bot.send_message(
                    chat_id=TELEGRAM_CHANNEL_ID,
                    text=caption,
                    parse_mode="HTML",
                    disable_web_page_preview=False,
                )
                logger.info(f"Posted text-only: {game_info['title']}")
                return True
            except Exception as e2:
                logger.error(f"Text fallback error: {e2}")
                return False
    else:
        try:
            await bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=caption,
                parse_mode="HTML",
                disable_web_page_preview=False,
            )
            logger.info(f"Posted text-only (no screenshots): {game_info['title']}")
            return True
        except Exception as e:
            logger.error(f"Send error: {e}")
            return False


# ==================== ХРАНИЛИЩЕ ====================
def load_deals_history() -> set:
    """Загружает историю опубликованных игр."""
    state = load_all_state()
    history = state.get(DEALS_HISTORY_FILE, [])
    return set(history)


def save_deals_history(history: set):
    """Сохраняет историю опубликованных игр."""
    state = load_all_state()
    state[DEALS_HISTORY_FILE] = list(history)[-500:]  # Храним последние 500
    save_all_state(state)


# ==================== ОСНОВНАЯ ФУНКЦИЯ ====================
def process_deals() -> dict | None:
    """
    Основная логика: найти NSFW-скидку, подготовить пост.
    Возвращает game_info или None.
    """
    posted_ids = load_deals_history()
    logger.info(f"Loaded {len(posted_ids)} posted deals from history")

    # Шаг 1: Получаем 60 лучших сделок без фильтра по цене.
    # upperPrice убран намеренно: он отрезал дорогие игры с большой % скидкой,
    # оставляя только дешёвые игры с крошечной реальной скидкой (~1%).
    deals = fetch_cheapshark_deals(limit=60)
    if not deals:
        logger.warning("No deals from CheapShark")
        return None

    logger.info(f"CheapShark returned {len(deals)} deals total")

    # Шаг 2: Фильтруем по цене и проценту скидки.
    # Процент считаем сами из salePrice/normalPrice — поле savings ненадёжно
    # (это экономия в долларах, а не процент).
    filtered = []
    for d in deals:
        try:
            sale_p = float(d.get("salePrice", 0) or 0)
            norm_p = float(d.get("normalPrice", 0) or 0)

            # Ценовой фильтр — берём только игры до MAX_DEAL_PRICE_USD
            if sale_p > MAX_DEAL_PRICE_USD:
                continue

            # Считаем процент скидки из реальных цен
            if norm_p > 0 and sale_p < norm_p:
                pct = round((norm_p - sale_p) / norm_p * 100)
            else:
                pct = 0

            d["_savings_pct"] = pct

            if pct >= MIN_DISCOUNT_PCT:
                filtered.append(d)

        except (TypeError, ValueError):
            continue

    logger.info(
        f"After price+discount filter (<=${MAX_DEAL_PRICE_USD}, >={MIN_DISCOUNT_PCT}%): "
        f"{len(filtered)} deals"
    )

    if not filtered:
        logger.warning("No suitable deals after filtering")
        return None

    # Сортируем по проценту скидки (лучшие первые)
    filtered.sort(key=lambda d: d["_savings_pct"], reverse=True)

    # Шаг 3: Проверяем каждую игру на NSFW через Steam API
    for deal in filtered:
        steam_app_id = deal.get("steamAppID")
        if not steam_app_id:
            continue

        game_id = f"steam_{steam_app_id}"
        if game_id in posted_ids:
            logger.debug(f"Already posted: {game_id}")
            continue

        title = deal.get("title", "Unknown")
        discount = deal["_savings_pct"]
        sale_price = float(deal.get("salePrice", 0))
        normal_price = float(deal.get("normalPrice", 0))
        store_link = f"https://store.steampowered.com/app/{steam_app_id}"

        logger.info(f"Checking: {title} (-{discount}%, ${sale_price})")

        # Шаг 4: Получаем детали из Steam API
        app_data = _get_steam_app_details(int(steam_app_id))
        if not app_data:
            logger.debug(f"  No Steam data for {title}")
            continue

        # Шаг 5: Проверяем NSFW
        if not _is_nsfw_game(title, app_data):
            logger.debug(f"  Not NSFW: {title}")
            continue

        logger.info(f"  ✅ NSFW game found: {title}")

        # Шаг 6: Собираем данные для поста
        screenshots = _get_steam_screenshots(app_data)
        description = _get_steam_description(app_data)
        tags = _extract_steam_tags(app_data)
        nsfw_tags = [t for t in tags if t.lower() in NSFW_TAGS]

        game_info = {
            "id": game_id,
            "title": title,
            "discount": discount,
            "old_price": f"${normal_price:.2f}",
            "new_price": f"${sale_price:.2f}",
            "description": description,
            "tags": nsfw_tags[:10],
            "screenshots": screenshots,
            "store_url": store_link,
        }

        # Шаг 7: Генерируем текст через AI
        caption = _generate_ai_post(game_info)
        game_info["caption"] = caption

        # Хэш для защиты от дубликатов
        content_hash = hashlib.sha256(
            f"{title}_{discount}_{sale_price}".encode()
        ).hexdigest()
        game_info["hash"] = content_hash

        return game_info

    logger.warning("No suitable NSFW deals found")
    return None


# ==================== MAIN ====================
async def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("No TELEGRAM_BOT_TOKEN found!")
        return

    if not STEAM_API_KEY:
        logger.error("No STEAM_API_KEY found! Get one at https://steamcommunity.com/dev/apikey")
        return

    logger.info("=" * 50)
    logger.info("Starting ErosLab Steam Deals Bot")
    logger.info(f"Channel: {TELEGRAM_CHANNEL_ID}")
    logger.info(f"Max price: ${MAX_DEAL_PRICE_USD}, Min discount: {MIN_DISCOUNT_PCT}%")
    logger.info("=" * 50)

    game_info = process_deals()
    if not game_info:
        logger.info("No NSFW deals found this run")
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    success = await send_deal_post(bot, game_info)

    if success:
        history = load_deals_history()
        history.add(game_info["id"])
        save_deals_history(history)
        logger.info(f"✅ Posted deal: {game_info['title']}")
    else:
        logger.error(f"❌ Failed to post deal: {game_info['title']}")


if __name__ == "__main__":
    asyncio.run(main())