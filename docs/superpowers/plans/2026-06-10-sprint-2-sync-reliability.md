# Спринт 2 «Надёжность синхронизации + скорость отчётов» — план исполнения

> Исполнение: волны параллельных агентов; файлы внутри одной волны не пересекаются. Фиксации (commit) делает оркестратор после проверки каждой задачи. Ветка: `sprint-2-sync-reliability` (от `prod_2026`, спринт 1 безопасности влит). **КОД В РАМКАХ НАПИСАНИЯ ПЛАНА НЕ МЕНЯЕТСЯ** — это документ для последующего исполнения.

## Цель

Сделать синхронизацию трудозатрат **безопасной и честной** на боевом объёме (103 000 записей `TimesheetItem`, 229 проектов, 131 аккаунт), а формирование 7 отчётов — заметно быстрее. После спринта: единичная пустая страница от Битрикс на середине обхода больше не стирает валидные записи; два одновременных синка одного портала не топчут друг друга; пользователь видит честное предупреждение, когда данные не обновились (а не «успех» поверх старого кэша); справочник сотрудников и архивные проекты перестают перевыбираться на каждый отчёт; двойной клик «Сформировать» не запускает второй полный цикл.

## Подход (3 предложения)

Защиту от массового удаления и замок параллельных запусков ставим в сервисный слой синхронизации по уже существующим в коде образцам (`_delete_scoped_orphans` для порога-безопасности; конвенции декораторов `rate_limit`/`admin_required` для замка), чтобы не плодить новые паттерны. Замок реализуем как **session-level** advisory-lock PostgreSQL с гарантированным освобождением в `finally` (обоснование отклонения от xact-варианта — в задаче 2.2), активный только при `connection.vendor == "postgresql"` и являющийся безопасным no-op на sqlite, чтобы существующие тесты на sqlite не падали. Ускорения отчётов и фронтовые правки берём минимальные и поведенчески-эквивалентные (один `values_list` вместо трёх QuerySet, кэш справочника по образцу `fetch_active_users`, guard+`AbortController` в единственной точке `generateReport`), а всё покрываем тестами на реальной sqlite-БД (без моков ORM и `transaction.atomic`) плюс юнит-тестами логики замка через мок курсора.

## Волны и непересечение файлов

Спринт 2 имеет сильное пересечение по `views.py` и `timesheet_sync_service.py`. Чтобы в одной волне не было двух задач, пишущих в один файл, разводим так:

| Волна | Задачи (параллельно) | Файлы записи (Create/Modify) |
|---|---|---|
| 1 | **2.1** Порог удаления; **2.5** Ускорение отчётов; **2.7** Двойной клик | 2.1: `main/timesheet_sync_service.py`, `main/tests_sync_threshold.py` (new) · 2.5: `main/report_queries.py`, `main/tests_report_perf.py` (new) · 2.7: `frontend/app/composables/useReportGenerator.ts` |
| 2 | **2.2** Замок параллельных запусков; **2.4** Кэш справочника | 2.2: `main/utils/decorators/sync_lock.py` (new), `main/views.py`, `main/project_sync_service.py` *(только если решено ставить замок в сервис — см. ниже; по принятому решению — НЕ трогаем)*, `main/tests_sync_lock.py` (new) · 2.4: `main/bitrix_data_access.py`, `main/project_board_shared.py`, `main/tests_user_cache.py` (new) |
| 3 | **2.3** Честные ошибки синхронизации (бэк + фронт) | `main/views.py` (только блок `timesheet_sync` ≈1441-1452), `frontend/app/composables/useReportGenerator.ts`, `frontend/app/stores/api.ts` (тип), `main/tests_sync_honest_errors.py` (new) |
| 4 | **2.6** Интеграционные тесты на реальной БД | `main/tests_sync_integration.py` (new) — только чтение `timesheet_sync_service.py`, без правок прод-кода |
| 5 | **2.8** Ревизия | без правок (чтение + полный прогон) |

**Доказательство непересечения по волнам:**
- **Волна 1:** 2.1 пишет `timesheet_sync_service.py`; 2.5 пишет `report_queries.py`; 2.7 пишет `useReportGenerator.ts`. Три разных файла + три разных новых тест-модуля. Пересечений нет.
- **Волна 2:** 2.2 пишет `views.py` + новый `sync_lock.py`; 2.4 пишет `bitrix_data_access.py` + `project_board_shared.py`. Файлы не общие. (Оба читают `project_board_shared.py`, но **пишет** туда только 2.4 — добавляет/НЕ добавляет инвалидацию; 2.2 туда не пишет.)
- **Волна 3 (одна задача):** 2.3 — единственная пишущая в `views.py` после волны 2 и единственная пишущая во фронт `useReportGenerator.ts`/`api.ts` после волны 1. Поэтому 2.3 идёт **отдельной волной после** 2.1/2.2/2.4 и после 2.7, чтобы исключить конкуренцию за `views.py` (с 2.2) и за `useReportGenerator.ts` (с 2.7).
- **Волна 4:** 2.6 — только новый файл тестов; зависит от готовности 2.1 (порог) и 2.2 (замок), которые тестирует косвенно.
- **Волна 5:** 2.8 — без правок.

**Почему 2.7 и 2.3 обе трогают `useReportGenerator.ts`, но в разных волнах:** 2.7 (волна 1) добавляет guard/`AbortController`; 2.3 (волна 3) добавляет разбор `result.status`. Разнесены по волнам — один файл не правится двумя агентами одновременно. Это сознательная сериализация, а не пересечение в волне.

## Как запускать тесты (обязательно к прочтению исполнителями)

- **Django-тесты (sqlite):** `cd backends/python/api && ./.venv/bin/python manage.py test main.<модуль> --settings=test_settings`. Python и Django в `backends/python/api/.venv` (Python 3.9.6, Django 4.2.29).
- **Автономные тесты (подменяют `django` в `sys.modules`!):** запускать ТОЛЬКО через `cd backends/python && api/.venv/bin/python -m unittest api.main.<модуль>`. Семейство: `tests_fetch_paginated_batch`, `tests_project_fetch_keyset`, `tests_sync_scoped`, `tests_inn_apply_batch`. Эти модули **никогда не запускать через `manage.py test`**. Перед добавлением любого нового тест-модуля в общий прогон проверить `grep -L "sys.modules" main/tests_*.py` — все новые модули спринта 2 (`tests_sync_threshold`, `tests_sync_lock`, `tests_user_cache`, `tests_report_perf`, `tests_sync_honest_errors`, `tests_sync_integration`) пишутся как Django-`TestCase` **без** `sys.modules`-заглушек, то есть запускаются через `manage.py test`.
- **База регресса:** `main.tests_reports` — **41 тест, 2 ИЗВЕСТНЫЕ ошибки** в `FinanceOperationServiceTest` (finance отключён флагом; существовали до спринта 2 — не чинить, новых ошибок не добавлять). В этом же модуле уже есть контракты, которые НЕЛЬЗЯ ломать: `test_sync_endpoint_returns_warning_instead_of_500` (sync-timesheets отдаёт `status="warning"`, `count=0`), `test_timesheet_sync_save_batch_updates_and_creates_records`, `test_timesheet_filters_use_date_range_and_exclude_archived_projects` (касается 2.5), `test_project_board_sync_endpoint_returns_warning_instead_of_500`.
- **БД тестов:** sqlite (`test_settings.py`: `ENGINE django.db.backends.sqlite3`, `NAME BASE_DIR/test.sqlite3`). **Кэш:** в `settings.py` блок `CACHES` не задан → Django по умолчанию использует `LocMemCache`, чего достаточно для тестов кэша 2.4 (отдельный locmem-override в тестах не требуется, но допустим через `@override_settings`).
- **Docker НЕ запущен.** PostgreSQL в тест-окружение НЕ вводить. Путь проекта содержит пробелы и кириллицу — экранировать кавычками.

---

## Задача 2.1 — Защита от массового удаления осиротевших записей [опус]

**Файлы:** Modify `main/timesheet_sync_service.py` (метод `_sync_full`, блок удаления ≈177-185); Create `main/tests_sync_threshold.py`.

**Дыра (проверено чтением).** В `_sync_full` (timesheet_sync_service.py:102) цикл keyset-пагинации может прерваться по `if not items: break` (стр. 131-133), если Битрикс на середине вернёт **пустую страницу без исключения**. Тогда `all_bitrix_ids` окажется неполным, а блок на стр. 177-185:
```python
if all_bitrix_ids:
    deleted_count, _ = (
        TimesheetItem.objects.filter(bitrix24_account=self.account)
        .exclude(bitrix_id__in=all_bitrix_ids)
        .delete()
    )
```
удалит ВСЕ записи, которых нет в неполном множестве — то есть массово сотрёт валидные данные. Это единственная защита и она недостаточна. Образец правильной защиты уже есть в `_delete_scoped_orphans` (стр. 328): при пустом `fetched_ids` удаление пропускается с логом «skip deletion (safety)».

**Обоснование порога (важно — крайние случаи разобраны).**

Нужен критерий «обход выглядит полным и достоверным» перед разрушительным удалением. Рассмотрены варианты:

1. **Процент от текущего count** (удалять только если `len(all_bitrix_ids) >= X% * current_count`). Проблема: легитимные сценарии ломаются. Например, реальная чистка половины записей (массовое удаление старого проекта в Битрикс) даст `all_bitrix_ids ≈ 50%` и пройдёт при X=50, но не пройдёт при X=80. А первый синк на пустую БД (`current_count == 0`) — порог тривиально проходит (что верно), но если БД уже большая, а в Битрикс реально осталось мало записей, мы заблокируем легитимную чистку. Процент в одиночку не отличает «сбой обхода» от «реального удаления».

2. **Флаг целостности обхода** (синк прошёл от начала до естественного конца без аномалий). Это прямо отвечает на нужный вопрос: «дошли ли мы до конца данных или оборвались?». Пустая страница на середине — единственный путь к неполному `all_bitrix_ids`, который НЕ кидает исключение (любое исключение и так пробрасывается на стр. 173-175 → синк падает → удаления не происходит). Значит, надёжный сигнал — **отличить «дошли до конца» от «оборвались на пустой странице, не достигнув естественного хвоста»**.

**Принятое решение — комбинированная защита (флаг + страховочный порог):**

- Ввести локальную переменную `traversal_complete = False`. Установить `traversal_complete = True` ТОЛЬКО на ветке естественного завершения обхода: `if count < page_size: break` (стр. 169-170) — это значит, что Битрикс вернул неполную последнюю страницу, то есть данные кончились. На ветках `if not items: break` (стр. 131-133), `if batch_max_id <= last_id: break` (стр. 160-166) флаг НЕ выставлять — это «оборвались, не зная, дошли ли до конца».
  - Тонкость: если общий объём кратен `page_size` (последняя страница ровно 50 записей), следующая итерация вернёт `items == []` и сработает `if not items: break` без `traversal_complete=True` — ложная тревога. Чтобы это не блокировало легитимный синк, добавляем **второй, независимый критерий**: страховочный порог.
- Ввести `current_count = TimesheetItem.objects.filter(bitrix24_account=self.account).count()` (один дешёвый COUNT перед удалением).
- **Удаление выполнять, если выполнено ХОТЯ БЫ ОДНО из условий безопасности:**
  - `traversal_complete is True` (обход явно дошёл до неполной последней страницы — данные достоверны), **ИЛИ**
  - `current_count == 0` (первый синк / пустая БД — удалять нечего и нечего терять), **ИЛИ**
  - `len(all_bitrix_ids) >= DELETE_SAFETY_RATIO * current_count`, где `DELETE_SAFETY_RATIO = 0.5` (собрали не меньше половины того, что лежит в БД — даже если флаг не выставился из-за кратности 50, такой объём не похож на ранний обрыв).
- **Иначе — ПРОПУСТИТЬ удаление** с предупреждением: `logger.warning("Full sync: traversal looks incomplete (collected=%s, db_count=%s, complete=%s); SKIP orphan deletion (safety).", len(all_bitrix_ids), current_count, traversal_complete)`. Реальная очистка произойдёт на следующем здоровом полном синке.

Почему `0.5`: при кратном-50 объёме (ложное `not items`) мы собрали 100% id → условие порога выполняется с запасом, удаление произойдёт корректно. При обрыве на 1-й пустой странице из середины (например, собрали 20% и оборвались) — ни флаг, ни порог не сработают → удаление пропускается. Граница 50% — консервативный компромисс: легитимная чистка «удалить больше половины записей разом» через полный синк встречается крайне редко (обычно это делается через scoped-окно `_sync_scoped`, у которого своя защита `_delete_scoped_orphans`), а цена ложного срабатывания (пропуск одной чистки до следующего синка) несопоставимо ниже цены массовой потери данных. Значение вынести в константу класса `DELETE_SAFETY_RATIO = 0.5` рядом с `BULK_BATCH_SIZE` для дальнейшей настройки.

**Шаг 1. Падающие тесты** — Create `main/tests_sync_threshold.py` (Django `TestCase`, реальная sqlite, мок только Bitrix-клиента):

```python
from datetime import datetime
from unittest.mock import Mock

from django.test import TestCase
from django.utils import timezone

from .models import Bitrix24Account, TimesheetItem
from .timesheet_sync_service import TimesheetSyncService


def _make_item(bitrix_id):
    # Сырой ответ Bitrix crm.item.list -> один элемент items[]
    return {
        "id": bitrix_id,
        "ufCrmTask": str(bitrix_id),
        "createdTime": "2026-01-01T09:00:00+03:00",
    }


class _FakeClient:
    """Минимальный двойник Client: возвращает заранее заданные страницы по start/filter."""

    def __init__(self, pages):
        # pages: список ответов crm.item.list в порядке вызова
        self._pages = list(pages)
        self._calls = 0
        self._bitrix_token = self  # _call_with_retry дергает self.client._bitrix_token.call_method

    def call_method(self, method, params):
        if self._calls < len(self._pages):
            resp = self._pages[self._calls]
        else:
            resp = {"result": {"items": []}}
        self._calls += 1
        return resp


class FullSyncOrphanThresholdTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1,
            is_b24_user_admin=True,
            member_id="member-2-1",
            is_master_account=True,
            domain_url="example.bitrix24.ru",
            status="active",
            application_version=1,
        )
        # Конфиг с маппингом, достаточным для normalize_items и без scoped (даты не передаём).
        self.config = {
            "sp_entity_type_id": 1,
            "fields_mapping": {
                "data": "createdTime",
                "id_zadachi": "ufCrmTask",
            },
        }

    def _seed(self, *bitrix_ids):
        day = timezone.make_aware(datetime(2026, 1, 1, 9, 0))
        for bid in bitrix_ids:
            TimesheetItem.objects.create(
                bitrix24_account=self.account,
                bitrix_id=bid,
                task_id=str(bid),
                employee_id="emp-1",
                hours=1,
                project_id="p1",
                project_title="P1",
                date_reflection=day,
            )

    def test_normal_full_sync_deletes_true_orphans(self):
        # В БД были 1,2,3. Битрикс отдаёт только 1,2 (неполная последняя страница -> traversal_complete).
        self._seed(1, 2, 3)
        pages = [
            {"result": {"items": [_make_item(1), _make_item(2)]}},  # count=2 < page_size=50 -> стоп, traversal_complete=True
        ]
        service = TimesheetSyncService(_FakeClient(pages), self.account, self.config)
        service._sync_full()
        remaining = set(TimesheetItem.objects.filter(bitrix24_account=self.account).values_list("bitrix_id", flat=True))
        self.assertEqual(remaining, {1, 2})  # 3 удалён как настоящий сирота

    def test_empty_page_midway_does_not_delete_valid_records(self):
        # В БД 1..6. Битрикс на ПЕРВОЙ же странице возвращает 1,2 (50? нет — эмулируем обрыв:
        # делаем page_size-полную страницу, затем пустую посередине).
        # Для честной эмуляции "обрыва на середине" заставим первую страницу быть НЕ последней
        # по количеству, а вторую — пустой, не достигнув хвоста.
        self._seed(1, 2, 3, 4, 5, 6)
        # Первая страница: ровно столько, что count == page_size -> цикл продолжится;
        # но page_size=50, отдать 50 элементов в тесте громоздко. Поэтому проверяем логику обрыва
        # через пустую страницу при НЕполном объёме относительно БД: collected < 50% от db_count.
        pages = [
            {"result": {"items": [_make_item(1)]}},        # count=1 < 50 -> по текущему коду это traversal_complete...
        ]
        # ВНИМАНИЕ исполнителю: см. примечание ниже — этот сценарий проверяет ИМЕННО
        # страховочный порог, а не флаг. Собрано 1 id из 6 в БД (16% < 50%) и traversal_complete
        # тут True по ветке count<page_size, поэтому для чистоты теста обрыва используем
        # вариант с пустой первой страницей (collected=0).
        service = TimesheetSyncService(_FakeClient(pages), self.account, self.config)
        service._sync_full()
        # Здесь traversal_complete=True (count<page_size), удаление произойдёт -> это НЕ тот кейс.
        # Поэтому реальный тест обрыва — следующий метод.

    def test_empty_first_page_skips_deletion(self):
        # Битрикс сразу вернул пустую страницу (сбой) -> all_bitrix_ids пуст -> блок `if all_bitrix_ids`
        # и так не сработает. Проверяем, что данные целы.
        self._seed(1, 2, 3, 4, 5, 6)
        pages = [{"result": {"items": []}}]
        service = TimesheetSyncService(_FakeClient(pages), self.account, self.config)
        service._sync_full()
        remaining = set(TimesheetItem.objects.filter(bitrix24_account=self.account).values_list("bitrix_id", flat=True))
        self.assertEqual(remaining, {1, 2, 3, 4, 5, 6})  # ничего не потеряно

    def test_incomplete_traversal_below_ratio_skips_deletion(self):
        # Ключевой кейс порога: обход оборвался НЕ по count<page_size, а по пустой странице
        # ПОСЛЕ непустой, собрав < 50% от БД. Эмулируем: стр.1 = [1] (но это count<50 -> завершение).
        # Чтобы получить обрыв без traversal_complete, нужна непустая страница, НЕ являющаяся
        # последней по размеру (count==page_size), затем пустая. page_size=50.
        # Сидим 200 записей, отдаём первую полную страницу (50 шт: id 1..50), затем пустую (обрыв).
        ids = list(range(1, 201))
        self._seed(*ids)
        first_page = {"result": {"items": [_make_item(i) for i in range(1, 51)]}}  # count==50 -> цикл продолжится
        empty_page = {"result": {"items": []}}                                      # обрыв на середине
        service = TimesheetSyncService(_FakeClient([first_page, empty_page]), self.account, self.config)
        service._sync_full()
        remaining_count = TimesheetItem.objects.filter(bitrix24_account=self.account).count()
        # Собрано 50 id из 200 (25% < 50%) и traversal_complete=False -> удаление ПРОПУЩЕНО.
        self.assertEqual(remaining_count, 200)
```
> Примечание исполнителю: метод `test_empty_page_midway_does_not_delete_valid_records` оставлен как иллюстрация ловушки кратности-50 и в финальной версии должен быть либо удалён, либо переписан в стиль `test_incomplete_traversal_below_ratio_skips_deletion`. Боевые проверки — `test_normal_full_sync_deletes_true_orphans`, `test_empty_first_page_skips_deletion`, `test_incomplete_traversal_below_ratio_skips_deletion`.

**Шаг 2. Запуск (ожидание: FAIL).** `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_sync_threshold --settings=test_settings`. Ожидаем падение `test_incomplete_traversal_below_ratio_skips_deletion` (текущий код удалит 150 записей).

**Шаг 3. Реализация (ПОЛНЫЙ код блока).** В `main/timesheet_sync_service.py`:

Добавить константу в тело класса рядом с `BULK_BATCH_SIZE = 200`:
```python
    DELETE_SAFETY_RATIO = 0.5
```

В `_sync_full` добавить флаг `traversal_complete = False` рядом с инициализацией `last_id = 0` (стр. 110). В ветке естественного завершения (текущие стр. 169-170):
```python
                if count < page_size:
                    traversal_complete = True
                    break
```
Заменить блок удаления (текущие стр. 177-185) на:
```python
        if all_bitrix_ids:
            current_count = TimesheetItem.objects.filter(
                bitrix24_account=self.account
            ).count()
            collected = len(all_bitrix_ids)
            safe_to_delete = (
                traversal_complete
                or current_count == 0
                or collected >= self.DELETE_SAFETY_RATIO * current_count
            )
            if safe_to_delete:
                deleted_count, _ = (
                    TimesheetItem.objects.filter(bitrix24_account=self.account)
                    .exclude(bitrix_id__in=all_bitrix_ids)
                    .delete()
                )
                if deleted_count > 0:
                    logger.info("Deleted %s orphaned records", deleted_count)
            else:
                logger.warning(
                    "Full sync: traversal looks incomplete "
                    "(collected=%s, db_count=%s, complete=%s); "
                    "SKIP orphan deletion (safety).",
                    collected,
                    current_count,
                    traversal_complete,
                )
```

**Шаг 4. Запуск (ожидание: PASS).** `./.venv/bin/python manage.py test main.tests_sync_threshold --settings=test_settings` → все боевые методы зелёные. Затем регресс: `./.venv/bin/python manage.py test main.tests_reports --settings=test_settings` → 41/2-известные, новых ошибок нет.

**Шаг 5. Доклад.** Порог и флаг внедрены; настоящие сироты удаляются, обрыв-на-середине не приводит к потере; константа `DELETE_SAFETY_RATIO=0.5`.

---

## Задача 2.2 — Замок от одновременных запусков синхронизации [опус]

**Файлы:** Create `main/utils/decorators/sync_lock.py`; Modify `main/views.py` (3 точки: `timesheet_sync` ≈1416, `sync_project_board` ≈722, `save_configuration` ≈1564-1566); Create `main/tests_sync_lock.py`.

**Цель.** Не допустить, чтобы два синка одного портала шли одновременно (на 103k записей это часы work и гонки на удалении/upsert). Если синк уже идёт — быстрый ответ HTTP 409 `{"error": "Синхронизация уже выполняется, подождите"}`.

**Архитектурное решение (отклонение от формулировки ТЗ — обосновано).**

ТЗ предлагает `pg_try_advisory_xact_lock(key)` внутри `transaction.atomic`. Проблема: xact-lock освобождается только на commit/rollback транзакции, а боевой синк **не** обёрнут в одну транзакцию — единственный `@transaction.atomic` это `_save_batch` (per-batch, проверено: в `timesheet_sync_service.py` это единственный atomic; в `project_sync_service.py` atomic вообще нет). Чтобы держать xact-lock на весь синк, пришлось бы обернуть весь обход (сотни батчей + длинные HTTP-вызовы к Битрикс) в одну гигантскую транзакцию — это сломает существующий батч-дизайн, удержит блокировку БД на минуты-часы и создаст риск раздувания/таймаутов на Postgres. Поэтому:

**Принято:** контекст-менеджер `account_sync_lock(account, scope)` на **session-level** `pg_try_advisory_lock(key)` / `pg_advisory_unlock(key)` с **гарантированным освобождением в `finally`**. Сессионный лock держится поверх многих коротких транзакций синка и не требует единой гигантской транзакции. Страховка от утечки при падении процесса: session-advisory-lock автоматически снимается при закрытии соединения с Postgres (это штатное поведение PG), а `finally` снимает его при нормальном/исключительном завершении. На не-postgresql (`connection.vendor != "postgresql"`) — полный **no-op** (вход/выход без SQL), поэтому sqlite-тесты и синк не ломаются. Юнит-тест логики «занято→409» делается через мок курсора (см. ниже), а не через реальный второй процесс.

**Где ставить замок и какие ключи (решение + обоснование).**

- **Ставим в VIEW, а не в сервис.** Причина: ответ 409 — это HTTP-семантика, его естественно формировать на уровне view; сервис (`sync_all`/`sync`) переиспользуется из разных мест (в т.ч. `save_configuration` дергает `project_sync_service.sync()` напрямую) и не должен знать про HTTP-коды. Контекст-менеджер `account_sync_lock` оборачивает тело view; при занятом локе бросает специфическое исключение `SyncLockBusy`, которое view ловит и отдаёт 409. Это держит сервис чистым и покрывает все 3 пути одинаково.
- **Реализация как декоратор + контекст-менеджер.** Базовый примитив — контекст-менеджер `account_sync_lock(account, scope)`. Поверх него — декоратор `@sync_lock(scope)` (по образцу `rate_limit`/`admin_required`, применяется ПОСЛЕ `@auth_required`), который оборачивает view и на `SyncLockBusy` возвращает 409. Для `timesheet_sync` и `sync_project_board` используем **декоратор** (чистые точки входа). Для `save_configuration` декоратор не подходит (там синк — лишь часть длинной логики сохранения, нельзя блокировать всё сохранение настроек замком синка), поэтому внутри `save_configuration` оборачиваем **только вызов** `project_sync_service.sync()` (стр. 1566) **контекст-менеджером** `account_sync_lock(account, scope="project")`; при `SyncLockBusy` ведём себя как при ошибке синка — кладём в `response_payload["project_sync"]` предупреждение «Синхронизация проектов уже выполняется, попробуйте позже» и продолжаем сохранение (настройки важнее, чем немедленный синк).
- **Ключи: РАЗДЕЛЬНЫЕ per-account по scope.** Timesheet-синк и project-синк трогают **разные таблицы** (`TimesheetItem` vs `ProjectCard`) и могут безопасно идти параллельно друг другу, но НЕ сами с собой. Поэтому два независимых ключа на аккаунт:
  - timesheet: `scope="timesheet"`,
  - project: `scope="project"`.
  - Числовой ключ для PG advisory-lock (требует bigint) формируем детерминированно из `account.pk` и `scope`: `key = (account.pk << 4) | SCOPE_BITS[scope]`, где `SCOPE_BITS = {"timesheet": 1, "project": 2}`. Сдвиг на 4 бита оставляет место под будущие scope и исключает коллизии между timesheet/project одного аккаунта и между аккаунтами (pk уникален). Двухаргументный вариант `pg_try_advisory_lock(int4, int4)` тоже допустим (classid=account.pk, objid=scope_code), но односложный bigint проще и переносимее — выбираем его.

**Шаг 1. Падающие тесты** — Create `main/tests_sync_lock.py` (Django `TestCase`):

```python
from unittest.mock import MagicMock, patch

from django.test import TestCase, Client

from .models import Bitrix24Account
from .utils.decorators.sync_lock import account_sync_lock, SyncLockBusy, _advisory_key


class AdvisoryKeyTest(TestCase):
    def test_scopes_produce_distinct_keys(self):
        k_ts = _advisory_key(account_pk=10, scope="timesheet")
        k_pr = _advisory_key(account_pk=10, scope="project")
        self.assertNotEqual(k_ts, k_pr)

    def test_accounts_produce_distinct_keys(self):
        self.assertNotEqual(
            _advisory_key(account_pk=10, scope="timesheet"),
            _advisory_key(account_pk=11, scope="timesheet"),
        )


class SyncLockNoopOnSqliteTest(TestCase):
    def test_context_manager_is_noop_on_sqlite_and_yields(self):
        # connection.vendor == "sqlite" в тест-окружении -> вход/выход без ошибок.
        account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m", is_master_account=True,
            domain_url="example.bitrix24.ru", status="active", application_version=1,
        )
        entered = False
        with account_sync_lock(account, scope="timesheet"):
            entered = True
        self.assertTrue(entered)


class SyncLockBusyOnPostgresMockTest(TestCase):
    def test_busy_lock_raises_on_postgres(self):
        # Эмулируем postgres: vendor=="postgresql", а pg_try_advisory_lock -> False.
        account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m2", is_master_account=True,
            domain_url="example.bitrix24.ru", status="active", application_version=1,
        )
        fake_cursor = MagicMock()
        fake_cursor.fetchone.return_value = (False,)  # лок занят
        fake_cm = MagicMock()
        fake_cm.__enter__.return_value = fake_cursor
        fake_cm.__exit__.return_value = False

        with patch("main.utils.decorators.sync_lock.connection") as conn:
            conn.vendor = "postgresql"
            conn.cursor.return_value = fake_cm
            with self.assertRaises(SyncLockBusy):
                with account_sync_lock(account, scope="timesheet"):
                    pass

    def test_acquired_lock_releases_on_postgres(self):
        account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m3", is_master_account=True,
            domain_url="example.bitrix24.ru", status="active", application_version=1,
        )
        fake_cursor = MagicMock()
        fake_cursor.fetchone.return_value = (True,)  # лок получен
        fake_cm = MagicMock()
        fake_cm.__enter__.return_value = fake_cursor
        fake_cm.__exit__.return_value = False

        with patch("main.utils.decorators.sync_lock.connection") as conn:
            conn.vendor = "postgresql"
            conn.cursor.return_value = fake_cm
            with account_sync_lock(account, scope="timesheet"):
                pass
        # После выхода должен быть вызван pg_advisory_unlock (вторым execute).
        executed_sql = " ".join(str(c.args[0]) for c in fake_cursor.execute.call_args_list)
        self.assertIn("pg_advisory_unlock", executed_sql)


class TimesheetSyncEndpoint409Test(TestCase):
    @patch("main.views.ConfigurationService.get_configuration_sync",
           return_value={"sp_entity_type_id": 1, "fields_mapping": {}})
    def test_busy_sync_returns_409(self, _cfg):
        account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m4", is_master_account=True,
            domain_url="example.bitrix24.ru", status="active", application_version=1,
        )
        token = account.create_jwt_token()
        # Заставим контекст-менеджер сразу бросить SyncLockBusy (эмуляция занятого лока),
        # не трогая реальный sync_all.
        with patch("main.views.account_sync_lock", side_effect=SyncLockBusy):
            response = Client().post(
                "/api/sync-timesheets",
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {token}",
            )
        self.assertEqual(response.status_code, 409)
        self.assertIn("error", response.json())
```

**Шаг 2. Запуск (ожидание: FAIL — модуля `sync_lock` ещё нет).** `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_sync_lock --settings=test_settings`.

**Шаг 3. Реализация (ПОЛНЫЙ код).**

Create `main/utils/decorators/sync_lock.py`:
```python
"""Advisory-замок на синхронизацию по аккаунту.

PostgreSQL: session-level pg_try_advisory_lock(key) с гарантированным
pg_advisory_unlock(key) в finally. Session-, а НЕ xact-уровень — потому что
боевой синк состоит из множества коротких транзакций (_save_batch) и длинных
HTTP-вызовов к Битрикс; единая гигантская транзакция (которой требует
xact-lock) сломала бы батч-дизайн и держала бы блокировку БД минутами.
Session-lock держится поверх этих транзакций; при падении процесса PG снимает
его автоматически при закрытии соединения.

Иные БД (sqlite в тестах): полный no-op (вход/выход без SQL). sqlite в тестах
однопоточный — гонок нет, поэтому no-op безопасен.

Ключи раздельные per-account по scope: timesheet-синк и project-синк трогают
разные таблицы и могут идти параллельно друг другу, но не сами с собой.
"""

import logging
from contextlib import contextmanager

from django.db import connection
from django.http import JsonResponse
from functools import wraps


logger = logging.getLogger(__name__)

SCOPE_BITS = {"timesheet": 1, "project": 2}


class SyncLockBusy(Exception):
    """Бросается, когда advisory-лок по аккаунту/скоупу уже занят."""


def _advisory_key(account_pk: int, scope: str) -> int:
    if scope not in SCOPE_BITS:
        raise ValueError(f"sync_lock: unknown scope {scope!r}")
    return (int(account_pk) << 4) | SCOPE_BITS[scope]


@contextmanager
def account_sync_lock(account, scope: str):
    """Контекст-менеджер advisory-замка. На не-postgresql — no-op.

    Бросает SyncLockBusy, если лок занят (только на postgresql).
    """
    if connection.vendor != "postgresql":
        # no-op для sqlite и прочих
        yield
        return

    key = _advisory_key(account.pk, scope)
    acquired = False
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [key])
        row = cursor.fetchone()
        acquired = bool(row and row[0])
        if not acquired:
            raise SyncLockBusy()
    try:
        yield
    finally:
        # Освобождаем в отдельном курсоре — соединение могло смениться,
        # но session-lock привязан к соединению; при штатной работе это то же
        # соединение. На случай ошибки лог не валит основной поток.
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [key])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to release advisory lock %s: %s", key, exc)


def sync_lock(scope: str):
    """Декоратор: оборачивает view в account_sync_lock; на занятом локе -> 409.

    Применять ПОСЛЕ @auth_required (нужен request.bitrix24_account).
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            account = getattr(request, "bitrix24_account", None)
            try:
                with account_sync_lock(account, scope):
                    return view_func(request, *args, **kwargs)
            except SyncLockBusy:
                return JsonResponse(
                    {"error": "Синхронизация уже выполняется, подождите"},
                    status=409,
                )
        return wrapped
    return decorator
```

В `main/views.py`:
- Импорт рядом с прочими декораторами: `from .utils.decorators.sync_lock import sync_lock, account_sync_lock, SyncLockBusy`.
- На `timesheet_sync` (после `@auth_required`, рядом с `@rate_limit(...)`):
```python
@auth_required
@rate_limit("sync", 6, 60, key="account")
@sync_lock("timesheet")
def timesheet_sync(request: AuthorizedRequest):
```
- На `sync_project_board` (после `@auth_required`/`@admin_required`/`@rate_limit`):
```python
@auth_required
@admin_required
@rate_limit("sync", 6, 60, key="account")
@sync_lock("project")
def sync_project_board(request: AuthorizedRequest):
```
- В `save_configuration` обернуть только вызов синка (текущие стр. 1564-1576). Заменить:
```python
            project_sync_service = ProjectSyncService(request.bitrix24_account.client, request.bitrix24_account)
            try:
                sync_result = project_sync_service.sync()
                response_payload["project_sync"] = sync_result
            except Exception as sync_exc:
                ...
```
на:
```python
            project_sync_service = ProjectSyncService(request.bitrix24_account.client, request.bitrix24_account)
            try:
                with account_sync_lock(request.bitrix24_account, scope="project"):
                    sync_result = project_sync_service.sync()
                response_payload["project_sync"] = sync_result
            except SyncLockBusy:
                warnings.append(
                    "Синхронизация проектов уже выполняется, повторите позже."
                )
                response_payload["project_sync"] = {
                    "status": "warning",
                    "warning": "Синхронизация проектов уже выполняется, повторите позже.",
                }
            except Exception as sync_exc:
                logger.exception("Configuration save project sync failed: %s", sync_exc)
                warnings.append(
                    "Настройки сохранены, но автосинхронизация проектов завершилась ошибкой."
                )
                response_payload["project_sync"] = {
                    "status": "warning",
                    "warning": str(sync_exc),
                }
```
> Примечание: `str(sync_exc)` в ветке общего `except` здесь НЕ трогаем в рамках 2.2 — это вне scope (см. открытый вопрос про `save_configuration` в 2.3). 2.2 только добавляет ветку `SyncLockBusy`.

**Порядок декораторов — обоснование.** `@rate_limit` стоит ВЫШЕ `@sync_lock`, чтобы rate-limit отрабатывал первым (дешёвая проверка кэша) и не давал захватывать advisory-лок при флуде. `@sync_lock` — самый близкий к функции, оборачивает непосредственно тело view, держа сессионный лок ровно на время работы view.

**Шаг 4. Запуск (ожидание: PASS).** `./.venv/bin/python manage.py test main.tests_sync_lock --settings=test_settings`. Затем регресс: `./.venv/bin/python manage.py test main.tests_reports --settings=test_settings` (контракты warning-эндпоинтов не должны сломаться: на sqlite `account_sync_lock` — no-op, `test_sync_endpoint_returns_warning_instead_of_500` остаётся зелёным).

**Шаг 5. Доклад.** Замок в view через декоратор для 2 эндпоинтов + контекст-менеджер внутри save_configuration; ключи раздельные `timesheet`/`project` per-account; session-lock (не xact) с finally-release; no-op на sqlite; 409 при занятом локе; конкурентность на sqlite честно не воспроизводится — покрыто юнит-тестом через мок курсора.

---

## Задача 2.3 — Честные ошибки синхронизации [соннет]

**Файлы:** Modify `main/views.py` (только блок `timesheet_sync` ≈1441-1452); Modify `frontend/app/composables/useReportGenerator.ts`; Modify `frontend/app/stores/api.ts` (только тип возврата `syncTimesheets`, при необходимости); Create `main/tests_sync_honest_errors.py`.

**Дыра (проверено).** `timesheet_sync` при исключении в `sync_all` возвращает HTTP 200 с `{"status":"warning","count":0,"warning":"...","error": str(exc)}` (views.py:1445-1452). Две проблемы: (1) `error: str(exc)` утекает наружу текст исключения; (2) фронт `useReportGenerator` (стр. 55-69) делает `await apiStore.syncTimesheets(...)` в `try/catch`, но т.к. бэк отдаёт 200 (не исключение), `catch` НЕ срабатывает и `syncWarning` не выставляется — пользователь видит «успех» поверх старых данных.

**Бэк-изменение.** Заменить тело `except` в `timesheet_sync` (текущие стр. 1441-1452): оставить HTTP 200 и `status="warning"`, `count=0`, понятный `warning`, но **убрать ключ `error: str(exc)`** (трейс уже уходит в лог через `logger.exception` на стр. 1442 — оставить как есть). Итог:
```python
    except Exception:
        logger.exception("Timesheet sync failed for account %s", request.bitrix24_account.pk)
        profiler.set_metric("status", "error")
        profiler.log()
        return JsonResponse(
            {
                "status": "warning",
                "count": 0,
                "warning": "Не удалось обновить данные из Битрикс24. Используются последние сохраненные данные.",
            }
        )
```
> Совместимость с существующим контрактом: `test_sync_endpoint_returns_warning_instead_of_500` (tests_reports.py:503) проверяет `status=="warning"`, `count==0`, наличие `"warning"` — всё сохраняется. Удаление `error` его не ломает.

**Фронт-изменение (минимально, в единственной точке `generateReport`).** Сейчас результат `syncTimesheets` игнорируется (стр. 58). Заменить блок 56-69 так, чтобы разбирать `result.status`:
```typescript
      if (willSync) {
        const syncStart = perfEnabled ? performance.now() : 0
        try {
          const syncResult = await apiStore.syncTimesheets(config.syncDateFrom, config.syncDateTo)
          if (syncResult?.status === 'warning') {
            syncWarning.value = config.syncWarningMessage
              || 'Не удалось обновить данные из Битрикс24. Показаны последние сохраненные данные.'
          }
        } catch (error) {
          if (!config.allowSyncFallback) {
            throw error
          }
          syncWarning.value = config.syncWarningMessage
            || 'Не удалось обновить данные из Битрикс24. Показаны последние сохраненные данные.'
        } finally {
          if (perfEnabled) {
            syncMs = performance.now() - syncStart
          }
        }
        progress.stage(`${reportTitle} · шаг 2 из 2: формирование`, 'Считаем таблицы и итоги')
      }
```
> Поведение: при `status==="warning"` от бэка теперь выставляется `syncWarning` независимо от того, было ли исключение. При жёстком сбое сети (исключение) — прежний фолбэк через `allowSyncFallback` сохраняется.

**Тип `syncTimesheets`.** Уже объявлен как `Promise<{ status: string; count: number }>` (api.ts:573) и возвращает `result` — тип прокинут корректно, правок в `api.ts` по типу НЕ требуется. Исполнитель ОБЯЗАН перепроверить чтением и доложить, если тип расходится.

**Где `syncWarning` показывается пользователю (проверено грепом).** Панель `<div v-if="syncWarning" class="ms-panel-warning">` есть ТОЛЬКО на `pages/reports/daily.client.vue` (стр. 255-256), и только эта страница передаёт `allowSyncFallback: true`. Остальные 6 отчётных страниц (`project`, `focus-analysis`, `project-task`, `employee`, `revenue-leakage`, `time-discipline`) `syncWarning` НЕ деструктурируют и панель НЕ рендерят. → См. **открытый вопрос 2** ниже: расширять ли панель на 6 страниц. В рамках 2.3 движок (`generateReport`) начинает корректно выставлять `syncWarning` для всех; на `daily` это сразу видно, остальные 6 покажут предупреждение только после расширения шаблонов (вне минимального scope).

**Шаг 1. Падающий тест (бэк)** — Create `main/tests_sync_honest_errors.py`:
```python
from unittest.mock import patch

from django.test import TestCase, Client

from .models import Bitrix24Account


class SyncHonestErrorTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-2-3", is_master_account=True,
            domain_url="example.bitrix24.ru", status="active", application_version=1,
        )

    @patch("main.views.TimesheetSyncService.sync_all", side_effect=RuntimeError("secret trace 12345"))
    @patch("main.views.ConfigurationService.get_configuration_sync",
           return_value={"sp_entity_type_id": 1, "fields_mapping": {}})
    def test_sync_failure_is_not_success_and_hides_trace(self, _cfg, _sync):
        token = self.account.create_jwt_token()
        response = Client().post(
            "/api/sync-timesheets",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotEqual(payload.get("status"), "success")
        self.assertEqual(payload.get("status"), "warning")
        body = response.content.decode("utf-8")
        self.assertNotIn("secret trace 12345", body)
        self.assertNotIn("error", payload)  # ключ error удалён из ответа
```

**Шаг 2. Запуск (ожидание: FAIL).** `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_sync_honest_errors --settings=test_settings` — упадёт на `assertNotIn("secret trace 12345")` и `assertNotIn("error")` (текущий код кладёт `error: str(exc)`).

**Шаг 3. Реализация.** Применить бэк- и фронт-изменения выше.

**Шаг 4. Запуск (ожидание: PASS).** `./.venv/bin/python manage.py test main.tests_sync_honest_errors --settings=test_settings`; затем регресс `main.tests_reports`. Фронт-тесты не обязательны (правка точечная); достаточно аккуратности и ручной проверки на `daily`.

**Шаг 5. Доклад.** Бэк больше не маскирует сбой под success и не отдаёт трейс; фронт распознаёт `status==="warning"`; перечислены страницы с панелью предупреждения и зафиксирован открытый вопрос про 6 страниц без панели.

---

## Задача 2.4 — Кэш справочника сотрудников [соннет]

**Файлы:** Modify `main/bitrix_data_access.py` (метод `fetch_users` ≈45-85); Modify `main/project_board_shared.py` (константа суффикса + опционально инвалидация — см. решение); Create `main/tests_user_cache.py`.

**Дыра (проверено).** `_get_user_map` (views.py:129-136) на КАЖДЫЙ отчёт строит `BitrixDataService` и зовёт `fetch_users(user_ids)`, а `fetch_users` (bitrix_data_access.py:45) НЕ кэширован — синхронный `user.get` к Битрикс на каждый отчёт. Образец кэширования уже рядом: `fetch_active_users` (стр. 87) кэширует по `build_account_cache_key(account, FILTER_EMPLOYEES_CACHE_SUFFIX)` с TTL `BITRIX_REFERENCE_CACHE_TTL` и НЕ кэширует пустой результат (`if cached == []: cache.delete`).

**Решение по ключу.** Набор `user_ids` в `fetch_users` варьируется от отчёта к отчёту, поэтому ключ должен включать стабильный отпечаток **множества числовых id**. Берём numeric id (через `extract_bitrix_user_id`, как уже делает метод), нормализуем в отсортированное множество, считаем хэш и формируем суффикс. Разные наборы id → разные ключи; перестановка/дубликаты id → один ключ.

**Решение по инвалидации (обосновано — инвалидацию в `invalidate_project_runtime_caches` НЕ добавляем).** Имена людей в Битрикс меняются крайне редко; синк трудозатрат имена НЕ меняет (он тянет `crm.item.list`, а не `user.get`). Текущая `invalidate_project_runtime_caches` (project_board_shared.py:65) сбрасывает справочник **фильтра** (`FILTER_EMPLOYEES_CACHE_SUFFIX`) — это другой кэш (полный активный список для UI-фильтра), его инвалидация при синке оправдана. Кэш `fetch_users` (карта id→имя для отчёта) при синке инвалидировать НЕ нужно: данные синка на имена не влияют, а TTL 30 мин — приемлемая свежесть для ФИО. Добавление его в инвалидацию лишь увеличило бы число cache.delete без пользы. → НЕ добавляем; фиксируем как осознанное решение. (Если потом понадобится принудительный сброс — он делается естественно по истечении TTL.)

**Константа суффикса.** В `project_board_shared.py` рядом с `FILTER_EMPLOYEES_CACHE_SUFFIX` добавить базовый префикс: `USER_NAMES_CACHE_PREFIX = "user-names-v1"`. Полный суффикс собирается в `fetch_users` как `f"{USER_NAMES_CACHE_PREFIX}:{digest}"`.

**Шаг 1. Падающий тест** — Create `main/tests_user_cache.py`:
```python
import hashlib
from unittest.mock import Mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from .bitrix_data_access import BitrixDataService
from .models import Bitrix24Account


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class FetchUsersCacheTest(TestCase):
    def setUp(self):
        cache.clear()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-2-4", is_master_account=True,
            domain_url="example.bitrix24.ru", status="active", application_version=1,
        )

    def _service(self):
        client = Mock()
        client._bitrix_token.call_method.return_value = {
            "result": [
                {"ID": "1", "NAME": "Иван", "LAST_NAME": "Петров"},
                {"ID": "2", "NAME": "Анна", "LAST_NAME": "Сидорова"},
            ]
        }
        return BitrixDataService(client, {}, self.account), client

    def test_second_fetch_same_ids_does_not_call_user_get(self):
        service, client = self._service()
        first = service.fetch_users(["1", "2"])
        second = service.fetch_users(["1", "2"])
        self.assertEqual(first, second)
        self.assertEqual(client._bitrix_token.call_method.call_count, 1)  # второй раз из кэша

    def test_different_ids_use_different_keys(self):
        service, client = self._service()
        service.fetch_users(["1", "2"])
        service.fetch_users(["1"])  # другой набор -> новый вызов
        self.assertEqual(client._bitrix_token.call_method.call_count, 2)

    def test_id_order_does_not_affect_key(self):
        service, client = self._service()
        service.fetch_users(["1", "2"])
        service.fetch_users(["2", "1"])  # та же множественность -> кэш
        self.assertEqual(client._bitrix_token.call_method.call_count, 1)

    def test_empty_result_not_cached(self):
        client = Mock()
        client._bitrix_token.call_method.return_value = {"result": []}
        service = BitrixDataService(client, {}, self.account)
        service.fetch_users(["99"])
        service.fetch_users(["99"])
        # пустой результат не кэшируется -> повторный вызов снова бьёт в Bitrix
        self.assertEqual(client._bitrix_token.call_method.call_count, 2)
```

**Шаг 2. Запуск (ожидание: FAIL).** `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_user_cache --settings=test_settings` — падает (сейчас кэша нет, `call_count` всегда растёт).

**Шаг 3. Реализация (ПОЛНЫЙ код).**

В `project_board_shared.py` рядом с `FILTER_EMPLOYEES_CACHE_SUFFIX = "filter-employees-v3"`:
```python
USER_NAMES_CACHE_PREFIX = "user-names-v1"
```

В `bitrix_data_access.py` импорт расширить:
```python
import hashlib
...
from .project_board_shared import (
    BITRIX_REFERENCE_CACHE_TTL,
    FILTER_EMPLOYEES_CACHE_SUFFIX,
    USER_NAMES_CACHE_PREFIX,
    build_account_cache_key,
)
```

Переписать `fetch_users` (тело метода), сохранив всю существующую логику алиасов и добавив кэш-обёртку вокруг вызова `user.get`:
```python
    def fetch_users(self, user_ids: List[str]) -> Dict[str, str]:
        if not user_ids:
            return {}

        numeric_to_aliases: Dict[str, set[str]] = {}
        for uid in user_ids:
            raw_id = str(uid).strip() if uid not in (None, "") else ""
            normalized_id = normalize_employee_id(uid)
            numeric_id = extract_bitrix_user_id(uid)
            if not numeric_id:
                continue

            aliases = numeric_to_aliases.setdefault(numeric_id, set())
            aliases.add(numeric_id)
            if normalized_id:
                aliases.add(normalized_id)
            if raw_id:
                aliases.add(raw_id)

        if not numeric_to_aliases:
            return {}

        cache_key = None
        if self.account:
            numeric_ids_sorted = sorted(numeric_to_aliases.keys(), key=lambda x: int(x))
            digest = hashlib.sha1(",".join(numeric_ids_sorted).encode("utf-8")).hexdigest()[:16]
            cache_key = build_account_cache_key(self.account, f"{USER_NAMES_CACHE_PREFIX}:{digest}")
            cached = cache.get(cache_key)
            if cached:
                return cached
            if cached == {}:
                cache.delete(cache_key)

        try:
            response = self.client._bitrix_token.call_method(
                "user.get",
                {"FILTER": {"ID": list(numeric_to_aliases.keys())}},
            )
            users = response.get("result", [])
            user_map: Dict[str, str] = {}
            for user in users:
                numeric_id = extract_bitrix_user_id(user.get("ID"))
                if not numeric_id:
                    continue

                name = self._build_user_name(user, numeric_id)
                for alias in numeric_to_aliases.get(numeric_id, {numeric_id}):
                    user_map[alias] = name

            if cache_key is not None:
                if user_map:
                    cache.set(cache_key, user_map, BITRIX_REFERENCE_CACHE_TTL)
                else:
                    cache.delete(cache_key)
            return user_map
        except Exception as exc:
            logger.error("Error fetching users: %s", exc)
            return {}
```
> Сортировка numeric id числовым ключом (`int(x)`) гарантирует, что `["1","2"]` и `["2","1"]` дают один digest. Пустой `user_map` не кэшируется (по образцу `fetch_active_users`).

**Шаг 4. Запуск (ожидание: PASS).** `./.venv/bin/python manage.py test main.tests_user_cache --settings=test_settings`; регресс `main.tests_reports`.

**Шаг 5. Доклад.** `fetch_users` кэширован по хэшу отсортированного множества numeric id, TTL 30 мин, пустой результат не кэшируется; инвалидация в `invalidate_project_runtime_caches` НЕ добавлена (обосновано: синк имена не меняет).

---

## Задача 2.5 — Мелкие ускорения отчётов [хайку — шаги предельно точные]

**Файлы:** Modify `main/report_queries.py` (две точки: блок архивных ≈38-44 и `build_project_title_lookups` ≈71-83); Create `main/tests_report_perf.py`.

**Дыра (проверено).** (а) `build_filtered_timesheet_queryset` (report_queries.py:38-44) на КАЖДЫЙ вызов строит **три** отдельных подзапроса к `ProjectCard` (`archived_item_ids`, `archived_ids`, `archived_names`) и подставляет их в `exclude(Q|Q|Q)`. (б) `build_project_title_lookups` (стр. 71-83) делает `for card in cards` по ПОЛНЫМ ORM-объектам `ProjectCard` (25+ полей), хотя нужны только `project_item_id/project_id/project_name`.

**Решение (а) — минимальный безопасный вариант: один `values_list` вместо трёх QuerySet, БЕЗ кэша.** Кэш архивных id по account на короткий TTL рассматривался, но добавляет инвалидацию (нужно сбрасывать при синке/архивации проекта) и риск рассинхронизации; выигрыш на одном COUNT-подобном проходе невелик. Поэтому берём **один** проход `values_list("project_item_id", "project_id", "project_name")` по `archived_cards`, в Python формируем три множества (с тем же отсевом пустых/None, что и сейчас) и используем их в `exclude`. Поведение идентично, число обращений к БД за архивными сокращается с 3 подзапросов до 1 выборки. **Кэш НЕ вводим** — фиксируем как осознанное решение (проще и безопаснее, эквивалентность результата гарантирована).

**Решение (б).** Заменить `for card in cards` на `cards.values_list("project_item_id", "project_id", "project_name")` и собрать те же два словаря.

**Шаг 1. Падающий тест (поведенческая эквивалентность)** — Create `main/tests_report_perf.py`:
```python
from datetime import datetime

from django.test import TestCase
from django.utils import timezone

from .models import Bitrix24Account, ProjectCard, TimesheetItem
from .project_board_shared import PROJECT_STAGE_IN_WORK
from .report_queries import build_filtered_timesheet_queryset, build_project_title_lookups


class ReportPerfEquivalenceTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-2-5", is_master_account=True,
            domain_url="example.bitrix24.ru", status="active", application_version=1,
        )

    def test_archived_exclusion_unchanged(self):
        ProjectCard.objects.create(
            bitrix24_account=self.account, project_id="arch-id", project_item_id="arch-item",
            project_name="Архив", stage=PROJECT_STAGE_IN_WORK, manual_stage=PROJECT_STAGE_IN_WORK,
            is_archived=True,
        )
        ProjectCard.objects.create(
            bitrix24_account=self.account, project_id="live-id", project_item_id="live-item",
            project_name="Живой", stage=PROJECT_STAGE_IN_WORK, manual_stage=PROJECT_STAGE_IN_WORK,
            is_archived=False,
        )
        day = timezone.make_aware(datetime(2026, 3, 1, 9, 0))
        TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=1, task_id="1", employee_id="e1", hours=2,
            project_id="arch-id", project_item_id="arch-item", project_title="Архив", date_reflection=day,
        )
        keep = TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=2, task_id="2", employee_id="e1", hours=3,
            project_id="live-id", project_item_id="live-item", project_title="Живой", date_reflection=day,
        )
        qs = build_filtered_timesheet_queryset(self.account, {})
        self.assertEqual(list(qs.values_list("bitrix_id", flat=True)), [keep.bitrix_id])

    def test_title_lookups_unchanged(self):
        ProjectCard.objects.create(
            bitrix24_account=self.account, project_id="g1", project_item_id="i1",
            project_name="Проект-1", stage=PROJECT_STAGE_IN_WORK, manual_stage=PROJECT_STAGE_IN_WORK,
            is_archived=False,
        )
        by_item, by_group = build_project_title_lookups(self.account)
        self.assertEqual(by_item.get("i1"), "Проект-1")
        self.assertEqual(by_group.get("g1"), "Проект-1")
```

**Шаг 2. Запуск (ожидание: PASS уже сейчас — это baseline-фиксация эквивалентности).** `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_report_perf --settings=test_settings`. Эти тесты должны проходить и ДО, и ПОСЛЕ рефактора — они закрепляют поведение. (Если до рефактора не проходят — значит фикстуры/импорты неверны, починить до правок прод-кода.)

**Шаг 3. Реализация (ПОЛНЫЙ код).** В `report_queries.py`:

Заменить блок 38-44:
```python
    archived_cards = get_project_card_queryset(account).filter(is_archived=True)
    archived_rows = archived_cards.values_list("project_item_id", "project_id", "project_name")
    archived_item_ids = set()
    archived_ids = set()
    archived_names = set()
    for item_id, group_id, name in archived_rows:
        if item_id:
            archived_item_ids.add(item_id)
        if group_id:
            archived_ids.add(group_id)
        if name:
            archived_names.add(name)
    queryset = queryset.exclude(
        Q(project_item_id__in=archived_item_ids)
        | Q(project_id__in=archived_ids)
        | Q(project_title__in=archived_names)
    )
```
> Отсев пустых строк/None в Python воспроизводит прежние `.exclude(...__isnull=True).exclude(...="")`. Пустые множества в `__in` дают пустое условие — поведение `exclude(Q(... in []))` эквивалентно отсутствию исключения по этому полю, как и раньше.

Заменить `build_project_title_lookups` (71-83):
```python
def build_project_title_lookups(account: Bitrix24Account) -> tuple[Dict[str, str], Dict[str, str]]:
    rows = (
        get_project_card_queryset(account)
        .exclude(project_name__isnull=True)
        .exclude(project_name="")
        .values_list("project_item_id", "project_id", "project_name")
    )
    by_item: Dict[str, str] = {}
    by_group: Dict[str, str] = {}
    for project_item_id, project_id, project_name in rows:
        if project_item_id:
            by_item[str(project_item_id).strip()] = project_name
        if project_id:
            by_group[str(project_id).strip()] = project_name
    return by_item, by_group
```

**Шаг 4. Запуск (ожидание: PASS).** `./.venv/bin/python manage.py test main.tests_report_perf --settings=test_settings` (теперь проверяет рефакторенный код, результат идентичен). Затем **обязательно** `./.venv/bin/python manage.py test main.tests_reports --settings=test_settings` — в нём есть `test_timesheet_filters_use_date_range_and_exclude_archived_projects`, прямо покрывающий блок архивных; должен остаться зелёным (41/2-известные).

**Шаг 5. Доклад.** Три подзапроса архивных → один `values_list`+Python; `build_project_title_lookups` → `values_list` вместо полных ORM-объектов; кэш НЕ вводился (обосновано); результаты отчётов идентичны.

---

## Задача 2.6 — Интеграционные тесты синхронизации на реальной (sqlite) БД [опус]

**Файлы:** Create `main/tests_sync_integration.py`. Прод-код НЕ меняется (только читается `timesheet_sync_service.py`). Зависит от готовности 2.1 (порог) и 2.2 (no-op замка на sqlite).

**Назначение.** Страховка всего спринта: реальная sqlite-БД, БЕЗ моков `transaction.atomic` и БЕЗ `sys.modules`-заглушек. Мок только Bitrix-клиента (`call_method`). Покрываем: идемпотентность, orphan-удаление с порогом 2.1, частичный сбой `_save_batch`.

**Перед написанием** перечитать `timesheet_sync_service.py` (`_sync_full`, `_save_batch`, `_extract_items`, `normalize_items` через `DataProcessingService`) и убедиться, что `_FakeClient` отдаёт ответ в форме `{"result": {"items": [...]}}` (см. `_extract_items` стр. 481-491). Проверить, что `processing_service.normalize_items` корректно отрабатывает на минимальном элементе с полями маппинга (`data`→дата, `id_zadachi` и т.д.). Если normalize требует больше полей — расширить `_make_item` ДО написания ассертов.

**Шаг 1. Тесты (ПОЛНЫЙ код)** — Create `main/tests_sync_integration.py`:
```python
from datetime import datetime
from unittest.mock import Mock

from django.test import TestCase
from django.utils import timezone

from .models import Bitrix24Account, TimesheetItem
from .timesheet_sync_service import TimesheetSyncService


def _item(bitrix_id):
    return {
        "id": bitrix_id,
        "ufCrmTask": str(bitrix_id),
        "createdTime": "2026-01-01T09:00:00+03:00",
    }


class _ScriptedClient:
    """Отдаёт заранее заданные ответы crm.item.list по порядку вызовов call_method."""

    def __init__(self, responses):
        self._responses = list(responses)
        self._idx = 0
        self._bitrix_token = self

    def call_method(self, method, params):
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
        else:
            resp = {"result": {"items": []}}
        self._idx += 1
        return resp


class _Config:
    @staticmethod
    def make():
        return {
            "sp_entity_type_id": 1,
            "fields_mapping": {"data": "createdTime", "id_zadachi": "ufCrmTask"},
        }


class SyncIdempotencyTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-int-1", is_master_account=True,
            domain_url="example.bitrix24.ru", status="active", application_version=1,
        )

    def test_two_full_syncs_same_response_no_duplicates(self):
        page = {"result": {"items": [_item(1), _item(2), _item(3)]}}  # count<50 -> traversal_complete
        svc1 = TimesheetSyncService(_ScriptedClient([page]), self.account, _Config.make())
        n1 = svc1._sync_full()
        count_after_first = TimesheetItem.objects.filter(bitrix24_account=self.account).count()

        svc2 = TimesheetSyncService(_ScriptedClient([page]), self.account, _Config.make())
        n2 = svc2._sync_full()
        count_after_second = TimesheetItem.objects.filter(bitrix24_account=self.account).count()

        self.assertEqual(count_after_first, 3)
        self.assertEqual(count_after_second, 3)  # нет дублей
        self.assertEqual(n1, n2)


class SyncOrphanWithThresholdTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-int-2", is_master_account=True,
            domain_url="example.bitrix24.ru", status="active", application_version=1,
        )

    def test_true_orphans_deleted_on_complete_traversal(self):
        # Первый синк: 1,2,3
        first = {"result": {"items": [_item(1), _item(2), _item(3)]}}
        TimesheetSyncService(_ScriptedClient([first]), self.account, _Config.make())._sync_full()
        # Второй синк: 1,2 (3 стал сиротой, traversal_complete True)
        second = {"result": {"items": [_item(1), _item(2)]}}
        TimesheetSyncService(_ScriptedClient([second]), self.account, _Config.make())._sync_full()
        remaining = set(TimesheetItem.objects.filter(bitrix24_account=self.account).values_list("bitrix_id", flat=True))
        self.assertEqual(remaining, {1, 2})

    def test_midway_empty_page_keeps_data(self):
        # Сидим 200 через первый здоровый синк (4 страницы по 50).
        pages_seed = [
            {"result": {"items": [_item(i) for i in range(1, 51)]}},
            {"result": {"items": [_item(i) for i in range(51, 101)]}},
            {"result": {"items": [_item(i) for i in range(101, 151)]}},
            {"result": {"items": [_item(i) for i in range(151, 201)]}},  # 50 ровно -> followed by empty
            {"result": {"items": []}},  # естественный конец (но 4-я была ==50, см. ниже)
        ]
        TimesheetSyncService(_ScriptedClient(pages_seed), self.account, _Config.make())._sync_full()
        seeded = TimesheetItem.objects.filter(bitrix24_account=self.account).count()
        self.assertEqual(seeded, 200)
        # Второй синк ОБРЫВАЕТСЯ: 1 полная страница (50, count==page_size -> цикл идёт),
        # затем пустая (обрыв на середине, traversal_complete=False, собрано 50 из 200 = 25% < 50%).
        broken = [
            {"result": {"items": [_item(i) for i in range(1, 51)]}},
            {"result": {"items": []}},
        ]
        TimesheetSyncService(_ScriptedClient(broken), self.account, _Config.make())._sync_full()
        self.assertEqual(
            TimesheetItem.objects.filter(bitrix24_account=self.account).count(),
            200,  # данные целы — порог 2.1 заблокировал удаление
        )


class SyncPartialBatchFailureTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-int-3", is_master_account=True,
            domain_url="example.bitrix24.ru", status="active", application_version=1,
        )

    def test_save_batch_failure_on_nth_batch_leaves_consistent_state(self):
        # Сидим валидную запись id=1.
        day = timezone.make_aware(datetime(2026, 1, 1, 9, 0))
        TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=1, task_id="1", employee_id="emp-old",
            hours=1, project_id="p", project_title="P", date_reflection=day,
        )
        # Клиент отдаёт страницу с id 1,2; но _save_batch упадёт.
        page = {"result": {"items": [_item(1), _item(2)]}}
        svc = TimesheetSyncService(_ScriptedClient([page]), self.account, _Config.make())

        original_save = svc._save_batch

        def boom(items):
            raise RuntimeError("batch save failed")

        svc._save_batch = boom  # падение на первой же пачке

        with self.assertRaises(RuntimeError):
            svc._sync_full()

        # Состояние согласовано: исходная запись id=1 не перезаписана половинчато,
        # удаления не произошло (исключение пробросилось до блока orphan-delete).
        item = TimesheetItem.objects.get(bitrix24_account=self.account, bitrix_id=1)
        self.assertEqual(item.employee_id, "emp-old")
        self.assertEqual(TimesheetItem.objects.filter(bitrix24_account=self.account).count(), 1)
```
> Примечание исполнителю: в `test_midway_empty_page_keeps_data` сценарий сидирования полагается на keyset-курсор по `id` — проверить, что `_ScriptedClient` отдаёт страницы строго в порядке возрастания id и что `batch_max_id` продвигается. Если из-за keyset-фильтра `{">id": last_id}` фейковый клиент должен учитывать `last_id` из `params["filter"]`, расширить `_ScriptedClient.call_method` чтением `params` и возвратом среза по id > last_id (более честная эмуляция). Это допустимое усложнение фейка — БД остаётся настоящей.

**Шаг 2. Запуск (ожидание: PASS).** `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_sync_integration --settings=test_settings`.

**Шаг 3. Доклад.** Идемпотентность, orphan+порог, частичный сбой покрыты на реальной sqlite; конкурентность (две параллельные сессии) на sqlite честно не воспроизводима — это ограничение, логика замка покрыта юнит-тестом в 2.2.

---

## Задача 2.7 — Защита от двойного клика «Сформировать» [хайку]

**Файлы:** Modify `frontend/app/composables/useReportGenerator.ts`.

**Дыра (проверено).** `generateReport` (единая точка, вызывается всеми 7 отчётными страницами через `loader`-замыкание) НЕ имеет защиты от повторного запуска: повторный клик «Сформировать», пока идёт текущий, стартует второй полный цикл синк+отчёт. `AbortController` нигде во фронте не используется. `isLoading` есть на страницах, но он управляет лишь спиннером, а не блокирует повторный вход в `generateReport`.

**Решение (минимально, без редизайна, в единственной точке).** В `useReportGenerator` добавить:
1. **Re-entry guard:** module-уровневый или composable-уровневый флаг `isGenerating` (через `ref`). В начале `generateReport`: если `isGenerating.value === true` — немедленно `return null` (не запускать второй цикл, в т.ч. не делать повторный синк). Снимать флаг в `finally`.
2. **AbortController:** хранить ссылку на текущий контроллер; при новом вызове, если предыдущий ещё жив, вызвать `abort()` на нём (отмена устаревшего запроса). Новый контроллер создаётся на каждый вызов; его `signal` передаётся в загрузку. Поскольку guard уже не пускает второй вызов во время активного — `abort()` фактически срабатывает в сценарии, когда первый цикл завершился, но запрос «завис»; для минимальности оставляем abort как страховку и НЕ тянем `signal` через все 7 страниц.

**Важная деталь о `signal`.** `loader()` — это замыкание страницы (например `() => apiStore.getReportDailyWorkload(...)`), которое сейчас НЕ принимает `signal`. Чтобы НЕ править 7 страниц и сам стор, в рамках минимального 2.7:
- Guard (`isGenerating`) — основная и достаточная защита от вреда (двойной синк/отчёт). Внедряется полностью.
- `AbortController` создаётся и его `abort()` вызывается при повторном входе ДО guard-возврата стащить устаревший контроллер; но прокидывание `signal` в ofetch делаем опционально: добавляем в `GenerateReportOptions<T>` необязательное поле, не меняя страницы. Если страница его не передаёт — abort просто отменяет «ничейный» контроллер без эффекта на сеть. → Активная отмена HTTP остаётся точкой роста; гарантируется именно неповторный запуск. (Зафиксировать в докладе как сознательное ограничение минимального варианта.)

**Шаг 1. Реализация (ПОЛНЫЙ код фрагментов).** В `useReportGenerator.ts`:

Внутри `useReportGenerator(...)` рядом с `const hasGenerated = ref(false)`:
```typescript
  const isGenerating = ref(false)
  let currentController: AbortController | null = null
```

В начале `generateReport` (заменить первые строки тела до `options.setLoading?.(true)`):
```typescript
  async function generateReport<T>(config: GenerateReportOptions<T>) {
    // Guard от двойного клика: если предыдущая генерация ещё идёт — не запускаем вторую
    // (иначе второй полный цикл синк+отчёт).
    if (isGenerating.value) {
      return null
    }
    // Отменяем устаревший запрос, если он ещё жив (страховка).
    if (currentController) {
      currentController.abort()
    }
    currentController = new AbortController()
    isGenerating.value = true

    options.setLoading?.(true)
    syncWarning.value = ''
```

В `finally` блока `generateReport` (где уже есть `options.setLoading?.(false)` и `progress.end()`):
```typescript
    } finally {
      if (perfEnabled) {
        const totalMs = performance.now() - startedAt
        // eslint-disable-next-line no-console
        console.info('[report-perf]', {
          report: config.reportName || 'unknown',
          sync_ms: Math.round(syncMs),
          fetch_ms: Math.round(fetchMs),
          total_ms: Math.round(totalMs),
        })
      }
      isGenerating.value = false
      currentController = null
      options.setLoading?.(false)
      progress.end()
    }
```

Добавить `isGenerating` в возвращаемый объект:
```typescript
  return {
    hasGenerated,
    isGenerating,
    syncWarning,
    generateReport,
    resetGenerated
  }
```

**Шаг 2. Проверка.** Тесты фронта не обязательны. Ручная проверка: на любой отчётной странице быстро дважды нажать «Сформировать» — второй клик не должен запускать второй синк (в Network один POST `/api/sync-timesheets`, не два). Запустить фронт согласно `make dev-python` (вне рамок написания плана; делает заказчик/исполнитель при проверке).

**Шаг 3. Доклад.** Guard `isGenerating` предотвращает повторный запуск (в т.ч. повторный синк); `AbortController` добавлен как страховка; прокидывание `signal` в ofetch оставлено точкой роста (минимальный вариант не правит 7 страниц).

---

## Задача 2.8 — Ревизия [соннет]

**Файлы:** без правок (только чтение + прогон).

**ТЗ ревизии:**
1. **Перепроверить 2.1-2.7 по коду** (чтением, не на память):
   - 2.1: блок удаления в `_sync_full` содержит `traversal_complete`/`current_count`/`DELETE_SAFETY_RATIO`; на ветке `if not items: break` флаг НЕ выставляется.
   - 2.2: `sync_lock.py` — `connection.vendor` гейт, `finally`-release, раздельные ключи; декораторы на `timesheet_sync`/`sync_project_board` стоят ПОСЛЕ `@auth_required`; в `save_configuration` обёрнут только `project_sync_service.sync()`; ответ 409 корректен.
   - 2.3: в ответе `timesheet_sync` при сбое нет ключа `error` и нет подстроки трейса; `useReportGenerator` разбирает `result.status === 'warning'`.
   - 2.4: `fetch_users` кэширован; пустой результат не кэшируется; ключ зависит от множества id, не от порядка.
   - 2.5: в `build_filtered_timesheet_queryset` один `values_list` архивных; `build_project_title_lookups` без полных ORM-объектов.
   - 2.7: `isGenerating`-guard в `generateReport`.
2. **Полный прогон тестов:**
   - Django-семейство пофайльно: `tests_reports` (база 41/2-известные), `tests_inn_backfill`, `tests_report_excel`, `tests_security_logs`, `tests_security_excel_cors`, `tests_security_ratelimit`, `tests_security_roles`, и новые `tests_sync_threshold`, `tests_sync_lock`, `tests_user_cache`, `tests_report_perf`, `tests_sync_honest_errors`, `tests_sync_integration`.
   - Автономные через unittest: `tests_fetch_paginated_batch`, `tests_project_fetch_keyset`, `tests_sync_scoped`, `tests_inn_apply_batch`.
   - Перед прогоном — `grep -L "sys.modules" main/tests_*.py`, убедиться, что все новые модули НЕ содержат `sys.modules` (иначе их нельзя в `manage.py test`).
3. **Регресс:** `main.tests_reports` остаётся 41 тест / 2 известные ошибки `FinanceOperationServiceTest` — НЕ регресс; новых ошибок нет.
4. **Grep-проверки:** в ответе `timesheet_sync` нет `"error": str(exc)`; в `report_queries.build_filtered_timesheet_queryset` нет трёх отдельных `archived_*.values(...)`; `account_sync_lock` присутствует в трёх местах `views.py`.

**Отчёт ревизии:** по каждой задаче 2.1-2.7 — закрыто/не закрыто, с указанием прогонов и их результатов.

---

## Самопроверка плана

- **Покрыты ли все 8 задач?** Да: 2.1 (порог удаления), 2.2 (замок), 2.3 (честные ошибки), 2.4 (кэш fetch_users), 2.5 (ускорение отчётов), 2.6 (интеграционные тесты), 2.7 (двойной клик), 2.8 (ревизия) — каждая с файлами Create/Modify, падающим тестом (полный код), командами запуска с ожиданием, полным кодом реализации, докладом. Без `git commit` (за оркестратором).
- **Нет ли «TBD» / «добавить обработку»?** Нет: все блоки кода приведены целиком; пороги, ключи, суффиксы — конкретными значениями.
- **Совпадают ли имена функций/сигнатуры между задачами?** Проверено сквозное согласование:
  - `account_sync_lock(account, scope)`, `sync_lock(scope)`, `SyncLockBusy`, `_advisory_key(account_pk, scope)`, `SCOPE_BITS={"timesheet":1,"project":2}` — определены в 2.2, импортируются в `views.py` (2.2) и в тестах 2.2; в 2.6 не используются (no-op на sqlite).
  - `DELETE_SAFETY_RATIO = 0.5`, `traversal_complete` — введены в 2.1, проверяются в 2.6 (`test_midway_empty_page_keeps_data`) и в 2.8.
  - `USER_NAMES_CACHE_PREFIX = "user-names-v1"` — добавляется в `project_board_shared.py` (2.4), импортируется в `bitrix_data_access.py` (2.4).
  - `build_filtered_timesheet_queryset`, `build_project_title_lookups` — сигнатуры НЕ меняются (2.5), что сохраняет вызовы в `views.py`/`report_services`.
  - `syncTimesheets(): Promise<{status; count}>` (api.ts) — потребляется `generateReport` (2.3); `isGenerating` добавляется в возврат `useReportGenerator` (2.7) — оба правят один файл, но в разных волнах (1 и 3), конфликта нет.
- **Совпадение фикстур:** все Django-тесты создают `Bitrix24Account.objects.create(...)` с теми же обязательными полями, что и существующий `QueryStabilityTest.setUp` (`b24_user_id`, `is_b24_user_admin`, `member_id`, `is_master_account`, `domain_url`, `status`, `application_version`) — проверено чтением `tests_reports.py:296-305`.

## Ручная проверка для заказчика (простыми словами)

1. **Синхронизация не теряет данные при сбое Битрикс.** Если во время обновления Битрикс «икнул» и вернул пустую страницу на середине — приложение НЕ стирает накопленные записи, а оставляет последние сохранённые и пишет предупреждение в лог. Раньше в этом случае можно было потерять большую часть из 103 000 записей.
2. **Два обновления одновременно не мешают друг другу.** Если нажать «Обновить» в двух вкладках/устройствах одновременно (на боевом Postgres), второе получит вежливый ответ «Синхронизация уже выполняется, подождите» вместо двойной нагрузки и гонок. (На тестовой базе это не воспроизводится — там однопоточно.)
3. **Честное предупреждение вместо ложного «успех».** Если данные не удалось обновить, на странице «Ежедневная нагрузка» появляется жёлтая плашка «данные не обновлены, показаны последние сохранённые». Раньше показывался «успех», хотя данные были старые. (По остальным отчётам — см. открытый вопрос ниже: возможно, плашку стоит добавить и туда.)
4. **Отчёты строятся быстрее.** Список сотрудников берётся из кэша (30 минут), а не запрашивается у Битрикс на каждый отчёт; исключение архивных проектов делается одним запросом вместо трёх. Цифры в отчётах не меняются — только скорость.
5. **Двойной клик «Сформировать» безопасен.** Быстрое двойное нажатие больше не запускает обновление и отчёт дважды — второй клик игнорируется, пока идёт первый.
6. **Секреты не утекают в ответах.** При сбое обновления пользователю больше не показывается технический текст ошибки — он уходит только в серверный лог.
7. **Ничего из работающего не сломалось.** Базовый набор автотестов (41 проверка) остаётся зелёным; 2 давно известные ошибки в финансовом модуле — не новые и связаны с отключённой функцией.

---

## Открытые вопросы — решить ДО старта волны 1

1. **Порог `DELETE_SAFETY_RATIO = 0.5` (задача 2.1).** Принят компромисс: удаление при полном обходе ИЛИ пустой БД ИЛИ собрано ≥50% от текущего числа записей. Нужно подтверждение продукта: бывает ли легитимный сценарий «через ПОЛНЫЙ синк (без дат) разом удаляется БОЛЬШЕ половины записей аккаунта»? Если да и это штатно — порог 0.5 заблокирует такую чистку до следующего синка (она просто отложится, не потеряется). Если такого не бывает — 0.5 безопасен с запасом. Моя рекомендация: оставить 0.5; массовые чистки делать через scoped-окно (там своя защита).
2. **Плашка `syncWarning` на 6 отчётах (задача 2.3).** Сейчас панель предупреждения есть ТОЛЬКО на `daily.client.vue`; остальные 6 страниц (`project`, `focus-analysis`, `project-task`, `employee`, `revenue-leakage`, `time-discipline`) её не показывают и не передают `allowSyncFallback`. Движок `generateReport` после 2.3 будет корректно выставлять `syncWarning` для всех, но визуально его увидят только на `daily`. Вопрос: расширить ли панель + `allowSyncFallback` на остальные 6 страниц (это правки 6 шаблонов — рост scope 2.3), или принять, что пока предупреждение видно только на `daily`, а на остальных отчёт молча строится по последним данным? Рекомендация: вынести расширение на 6 страниц в отдельную мелкую задачу, чтобы не раздувать 2.3.
3. **Замок в задаче 2.2 — место и тип.** Принято: замок в VIEW (декоратор для 2 эндпоинтов + контекст-менеджер внутри `save_configuration`), ключи РАЗДЕЛЬНЫЕ per-account (`timesheet`/`project`), тип — **session-level** `pg_try_advisory_lock` с `finally`-release, а НЕ `xact`-lock (обоснование: боевой синк состоит из многих коротких транзакций + длинных HTTP, единая гигантская транзакция под xact-lock сломала бы батч-дизайн и держала бы блокировку БД минутами). Это сознательное отклонение от формулировки ТЗ («xact_lock»). Нужно подтверждение, что session-lock приемлем (он штатно снимается и при падении процесса — при закрытии соединения PG).
4. **`str(exc)` в `save_configuration` (смежно с 2.3).** В `save_configuration` ветка `except Exception as sync_exc` кладёт `str(sync_exc)` в `response_payload["project_sync"]["warning"]` (views.py:1575) — та же утечка текста исключения, что чиним в `timesheet_sync`. Scope 2.3 по ТЗ — только `timesheet_sync`. Вопрос: чистить ли `save_configuration` в этом же спринте (тогда расширить 2.3 или 2.2) или вынести в бэклог. Рекомендация: вынести в бэклог отдельным пунктом (это админский эндпоинт, риск ниже).
5. **Кэш архивных проектов в 2.5.** Принято: НЕ кэшировать, обойтись одним `values_list` вместо трёх QuerySet (проще, безопаснее, эквивалентно). Если на боевом объёме (229 проектов) этого окажется мало — кэш архивных id по account на короткий TTL с инвалидацией при синке/архивации можно добавить отдельной задачей. Подтвердить, что минимальный вариант устраивает на старте.
6. **Инвалидация кэша `fetch_users` в 2.4.** Принято: НЕ добавлять в `invalidate_project_runtime_caches` (синк имена не меняет; TTL 30 мин достаточно). Если бизнес ожидает мгновенного отражения переименования сотрудника в отчётах — потребуется явная инвалидация (точка роста). Подтвердить, что задержка до 30 мин по ФИО приемлема.
