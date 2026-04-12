"""
ErosLab Wallpapers Bot — Только красивые безопасные обои
Работает полностью независимо от основного бота
"""

import os
import random
import re
from PIL import Image
import asyncio
import time
from datetime import datetime

from bot_base import BaseBot, logger, calculate_image_hash, validate_image_size, validate_aspect_ratio, clean_tags, send_with_retry, _fit_photo_size_for_telegram, check_media_size, get_video_duration, get_video_dimensions, get_min_bitrate_kbps_for_height, validate_video, normalize_video_format, get_video_thumbnail, weighted_choice, _is_video, _is_gif, _is_video_item, _is_photo_item, normalize_video_aspect_ratio, BLACKLIST_TAGS
from caption_generator import generate_wallpaper_caption
from watermark import should_add_watermark
from parser_99px import fetch_99px


# ==================== БОТ ОБОЕВ ====================
class WallpapersBot(BaseBot):
    BOT_NAME = "wallpapers"
    
    TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN_WALLPAPERS", "")
    TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID_WALLPAPERS", "")
    ADMIN_USER_ID = str(os.environ.get("ADMIN_USER_ID", "")).strip()
    CIVITAI_API_KEY     = os.environ.get("CIVITAI_API_KEY", "")
    WALLHAVEN_API_KEY   = os.environ.get("WALLHAVEN_API_KEY", "")
    
    MIN_LIKES        = 5
    MIN_IMAGE_SIZE   = 720
    MIN_ASPECT_RATIO_MIN = 0.5   # 9:16 вертикальные (телефон)
    MIN_ASPECT_RATIO_MAX = 2.0   # 16:9 горизонтальные (монитор)
    IMAGE_PACK_SIZE = 4
    IMAGE_PACK_CANDIDATE_POOL = 24
    
    WATERMARK_ENABLED = False

    ENABLE_CIVITAI = False  # ✅ Поставь False чтобы отключить CivitAI полностью
    ENABLE_99PX = False     # ✅ Поставь False чтобы отключить 99px полностью


    HASHTAG_STOP_WORDS = BaseBot.HASHTAG_STOP_WORDS | {
        "score", "source", "rating", "version", "step", "steps", "cfg", "seed",
        "sampler", "model", "lora", "vae", "clip", "unet", "fp16", "safetensors",
        "checkpoint", "embedding", "none", "null", "true", "false", "and", "the",
        "for", "with", "masterpiece", "best", "quality", "high", "ultra", "detail",
        "detailed", "8k", "4k", "hd", "resolution", "simple", "background",
        "generated_by_ai", "animated", "rating_explicit", "rating_questionable",
        "rating_safe", "rating_suggestive", "tagme",
    }


    def __init__(self):
        super().__init__()
        self.content_state.setdefault("last_type", "landscape")


    def get_preferred_orientation(self) -> str:
        """Возвращает предпочтительную ориентацию и переключает на следующую."""
        last_type = self.content_state.get("last_type", "landscape")
        preferred = "portrait" if last_type == "landscape" else "landscape"
        self.content_state["last_type"] = preferred
        logger.info(f"Orientation: last={last_type}, preferred={preferred}")
        return preferred


    def clean_tags(self, tags):
        clean, seen = [], set()
        for t in tags:
            t = re.sub(r"[^\w]", "", str(t).strip().lower().replace(" ", "_").replace("-", "_"))
            if re.search(r'\d+$', t):
                continue
            if t and t not in self.HASHTAG_STOP_WORDS and t not in seen and 3 <= len(t) <= 30:
                clean.append(t)
                seen.add(t)
        return clean


    async def run(self):
        run_started = time.time()
        run_metrics = {
            "runs": 1,
            "posted": 0,
            "skip_no_item": 0,
            "skip_download_error": 0,
            "skip_bad_image": 0,
            "send_errors": 0,
        }
        stats_flushed = False

        def flush_stats_once():
            nonlocal stats_flushed
            if stats_flushed:
                return
            run_metrics["runtime_sec"] = round(time.time() - run_started, 2)
            self.record_run_stats(run_metrics)
            stats_flushed = True

        if not self.TELEGRAM_BOT_TOKEN:
            logger.error("No TELEGRAM_BOT_TOKEN provided")
            flush_stats_once()
            return

        selected = await self.fetch_and_pick()

        if not selected:
            run_metrics["skip_no_item"] = 1
            logger.info("No suitable wallpaper found this run")
            flush_stats_once()
            await self.save_state()
            return

        success = await self.publish_item_to_channel(selected)

        if success:
            run_metrics["posted"] = 1
            logger.info(f"Successfully posted wallpaper {selected['id']}")
        else:
            run_metrics["send_errors"] = 1

        flush_stats_once()
        await self.save_state()


async def main():
    bot = WallpapersBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())