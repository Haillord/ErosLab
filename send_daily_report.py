import asyncio
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Bot

STATS_FILE = "stats.json"
REPORT_CHAT = (
    os.environ.get("TELEGRAM_REPORT_CHAT")
    or os.environ.get("ADMIN_USER_ID")
    or "@Haillord"
)
STATS_TZ = os.environ.get("STATS_TZ", "Europe/Moscow")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")


def load_stats():
    if not os.path.exists(STATS_FILE):
        return {"daily": {}, "report": {}}
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {"daily": {}, "report": {}}
            data.setdefault("daily", {})
            data.setdefault("report", {})
            return data
    except Exception:
        return {"daily": {}, "report": {}}


def save_stats(data):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_report_date():
    try:
        now_local = datetime.now(ZoneInfo(STATS_TZ))
    except Exception:
        now_local = datetime.utcnow()
    return (now_local.date() - timedelta(days=1)).isoformat()


def fmt_int(metrics, key):
    return int(metrics.get(key, 0))


def render_report(date_key, metrics):
    runs = fmt_int(metrics, "runs")
    posted = fmt_int(metrics, "posted")
    civitai = fmt_int(metrics, "source_civitai_selected")
    rule34 = fmt_int(metrics, "source_rule34_selected")
    skip_no_item = fmt_int(metrics, "skip_no_item")
    skip_download = fmt_int(metrics, "skip_download_error")
    skip_large = fmt_int(metrics, "skip_file_too_large")
    skip_small = fmt_int(metrics, "skip_small_image")
    skip_duration = fmt_int(metrics, "skip_bad_video_duration")
    skip_qos = fmt_int(metrics, "skip_low_video_quality")
    skip_dup = fmt_int(metrics, "skip_duplicate_hash")
    send_errors = fmt_int(metrics, "send_errors")
    runtime_sec = float(metrics.get("runtime_sec", 0))
    avg_runtime = (runtime_sec / runs) if runs > 0 else 0

    return (
        f"📊 <b>Daily Bot Report</b>\n"
        f"🗓️ {date_key} ({STATS_TZ})\n\n"
        f"Runs: <b>{runs}</b>\n"
        f"Posted: <b>{posted}</b>\n"
        f"Sources: CivitAI={civitai}, Rule34={rule34}\n\n"
        f"Skips:\n"
        f"- No item: {skip_no_item}\n"
        f"- Download errors: {skip_download}\n"
        f"- Too large: {skip_large}\n"
        f"- Small image: {skip_small}\n"
        f"- Bad duration: {skip_duration}\n"
        f"- Low video QoS: {skip_qos}\n"
        f"- Duplicate hash: {skip_dup}\n"
        f"- Send errors: {send_errors}\n\n"
        f"Avg runtime: {avg_runtime:.1f}s"
    )


async def main():
    if not BOT_TOKEN:
        print("No TELEGRAM_BOT_TOKEN found; skip report send.")
        return

    stats = load_stats()
    report_date = get_report_date()

    last_sent = stats.get("report", {}).get("last_sent_date")
    if last_sent == report_date:
        print(f"Report for {report_date} already sent.")
        return

    metrics = stats.get("daily", {}).get(report_date)
    if not metrics:
        print(f"No daily metrics for {report_date}; skip report.")
        return

    bot = Bot(token=BOT_TOKEN)
    message = render_report(report_date, metrics)
    await bot.send_message(chat_id=REPORT_CHAT, text=message, parse_mode="HTML")
    print(f"Daily report sent to {REPORT_CHAT} for {report_date}.")

    stats.setdefault("report", {})
    stats["report"]["last_sent_date"] = report_date
    save_stats(stats)


if __name__ == "__main__":
    asyncio.run(main())
