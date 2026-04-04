# Техническая документация приложения «Учёт трудозатрат»

## 1. Назначение

Приложение предназначено для учета времени в задачах Bitrix24 и последующего анализа этих данных через набор отчетов и административных экранов.

Текущая рабочая связка проекта:

- frontend: `Nuxt 3`
- backend: `Django`
- database: `PostgreSQL`
- интеграция с Bitrix24: `@bitrix24/b24jssdk` и `b24pysdk`

## 2. Архитектура

```text
Bitrix24
  ├── задачи
  ├── смарт-процесс с записями времени
  └── iframe / placement приложения
           │
           ▼
Frontend (Nuxt 3)
  ├── embedded-вкладка в задаче
  ├── отчеты
  ├── настройки
  └── guide
           │
           ▼
Backend (Django)
  ├── аутентификация по JWT
  ├── конфигурация приложения
  ├── синхронизация данных из Bitrix24
  ├── построение отчетов
  └── экспорт и диагностика
           │
           ▼
PostgreSQL
  ├── bitrix24account
  ├── timesheet_item
  ├── request_log
  └── system_log
```

## 3. Режимы работы frontend

Во frontend есть два основных режима:

### Embedded

Файл: `frontend/app/pages/embedded.vue`

Используется во вкладке задачи Bitrix24. Работает напрямую через Bitrix24 JSSDK:

- получает контекст задачи;
- читает дерево подзадач;
- создает и обновляет записи времени;
- удаляет и разделяет записи;
- использует конфигурацию полей из `app.option.get`.

### Standalone

Основные страницы:

- `frontend/app/pages/index.client.vue`
- `frontend/app/pages/reports/*.vue`
- `frontend/app/pages/settings/*.vue`
- `frontend/app/pages/guide.client.vue`

Этот режим использует backend API через store `frontend/app/stores/api.ts`.

## 4. Основные пользовательские модули

### 4.1. Вкладка в задаче

Ключевые сценарии:

- добавление записи времени;
- редактирование записи;
- удаление записи;
- разделение записи;
- отображение дерева задач и накопительных итогов;
- расчет суммы по ставке часа.

Связанные файлы:

- `frontend/app/pages/embedded.vue`
- `frontend/app/components/TaskGroupComponent.vue`
- `frontend/app/components/TaskItemRow.vue`

### 4.2. Отчеты

Текущий набор отчетов:

- `employee.client.vue`
- `project.client.vue`
- `daily.client.vue`
- `project-task.client.vue`
- `revenue-leakage.client.vue`
- `time-discipline.client.vue`
- `focus-analysis.client.vue`
- `raw-data.client.vue`

Общий сценарий для основных отчетов:

1. загрузить фильтры;
2. выбрать период и параметры;
3. нажать `Сформировать`;
4. получить агрегированные данные от backend;
5. при необходимости выгрузить текущую выборку в Excel.

### 4.3. Настройки

Основные страницы:

- `settings/index.client.vue`
- `settings/mapping.client.vue`
- `settings/debug.client.vue`

Что настраивается:

- маппинг полей смарт-процесса;
- ставка часа;
- кликабельные метки в отчетах;
- доступ к сырым данным и служебным логам.

## 5. Backend: основные компоненты

### 5.1. Маршруты

Файл: `backends/python/api/main/urls.py`

Ключевые группы маршрутов:

- install/auth:
  - `/api/install`
  - `/api/getToken`
- filters/reports:
  - `/api/get-filter-employees`
  - `/api/get-filter-projects`
  - `/api/report-employee-project`
  - `/api/report-project-employee`
  - `/api/report-daily-workload`
  - `/api/report-project-task-employee`
  - `/api/report-revenue-leakage`
  - `/api/report-time-entry-discipline`
  - `/api/report-focus-analysis`
- timesheets:
  - `/api/sync-timesheets`
  - `/api/timesheets`
  - `/api/export-raw-data`
- configuration:
  - `/api/configuration`
  - `/api/configuration/save`
  - `/api/smart-processes`
  - `/api/smart-processes/fields`
  - `/api/smart-processes/create`
  - `/api/smart-processes/create-fields`
- logs:
  - `/api/logs/requests`
  - `/api/logs/system`

### 5.2. Сервисы

Файл: `backends/python/api/main/services.py`

Ключевые сервисы:

- `BitrixDataService`
  - загрузка пользователей;
  - загрузка активных пользователей для фильтров;
  - загрузка элементов смарт-процесса;
- `DataProcessingService`
  - нормализация сырых данных из Bitrix24;
  - сбор иерархии задач и проектных полей;
- `ReportService`
  - построение структурированных и аналитических отчетов;
- `TimesheetSyncService`
  - пакетная синхронизация записей из Bitrix24 в локальную БД.

### 5.3. Особенности синхронизации

Синхронизация:

- читает данные батчами из `crm.item.list`;
- нормализует значения полей;
- сохраняет записи в `timesheet_item`;
- удаляет локальные записи, которых больше нет в Bitrix24;
- использует retry/backoff для rate limit.

Сохранение сейчас идет через `update_or_create`, что удобно для консистентности, но дорого по производительности на больших объемах.

## 6. Модель данных

Файл: `backends/python/api/main/models.py`

### `Bitrix24Account`

Хранит установку приложения и OAuth-данные портала:

- домен портала;
- access/refresh token;
- статус установки;
- scope и версию приложения;
- JWT-логику для frontend/backend обмена.

### `TimesheetItem`

Основной локальный кэш записи времени:

| Поле | Назначение |
|---|---|
| `bitrix_id` | ID элемента в Bitrix24 |
| `task_id` | ID задачи |
| `employee_id` | ID сотрудника |
| `hours` | часы |
| `is_billable` | учитываемая запись или нет |
| `non_billable_hours` | отдельное числовое поле неучитываемых часов |
| `description` | описание работы |
| `project_id` | ID проекта |
| `project_title` | название проекта |
| `task_hierarchy_ids` | иерархия ID задач |
| `task_hierarchy_titles` | иерархия названий задач |
| `date_reflection` | дата отражения |
| `source_created_at` | оригинальная дата создания записи в Bitrix24 |

### Служебные таблицы

- `RequestLog` — журнал HTTP-запросов;
- `SystemLog` — системные события и ошибки.

## 7. Конфигурация полей

В приложении есть два уровня конфигурации:

### Backend configuration

Backend хранит конфигурацию через `app.option` и работает с:

- `sp_entity_type_id`
- `fields_mapping`
- `hourly_rate`
- дополнительными task/spa fields

### Frontend configuration

Файл: `frontend/app/stores/fieldConfig.ts`

Store:

- читает конфиг через `app.option.get`;
- преобразует backend-ключи в frontend-константы;
- отдает объект `configObject` для `embedded.vue` и `task.vue`.

## 8. Frontend stores и утилиты

### `frontend/app/stores/api.ts`

Центральная точка работы с backend API:

- healthcheck;
- получение JWT;
- фильтры;
- все report endpoints;
- синхронизация;
- работа с сырыми данными;
- конфигурация и журналы.

### `frontend/app/stores/fieldConfig.ts`

Отвечает за:

- загрузку конфигурации из Bitrix24;
- хранение entity type id;
- хранение mappings и ставки часа;
- backward-compatible объект конфигурации для embedded-страниц.

### Полезные утилиты

- `reportDateRange.ts` — пресеты периодов;
- `exportXlsx.ts` — выгрузка в Excel;
- `iframe-resizer.ts` — работа с высотой iframe внутри Bitrix24;
- `openCrmItem.ts` — открытие карточек элементов.

## 9. Логика фильтров

Фильтры отчетов разделены на два типа:

- сотрудники;
- проекты.

Источники данных:

- сотрудники загружаются отдельно через `user.get`;
- проекты формируются отдельно из локального кэша.

Поддерживаются два режима:

- `include`
- `exclude`

На frontend это реализовано через `MultiSelectFilter.vue`, а на backend через параметры:

- `employee_ids[]`
- `employee_mode`
- `project_ids[]`
- `project_mode`

## 10. Экспорт

В проекте есть два разных сценария Excel:

### Экспорт отчетов

Используется в основных аналитических страницах и выгружает текущую выборку отчета.

### Экспорт сырых данных

Файл: `frontend/app/pages/reports/raw-data.client.vue`

Позволяет:

- выбрать тип даты;
- задать период;
- выбрать набор полей;
- скачать Excel напрямую по данным из Bitrix24.

## 11. Локальная разработка

Базовый сценарий:

```bash
cp .env.example .env
make dev-python
```

Дополнительные команды:

```bash
make down
make logs
make queue-up
make queue-down
```

Основной compose-файл локальной разработки: `local-dev.yaml`.

## 12. Production и деплой

Production-сборка выполняется через корневой `Dockerfile`:

- на первом этапе собирается frontend;
- на втором запускается Python image с backend;
- frontend build копируется в backend image и раздается из него.

Отдельная инструкция:

- [DEPLOY_README.md](../DEPLOY_README.md)

## 13. Основные ограничения и известные особенности

- отчеты работают по локальному кэшу backend, а не по прямому live-чтению Bitrix24;
- часть аналитики зависит от качества маппинга полей;
- производительность синхронизации упирается в модель хранения и `update_or_create`;
- встраиваемые экраны зависят от поведения iframe и layout Bitrix24, поэтому UI-фиксы часто связаны с контейнерами, скроллом и высотой окна.

## 14. Связанные документы

- [README](../README.md)
- [INSTALLATION_GUIDE.md](./INSTALLATION_GUIDE.md)
- [Application_Documentation.md](../Application_Documentation.md)
