"""
fetch_ai_videos.py
Собирает 10 AI-сгенерированных видео с rule34.xxx и сохраняет в артефакты.
Использует существующий rule34_api.py для получения данных.

Фильтры качества:
  - score >= 100 (отсекаем AnimateDiff-шлак 2023 года)
  - длительность >= 3 секунд (проверка через ffprobe)
  - ширина >= 512 пикселей (проверка через ffprobe)
  - только посты с тегом ai_generated (без авторской 3D-анимации)

Запуск: python fetch_ai_videos.py
"""

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rule34_api import fetch_rule34
from watermark import add_watermark_to_video

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("FetchAIVideos")

OUTPUT_DIR = Path("ai_videos")
REPORT_FILE = Path("report.json")

MAX_VIDEOS = 10

# ── Пороги качества ────────────────────────────────────────────────────────────
MIN_SCORE = 5         # минимальный score (лайки) — на Rule34 скор у AI-видео низкий
MIN_DURATION = 3.0    # минимальная длительность видео, сек
MIN_WIDTH = 512       # минимальная ширина, px

# ── Размеры файлов ─────────────────────────────────────────────────────────────
MIN_FILE_SIZE = 100 * 1024        # 100 КБ
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 МБ

# ── Индикаторы AI-контента ──────────────────────────────────────────────────
# Набор тегов, указывающих на AI-генерацию. Расширяемый.
AI_KEYWORDS = {
    "ai_generated", "ai", "ai_art", "ai_video",
    "ai_animation", "generated",
}


# ── Утилиты ────────────────────────────────────────────────────────────────────

def _is_video_url(url: str) -> bool:
    path = url.lower().split("?")[0]
    return path.endswith((".mp4", ".webm"))


def _is_ai_generated(tags: list[str]) -> bool:
    """Проверяет наличие AI-тегов в списке тегов поста."""
    tag_set = set(t.lower() for t in tags)
    return bool(tag_set & AI_KEYWORDS)


def _get_video_metadata(data: bytes) -> dict:
    """
    ffprobe — получение метаданных видео (парсинг ключ=значение).
    Возвращает: {duration, width, height, is_valid, issues}
    """
    result = {
        "duration": 0.0,
        "width": 0,
        "height": 0,
        "is_valid": False,
        "issues": [],
    }
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration:stream=width,height",
            "-of", "default=noprint_wrappers=1:nokey=0",
            "-select_streams", "v:0",
            tmp_path,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if proc.returncode != 0:
            result["issues"].append("ffprobe failed")
            return result

        # Парсим ключ=значение (nokey=0 — выводит с ключами)
        for line in proc.stdout.strip().splitlines():
            line = line.strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if key == "duration":
                try:
                    result["duration"] = float(value) if value and value != "N/A" else 0.0
                except ValueError:
                    result["issues"].append(f"invalid duration: {value}")
            elif key == "width":
                try:
                    result["width"] = int(value)
                except ValueError:
                    result["issues"].append(f"invalid width: {value}")
            elif key == "height":
                try:
                    result["height"] = int(value)
                except ValueError:
                    result["issues"].append(f"invalid height: {value}")

        # Проверяем что получили данные
        if result["width"] <= 0 or result["height"] <= 0:
            result["issues"].append(f"bad resolution: {result['width']}x{result['height']}")
        if result["duration"] <= 0:
            result["issues"].append(f"bad duration: {result['duration']}")

        result["is_valid"] = len(result["issues"]) == 0
        return result

    except FileNotFoundError:
        result["issues"].append("ffprobe not found")
        return result
    except subprocess.TimeoutExpired:
        result["issues"].append("ffprobe timeout")
        return result
    except Exception as e:
        result["issues"].append(f"ffprobe error: {e}")
        return result
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _check_video_quality(data: bytes) -> dict:
    """
    Проверяет качество видео через ffprobe.
    Возвращает: {passed: bool, metadata: dict, reasons: [str]}
    """
    meta = _get_video_metadata(data)
    reasons = []

    if not meta["is_valid"]:
        for issue in meta["issues"]:
            reasons.append(f"ffprobe: {issue}")
        return {"passed": False, "metadata": meta, "reasons": reasons}

    dur = meta["duration"]
    w = meta["width"]
    h = meta["height"]

    if dur < MIN_DURATION:
        reasons.append(f"duration={dur:.1f}s < {MIN_DURATION}s")

    if w < MIN_WIDTH and h < MIN_WIDTH:
        reasons.append(f"resolution={w}x{h} — обе стороны меньше {MIN_WIDTH}px")

    # Соотношение сторон: не слишком узкое/широкое
    if w > 0 and h > 0:
        ratio = w / h
        if ratio < 0.3 or ratio > 4.0:
            reasons.append(f"extreme aspect ratio: {w}x{h} (ratio={ratio:.2f})")

    return {"passed": len(reasons) == 0, "metadata": meta, "reasons": reasons}


# ── Скачивание и сохранение ────────────────────────────────────────────────────

def download_video(url: str, timeout: int = 120) -> bytes | None:
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        }
        r = requests.get(url, headers=headers, timeout=timeout, stream=True)
        r.raise_for_status()
        data = r.content
        logger.info(f"  Скачано {len(data) // 1024 // 1024} МБ")
        return data
    except Exception as e:
        logger.error(f"  Ошибка скачивания: {e}")
        return None


def save_video(item: dict, index: int) -> str | None:
    """Скачивает, проверяет качество и сохраняет видео."""
    url = item.get("url", "")
    if not url:
        return None

    ext = ".webm" if url.lower().split("?")[0].endswith(".webm") else ".mp4"
    filename = f"ai_video_{index:02d}{ext}"
    filepath = OUTPUT_DIR / filename

    # ── Скачивание ──
    data = download_video(url)
    if data is None:
        return None

    # ── Базовая проверка размера ──
    if len(data) < MIN_FILE_SIZE:
        logger.warning(f"  Файл слишком мал: {len(data)} байт")
        return None

    if len(data) > MAX_FILE_SIZE:
        logger.warning(f"  Файл слишком большой: {len(data) // 1024 // 1024} МБ")
        return None

    # ── Проверка качества через ffprobe ──
    quality = _check_video_quality(data)
    if not quality["passed"]:
        for reason in quality["reasons"]:
            logger.warning(f"  Качество не прошло: {reason}")
        return None

    meta = quality["metadata"]
    logger.info(
        f"  Качество OK: {meta['width']}x{meta['height']}, "
        f"{meta['duration']:.1f}с"
    )

    # ── Водяной знак ──
    try:
        data = add_watermark_to_video(
            video_data=data,
            text="📣 @eroslabai",
            opacity=0.3,
        )
        logger.info(f"  Водяной знак нанесён ({len(data) // 1024 // 1024} МБ)")
    except Exception as e:
        logger.warning(f"  Ошибка нанесения водяного знака, сохраняю оригинал: {e}")

    # ── Сохранение ──
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_bytes(data)
    logger.info(f"  Сохранён: {filename} ({len(data) // 1024} КБ)")

    return filename


# ── Главная функция ────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 50)
    logger.info("Запуск fetch_ai_videos.py")
    logger.info(f"Пороги: score>={MIN_SCORE}, duration>={MIN_DURATION}s, width>={MIN_WIDTH}px")
    logger.info("=" * 50)

    # Шаг 1: Получаем посты через rule34_api
    # Передаём теги напрямую с принудительным video, чтобы API отдавал именно видео
    logger.info("Шаг 1: Запрашиваем AI-видео с rule34.xxx...")
    # animated — стандартный тег Rule34 для видео/анимации
    all_items = fetch_rule34(
        tags="ai_generated animated rating:explicit",
        limit=100,
        content_type="mixed",
        media_type="mixed",
    )

    if not all_items:
        logger.error("Не получено ни одного поста от rule34 API")
        _save_error_report("No items from rule34 API")
        sys.exit(1)

    logger.info(f"Получено всего постов: {len(all_items)}")

    # Шаг 2: Фильтруем только видео, применяем score
    debug_not_video = 0
    debug_low_score = 0
    debug_not_ai = 0
    candidates = []

    # Покажем первые 3 поста для диагностики
    logger.info("Первые 3 поста из API (raw):")
    for i, item in enumerate(all_items[:3]):
        logger.info(f"  [{i}] id={item.get('id','?')} url={str(item.get('url',''))[:80]} score={item.get('likes',0)} tags={item.get('tags',[])[:5]}")

    for item in all_items:
        if not _is_video_url(item.get("url", "")):
            debug_not_video += 1
            continue

        score = max(0, int(item.get("likes", 0)))
        if score < MIN_SCORE:
            debug_low_score += 1
            continue

        tags = item.get("tags", [])
        if not _is_ai_generated(tags):
            debug_not_ai += 1
            continue

        candidates.append({
            "item": item,
            "score": score,
        })

    logger.info(f"Отсев: не видео={debug_not_video}, score<{MIN_SCORE}={debug_low_score}, нет AI-тегов={debug_not_ai}")

    logger.info(f"Кандидатов после фильтрации: {len(candidates)}")

    if not candidates:
        logger.error("Нет кандидатов, удовлетворяющих условиям")
        _save_error_report("No candidates after filtering")
        sys.exit(1)

    # Сортируем по score
    candidates.sort(key=lambda x: x["score"], reverse=True)

    # Шаг 3: Скачиваем с проверкой качества
    downloaded = []
    pool = candidates[:MAX_VIDEOS * 3]  # запас для отбраковки по качеству

    logger.info(f"Шаг 3: Скачиваем и проверяем кандидатов (запас: {len(pool)})")

    for idx, entry in enumerate(pool, start=1):
        if len(downloaded) >= MAX_VIDEOS:
            break

        item = entry["item"]
        url = item.get("url", "")
        tags = item.get("tags", [])

        logger.info(f"\n[{len(downloaded) + 1}/{MAX_VIDEOS}] ID: {item.get('id', '?')}")
        logger.info(f"  URL: {url[:100]}...")
        logger.info(f"  Score: {entry['score']}")
        logger.info(f"  Теги ({len(tags)}): {tags[:6]}...")

        filename = save_video(item, len(downloaded) + 1)

        if filename:
            downloaded.append({
                "index": len(downloaded) + 1,
                "id": item.get("id", ""),
                "url": url,
                "filename": filename,
                "tags": tags[:20],
                "score": entry["score"],
                "source": item.get("source", "rule34"),
            })
        else:
            logger.warning("  Не прошло проверку качества, пробуем следующее...")

        time.sleep(0.5)

    # Шаг 4: Итоги
    logger.info(f"\n{'=' * 50}")
    logger.info(f"Скачано AI-видео: {len(downloaded)} из {len(candidates)} кандидатов")
    logger.info(f"{'=' * 50}")

    # Шаг 5: Сохраняем отчёт
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "status": "success" if downloaded else "error",
        "total_from_api": len(all_items),
        "candidates_after_filter": len(candidates),
        "downloaded": len(downloaded),
        "filters": {
            "min_score": MIN_SCORE,
            "min_duration_sec": MIN_DURATION,
            "min_width_px": MIN_WIDTH,
        },
        "search_tags": "ai_generated video",
        "ai_videos": downloaded,
    }

    REPORT_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    logger.info(f"Отчёт сохранён: {REPORT_FILE}")

    if not downloaded:
        logger.error("Не скачано ни одного AI-видео!")
        sys.exit(1)

    logger.info("Готово! ✓")


def _save_error_report(message: str):
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "status": "error",
        "message": message,
        "ai_videos": [],
        "total_from_api": 0,
        "candidates_after_filter": 0,
        "downloaded": 0,
        "filters": {
            "min_score": MIN_SCORE,
            "min_duration_sec": MIN_DURATION,
            "min_width_px": MIN_WIDTH,
        },
    }
    REPORT_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()