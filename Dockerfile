# ErosLab Bot Docker Image
# Предварительно собранный образ со всеми зависимостями для GitHub Actions
FROM python:3.10-slim

LABEL org.opencontainers.image.description="ErosLab Bot - CivitAI / Rule34 Telegram бот"
LABEL org.opencontainers.image.source="https://github.com/Haillord/eroslab-bot"

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV DEBIAN_FRONTEND=noninteractive

# Установка системных зависимостей один раз
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Установка Python зависимостей один раз
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода бота
COPY . .

# Точка входа
CMD ["python", "civitai_bot.py"]