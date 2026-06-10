#!/bin/bash
set -e

# Turn color on
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo -e "${GREEN}Skipping automatic migrations at runtime...${NC}"
echo "DB Config: HOST=$DB_HOST, PORT=$DB_PORT, NAME=$DB_NAME, USER=$DB_USER"
echo "Run 'python manage.py migrate --noinput' as a release step before starting the app."

echo -e "${GREEN}Collecting static files...${NC}"
python manage.py collectstatic --noinput || echo "ERROR: collectstatic failed. Continuing..."

# Приложение полностью синхронное (нет async-вьюх/websocket). Под ASGI/uvicorn
# синхронные вьюхи Django выполнялись в пуле потоков, и close_old_connections не
# закрывал потоко-локальные соединения с БД -> они зависали как 'idle' и упирались
# в max_connections=25. Под WSGI/gunicorn соединение закрывается в конце каждого
# запроса (CONN_MAX_AGE=0), утечки нет. Воркеры/потоки ограничены, чтобы суммарно
# держать заметно меньше доступного лимита соединений. timeout 300 — на долгие синки.
echo -e "${GREEN}Starting Gunicorn (WSGI) server...${NC}"

# Встроенный планировщик (App Platform не имеет внешнего cron):
# синхронизация ПРОЕКТОВ раз в 3 часа. Трудозатраты синкаются по запросу при открытии отчёта.
# Цикл — отдельный дочерний процесс; переживает exec gunicorn. Сначала спим, чтобы не
# конкурировать со стартом/миграциями; advisory-lock (scope=project) защищает от дублей
# при нескольких инстансах App Platform.
( while true; do sleep 10800; python manage.py sync_all_portals --scope project || true; done ) &

exec gunicorn wsgi:application \
    --bind 0.0.0.0:8000 \
    --worker-class gthread \
    --workers 2 \
    --threads 4 \
    --timeout 300 \
    --graceful-timeout 30 \
    --max-requests 1000 \
    --max-requests-jitter 100 \
    --access-logfile - \
    --error-logfile -
