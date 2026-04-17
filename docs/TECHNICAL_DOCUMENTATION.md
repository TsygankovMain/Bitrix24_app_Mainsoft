# Техническая документация

## 1. Стек

- frontend: `Nuxt 4`, `Vue 3`, `TypeScript`, `Pinia`
- backend: `Django`
- database: `PostgreSQL`
- Bitrix24 integration: `@bitrix24/b24jssdk`, `b24pysdk`

## 2. Каноническая архитектура

### Production

Production-схема одна:

```text
Bitrix24
  -> production domain приложения
  -> Django backend
      -> API
      -> SPA index.html
      -> frontend assets (_nuxt)
      -> PostgreSQL
```

Ключевой файл production-сборки:

- [Dockerfile](../Dockerfile)

Frontend собирается статически и копируется в backend image как `frontend_build`.

### Local dev

Local dev остается отдельным контуром:

- `local-dev.yaml`
- dev frontend server
- dev backend
- внешний tunnel/CloudPub только для открытия локальной среды внутри Bitrix24

CloudPub не считается production-архитектурой.

## 3. Основные frontend-зоны

### Главная и маршрутизация

- `frontend/app/pages/index.client.vue`
- `frontend/app/middleware/01.app.page.or.slider.global.ts`

Root page определяет placement и маршрутизирует пользователя:

- `TASK_VIEW_TAB` -> `/task`
- `SONET_GROUP_DETAIL_TAB` -> `/reports/project-report`

### Embedded / задача

- `frontend/app/pages/embedded.vue`
- `frontend/app/pages/task.vue`
- `frontend/app/composables/useTaskTreeLoader.ts`

Отвечают за:

- чтение контекста задачи;
- загрузку дерева задач;
- CRUD меток времени;
- расчет стоимости;
- редактор записи.

### Отчеты

- `frontend/app/pages/reports/*.client.vue`
- `frontend/app/stores/api.ts`
- `frontend/app/utils/reportFilters.ts`
- `frontend/app/types/report.ts`

Общая логика:

- загрузка filter options;
- ручной запуск `Сформировать`;
- Excel/export flow;
- единый report layer через shared types и helpers.

### Настройки

- `frontend/app/pages/settings/*.client.vue`
- `frontend/app/stores/fieldConfig.ts`

Отвечают за:

- выбор СП;
- загрузку полей;
- создание СП и обязательных полей;
- точечное создание поля из dropdown;
- маппинг полей приложения к Bitrix24.

## 4. Основные backend-зоны

### API routes

Файл:

- `backends/python/api/main/urls.py`

Ключевые группы:

- install/auth:
  - `/api/install`
  - `/api/getToken`
- filters/reports
- project board / homepage
- configuration / smart processes
- logs / diagnostics
- catch-all SPA route

### Install / configuration

Файлы:

- `backends/python/api/main/installation_service.py`
- `backends/python/api/main/configuration_service.py`

Сейчас backend централизованно выполняет bind:

- `TASK_VIEW_TAB`
- `SONET_GROUP_DETAIL_TAB`

### Serving SPA

Файлы:

- `backends/python/api/main/views.py`
- `backends/python/api/settings.py`

Backend:

- отдает `index.html` для SPA;
- использует WhiteNoise для статических файлов;
- работает с `frontend_build`.

## 5. Production config contract

### Build-time

При `pnpm run generate` frontend bake-ит публичные URL. Поэтому build должен знать production host:

- `VIRTUAL_HOST`
- `NUXT_PUBLIC_API_URL` при необходимости

### Runtime

Backend использует:

- `BUILD_TARGET`
- `VIRTUAL_HOST`
- `DB_*`
- `CLIENT_ID`
- `CLIENT_SECRET`
- `JWT_SECRET`
- опционально `DJANGO_ALLOWED_HOSTS`
- опционально `CORS_ALLOWED_ORIGINS`

## 6. Data model

Основные сущности:

- `Bitrix24Account` — установленный портал и OAuth-данные
- `TimesheetItem` — локальный кэш записи времени
- `RequestLog` — журнал HTTP-запросов
- `SystemLog` — системные события

## 7. Важные технические решения

### Почему production идет через один домен

Это снижает количество moving parts:

- не нужен отдельный frontend origin;
- не нужен CloudPub;
- проще install/auth flow;
- меньше рисков с `getToken`, iframe и asset routing.

### Почему CloudPub оставлен только для dev

Tunnel удобен для локальной проверки Bitrix24 placements, но:

- не подходит как стабильный production endpoint;
- усложняет troubleshooting;
- создает риск hardcoded URL в runtime/build.

### Почему bind placement’ов централизован на backend

Это делает install flow предсказуемым:

- один источник истины для handler URL;
- меньше расхождений между manual install и backend install;
- проще переезд между доменами.

## 8. Риски, которые еще нужно держать под контролем

- после смены домена нужен reinstall или rebind placement’ов;
- старый браузерный кеш может отдавать устаревшие frontend chunks;
- release step по миграциям остается обязательным;
- split-deploy Dockerfile’ы в подкаталогах не являются canonical production path.

## 9. Связанные документы

- [README.md](../README.md)
- [DEPLOY_README.md](../DEPLOY_README.md)
- [INSTALLATION_GUIDE.md](./INSTALLATION_GUIDE.md)
- [PRODUCTION_ROLLOUT_GUIDE.md](./PRODUCTION_ROLLOUT_GUIDE.md)
