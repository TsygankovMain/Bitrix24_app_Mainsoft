# Учёт трудозатрат — руководство для агента

Приложение для Bitrix24: учёт времени внутри карточки задачи + управленческая отчётность.
Связка **Nuxt 4 (SPA, ssr: false) + Django + PostgreSQL**.

Проект вырос из стартер-кита `bitrix-tools/b24-ai-starter`, но от него остался только каркас.
Бэкенд один — Python/Django. PHP- и Node-бэкендов в проекте нет.

## Git: важное

- `origin` указывает на **чужой апстрим** `bitrix-tools/b24-ai-starter`. Туда не пушить никогда.
- Настоящий репозиторий — remote `user-repo` (`TsygankovMain/Bitrix24_app_Mainsoft`).
- Боевая ветка — `prod_2026`. Пуш в неё = выкатка в прод, только по явной команде.

## Команды

- `make dev-python` — поднять локальный контур (frontend + Django + PostgreSQL).
- `make dev-front` — только frontend.
- `make down` / `make clean` — остановка и полная очистка Docker.
- `make security-scan`, `make security-tests` — проверки безопасности.

### Тесты

- Бэкенд: `cd backends/python/api && python manage.py test main --settings=test_settings`
  (тесты идут на sqlite, PostgreSQL не нужен).
- Фронтенд: `cd frontend && pnpm test` (node:test + tsx, юнит-тесты утилит и композаблов).

## Архитектура

- `frontend/` — Nuxt 4, Vue 3, Bitrix24 UI Kit (`@bitrix24/b24ui-nuxt`), Pinia, i18n.
- `backends/python/api/` — Django-проект, приложение `main`.
- `infrastructure/database/` — init-скрипты БД.
- `local-dev.yaml` — docker compose для локальной разработки (профили `frontend`, `python`, `cloudpub`, `db-postgres`).
- `Dockerfile` (корневой) — production: собирает фронт статикой и кладёт его в backend-образ,
  Django отдаёт и API, и SPA с одного домена.

## Правила разработки

### Frontend

- Компоненты Bitrix24 UI Kit с префиксом `B24`.
- Страницы, работающие внутри Bitrix24, оканчиваются на `.client.vue`.
- Запросы к бэкенду — только через `useApiStore` (`app/stores/api.ts`).
- Маршрутизация по placement'ам делается на клиенте: `index.client.vue` смотрит
  `placement.info()` и редиректит на `/task` или `/reports/project-report`.

### Backend

- Эндпоинты — в `main/views.py`, маршруты в `main/urls.py`.
- Все эндпоинты закрыты JWT, кроме `/install` и `/getToken`.
- Работа с Bitrix24 — через `b24pysdk`.
- Изменения модели — обязательно миграцией.

### Bitrix24

- Placement'ы биндятся в `main/installation_service.py`:
  `TASK_VIEW_TAB`, `SONET_GROUP_DETAIL_TAB`, `CRM_DEAL_DETAIL_TAB`.
- После смены production-домена нужен ре-бинд placement'ов (переустановка приложения).

## Документация

- `README.md` — быстрый старт и production-сборка.
- `DEPLOY_README.md`, `docs/PRODUCTION_ROLLOUT_GUIDE.md` — выкатка.
- `docs/TECHNICAL_DOCUMENTATION.md` — архитектура и ключевые модули.
- `docs/architecture/` — карта фич и спеки.
- `.claude/skills/` — навыки под этот проект.
