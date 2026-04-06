<p align="center">
  <img src="banner.svg?v=5" width="100%" alt="ErosLab Banner">
</p>

<p align="center">
  <a href="https://git.io/typing-svg">
    <img src="https://readme-typing-svg.demolab.com?font=monospace&size=20&pause=2000&color=FF2244&center=true&width=600&lines=ErosLab+Bot+Ecosystem+🔞;Serverless+24%2F7+на+GitHub+Actions;AI-генерация+через+Groq+%26+Llama+3;Умная+фильтрация+и+защита+от+дублей;Бесплатный+хостинг+•+Полная+автономность">
  </a>
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

- **Serverless 24/7** — Полная автоматизация на GitHub Actions без затрат на сервер.
- **Gist Database** — Хранение состояния в скрытых Gists: **никаких лишних коммитов** в истории.
- **Smart Filtering** — Защита от дублей по хешу, автоматический контроль качества и разрешения.
- **AI Engine** — Генерация контекстных подписей через Groq и OpenRouter (Llama 3 / Vision).
- **Media Lab** — Наложение водяных знаков и оптимизация видео через FFmpeg на лету.

---

### 🛠 Stack & Integration

| Компонент | Технологии |
| :--- | :--- |
| **Engine** | Python 3.11 • `python-telegram-bot` |
| **Automation** | GitHub Actions Workflow |
| **Database** | GitHub Gist API |
| **Content** | CivitAI • Rule34 • Wallhaven |
| **AI Processing** | Groq • OpenRouter |
| **Media** | FFmpeg • yt-dlp |

---

### 📂 Structure

```text
📜 civitai_bot.py      # Основной движок (NSFW)
📜 wallpapers_bot.py   # Бот с обоями (SFW)
📜 gist_storage.py     # Логика работы с БД Gist
📜 caption_gen.py      # AI-генератор описаний
📜 watermark.py        # Обработка фото и видео
```

---

### 🔑 Configuration (Secrets)

Настройте эти переменные в репозитории:  
`Settings` → `Secrets and variables` → `Actions`

| Secret | Описание |
| :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | Токен основного бота |
| `GH_TOKEN` | Classic Token с правами на Gist |
| `GIST_ID` | ID вашего секретного Gist |
| `CIVITAI_API_KEY` | Доступ к API CivitAI |
| `GROQ_API_KEY` | Ключ для AI генерации подписей |

---

<p align="center">
  <img src="https://img.shields.io/badge/Made%20with-Python-3776AB?style=for-the-badge&logo=python" alt="python">
  <img src="https://img.shields.io/badge/Powered%20by-GitHub%20Actions-2088FF?style=for-the-badge&logo=github-actions" alt="actions">
  <img src="https://img.shields.io/badge/Developer-Haillord-red?style=for-the-badge&logo=telegram" alt="author">
</p>