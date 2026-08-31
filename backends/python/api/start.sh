#!/bin/bash
set -e

# Turn color on
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo "DB Config: HOST=$DB_HOST, PORT=$DB_PORT, NAME=$DB_NAME, USER=$DB_USER"

# Миграции применяются при старте контейнера. Раньше это был ручной релизный шаг,
# и его пропускали: 2026-07-27 прод-БД оказалась на 0011 при коде 0015 — таблицы
# sync_run не существовало, и фоновый синк проектов молча падал на каждой итерации.
# Инстанс один, migrate идемпотентен. При ошибке миграции set -e останавливает старт
# (контейнер не поднимется) — это видно сразу в логе деплоя, в отличие от 500-х на
# каждом запросе к моделям при отсутствующей колонке.
echo -e "${GREEN}Applying database migrations...${NC}"
python manage.py migrate --noinput

# Предсжатие ассетов фронта (.br/.gz) теперь выполняется в Dockerfile при сборке
# образа (Stage 2, сразу после COPY frontend_build), а не здесь. Здесь оно раньше
# падало молча: start.sh выполняется уже от appuser, а /app/frontend_build скопирован
# в образ от root — прав на запись рядом с файлами нет. Ошибка пряталась за `|| echo`,
# и бандлы месяц уезжали в браузер несжатыми незамеченными.

# Таблица кэша (django_cache, см. CACHES в settings.py). Команда идемпотентна:
# если таблица уже есть, она просто сообщает об этом и выходит с кодом 0.
# Отдельной миграцией это не сделать штатным способом — Django предлагает
# именно createcachetable.
echo -e "${GREEN}Ensuring cache table...${NC}"
python manage.py createcachetable

echo -e "${GREEN}Collecting static files...${NC}"
python manage.py collectstatic --noinput || echo "ERROR: collectstatic failed. Continuing..."

# Приложение полностью синхронное (нет async-вьюх/websocket). Под ASGI/uvicorn
# синхронные вьюхи Django выполнялись в пуле потоков, и close_old_connections не
# закрывал потоко-локальные соединения с БД -> они зависали как 'idle' и упирались
# в max_connections=25. Под WSGI/gunicorn соединение закрывается в конце каждого
# запроса (CONN_MAX_AGE=0), утечки нет. Воркеры/потоки ограничены, чтобы суммарно
# держать заметно меньше доступного лимита соединений. timeout 300 — на долгие синки.
echo -e "${GREEN}Starting Gunicorn (WSGI) server...${NC}"

# Встроенный планировщик (App Platform не имеет внешнего cron): четыре независимых
# фоновых цикла — отдельные дочерние процессы, переживают exec gunicorn. Сначала
# спим в каждом, чтобы не конкурировать со стартом/миграциями; advisory-lock
# (per-scope: project/timesheet/users) защищает от дублей при нескольких инстансах
# App Platform. Падение одной итерации (|| true) не убивает цикл.

# Проекты: полный синк раз в 3 часа.
( while true; do sleep 10800; python manage.py sync_all_portals --scope project || true; done ) &

# Таймшиты: инкремент (scoped 7д) каждые 20 минут, off-request.
( while true; do sleep 1200; python manage.py sync_all_portals --scope timesheet || true; done ) &
# Таймшиты: полная ночная сверка раз в сутки (ловит удаления/пропуски).
( while true; do sleep 86400; python manage.py sync_all_portals --scope timesheet --full || true; done ) &

# Пользователи: полный синк раз в час (юзеров мало, меняются редко; полный
# синк дешёвый — отдельная "ночная" сверка не нужна, часовой цикл её заменяет,
# см. Global Constraints / Self-Review). Первый прогон — сразу, БЕЗ начального
# sleep 3600: таблица portal_user новая и пустая на всех порталах в момент
# деплоя, а синк дешёвый — час ожидания ничем не оправдан (Дефект 3
# финального ревью Фазы 2).
( python manage.py sync_all_portals --scope users || true
  while true; do sleep 3600; python manage.py sync_all_portals --scope users || true; done ) &

# Задачи: актуальные название и группа (PortalTask), раз в час. Нужен, потому
# что название задачи и её проект приложение хранит СНИМКОМ на карточке
# списания: перенос или переименование меняют задачу, карточка не меняется, её
# updatedTime не двигается — и ни инкремент, ни ночная полная сверка этого не
# видят. Отчёт берёт актуальные значения отсюда.
# Первый прогон сразу, без начальной паузы: таблица новая и пустая в момент
# деплоя, а до её наполнения отчёты показывают снимок, то есть ровно ту
# рассинхронизацию, ради которой всё и делалось. Синк дешёвый — на боевом
# портале 1 582 задачи, выборка по списку ID пачками по 50.
( python manage.py sync_all_portals --scope tasks || true
  while true; do sleep 3600; python manage.py sync_all_portals --scope tasks || true; done ) &

# Очистка логов: request_log и system_log старше 30 дней. Команда
# purge_request_logs существовала с самого начала, но не запускалась ниоткуда —
# таблицы росли без ограничения. Это стало заметно, когда логирование
# расширили: теперь в system_log идёт всё уровня WARNING и выше, а в
# request_log — все ошибки, включая ранее пропускавшиеся 4xx на /api/getToken.
# Тела запросов могут содержать токены (см. докстринг команды), так что
# ограничение срока хранения здесь ещё и про безопасность, не только про
# размер. Первый прогон — после суток аптайма, чистить на старте нечего.
( while true; do sleep 86400; python manage.py purge_request_logs || true; done ) &

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
