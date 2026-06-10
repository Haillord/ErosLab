"""
SFM Bot — лёгкая обёртка над ErosLab Bot.
Парсит только SFM/3D sexy контент с CivitAI (browsingLevel: 3)
и отправляет в отдельный Telegram канал.
"""

import os

# ==================== НАСТРОЙКИ SFM РЕЖИМА ====================
os.environ["BOT_MODE"] = "sfm"  # Маркер для основного бота

# Источники: только CivitAI
os.environ["ENABLE_RULE34GEN"] = "false"
os.environ["SOURCE_WEIGHTS"] = '{"civitai": 1}'

# Канал для SFM (токен общий — TELEGRAM_BOT_TOKEN)
sfm_channel = os.environ.get("TELEGRAM_CHANNEL_ID_SFM", "")
if sfm_channel:
    os.environ["TELEGRAM_CHANNEL_ID"] = sfm_channel

# CivitAI: browsingLevel 8 (R = sexy/mature, без X/XXX)
os.environ["CIVITAI_BROWSING_LEVEL"] = "8"
os.environ["MIN_CIVITAI_LIKES"] = "30"  # Меньше лайков для SFM контента

# Watermark
os.environ["WATERMARK_IMAGE_TEXT"] = "@eroslabai"
os.environ["WATERMARK_IMAGE_OPACITY"] = "0.25"

# Video QoS: отключён (SFM часто в высоком разрешении)
os.environ["ENABLE_VIDEO_QOS"] = "false"

# Male-only контент разрешён в SFM канале
os.environ["SFM_ALLOW_MALE_ONLY"] = "true"

# Image pack отключён для SFM (только одиночные посты)
os.environ["IMAGE_PACK_ENABLED"] = "false"


# ==================== ЗАПУСК ====================
from eroslab_bot import main as eroslab_main
import asyncio

if __name__ == "__main__":
    asyncio.run(eroslab_main())