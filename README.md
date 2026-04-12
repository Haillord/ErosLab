<p align="center">
  <img src="angel_gothic_FOR_GITHUB.webp" width="100%" alt="ErosLab Gothic Angel">
</p>

<p align="center">
<img src="https://readme-typing-svg.demolab.com?font=Share+Tech+Mono&size=22&pause=2000&color=FF2244&center=true&vCenter=true&width=700&height=45&duration=40&lines=ErosLab+Bot+Ecosystem+%F0%9F%94%9E;Serverless+24%2F7+on+GitHub+Actions;AI+via+Groq+%26+Llama+3;Smart+filtering+%26+no+duplicates;Free+hosting+%E2%80%A2+Full+autonomy">
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

<div align="center">

[![](https://img.shields.io/badge/🔞_Основной_канал-FF2244?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/eroslabai)
[![](https://img.shields.io/badge/🤍_Обои-white?style=for-the-badge&logo=telegram&logoColor=black)](https://t.me/eroslabwallpaper)

</div>

<br>


**ErosLab** — полностью автономная система постинга контента в Telegram.  
Работает **24/7 бесплатно** на GitHub Actions. Никакого сервера. Никаких затрат.  
Контент отбирается, фильтруется, подписывается и публикуется **без участия человека**.

<br>


<table>
<tr>
<td width="50%" valign="top">

### ⚙️ Инфраструктура
- **Serverless** — GitHub Actions, 0 руб/месяц
- **Gist как БД** — состояние без коммитов
- **Dual-source** — CivitAI + Rule34 в ротации
- **Fallback** — если один источник упал, берёт другой

</td>
<td width="50%" valign="top">

### 🧠 Интеллект
- **AI подписи** — Groq + OpenRouter + Vision
- **Дедупликация** — SHA256 хеш каждого файла
- **QoS фильтр** — минимальный битрейт для видео
- **Блэклист** — автофильтрация нежелательных тегов

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 🎨 Медиа
- **Вотермарки** — на фото и видео через PIL + FFmpeg
- **Image Pack** — автосборка альбомов из 3 фото
- **Видео нормализация** — yuv420p, h264, max 1080p
- **Aspect ratio fix** — паддинги для Telegram

</td>
<td width="50%" valign="top">

### 🛡️ Безопасность
- **Review Mode** — одобрение постов через бота
- **История 5000** — защита от повторов
- **Content filter** — NSFW только нужного типа
- **Размерный фильтр** — мин. 720px по обеим сторонам

</td>
</tr>
</table>

<br>


```mermaid
flowchart TD
    A[⏰ GitHub Actions Cron] -->|каждые 15 мин| B[🎲 Ротация 50/50]
    B --> C[🔥 CivitAI]
    B --> D[🟧 Rule34]
    C & D --> E[🔍 Фильтрация<br/><small>теги / хеш / размер / QoS</small>]
    E --> F[🧠 AI Подпись<br/><small>Groq / OpenRouter</small>]
    F --> G[🖼️ Вотермарк<br/><small>PIL + FFmpeg</small>]
    G --> H[📢 Telegram<br/><small>фото / видео / gif</small>]
    H --> I[💾 Gist Storage<br/><small>история постов</small>]
    
    style A fill:#2088FF,color:white,stroke:none
    style B fill:#1a1a1a,color:white,stroke:none
    style C fill:#FF2244,color:white,stroke:none
    style D fill:#FF6600,color:white,stroke:none
    style E fill:#1a1a1a,color:white,stroke:none
    style F fill:#00A67E,color:white,stroke:none
    style G fill:#007808,color:white,stroke:none
    style H fill:#2CA5E0,color:white,stroke:none
    style I fill:#181717,color:white,stroke:none

    linkStyle default stroke:#555,stroke-width:2px
```

<br>


<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/GitHub_Actions-2088FF?style=for-the-badge&logo=github-actions&logoColor=white"/>
  <img src="https://img.shields.io/badge/Gist_API-181717?style=for-the-badge&logo=github&logoColor=white"/>
  <br>
  <img src="https://img.shields.io/badge/CivitAI-FF2244?style=for-the-badge&logoColor=white"/>
  <img src="https://img.shields.io/badge/Rule34-FF6600?style=for-the-badge&logoColor=white"/>
  <img src="https://img.shields.io/badge/Groq-00A67E?style=for-the-badge&logoColor=white"/>
  <img src="https://img.shields.io/badge/OpenRouter-FF6B35?style=for-the-badge&logoColor=white"/>
  <br>
  <img src="https://img.shields.io/badge/FFmpeg-007808?style=for-the-badge&logo=ffmpeg&logoColor=white"/>
  <img src="https://img.shields.io/badge/Pillow-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/python--telegram--bot-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white"/>
</p>

<br>


<details>
<summary><b>📂 Показать структуру проекта</b></summary>
<br>

```
eroslab-bot/
│
├── 🔴  civitai_bot.py       — основной движок (nsfw)
├── 🤍  wallpapers_bot.py    — бот с обоями (sfw)
│
├── ⚙️  gist_storage.py      — БД через GitHub Gist
├── 🧠  caption_generator.py — AI генератор подписей
├── 🔎  rule34_api.py        — парсер Rule34
└── 🖼️  watermark.py         — обработка фото и видео
```

</details>

<br>


 `Settings` → `Secrets and variables` → `Actions`

| Secret | Описание | Обязательно |
|--------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | 🤖 Токен основного бота | ✅ |
| `TELEGRAM_CHANNEL_ID` | 📢 ID или @username канала | ✅ |
| `GH_TOKEN` | 🔐 Classic Token с правами на Gist | ✅ |
| `GIST_ID` | 🗄️ ID секретного Gist | ✅ |
| `CIVITAI_API_KEY` | 🎨 Доступ к API CivitAI | ✅ |
| `GROQ_API_KEY` | 🧠 AI генерация подписей | ⚡ опц. |
| `OPENROUTER_API_KEY` | 👁️ Vision модели | ⚡ опц. |
| `ADMIN_USER_ID` | 🛡️ ID для Review Mode | ⚡ опц. |

<br>


<p align="center">
  <img src="https://img.shields.io/badge/Made%20with-Python-3776AB?style=for-the-badge&logo=python" alt="python">
  <img src="https://img.shields.io/badge/Powered%20by-GitHub%20Actions-2088FF?style=for-the-badge&logo=github-actions" alt="actions">
  <img src="https://img.shields.io/badge/Developer-Haillord-FF2244?style=for-the-badge&logo=telegram" alt="author">
</p>
