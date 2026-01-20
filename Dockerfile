# ---------- Base stage ----------
FROM python:3.11-slim

# Создаем пользователя appuser
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Установка системных зависимостей (если нужны для psycopg2 и т.д.)
# Убедимся, что установлены необходимые библиотеки для сборки (если есть бинарные зависимости)
RUN apt-get update && apt-get install -y \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Копируем и устанавливаем зависимости
COPY backends/python/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir uvicorn

# Копируем исходный код
COPY backends/python/api/ /app/

# Переключаемся на пользователя appuser
USER appuser

# Открываем порт
EXPOSE 8000

# Запускаем через uvicorn
# Точка входа: asgi.py находится в корне /app/ (так как мы скопировали содержимое api/ в /app/)
# Модуль asgi.py содержит переменную application
CMD ["uvicorn", "asgi:application", "--host", "0.0.0.0", "--port", "8000"]
