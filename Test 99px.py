"""
Быстрый тест парсера 99px.ru
Запуск: python test_99px.py
"""

import requests
from bs4 import BeautifulSoup
import re

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
}

def test():
    url = "https://wallpapers.99px.ru/new/"
    print(f"Fetching: {url}")

    r = requests.get(url, headers=HEADERS, timeout=15)
    print(f"Status: {r.status_code}")
    print(f"Content-Type: {r.headers.get('Content-Type')}")
    print(f"Response size: {len(r.content)} bytes")
    print()

    soup = BeautifulSoup(r.text, "html.parser")

    # Ищем все ссылки на обои
    wallpaper_links = []
    for link in soup.select("a[href*='/wallpapers/']"):
        href = link.get("href", "")
        if re.search(r"/wallpapers/\d+", href):
            img = link.find("img")
            if img:
                wallpaper_links.append({
                    "href": href,
                    "img_src": img.get("src") or img.get("data-src", ""),
                    "alt": img.get("alt", ""),
                })

    print(f"Found wallpaper links: {len(wallpaper_links)}")
    print()

    for i, item in enumerate(wallpaper_links[:5], 1):
        print(f"[{i}] href:    {item['href']}")
        print(f"     img_src: {item['img_src'][:80]}")
        print(f"     alt:     {item['alt']}")
        print()

    if wallpaper_links:
        print("--- Тест страницы конкретного обоя ---")
        test_page = wallpaper_links[0]["href"]
        if not test_page.startswith("http"):
            test_page = "https://wallpapers.99px.ru" + test_page
        print(f"Fetching: {test_page}")

        r2 = requests.get(test_page, headers=HEADERS, timeout=15)
        print(f"Status: {r2.status_code}")

        soup2 = BeautifulSoup(r2.text, "html.parser")

        # Все img теги
        imgs = soup2.find_all("img")
        print(f"Total img tags on page: {len(imgs)}")
        for img in imgs:
            src = img.get("src", "") or img.get("data-src", "")
            if src and not src.startswith("data:") and "99px" in src:
                print(f"  IMG: {src}")

        # Ссылки на скачивание
        downloads = soup2.select("a[href*='download']") + soup2.select("a.download_btn")
        print(f"Download links: {len(downloads)}")
        for d in downloads:
            print(f"  DL: {d.get('href', '')}")
    else:
        print("Ничего не нашли — скорее всего JS-рендеринг или другая структура HTML")
        print()
        print("--- Сырой HTML (первые 2000 символов) ---")
        print(r.text[:2000])

if __name__ == "__main__":
    test()