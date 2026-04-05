<p align="center">
  <img src="logo.png?v=5" width="100%" alt="ErosLab Banner">
</p>

<p align="center">
  <img src="https://img.shields.io/github/license/Haillord/eroslab-bot?style=for-the-badge&color=red" alt="license">
  <img src="https://img.shields.io/github/stars/Haillord/eroslab-bot?style=for-the-badge&color=red" alt="stars">
  <img src="https://img.shields.io/github/actions/workflow/status/Haillord/eroslab-bot/bot.yml?style=for-the-badge&label=Bot%20Status" alt="workflow">
</p>

<h1 align="center">ErosLab Bot Ecosystem</h1>

<p align="center">
  <b>Полностью автономная экосистема Telegram-ботов на базе GitHub Actions.</b><br>
  Бесплатный хостинг, умная фильтрация контента и AI-генерация описаний.
</p>

<p align="center">
  <a href="https://t.me/eroslabai"><strong>🔞 Основной канал</strong></a>
  • 
  <a href="https://t.me/eroslabwallpaper"><strong>🤍 Обои</strong></a>
</p>

---

### ⚡️ Killer Features

*   **Serverless Architecture** — Работает 24/7 на GitHub Actions. Ноль затрат на сервер.
*   **Gist DB Storage** — Состояние и история хранятся в скрытых Gists. **Никаких лишних коммитов** в историю репозитория.
*   **Smart Filtering** — Защита от дублей по хешу медиа, проверка разрешения и качества.
*   **AI Engine** — Автоматическая генерация подписей через Groq/OpenRouter (Vision).
*   **Media Processing** — Наложение водяных знаков и перекодирование видео через FFmpeg на лету.

---

### 🛠 Stack & Integration

| Component | Technology |
| :--- | :--- |
| **Engine** | Python 3.11 + `python-telegram-bot` |
| **Runtime** | GitHub Actions (Workflow Dispatch / Schedule) |
| **Database** | GitHub Gist API (No-SQL style) |
| **Content** | CivitAI, Rule34, Wallhaven |
| **AI/ML** | Groq (Llama 3), OpenRouter |
| **Media** | FFmpeg, yt-dlp |

---

### 📂 Project Logic

```text
📜 civitai_bot.py      # Core Engine (NSFW/Main)
📜 wallpapers_bot.py   # SFW Engine (Wallpapers)
📜 gist_storage.py     # State & Hash Management
📜 caption_gen.py      # AI Captioning Logic
📜 watermark.py        # Image/Video Processing
└─ .github/workflows/  # Deployment & Scheduling
⚙️ Quick ConfigurationДобавьте следующие переменные в Settings > Secrets and variables > Actions:SecretRoleTELEGRAM_BOT_TOKENТокен бота для контента 18+TELEGRAM_BOT_TOKEN_WALLPAPERSТокен бота для SFW обоевGH_TOKENClassic Token с доступом к GistGIST_IDID вашего секретного GistCIVITAI_API_KEYДоступ к API CivitAIGROQ_API_KEYКлюч для работы AI-подписей👨‍💻 Developed byHaillord — Telegram<p align="right"><img src="https://www.google.com/search?q=https://img.shields.io/badge/Made%2520with-Python-3776AB%3Fstyle%3Dflat-square%26logo%3Dpython" alt="python"><img src="https://www.google.com/search?q=https://img.shields.io/badge/Powered%2520by-GitHub%2520Actions-2088FF%3Fstyle%3Dflat-square%26logo%3Dgithub-actions" alt="actions"></p>