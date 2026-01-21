# ---------- Base stage ----------
FROM python:3.11-slim

# Создаем пользователя appuser
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Копируем и устанавливаем зависимости
COPY backends/python/api/requirements.txt .
# Устанавливаем whitenoise и uvicorn, если они не в requirements
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir uvicorn whitenoise

# Копируем исходный код
COPY backends/python/api/ /app/

# Сборка статики во время билда (ускоряет запуск)
# Используем фейковые данные для сборки, так как подключения к БД нет
RUN SECRET_KEY=build_only \
    DB_NAME=none DB_USER=none DB_PASSWORD=none DB_HOST=none DB_PORT=5432 \
    python manage.py collectstatic --noinput

# Делаем скрипт запуска исполняемым
RUN chmod +x /app/start.sh

# Переключаемся на пользователя appuser
USER appuser

# Открываем порт
EXPOSE 8000

# Добавляем Healthcheck (как рекомендовано в логах)
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/healthz || exit 1

# Запускаем через start.sh (миграции + сервер)
CMD ["/app/start.sh"]
