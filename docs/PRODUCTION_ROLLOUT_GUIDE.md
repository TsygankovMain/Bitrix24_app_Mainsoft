# Production Rollout Guide

Короткий guide для технического специалиста и продакта перед выпуском в production.

## Цель

Выпустить приложение на production-домен без CloudPub и убедиться, что:

- приложение открывается внутри Bitrix24;
- placements указывают на production URL;
- backend и frontend работают с одного домена;
- отчеты, настройки и task embedded открываются без dev tunnel.

## Этапы rollout

### 1. Подготовка production host

Нужно:

- поднять production domain с SSL;
- подготовить PostgreSQL;
- собрать image с правильным `VIRTUAL_HOST`.

### 2. Сборка

```bash
docker build \
  --build-arg VIRTUAL_HOST=https://app.example.com \
  --build-arg NUXT_PUBLIC_API_URL=https://app.example.com \
  -t bitrix24-timesheet:prod .
```

### 3. Runtime env

Проверить наличие:

- `BUILD_TARGET=production`
- `VIRTUAL_HOST=https://app.example.com`
- `CLIENT_ID`
- `CLIENT_SECRET`
- `JWT_SECRET`
- `DB_*`

### 4. Release step — миграции БД (ОБЯЗАТЕЛЬНО)

> ⚠️ `start.sh` **намеренно НЕ запускает миграции** при старте контейнера (`Skipping automatic migrations at runtime`). Их нужно прогнать **вручную как релизный шаг** — иначе после деплоя кода с новыми полями БД будет без колонок → **500 на каждом запросе к моделям** (`TimesheetItem`/`ProjectCard`).

```bash
# 1. Сначала проверить состояние
python manage.py showmigrations main

# 2. Применить
python manage.py migrate --noinput
```

**Если `migrate` падает с `DuplicateColumn: column ... already exists`** — это расхождение лайнеджей миграций (схема уже содержит колонку, которую миграция пытается добавить; типично после merge ветки с другой историей миграций). Порядок реконсиляции:

```bash
# узнать, какие колонки уже есть
python manage.py shell -c "from django.db import connection; c=connection.cursor(); c.execute(\"SELECT table_name||'.'||column_name FROM information_schema.columns WHERE table_name='timesheet_item'\"); print([r[0] for r in c.fetchall()])"

# миграцию, чьи колонки УЖЕ существуют → пометить применённой без SQL:
python manage.py migrate main <NNNN_name> --fake
# миграции с НЕДОСТАЮЩИМИ колонками → применить обычно:
python manage.py migrate main
```

После — `showmigrations main` должен показать все `[X]`.

### 5. Bitrix24 setup

В настройках локального/серверного приложения:

- URL приложения: `https://app.example.com/`
- URL установки: `https://app.example.com/install`

После смены домена:

- переустановить приложение или выполнить повторный bind placement’ов.

### 6. Smoke test

Минимальный набор:

1. Открыть приложение из Bitrix24.
2. Проверить загрузку главной.
3. Проверить `/api/getToken`.
4. Открыть задачу и вкладку учета времени.
5. Открыть проектный сценарий.
6. Открыть любой отчет и настройки.
7. Убедиться, что в `Network` нет обращений к `cloudpub.ru`.
8. В `Network` на странице отчёта: `POST /api/sync-timesheets` → `200`
   со `{"status": "success"}`, в консоли нет 5xx. Тихий 500 на синке не ломает
   страницы визуально — см.
   [инцидент 2026-06-10](./incidents/2026-06-10-sync-advisory-lock-bigint.md).

## Признаки корректного релиза

- нет `ERR_NETWORK` на старый домен;
- `/_nuxt/*` грузится как JS/CSS, а не как HTML;
- `TASK_VIEW_TAB` и `SONET_GROUP_DETAIL_TAB` открывают production-приложение;
- ручной hard refresh не ломает страницы;
- backend health check отвечает стабильно.

## Если что-то пошло не так

Сначала проверить:

- совпадает ли `VIRTUAL_HOST` в build и runtime;
- не остались ли старые Bitrix24 handler URL;
- содержит ли image `frontend_build/index.html`;
- не открылся ли портал на старом cached frontend.
