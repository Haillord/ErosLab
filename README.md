<p align="center">
  <img src="angel_gothic_FOR_GITHUB.webp" width="100%" alt="ErosLab Gothic Angel">
</p>

<p align="center">
<img src="https://readme-typing-svg.demolab.com?font=Share+Tech+Mono&size=22&pause=2000&color=FF2244&center=true&vCenter=true&width=700&height=45&duration=40&lines=ErosLab+Bot+Ecosystem+%F0%9F%94%9E;Serverless+24%2F7+on+GitHub+Actions;4+sources+%E2%80%A2+smart+fallback;AI+captions+via+Groq+%26+Vision;Smart+filtering+%26+no+duplicates;Free+hosting+%E2%80%A2+Full+autonomy">
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

[![](https://img.shields.io/badge/🔞_Основной_канал-FF2244?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/eroslabai)
[![](https://img.shields.io/badge/🤍_Обои-white?style=for-the-badge&logo=telegram&logoColor=black)](https://t.me/eroslabwallpaper)

</div>

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
- **2 источника** — CivitAI, Rule34
- **Fallback-цепочка** — если источник упал, берёт следующий по весу

</td>
<td width="50%" valign="top">

### 🧠 Интеллект
- **AI подписи** — Groq + OpenRouter + Vision
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

</td>
<td width="50%" valign="top">

### 🛡️ Безопасность
- **История 5000** — защита от повторов
- **Content filter** — NSFW только нужного типа
- **Размерный фильтр** — мин. 720px по обеим сторонам

</td>
</tr>
</table>

<br>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
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
</p>

<br>

<details>
<summary><b>📂 Показать структуру проекта</b></summary>
<br>

```
ErosLab/
│
├── 🔴  civitai_bot.py          — основной движок (NSFW)
├── 🤍  wallpapers_bot.py       — бот обоев (SFW, Wallhaven)
│
├── ⚙️  gist_storage.py         — хранилище состояния в Gist
├── 🧠  caption_generator.py    — AI генератор подписей
├── 🖼️  watermark.py            — водяные знаки (фото + видео)
├── 🎬  make_slideshow.py       — сборка слайдшоу из обоев
│
├── 🔎  rule34_api.py           — парсер Rule34
│
├── 🛠️  utils_state.py          — статистика и состояние
├── 🛠️  utils_tags.py           — обработка тегов
└── 🛠️  utils_telegram_media.py — отправка медиа в Telegram
```

</details>

<details>
<summary><b>⚙️ Настройка — GitHub Secrets</b></summary>
<br>

`Settings` → `Secrets and variables` → `Actions`

**NSFW-бот:**

| Secret | Описание | |
|--------|----------|-|
| `TELEGRAM_BOT_TOKEN` | Токен основного бота | ✅ |
| `TELEGRAM_CHANNEL_ID` | ID или @username NSFW-канала | ✅ |
| `GH_TOKEN` | Classic Token с правами на Gist | ✅ |
| `GIST_ID` | ID секретного Gist | ✅ |
| `CIVITAI_API_KEY` | Доступ к API CivitAI | ✅ |
| `R34_USER_ID` / `R34_API_KEY` | Авторизация Rule34 | ✅ |
| `SOURCE_WEIGHTS` | JSON весов: `{"civitai":35,"rule34":25}` | ⚡ опц. |
| `GROQ_API_KEY` | AI генерация подписей | ⚡ опц. |
| `OPENROUTER_API_KEY` | Vision модели для подписей | ⚡ опц. |

**Wallpapers-бот:**

| Secret | Описание | |
|--------|----------|-|
| `TELEGRAM_BOT_TOKEN_WALLPAPERS` | Токен wallpapers-бота | ✅ |
| `TELEGRAM_CHANNEL_ID_WALLPAPERS` | ID или @username SFW-канала | ✅ |
| `WALLHAVEN_API_KEY` | Доступ к NSFW-контенту на Wallhaven | ✅ |

</details>


<br>

---

<p align="center">
  <img src="https://img.shields.io/badge/Made%20with-Python-3776AB?style=for-the-badge&logo=python" alt="python">
  <img src="https://img.shields.io/badge/Powered%20by-GitHub%20Actions-2088FF?style=for-the-badge&logo=github-actions" alt="actions">
  <img src="https://img.shields.io/badge/Developer-Haillord-FF2244?style=for-the-badge&logo=telegram" alt="author">
</p>