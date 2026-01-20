# ---------- Base stage ----------
FROM python:3.11-slim

# Создаем пользователя appuser
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Копируем и устанавливаем зависимости
COPY backends/python/api/requirements.txt .
# Устанавливаем whitenoise и uvicorn, если они не в requirements
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir uvicorn whitenoise

# Копируем исходный код
COPY backends/python/api/ /app/

# Делаем скрипт запуска исполняемым
RUN chmod +x /app/start.sh

# Переключаемся на пользователя appuser
USER appuser

# Открываем порт
EXPOSE 8000

# Запускаем через start.sh (миграции + статика + сервер)
CMD ["/app/start.sh"]
