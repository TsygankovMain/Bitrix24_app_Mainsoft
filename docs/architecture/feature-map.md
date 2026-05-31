# Карта: фича → код

Навигационный ориентир: какие файлы трогать для каждой пользовательской фичи (фронт + бэк + endpoint).
Точные имена функций/методов и строки сверяйте с актуальным кодом — карта обновляется по мере развития (см. конвенцию в [../README.md](../README.md)).

## 1. Учёт времени в задаче (placement)
- **Фронт:** `pages/task.vue` — placement в карточке задачи; `composables/useTaskPlacement.ts`, `composables/useTaskTreeLoader.ts`; компоненты `components/TaskGroupComponent.vue`, `TaskNode.vue`, `TaskItemRow.vue`.
- **Синхронизация:** `stores/api.ts::syncTimesheets()` → `POST /api/sync-timesheets`.
- **Бэк:** `views.py::timesheet_sync` → `timesheet_sync_service.py::TimesheetSyncService`; модель `models.py::TimesheetItem`.

## 2. Синхронизация списаний (Bitrix СП → локальная БД)
- **Фронт:** `pages/reports/raw-data.client.vue` (кнопка «Синхронизировать»); `stores/api.ts::syncTimesheets()`.
- **Бэк:** `views.py::timesheet_sync` → `timesheet_sync_service.py::TimesheetSyncService.sync_all()` (чтение `crm.item.list`, нормализация по `fields_mapping`, bulk upsert в `TimesheetItem`). После синка — авто-простановка ИНН (`_autofill_inn` → `inn_backfill_service`).

## 3. Отчёты
Общий путь: `pages/reports/*.client.vue` → `stores/api.ts::getReport*` → `GET /api/report-*` → `views.py::report_*` → `report_queries.py` + `report_services.py::ReportService`. Фильтры — `composables/useReportFilters.ts`, генерация — `useReportGenerator.ts`.

| Отчёт | Страница | API-метод / endpoint |
|---|---|---|
| По сотрудникам | `reports/employee.client.vue` | `getReportEmployeeProject` → `/api/report-employee-project` |
| По проектам | `reports/project.client.vue` | `getReportProjectEmployee` → `/api/report-project-employee` |
| Ежедневная нагрузка | `reports/daily.client.vue` | `getReportDailyWorkload` → `/api/report-daily-workload` |
| Учёт по проектам/задачам | `reports/project-task.client.vue` | `getReportProjectTaskEmployee` → `/api/report-project-task-employee` |
| Потери выручки | `reports/revenue-leakage.client.vue` | `getReportRevenueLeakage` → `/api/report-revenue-leakage` |
| Дисциплина внесения | `reports/time-discipline.client.vue` | `getReportTimeEntryDiscipline` → `/api/report-time-entry-discipline` |
| Фокус и распыление | `reports/focus-analysis.client.vue` | `getReportFocusAnalysis` → `/api/report-focus-analysis` |

**Учёт по проектам/задачам — детали:** компоненты `components/reports/ProjectTaskReportTable.vue` / `ProjectTaskReportRow.vue` / `ProjectTaskReportEmployeeRow.vue`; форматтер `utils/reportFormat.ts`; кликабельные метки `composables/useProjectTaskLabel.ts`. Excel-выгрузка: `exportReportProjectTaskEmployee` → `GET /api/report-project-task-employee-export` → `views.py::report_project_task_employee_export` → `report_excel.py::build_project_task_workbook`.

**Excel-выгрузка (все отчёты, серверная):** генераторы `report_excel.py::{build_hierarchy_workbook, build_matrix_workbook, build_table_workbook, build_project_task_workbook}`; на каждый отчёт — `views.py::report_*_export` (`…-export` endpoint) + `api.ts::exportReport*` + `handleExport` на странице. Тесты — `tests_report_excel.py`.

## 4. Выгрузка «Сырые данные» и дозаполнение ИНН
- **Выгрузка:** `pages/reports/raw-data.client.vue` (вкладка «Выгрузка») → `stores/api.ts::exportRawData()` → `POST /api/export-raw-data` → `views.py::export_raw_data` (openpyxl, чтение СП напрямую).
- **Дозаполнение ИНН:** вкладка «Дозаполнение ИНН» → `components/reports/InnBackfillPanel.vue` (+ `InnAssignModal.vue` — окно заполнения/замены на проект, `components/common/ProgressOverlay.vue` — прогресс с бобром); `stores/api.ts::scanInnBackfill()` / `applyInnBackfill()` / `resolveInnProjectItems()` / `getProjectsHealth()` → `/api/inn-backfill/scan|apply|project-items`, `/api/projects-health` → `views.py::inn_backfill_scan` / `inn_backfill_apply` / `inn_backfill_project_items` / `projects_health` → `inn_backfill_service.py::InnBackfillService` (`scan`/`apply`/`autofill`/`project_items`/`projects_health`). Настройки «Незаполненные проекты» — `pages/settings/projects-health.client.vue`. Типы — `types/inn.ts`.

## 5. Проектный контур (доска / timeline / карточка)
- **Фронт:** `pages/projects/index.client.vue`; компоненты `components/projects/ProjectBoardCard.vue`, `ProjectBoardColumn.vue`, `ProjectBoardDrawer.vue`, `ProjectTimelineLane.vue`; утилиты `utils/projectBoard.ts`, `utils/openProjectGroup.ts`.
- **API:** `getProjectBoard` → `/api/project-board`; `getProjectBoardMeta` → `/api/project-board/meta`; `getProjectBoardCard` → `/api/project-board/card`; обновления → `/api/project-board/update`, `/update-stage`, `/archive`; синк → `/api/project-board/sync`.
- **Бэк:** `views.py::get_project_board / get_project_board_meta / update_project_board / sync_project_board` → `project_board_service.py::ProjectCardService`, `project_sync_service.py::ProjectSyncService`; модель `models.py::ProjectCard`.
- **ИНН-резолв:** `project_board_service.py` — `get_companies()`, `get_legal_entities()`, `_fetch_company_inn_map()` (`crm.requisite.list`, `RQ_INN`).

## 6. Настройки (смарт-процессы, маппинг, создание полей)
- **Фронт:** страницы настроек/маппинга; `stores/api.ts::getConfiguration()` / `saveConfiguration()`, `getSmartProcesses()`, `getSpFields()`, `createSmartProcess()`, `createFields()`, `createMappedField()`.
- **Endpoints:** `/api/configuration`, `/api/configuration/save`, `/api/smart-processes`, `/api/smart-processes/fields`, `/api/smart-processes/create`, `/create-fields`, `/create-field`, `/api/project-spa/validation`, `/api/project-spa/stages`.
- **Бэк:** `views.py` соответствующие функции → `configuration_service.py::ConfigurationService`, `installation_service.py::InstallationService` (определения полей, в т.ч. `TIMESHEET_FIELD_DEFINITIONS` с `OUR_INN`/`CLIENT_INN`).

## 7. Установка и авторизация
- **Фронт:** `pages/install.client.vue`; `stores/api.ts::postInstall()`, `getToken()`.
- **Бэк:** `views.py::install` / `get_token` → `installation_service.py::InstallationService`; модели `models.py::Bitrix24Account` (JWT: `create_jwt_token`/`get_from_jwt_token`), `ApplicationInstallation`. JWT-проверка — `utils/decorators/auth_required.py`.

## 8. Логи и диагностика
- **Фронт:** страница отладки; `stores/api.ts::getRequestLogs()`, `getSystemLogs()`.
- **Бэк:** `views.py::get_request_logs / get_system_logs`; модели `models.py::RequestLog`, `SystemLog`.

## Прочее
- **Глобальный прогресс:** `composables/useProgress.ts` (синглтон `begin/update/end`, счётчик параллельных операций) + единый `<ProgressOverlay>` (🦫) в `app.vue`. `begin/end` — в `useReportGenerator` (генерация отчётов), `handleExport*` (выгрузки), синках, ИНН-простановке. Тест `tests/progress.test.ts`.
- **Главная/портфолио:** `pages/index.client.vue` → `getHomepagePortfolio` → `/api/homepage/portfolio`.
- **Поддержка:** `/api/support/status`, `/api/support/connect`.
- **Финансовый контур** — **в планах**, на текущий момент изолирован (см. CHANGELOG, секции про finance).

---
*Карта собрана автоматически + выверена по ключевым потокам сессии (отчёты, ИНН). При расхождении имён — приоритет у кода.*
