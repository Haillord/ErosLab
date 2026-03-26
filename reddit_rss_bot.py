"""
Reddit 3D Bot — парсит NSFW 3D-контент через RSS (без API)
"""

import asyncio
import hashlib
import json
import logging
import os
import random
import re
import requests
import feedparser
from io import BytesIO
from pathlib import Path
from telegram import Bot

# ==================== НАСТРОЙКИ ====================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "@eroslabai")

# Сабреддиты с 3D NSFW контентом
SUBREDDITS = [
    "3dnsfw",
    "blendernsfw", 
    "3dart",
    "sfmcompileclub",
    "3dhentai"
]

# Минимальный рейтинг (RSS не даёт лайки, будем использовать комментарии/активность)
# Пропускаем, будем брать первые посты

HISTORY_FILE = "reddit_rss_posted.json"
WATERMARK_TEXT = "@eroslabai"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

def load_posted():
    """Загружает историю опубликованных постов"""
    if Path(HISTORY_FILE).exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except:
            pass
    return set()

def save_posted(posted):
    """Сохраняет историю"""
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(list(posted), f, ensure_ascii=False, indent=2)

def is_media_url(url):
    """Проверяет, является ли URL медиафайлом"""
    media_extensions = (".jpg", ".jpeg", ".png", ".gif", ".mp4", ".webm", ".gifv")
    return url.lower().endswith(media_extensions)

def extract_image_url(entry):
    """Извлекает URL изображения/видео из поста"""
    # Пробуем взять из content
    if hasattr(entry, 'content') and entry.content:
        content = entry.content[0].value
        # Ищем img src
        img_match = re.search(r'<img src="([^"]+)"', content)
        if img_match:
            return img_match.group(1)
    
    # Пробуем взять из media_content
    if hasattr(entry, 'media_content') and entry.media_content:
        return entry.media_content[0]['url']
    
    # Пробуем взять из links
    if hasattr(entry, 'links'):
        for link in entry.links:
            if link.get('type', '').startswith('image/'):
                return link.get('href')
    
    return None

def fetch_reddit_rss():
    """Получает посты из RSS лент сабреддитов"""
    posted_ids = load_posted()
    all_posts = []
    
    for subreddit in SUBREDDITS:
        try:
            url = f"https://www.reddit.com/r/{subreddit}/.rss"
            logger.info(f"Fetching: {url}")
            
            feed = feedparser.parse(url)
            
            if feed.bozo:
                logger.warning(f"Parse warning for {subreddit}: {feed.bozo_exception}")
            
            posts_count = 0
            for entry in feed.entries[:10]:  # Берём первые 10
                post_id = entry.get('id', '').split('/')[-2] if entry.get('id') else None
                if not post_id:
                    post_id = hashlib.md5(entry.link.encode()).hexdigest()[:12]
                
                post_key = f"reddit_{subreddit}_{post_id}"
                
                if post_key in posted_ids:
                    continue
                
                # Получаем URL медиа
                media_url = extract_image_url(entry)
                
                # Если не нашли медиа, пробуем взять прямую ссылку
                if not media_url and entry.link:
                    # Reddit часто даёт прямые ссылки на i.redd.it
                    if 'i.redd.it' in entry.link or 'v.redd.it' in entry.link:
                        media_url = entry.link
                
                if not media_url or not is_media_url(media_url):
                    logger.debug(f"Skipping {post_key} - no media URL")
                    continue
                
                # Получаем примерное количество комментариев (замена лайкам)
                comments = 0
                if hasattr(entry, 'comments'):
                    comments = entry.comments
                
                all_posts.append({
                    "id": post_key,
                    "url": media_url,
                    "title": entry.title,
                    "subreddit": subreddit,
                    "comments": comments,
                    "link": entry.link
                })
                posts_count += 1
            
            logger.info(f"Found {posts_count} new posts from r/{subreddit}")
            
        except Exception as e:
            logger.error(f"Error fetching r/{subreddit}: {e}")
    
    return all_posts

async def main():
    """Основная функция"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("No TELEGRAM_BOT_TOKEN found!")
        return
    
    logger.info("=" * 50)
    logger.info("Starting Reddit 3D RSS Bot")
    logger.info(f"Channel: {TELEGRAM_CHANNEL_ID}")
    logger.info("=" * 50)
    
    posts = fetch_reddit_rss()
    
    if not posts:
        logger.info("No new posts found")
        return
    
    logger.info(f"Total fresh posts: {len(posts)}")
    
    # Выбираем случайный пост
    post = random.choice(posts)
    logger.info(f"Selected: {post['id']} from r/{post['subreddit']}")
    logger.info(f"Title: {post['title'][:80]}")
    
    # Скачиваем медиа
    try:
        logger.info(f"Downloading: {post['url']}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        r = requests.get(post["url"], timeout=60, headers=headers)
        r.raise_for_status()
        data = r.content
        logger.info(f"Downloaded {len(data)} bytes")
    except Exception as e:
        logger.error(f"Download error: {e}")
        return
    
    # Проверка на дубликат по хэшу
    img_hash = hashlib.md5(data).hexdigest()
    posted_ids = load_posted()
    
    # Формируем подпись
    caption = f"🎨 **{post['title']}**\n\n📌 r/{post['subreddit']} | 🔗 [Source]({post['link']})\n\n{WATERMARK_TEXT}"
    
    # Отправляем в Telegram
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    
    try:
        url_lower = post["url"].lower()
        if url_lower.endswith((".mp4", ".webm", ".gif")):
            logger.info("Sending as video")
            await bot.send_video(
                chat_id=TELEGRAM_CHANNEL_ID,
                video=BytesIO(data),
                caption=caption,
                supports_streaming=True,
                parse_mode='Markdown',
                write_timeout=60,
                read_timeout=60
            )
        else:
            logger.info("Sending as image")
            await bot.send_photo(
                chat_id=TELEGRAM_CHANNEL_ID,
                photo=BytesIO(data),
                caption=caption,
                parse_mode='Markdown',
                write_timeout=60,
                read_timeout=60
            )
        
        # Сохраняем историю
        posted_ids.add(post["id"])
        save_posted(posted_ids)
        logger.info(f"✅ Successfully posted: {post['id']}")
        
    except Exception as e:
        logger.error(f"Send error: {e}")

if __name__ == "__main__":
    asyncio.run(main())