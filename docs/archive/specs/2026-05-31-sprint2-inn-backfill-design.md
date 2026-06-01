# Спринт 2 — ИНН в карточках списания + дозаполнение для 1С

## Контекст (диагностика)

Выгрузка в 1С = отчёт «Сырые данные» (`export_raw_data`), который тянет поля **напрямую из смарт-процесса списания** Bitrix (`crm.item.list`). В смарт-процессе уже есть поля `OUR_INN` («Наш ИНН») и `CLIENT_INN` («ИНН клиента») — [installation_service.py:16-33](backends/python/api/main/installation_service.py) — но их **никто не заполняет**: моста «проект → ИНН → карточка списания» в коде нет. ИНН в системе живёт только в проектах (ProjectCard: `company_id`, `our_legal_entity_id`) и резолвится из реквизитов (`crm.requisite.list`, `RQ_INN`) лишь при отрисовке доски.

## Принятые решения

| Развилка | Решение |
|---|---|
| Где хранить ИНН | **Вариант A** — писать в поля `OUR_INN`/`CLIENT_INN` карточек списания (Bitrix, `crm.item.update`). Текущая выгрузка «Сырые данные» сразу заработает. |
| Стратегия | **Авто + ручной UI**: при синхронизации авто-простановка только в **пустые** поля; ручной UI — для старых/проблемных. |
| Источник ИНН | Оба из проекта: клиент ← `company_id`, наш ← `our_legal_entity_id` (резолв `RQ_INN`). |
| Размещение UI | Вкладка внутри отчёта «Сырые данные» (`raw-data.client.vue`). |
| Перезапись | Только пустые поля; заполненное (в т.ч. вручную) не трогаем. |

Мокап: [docs/internal/mockups/inn/01-inn-backfill-screen.html](docs/internal/mockups/inn/01-inn-backfill-screen.html).

## Архитектура

### Резолв ИНН (переиспортуем готовое)
- `get_companies()` → `[{id, name, inn}]` (все компании), `get_legal_entities()` → наши юрлица — [project_board_service.py:564-576](backends/python/api/main/project_board_service.py). Кэшируются.
- Карточка списания → проект: по `project_item_id`/`project_id` найти `ProjectCard` (`get_project_card_queryset`). Из карты: `company_id` → ИНН клиента, `our_legal_entity_id` → наш ИНН.

### Запись в Bitrix (образец существует)
- `self.client._bitrix_token.call_method("crm.item.update", {"entityTypeId": <sp>, "id": <bitrix_id>, "fields": {<mapping['client_inn']>: ..., <mapping['our_inn']>: ...}})` — как в `project_board_service._sync_project_card_to_project_spa`.
- Field-коды берём из `config['fields_mapping']['our_inn'|'client_inn']`. Throttle/retry — как в `timesheet_sync_service` (`THROTTLE_DELAY=0.5`, `MAX_RETRIES=5`).
- Пишем только непустые значения и только в пустые поля карточки.

### Определение «пусто ли ИНН»
Текущее значение полей `OUR_INN`/`CLIENT_INN` хранится только в Bitrix (в нашей БД их нет). Поэтому **scan читает карточки из Bitrix** (`crm.item.list` за период с `select` даты + employee + task + project + поля ИНН) — так же, как `export_raw_data`. Резолв проекта/ИНН — из нашей БД (ProjectCard) + кэш компаний.

## Этапы реализации

### Этап A — бэк-ядро (сервис + endpoints)
- **Новый** `backends/python/api/main/inn_backfill_service.py`:
  - `scan(account, client, config, date_from, date_to, project_ids)` → читает карточки из Bitrix, отбирает где `OUR_INN`/`CLIENT_INN` пусты, резолвит проект+ИНН, группирует по проекту, считает KPI (всего/без ИНН/можно проставить/требуют внимания). Возвращает структуру для UI.
  - `apply(account, client, config, items)` → пишет `crm.item.update` пачкой (throttle), только непустые значения; возвращает `{updated, failed[]}`.
- **views.py**: `inn_backfill_scan` (GET, `@auth_required`), `inn_backfill_apply` (POST, `@auth_required`); регистрация в `__all__`.
- **urls.py**: `api/inn-backfill/scan`, `api/inn-backfill/apply`.
- Тесты: резолв ИНН (клиент/наш), фильтр пустых, запись (мок Bitrix-клиента).

### Этап B — фронт UI (вкладка в «Сырых данных»)
- `raw-data.client.vue`: добавить переключатель вкладок (вручную, `ref activeTab` + `v-if` — готового `B24Tabs` в проекте нет): «Выгрузка» (текущее) и «Дозаполнение ИНН».
- **Новый** `components/reports/InnBackfillPanel.vue`: фильтры (период/проект), KPI (`ReportMetricCard`), таблица с группировкой по проекту, чекбоксы массового выбора, ручной ввод для проблемных, кнопки «Заполнить всё возможное» / «Проставить выбранным».
- `stores/api.ts`: `scanInnBackfill(...)`, `applyInnBackfill(...)` (POST с JWT, образец `exportRawData`/`createFinanceOperation`).

### Этап C — авто-простановка при синхронизации
- `timesheet_sync_service.py`: после синка добавить шаг — для карточек с пустыми `OUR_INN`/`CLIENT_INN` и резолвимым проектом записать ИНН (только пустые). Добавить поля ИНН в `select` при чтении, чтобы знать пустоту. Под флагом/безопасно по throttle.

### Этап D — ревью, верификация, лог
- `requesting-code-review`; `verification-before-completion`; запись в `docs/CHANGELOG.md` + пользовательская строка в `RELEASES.md` (Задача 3).

## Риски
- Объём `crm.item.update` при первом backfill (тысячи карточек) → throttle + прогресс + батч-лимит на запрос; UI пишет выбранными порциями.
- Поля `OUR_INN`/`CLIENT_INN` должны быть созданы и быть в `fields_mapping` — на этапе A проверить наличие; если нет — явная ошибка с подсказкой создать поля (`create_fields_only`).
- Карточки без проекта / проект без ИНН → не авто, только ручной ввод (показываем статусом).
- Рассинхрон scan/apply (значение изменилось между ними) — низкий риск; apply пишет переданное.

## Верификация (e2e)
1. `make dev-python`, открыть «Сырые данные» → вкладка «Дозаполнение ИНН».
2. Период → «Найти»: KPI и группировка по проектам корректны, статусы (есть ИНН/нет в проекте/нет проекта) верны.
3. «Проставить выбранным» → проверить в Bitrix, что в карточках заполнились `OUR_INN`/`CLIENT_INN`.
4. Выгрузка «Сырые данные» с полями ИНН → значения присутствуют.
5. Авто: создать новую карточку → синхронизация проставила ИНН (если проект резолвится).
