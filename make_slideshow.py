"""
Делает вертикальное слайдшоу 9:16 из последних обоев.
Берёт URL-ы из Gist, скачивает обои, склеивает через ffmpeg.

Запуск: python make_slideshow.py
Результат: slideshow.mp4
"""

import json
import os
import requests
import subprocess
import tempfile
from pathlib import Path
from PIL import Image
from io import BytesIO

# ==================== НАСТРОЙКИ ====================
OUTPUT_FILE = "slideshow.mp4"
COUNT = 3             # сколько обоев взять
DURATION_PER_IMAGE = 7  # секунд на каждый обой
TRANSITION_DURATION = 0.5  # секунд на переход
WIDTH = 1080
HEIGHT = 1080
FPS = 30

GIST_TOKEN = os.environ.get("GH_TOKEN", "")
GIST_ID = os.environ.get("GIST_ID", "")

HEADERS = {
    "Authorization": f"token {GIST_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}


def load_gist_state():
    if not GIST_TOKEN or not GIST_ID:
        print("⚠️  GH_TOKEN или GIST_ID не найдены, используем локальный файл")
        path = Path("posted_ids_wallpapers.json")
        if path.exists():
            with open(path, "r") as f:
                return json.load(f)
        return []

    resp = requests.get(
        f"https://api.github.com/gists/{GIST_ID}",
        headers=HEADERS,
        timeout=10
    )
    resp.raise_for_status()
    data = resp.json()

    # Ищем файл с историей обоев
    for filename in ["posted_ids_wallpapers.json", "content_state_wallpapers.json"]:
        if filename in data["files"]:
            content = data["files"][filename]["content"]
            return json.loads(content)

    return []


def get_wallhaven_urls(ids: list, count: int) -> list:
    """Берёт последние N wallhaven ID и получает прямые URL картинок."""
    wallhaven_ids = [
        i.replace("wallhaven_", "")
        for i in reversed(ids)
        if i.startswith("wallhaven_")
    ][:count]

    urls = []
    api_key = os.environ.get("WALLHAVEN_API_KEY", "")

    for wh_id in wallhaven_ids:
        try:
            params = {"apikey": api_key} if api_key else {}
            r = requests.get(
                f"https://wallhaven.cc/api/v1/w/{wh_id}",
                params=params,
                timeout=10
            )
            r.raise_for_status()
            path = r.json()["data"]["path"]
            urls.append({"id": wh_id, "url": path})
            print(f"  ✅ {wh_id}: {path}")
        except Exception as e:
            print(f"  ⚠️  {wh_id}: {e}")

    return urls


def download_and_prepare(url_info: dict, out_path: str) -> bool:
    """Скачивает обой и подготавливает под 9:16 с чёрными полосами."""
    try:
        r = requests.get(url_info["url"], timeout=30)
        r.raise_for_status()

        img = Image.open(BytesIO(r.content)).convert("RGB")
        w, h = img.size

        # Ресайз с сохранением пропорций под 1080x1920
        scale = min(WIDTH / w, HEIGHT / h)
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # Центрируем на чёрном фоне 1080x1920
        canvas = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
        x = (WIDTH - new_w) // 2
        y = (HEIGHT - new_h) // 2
        canvas.paste(img, (x, y))
        canvas.save(out_path, "JPEG", quality=95)

        print(f"  📐 {url_info['id']}: {w}x{h} → {new_w}x{new_h} на {WIDTH}x{HEIGHT}")
        return True

    except Exception as e:
        print(f"  ❌ Ошибка скачивания {url_info['id']}: {e}")
        return False


def make_slideshow(image_paths: list, output: str):
    """Склеивает изображения в видео с fade-переходами через ffmpeg."""

    # Строим filter_complex для fade между слайдами
    n = len(image_paths)
    total_duration = DURATION_PER_IMAGE * n

    # Создаём concat из отдельных видео-сегментов с фейдом
    inputs = []
    filter_parts = []
    last_label = None

    for i, path in enumerate(image_paths):
        inputs += ["-loop", "1", "-t", str(DURATION_PER_IMAGE + TRANSITION_DURATION), "-i", path]

    # filter_complex: каждое изображение → видеопоток, потом xfade между ними
    streams = [f"[{i}:v]" for i in range(n)]
    scale_parts = []
    for i in range(n):
        scale_parts.append(
            f"[{i}:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS}[v{i}]"
        )

    # Цепочка xfade
    xfade_parts = []
    current = "v0"
    for i in range(1, n):
        offset = DURATION_PER_IMAGE * i - TRANSITION_DURATION * (i - 1)
        next_label = f"xf{i}" if i < n - 1 else "out"
        xfade_parts.append(
            f"[{current}][v{i}]xfade=transition=fade:duration={TRANSITION_DURATION}:offset={offset:.2f}[{next_label}]"
        )
        current = next_label

    filter_complex = ";".join(scale_parts + xfade_parts)

    cmd = []
    for i, path in enumerate(image_paths):
        cmd += ["-loop", "1", "-t", str(DURATION_PER_IMAGE + TRANSITION_DURATION * 2), "-i", path]

    cmd = [
        "ffmpeg", "-y",
        *cmd,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:v", "libx264",
        "-crf", "18",
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-t", str(DURATION_PER_IMAGE * n),
        output
    ]

    print(f"\n🎬 Склеиваем {n} обоев...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"❌ ffmpeg ошибка:\n{result.stderr[-1000:]}")
        return False

    print(f"✅ Готово: {output}")
    return True


def main():
    print("📥 Загружаем историю из Gist...")
    posted_ids = load_gist_state()

    if not posted_ids:
        print("❌ История пустая — сначала запусти бота чтобы набрать обои")
        return

    print(f"  Найдено {len(posted_ids)} записей в истории")

    print(f"\n🔍 Получаем URL последних {COUNT} обоев с Wallhaven...")
    urls = get_wallhaven_urls(posted_ids, COUNT)

    if not urls:
        print("❌ Не удалось получить URL обоев")
        return

    print(f"\n⬇️  Скачиваем {len(urls)} обоев...")
    tmp_dir = tempfile.mkdtemp()
    image_paths = []

    for i, url_info in enumerate(urls):
        out_path = os.path.join(tmp_dir, f"slide_{i:02d}.jpg")
        if download_and_prepare(url_info, out_path):
            image_paths.append(out_path)

    if len(image_paths) < 2:
        print(f"❌ Скачалось только {len(image_paths)} обоев, нужно минимум 2")
        return

    print(f"\n✅ Скачано {len(image_paths)} обоев")
    make_slideshow(image_paths, OUTPUT_FILE)

    # Чистим временные файлы
    for p in image_paths:
        try:
            os.unlink(p)
        except Exception:
            pass

    size_mb = os.path.getsize(OUTPUT_FILE) / 1024 / 1024
    print(f"\n🎉 Видео готово: {OUTPUT_FILE} ({size_mb:.1f} MB)")
    print(f"   Разрешение: {WIDTH}x{HEIGHT} (9:16)")
    print(f"   Длительность: ~{DURATION_PER_IMAGE * len(image_paths)}с")
    print(f"   Накладывай музыку и заливай в TikTok/Shorts/Reels 🚀")


if __name__ == "__main__":
    main()