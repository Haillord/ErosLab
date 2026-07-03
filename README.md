<p align="center">
  <img src="angel_gothic_FOR_GITHUB.webp" width="100%" alt="ErosLab Gothic Angel">
</p>

<p align="center">
<img src="https://readme-typing-svg.demolab.com?font=Share+Tech+Mono&size=22&pause=2000&color=FF2244&center=true&vCenter=true&width=700&height=45&duration=40&lines=ErosLab+Bot+Ecosystem+%F0%9F%94%9E;Serverless+24%2F7+on+GitHub+Actions;3+sources+%E2%80%A2+smart+fallback;AI+captions+via+Groq+%26+Vision;Smart+filtering+%26+no+duplicates;Free+hosting+%E2%80%A2+Full+autonomy">
</p>

<p align="center">
  <img src="https://img.shields.io/github/license/Haillord/eroslab-bot?style=for-the-badge&label=LICENSE&color=FF2244&labelColor=1a1a1a" alt="license">
  <img src="https://img.shields.io/github/stars/Haillord/eroslab-bot?style=for-the-badge&label=STARS&color=FF2244&labelColor=1a1a1a" alt="stars">
  <img src="https://img.shields.io/github/actions/workflow/status/Haillord/eroslab-bot/bot.yml?style=for-the-badge&label=BOT+STATUS&labelColor=1a1a1a&color=FF2244" alt="workflow">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/Haillord/eroslab-bot/main/banner.svg" width="100%" alt="ErosLab Bot Ecosystem">
</p>

<div align="center">

[![](https://img.shields.io/badge/🔞_Основной_канал-FF2244?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/+P3yEVmH-EK82NDky)
[![](https://img.shields.io/badge/🤍_Обои-white?style=for-the-badge&logo=telegram&logoColor=black)](https://t.me/eroslaab)

</div>

<br>

<details>
<summary><b>🇷🇺 Русская версия</b></summary>
<br>

<div align="center" style="background: linear-gradient(135deg, rgba(255,34,68,0.08) 0%, rgba(26,26,26,0.95) 100%); border: 1px solid #333; border-radius: 14px; padding: 22px 28px; margin: 10px 0;">

**ErosLab** — полностью автономная система постинга контента в Telegram.

Работает **24/7 бесплатно** на GitHub Actions. Никакого сервера. Никаких затрат.

Контент отбирается, фильтруется, подписывается и публикуется **автоматически**.

</div>

<br>

<table>
<tr>
<td width="50%" valign="top">

### ⚙️ Инфраструктура
- **Serverless** — GitHub Actions, 0 руб/месяц
- **Gist как БД** — состояние без коммитов в репо
- **3 источника** — CivitAI, Rule34 API, Rule34Gen
- **Fallback-цепочка** — если источник упал, берёт следующий по весу
</td>
<td width="50%" valign="top">

### 🧠 Интеллект
- **AI подписи** — Groq + OpenRouter + Vision
- **AI CTA** — призывы к действию на основе контента
- **Дедупликация** — SHA256 хеш каждого файла
- **QoS фильтр** — минимальный битрейт для 480p/720p/1080p
- **Блэклист** — автофильтрация нежелательных тегов

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 🎨 Медиа
- **Ватермарки** — на фото и видео через PIL + FFmpeg
- **Image Pack** — автосборка альбомов из 3 фото
- **Видео нормализация** — yuv420p, h264, max 1080p
- **Aspect ratio fix** — скип экстремальных соотношений сторон
- **Playwright** — для рендеринга страниц (Rule34Gen)

</td>
<td width="50%" valign="top">

### 🛡️ Безопасность
- **История 5000** — защита от повторов
- **Content filter** — NSFW только нужного типа
- **Размерный фильтр** — мин. 720px по обеим сторонам
- **Review mode** — опциональная модерация перед постом

</td>
</tr>
</table>

<br>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/GitHub_Actions-2088FF?style=for-the-badge&logo=github-actions&logoColor=white"/>
  <img src="https://img.shields.io/badge/Gist_API-181717?style=for-the-badge&logo=github&logoColor=white"/>
  <br>
  <img src="https://img.shields.io/badge/CivitAI-FF2244?style=for-the-badge&logoColor=white"/>
  <img src="https://img.shields.io/badge/Rule34-FF6600?style=for-the-badge&logoColor=white"/>
  <br>
  <img src="https://img.shields.io/badge/Groq-00A67E?style=for-the-badge&logoColor=white"/>
  <img src="https://img.shields.io/badge/FFmpeg-007808?style=for-the-badge&logo=ffmpeg&logoColor=white"/>
  <img src="https://img.shields.io/badge/Pillow-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/python--telegram--bot-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white"/>
  <br>
  <img src="https://img.shields.io/badge/Playwright-45ba4b?style=for-the-badge&logo=playwright&logoColor=white"/>
</p>

<br>

<details>
<summary><b>📂 Показать структуру проекта</b></summary>
<br>

```
ErosLab/
│
├── 🔴  eroslab_bot.py           — основной движок (NSFW)
├── 🤍  wallpapers_bot.py        — бот обоев (SFW, Wallhaven)
│
├── ⚙️  gist_storage.py          — хранилище состояния в Gist
├── 🧠  caption_generator.py     — AI генератор подписей
├── 🖼️  watermark.py             — водяные знаки (фото + видео)
│
├── 🔎  rule34_api.py            — парсер Rule34 (API)
├── 🔎  rule34gen_api.py         — парсер Rule34Gen (через Playwright)
├── 🔎  civitai_api.py           — парсер CivitAI
│
├── 🛠️  utils_state.py           — статистика и состояние
├── 🛠️  utils_tags.py            — обработка тегов
└── 🛠️  utils_telegram_media.py  — отправка медиа в Telegram
```

</details>

<details>
<summary><b>⚙️ Настройка — GitHub Secrets</b></summary>
<br>

`Settings` → `Secrets and variables` → `Actions`

**NSFW-бот (eroslab_bot.yml):**

| Secret | Описание | |
|--------|----------|-|
| `TELEGRAM_BOT_TOKEN` | Токен основного бота | ✅ |
| `TELEGRAM_CHANNEL_ID` | ID или @username NSFW-канала | ✅ |
| `ADMIN_USER_ID` | ID админа для ревью-режима | ⚡ опц. |
| `GH_TOKEN` | Classic Token с правами на Gist | ✅ |
| `GIST_ID` | ID секретного Gist | ✅ |
| `CIVITAI_API_KEY` | Доступ к API CivitAI | ✅ |
| `R34_USER_ID` / `R34_API_KEY` | Авторизация Rule34 | ✅ |
| `R34V_PHPSESSID` / `R34V_KT_ACCTOKEN` | Авторизация Rule34Video | ⚡ опц. |
| `RULE34_MIN_SCORE` | Мин. рейтинг для постов Rule34 (def: 10) | ⚡ опц. |
| `SOURCE_WEIGHTS` | JSON весов: `{"civitai":35,"rule34":25}` | ⚡ опц. |
| `GROQ_API_KEY` | AI генерация подписей (Groq) | ⚡ опц. |
| `OPENROUTER_API_KEY` | Vision модели для подписей | ⚡ опц. |
| `GROQ_MODEL` | Модель Groq (def: `llama-3.3-70b-versatile`) | ⚡ опц. |
| `OPENROUTER_MODEL` | Модель OpenRouter (def: `openai/gpt-4o-mini`) | ⚡ опц. |
| `AI_PROVIDER` | Провайдер AI: `auto`, `groq`, `openrouter` | ⚡ опц. |
| `AI_TIMEOUT_SEC` | Таймаут AI (def: 12) | ⚡ опц. |
| `ENABLE_AI_CAPTION` | Включить AI подписи (`true`/`false`) | ⚡ опц. |
| `ENABLE_AI_CTA` | Включить CTA-блок (`true`/`false`) | ⚡ опц. |
| `AI_DRY_RUN` | Режим просмотра без отправки | ⚡ опц. |
| `ENABLE_STYLE_BLOCK` | Блок стилей в подписи | ⚡ опц. |
| `STYLE_BLOCK_MAX_ITEMS` | Макс. элементов стиля (def: 3) | ⚡ опц. |
| `CAPTION_STYLE` | Стиль: `minimal`, `default`, `detailed` | ⚡ опц. |
| `REVIEW_MODE` | Модерация перед постом (`true`/`false`) | ⚡ опц. |
| `ALLOW_MATURE_FALLBACK` | Fallback на mature контент | ⚡ опц. |
| `ENABLE_VIDEO_QOS` | QoS для видео (`true`/`false`) | ⚡ опц. |
| `MIN_BITRATE_480P` | Мин. битрейт для 480p (def: 900) | ⚡ опц. |
| `MIN_BITRATE_720P` | Мин. битрейт для 720p (def: 1400) | ⚡ опц. |
| `MIN_BITRATE_1080P` | Мин. битрейт для 1080p (def: 2200) | ⚡ опц. |
| `STATS_TZ` | Часовой пояс статистики (def: `Europe/Moscow`) | ⚡ опц. |

**Wallpapers-бот:**

| Secret | Описание | |
|--------|----------|-|
| `TELEGRAM_BOT_TOKEN_WALLPAPERS` | Токен wallpapers-бота | ✅ |
| `TELEGRAM_CHANNEL_ID_WALLPAPERS` | ID или @username SFW-канала | ✅ |
| `WALLHAVEN_API_KEY` | Доступ к Wallhaven | ✅ |

</details>

</details>

<details>
<summary><b>🇬🇧 English version</b></summary>
<br>

<div align="center" style="background: linear-gradient(135deg, rgba(255,34,68,0.08) 0%, rgba(26,26,26,0.95) 100%); border: 1px solid #333; border-radius: 14px; padding: 22px 28px; margin: 10px 0;">

**ErosLab** — a fully autonomous Telegram content posting system.

Runs **24/7 for free** on GitHub Actions. No server. No costs.

Content is selected, filtered, captioned and published **automatically**.

</div>

<br>

<table>
<tr>
<td width="50%" valign="top">

### ⚙️ Infrastructure
- **Serverless** — GitHub Actions, $0/month
- **Gist as DB** — state without repo commits
- **3 sources** — CivitAI, Rule34 API, Rule34Gen
- **Fallback chain** — if a source fails, picks next by weight
</td>
<td width="50%" valign="top">

### 🧠 Intelligence
- **AI captions** — Groq + OpenRouter + Vision
- **AI CTA** — content-based call-to-action generation
- **Deduplication** — SHA256 hash of each file
- **QoS filter** — minimum bitrate for 480p/720p/1080p
- **Blacklist** — auto-filtering of unwanted tags

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 🎨 Media
- **Watermarks** — on photos & video via PIL + FFmpeg
- **Image Pack** — auto-albums from 3 photos
- **Video normalization** — yuv420p, h264, max 1080p
- **Aspect ratio fix** — skip extreme aspect ratios
- **Playwright** — headless browser for page rendering

</td>
<td width="50%" valign="top">

### 🛡️ Safety
- **History of 5000** — duplicate protection
- **Content filter** — NSFW only of required type
- **Size filter** — min. 720px on both sides
- **Review mode** — optional moderation before posting

</td>
</tr>
</table>

<br>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/GitHub_Actions-2088FF?style=for-the-badge&logo=github-actions&logoColor=white"/>
  <img src="https://img.shields.io/badge/Gist_API-181717?style=for-the-badge&logo=github&logoColor=white"/>
  <br>
  <img src="https://img.shields.io/badge/CivitAI-FF2244?style=for-the-badge&logoColor=white"/>
  <img src="https://img.shields.io/badge/Rule34-FF6600?style=for-the-badge&logoColor=white"/>
  <br>
  <img src="https://img.shields.io/badge/Groq-00A67E?style=for-the-badge&logoColor=white"/>
  <img src="https://img.shields.io/badge/FFmpeg-007808?style=for-the-badge&logo=ffmpeg&logoColor=white"/>
  <img src="https://img.shields.io/badge/Pillow-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/python--telegram--bot-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white"/>
  <br>
  <img src="https://img.shields.io/badge/Playwright-45ba4b?style=for-the-badge&logo=playwright&logoColor=white"/>
</p>

<br>

<details>
<summary><b>📂 Show project structure</b></summary>
<br>

```
ErosLab/
│
├── 🔴  eroslab_bot.py           — main engine (NSFW)
├── 🤍  wallpapers_bot.py        — wallpapers bot (SFW, Wallhaven)
│
├── ⚙️  gist_storage.py          — state storage in Gist
├── 🧠  caption_generator.py     — AI caption generator
├── 🖼️  watermark.py             — watermarks (photo + video)
│
├── 🔎  rule34_api.py            — Rule34 API parser
├── 🔎  rule34gen_api.py         — Rule34Gen parser (Playwright)
├── 🔎  civitai_api.py           — CivitAI parser
│
├── 🛠️  utils_state.py           — statistics & state
├── 🛠️  utils_tags.py            — tag processing
└── 🛠️  utils_telegram_media.py  — sending media to Telegram
```

</details>

<details>
<summary><b>⚙️ Setup — GitHub Secrets</b></summary>
<br>

`Settings` → `Secrets and variables` → `Actions`

**NSFW bot (eroslab_bot.yml):**

| Secret | Description | |
|--------|-------------|-|
| `TELEGRAM_BOT_TOKEN` | Main bot token | ✅ |
| `TELEGRAM_CHANNEL_ID` | ID or @username of NSFW channel | ✅ |
| `ADMIN_USER_ID` | Admin ID for review mode | ⚡ opt. |
| `GH_TOKEN` | Classic Token with Gist permissions | ✅ |
| `GIST_ID` | Secret Gist ID | ✅ |
| `CIVITAI_API_KEY` | CivitAI API access | ✅ |
| `R34_USER_ID` / `R34_API_KEY` | Rule34 authorization | ✅ |
| `R34V_PHPSESSID` / `R34V_KT_ACCTOKEN` | Rule34Video auth | ⚡ opt. |
| `RULE34_MIN_SCORE` | Min score for Rule34 posts (def: 10) | ⚡ opt. |
| `SOURCE_WEIGHTS` | JSON weights: `{"civitai":35,"rule34":25}` | ⚡ opt. |
| `GROQ_API_KEY` | AI caption generation (Groq) | ⚡ opt. |
| `OPENROUTER_API_KEY` | Vision models for captions | ⚡ opt. |
| `GROQ_MODEL` | Groq model (def: `llama-3.3-70b-versatile`) | ⚡ opt. |
| `OPENROUTER_MODEL` | OpenRouter model (def: `openai/gpt-4o-mini`) | ⚡ opt. |
| `AI_PROVIDER` | AI provider: `auto`, `groq`, `openrouter` | ⚡ opt. |
| `AI_TIMEOUT_SEC` | AI timeout (def: 12) | ⚡ opt. |
| `ENABLE_AI_CAPTION` | Enable AI captions (`true`/`false`) | ⚡ opt. |
| `ENABLE_AI_CTA` | Enable CTA block (`true`/`false`) | ⚡ opt. |
| `AI_DRY_RUN` | Preview mode without sending | ⚡ opt. |
| `ENABLE_STYLE_BLOCK` | Style block in caption | ⚡ opt. |
| `STYLE_BLOCK_MAX_ITEMS` | Max style items (def: 3) | ⚡ opt. |
| `CAPTION_STYLE` | Style: `minimal`, `default`, `detailed` | ⚡ opt. |
| `REVIEW_MODE` | Moderation before posting (`true`/`false`) | ⚡ opt. |
| `ALLOW_MATURE_FALLBACK` | Allow mature fallback content | ⚡ opt. |
| `ENABLE_VIDEO_QOS` | Video QoS (`true`/`false`) | ⚡ opt. |
| `MIN_BITRATE_480P` | Min bitrate for 480p (def: 900) | ⚡ opt. |
| `MIN_BITRATE_720P` | Min bitrate for 720p (def: 1400) | ⚡ opt. |
| `MIN_BITRATE_1080P` | Min bitrate for 1080p (def: 2200) | ⚡ opt. |
| `STATS_TZ` | Stats timezone (def: `Europe/Moscow`) | ⚡ opt. |

**Wallpapers bot:**

| Secret | Description | |
|--------|-------------|-|
| `TELEGRAM_BOT_TOKEN_WALLPAPERS` | Wallpapers bot token | ✅ |
| `TELEGRAM_CHANNEL_ID_WALLPAPERS` | ID or @username of SFW channel | ✅ |
| `WALLHAVEN_API_KEY` | Wallhaven access | ✅ |

</details>

</details>

<br>

---

<p align="center">
  <img src="https://img.shields.io/badge/Made%20with-Python-3776AB?style=for-the-badge&logo=python" alt="python">
  <img src="https://img.shields.io/badge/Powered%20by-GitHub%20Actions-2088FF?style=for-the-badge&logo=github-actions" alt="actions">
  <img src="https://img.shields.io/badge/Developer-Haillord-FF2244?style=for-the-badge&logo=telegram" alt="author">
</p>