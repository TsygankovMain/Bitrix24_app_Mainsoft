# Changelog

Технический лог изменений приложения «Учёт трудозатрат» (для команды).
Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/). Даты — ГГГГ-ММ-ДД.

Пользовательские релизы (человеческим языком) — в [RELEASES.md](./RELEASES.md) *(будет создан в рамках Задачи 3)*.

## [Unreleased]

### Глобальный прогресс-оверлей во всех фоновых операциях — 2026-05-31

#### Added
- Композабл-синглтон `frontend/app/composables/useProgress.ts` (`begin/update/end`, геттер `active`, счётчик `count` параллельных операций) + единый `<ProgressOverlay>` (🦫 Бобёр) смонтирован в `app.vue`. Тест `frontend/tests/progress.test.ts`.

#### Changed
- Прогресс-оверлей теперь показывается во **всех** фоновых операциях: формирование отчётов (`useReportGenerator`), выгрузки Excel (7 страниц), синхронизации (raw-data, доска проектов), ИНН-простановка (с прогрессом X/Y). Локальные `ProgressOverlay` (ИНН-панель/модалка, raw-data) удалены — одна точка правды (`app.vue`).

#### Fixed (code-review)
- BLOCKER: `InnAssignModal.apply` — `begin/end` сделаны строго парными (вложенный `try/finally` только после `begin`), чтобы при пустом списке/параллельной операции не гасить чужой оверлей.
- `useReportGenerator`: `begin` перенесён внутрь `try` (надёжное гашение при ошибке).

#### Verification
- `npx tsx --test tests/progress.test.ts` PASS; `nuxt prepare` чист; `ProgressOverlay` используется только в `app.vue`.
- ⏳ e2e на проде.

### Спринт 4 — Единый структурный Excel во всех отчётах + техдолг — 2026-05-31

#### Added
- 3 переиспользуемых серверных генератора Excel (`report_excel.py`): `build_hierarchy_workbook` (employee/project, с листовыми записями), `build_matrix_workbook` (daily: сотрудник×день, заморозка, итоги по строке/дню), `build_table_workbook` (сводки: форматы text/hours/money/percent/int, опц. ИТОГО).
- 6 серверных export-endpoint (employee/project/daily/revenue-leakage/time-discipline/focus-analysis) по образцу `report_project_task_employee_export`; в `api.ts` — 6 методов; `handleExport` 6 страниц переключён на серверное скачивание blob.
- Тесты `backends/python/api/main/tests_report_excel.py`.

#### Changed
- Все отчёты выгружаются серверным структурным Excel (как project-task). Удалён мёртвый фронтовый xlsx (`utils/reportExport.ts` → заглушка, `utils/exportXlsx.ts` удалён).

#### Fixed (техдолг + ревью)
- ESLint-долг: предсуществующие ошибки в `utils` починены (`npm run lint` зелёный).
- Изоляция finance на фронте: `FINANCE_FEATURE_ENABLED=false` в placement + методы-заглушки в `api.ts`.
- Code-review MAJOR: иерархический Excel (employee/project) сохраняет **листовые записи (items)**, как на экране; счётчики — формат «0» (без «.0»).

#### Verification
- Бэк: 15 тестов OK, `django check` чист. Фронт: `nuxt prepare` чист, `npm run lint` 0.
- Отложено в бэклог: удаление неиспользуемой зависимости `xlsx` (нужен pnpm-lock update); лимит объёма выгрузок; общий composable `useReportExport`; единообразие `loss_rate` (%).
- ⏳ e2e на проде (скачать Excel во всех 6 отчётах).

### Спринт 3 — ИНН-UX: незаполненные проекты, окно заполнения/замены, прогресс с бобром — 2026-05-31

#### Added
- **Настройки → «Незаполненные проекты»** (`pages/settings/projects-health.client.vue`, `GET /api/projects-health` → `InnBackfillService.projects_health`): список проектов без данных для ИНН (нет компании/юрлица/ИНН в реквизитах) + переход к проекту.
- **Окно заполнения/замены ИНН на проект** (`components/reports/InnAssignModal.vue`, `POST /api/inn-backfill/project-items` → `InnBackfillService.project_items`): редактируемые ИНН, режим «только пустые» / «перезаписать всё» (смена юр.лица); запись чанками по 25 через существующий `apply`.
- **Переиспользуемый `ProgressOverlay.vue`** с маскотом 🦫 Бобёр-Учётчик — на ИНН-простановке, синхронизации, экспортах.
- **Сворачивание групп** в панели дозаполнения ИНН.
- Тесты: `test_project_items_blank_only_vs_overwrite`, `test_projects_health_flags`.

#### Changed
- Убраны дублирующие кнопки на вкладке «Дозаполнение ИНН» (синхронизация/обновить — только на вкладке «Выгрузка»).
- `InnBackfillPanel`: кнопка «заполнить (N)» → «Заполнить / Изменить ИНН →» (открывает окно).
- Доска проектов читает `?search=` из query → «Открыть проект» из health-страницы фильтрует доску по `project_id`.

#### Verification
- Бэк: 12 тестов OK, `django check` чист. Фронт: `nuxt prepare` чист.
- Code-review пройдено; MAJOR (битая навигация) + закрытие модалки во время записи + чистка — починены. **Отложено в бэклог:** двойной индикатор на raw-data, диагностика при незамапленных полях проекта, лимит размера `project-items`, валидация формата ИНН, вложенный Teleport.
- ⏳ e2e на проде (вручную).

### Hotfix (prod) — реконсиляция миграций после деплоя — 2026-05-31

#### Fixed
- **Прод: 500 на всех запросах к `TimesheetItem`/`ProjectCard`** (`report-project-task-employee`, `timesheets` и др.). Причина: после деплоя merged `prod_2026` БД не была мигрирована (`start.sh` намеренно пропускает `migrate`). Миграции `0009–0011` пришли с merge, при этом схема прода уже содержала `project_item_id` (расхождение лайнеджей миграций dev/prod) → `migrate` падал с `DuplicateColumn`.
- **Реконсиляция:** `migrate main 0009 --fake` (колонки `project_item_id` уже были) + `migrate main` (применены `0010` → `project_card.project_type/budget_mode/planned_budget_amount`, `0011` → `timesheet_item.hourly_rate_snapshot`). Все миграции `[X]`, 500-е устранены, данные не потеряны.

#### Process
- `PRODUCTION_ROLLOUT_GUIDE.md` (раздел 4) усилен: обязательный `migrate` как релизный шаг + процедура реконсиляции при `DuplicateColumn` (`showmigrations` → `--fake` для уже существующих, обычный `migrate` для недостающих).
- ⏳ Известный не-блокирующий нюанс: `0009` зафейкан → unique-constraint `(account, project_item_id)` на `project_card` мог не создаться (на работу не влияет, upsert идёт по `bitrix_id`). Добавить при необходимости отдельно.

### Задача 3 — Единая база документации — 2026-05-31

#### Added
- `docs/README.md` — единый индекс всей документации (для пользователей / команды / решения / внутреннее).
- `docs/RELEASES.md` — пользовательские релизы (Спринты 1–2 человеческим языком).
- `docs/architecture/overview.md` — обзор архитектуры (слои, потоки данных).
- `docs/architecture/feature-map.md` — карта «фича → файлы кода».
- `docs/CHANGELOG.md` (ведётся всю сессию) — технический лог изменений.

Зафиксирована конвенция: изменение кода → CHANGELOG; пользовательское → RELEASES; новая фича → feature-map. Существующие документы не перемещались (во избежание битых ссылок) — собраны в индексе `README.md`.

### Изоляция финансового функционала на фронте (продолжение разблокировки) — 2026-05-31

Завершение начатого в «Спринт 2 — Этап A» (см. ниже): фронтовая часть finance вынесена и аккуратно изолирована, чтобы не было битых вызовов к уже отключённым на бэке finance-эндпоинтам. Код не удалён — помечен «функционал в планах» и легко восстанавливается.

#### Changed
- **`frontend/app/pages/install.client.vue`** — закомментирован install-шаг `userFields`, регистрировавший пользовательский тип `project_finance_embed_{dev|prod}` (вкладка «Финансы проекта (сделка)» → `/handler/placement-crm-deal-detail-tab`). Новые установки больше не показывают finance-встройку в карточке сделки.
- **`frontend/app/pages/handler/placement-crm-deal-detail-tab.client.vue`** (это **finance-only** таб целиком) — добавлен флаг `FINANCE_FEATURE_ENABLED = false`. При `false`: `onMounted` инициализирует B24-фрейм, но пропускает finance-загрузку (`getFinanceOperations`/`getProjectBoard`/`getConfiguration`) и показывает заглушку «Функционал в разработке»; форма и список операций (`v-else`) не рендерятся. Существующие установки (где встройка уже зарегистрирована) открывают эту заглушку без сетевых finance-вызовов. Восстановление — флаг в `true` + раскомментировать шаг `userFields`.
- **`frontend/app/stores/api.ts`** — методы `getFinanceOperations`, `createFinanceOperation` (`/api/finance-operations[/create]`), `runProjectBudgetNotifier` (`/api/project-budget/notify`), `getFinanceSpaValidation` (`/api/finance-spa/validation`) помечены как недоступные: тело-заглушка бросает понятную ошибку *до* любого `$api`-вызова, оригинальное тело сохранено в комментарии для восстановления. Сигнатуры и записи в возвращаемом объекте стора оставлены (типы и ссылки не ломаются).

#### Verification
- `nuxt prepare` — без ошибок (предсуществующие warnings про `useAppConfig` не связаны с правкой).
- `grep` по `app/`: активных `$api(...)`-вызовов к finance-эндпоинтам — нет; регистрация `project_finance_embed` присутствует только в комментариях. Вызовы `apiStore.getFinanceOperations/createFinanceOperation` остаются лишь внутри незапускаемых (за флагом) функций страницы и дополнительно защищены throw-заглушкой в сторе.
- Типы (`FinanceOperationRecord`, `FinanceOperationsResponse`, `FinanceOperationCreatePayload`, `FinanceSpaValidationPayload`, `ProjectFinanceOperationRecord`) оставлены без изменений — вызовов не делают, сборку не ломают.
- Доска проектов: секция `recent_finance_operations` в `ProjectBoardDrawer.vue` читает данные из активного `/api/project-board` (отдельного finance-вызова нет) и при отсутствии данных деградирует штатно — оставлена без изменений.
- Тесты фронта (`npm test`) сейчас падают на уровне окружения (`Cannot find package 'tsx'`) — предсуществующая проблема тулинга, не связана с этой правкой.
- ⏳ Осталось: e2e на запущенном приложении (открытие вкладки в карточке сделки → видна заглушка, в Network нет запросов к finance-эндпоинтам).

### Спринт 2 — ИНН в карточках списания (Этап C: авто-простановка при синхронизации) — 2026-05-31

#### Added
- `InnBackfillService.autofill(cards_info)` — резолвит ИНН из проекта для новых карточек и пишет его (лимит `AUTOFILL_LIMIT=30` за синк, остальное — через UI).
- `timesheet_sync_service.py`: `_save_batch` возвращает список новых карточек, `sync_all` их аккумулирует и после синка вызывает `_autofill_inn` (изолировано в `try/except` — ошибки авто-простановки не валят синхронизацию).
- Тест `test_autofill_resolves_and_writes` (всего 10 тестов).

#### Verification
- `py_compile` чист; `unittest main.tests_inn_backfill` — **10/10 OK**; `django check` — no issues.

### Спринт 2 — ИНН: правки по code-review (Этапы A+B) — 2026-05-31

#### Fixed
- **M1** — `apply` защищён лимитом `MAX_APPLY_BATCH=100`; фронт шлёт чанками по 25 с прогрессом (защита от таймаута и частичной записи на больших объёмах).
- **M2** — при недоступности реквизитов (пустой резолв ИНН при наличии проектов) `scan` возвращает `warning`; фронт показывает предупреждение.
- **m2** — группировка `scan` по `project_id` вместо имени (одноимённые проекты не схлопываются; фронт `:key="group.key"`).
- **m3** — убран режим exclude фильтра проектов (только include — устранено расхождение UI/бэка).
- **m1** — точный `except` при парсинге JSON в `inn_backfill_apply`.
- **m5** — уточнена подпись KPI «Без ИНН» («хотя бы одно поле пусто»); **n1** — docstring (`ProjectCardService`).
- **n4** — добавлены тесты на `scan` (группировка/KPI/статусы) и лимит `apply`.

#### Verification
- `py_compile` чист; `unittest main.tests_inn_backfill` — **9/9 OK**; `django check` — no issues; `nuxt prepare` — без ошибок.

### Спринт 2 — ИНН в карточках списания (Этап B: фронт UI) — 2026-05-31

#### Added
- **`frontend/app/components/reports/InnBackfillPanel.vue`** — экран дозаполнения: фильтры (период/проекты), KPI (`ReportMetricCard`), таблица с группировкой по проекту, чекбоксы массового выбора, ручной ввод для проблемных карточек, действия «Заполнить всё возможное» / «заполнить проект» / «Проставить выбранным».
- `frontend/app/types/inn.ts` — типы scan/apply.
- `frontend/app/stores/api.ts` — методы `scanInnBackfill` (GET) и `applyInnBackfill` (POST, JWT).
- `frontend/app/pages/reports/raw-data.client.vue` — вкладки «Выгрузка» / «Дозаполнение ИНН» (ручной таб-свитчер, готового `B24Tabs` в проекте нет).

#### Verification
- `nuxt prepare` без ошибок; eslint по изменённым `utils`/`composables` чист.
- ⏳ Осталось: e2e на запущенном приложении (вид вкладки, scan/apply против реального Bitrix).
- Примечание: scan использует выбранные проекты как include-фильтр (режим exclude в MVP не учитывается).

### Спринт 2 — ИНН в карточках списания (Этап A: бэк-ядро) — 2026-05-31

#### Added
- **`backends/python/api/main/inn_backfill_service.py`** — сервис дозаполнения ИНН:
  - `scan(date_from, date_to, project_ids)` — читает карточки списания из Bitrix, отбирает с пустыми `OUR_INN`/`CLIENT_INN`, резолвит проект → ИНН (клиент ← `company_id`, наш ← `our_legal_entity_id`), группирует по проекту, считает KPI и статусы строк (`ready`/`attention`/`no_project`).
  - `apply(items)` — пишет ИНН в Bitrix (`crm.item.update`, throttle 0.5с), только непустые значения.
  - Переиспортует `ProjectCardService.get_companies()/get_legal_entities()` и `get_project_card_queryset`.
- Endpoints `GET /api/inn-backfill/scan`, `POST /api/inn-backfill/apply` (JWT) — `views.py`, роуты в `urls.py`.
- Тесты `main/tests_inn_backfill.py` — 6 шт (чистые функции резолва/классификации + `apply` с моком клиента). Все зелёные.

#### Fixed (разблокировка запуска приложения)
- Изолирован **финансовый функционал (в планах)**: в `urls.py` закомментированы 4 роута, ссылавшихся на отсутствующие в `views.py` views (`get_finance_operations`, `create_finance_operation`, `run_project_budget_notifier`, `get_finance_spa_validation`) — следствие merge `d8a6a16`. Теперь urlconf собирается, `django check` — без ошибок, приложение стартует.
- Фронтовая часть finance (placement-виджет `placement-crm-deal-detail-tab.client.vue` + методы `api.ts`) — вынесена отдельной задачей для чистой изоляции (не мешает основному приложению).

#### Verification
- `py_compile` чист; `python -m unittest main.tests_inn_backfill` — 6/6 OK; новые views доступны как атрибуты модуля.
- `django check` — System check identified no issues (после изоляции finance).

### Спринт 1 — Отчёт «Учет по проектам/задачам»: редизайн + структурный Excel — 2026-05-31

#### Added
- **Серверная выгрузка в Excel с сохранением иерархии** (openpyxl):
  - endpoint `GET /api/report-project-task-employee-export` (`backends/python/api/main/views.py` → `report_project_task_employee_export`, JWT через `@auth_required`);
  - модуль-генератор `backends/python/api/main/report_excel.py` (`build_project_task_workbook`): объединённая шапка с периодом, заливки и отступы по уровням, outline-группировка (сворачивание), числа в формате «0.0», строка ИТОГО, закрепление заголовков.
- **KPI-карточки** на странице отчёта: Всего часов / Учтено / Не учтено / % учтённости (`ReportMetricCard`).
- Новые компоненты: `frontend/app/components/reports/ProjectTaskReportTable.vue`, `ProjectTaskReportRow.vue` (рекурсивная строка узла), `ProjectTaskReportEmployeeRow.vue`.
- Утилита форматирования `frontend/app/utils/reportFormat.ts` (`formatHours`, `formatPercent`, `formatReportDate`, русская локаль).
- HTML-мокапы дизайна и структуры выгрузки: `docs/internal/mockups/reports/01-project-task-page.html`, `02-project-task-excel.html`.

#### Changed
- Страница `frontend/app/pages/reports/project-task.client.vue` переведена на единый стиль отчётов (классы `ms-*`, шапка/фильтры/состояния как в `project.client.vue`); самопальная `div`-таблица заменена на переиспользуемые компоненты.
- Экспорт Excel переключён с фронтового (`xlsx`, плоская таблица с отступами-пробелами) на серверный структурный (`handleExportExcel` теперь качает blob с бэка).
- `frontend/app/stores/api.ts`: добавлен метод `exportReportProjectTaskEmployee` (GET + `responseType: 'blob'`).

#### Fixed (по итогам code-review)
- Восстановлена **кликабельность меток времени** (открытие карточки CRM по `id_elem` при включённой настройке `clickableLabelsEnabled`) — потерянная при редизайне. Реализована через `provide/inject` (`composables/useProjectTaskLabel.ts`), без prop-drilling сквозь рекурсию; в тип `ProjectTaskReportItem` добавлено поле `id_elem`.
- Удалён мёртвый код фронтового экспорта project-task в `utils/reportExport.ts` (`exportProjectTaskReportToXlsx` и хелперы).
- Формат даты в Excel приведён к `ДД.ММ.ГГГГ` (как на экране).
- `handleExportExcel` не сохраняет JSON-ошибку как `.xlsx` (проверка `blob.type`).
- Кнопка «Скачать Excel» заблокирована до успешной генерации отчёта.

#### Verification
- Фронт: `nuxt prepare` без ошибок; eslint по изменённым `utils`/`composables` чист (24 предсуществующие ошибки — в нетронутых файлах `iframe-resizer.ts`/`openCrmItem.ts`/`openProjectGroup.ts`).
- Бэк: `py_compile` чист; smoke-тесты `build_project_task_workbook` (пустые данные, данные с `id_elem`) и `_format_iso_date` — проходят, xlsx валиден (сигнатура `PK`).
- ⏳ Осталось: e2e-проверка на запущенном приложении (визуальный вид страницы + открытие файла в Excel).
