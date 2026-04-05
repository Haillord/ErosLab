<p align="center">
  <img src="logo.png?v=5" width="1080" alt="ErosLab Logo">
  <h3 align="center">ErosLab Bot</h3>
  <p align="center">
    Автоматизированный контентный бот для Telegram
    <br />
    <a href="https://t.me/eroslabai"><strong>🔞 Основной канал</strong></a>
    ·
    <a href="https://t.me/eroslabwallpaper"><strong>🤍 Обои</strong></a>
  </p>
</p>

---

## ✨ О проекте

Два полностью независимых бота которые 24/7 публикуют контент в Telegram каналы. Оптимизированы для работы на GitHub Actions абсолютно бесплатно, без необходимости в собственном сервере.

## 🚀 Особенности

✅ **Два независимых бота**
- 🔞 Основной бот с контентом 18+ (CivitAI + Rule34)
- 🤍 Бот с безопасными красивыми обоями (CivitAI + Wallhaven)

✅ **Умные алгоритмы**
- Защита от дубликатов по хешу медиа
- Разнообразие хештегов с защитой от повторов
- Автоматическое чередование типов контента
- Фильтрация по качеству и разрешению
- Автоматическая генерация подписей

✅ **Архитектура**
- Полностью работает на GitHub Actions
- Состояние хранится в отдельном секретном Gist
- ❌ Больше нет мусорных коммитов каждые 2 часа в истории
- Встроенная история версий всех данных
- Никаких git конфликтов, pull/push задержек

✅ **Дополнительные фичи**
- Автоматический водяной знак
- AI генерация подписей
- Оптимизация видео для Telegram
- Кросспромо между каналами
- Детальная статистика запусков

---

## 🛠 Технологии

| Компонент | Стек |
|---|---|
| Язык | Python 3.11 |
| Хранилище | GitHub Gist |
| CI/CD | GitHub Actions |
| Источники контента | CivitAI, Rule34, Wallhaven |
| AI | Groq, OpenRouter |
| Видео обработка | FFmpeg + yt-dlp |
| Фреймворк | python-telegram-bot |

---

## 📂 Структура проекта

```
📦 eroslab-bot
├─ 📜 civitai_bot.py          # Основной бот 🔞
├─ 📜 wallpapers_bot.py       # Бот с обоями 🤍
├─ 📜 gist_storage.py         # Универсальное хранилище на Gist
├─ 📜 caption_generator.py    # Генератор подписей + AI
├─ 📜 watermark.py            # Водяной знак для фото и видео
├─ 📜 rule34_api.py           # Обёртка для Rule34 API
├─ 📜 requirements.txt        # Зависимости
└─ 📂 .github/workflows/
   ├─ 📜 bot.yml              # Расписание основного бота
   └─ 📜 wallpapers.yml       # Расписание бота обоев
```

---

## 🔑 Необходимые Secrets

Для работы нужно добавить в Secrets репозитория:

| Secret | Описание |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен основного бота |
| `TELEGRAM_CHANNEL_ID` | ID канала для основного бота |
| `TELEGRAM_BOT_TOKEN_WALLPAPERS` | Токен бота с обоями |
| `TELEGRAM_CHANNEL_ID_WALLPAPERS` | ID канала с обоями |
| `CIVITAI_API_KEY` | API ключ CivitAI |
| `WALLHAVEN_API_KEY` | API ключ Wallhaven |
| `GROQ_API_KEY` | API ключ Groq для AI подписей |
| `OPENROUTER_API_KEY` | API ключ OpenRouter для Vision |
| `GH_TOKEN` | GitHub токен с правами на Gist |
| `GIST_ID` | ID секретного Gist для хранения состояния |
| `ADMIN_USER_ID` | Telegram ID админа |

---

## 🚀 Запуск локально

```bash
# Клонировать репозиторий
git clone https://github.com/Haillord/eroslab-bot.git
cd eroslab-bot

# Установить зависимости
pip install -r requirements.txt

# Установить FFmpeg
sudo apt install ffmpeg

# Установить переменные окружения
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHANNEL_ID="@your_channel"
export CIVITAI_API_KEY="your_key"

# Запустить бота
python civitai_bot.py
```

---

## 👨‍💻 Автор

**@Haillord**

- 🔞 [t.me/eroslabai](https://t.me/eroslabai)
- 🤍 [t.me/eroslabwallpaper](https://t.me/eroslabwallpaper)

---

<p align="center">
  <sub>Сделано с 💙 и много кофе</sub>
</p>