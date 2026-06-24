"""
Тестовый скрипт для проверки steam_workshop.py
"""

import os
import logging
from steam_workshop import fetch_steam_workshop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

if __name__ == "__main__":
    # Проверяем наличие API ключа
    api_key = os.environ.get("STEAM_API_KEY")
    if not api_key:
        print("❌ STEAM_API_KEY не установлен в переменных окружения")
        print("Получить ключ можно здесь: https://steamcommunity.com/dev/apikey")
        print("\nУстановить ключ можно так:")
        print("  Windows (PowerShell): $env:STEAM_API_KEY='ваш_ключ'")
        print("  Windows (CMD): set STEAM_API_KEY=ваш_ключ")
        print("  Linux/Mac: export STEAM_API_KEY='ваш_ключ'")
    else:
        print(f"✅ STEAM_API_KEY найден (первые 8 символов: {api_key[:8]}...)")
    
    print("\n🔍 Запрашиваем популярные обои из Steam Workshop Wallpaper Engine...")
    
    try:
        items = fetch_steam_workshop(max_pages=2)
        
        if items:
            print(f"\n✅ Успешно получено {len(items)} обоев")
            print("\n📋 Первые 3 результата:")
            for i, item in enumerate(items[:3], 1):
                print(f"\n{i}. {item.get('title', 'Без названия')}")
                print(f"   ID: {item['id']}")
                print(f"   Подписчиков: {item['likes']}")
                print(f"   MIME: {item['mime']}")
                print(f"   URL: {item['url'][:80]}...")
                print(f"   Теги: {', '.join(item['tags'][:5])}")
        else:
            print("\n❌ Не удалось получить обои")
            print("Возможные причины:")
            print("  - Неверный API ключ")
            print("  - Превышен лимит запросов")
            print("  - Нет подходящих обоев (NSFW фильтр)")
    except Exception as e:
        print(f"\n❌ Ошибка при выполнении: {e}")
        import traceback
        traceback.print_exc()
