# Архитектура приложения «Учёт трудозатрат»

Встроенное Bitrix24-приложение: ввод времени в задачах, синхронизация в локальную БД, управленческие отчёты и проектный контур.

## Слои

### Frontend — Nuxt 3 / Vue 3 + Bitrix24 UI Kit (`frontend/app`)
- **Страницы** `pages/` — отчёты (`reports/*.client.vue`), доска проектов (`projects/`), задача (`task.vue`), настройки, placement-виджеты (`handler/`).
- **Доступ к API** — `stores/api.ts` (Pinia): все вызовы бэка с JWT (`Authorization: Bearer`).
- **Состояние/фильтры** — `composables/` (`useReportFilters`, `useReportGenerator`, `useAppInit` и др.).
- **Компоненты** — `components/reports/` (таблицы, KPI-карточки), `components/common/` (фильтры).

### Backend — Django (`backends/python/api/main`)
- **`views.py`** — HTTP-endpoints, защищены `@auth_required` (JWT), кроме install/getToken.
- **Сервисы:** `configuration_service` (конфиг/маппинг), `timesheet_sync_service` (синк списаний), `project_sync_service` / `project_board_service` (проекты, ИНН-резолв), `report_queries` + `report_services` (построение отчётов), `report_excel` (xlsx), `inn_backfill_service` (ИНН в списания), `installation_service` (создание СП/полей).
- **Модели** — `models.py`: `TimesheetItem` (списание), `ProjectCard` (проект), и др.

### Хранилище и внешние системы
- **PostgreSQL** — локальный кэш списаний (`TimesheetItem`) и проектов (`ProjectCard`) для стабильной аналитики.
- **Bitrix app.option** (`timestamp_config`) — конфигурация приложения (смарт-процессы, маппинг полей).
- **Bitrix24 REST** — через `account.client._bitrix_token.call_method(...)`: `crm.item.list/update`, `crm.requisite.list`, `user.*` и т.д.

## Поток данных (списания времени)
1. Сотрудник вносит время в задаче → элемент **смарт-процесса (СП) списания** в Bitrix.
2. `timesheet_sync_service.sync_all()` читает СП (`crm.item.list`), нормализует по `fields_mapping` (`DataProcessingService`), сохраняет в `TimesheetItem`.
3. **Отчёты** строятся по локальному кэшу (`report_queries` → `report_services`).
4. **Выгрузка «Сырые данные»** (`export_raw_data`) читает СП напрямую из Bitrix.

## Конфигурация
- Смарт-процессы (списание, проект) и маппинг полей задаются в **Настройках**, хранятся в `app.option` (`configuration_service`).
- Поля СП списания определены в `installation_service.TIMESHEET_FIELD_DEFINITIONS` (включая `OUR_INN`, `CLIENT_INN`).

## Ключевые сквозные потоки
- **Отчёты:** `pages/reports/*` → `stores/api` → `/api/report-*` → `report_queries`/`report_services` (+ `report_excel` для xlsx).
- **ИНН → 1С:** проект (`ProjectCard`: `company_id`, `our_legal_entity_id`) → реквизиты (`crm.requisite.list`, `RQ_INN`) → запись в `OUR_INN`/`CLIENT_INN` карточек списания (`inn_backfill_service`) → выгрузка «Сырые данные» → 1С.

> Детальная карта «фича → конкретные файлы» — [feature-map.md](./feature-map.md).
