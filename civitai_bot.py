"""
ErosLab Bot — CivitAI (только X и XXX рейтинг)
Оптимизирован для GitHub Actions с защитой от повторов.
"""

import os
import random
import hashlib
import re
from PIL import Image
import telegram
import asyncio
import time
from datetime import datetime

from bot_base import BaseBot, logger, send_with_retry, _fit_photo_size_for_telegram, check_media_size, get_video_duration, get_video_dimensions, get_min_bitrate_kbps_for_height, validate_video, normalize_video_format, get_video_thumbnail, weighted_choice, _is_video, _is_gif, _is_video_item, _is_photo_item, normalize_video_aspect_ratio, BLACKLIST_TAGS
from caption_generator import generate_caption
from rule34_api import fetch_rule34
from watermark import add_watermark, add_watermark_to_video, should_add_watermark


# ==================== БОТ ====================
class CivitaiBot(BaseBot):
    BOT_NAME = "civitai"
    
    TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "@eroslabai")
    ADMIN_USER_ID = str(os.environ.get("ADMIN_USER_ID", "")).strip()
    
    MIN_LIKES        = 10
    MIN_IMAGE_SIZE   = 720
    IMAGE_PACK_SIZE = max(1, int(os.environ.get("IMAGE_PACK_SIZE", "3")))
    IMAGE_PACK_CANDIDATE_POOL = max(IMAGE_PACK_SIZE, int(os.environ.get("IMAGE_PACK_CANDIDATE_POOL", "18")))
    
    WATERMARK_ENABLED = True

    # Дополнительные настройки специфичные только для этого бота
    BOT_MODE = os.environ.get("BOT_MODE", "nsfw").lower()
    REVIEW_MODE = os.environ.get("REVIEW_MODE", "false").lower() in ("1", "true", "yes", "on")
    CIVITAI_API_KEY     = os.environ.get("CIVITAI_API_KEY", "")

    WATERMARK_TEXT   = "📣 @eroslabai"
    WATERMARK_IMAGE_TEXT = os.environ.get("WATERMARK_IMAGE_TEXT", "@eroslabai")
    WATERMARK_IMAGE_OPACITY = float(os.environ.get("WATERMARK_IMAGE_OPACITY", "0.3"))
    MIN_CIVITAI_LIKES = int(os.environ.get("MIN_CIVITAI_LIKES", "1"))
    ALLOW_MATURE_FALLBACK = os.environ.get("ALLOW_MATURE_FALLBACK", "false").lower() in ("1", "true", "yes", "on")
    ENABLE_VIDEO_QOS = os.environ.get("ENABLE_VIDEO_QOS", "true").lower() in ("1", "true", "yes", "on")
    MIN_BITRATE_480P  = int(os.environ.get("MIN_BITRATE_480P", "900"))
    MIN_BITRATE_720P  = int(os.environ.get("MIN_BITRATE_720P", "1400"))
    MIN_BITRATE_1080P = int(os.environ.get("MIN_BITRATE_1080P", "2200"))
    IMAGE_PACK_ENABLED = os.environ.get("IMAGE_PACK_ENABLED", "true").lower() in ("1", "true", "yes", "on")
    IMAGE_PACK_SPLIT_POSTS = os.environ.get("IMAGE_PACK_SPLIT_POSTS", "false").lower() in ("1", "true", "yes", "on")
    TEST_CIVITAI_ONLY = False

    # Расширенный блэклист специфичный для этого бота
    BLACKLIST_TAGS = BLACKLIST_TAGS | {
        "gay", "yaoi", "bara", "2boys", "3boys", "multiple_boys",
        "male_only", "male_male", "gay_male", "bl", "boy_love",
        "1boy", "solo_male", "male_focus", "male_pov",
        "handsome_muscular_man", "muscular_man", "handsome_man",
        "old_man", "young_man", "dilf", "twink", "femboy",
        "furry_male", "anthro",
    }

    # Паттерны только для явного male-only фокуса
    MALE_ONLY_PATTERNS = (
        r"(^|_)solo_male(_|$)", r"(^|_)male_only(_|$)", r"(^|_)male_focus(_|$)",
        r"(^|_)male_pov(_|$)", r"(^|_)1boy(_|$)", r"(^|_)\d+boy(s)?(_|$)",
        r"(^|_)2boys(_|$)", r"(^|_)3boys(_|$)", r"(^|_)multiple_boys(_|$)",
        r"(^|_)male_male(_|$)", r"(^|_)all_male(_|$)", r"(^|_)male_group(_|$)",
        r"(^|_)gay_male(_|$)", r"(^|_)boy_love(_|$)",
    )


    def __init__(self):
        super().__init__()
        self.content_state.setdefault("last_type", "3d")
        self.content_state.setdefault("last_media", "video")
        self.pending_draft = self._state.get(f"pending_draft_{self.BOT_NAME}.json", {})
        self.review_state = self._state.get(f"review_state_{self.BOT_NAME}.json", {"last_update_id": 0})


    # Методы бота переопределяющие поведение базы
    def get_next_content_type(self):
        """Чередует между 3d и ai контентом"""
        next_type = "ai" if self.content_state["last_type"] == "3d" else "3d"
        self.content_state["last_type"] = next_type
        return next_type

    def get_next_media_type(self):
        """Строгое распределение: 70% video, 30% image."""
        return "video" if random.random() < 0.7 else "image"

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


    def _normalize_tag(self, tag: str) -> str:
        return str(tag).strip().lower().replace(" ", "_").replace("-", "_")

    def _has_male_only_pattern(self, tag: str) -> bool:
        for pattern in self.MALE_ONLY_PATTERNS:
            if re.search(pattern, tag):
                return True
        return False

    def has_blacklisted(self, tags):
        normalized_tags = [self._normalize_tag(t) for t in tags]
        blacklisted = set(normalized_tags) & self.BLACKLIST_TAGS

        if not blacklisted:
            for tag in normalized_tags:
                if self._has_male_only_pattern(tag):
                    blacklisted.add(tag)

        if blacklisted:
            logger.debug(f"Blacklisted: {blacklisted}")
            return True
        return False


    async def save_state(self):
        self._state[f"pending_draft_{self.BOT_NAME}.json"] = self.pending_draft
        self._state[f"review_state_{self.BOT_NAME}.json"] = self.review_state
        await super().save_state()


    async def run(self):
        """Главный цикл бота"""
        run_started = time.time()
        run_metrics = {
            "runs": 1,
            "posted": 0,
            "source_civitai_selected": 0,
            "source_rule34_selected": 0,
            "skip_no_item": 0,
            "skip_download_error": 0,
            "skip_file_too_large": 0,
            "skip_small_image": 0,
            "skip_bad_video_duration": 0,
            "skip_low_video_quality": 0,
            "skip_duplicate_hash": 0,
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
            logger.error("No TELEGRAM_BOT_TOKEN found!")
            flush_stats_once()
            return

        if not self.CIVITAI_API_KEY:
            logger.error("No CIVITAI_API_KEY found!")
            flush_stats_once()
            return

        logger.info("=" * 50)
        logger.info("Starting ErosLab Bot")
        logger.info(f"Channel: {self.TELEGRAM_CHANNEL_ID}")
        logger.info(f"Min likes: {self.MIN_LIKES}")
        logger.info(f"Min image size: {self.MIN_IMAGE_SIZE}x{self.MIN_IMAGE_SIZE}")
        logger.info(
            "Video QoS: "
            f"enabled={self.ENABLE_VIDEO_QOS}, "
            f"min_bitrate_480p={self.MIN_BITRATE_480P}, "
            f"min_bitrate_720p={self.MIN_BITRATE_720P}, "
            f"min_bitrate_1080p={self.MIN_BITRATE_1080P}"
        )
        logger.info("=" * 50)

        # Основная логика бота здесь
        flush_stats_once()
        await self.save_state()


async def main():
    bot = CivitaiBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())