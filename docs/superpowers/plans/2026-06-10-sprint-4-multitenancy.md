# Спринт 4 «Перестройка мультитенантности (одна компания — одно хранилище)» — план исполнения

> Исполнение: волны параллельных агентов; файлы внутри одной волны не пересекаются. Фиксации (commit) делает оркестратор после проверки каждой задачи. Ветка: `sprint-4-multitenancy` (от `prod_2026`, спринты 1-3 безопасности/надёжности/UI влиты). **КОД В РАМКАХ НАПИСАНИЯ ПЛАНА НЕ МЕНЯЕТСЯ** — это документ для последующего исполнения. Детализирует утверждённый проект `docs/architecture/multitenancy-redesign-spec.md` (этапы 0-4 expand/contract) в исполняемые шаги с полным кодом, миграциями и тестами.
>
> **План разделён на ДВЕ части.** **ЧАСТЬ A** (этапы 0-3) выполняется в спринте 4: всё обратимо, тестируется на sqlite, прод-данные НЕ трогаются, поведение при выключенном флаге БИТ-в-БИТ как сейчас. **ЧАСТЬ B** (этап 4, contract) в спринте 4 **НЕ выполняется** — миграция написана как код, но это ТОЧКА НЕВОЗВРАТА, применяется на проде только после прогона всей Части A на копии боевой БД, проверки эквивалентности отчётов и явного решения заказчика. Прод-копию создаёт заказчик на своей инфраструктуре (см. Часть B).

## Цель

Перевести хранение данных с модели «одна копия на каждого пользователя портала» на модель «одна копия на компанию (portal/member_id)», устранив дублирование (на проде 131 аккаунт против 229 проектов — данные раздуты и два руководителя одной компании видят разные отчёты), но сделать это **обратимо и поэтапно**, без простоя и без риска для боевых данных. В спринте 4 мы вводим модель `Portal` (tenant-ключ `member_id`), добавляем нуллевые FK `portal` к трём моделям, наполняем их идемпотентным batched-backfill, пишем выверенную команду дедупликации с dry-run, и переводим все ~24 точки скоупинга на portal через флаг `USE_PORTAL_SCOPING` с фолбэком на account — так что при выключенном флаге (дефолт) приложение работает в точности как сегодня, а при включённом читает/пишет по компании. Финальное сжатие схемы (NOT NULL, portal-уникальность, снятие старых ограничений, удаление сирот) — это этап 4, который в спринте 4 только проектируется как код и процедура прод-выката, а исполняется заказчиком на копии прода после проверки эквивалентности.

## Подход (3 предложения)

Мы строго следуем expand/contract: сначала расширяем схему **аддитивно** (новая таблица `portal` + нуллевые внешние ключи + data-migration «один Portal на member_id»), потом наполняем эти ключи отдельными идемпотентными командами батчами по образцу `_save_batch` из `timesheet_sync_service.py` (а не одной миграцией — на 103k+ записях это операция осознанного запуска, не авто-применение при деплое), и только затем вводим переключатель чтения/записи. Переключение делаем через единый помощник `scope_to_tenant(account)` (модуль `tenant_scoping.py`), который при `USE_PORTAL_SCOPING=False` или пустом `portal` возвращает `{"bitrix24_account": account}` (текущее поведение, БИТ-в-БИТ), а при включённом флаге и заполненном `portal` — `{"portal": account.portal}`; все 24 точки скоупинга заменяют литерал `bitrix24_account=...` на `**scope_to_tenant(...)`, при этом точки, пишущие в `RequestLog`/`SystemLog` (аудит «кто принёс запись»), сознательно НЕ трогаем — они остаются на `bitrix24_account`. Дедупликацию изолируем в команду `dedupe_portal_data` с обязательным dry-run по умолчанию (считает и печатает отчёт, ничего не удаляет) и выбором «правильной» копии по детерминированному правилу (мастер-аккаунт портала, при равенстве — копия с максимумом данных/свежести), а корректность проверяем тестом эквивалентности отчётов на sqlite (одинаковый результат с флагом и без на тех же данных) и обязательно сохраняем зелёными существующие 148 тестов; всё, что касается поведения unique-constraint на больших данных и блокировок Postgres, проверяется ТОЛЬКО на копии прода в рамках Части B.

## Волны и непересечение файлов (ЧАСТЬ A)

Часть A — почти целиком бэкенд (модель, миграции, команды, помощник скоупинга, тесты). Главный источник пересечения — `models.py` (его трогает этап 0) и десять сервис-модулей с точками скоупинга (их трогает этап 3). Поэтому **этап 0 идёт первой волной в одиночку** (он создаёт модель и миграции, от которых зависят все остальные), а этапы 1-2 (команды backfill/dedupe — новые файлы) параллелятся между собой во второй волне. Этап 3 (перевод 10 сервис-модулей на `scope_to_tenant`) разбит на под-волны по непересекающимся группам файлов. Тесты каждого этапа лежат в собственных новых тест-модулях.

| Волна | Задачи (параллельно) | Файлы записи (Create/Modify) |
|---|---|---|
| 1 | **4.0** Модель `Portal` + нуллевые FK + миграция + data-migration «один Portal на member_id» | 4.0: `backends/python/api/main/models.py` (Modify), `main/migrations/0014_portal_and_nullable_fk.py` (new), `main/migrations/0015_seed_portals_from_member_id.py` (new, data-migration), `main/tests_portal_model.py` (new) |
| 2 | **4.1** Команда `backfill_portal_links`; **4.2** Команда `dedupe_portal_data` (dry-run) | 4.1: `main/management/commands/backfill_portal_links.py` (new), `main/portal_backfill_service.py` (new), `main/tests_portal_backfill.py` (new) · 4.2: `main/management/commands/dedupe_portal_data.py` (new), `main/portal_dedupe_service.py` (new), `main/tests_portal_dedupe.py` (new) |
| 3 | **4.3-helper** Помощник `scope_to_tenant` + флаг `USE_PORTAL_SCOPING` | 4.3-helper: `main/tenant_scoping.py` (new), `backends/python/api/settings.py` (Modify — чтение env-флага), `main/tests_tenant_scoping.py` (new) |
| 4 | **4.3-reads-a** report_queries + project_board_shared; **4.3-reads-b** project_board_service + project_budget_service; **4.3-views** views.py reads | 4.3-reads-a: `main/report_queries.py`, `main/project_board_shared.py` · 4.3-reads-b: `main/project_board_service.py`, `main/project_budget_service.py` · 4.3-views: `main/views.py` |
| 5 | **4.3-sync-ts** timesheet_sync_service; **4.3-sync-proj** project_sync_service; **4.3-lock** account_sync_lock → portal-ключ | 4.3-sync-ts: `main/timesheet_sync_service.py` · 4.3-sync-proj: `main/project_sync_service.py` · 4.3-lock: `main/utils/decorators/sync_lock.py`, `main/sync_scheduler_service.py` |
| 6 | **4.4** Тест эквивалентности отчётов (с флагом и без) | 4.4: `main/tests_portal_scoping_equivalence.py` (new) |
| 7 | **4.5** Ревизия Части A | без правок (чтение + полный прогон) |

**Доказательство непересечения по волнам:**
- **Волна 1 (одна задача 4.0):** один writer на `models.py` и две новые миграции + новый тест. Пересечений нет по определению.
- **Волна 2:** 4.1 пишет `backfill_portal_links.py` + `portal_backfill_service.py` + `tests_portal_backfill.py`; 4.2 пишет `dedupe_portal_data.py` + `portal_dedupe_service.py` + `tests_portal_dedupe.py`. Шесть новых непересекающихся файлов; оба только читают `models.py` (уже стабилен после волны 1), не пишут его.
- **Волна 3 (одна задача):** 4.3-helper пишет новый `tenant_scoping.py`, новый тест и точечно `settings.py` (одна вставка чтения env). Никто другой в волне 3 `settings.py` не трогает.
- **Волна 4:** три непересекающихся набора: {`report_queries.py`, `project_board_shared.py`} ∩ {`project_board_service.py`, `project_budget_service.py`} ∩ {`views.py`} = ∅. Все импортируют `scope_to_tenant` из `tenant_scoping.py` (стабилен после волны 3), но его НЕ пишут.
- **Волна 5:** три непересекающихся набора: {`timesheet_sync_service.py`} ∩ {`project_sync_service.py`} ∩ {`sync_lock.py`, `sync_scheduler_service.py`} = ∅.
- **Волна 6 (одна задача):** 4.4 — только новый тест-модуль `tests_portal_scoping_equivalence.py`.
- **Волна 7:** 4.5 — без правок.

**Критические зависимости между волнами (сознательная сериализация, не пересечение в волне):**
1. **`models.py` (4.0) → всё остальное.** Модель `Portal` и FK `portal` нужны и командам (4.1/4.2), и помощнику (4.3-helper использует `account.portal`), и тестам. Поэтому 4.0 — строго волна 1, одна.
2. **`tenant_scoping.py` (4.3-helper, волна 3) → все точки скоупинга (волны 4-5).** Помощник `scope_to_tenant` определяется в волне 3; волны 4-5 его только импортируют и применяют. Это разводит запись помощника и запись точек по разным волнам.
3. **`backfill_portal_links` (4.1) → `dedupe_portal_data` (4.2) по СМЫСЛУ, но не по файлам.** Дедуп логически выполняется ПОСЛЕ backfill (нужны заполненные `portal`), но они пишут разные файлы, поэтому параллелятся в волне 2 без конфликта; порядок запуска (сначала backfill, потом dedupe) фиксируется в командах через предохранитель (dedupe отказывается работать, если есть записи с пустым `portal` — см. карточку 4.2) и в процедуре прод-выката (Часть B).
4. **`migrations/0013_syncrun` — последняя существующая.** Новые миграции спринта 4: `0014` (Portal + nullable FK), `0015` (seed Portal из member_id, data-migration). Этап 4 (Часть B) добавит `0016` (contract), но он в спринте 4 НЕ применяется (см. Часть B).
5. **4.4 (эквивалентность) → после волн 4-5.** Тест эквивалентности сравнивает отчёты с флагом и без; имеет смысл только когда все точки скоупинга уже переведены (волны 4-5). Поэтому 4.4 — волна 6.

## Как запускать тесты / проверки (обязательно к прочтению исполнителями)

- **Django-тесты (sqlite):** `cd backends/python/api && ./.venv/bin/python manage.py test main.<модуль> --settings=test_settings`. Python и Django в `backends/python/api/.venv` (Python 3.9.6, Django 4.2.29). База тестов — sqlite (`test_settings.py`: `ENGINE django.db.backends.sqlite3`, `NAME BASE_DIR/test.sqlite3`). Все новые тест-модули спринта 4 (`tests_portal_model`, `tests_portal_backfill`, `tests_portal_dedupe`, `tests_tenant_scoping`, `tests_portal_scoping_equivalence`) пишем как Django-`TestCase` **без** `sys.modules`-заглушек и **без** `django.setup()` на верхнем уровне — тогда они запускаются через `manage.py test`.
- **Как распознать «автономный» (sys.modules) тест — ВАЖНАЯ ОГОВОРКА.** Команда `grep -l "sys.modules" main/tests_*.py` даёт **ложноположительное** срабатывание на `tests_scheduled_sync.py`, потому что в его докстринге есть слова «БЕЗ sys.modules/django.setup()» — сам модуль чистый Django-`TestCase`. Поэтому проверять надо паттерн фактического присвоения, а не подстроку: `grep -n "sys\.modules\[" main/tests_*.py` (с открывающей скобкой). Истинно автономные (подменяют `sys.modules[...]` на верхнем уровне): `tests_fetch_paginated_batch`, `tests_project_fetch_keyset`, `tests_sync_scoped`, `tests_inn_apply_batch`, `tests_sync_integration`. Их запускать ТОЛЬКО через `cd backends/python && api/.venv/bin/python -m unittest api.main.<модуль>` и НИКОГДА через `manage.py test`. Новые модули спринта 4 в это семейство НЕ входят — они Django-`TestCase`.
- **База регресса:** `main.tests_reports` — **41 тест, 2 ИЗВЕСТНЫЕ ошибки** в `FinanceOperationServiceTest` (finance отключён флагом; существовали до спринта 4 — НЕ чинить, новых ошибок не добавлять). Полный регресс существующих 148 тестов спринтов 1-3 НЕ ломать. Контракты, которые НЕЛЬЗЯ ломать (проверены в `tests_reports`): `test_sync_endpoint_returns_warning_instead_of_500`, `test_project_board_sync_endpoint_returns_warning_instead_of_500`, `test_timesheet_filters_use_date_range_and_exclude_archived_projects`, `test_timesheet_sync_save_batch_updates_and_creates_records`.
- **Главный инвариант спринта 4 (проверяется в каждом прогоне волн 4-5):** при `USE_PORTAL_SCOPING=False` (дефолт) ВСЕ существующие тесты зелёные без изменений — это и есть доказательство «БИТ-в-БИТ как сейчас». Тесты спринта 4 (`tests_portal_*`), которым нужен включённый флаг, переключают его через `@override_settings(USE_PORTAL_SCOPING=True)` ВНУТРИ теста, а не глобально.
- **БД тестов — sqlite, прод — Postgres (КРИТИЧНО для этапа 4).** Логику (создание Portal, дедуп по member_id, идемпотентность backfill, корректность выбора копии, dry-run, эквивалентность отчётов) покрываем на sqlite. **НО:** добавление уникального индекса `(portal, bitrix_id)` / `(portal, project_id)` на остаточных дублях (этап 4, Часть B) **упадёт** и на sqlite, и на Postgres — поэтому дедуп ОБЯЗАН пройти до этапа 4. На sqlite это можно проверить только синтетически (создать дубли → убедиться, что миграция 0016 падает; запустить dedupe → убедиться, что проходит). Поведение unique-constraint на **больших** данных, длительность и блокировки Postgres проверяются ТОЛЬКО на копии прода (Часть B) — sqlite этого не воспроизводит (он однопоточный, без advisory-lock — `account_sync_lock` на sqlite no-op, gate `connection.vendor != "postgresql"`).
- **Миграции:** последняя существующая — `0013_syncrun`. Новые Части A: `0014_portal_and_nullable_fk` (структура), `0015_seed_portals_from_member_id` (data-migration). Часть B: `0016_portal_contract` (НЕ применяется в спринте 4). На проде миграции применяются ОТДЕЛЬНЫМ release-шагом (`python manage.py migrate --noinput`); `start.sh` миграции НЕ запускает. Команды backfill/dedupe — **НЕ** миграции, запускаются осознанно (`python manage.py backfill_portal_links`, `python manage.py dedupe_portal_data`).
- **Docker НЕ запущен.** PostgreSQL в тест-окружение НЕ вводить. Прод-копию создать в этой среде нельзя — это операция заказчика на его инфраструктуре (Timeweb); см. Часть B. Путь проекта содержит пробелы и кириллицу — экранировать кавычками.

**Инвентарь фактических схем (проверено чтением `backends/python/api/main/models.py`):**
- **`Bitrix24Account`** (`db_table="bitrix24account"`): `id` = UUIDField (PK), `b24_user_id` IntegerField, `member_id` CharField(255) — **НЕ unique**, `is_master_account` BooleanField(null=True), `domain_url` CharField(255), `status` CharField(50), OAuth-поля. `unique_together = ("b24_user_id", "domain_url")` — одна строка на пользователя портала. **Важно:** `member_id` НЕ уникален, у одной компании несколько аккаунтов с одинаковым `member_id`.
- **`TimesheetItem`** (`db_table="timesheet_item"`): `bitrix24_account` FK (CASCADE, related_name="timesheets"), `bitrix_id` IntegerField(db_index), `unique_together = ("bitrix24_account", "bitrix_id")`. Пять составных индексов начинаются с `bitrix24_account` (`timesheet_acc_date_idx` и др.).
- **`ProjectCard`** (`db_table="project_card"`): `bitrix24_account` FK (CASCADE, related_name="project_cards"), `project_id` CharField(db_index), `project_item_id` CharField(null, db_index), `unique_together = (("bitrix24_account", "project_id"), ("bitrix24_account", "project_item_id"))`.
- **`RequestLog`/`SystemLog`:** имеют `bitrix24_account` FK (SET_NULL, related_name="+") как **аудит-поле** «кто породил запись/лог» — это НЕ tenant-скоупинг данных, в спринте 4 НЕ переводится на portal.
- **`SyncRun`** (спринт 3): журнал запусков фонового синка; FK на аккаунт НЕТ; на portal-перевод не влияет (см. совместимость в карточке 4.3-lock).

**Инвентарь 25 точек `bitrix24_account=` (греп `grep -rn "bitrix24_account=" main/*.py | grep -v tests_`) с классификацией:**

Каждая точка отнесена к одному из трёх классов: **[DATA-READ]** — фильтр чтения `TimesheetItem`/`ProjectCard`, переводится на portal; **[DATA-WRITE]** — создание/синк/удаление `TimesheetItem`/`ProjectCard`, переводится на portal; **[AUDIT]** — запись `RequestLog`/`SystemLog` или конструктор сервиса, НЕ переводится (остаётся на `bitrix24_account`).

| # | Файл:строка | Класс | Контекст | Перевод |
|---|---|---|---|---|
| 1 | `configuration_service.py:16` | **[AUDIT/SKIP]** | параметр конструктора `def __init__(self, client, bitrix24_account=None)` — это имя аргумента, НЕ ORM-фильтр | НЕ трогать (не фильтр) |
| 2 | `middleware.py:122` | **[AUDIT]** | `RequestLog.objects.create(..., bitrix24_account=getattr(request,"bitrix24_account",None))` | НЕ трогать (аудит «кто») |
| 3 | `project_board_shared.py:161` | **[DATA-READ]** | `ProjectCard.objects.filter(bitrix24_account=account)` в `get_project_card_queryset(account)` | `**scope_to_tenant(account)` |
| 4 | `project_board_shared.py:166` | **[DATA-READ]** | `TimesheetItem.objects.filter(bitrix24_account=account)` в `build_local_project_groups(account)` | `**scope_to_tenant(account)` |
| 5 | `project_budget_notifier.py:281` | **[AUDIT]** | `SystemLog.objects.create(..., bitrix24_account=self.account)` | НЕ трогать (аудит) |
| 6 | `project_budget_service.py:50` | **[DATA-READ]** | `TimesheetItem.objects.filter(bitrix24_account=self.account)` в `_collect_timesheet_aggregates` | `**scope_to_tenant(self.account)` |
| 7 | `report_queries.py:29` | **[DATA-READ]** | `TimesheetItem.objects.filter(bitrix24_account=account)` в `build_filtered_timesheet_queryset(account, params)` — ядро всех отчётов | `**scope_to_tenant(account)` |
| 8 | `project_board_service.py:521` | **[DATA-READ]** | `TimesheetItem...filter(bitrix24_account=self.account)` в `collect_writeoff_maps` (by item) | `**scope_to_tenant(self.account)` |
| 9 | `project_board_service.py:539` | **[DATA-READ]** | то же, by project_id | `**scope_to_tenant(self.account)` |
| 10 | `project_board_service.py:551` | **[DATA-READ]** | то же, by project_title | `**scope_to_tenant(self.account)` |
| 11 | `project_board_service.py:1047` | **[DATA-READ]** | `TimesheetItem...filter(bitrix24_account=self.account, date_reflection__gte=...)` в `_get_revenue_leakage_rows` | `**scope_to_tenant(self.account)` + остальные kwargs |
| 12 | `project_board_service.py:1239` | **[AUDIT]** | `SystemLog.objects.create(..., bitrix24_account=self.account)` | НЕ трогать (аудит) |
| 13 | `project_board_service.py:1245` | **[DATA-READ]** | `ProjectCard.objects.get(bitrix24_account=self.account, project_id=...)` в `_get_card` | `**scope_to_tenant(self.account)` + `project_id=...` |
| 14 | `project_sync_service.py:166` | **[DATA-WRITE]** | `ProjectCard.objects.create(bitrix24_account=self.account, ...)` (создание карточки группы) | `**scope_to_tenant(self.account, write=True)` |
| 15 | `project_sync_service.py:281` | **[DATA-WRITE]** | `ProjectCard.objects.create(bitrix24_account=self.account, ...)` (создание карточки SP-элемента) | `**scope_to_tenant(self.account, write=True)` |
| 16 | `project_sync_service.py:570` | **[DATA-READ]** | `TimesheetItem...filter(bitrix24_account=self.account).filter(...)` (поиск несвязанных) | `**scope_to_tenant(self.account)` |
| 17 | `views.py:153` | **[DATA-READ]** | `TimesheetItem.objects.filter(bitrix24_account=request.bitrix24_account)` в `_build_project_filter_options` | `**scope_to_tenant(request.bitrix24_account)` |
| 18 | `views.py:1492` | **[DATA-READ]** | `TimesheetItem...filter(bitrix24_account=request.bitrix24_account)` в `timesheet_list` | `**scope_to_tenant(request.bitrix24_account)` |
| 19 | `views.py:1860` | **[AUDIT]** | `RequestLog.objects.filter(bitrix24_account=request.bitrix24_account)` (просмотр логов запросов) | НЕ трогать (аудит «кто») |
| 20 | `views.py:1894` | **[AUDIT]** | `SystemLog.objects.filter(bitrix24_account=request.bitrix24_account)` (просмотр системных логов) | НЕ трогать (аудит «кто») |
| 21 | `timesheet_sync_service.py:182` | **[DATA-WRITE]** | `TimesheetItem...filter(bitrix24_account=self.account).count()` (счёт для orphan-deletion, полный синк) | `**scope_to_tenant(self.account, write=True)` |
| 22 | `timesheet_sync_service.py:192` | **[DATA-WRITE]** | `TimesheetItem...filter(bitrix24_account=self.account).exclude(...).delete()` (orphan-deletion полный) | `**scope_to_tenant(self.account, write=True)` |
| 23 | `timesheet_sync_service.py:381` | **[DATA-WRITE]** | `TimesheetItem...filter(bitrix24_account=self.account, date_reflection__date__gte=...)...delete()` (orphan scoped) | `**scope_to_tenant(self.account, write=True)` + остальные kwargs |
| 24 | `timesheet_sync_service.py:453` | **[DATA-WRITE]** | `TimesheetItem...filter(bitrix24_account=self.account, bitrix_id__in=bitrix_ids)` (upsert lookup в `_save_batch`) | `**scope_to_tenant(self.account, write=True)` + `bitrix_id__in=...` |
| 25 | `timesheet_sync_service.py:465` | **[DATA-WRITE]** | `TimesheetItem(bitrix24_account=self.account, bitrix_id=..., **defaults)` (создание в `_save_batch`) | см. карточку 4.3-sync-ts (создание объекта, не filter) |

**Итог классификации:** **[DATA-READ]** — 12 точек (3,4,6,7,8,9,10,11,13,16,17,18); **[DATA-WRITE]** — 6 точек (14,15,21,22,23,24) + точка 25 (создание объекта); **[AUDIT/SKIP]** — 6 точек (1,2,5,12,19,20). Переводу на portal подлежат 12 read + 7 write = 19 точек в 7 файлах (`report_queries.py`, `project_board_shared.py`, `project_budget_service.py`, `project_board_service.py`, `project_sync_service.py`, `timesheet_sync_service.py`, `views.py`). Шесть AUDIT-точек остаются на `bitrix24_account` — это сознательное решение (логи и аудит привязаны к пользователю-источнику, не к компании; см. открытый вопрос 3).

---

# ЧАСТЬ A — выполняется в спринте 4

> Всё в Части A обратимо, тестируется на sqlite, прод-данные НЕ трогаются. При `USE_PORTAL_SCOPING=False` (дефолт) поведение БИТ-в-БИТ как сегодня.

## Задача 4.0 — Модель `Portal` + нуллевые FK + миграция + seed-data-migration [опус — архитектурное ядро]

**Файлы:** Modify `backends/python/api/main/models.py` (новая модель `Portal` после `Bitrix24Account`; FK `portal` к `Bitrix24Account`, `TimesheetItem`, `ProjectCard`); Create `main/migrations/0014_portal_and_nullable_fk.py`; Create `main/migrations/0015_seed_portals_from_member_id.py` (data-migration); Create `main/tests_portal_model.py`.

**Дыра (проверено чтением `models.py`).** `member_id` (стр. 23) — обычный `CharField`, не tenant-ключ, не уникален. Несколько `Bitrix24Account` одной компании имеют одинаковый `member_id`, но данные (`TimesheetItem`/`ProjectCard`) привязаны к конкретному аккаунту. Нет сущности, представляющей «компанию целиком».

**Решение (аддитивно, обратимо — этап 0 expand).**
- Ввести модель `Portal` с `member_id` как `unique=True` — общие данные портала: домен (последний известный), статус, тайм-штампы. Это будущий tenant-ключ.
- Добавить **нуллевые** FK `portal` к `Bitrix24Account`, `TimesheetItem`, `ProjectCard`. `null=True, blank=True` — на этапе 0 они пустые; `on_delete=models.SET_NULL` для безопасности (удаление Portal не каскадит данные, пока идёт переезд; на этапе 4 политику можно ужесточить). НЕ менять существующие `unique_together` и существующий `bitrix24_account` FK — они остаются на месте, прод работает по-старому.
- Data-migration: для каждого **различного** `member_id` среди `Bitrix24Account` создать ровно один `Portal` (дедуп по `member_id`). Домен/статус взять у представителя (мастер-аккаунт, иначе любой). Идемпотентно (`get_or_create` по `member_id`). НЕ заполняет FK на этом этапе (это backfill, задача 4.1) — миграция 0015 только сеет таблицу `portal` и **проставляет `Bitrix24Account.portal`** (это дёшево — аккаунтов 131; данные не трогаются). FK у `TimesheetItem`/`ProjectCard` остаются пустыми до backfill.

> **Почему `Bitrix24Account.portal` проставляем прямо в миграции 0015, а `TimesheetItem`/`ProjectCard.portal` — отдельной командой 4.1?** Аккаунтов ~131 — это копеечная операция, безопасная в миграции. Данных 103k+ — их батчевый backfill нельзя гнать как авто-миграцию при деплое (долго, блокировки), поэтому он вынесен в осознанно запускаемую команду 4.1. Это соответствует спецификации (этап 0 — Portal + nullable FK; этап 1 — backfill данных).

**Шаг 1. Падающий тест** — Create `main/tests_portal_model.py` (Django-`TestCase`, sqlite, БЕЗ `django.setup()`):
```python
"""Тесты модели Portal и seed-миграции (задача 4.0)."""
from django.test import TestCase

from .models import Bitrix24Account, Portal


def _account(member_id, *, master=False, b24_user_id=1, domain=None, status="active"):
    return Bitrix24Account.objects.create(
        b24_user_id=b24_user_id,
        is_b24_user_admin=True,
        member_id=member_id,
        is_master_account=master,
        domain_url=domain or f"{member_id}.bitrix24.ru",
        status=status,
        application_version=1,
    )


class PortalModelTest(TestCase):
    def test_member_id_is_unique(self):
        Portal.objects.create(member_id="m1", domain_url="m1.bitrix24.ru", status="active")
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Portal.objects.create(member_id="m1", domain_url="dup.bitrix24.ru", status="active")

    def test_account_has_nullable_portal_fk_default_none(self):
        acc = _account("m2")
        # На этапе 0 FK ещё не заполнен напрямую при создании аккаунта.
        self.assertIsNone(acc.portal_id)

    def test_timesheet_and_card_have_nullable_portal_fk(self):
        # Поле существует и nullable: создаём запись БЕЗ portal — не падает.
        from .models import TimesheetItem, ProjectCard
        from django.utils import timezone
        acc = _account("m3")
        ts = TimesheetItem.objects.create(
            bitrix24_account=acc, bitrix_id=1, task_id="1", employee_id="1",
            hours=1.0, date_reflection=timezone.now(),
        )
        card = ProjectCard.objects.create(
            bitrix24_account=acc, project_id="100", project_name="P", stage="new",
        )
        self.assertIsNone(ts.portal_id)
        self.assertIsNone(card.portal_id)


class SeedPortalsMigrationTest(TestCase):
    """Проверяем эффект data-migration 0015 на «живых» данных.

    Тест-раннер применяет все миграции к sqlite, включая 0015, но 0015 видит
    пустую БД (фикстур ещё нет). Поэтому здесь воспроизводим её ЛОГИКУ через
    публичную функцию seed_portals_from_accounts (вынесена в migrations-helper
    и переиспользуется), чтобы протестировать дедуп по member_id и проставление
    Bitrix24Account.portal.
    """

    def test_one_portal_per_member_id_and_account_linked(self):
        from .portal_seed import seed_portals_from_accounts
        # Две учётки одной компании m1 + одна m2.
        a1 = _account("m1", master=True, b24_user_id=1, domain="m1.bitrix24.ru")
        a2 = _account("m1", master=False, b24_user_id=2, domain="m1.bitrix24.ru")
        a3 = _account("m2", master=True, b24_user_id=3, domain="m2.bitrix24.ru")

        created = seed_portals_from_accounts(Portal, Bitrix24Account)

        self.assertEqual(Portal.objects.count(), 2)  # по одному на member_id
        self.assertEqual(created, 2)
        # Повторный прогон идемпотентен — новых Portal нет.
        created_again = seed_portals_from_accounts(Portal, Bitrix24Account)
        self.assertEqual(created_again, 0)
        self.assertEqual(Portal.objects.count(), 2)

        for acc in (a1, a2, a3):
            acc.refresh_from_db()
            self.assertIsNotNone(acc.portal_id)
        a1.refresh_from_db(); a2.refresh_from_db()
        self.assertEqual(a1.portal_id, a2.portal_id)  # обе учётки m1 -> один Portal
        # Домен Portal m1 взят у мастер-аккаунта.
        p1 = Portal.objects.get(member_id="m1")
        self.assertEqual(p1.domain_url, "m1.bitrix24.ru")
```

**Шаг 2. Запуск (ожидание: FAIL).** `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_portal_model --settings=test_settings` — упадёт (`Portal`/`portal_seed`/FK `portal` ещё нет).

**Шаг 3. Реализация (ПОЛНЫЙ код).**

**Модель `Portal`** — добавить в `main/models.py` сразу после класса `Bitrix24Account` (до `ApplicationInstallation`):
```python
class Portal(models.Model):
    """Tenant-сущность «компания» (этап 0 перестройки мультитенантности, спринт 4).

    Один Portal на каждый member_id Битрикс24. Общие данные компании: домен,
    статус. Данные (TimesheetItem/ProjectCard) на этапе 4 скоупятся по этому
    Portal, а не по Bitrix24Account (per-user). Пока (этапы 0-3) FK portal на
    данных nullable и переключение чтения за флагом USE_PORTAL_SCOPING.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    member_id = models.CharField(max_length=255, unique=True)
    domain_url = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=50, default="active")
    created_at_utc = models.DateTimeField(auto_now_add=True)
    updated_at_utc = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = "portal"
        indexes = [
            models.Index(fields=["member_id"], name="portal_member_id_idx"),
        ]

    def __str__(self) -> str:
        return f"Portal<{self.member_id}>"
```

**FK `portal`** — добавить поле в три модели (НЕ менять существующие поля/`unique_together`):
- В `Bitrix24Account` (после `current_scope`, перед `class Meta`):
```python
    portal = models.ForeignKey(
        "Portal", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="accounts", db_index=True,
    )
```
- В `TimesheetItem` (после `bitrix24_account`):
```python
    portal = models.ForeignKey(
        "Portal", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="timesheets", db_index=True,
    )
```
- В `ProjectCard` (после `bitrix24_account`):
```python
    portal = models.ForeignKey(
        "Portal", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="project_cards", db_index=True,
    )
```

**Seed-хелпер** — Create `main/portal_seed.py` (выносим логику из миграции, чтобы её можно было тестировать и переиспользовать; миграция 0015 импортирует её через `apps.get_model`-совместимую сигнатуру — принимает классы моделей аргументами):
```python
"""Логика seed-миграции 0015 (этап 0): один Portal на member_id.

Вынесена сюда отдельной функцией, принимающей классы моделей, чтобы:
(1) тестировать на реальных моделях через manage.py test;
(2) вызывать из data-migration 0015 через historical-модели (apps.get_model).
Идемпотентна: повторный вызов не плодит Portal и не перетирает связи.
"""
from typing import Type


def seed_portals_from_accounts(portal_model: Type, account_model: Type) -> int:
    """Создаёт по одному Portal на каждый member_id и проставляет
    Bitrix24Account.portal. Возвращает число СОЗДАННЫХ Portal."""
    created = 0
    seen_member_ids = set(
        portal_model.objects.values_list("member_id", flat=True)
    )

    # Группируем аккаунты по member_id; мастер-аккаунт приоритетен как источник домена.
    accounts = list(
        account_model.objects.all().order_by("member_id", "-is_master_account", "b24_user_id")
    )
    portal_by_member = {}
    for acc in accounts:
        member_id = (acc.member_id or "").strip()
        if not member_id:
            continue
        portal = portal_by_member.get(member_id)
        if portal is None:
            if member_id in seen_member_ids:
                portal = portal_model.objects.get(member_id=member_id)
            else:
                portal = portal_model.objects.create(
                    member_id=member_id,
                    domain_url=acc.domain_url,   # первый в порядке = мастер (если есть)
                    status=acc.status or "active",
                )
                created += 1
                seen_member_ids.add(member_id)
            portal_by_member[member_id] = portal
        # Проставляем FK аккаунта, если ещё не проставлен.
        if acc.portal_id != portal.id:
            acc.portal_id = portal.id
            acc.save(update_fields=["portal"])
    return created
```

**Миграция структуры** — Create `main/migrations/0014_portal_and_nullable_fk.py`. Сгенерировать `./.venv/bin/python manage.py makemigrations main --name portal_and_nullable_fk`, затем СВЕРИТЬ, что она: (1) зависит от `0013_syncrun`; (2) создаёт модель `Portal` (таблица `portal`); (3) добавляет nullable FK `portal` к `bitrix24account`, `timesheet_item`, `project_card`; (4) НЕ меняет существующие `unique_together`/индексы. Имя файла — `0014_portal_and_nullable_fk.py`.

**Data-migration seed** — Create `main/migrations/0015_seed_portals_from_member_id.py` вручную:
```python
from django.db import migrations


def forwards(apps, schema_editor):
    Portal = apps.get_model("main", "Portal")
    Bitrix24Account = apps.get_model("main", "Bitrix24Account")
    # Импортируем логику из portal_seed; она работает с любыми классами моделей,
    # включая historical (apps.get_model). save(update_fields=["portal"]) валиден.
    from main.portal_seed import seed_portals_from_accounts
    seed_portals_from_accounts(Portal, Bitrix24Account)


def backwards(apps, schema_editor):
    # Обратимо: снимаем связь аккаунтов и удаляем все Portal.
    # (Данные TimesheetItem/ProjectCard на этапе 0 ещё не привязаны к Portal.)
    Portal = apps.get_model("main", "Portal")
    Bitrix24Account = apps.get_model("main", "Bitrix24Account")
    Bitrix24Account.objects.update(portal=None)
    Portal.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("main", "0014_portal_and_nullable_fk"),
    ]
    operations = [
        migrations.RunPython(forwards, backwards),
    ]
```
> **Сверка перед коммитом:** `seed_portals_from_accounts` вызывает `acc.save(update_fields=["portal"])`. У historical-модели `Bitrix24Account.__init__` переопределён в реальном коде (подключает сигналы b24pysdk), но historical-модель в миграции — это «голый» Django-класс БЕЗ кастомного `__init__`/`AbstractBitrixToken`, поэтому `save` отработает штатно. Если при прогоне `makemigrations`/`migrate` на sqlite возникнет ошибка из-за `update_fields`, заменить на `Bitrix24Account.objects.filter(pk=acc.pk).update(portal_id=portal.id)` (чистый UPDATE, без вызова save). Зафиксировать выбранный вариант в докладе.

**Шаг 4. Запуск (ожидание: PASS).**
- `./.venv/bin/python manage.py test main.tests_portal_model --settings=test_settings` → зелёные.
- Регресс: `./.venv/bin/python manage.py test main.tests_reports --settings=test_settings` → 41/2-известные (миграции 0014/0015 не ломают существующие модели — поля nullable, новые).
- Убедиться, что `./.venv/bin/python manage.py makemigrations main --check --dry-run --settings=test_settings` НЕ предлагает новых миграций (модель и миграции согласованы).

**Шаг 5. Доклад.** Введена модель `Portal` (`member_id` unique); добавлены nullable FK `portal` (SET_NULL) к `Bitrix24Account`/`TimesheetItem`/`ProjectCard` без изменения существующих ограничений; миграция 0014 (структура) + 0015 (seed: один Portal на member_id + проставление `Bitrix24Account.portal`, идемпотентно, обратимо). Логика seed вынесена в `portal_seed.seed_portals_from_accounts` и протестирована. Зафиксировать вариант сохранения FK аккаунта (`save(update_fields)` или `.update()`).

---

## Задача 4.1 — Команда backfill связей `portal` для данных [соннет]

**Файлы:** Create `main/management/commands/backfill_portal_links.py`; Create `main/portal_backfill_service.py` (батчевая логика); Create `main/tests_portal_backfill.py`.

**Дыра.** После задачи 4.0 `Bitrix24Account.portal` проставлен (миграцией 0015), но `TimesheetItem.portal` и `ProjectCard.portal` пусты (их 103k+ — в миграцию не выносим). Нужна осознанно запускаемая идемпотентная команда, которая проставит им `portal` от их `bitrix24_account`, батчами.

**Решение (этап 1 — backfill, идемпотентно, батчами).**
- Сервис `portal_backfill_service.backfill_portal_links(batch_size=2000)` проходит `TimesheetItem` и `ProjectCard`, у которых `portal_id IS NULL` и `bitrix24_account.portal_id IS NOT NULL`, и проставляет `portal_id = bitrix24_account.portal_id`. Идёт батчами через `.values_list("pk", "bitrix24_account__portal_id")` + `bulk_update`/прямой `UPDATE ... WHERE pk IN (...)`. По образцу батчинга `_save_batch` (атомарные батчи, без одного гигантского запроса — на 103k записях это держит память и блокировки под контролем).
- **Идемпотентность:** фильтр `portal__isnull=True` означает, что повторный запуск обрабатывает только незаполненные записи — второй прогон делает 0 изменений (проверяется тестом).
- Для аккаунтов с `portal_id IS NULL` (теоретически — если seed не покрыл, например аккаунт без member_id) их `TimesheetItem`/`ProjectCard` пропускаются (остаются с `portal=None`); команда печатает их число как «unlinked» (это сигнал к ручной проверке). Дедуп (4.2) и contract (этап 4) на такие записи не повлияют, пока у них нет portal.
- Команда принимает `--batch-size` (по умолчанию 2000) и печатает отчёт: сколько `TimesheetItem`/`ProjectCard` проставлено, сколько осталось без portal.

**Шаг 1. Падающий тест** — Create `main/tests_portal_backfill.py` (Django-`TestCase`):
```python
"""Тесты backfill связей portal (задача 4.1)."""
from django.test import TestCase
from django.utils import timezone

from .models import Bitrix24Account, Portal, TimesheetItem, ProjectCard
from .portal_backfill_service import backfill_portal_links


def _account_with_portal(member_id, *, b24_user_id=1):
    portal = Portal.objects.create(member_id=member_id, domain_url=f"{member_id}.b24.ru", status="active")
    acc = Bitrix24Account.objects.create(
        b24_user_id=b24_user_id, is_b24_user_admin=True, member_id=member_id,
        is_master_account=True, domain_url=f"{member_id}.b24.ru", status="active",
        application_version=1, portal=portal,
    )
    return acc, portal


class BackfillPortalLinksTest(TestCase):
    def test_backfills_timesheet_and_card_portal_from_account(self):
        acc, portal = _account_with_portal("m1")
        ts = TimesheetItem.objects.create(
            bitrix24_account=acc, bitrix_id=1, task_id="1", employee_id="1",
            hours=1.0, date_reflection=timezone.now(),
        )
        card = ProjectCard.objects.create(
            bitrix24_account=acc, project_id="100", project_name="P", stage="new",
        )
        self.assertIsNone(ts.portal_id)
        self.assertIsNone(card.portal_id)

        report = backfill_portal_links(batch_size=10)

        ts.refresh_from_db(); card.refresh_from_db()
        self.assertEqual(ts.portal_id, portal.id)
        self.assertEqual(card.portal_id, portal.id)
        self.assertEqual(report["timesheets_linked"], 1)
        self.assertEqual(report["cards_linked"], 1)
        self.assertEqual(report["timesheets_unlinked"], 0)

    def test_idempotent_second_run_changes_nothing(self):
        acc, portal = _account_with_portal("m1")
        TimesheetItem.objects.create(
            bitrix24_account=acc, bitrix_id=1, task_id="1", employee_id="1",
            hours=1.0, date_reflection=timezone.now(),
        )
        backfill_portal_links(batch_size=10)
        report2 = backfill_portal_links(batch_size=10)
        self.assertEqual(report2["timesheets_linked"], 0)
        self.assertEqual(report2["cards_linked"], 0)

    def test_account_without_portal_leaves_items_unlinked(self):
        # Аккаунт без portal (например без member_id в seed) -> items не привязываются.
        acc = Bitrix24Account.objects.create(
            b24_user_id=9, is_b24_user_admin=True, member_id="", is_master_account=True,
            domain_url="x.b24.ru", status="active", application_version=1, portal=None,
        )
        TimesheetItem.objects.create(
            bitrix24_account=acc, bitrix_id=1, task_id="1", employee_id="1",
            hours=1.0, date_reflection=timezone.now(),
        )
        report = backfill_portal_links(batch_size=10)
        self.assertEqual(report["timesheets_linked"], 0)
        self.assertEqual(report["timesheets_unlinked"], 1)
```

**Шаг 2. Запуск (ожидание: FAIL).** `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_portal_backfill --settings=test_settings` — упадёт (`portal_backfill_service` ещё нет).

**Шаг 3. Реализация (ПОЛНЫЙ код).**

**Сервис** — Create `main/portal_backfill_service.py`:
```python
"""Backfill FK portal на данных (этап 1 перестройки мультитенантности).

Проставляет TimesheetItem.portal / ProjectCard.portal от их bitrix24_account.portal.
Идемпотентно (обрабатывает только portal IS NULL), батчами (память/блокировки на
103k+ записях). Запускается командой backfill_portal_links, НЕ миграцией.
"""
import logging
from typing import Dict

from django.db import transaction

from .models import TimesheetItem, ProjectCard

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 2000


def _backfill_model(model, batch_size: int) -> Dict[str, int]:
    linked = 0
    unlinked = 0
    while True:
        # Берём пачку незаполненных pk + portal их аккаунта.
        rows = list(
            model.objects
            .filter(portal__isnull=True)
            .values_list("pk", "bitrix24_account__portal_id")[:batch_size]
        )
        if not rows:
            break

        to_link = {pk: portal_id for pk, portal_id in rows if portal_id is not None}
        unlinkable = [pk for pk, portal_id in rows if portal_id is None]

        if to_link:
            # Группируем по portal_id, чтобы делать пачкой UPDATE ... WHERE pk IN (...).
            by_portal: Dict[str, list] = {}
            for pk, portal_id in to_link.items():
                by_portal.setdefault(portal_id, []).append(pk)
            with transaction.atomic():
                for portal_id, pks in by_portal.items():
                    model.objects.filter(pk__in=pks).update(portal_id=portal_id)
            linked += len(to_link)

        if unlinkable:
            unlinked += len(unlinkable)
            # Защита от бесконечного цикла: если в пачке ТОЛЬКО непривязываемые,
            # дальнейшие выборки вернут те же записи (portal остаётся NULL).
            if not to_link:
                break

    return {"linked": linked, "unlinked": unlinked}


def backfill_portal_links(batch_size: int = DEFAULT_BATCH_SIZE) -> Dict[str, int]:
    ts = _backfill_model(TimesheetItem, batch_size)
    cards = _backfill_model(ProjectCard, batch_size)
    report = {
        "timesheets_linked": ts["linked"],
        "timesheets_unlinked": ts["unlinked"],
        "cards_linked": cards["linked"],
        "cards_unlinked": cards["unlinked"],
    }
    logger.info("backfill_portal_links report: %s", report)
    return report
```
> **Тонкость бесконечного цикла:** записи с `portal_id IS NULL` у аккаунта без portal никогда не «уйдут» из выборки `portal__isnull=True`. Поэтому если в пачке нет ни одной привязываемой (`to_link` пуст), но есть непривязываемые — выходим (`break`). Если в пачке смешаны привязываемые и нет — привязываемые уйдут на следующей итерации, непривязываемые останутся, и в какой-то момент пачка станет состоять только из них → `break`. Это считает unlinked честно за один проход. Альтернатива (исключать unlinkable из выборки через `bitrix24_account__portal__isnull=False`) — тоже верна; выбран явный счётчик ради прозрачного отчёта. Зафиксировать в докладе.

**Команда** — Create `main/management/commands/backfill_portal_links.py` (по образцу `purge_request_logs.py`):
```python
"""Management command: backfill_portal_links

Этап 1 перестройки мультитенантности: проставляет TimesheetItem.portal /
ProjectCard.portal от их bitrix24_account.portal. Идемпотентно, батчами.
Запускать ПОСЛЕ применения миграций 0014/0015 (seed Portal).

Usage:
    python manage.py backfill_portal_links
    python manage.py backfill_portal_links --batch-size 5000
"""
from django.core.management.base import BaseCommand

from main.portal_backfill_service import backfill_portal_links, DEFAULT_BATCH_SIZE


class Command(BaseCommand):
    help = "Backfill FK portal на TimesheetItem/ProjectCard от их аккаунта (этап 1)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
            help=f"Размер батча UPDATE (по умолчанию {DEFAULT_BATCH_SIZE}).",
        )

    def handle(self, *args, **options):
        report = backfill_portal_links(batch_size=options["batch_size"])
        self.stdout.write(
            "Backfill done: "
            f"timesheets linked={report['timesheets_linked']} "
            f"unlinked={report['timesheets_unlinked']}; "
            f"cards linked={report['cards_linked']} "
            f"unlinked={report['cards_unlinked']}."
        )
        if report["timesheets_unlinked"] or report["cards_unlinked"]:
            self.stdout.write(self.style.WARNING(
                "Есть записи без portal (аккаунт без member_id/portal). "
                "Проверьте перед дедупом и этапом 4."
            ))
```

**Шаг 4. Запуск (ожидание: PASS).**
- `./.venv/bin/python manage.py test main.tests_portal_backfill --settings=test_settings` → зелёные.
- Регресс: `./.venv/bin/python manage.py test main.tests_reports --settings=test_settings` → 41/2-известные.

**Шаг 5. Доклад.** Команда `backfill_portal_links` + сервис `backfill_portal_links(batch_size)`: проставляет `portal` данным от аккаунта, идемпотентно (`portal__isnull=True`), батчами (UPDATE ... WHERE pk IN, без гигантского запроса), считает unlinked (аккаунты без portal). НЕ миграция — осознанный запуск после 0014/0015. Зафиксировать решение по обработке unlinkable-цикла.

---

## Задача 4.2 — Команда дедупликации `dedupe_portal_data` с dry-run [опус — выбор мастер-копии]

**Файлы:** Create `main/management/commands/dedupe_portal_data.py`; Create `main/portal_dedupe_service.py` (логика выбора копии + dry-run отчёт); Create `main/tests_portal_dedupe.py`.

**Дыра.** После backfill (4.1) у одного `Portal` есть несколько `TimesheetItem` с ОДИНАКОВЫМ `bitrix_id` (по одному от каждого аккаунта компании) и несколько `ProjectCard` с одинаковым `project_id`/`project_item_id`. До включения portal-уникальности (этап 4) эти дубли надо схлопнуть до одной «правильной» копии, иначе уникальный индекс `(portal, bitrix_id)` упадёт. Это **самая опасная** операция переезда — поэтому она отдельная команда с dry-run по умолчанию, НЕ миграция.

**Решение (этап 2 — дедуп, dry-run по умолчанию, выбор мастер-копии).**
- **Правило выбора «правильной» копии (детерминированное):** среди дублей одной группы `(portal, bitrix_id)` (для `TimesheetItem`) или `(portal, project_id)` и `(portal, project_item_id)` (для `ProjectCard`) оставить копию:
  1. принадлежащую **мастер-аккаунту** портала (`bitrix24_account.is_master_account=True`), если такая есть;
  2. иначе — копию с **максимумом данных/свежести**: для `TimesheetItem` наибольший `updated_at` (свежайший синк), при равенстве — наибольший `bitrix24_account.b24_user_id` (стабильный tie-break); для `ProjectCard` — наибольший `stage_updated_at`/`updated_at`, при равенстве — `bitrix24_account.b24_user_id`. «Максимум данных» здесь = свежайшая синхронизированная копия (она наиболее полная, т.к. синк — upsert).
  - Обоснование: мастер-аккаунт — естественный «владелец» компании; при его отсутствии свежайшая копия минимизирует риск потерять данные (риск из спецификации: «дедуп выберет неполную копию»). Снижение риска описано в Части B (перед дедупом синкнуть представителей до полноты).
- **dry-run по умолчанию:** команда БЕЗ флага `--apply` НИЧЕГО не удаляет — только считает группы дублей и печатает отчёт: сколько групп, сколько записей схлопнётся (к удалению), сколько уникальных останется, разбивка по порталам. Только с `--apply` выполняется реальное удаление (батчами, атомарно по порталу).
- **Что значит «схлопнуть»:** удалить дубль-копии, оставив выбранную. На этапе 2 мы НЕ переносим вложенные ссылки (у `TimesheetItem`/`ProjectCard` нет дочерних FK на них в этой схеме — проверено: `RequestLog`/`SystemLog` ссылаются на `Bitrix24Account`, не на эти модели), поэтому удаление безопасно.
- **Предохранитель порядка:** перед дедупом команда проверяет, что нет `TimesheetItem`/`ProjectCard` с `portal IS NULL` среди записей, чьи аккаунты имеют portal (т.е. backfill завершён). Если такие есть — печатает предупреждение и при `--apply` отказывается работать (нужно сначала добить backfill). Записи с аккаунтом без portal (честно unlinked) — игнорирует (они вне дедупа).

**Шаг 1. Падающий тест** — Create `main/tests_portal_dedupe.py` (Django-`TestCase`):
```python
"""Тесты дедупликации данных портала (задача 4.2)."""
from django.test import TestCase
from django.utils import timezone

from .models import Bitrix24Account, Portal, TimesheetItem, ProjectCard
from .portal_dedupe_service import dedupe_portal_data


def _portal(member_id="m1"):
    return Portal.objects.create(member_id=member_id, domain_url=f"{member_id}.b24.ru", status="active")


def _account(portal, *, master=False, b24_user_id=1):
    return Bitrix24Account.objects.create(
        b24_user_id=b24_user_id, is_b24_user_admin=True, member_id=portal.member_id,
        is_master_account=master, domain_url=portal.domain_url, status="active",
        application_version=1, portal=portal,
    )


def _ts(account, portal, bitrix_id, *, hours=1.0):
    return TimesheetItem.objects.create(
        bitrix24_account=account, portal=portal, bitrix_id=bitrix_id,
        task_id="1", employee_id="1", hours=hours, date_reflection=timezone.now(),
    )


class DedupeDryRunTest(TestCase):
    def test_dry_run_counts_but_does_not_delete(self):
        portal = _portal()
        master = _account(portal, master=True, b24_user_id=1)
        other = _account(portal, master=False, b24_user_id=2)
        _ts(master, portal, bitrix_id=100)
        _ts(other, portal, bitrix_id=100)   # дубль того же bitrix_id в пределах portal
        _ts(other, portal, bitrix_id=200)   # уникальный

        report = dedupe_portal_data(apply=False)   # dry-run

        # Ничего не удалено.
        self.assertEqual(TimesheetItem.objects.count(), 3)
        # Отчёт: одна группа-дубль (bitrix_id=100), 1 запись к удалению.
        self.assertEqual(report["timesheets"]["duplicate_groups"], 1)
        self.assertEqual(report["timesheets"]["rows_to_delete"], 1)
        self.assertFalse(report["applied"])

    def test_apply_keeps_master_copy(self):
        portal = _portal()
        master = _account(portal, master=True, b24_user_id=1)
        other = _account(portal, master=False, b24_user_id=2)
        keep = _ts(master, portal, bitrix_id=100)
        drop = _ts(other, portal, bitrix_id=100)

        report = dedupe_portal_data(apply=True)

        self.assertEqual(report["applied"], True)
        self.assertTrue(TimesheetItem.objects.filter(pk=keep.pk).exists())   # мастер остался
        self.assertFalse(TimesheetItem.objects.filter(pk=drop.pk).exists())  # дубль удалён
        self.assertEqual(TimesheetItem.objects.filter(portal=portal, bitrix_id=100).count(), 1)

    def test_apply_without_master_keeps_freshest(self):
        portal = _portal()
        a1 = _account(portal, master=False, b24_user_id=1)
        a2 = _account(portal, master=False, b24_user_id=2)
        older = _ts(a1, portal, bitrix_id=100)
        newer = _ts(a2, portal, bitrix_id=100)
        # Делаем newer свежее по updated_at.
        TimesheetItem.objects.filter(pk=newer.pk).update(updated_at=timezone.now())
        older.refresh_from_db(); newer.refresh_from_db()

        dedupe_portal_data(apply=True)
        # Осталась ровно одна; при отсутствии мастера — свежайшая (newer).
        remaining = TimesheetItem.objects.filter(portal=portal, bitrix_id=100)
        self.assertEqual(remaining.count(), 1)

    def test_card_dedup_by_project_id(self):
        portal = _portal()
        master = _account(portal, master=True, b24_user_id=1)
        other = _account(portal, master=False, b24_user_id=2)
        ProjectCard.objects.create(bitrix24_account=master, portal=portal, project_id="500", project_name="P", stage="new")
        ProjectCard.objects.create(bitrix24_account=other, portal=portal, project_id="500", project_name="P2", stage="new")

        report = dedupe_portal_data(apply=True)
        self.assertEqual(ProjectCard.objects.filter(portal=portal, project_id="500").count(), 1)
        self.assertEqual(report["cards"]["rows_to_delete"], 1)

    def test_refuses_apply_when_backfill_incomplete(self):
        # Запись с аккаунтом-с-portal, но portal на записи пуст -> backfill не завершён.
        portal = _portal()
        acc = _account(portal, master=True, b24_user_id=1)
        TimesheetItem.objects.create(
            bitrix24_account=acc, portal=None, bitrix_id=100,
            task_id="1", employee_id="1", hours=1.0, date_reflection=timezone.now(),
        )
        report = dedupe_portal_data(apply=True)
        self.assertFalse(report["applied"])
        self.assertTrue(report["backfill_incomplete"])
        self.assertEqual(TimesheetItem.objects.count(), 1)  # ничего не тронули
```

**Шаг 2. Запуск (ожидание: FAIL).** `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_portal_dedupe --settings=test_settings` — упадёт.

**Шаг 3. Реализация (ПОЛНЫЙ код).**

**Сервис** — Create `main/portal_dedupe_service.py`:
```python
"""Дедупликация данных портала (этап 2 перестройки мультитенантности).

В пределах Portal схлопывает дубли TimesheetItem по (portal, bitrix_id) и
ProjectCard по (portal, project_id) и (portal, project_item_id), оставляя
«правильную» копию: мастер-аккаунт портала, иначе свежайшую (max updated_at,
tie-break по b24_user_id). По умолчанию DRY-RUN: только считает и печатает,
НИЧЕГО не удаляет. Реальное удаление — только при apply=True.

ВАЖНО: запускать ПОСЛЕ backfill_portal_links (4.1). До включения portal-
уникальности (этап 4, Часть B) дубли ОБЯЗАНЫ быть устранены — иначе
уникальный индекс упадёт. Команда, НЕ миграция.
"""
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from django.db import transaction

from .models import TimesheetItem, ProjectCard

logger = logging.getLogger(__name__)


def _master_account_ids() -> set:
    from .models import Bitrix24Account
    return set(
        Bitrix24Account.objects
        .filter(is_master_account=True)
        .values_list("pk", flat=True)
    )


def _backfill_incomplete() -> bool:
    """True, если есть записи с portal=NULL у аккаунта, у которого portal есть."""
    ts_pending = TimesheetItem.objects.filter(
        portal__isnull=True, bitrix24_account__portal__isnull=False
    ).exists()
    card_pending = ProjectCard.objects.filter(
        portal__isnull=True, bitrix24_account__portal__isnull=False
    ).exists()
    return ts_pending or card_pending


def _pick_keeper(rows: List[Tuple], master_ids: set) -> Any:
    """rows: список кортежей (pk, account_pk, sort_key, b24_user_id).
    Возвращает pk копии, которую ОСТАВЛЯЕМ."""
    # 1) мастер-аккаунт.
    masters = [r for r in rows if r[1] in master_ids]
    pool = masters or rows
    # 2) свежайшая (sort_key), tie-break по b24_user_id (оба — больше=лучше).
    pool_sorted = sorted(pool, key=lambda r: (r[2] or 0, r[3] or 0), reverse=True)
    return pool_sorted[0][0]


def _dedupe_timesheets(apply: bool, master_ids: set) -> Dict[str, int]:
    # Группируем по (portal_id, bitrix_id).
    groups: Dict[Tuple, List[Tuple]] = defaultdict(list)
    qs = (
        TimesheetItem.objects
        .filter(portal__isnull=False)
        .values_list("pk", "bitrix24_account_id", "updated_at", "bitrix24_account__b24_user_id",
                     "portal_id", "bitrix_id")
    )
    for pk, acc_pk, updated_at, b24_user_id, portal_id, bitrix_id in qs.iterator(chunk_size=5000):
        ts = updated_at.timestamp() if updated_at else 0
        groups[(portal_id, bitrix_id)].append((pk, acc_pk, ts, b24_user_id))

    to_delete: List[Any] = []
    dup_groups = 0
    for key, rows in groups.items():
        if len(rows) <= 1:
            continue
        dup_groups += 1
        keeper = _pick_keeper(rows, master_ids)
        to_delete.extend(r[0] for r in rows if r[0] != keeper)

    if apply and to_delete:
        with transaction.atomic():
            # Батчами по 5000 pk.
            for i in range(0, len(to_delete), 5000):
                TimesheetItem.objects.filter(pk__in=to_delete[i:i + 5000]).delete()

    return {"duplicate_groups": dup_groups, "rows_to_delete": len(to_delete)}


def _dedupe_cards(apply: bool, master_ids: set) -> Dict[str, int]:
    dup_groups = 0
    to_delete: set = set()

    def _collect(group_field: str):
        nonlocal dup_groups
        groups: Dict[Tuple, List[Tuple]] = defaultdict(list)
        qs = (
            ProjectCard.objects
            .filter(portal__isnull=False)
            .exclude(**{f"{group_field}__isnull": True})
            .exclude(**{group_field: ""})
            .values_list("pk", "bitrix24_account_id", "updated_at",
                         "bitrix24_account__b24_user_id", "portal_id", group_field)
        )
        for pk, acc_pk, updated_at, b24_user_id, portal_id, gval in qs.iterator(chunk_size=5000):
            ts = updated_at.timestamp() if updated_at else 0
            groups[(portal_id, gval)].append((pk, acc_pk, ts, b24_user_id))
        for key, rows in groups.items():
            if len(rows) <= 1:
                continue
            dup_groups += 1
            keeper = _pick_keeper(rows, master_ids)
            for r in rows:
                if r[0] != keeper:
                    to_delete.add(r[0])

    _collect("project_id")
    _collect("project_item_id")

    if apply and to_delete:
        ids = list(to_delete)
        with transaction.atomic():
            for i in range(0, len(ids), 5000):
                ProjectCard.objects.filter(pk__in=ids[i:i + 5000]).delete()

    return {"duplicate_groups": dup_groups, "rows_to_delete": len(to_delete)}


def dedupe_portal_data(apply: bool = False) -> Dict[str, Any]:
    incomplete = _backfill_incomplete()
    if incomplete and apply:
        logger.warning("dedupe_portal_data: backfill incomplete, refusing to apply.")
        return {"applied": False, "backfill_incomplete": True,
                "timesheets": {"duplicate_groups": 0, "rows_to_delete": 0},
                "cards": {"duplicate_groups": 0, "rows_to_delete": 0}}

    master_ids = _master_account_ids()
    ts_report = _dedupe_timesheets(apply=apply, master_ids=master_ids)
    card_report = _dedupe_cards(apply=apply, master_ids=master_ids)

    report = {
        "applied": bool(apply) and not incomplete,
        "backfill_incomplete": incomplete,
        "timesheets": ts_report,
        "cards": card_report,
    }
    logger.info("dedupe_portal_data report (apply=%s): %s", apply, report)
    return report
```

**Команда** — Create `main/management/commands/dedupe_portal_data.py`:
```python
"""Management command: dedupe_portal_data

Этап 2 перестройки мультитенантности: схлопывает дубли TimesheetItem/ProjectCard
в пределах Portal (оставляет мастер-копию, иначе свежайшую). По умолчанию
DRY-RUN — только отчёт, без удаления. Реальное удаление — только с --apply.

Запускать ПОСЛЕ backfill_portal_links (4.1) и ДО этапа 4 (включение portal-
уникальности). Сначала прогнать БЕЗ --apply, проверить отчёт, затем --apply.

Usage:
    python manage.py dedupe_portal_data            # dry-run (отчёт)
    python manage.py dedupe_portal_data --apply    # реальное удаление дублей
"""
from django.core.management.base import BaseCommand

from main.portal_dedupe_service import dedupe_portal_data


class Command(BaseCommand):
    help = "Дедуп TimesheetItem/ProjectCard в пределах Portal (dry-run по умолчанию)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Выполнить реальное удаление дублей (по умолчанию только отчёт).",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        report = dedupe_portal_data(apply=apply)

        if report["backfill_incomplete"]:
            self.stdout.write(self.style.ERROR(
                "Backfill не завершён (есть записи с пустым portal у аккаунтов с portal). "
                "Сначала добейте `backfill_portal_links`. Дедуп НЕ применён."
            ))
            return

        mode = "ПРИМЕНЕНО" if report["applied"] else "DRY-RUN (ничего не удалено)"
        self.stdout.write(f"Дедуп [{mode}]:")
        self.stdout.write(
            f"  TimesheetItem: групп-дублей={report['timesheets']['duplicate_groups']}, "
            f"к удалению={report['timesheets']['rows_to_delete']}"
        )
        self.stdout.write(
            f"  ProjectCard:   групп-дублей={report['cards']['duplicate_groups']}, "
            f"к удалению={report['cards']['rows_to_delete']}"
        )
        if not report["applied"]:
            self.stdout.write(self.style.WARNING(
                "Это был dry-run. Для реального удаления запустите с --apply "
                "(только после проверки отчёта и на копии прода — см. план, Часть B)."
            ))
```

**Шаг 4. Запуск (ожидание: PASS).**
- `./.venv/bin/python manage.py test main.tests_portal_dedupe --settings=test_settings` → зелёные.
- Регресс: `./.venv/bin/python manage.py test main.tests_reports --settings=test_settings` → 41/2-известные.

**Шаг 5. Доклад.** Команда `dedupe_portal_data` + сервис: dry-run по умолчанию (считает группы дублей и rows_to_delete, НЕ удаляет), `--apply` — реальное удаление батчами по 5000, атомарно. Выбор копии: мастер-аккаунт → свежайшая (max updated_at, tie-break b24_user_id). Предохранитель: при незавершённом backfill отказывается применять. НЕ миграция. Зафиксировать правило выбора и поведение предохранителя.

---

## Задача 4.3-helper — Помощник `scope_to_tenant` + флаг `USE_PORTAL_SCOPING` [опус — механизм переключения]

**Файлы:** Create `main/tenant_scoping.py`; Modify `backends/python/api/settings.py` (чтение env-флага `USE_PORTAL_SCOPING`); Create `main/tests_tenant_scoping.py`.

**Дыра.** Сейчас 19 точек данных жёстко фильтруют `bitrix24_account=...`. Нужен единый переключатель, который при выключенном флаге возвращает то же самое (БИТ-в-БИТ), а при включённом — `portal=...`, с фолбэком на account, когда portal пуст.

**Решение (этап 3 — флаг двойного чтения).**
- Флаг `USE_PORTAL_SCOPING` в `settings.py`, читается из env, **дефолт `False`**. По образцу того, как настройки уже читаются в проекте (проверить, как читаются прочие булевы env — `os.environ.get(...)`; привести к bool из строки `"1"/"true"/"True"`).
- Помощник `scope_to_tenant(account, *, write=False) -> dict` в `main/tenant_scoping.py` возвращает **kwargs для `.filter()`/создания**:
  - Если `USE_PORTAL_SCOPING` выключен → `{"bitrix24_account": account}` (текущее поведение, БИТ-в-БИТ).
  - Если включён И у `account` есть `portal` (`account.portal_id` не None) → `{"portal": account.portal}` для чтения; а для записи (`write=True`) дополнительно ставит и `bitrix24_account` тоже (двойная запись: новые записи получают и portal, и account — чтобы откат на account-скоупинг был возможен до этапа 4, и чтобы аудит «кто принёс» сохранялся). Подробнее ниже.
  - Если включён, но `portal` пуст (`account.portal_id is None`) → фолбэк `{"bitrix24_account": account}` (как при выключенном — переходный период, пока backfill не добил этот аккаунт).
- **Двойная запись (write=True).** Для точек DATA-WRITE (создание `TimesheetItem`/`ProjectCard`, orphan-deletion) логика тоньше:
  - **Чтение в рамках записи (lookup перед upsert, orphan count/delete фильтры):** при включённом флаге скоупим по `portal` (чтобы найти/удалить записи всей компании). Это то, что делает `scope_to_tenant(account)` для чтения.
  - **Создание новой записи:** проставляем И `portal`, И `bitrix24_account` (account = «кто синкнул», аудит + возможность отката). Поэтому для создания помощник возвращает оба ключа: `{"portal": account.portal, "bitrix24_account": account}`.
  - Это значит: сигнатура `scope_to_tenant(account, write=False)`. При `write=False` (чтение) и включённом флаге с portal → только `{"portal": ...}`. При `write=True` (создание/orphan) и включённом флаге с portal → `{"portal": ..., "bitrix24_account": ...}`. При выключенном флаге обе ветки → `{"bitrix24_account": account}`.

> **Почему orphan-deletion при включённом флаге должен скоупиться по portal, но это ОПАСНО до дедупа?** При включённом флаге orphan-deletion в `timesheet_sync_service` будет удалять записи всей компании, которых нет в свежем фетче представителя. Это КОРРЕКТНО после дедупа (одна копия на компанию), но ДО дедупа, при двойном чтении, может удалить копии других аккаунтов. **Решение:** orphan-deletion — операция записи под флагом; в процедуре прод-выката (Часть B) флаг включается ТОЛЬКО после дедупа. На переходном этапе (флаг включён, дедуп ещё не сделан) этого состояния на проде не будет — порядок выката это гарантирует (backfill → dedupe → флаг). В тестах эквивалентности (4.4) orphan-deletion проверяется на уже дедуплицированных данных. Зафиксировать как явное ограничение порядка (открытый вопрос 4).

**Шаг 1. Падающий тест** — Create `main/tests_tenant_scoping.py` (Django-`TestCase`, использует `@override_settings`):
```python
"""Тесты помощника scope_to_tenant и флага USE_PORTAL_SCOPING (задача 4.3)."""
from django.test import TestCase, override_settings

from .models import Bitrix24Account, Portal
from .tenant_scoping import scope_to_tenant


def _account(member_id="m1", *, with_portal=True):
    portal = None
    if with_portal:
        portal = Portal.objects.create(member_id=member_id, domain_url=f"{member_id}.b24.ru", status="active")
    return Bitrix24Account.objects.create(
        b24_user_id=1, is_b24_user_admin=True, member_id=member_id, is_master_account=True,
        domain_url=f"{member_id}.b24.ru", status="active", application_version=1, portal=portal,
    ), portal


class ScopeToTenantTest(TestCase):
    @override_settings(USE_PORTAL_SCOPING=False)
    def test_flag_off_returns_account_kwargs(self):
        acc, _ = _account()
        self.assertEqual(scope_to_tenant(acc), {"bitrix24_account": acc})
        # write=True при выключенном флаге — тоже account.
        self.assertEqual(scope_to_tenant(acc, write=True), {"bitrix24_account": acc})

    @override_settings(USE_PORTAL_SCOPING=True)
    def test_flag_on_with_portal_reads_by_portal(self):
        acc, portal = _account()
        self.assertEqual(scope_to_tenant(acc), {"portal": portal})

    @override_settings(USE_PORTAL_SCOPING=True)
    def test_flag_on_write_sets_both_portal_and_account(self):
        acc, portal = _account()
        result = scope_to_tenant(acc, write=True)
        self.assertEqual(result, {"portal": portal, "bitrix24_account": acc})

    @override_settings(USE_PORTAL_SCOPING=True)
    def test_flag_on_but_portal_empty_falls_back_to_account(self):
        acc, _ = _account(with_portal=False)
        self.assertIsNone(acc.portal_id)
        self.assertEqual(scope_to_tenant(acc), {"bitrix24_account": acc})
        self.assertEqual(scope_to_tenant(acc, write=True), {"bitrix24_account": acc})
```

**Шаг 2. Запуск (ожидание: FAIL).** `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_tenant_scoping --settings=test_settings` — упадёт.

**Шаг 3. Реализация (ПОЛНЫЙ код).**

**Помощник** — Create `main/tenant_scoping.py`:
```python
"""Помощник скоупинга «tenant» (этап 3 перестройки мультитенантности).

scope_to_tenant(account, write=False) возвращает kwargs для .filter()/создания.
Поведение управляется флагом settings.USE_PORTAL_SCOPING (дефолт False):

- Флаг OFF  -> {"bitrix24_account": account}  (текущее поведение, БИТ-в-БИТ).
- Флаг ON, portal есть, write=False -> {"portal": account.portal}  (чтение по компании).
- Флаг ON, portal есть, write=True  -> {"portal": account.portal, "bitrix24_account": account}
  (двойная запись: новые записи получают и portal, и account — для аудита «кто синкнул»
  и для возможности отката на account-скоупинг до этапа 4).
- Флаг ON, portal пуст (None) -> {"bitrix24_account": account}  (фолбэк, переходный период
  пока backfill не добил аккаунт).

Использование в точках скоупинга:
    TimesheetItem.objects.filter(**scope_to_tenant(self.account))
    TimesheetItem.objects.filter(**scope_to_tenant(self.account), bitrix_id__in=ids)
    TimesheetItem(**scope_to_tenant(self.account, write=True), bitrix_id=bid, **defaults)
"""
from typing import Any, Dict

from django.conf import settings


def _portal_scoping_enabled() -> bool:
    return bool(getattr(settings, "USE_PORTAL_SCOPING", False))


def scope_to_tenant(account: Any, *, write: bool = False) -> Dict[str, Any]:
    """Возвращает kwargs скоупинга для TimesheetItem/ProjectCard."""
    if account is None:
        # Защита: без аккаунта возвращаем заведомо пустой фильтр на account
        # (вызывающий код и так не должен звать без аккаунта).
        return {"bitrix24_account": account}

    if not _portal_scoping_enabled():
        return {"bitrix24_account": account}

    portal = getattr(account, "portal", None)
    if portal is None:
        # Фолбэк: portal ещё не проставлен (backfill не добил) — ведём себя как раньше.
        return {"bitrix24_account": account}

    if write:
        # Двойная запись: и portal, и account.
        return {"portal": portal, "bitrix24_account": account}
    return {"portal": portal}
```

**Флаг в settings** — Modify `backends/python/api/settings.py`. Сначала исполнитель читает, как в файле уже читаются булевы env (грепом `grep -n "os.environ\|os.getenv\|environ.get" settings.py`), и добавляет в том же стиле. Ориентир (адаптировать под фактический стиль файла):
```python
import os  # если ещё не импортирован

def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

# Флаг перевода скоупинга данных на portal (этап 3 перестройки мультитенантности).
# По умолчанию False — поведение БИТ-в-БИТ как до спринта 4 (account-скоупинг).
# Включать на проде ТОЛЬКО после backfill + dedupe (см. план Часть B).
USE_PORTAL_SCOPING = _env_bool("USE_PORTAL_SCOPING", False)
```
> **Сверка:** `test_settings.py` импортирует из `settings`? Если `test_settings` наследует `from settings import *`, то `USE_PORTAL_SCOPING=False` подхватится и в тестах (дефолт), что и нужно (тесты эквивалентности и спринта 4 включают флаг точечно через `@override_settings`). Проверить, что `test_settings.py` не переопределяет флаг. Если `test_settings` НЕ наследует settings — добавить `USE_PORTAL_SCOPING = False` и туда явно.

**Шаг 4. Запуск (ожидание: PASS).**
- `./.venv/bin/python manage.py test main.tests_tenant_scoping --settings=test_settings` → зелёные.
- Регресс: `./.venv/bin/python manage.py test main.tests_reports --settings=test_settings` → 41/2-известные (флаг по умолчанию False — ничего не меняется).

**Шаг 5. Доклад.** Помощник `scope_to_tenant(account, write=False)` + флаг `USE_PORTAL_SCOPING` (env, дефолт False). При выключенном флаге → account-kwargs (БИТ-в-БИТ); при включённом с portal → portal-kwargs для чтения, portal+account для записи (двойная запись для аудита/отката); при пустом portal → фолбэк на account. Зафиксировать стиль чтения env и поведение test_settings.

---

## Задача 4.3-reads-a — Перевод чтения: report_queries + project_board_shared [соннет]

**Файлы:** Modify `main/report_queries.py` (точка 7, стр. 29); Modify `main/project_board_shared.py` (точки 3-4, стр. 161, 166).

**Дыра.** Эти точки [DATA-READ] жёстко фильтруют `bitrix24_account=account`. `report_queries.build_filtered_timesheet_queryset` — ядро ВСЕХ отчётов (его зовут все отчётные вьюхи). `project_board_shared.get_project_card_queryset` и `build_local_project_groups` — общие источники карточек/групп.

**Решение.** Заменить `bitrix24_account=account` на `**scope_to_tenant(account)` (чтение). Импортировать помощник. Поведение при выключенном флаге — идентично текущему.

**Шаг 1. Падающий тест.** Отдельного теста для каждой точки не пишем — корректность чтения под флагом покрывает тест эквивалентности 4.4 (волна 6), а поведение при выключенном флаге — существующий регресс `tests_reports`. Перед правкой исполнитель читает обе функции целиком, чтобы понять сигнатуру `account` (в `report_queries` — аргумент `account: Bitrix24Account`; в `project_board_shared` — аргумент `account`).

**Шаг 2. Реализация.**

В `main/report_queries.py` — добавить импорт (рядом со стр. 9):
```python
from .tenant_scoping import scope_to_tenant
```
Заменить строку 29:
```python
    queryset = TimesheetItem.objects.filter(**scope_to_tenant(account))
```

В `main/project_board_shared.py` — добавить импорт `from .tenant_scoping import scope_to_tenant` (рядом с прочими импортами). Заменить строку 161:
```python
    return ProjectCard.objects.filter(**scope_to_tenant(account))
```
Заменить строку 166 (внутри `build_local_project_groups`):
```python
        TimesheetItem.objects.filter(**scope_to_tenant(account))
```

**Шаг 3. Проверка.**
- Регресс при флаге OFF (дефолт): `./.venv/bin/python manage.py test main.tests_reports --settings=test_settings` → 41/2-известные (БИТ-в-БИТ).
- Полный прогон по затронутым контрактам: `test_timesheet_filters_use_date_range_and_exclude_archived_projects` зелёный.

**Шаг 4. Доклад.** 3 точки чтения (report_queries:29, project_board_shared:161/166) переведены на `**scope_to_tenant(account)`; при OFF поведение идентично; регресс зелёный.

---

## Задача 4.3-reads-b — Перевод чтения: project_board_service + project_budget_service [соннет]

**Файлы:** Modify `main/project_board_service.py` (точки 8-11, 13: стр. 521, 539, 551, 1047, 1245 — ВСЕ [DATA-READ]; точка 12 стр. 1239 — [AUDIT], НЕ трогать); Modify `main/project_budget_service.py` (точка 6, стр. 50).

**Дыра.** `project_board_service` читает `TimesheetItem`/`ProjectCard` в пяти местах (writeoff-карты by item/id/title, revenue-leakage, `_get_card`). `project_budget_service._collect_timesheet_aggregates` агрегирует трудозатраты. Все скоупятся по `self.account`.

**Решение.** Заменить `bitrix24_account=self.account` на `**scope_to_tenant(self.account)` в пяти DATA-READ точках board_service и одной точке budget_service. Точку 12 (стр. 1239, `SystemLog.objects.create`) НЕ трогать — это аудит.
- Для точек с дополнительными kwargs (стр. 1047: `date_reflection__gte=...`; стр. 1245: `project_id=...`) — распаковка помощника идёт первой, остальные kwargs следом:
  - стр. 1047: `TimesheetItem.objects.filter(**scope_to_tenant(self.account), date_reflection__gte=...)`.
  - стр. 1245: `ProjectCard.objects.get(**scope_to_tenant(self.account), project_id=str(project_id))`.

**Шаг 1. Падающий тест.** Покрытие — тест эквивалентности 4.4 + регресс. Перед правкой прочитать конструкторы обоих классов (`self.account` устанавливается в `__init__`, проверено: board_service:73, budget_service:15).

**Шаг 2. Реализация.**

В `main/project_board_service.py` — добавить импорт `from .tenant_scoping import scope_to_tenant`. Заменить:
- стр. 521: `TimesheetItem.objects.filter(**scope_to_tenant(self.account))`
- стр. 539: `TimesheetItem.objects.filter(**scope_to_tenant(self.account))`
- стр. 551: `TimesheetItem.objects.filter(**scope_to_tenant(self.account))`
- стр. 1047: `queryset = TimesheetItem.objects.filter(**scope_to_tenant(self.account), date_reflection__gte=datetime.combine(recent_from, datetime.min.time(), tzinfo=timezone.get_current_timezone()))`
- стр. 1245: `return ProjectCard.objects.get(**scope_to_tenant(self.account), project_id=str(project_id))`
- стр. 1239 — **НЕ менять** (SystemLog, аудит).

В `main/project_budget_service.py` — добавить импорт `from .tenant_scoping import scope_to_tenant`. Заменить стр. 50:
```python
            TimesheetItem.objects.filter(**scope_to_tenant(self.account))
```

**Шаг 3. Проверка.** Регресс при OFF: `./.venv/bin/python manage.py test main.tests_reports --settings=test_settings` → 41/2-известные. Грепом убедиться, что точка 1239 (SystemLog) ОСТАЛАСЬ на `bitrix24_account=self.account`: `grep -n "bitrix24_account=self.account" main/project_board_service.py` должен показать только строку 1239 (и больше нет DATA-READ с этим литералом).

**Шаг 4. Доклад.** 5 точек чтения board_service + 1 budget_service переведены на `**scope_to_tenant(self.account)`; точка SystemLog (1239) сохранена на account (аудит); при OFF поведение идентично; регресс зелёный.

---

## Задача 4.3-views — Перевод чтения: views.py [соннет]

**Файлы:** Modify `main/views.py` (точки 17-18: стр. 153, 1492 — [DATA-READ]; точки 19-20 стр. 1860, 1894 — [AUDIT], НЕ трогать).

**Дыра.** `_build_project_filter_options` (стр. 153) и `timesheet_list` (стр. 1492) скоупят `TimesheetItem` по `request.bitrix24_account`. Просмотр логов (1860 RequestLog, 1894 SystemLog) — аудит «кто», остаётся на account.

**Решение.** Заменить две DATA-READ точки на `**scope_to_tenant(request.bitrix24_account)`. Точки 1860/1894 НЕ трогать.
- стр. 153: `queryset = TimesheetItem.objects.filter(**scope_to_tenant(request.bitrix24_account))`. **Тонкость:** в той же функции стр. 155 зовёт `get_project_card_queryset(request.bitrix24_account)` — он уже переведён на portal в задаче 4.3-reads-a, ничего дополнительно тут не нужно (передаётся account, помощник внутри решает).
- стр. 1492: `queryset = TimesheetItem.objects.filter(**scope_to_tenant(request.bitrix24_account)).order_by('-created_at', '-bitrix_id')`.

**Шаг 1. Падающий тест.** Покрытие — 4.4 + регресс. Перед правкой прочитать импорты `views.py` (добавить `from .tenant_scoping import scope_to_tenant`, если ещё нет; проверить, что нет конфликта имён).

**Шаг 2. Реализация.** Добавить импорт; заменить стр. 153 и 1492 как выше. Точки 1860/1894 — без изменений.

**Шаг 3. Проверка.** Регресс при OFF: `./.venv/bin/python manage.py test main.tests_reports --settings=test_settings` → 41/2-известные (контракт `timesheet_list` сохранён). Грепом: `grep -n "bitrix24_account=request.bitrix24_account" main/views.py` показывает только 1860/1894 (RequestLog/SystemLog).

**Шаг 4. Доклад.** 2 точки чтения views (153, 1492) переведены на `**scope_to_tenant(request.bitrix24_account)`; просмотр логов (1860/1894) сохранён на account (аудит); при OFF поведение идентично; регресс зелёный.

---

## Задача 4.3-sync-ts — Перевод записи: timesheet_sync_service [опус — критичный синк-путь]

**Файлы:** Modify `main/timesheet_sync_service.py` (точки 21-25: стр. 182, 192, 381, 453, 465).

**Дыра.** Это [DATA-WRITE] путь — самый чувствительный. `_save_batch` (стр. 408-471) делает upsert: lookup существующих (стр. 452-456) + создание новых (стр. 463-471). Orphan-deletion: полный (стр. 180-195) и scoped (стр. 378-394). Все скоупятся по `self.account`.

**Решение.** Перевести на `scope_to_tenant(self.account, write=True)`:
- **Lookup перед upsert (стр. 452-456):** при включённом флаге искать существующие записи надо по `portal` (чтобы найти запись компании, синкнутую любым представителем — иначе создадим дубль). → `**scope_to_tenant(self.account)` (чтение; для lookup write не нужен — мы только читаем существующие). НО bitrix_id__in остаётся.
  ```python
          existing_items = {
              item.bitrix_id: item
              for item in TimesheetItem.objects.filter(
                  **scope_to_tenant(self.account),
                  bitrix_id__in=bitrix_ids,
              )
          }
  ```
- **Создание (стр. 463-471):** новая запись получает И portal, И account. → `**scope_to_tenant(self.account, write=True)`:
  ```python
                  to_create.append(
                      TimesheetItem(
                          **scope_to_tenant(self.account, write=True),
                          bitrix_id=bitrix_id,
                          created_at=now,
                          updated_at=now,
                          **defaults,
                      )
                  )
  ```
  > **Тонкость:** при выключенном флаге `scope_to_tenant(..., write=True)` = `{"bitrix24_account": account}` — ровно как сейчас. При включённом = `{"portal": ..., "bitrix24_account": ...}` — оба поля, что корректно (запись принадлежит компании, аудит-account сохранён).
- **Orphan-deletion полный (стр. 181-183 count, 191-194 delete):** скоупим чтение по portal под флагом. count и delete:
  ```python
              current_count = TimesheetItem.objects.filter(
                  **scope_to_tenant(self.account)
              ).count()
              ...
                  TimesheetItem.objects.filter(**scope_to_tenant(self.account))
                  .exclude(bitrix_id__in=all_bitrix_ids)
                  .delete()
  ```
- **Orphan-deletion scoped (стр. 379-387):**
  ```python
              TimesheetItem.objects.filter(
                  **scope_to_tenant(self.account),
                  date_reflection__date__gte=date_from,
                  date_reflection__date__lte=date_to,
              )
              .exclude(bitrix_id__in=int_ids)
              .delete()
  ```

> **ОПАСНОСТЬ orphan-deletion при включённом флаге до дедупа** (см. помощник 4.3-helper): при включённом флаге orphan-deletion удаляет записи всей компании, отсутствующие в фетче представителя. До дедупа это удалит копии других аккаунтов. Гарантия: на проде флаг включается ТОЛЬКО после dedupe (Часть B, порядок выката). На переходе (флаг ON, дедуп не сделан) прод не будет — порядок это исключает. В тестах эквивалентности (4.4) синк-эквивалентность проверяется на дедуплицированных данных. Это ограничение зафиксировано в открытом вопросе 4.

**Шаг 1. Падающий тест.** Контракт `test_timesheet_sync_save_batch_updates_and_creates_records` (в `tests_reports`) проверяет upsert при флаге OFF — должен остаться зелёным. Поведение под флагом ON покрывает 4.4. Перед правкой прочитать `_save_batch` целиком (стр. 408-471) и оба orphan-блока.

**Шаг 2. Реализация.** Добавить импорт `from .tenant_scoping import scope_to_tenant` (рядом с прочими). Применить 5 замен выше (точки 21-25).

**Шаг 3. Проверка.**
- Регресс при OFF: `./.venv/bin/python manage.py test main.tests_reports --settings=test_settings` → 41/2-известные, контракт `test_timesheet_sync_save_batch_updates_and_creates_records` зелёный.
- Автономный синк-тест: `cd backends/python && api/.venv/bin/python -m unittest api.main.tests_sync_integration` → зелёный (он подменяет sys.modules — запускать ТОЛЬКО так). И `api.main.tests_sync_scoped` тем же способом.

**Шаг 4. Доклад.** 5 точек записи timesheet_sync (lookup, создание, 2× orphan-deletion) переведены: чтение/lookup по `scope_to_tenant(self.account)`, создание по `scope_to_tenant(self.account, write=True)` (portal+account). При OFF — БИТ-в-БИТ (контракт upsert зелёный). Зафиксировать риск orphan-deletion до дедупа (порядок выката его исключает).

---

## Задача 4.3-sync-proj — Перевод записи: project_sync_service [соннет]

**Файлы:** Modify `main/project_sync_service.py` (точки 14-16: стр. 166, 281 — создание ProjectCard [DATA-WRITE]; стр. 570 — чтение [DATA-READ]; точка стр. 1239 — НЕТ, это board_service; здесь SystemLog на стр. ~1239 НЕ в этом файле). В project_sync_service точка [AUDIT] — `_log_*` пишет SystemLog с `bitrix24_account=self.account`? Проверить: grep показал только 166/281/570 в project_sync_service — все три DATA. SystemLog-точка 1239 относится к project_board_service.

**Дыра.** Создание `ProjectCard` (две ветки: карточка группы стр. 165-180, карточка SP-элемента стр. 280+) скоупится `bitrix24_account=self.account`. Поиск несвязанных трудозатрат (стр. 570) — чтение.

**Решение.**
- **Создание (стр. 166, 281):** `**scope_to_tenant(self.account, write=True)` (portal+account):
  - стр. 165-166:
    ```python
                ProjectCard.objects.create(
                    **scope_to_tenant(self.account, write=True),
                    project_id=project_id,
                    ...
                )
    ```
  - стр. 280-281: аналогично — заменить `bitrix24_account=self.account,` на `**scope_to_tenant(self.account, write=True),` первой строкой в `ProjectCard.objects.create(...)`.
- **Чтение (стр. 570):** `**scope_to_tenant(self.account)`:
  ```python
          queryset = TimesheetItem.objects.filter(**scope_to_tenant(self.account)).filter(
              Q(project_item_id__isnull=True) | Q(project_item_id="")
          )
  ```
- **`_get_card`-аналог здесь?** Нет — `_get_card` (ProjectCard.objects.get) на стр. 1245 в board_service (задача 4.3-reads-b). В project_sync_service есть `existing_cards`-словарь — он строится из queryset; **проверить грепом** `grep -n "ProjectCard.objects" project_sync_service.py`, нет ли ещё точек скоупинга, которые греп `bitrix24_account=` не поймал (например `.filter(bitrix24_account=...)` через переменную). По гепу — только 166/281/570. Если найдётся `existing_cards = {... for c in ProjectCard.objects.filter(...)}` со скоупингом — перевести так же (DATA-READ). Зафиксировать в докладе, если нашлось.

> **Важно про дубль при создании под флагом:** при включённом флаге `ProjectCard.objects.create(portal=..., bitrix24_account=...)` создаёт карточку с обоими полями. До дедупа это может создать ВТОРУЮ карточку того же `project_id` в пределах portal (если представитель синкает, а у другого аккаунта она уже есть). Это переходное состояние; дедуп схлопнет. На проде флаг ON только после дедупа — порядок исключает. После этапа 4 (portal-уникальность) такой дубль невозможен. Зафиксировано в открытом вопросе 4.

**Шаг 1. Падающий тест.** Контракт `test_project_board_sync_endpoint_returns_warning_instead_of_500` (tests_reports) — зелёный при OFF. Под флагом — 4.4. Перед правкой прочитать обе ветки создания (стр. 155-182, 279-289) и конструктор (`self.account`, стр. 30).

**Шаг 2. Реализация.** Добавить импорт `from .tenant_scoping import scope_to_tenant`. Применить 3 замены (166, 281, 570) + любую дополнительную ProjectCard-точку, если греп её выявит.

**Шаг 3. Проверка.**
- Регресс при OFF: `./.venv/bin/python manage.py test main.tests_reports --settings=test_settings` → 41/2-известные.
- Автономный: `cd backends/python && api/.venv/bin/python -m unittest api.main.tests_project_fetch_keyset` → зелёный (sys.modules — только так).

**Шаг 4. Доклад.** 2 точки создания ProjectCard переведены на `scope_to_tenant(write=True)` (portal+account), 1 точка чтения на `scope_to_tenant`. При OFF — БИТ-в-БИТ. Зафиксировать, нашлись ли дополнительные ProjectCard-точки; зафиксировать риск дубля карточки до дедупа (исключён порядком выката).

---

## Задача 4.3-lock — account_sync_lock → portal-ключ + совместимость sync_scheduler [опус — заметка из ТЗ]

**Файлы:** Modify `main/utils/decorators/sync_lock.py` (ключ замка); Modify `main/sync_scheduler_service.py` (опционально — передача portal в lock).

**Дыра / контекст (проверено чтением `sync_lock.py` и `sync_scheduler_service.py`).** `account_sync_lock(account, scope)` ключуется по `account.pk` через `blake2b(str(account.pk))` (`_advisory_key`, стр. 36-50). После перехода на portal-скоупинг синк логически идёт на уровне **portal** (один представитель синкает данные всей компании в общие portal-таблицы). Если замок остаётся per-account, то два представителя одной компании (теоретически, при ручном запуске) могли бы синкать параллельно в одни и те же portal-данные — гонка. Поэтому ключ замка стоит привязать к **portal**, когда portal-скоупинг активен.

**Решение (аккуратно, под тем же флагом).**
- Расширить `account_sync_lock`, чтобы при включённом `USE_PORTAL_SCOPING` и наличии `account.portal` ключ считался по `portal.pk`, иначе (флаг OFF или portal пуст) — по `account.pk` (как сейчас, БИТ-в-БИТ). Это сохраняет текущее поведение по умолчанию и делает замок «по компании» только когда включён portal-режим.
- На sqlite (тесты) замок — no-op (gate `connection.vendor != "postgresql"`), поэтому изменение ключа НЕ влияет на тесты (там лок не берётся). Логику ключа покрываем юнит-тестом самой функции `_advisory_key`/выбора субъекта (без БД).
- **Совместимость с авто-синком (sync_scheduler_service, спринт 3):** `run_scheduled_sync` уже берёт ОДНОГО представителя на `member_id` (`select_portal_accounts`, стр. 950-960) и оборачивает синк в `account_sync_lock(account, scope="timesheet")` (стр. 992). После перехода на portal-ключ этот вызов естественно станет «замком по компании» (один представитель = один portal = один ключ) — дополнительной правки `sync_scheduler_service` НЕ требуется, кроме явной передачи субъекта замка (см. ниже). Авто-синк спринта 3 совместим: он и так синкает по одному представителю на компанию, что идеально ложится на portal-замок.

**Реализация ключа — два варианта (выбрать вариант 1 как менее инвазивный):**

*Вариант 1 (предпочтительный): субъект ключа выбирается ВНУТРИ `account_sync_lock` по флагу.* Меняем только `sync_lock.py`, сигнатура `account_sync_lock(account, scope)` не меняется — вызывающий код (views-декоратор `sync_lock`, sync_scheduler) не трогаем.

**Шаг 1. Падающий тест.** Лок на sqlite no-op, поэтому тестируем выбор субъекта ключа отдельной функцией. Вынести выбор субъекта в чистую функцию `_lock_subject_pk(account)` и протестировать её. Create-часть теста идёт в `main/tests_tenant_scoping.py`? Нет — `sync_lock.py` отдельный файл, тест держим рядом с ним логически, но чтобы не плодить модули — добавить класс в НОВЫЙ `main/tests_portal_lock.py` (Django-`TestCase`):
```python
"""Тест выбора субъекта advisory-замка под portal-скоупингом (задача 4.3-lock)."""
from django.test import TestCase, override_settings

from .models import Bitrix24Account, Portal
from .utils.decorators.sync_lock import _lock_subject_pk


def _account(member_id="m1", with_portal=True):
    portal = Portal.objects.create(member_id=member_id, domain_url="m1.b24.ru", status="active") if with_portal else None
    return Bitrix24Account.objects.create(
        b24_user_id=1, is_b24_user_admin=True, member_id=member_id, is_master_account=True,
        domain_url="m1.b24.ru", status="active", application_version=1, portal=portal,
    ), portal


class LockSubjectTest(TestCase):
    @override_settings(USE_PORTAL_SCOPING=False)
    def test_flag_off_subject_is_account_pk(self):
        acc, _ = _account()
        self.assertEqual(_lock_subject_pk(acc), acc.pk)

    @override_settings(USE_PORTAL_SCOPING=True)
    def test_flag_on_subject_is_portal_pk(self):
        acc, portal = _account()
        self.assertEqual(_lock_subject_pk(acc), portal.pk)

    @override_settings(USE_PORTAL_SCOPING=True)
    def test_flag_on_no_portal_falls_back_to_account_pk(self):
        acc, _ = _account(with_portal=False)
        self.assertEqual(_lock_subject_pk(acc), acc.pk)
```

**Шаг 2. Запуск (ожидание: FAIL).** `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_portal_lock --settings=test_settings` — упадёт (`_lock_subject_pk` ещё нет).

**Шаг 3. Реализация.** В `main/utils/decorators/sync_lock.py`:
- Добавить импорт `from django.conf import settings` (рядом со стр. 23-24).
- Добавить функцию выбора субъекта (после `_advisory_key`, стр. 51):
```python
def _lock_subject_pk(account):
    """Субъект advisory-замка: portal.pk при включённом portal-скоупинге и
    наличии portal, иначе account.pk (текущее поведение, БИТ-в-БИТ).

    Под portal-скоупингом синк логически идёт по компании (один представитель
    синкает данные всей компании в общие portal-таблицы), поэтому замок должен
    быть «по компании», а не по учётке."""
    if bool(getattr(settings, "USE_PORTAL_SCOPING", False)):
        portal = getattr(account, "portal", None)
        if portal is not None:
            return portal.pk
    return account.pk
```
- В `account_sync_lock` заменить `key = _advisory_key(account.pk, scope)` (стр. 64) на:
```python
    key = _advisory_key(_lock_subject_pk(account), scope)
```
  > `_advisory_key` принимает `account_pk` и хэширует `str(...)` — portal.pk (UUID) тоже строкуется одинаково, blake2b даёт стабильный bigint, переполнения нет (это и есть фикс инцидента 2026-06-10). Менять `_advisory_key` НЕ нужно.

**`sync_scheduler_service.py` — правка опциональна и минимальна.** Вызов `account_sync_lock(account, scope="timesheet")` (стр. 992) НЕ меняем — субъект ключа теперь выбирается внутри по флагу. Достаточно добавить комментарий-заметку рядом (одна строка), что под portal-скоупингом этот замок становится «по компании». Функционально ничего не меняется. Если исполнитель решит явно — оставить как есть (это чище). **Решение: НЕ менять `sync_scheduler_service.py` функционально** (только при желании — комментарий); файл зарезервирован за этой задачей, чтобы волна 5 не пересеклась.

**Шаг 4. Запуск (ожидание: PASS).**
- `./.venv/bin/python manage.py test main.tests_portal_lock --settings=test_settings` → зелёные.
- Существующий `tests_sync_lock` (на sqlite — проверяет no-op-поведение): `./.venv/bin/python manage.py test main.tests_sync_lock --settings=test_settings` → зелёный (ключ на sqlite не вычисляется, лок no-op; убедиться, что добавление `_lock_subject_pk` не сломало импорт/no-op-путь).
- Регресс: `tests_reports` → 41/2-известные; `tests_scheduled_sync` → зелёный.

**Шаг 5. Доклад.** Субъект advisory-замка вынесен в `_lock_subject_pk(account)`: при OFF/пустом portal — `account.pk` (БИТ-в-БИТ), при ON с portal — `portal.pk` («замок по компании»). `_advisory_key` не менялся (blake2b стабилен для UUID portal). `account_sync_lock`-сигнатура не менялась — вызовы (views-декоратор, sync_scheduler) не трогаются. Авто-синк спринта 3 совместим (он и так синкает одного представителя на компанию). `sync_scheduler_service` функционально не менялся.

---

## Задача 4.4 — Тест эквивалентности отчётов (с флагом и без) [опус — главный инвариант]

**Файлы:** Create `main/tests_portal_scoping_equivalence.py`.

**Дыра.** Нужно ДОКАЗАТЬ, что на одних и тех же данных отчёт даёт одинаковый результат при `USE_PORTAL_SCOPING=False` (account-скоупинг) и `True` (portal-скоупинг) — это гарантия безопасности переключения. Без этого теста переключение флага на проде — прыжок в неизвестность.

**Решение (тест эквивалентности на sqlite).**
- Построить сценарий: один `Portal`, один аккаунт (мастер) с `portal`, набор `TimesheetItem`/`ProjectCard` с проставленным `portal` (как после backfill) И без дублей (как после dedupe). На таких данных:
  - `build_filtered_timesheet_queryset(account, params)` при OFF фильтрует по `bitrix24_account=account`, при ON — по `portal=account.portal`. Поскольку у единственного аккаунта все его данные принадлежат тому же portal, результаты ДОЛЖНЫ совпасть по составу (множество pk одинаково).
  - Аналогично проверить `get_project_card_queryset(account)`.
- **Ключевой инвариант:** для данных, где `bitrix24_account=account` ⟺ `portal=account.portal` (один аккаунт на portal, backfill сделан), результат идентичен при обоих значениях флага. Это и есть «эквивалентность».
- **Сценарий «двух аккаунтов после дедупа»:** два аккаунта одной компании, но данные ОДНИ (после дедупа — одна копия на portal, привязанная к одному из аккаунтов). При OFF отчёт аккаунта A видит ТОЛЬКО его записи, аккаунта B — только его (разные!) — это и есть текущая болезнь (расхождение). При ON оба видят ОДНО (portal). Тест фиксирует: ON даёт обоим аккаунтам одинаковый (полный) результат, OFF — разный. Это демонстрирует, ЗАЧЕМ переключение (а не только эквивалентность для одиночного аккаунта).

**Шаг 1. Падающий тест** — Create `main/tests_portal_scoping_equivalence.py` (Django-`TestCase`, `@override_settings`):
```python
"""Эквивалентность отчётов при account- и portal-скоупинге (задача 4.4).

Доказывает: на данных, приведённых к виду «один Portal, backfill сделан,
дублей нет», отчёт даёт ОДИНАКОВЫЙ результат при USE_PORTAL_SCOPING=False и True.
И демонстрирует, что при двух аккаунтах одной компании portal-скоупинг устраняет
расхождение отчётов (текущая болезнь).
"""
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Bitrix24Account, Portal, TimesheetItem, ProjectCard
from .report_queries import build_filtered_timesheet_queryset
from .project_board_shared import get_project_card_queryset


def _portal(member_id="m1"):
    return Portal.objects.create(member_id=member_id, domain_url=f"{member_id}.b24.ru", status="active")


def _account(portal, *, master=False, b24_user_id=1):
    return Bitrix24Account.objects.create(
        b24_user_id=b24_user_id, is_b24_user_admin=True, member_id=portal.member_id,
        is_master_account=master, domain_url=portal.domain_url, status="active",
        application_version=1, portal=portal,
    )


def _ts(account, portal, bitrix_id, *, project_id="100", hours=1.0):
    return TimesheetItem.objects.create(
        bitrix24_account=account, portal=portal, bitrix_id=bitrix_id,
        task_id="1", employee_id="1", hours=hours, project_id=project_id,
        project_title="Проект", date_reflection=timezone.now(),
    )


class ReportEquivalenceTest(TestCase):
    def _ids(self, queryset):
        return sorted(str(pk) for pk in queryset.values_list("pk", flat=True))

    def test_single_account_report_identical_on_and_off(self):
        portal = _portal()
        acc = _account(portal, master=True, b24_user_id=1)
        _ts(acc, portal, 100)
        _ts(acc, portal, 200)
        params = {}

        with override_settings(USE_PORTAL_SCOPING=False):
            off_ids = self._ids(build_filtered_timesheet_queryset(acc, params))
        with override_settings(USE_PORTAL_SCOPING=True):
            on_ids = self._ids(build_filtered_timesheet_queryset(acc, params))

        self.assertEqual(off_ids, on_ids)   # эквивалентность
        self.assertEqual(len(on_ids), 2)

    def test_project_cards_identical_on_and_off(self):
        portal = _portal()
        acc = _account(portal, master=True, b24_user_id=1)
        ProjectCard.objects.create(bitrix24_account=acc, portal=portal, project_id="100", project_name="P", stage="new")
        ProjectCard.objects.create(bitrix24_account=acc, portal=portal, project_id="200", project_name="Q", stage="new")

        with override_settings(USE_PORTAL_SCOPING=False):
            off_ids = self._ids(get_project_card_queryset(acc))
        with override_settings(USE_PORTAL_SCOPING=True):
            on_ids = self._ids(get_project_card_queryset(acc))
        self.assertEqual(off_ids, on_ids)

    def test_two_accounts_portal_scoping_unifies_view(self):
        # После дедупа: данные компании привязаны к ОДНОМУ аккаунту, но к общему portal.
        portal = _portal()
        master = _account(portal, master=True, b24_user_id=1)
        other = _account(portal, master=False, b24_user_id=2)
        # Одна копия на компанию (после дедупа), принадлежит мастеру.
        _ts(master, portal, 100)
        _ts(master, portal, 200)
        params = {}

        # OFF: мастер видит 2, other видит 0 -> РАСХОЖДЕНИЕ (текущая болезнь).
        with override_settings(USE_PORTAL_SCOPING=False):
            master_off = self._ids(build_filtered_timesheet_queryset(master, params))
            other_off = self._ids(build_filtered_timesheet_queryset(other, params))
        self.assertEqual(len(master_off), 2)
        self.assertEqual(len(other_off), 0)
        self.assertNotEqual(master_off, other_off)

        # ON: оба видят ОДНО И ТО ЖЕ (portal) -> расхождение устранено.
        with override_settings(USE_PORTAL_SCOPING=True):
            master_on = self._ids(build_filtered_timesheet_queryset(master, params))
            other_on = self._ids(build_filtered_timesheet_queryset(other, params))
        self.assertEqual(master_on, other_on)
        self.assertEqual(len(master_on), 2)

    def test_fallback_when_portal_empty_matches_off(self):
        # Аккаунт без portal (backfill не добил): ON ведёт себя как OFF (фолбэк).
        portal = _portal()
        acc_no_portal = Bitrix24Account.objects.create(
            b24_user_id=9, is_b24_user_admin=True, member_id="m1", is_master_account=False,
            domain_url="m1.b24.ru", status="active", application_version=1, portal=None,
        )
        # Запись привязана к аккаунту без portal (portal=None).
        TimesheetItem.objects.create(
            bitrix24_account=acc_no_portal, portal=None, bitrix_id=300,
            task_id="1", employee_id="1", hours=1.0, date_reflection=timezone.now(),
        )
        params = {}
        with override_settings(USE_PORTAL_SCOPING=False):
            off_ids = self._ids(build_filtered_timesheet_queryset(acc_no_portal, params))
        with override_settings(USE_PORTAL_SCOPING=True):
            on_ids = self._ids(build_filtered_timesheet_queryset(acc_no_portal, params))
        self.assertEqual(off_ids, on_ids)   # фолбэк: portal пуст -> account-скоупинг
        self.assertEqual(len(on_ids), 1)
```

**Шаг 2. Запуск (ожидание: PASS — если волны 4-5 выполнены).** `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_portal_scoping_equivalence --settings=test_settings` → зелёные. Если упало — значит какая-то точка скоупинга в `report_queries`/`project_board_shared` не переведена или переведена неверно (диагностика расхождения).

**Шаг 3. Реализация.** Тест — это и есть артефакт; «реализация» — убедиться, что волны 4-5 переведены корректно. Если тест падает на `test_single_account_report_identical_on_and_off` — проверить `report_queries.py:29`. Если на cards — `project_board_shared.py:161`.

**Шаг 4. Доклад.** Тест эквивалентности зелёный: на приведённых данных отчёт идентичен при OFF и ON; при двух аккаунтах portal-скоупинг устраняет расхождение (демонстрация ценности); при пустом portal ON падает в фолбэк = OFF. Это инвариант безопасности переключения.

---

## Задача 4.5 — Ревизия Части A [соннет]

**Файлы:** без правок (только чтение + прогон).

**ТЗ ревизии:**
1. **Перепроверить 4.0-4.4 по коду** (чтением, не на память):
   - 4.0: `models.py` — модель `Portal` (`member_id` unique, `db_table="portal"`); nullable FK `portal` (SET_NULL) в `Bitrix24Account`/`TimesheetItem`/`ProjectCard`; существующие `unique_together` НЕ изменены; миграции `0014_portal_and_nullable_fk` (структура) + `0015_seed_portals_from_member_id` (data, обратима); `portal_seed.seed_portals_from_accounts` идемпотентна.
   - 4.1: `backfill_portal_links` (команда + сервис) — `portal__isnull=True`, батчи UPDATE, считает unlinked; идемпотентна.
   - 4.2: `dedupe_portal_data` — dry-run по умолчанию (без `--apply` НЕ удаляет), выбор мастер→свежайшая, предохранитель backfill_incomplete; НЕ миграция.
   - 4.3-helper: `tenant_scoping.scope_to_tenant(account, write=False)` — OFF→account, ON+portal→portal (read) / portal+account (write), ON+пусто→account; `USE_PORTAL_SCOPING` в settings (env, дефолт False).
   - 4.3-точки: ВСЕ 19 DATA-точек (12 read + 7 write) переведены на `scope_to_tenant`; 6 AUDIT-точек (middleware:122, project_budget_notifier:281, project_board_service:1239, views:1860/1894, configuration_service:16-параметр) НЕ тронуты.
   - 4.3-lock: `_lock_subject_pk` (OFF→account.pk, ON+portal→portal.pk); `_advisory_key`/`account_sync_lock`-сигнатура не менялись.
   - 4.4: тест эквивалентности зелёный.
2. **Главный инвариант — флаг OFF = БИТ-в-БИТ.** Полный прогон существующих тестов при дефолтном флаге (OFF):
   - Django-семейство пофайльно через `manage.py test --settings=test_settings`: `tests_reports` (база 41/2-известные), `tests_report_excel`, `tests_report_excel_guard`, `tests_scheduled_sync`, `tests_inn_backfill`, `tests_security_logs`, `tests_security_excel_cors`, `tests_security_ratelimit`, `tests_security_roles`, `tests_sync_threshold`, `tests_sync_lock`, `tests_user_cache`, `tests_report_perf`, `tests_sync_honest_errors`.
   - Новые модули спринта 4 через `manage.py test`: `tests_portal_model`, `tests_portal_backfill`, `tests_portal_dedupe`, `tests_tenant_scoping`, `tests_portal_lock`, `tests_portal_scoping_equivalence`.
   - Автономные через unittest (`cd backends/python && api/.venv/bin/python -m unittest api.main.<модуль>`): `tests_fetch_paginated_batch`, `tests_project_fetch_keyset`, `tests_sync_scoped`, `tests_inn_apply_batch`, `tests_sync_integration`. Перед прогоном — `grep -n "sys\.modules\[" main/tests_*.py` (НЕ `-l "sys.modules"` — ложное срабатывание на докстринг `tests_scheduled_sync`), убедиться, что новые модули 4.x НЕ содержат `sys.modules[` и НЕ делают `django.setup()` на верхнем уровне.
3. **Grep-проверки:**
   - Все 19 DATA-точек содержат `scope_to_tenant`: `grep -rn "scope_to_tenant" main/report_queries.py main/project_board_shared.py main/project_board_service.py main/project_budget_service.py main/project_sync_service.py main/timesheet_sync_service.py main/views.py`.
   - 6 AUDIT-точек ОСТАЛИСЬ на `bitrix24_account=`: `grep -n "bitrix24_account=" main/middleware.py main/project_budget_notifier.py` (по 1) + `grep -n "bitrix24_account=self.account" main/project_board_service.py` (только 1239) + `grep -n "bitrix24_account=request.bitrix24_account" main/views.py` (только 1860/1894).
   - `tenant_scoping.py` содержит `USE_PORTAL_SCOPING`; `settings.py` определяет `USE_PORTAL_SCOPING` через env с дефолтом False.
   - Миграции: `ls main/migrations/0014* main/migrations/0015*` существуют; `0016` (contract) в спринте 4 НЕ создан (это Часть B).
   - `_lock_subject_pk` присутствует в `sync_lock.py`.
4. **Проверка обратимости миграций (на sqlite):**
   - `./.venv/bin/python manage.py migrate main 0013 --settings=test_settings` (откат до 0013) затем `./.venv/bin/python manage.py migrate main --settings=test_settings` (накат обратно) — обе стороны проходят без ошибок (0015 имеет `backwards`). **ВНИМАНИЕ:** делать на ОТДЕЛЬНОЙ тестовой БД, не на `test.sqlite3`, который раннер создаёт/удаляет сам; или в одноразовой среде. Это проверка обратимости, не данных.
5. **Синтетическая проверка предохранителя этапа 4 (на sqlite):** убедиться, что БЕЗ дедупа уникальный индекс упал бы. Это проверяется в Части B (миграция 0016 написана, но не применяется); ревизия Части A лишь фиксирует, что дедуп работает (тест 4.2) и что 0016 НЕ применён.

**Отчёт ревизии:** по каждой задаче 4.0-4.4 — закрыто/не закрыто, с прогонами и результатами; явно подтвердить главный инвариант (флаг OFF → все 148 существующих тестов зелёные, новые тесты 4.x зелёные); список всех переведённых точек и всех сохранённых AUDIT-точек; подтвердить, что Часть B (этап 4) НЕ выполнялась.

---

# ЧАСТЬ B — ГЕЙТ (в спринте 4 НЕ выполняется; процедура прод-выката)

> **Эта часть в спринте 4 НЕ исполняется.** Миграция этапа 4 написана ниже как код (чтобы была готова и отревьюена), но это **ТОЧКА НЕВОЗВРАТА**. Она применяется на проде ТОЛЬКО после: (1) прогона всей Части A на КОПИИ боевой БД; (2) проверки эквивалентности отчётов на копии; (3) явного решения заказчика. Прод-копию создаёт заказчик на своей инфраструктуре (Timeweb) — в среде разработки её создать нельзя (Docker не запущен, доступа к бою нет).

## Этап 4 — contract: portal NOT NULL + portal-уникальность + снятие старых ограничений + удаление сирот

**Файл (НАПИСАТЬ, НЕ ПРИМЕНЯТЬ в спринте 4):** `main/migrations/0016_portal_contract.py`.

**Что делает (необратимо по сути — точка невозврата):**
1. Удаляет «осиротевшие» записи без portal, которые попадут под portal-уникальность (страховка — их быть не должно после backfill; но дубли по portal — должны быть устранены дедупом ДО этого).
2. Делает `TimesheetItem.portal` и `ProjectCard.portal` **NOT NULL** (`AlterField` null=False).
3. Заменяет `unique_together`: `TimesheetItem` → `("portal", "bitrix_id")`; `ProjectCard` → `(("portal", "project_id"), ("portal", "project_item_id"))`. Снимает старые `("bitrix24_account", ...)`-ограничения.
4. (Опционально, по решению) меняет индексы `TimesheetItem` с префикса `bitrix24_account` на `portal` (для производительности отчётов под portal-скоупингом). Это можно отложить в отдельную миграцию 0017.
5. `Bitrix24Account.portal` оставляем nullable (учётка может теоретически висеть без portal); FK `bitrix24_account` на данных ОСТАВЛЯЕМ как аудит-поле «кто принёс запись» (НЕ удаляем — дёшево, полезно для расследований).

**Код миграции (ориентир — точные имена `unique_together`/индексов сверить с `0001_initial` и `0007_timesheetitem_query_indexes`):**
```python
from django.db import migrations, models
import django.db.models.deletion


def delete_orphans(apps, schema_editor):
    """Удаляет записи без portal (страховка перед NOT NULL).

    После backfill таких быть не должно (кроме аккаунтов без member_id —
    их данные тоже без portal). Это последний рубеж: без portal запись не
    может жить под portal-уникальностью.
    ВАЖНО: дубли по (portal, bitrix_id) должны быть устранены командой
    dedupe_portal_data ДО этой миграции, иначе AlterUniqueTogether упадёт.
    """
    TimesheetItem = apps.get_model("main", "TimesheetItem")
    ProjectCard = apps.get_model("main", "ProjectCard")
    TimesheetItem.objects.filter(portal__isnull=True).delete()
    ProjectCard.objects.filter(portal__isnull=True).delete()


def noop_reverse(apps, schema_editor):
    # Откат удаления сирот невозможен (данные удалены). Точка невозврата.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("main", "0015_seed_portals_from_member_id"),
    ]
    operations = [
        migrations.RunPython(delete_orphans, noop_reverse),
        # Снять старые уникальные ограничения ПЕРЕД установкой новых.
        migrations.AlterUniqueTogether(name="timesheetitem", unique_together=set()),
        migrations.AlterUniqueTogether(name="projectcard", unique_together=set()),
        # portal -> NOT NULL.
        migrations.AlterField(
            model_name="timesheetitem",
            name="portal",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="timesheets", to="main.portal",
            ),
        ),
        migrations.AlterField(
            model_name="projectcard",
            name="portal",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="project_cards", to="main.portal",
            ),
        ),
        # Новые portal-уникальные ограничения.
        migrations.AlterUniqueTogether(
            name="timesheetitem",
            unique_together={("portal", "bitrix_id")},
        ),
        migrations.AlterUniqueTogether(
            name="projectcard",
            unique_together={("portal", "project_id"), ("portal", "project_item_id")},
        ),
    ]
```
> **Сверка перед написанием на проде:** (1) точные текущие `unique_together` берутся из `models.py` (`TimesheetItem`: `("bitrix24_account","bitrix_id")`; `ProjectCard`: два кортежа); (2) на этапе 4 модель `models.py` тоже правится (portal NOT NULL, `unique_together` на portal, `on_delete=CASCADE` для portal) — это часть Части B, в спринте 4 НЕ делается; (3) изменение `on_delete` FK `portal` с SET_NULL на CASCADE — осознанное (после contract удаление Portal каскадит данные компании, это корректно). Миграция и правка модели идут вместе на этапе 4.

## Порядок прод-выката (выполняет заказчик на своей инфраструктуре, ПОСЛЕ спринта 4)

> Всё ниже — на КОПИИ боевой БД сначала, затем на бою. Среда разработки этого сделать не может (нет доступа к Postgres-копии бойцов).

1. **Подготовка копии (заказчик).** Снять копию боевой Postgres-БД на отдельном стенде. Применить миграции Части A: `python manage.py migrate main 0015 --noinput` (накатит 0014 структуру + 0015 seed Portal + Bitrix24Account.portal). Прод при этом продолжает работать (флаг OFF, FK данных пустые).
2. **Backfill на копии.** `python manage.py backfill_portal_links --batch-size 5000`. Проверить отчёт: `timesheets_unlinked`/`cards_unlinked` должны быть 0 (или объяснимое число для аккаунтов без member_id). Идемпотентно — можно повторять.
3. **Синк представителей до полноты (снижение риска дедупа).** Перед дедупом прогнать `python manage.py sync_all_portals --days <широкое окно>` (или ручной синк представителей), чтобы копия мастер-аккаунта была максимально полной — тогда дедуп выберет полную копию (риск из спецификации «дедуп выберет неполную копию»).
4. **Дедуп — сначала DRY-RUN.** `python manage.py dedupe_portal_data` (без `--apply`). **Изучить отчёт:** сколько групп-дублей, сколько строк к удалению по TimesheetItem/ProjectCard. Сверить с ожиданием (на проде 131 аккаунт против 229 проектов → ожидаем заметное схлопывание). Если число к удалению выглядит подозрительно (например, к удалению идёт почти всё) — НЕ применять, разбираться.
5. **Дедуп — APPLY (на копии).** `python manage.py dedupe_portal_data --apply`. Затем повторный dry-run должен показать 0 групп-дублей (всё схлопнуто).
6. **Включить двойное чтение на копии.** Выставить env `USE_PORTAL_SCOPING=true`, перезапустить. **Проверить эквивалентность отчётов на копии вручную:** открыть ключевые отчёты под несколькими аккаунтами одной компании — они должны показывать ОДНО И ТО ЖЕ (расхождение устранено) и совпадать с тем, что показывал мастер-аккаунт при OFF. Это ручной аналог теста 4.4 на боевых данных.
7. **Наблюдение на копии.** Прогнать синк (ручной + авто `sync_all_portals`) под флагом ON: убедиться, что синк не плодит дубли (portal-lookup в `_save_batch` находит существующую копию), orphan-deletion не удаляет лишнего (данные уже дедуплицированы — одна копия на компанию).
8. **Этап 4 на копии (ТОЧКА НЕВОЗВРАТА — сначала на копии!).** Применить миграцию 0016: `python manage.py migrate main 0016 --noinput`. Если `AlterUniqueTogether` упал — значит остались дубли (вернуться к шагу 4-5). Если прошёл — portal-уникальность включена, схема сжата.
9. **Решение заказчика и выкат на бой.** Только после успешного полного цикла на копии и явного решения заказчика — повторить шаги 1-8 на боевой БД в окно низкой нагрузки, с мониторингом блокировок Postgres. **На бою между шагом 6 (флаг ON) и шагом 8 (этап 4) выдержать период наблюдения** (например сутки) с возможностью мгновенного отката.

## План отката (по этапам)

- **До этапа 4 (шаги 1-7) — откат ДЁШЕВЫЙ и БЫСТРЫЙ:**
  - **Мгновенный:** `USE_PORTAL_SCOPING=false` + перезапуск → чтение/запись мгновенно возвращаются на account-скоупинг (account-данные на месте, FK `bitrix24_account` не тронут). Это первый рубеж при ЛЮБОЙ проблеме после включения флага.
  - **Откат backfill/seed:** миграции 0015→0014→0013 обратимы (`backwards` у 0015 снимает `Bitrix24Account.portal` и удаляет Portal; 0014 удаляет таблицу и FK). FK `portal` на данных при откате 0014 удаляются вместе с колонкой. Данные `TimesheetItem`/`ProjectCard` (привязка к account) НЕ затронуты.
  - **Откат дедупа:** дедуп УДАЛЯЕТ дубли — это необратимо в рамках команды. НО до этапа 4 удалённые дубли — это лишние копии (одна компания их и так не должна иметь); «откат» = повторный синк всех аккаунтов (вернёт их копии). Поэтому дедуп на бою — только после dry-run и на копии сперва.
- **Этап 4 (шаг 8) — ТОЧКА НЕВОЗВРАТА:** после удаления сирот и снятия старых `unique_together` откат к account-скоупингу уже НЕ эквивалентен (старые уникальные ограничения сняты, часть данных удалена). Откат возможен только восстановлением из бэкапа БД, снятого ПЕРЕД шагом 8. Поэтому шаг 8 — только после длительного наблюдения под флагом ON (шаг 7) и явного решения.

---

## Самопроверка плана

- **Покрыты ли все этапы спецификации?** Да. **Часть A:** 4.0 (этап 0 — Portal + nullable FK + seed-миграция, обратимо), 4.1 (этап 1 — backfill батчами, идемпотентно), 4.2 (этап 2 — dedupe с dry-run + выбор мастер-копии), 4.3-helper + 4.3-точки + 4.3-lock (этап 3 — флаг `USE_PORTAL_SCOPING` + перевод всех 19 DATA-точек + portal-ключ замка), 4.4 (эквивалентность), 4.5 (ревизия). **Часть B:** этап 4 (contract) написан как код 0016 + процедура прод-выката + план отката, явно НЕ исполняется в спринте 4.
- **Нет ли «TBD» / «добавить обработку»?** Нет: весь код приведён целиком (модель, FK, seed-хелпер, обе data-миграции, обе команды + их сервисы, помощник, все замены точек, портал-ключ замка, контракт-миграция, 6 тест-модулей). Константы конкретны (`DEFAULT_BATCH_SIZE=2000`, дедуп-батч 5000, имена миграций `0014_portal_and_nullable_fk`/`0015_seed_portals_from_member_id`/`0016_portal_contract`, флаг `USE_PORTAL_SCOPING` дефолт False). Места, требующие сверки с фактическим кодом (стиль чтения env в `settings.py`, точные имена `unique_together`/индексов для 0016, поведение `save(update_fields)` на historical-модели), помечены явными примечаниями «сверить чтением» — это защита от расхождения, не TBD реализации.
- **Совпадают ли имена функций/сигнатуры между задачами?** Сквозная сверка:
  - `scope_to_tenant(account, write=False)` (4.3-helper) — используется во ВСЕХ 7 файлах точек (4.3-reads-a/b, 4.3-views, 4.3-sync-ts, 4.3-sync-proj) с единой сигнатурой; импорт `from .tenant_scoping import scope_to_tenant`.
  - `Portal` (4.0) — импортируется в `portal_seed`, `portal_backfill_service`, `portal_dedupe_service`, `tenant_scoping` (через `account.portal`), всех тестах.
  - `seed_portals_from_accounts(portal_model, account_model)` (4.0) — зовётся из миграции 0015 и теста 4.0.
  - `backfill_portal_links(batch_size)` (4.1) — команда + тест.
  - `dedupe_portal_data(apply=False)` (4.2) — команда + тест; возвращает dict с ключами `applied`/`backfill_incomplete`/`timesheets`/`cards`.
  - `_lock_subject_pk(account)` (4.3-lock) — в `sync_lock.py` + тест `tests_portal_lock`; `account_sync_lock(account, scope)`-сигнатура НЕ менялась (вызовы в views-декораторе и `sync_scheduler_service` целы).
  - `USE_PORTAL_SCOPING` — определён в `settings.py`, читается `tenant_scoping` и `sync_lock` через `getattr(settings, ...)`; в тестах переключается `@override_settings`.
- **Совпадение фикстур:** все Django-тесты создают `Bitrix24Account.objects.create(...)` с обязательными полями (`b24_user_id`, `is_b24_user_admin`, `member_id`, `is_master_account`, `domain_url`, `status`, `application_version`) — как в `tests_reports`/`tests_scheduled_sync`. `TimesheetItem`/`ProjectCard` создаются с обязательными полями (`bitrix_id`, `task_id`, `employee_id`, `hours`, `date_reflection` для TS; `project_id`, `project_name`, `stage` для card).
- **Совпадение волн с непересечением:** доказано в таблице волн; критическая сериализация (`models.py` 4.0 первой волной; `tenant_scoping.py` 4.3-helper до точек) разводит запись общих зависимостей по волнам. В волнах 4-5 семь файлов точек разбиты на непересекающиеся группы.
- **Главный инвариант проверяем?** Да: каждая задача волн 4-5 в шаге проверки прогоняет регресс при флаге OFF (БИТ-в-БИТ); 4.5 прогоняет ВСЕ 148 существующих + 6 новых при OFF; 4.4 проверяет эквивалентность OFF vs ON.
- **Различие sqlite/Postgres учтено?** Да: раздел «Как запускать тесты» явно отделяет, что проверяется на sqlite (логика, эквивалентность, идемпотентность, dry-run), а что ТОЛЬКО на Postgres-копии (поведение unique-constraint на больших данных, блокировки, длительность этапа 4); ложное срабатывание `grep -l sys.modules` на `tests_scheduled_sync` явно отмечено.

## Ручная проверка для заказчика (простыми словами)

> В спринте 4 выполняется ТОЛЬКО Часть A (подготовка, обратимо). Боевые данные при этом НЕ меняются — приложение работает в точности как сейчас, потому что переключатель `USE_PORTAL_SCOPING` по умолчанию ВЫКЛЮЧЕН.

1. **Появилась сущность «компания».** В базе заведена таблица «Portal» — по одной строке на каждую компанию (по её идентификатору `member_id`). Это фундамент для хранения «одна копия на компанию». Пока она просто создана и связана с учётками; на данные это не влияет.
2. **Данные помечены принадлежностью к компании (но не переехали).** Готова команда, которая проставляет каждой записи времени и каждой карточке проекта её компанию (батчами, безопасно, можно запускать повторно). На боевых данных это запускается отдельно и осознанно, не при обычном обновлении.
3. **Готова безопасная «склейка дублей» с предпросмотром.** Сегодня у компании с несколькими сотрудниками данные дублируются. Сделана команда, которая находит дубли и оставляет одну правильную копию (приоритет — копия главного аккаунта, иначе самая свежая). **По умолчанию она ничего не удаляет** — только показывает отчёт «столько-то дублей, столько-то будет удалено». Реальное удаление — только по явной команде и сначала на копии боевой базы.
4. **Переключатель «одна копия на компанию» (пока выключен).** Введён единый переключатель. Когда он ВЫКЛЮЧЕН (как сейчас по умолчанию) — приложение ведёт себя в точности как раньше, каждый сотрудник видит свою копию. Когда его ВКЛЮЧАТ (после склейки дублей) — все руководители одной компании начнут видеть одни и те же данные (расхождение отчётов между ними исчезнет).
5. **Доказано, что переключение безопасно.** Написан автотест, который на одинаковых данных сравнивает отчёт с выключенным и включённым переключателем и подтверждает: результат совпадает. Дополнительно тест показывает, что при включении два руководителя одной компании начинают видеть одно и то же (то, ради чего всё затевается).
6. **Ничего из работающего не сломалось.** Базовый набор автотестов (148 проверок) остаётся зелёным при выключенном переключателе (2 давно известные ошибки в финансовом модуле — не новые). Это и есть гарантия «как было».
7. **Что нужно от вас ПОСЛЕ спринта 4 (отдельная операция на вашей инфраструктуре).** Финальный переезд (включить «одну копию на компанию» на бою и сжать схему) — это **точка невозврата**, и она делается НЕ в этом спринте. Порядок (он расписан в плане, Часть B): на КОПИИ боевой базы прогнать пометку компаний → предпросмотр склейки → склейку → включить переключатель → проверить отчёты вручную → и только потом, по вашему решению и с резервной копией, повторить на бою. Копию боевой базы создаёте вы (у разработки нет доступа к боевым данным).

---

## Открытые вопросы — решить ДО старта волны 1

1. **Правило выбора «правильной» копии при дедупе (задача 4.2) — КРИТИЧНО.** Принято: мастер-аккаунт портала → при отсутствии свежайшая копия (max `updated_at`, tie-break по `b24_user_id`). Альтернатива — «копия с максимумом непустых полей» (буквально «максимум данных»). Рекомендация: свежайшая копия (синк — upsert, свежайшая = наиболее полная), плюс перед дедупом синкнуть представителей до полноты (шаг 3 прод-выката). Нужно подтверждение, что мастер-аккаунт на проде действительно держит самую полную копию, ИЛИ что свежайшая копия — приемлемый критерий. Если у вас есть знание, чья копия «эталонная» — назвать его, уточним правило.
2. **AUDIT-точки остаются на `bitrix24_account` (задачи 4.3-*).** Принято: 6 точек записи/чтения логов (`RequestLog`/`SystemLog` в middleware, notifier, board_service, views) и параметр конструктора `ConfigurationService` НЕ переводятся на portal — логи привязаны к пользователю-источнику («кто породил»), не к компании. Рекомендация: оставить как есть (аудит «кто» важнее агрегации по компании; просмотр логов руководителем по своей учётке — текущее поведение). Подтвердить, что просмотр логов остаётся per-user, а не per-company.
3. **Дефолт и способ хранения флага `USE_PORTAL_SCOPING` (задача 4.3-helper).** Принято: env-переменная, дефолт `False` (глобально на инстанс, не per-portal). Альтернатива — per-portal флаг (часть компаний на portal-скоупинге, часть нет) для постепенного выката. Рекомендация: глобальный env-флаг для спринта 4 (проще, безопаснее; постепенный выкат на проде делается порядком Части B, а не флагом на компанию). Если нужен поэтапный выкат по компаниям — это усложнит `scope_to_tenant` (читать флаг из конфига портала) и тесты; решить заранее.
4. **Порядок «дедуп → флаг» как жёсткая гарантия (задачи 4.3-helper, 4.3-sync-*).** Принято: на проде флаг `USE_PORTAL_SCOPING` включается ТОЛЬКО после дедупа — иначе orphan-deletion и создание под portal могут плодить/удалять дубли в переходном состоянии. Это гарантируется порядком прод-выката (Часть B, шаги 4-6), а не кодом. Альтернатива — техническая блокировка (например, помощник отказывается работать в write-режиме, если в portal есть дубли) — это дороже и в спринте 4 не реализуется. Рекомендация: полагаться на порядок выката (он на копии прода проверяется до боя). Подтвердить, что операционный порядок приемлем как гарантия.
5. **Политика `on_delete` для FK `portal` (задачи 4.0 и этап 4).** Принято: на этапах 0-3 (Часть A) — `SET_NULL` (удаление Portal не каскадит данные, безопасно при переезде); на этапе 4 (Часть B) — `CASCADE` (после сжатия удаление компании каскадит её данные). Рекомендация: так и сделать (SET_NULL на переезде, CASCADE после). Подтвердить, что каскадное удаление данных при удалении Portal после этапа 4 — желаемое поведение (компания удаляется → её данные удаляются).
6. **Старт спринта 4 и кто исполняет Часть B.** Часть A исполняется в спринте 4 (агентами, обратимо). Часть B (этап 4, точка невозврата) исполняется ЗАКАЗЧИКОМ на его инфраструктуре после спринта 4 (нужна копия боевой Postgres-БД, которой у разработки нет). Нужно ваше подтверждение: (1) запускать ли спринт 4 (оценка токенов — ниже); (2) кто и когда снимет копию боевой БД для Части B; (3) есть ли у вас окно низкой нагрузки для финального выката на бой.

---

## Оценка токенов (для оркестратора)

> Оценка по образцу спецификации (`multitenancy-redesign-spec.md`: «~250-350 тыс. токенов»). Разбита на Часть A (исполняется) и Часть B (только написание кода миграции + процедуры, без исполнения).

**ЧАСТЬ A (исполняется в спринте 4):**
- Волна 1 (4.0): модель + 2 миграции + seed-хелпер + тест — чтение `models.py`/миграций + написание. **~45-60k**.
- Волна 2 (4.1 + 4.2): 2 команды + 2 сервиса + 2 теста; дедуп — самая сложная логика (выбор копии, dry-run, предохранитель). **~55-70k**.
- Волна 3 (4.3-helper): помощник + флаг + тест; чтение `settings.py`/`test_settings.py`. **~20-30k**.
- Волны 4-5 (перевод 19 точек в 7 файлах + lock): много точечных правок + прогоны регресса после каждой; чтение контекста каждой точки. **~70-90k**.
- Волна 6 (4.4): тест эквивалентности (4 сценария) + диагностика, если падает. **~20-30k**.
- Волна 7 (4.5): ревизия — полный прогон всех тест-модулей (Django + автономные) + грепы + проверка обратимости миграций. **~30-45k**.
- **Итого Часть A: ~240-325k токенов.**

**ЧАСТЬ B (в спринте 4 только написание, НЕ исполнение):**
- Миграция 0016 (contract) написана как код в этом плане; на этапе исполнения спринта 4 её НЕ применяют и НЕ дописывают (она уже в плане). Дополнительных токенов в спринте 4 на Часть B практически нет — она задокументирована здесь. Если потребуется довести 0016 до файла-миграции в репозитории (как артефакт, но не применять) — **~10-15k** (написать файл + сверить имена unique_together/индексов чтением `0001_initial`/`0007`). Рекомендация: файл 0016 НЕ создавать в спринте 4 (чтобы случайно не примёнился в release-шаге); держать как код в плане до решения по Части B.
- **Итого Часть B в рамках спринта 4: ~0k** (документ) **или ~10-15k**, если решено материализовать файл 0016 (не применяя).

**ОБЩАЯ оценка спринта 4 (Часть A): ~240-325k токенов** — согласуется с оценкой спецификации (~250-350k). Часть B исполняется заказчиком отдельно и токенов агентов в спринте 4 не требует.
