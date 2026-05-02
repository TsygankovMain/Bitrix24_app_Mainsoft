# Task Status Log — 2026-04-24

## Контекст
- Репозиторий: dev_pyton_app
- Текущая ветка: DEV_new_functions
- Цель: запуск разработки функционала учёта доходов и расходов + локальный стенд Docker + CloudPub + инструкция возврата к прод-сценарию.

## Что сделано
1. Переключение на рабочую ветку `DEV_new_functions`.
2. Реализован MVP для учёта доходов/расходов в проектном модуле:
   - Backend (Python/Django):
     - добавлены поля `project_income` и `project_expense` в `ProjectCard`;
     - добавлена миграция `0010_projectcard_finance_fields.py`;
     - добавлены новые поля в sync из Project SPA (`project_sync_service.py`);
     - добавлены новые поля в сохранение/сериализацию board API (`project_board_service.py`);
     - добавлены новые маппинги в `installation_service.py` и валидацию в `views.py`.
   - Frontend (Nuxt/Vue):
     - обновлены типы `project-board.ts`;
     - в drawer проекта добавлены поля ввода Доход/Расход;
     - в карточке проекта добавлено отображение Доход/Расход;
     - в настройках маппинга добавлены поля `project_income` и `project_expense`.
3. Проверка Python-синтаксиса выполнена успешно (`py_compile` для изменённых backend-файлов).

## Текущий блокер
- Поднять CloudPub через Docker пока не удалось.
- Ошибка повторяется стабильно:
  - `failed to resolve reference "docker.io/cloudpub/cloudpub:latest"`
  - `net/http: TLS handshake timeout`
- Это сетевой таймаут TLS до Docker Hub (`registry-1.docker.io`), не ошибка токена CloudPub и не ошибка compose-конфига.

## Что осталось сделать
1. Дотянуть образ `cloudpub/cloudpub:latest` и поднять tunnel.
2. Завершить запуск полного локального стенда (`frontend + api-python + db + cloudpub`).
3. Пробросить URL в Bitrix24 для тестов.
4. Создать отдельную документацию по возврату к продовому сценарию.

## Примечание
- В рабочем дереве уже есть изменения по ранее выполненной чистке документации (до начала этой задачи).
