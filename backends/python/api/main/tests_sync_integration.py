"""Интеграционные тесты _sync_full на реальной sqlite-БД (Sprint 2, задача 2.6).

БЕЗ моков transaction.atomic, БЕЗ sys.modules-заглушек.
Мок только Bitrix-клиента (call_method).

Покрывает:
- Идемпотентность: два синка одного ответа — без дублей.
- Orphan-удаление с порогом 2.1: настоящие сироты удаляются при полном обходе;
  обрыв на середине (< 50% собрано) — данные сохраняются.
- Частичный сбой _save_batch: состояние согласовано, исключение пробрасывается
  до orphan-delete (удаление пропускается).

Запуск:
    cd backends/python/api
    ./.venv/bin/python manage.py test main.tests_sync_integration --settings=test_settings
"""

from datetime import datetime
from unittest.mock import Mock

from django.test import TestCase
from django.utils import timezone

from .models import Bitrix24Account, TimesheetItem
from .timesheet_sync_service import TimesheetSyncService


def _item(bitrix_id):
    """Минимальный сырой ответ crm.item.list — один элемент items[].

    Содержит все поля, необходимые normalize_items при маппинге
    {"data": "createdTime", "id_zadachi": "ufCrmTask"}:
      - "id"          → id_elem
      - "ufCrmTask"   → id_zadachi (должен быть непустым — иначе normalize дропнет)
      - "createdTime" → data (дата-отражения) и source_created_at
    """
    return {
        "id": bitrix_id,
        "ufCrmTask": str(bitrix_id),
        "createdTime": "2026-01-01T09:00:00+03:00",
    }


class _ScriptedClient:
    """Отдаёт заранее заданные ответы crm.item.list по индексу вызова call_method.

    Фильтр {">id": last_id} из keyset-курсора ИГНОРИРУЕТСЯ намеренно: тест
    формирует страницы с уже правильными id-диапазонами, поэтому дополнительная
    фильтрация не нужна. Это достаточно для корректной эмуляции — batch_max_id
    продвигается по id внутри элементов, а не по индексу вызова.

    После исчерпания responses возвращает пустую страницу (конец списка).
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self._idx = 0
        # _call_with_retry обращается к self.client._bitrix_token.call_method
        self._bitrix_token = self

    def call_method(self, method, params):
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
        else:
            resp = {"result": {"items": []}}
        self._idx += 1
        return resp


class _Config:
    """Минимальная конфигурация для _sync_full (без scoped-синка)."""

    @staticmethod
    def make():
        return {
            "sp_entity_type_id": 1,
            "fields_mapping": {"data": "createdTime", "id_zadachi": "ufCrmTask"},
        }


# ---------------------------------------------------------------------------
# 1. Идемпотентность
# ---------------------------------------------------------------------------

class SyncIdempotencyTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1,
            is_b24_user_admin=True,
            member_id="m-int-1",
            is_master_account=True,
            domain_url="example.bitrix24.ru",
            status="active",
            application_version=1,
        )

    def test_two_full_syncs_same_response_no_duplicates(self):
        """Два последовательных синка одинакового ответа не создают дублей."""
        # count=3 < page_size=50 → traversal_complete=True → безопасно удалять сирот
        page = {"result": {"items": [_item(1), _item(2), _item(3)]}}

        svc1 = TimesheetSyncService(_ScriptedClient([page]), self.account, _Config.make())
        n1 = svc1._sync_full()
        count_after_first = TimesheetItem.objects.filter(bitrix24_account=self.account).count()

        svc2 = TimesheetSyncService(_ScriptedClient([page]), self.account, _Config.make())
        n2 = svc2._sync_full()
        count_after_second = TimesheetItem.objects.filter(bitrix24_account=self.account).count()

        self.assertEqual(count_after_first, 3, "После первого синка должно быть 3 записи")
        self.assertEqual(count_after_second, 3, "После второго синка дублей быть не должно")
        self.assertEqual(n1, n2, "Оба синка должны вернуть одинаковое число обработанных элементов")


# ---------------------------------------------------------------------------
# 2. Orphan-удаление с порогом (задача 2.1)
# ---------------------------------------------------------------------------

class SyncOrphanWithThresholdTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1,
            is_b24_user_admin=True,
            member_id="m-int-2",
            is_master_account=True,
            domain_url="example.bitrix24.ru",
            status="active",
            application_version=1,
        )

    def test_true_orphans_deleted_on_complete_traversal(self):
        """При полном обходе настоящие сироты (не вернул Битрикс) удаляются.

        Первый синк: 1,2,3 → три записи в БД.
        Второй синк: 1,2 (count<50 → traversal_complete=True) → запись id=3 удаляется.
        """
        first = {"result": {"items": [_item(1), _item(2), _item(3)]}}
        TimesheetSyncService(_ScriptedClient([first]), self.account, _Config.make())._sync_full()

        second = {"result": {"items": [_item(1), _item(2)]}}
        TimesheetSyncService(_ScriptedClient([second]), self.account, _Config.make())._sync_full()

        remaining = set(
            TimesheetItem.objects.filter(bitrix24_account=self.account).values_list("bitrix_id", flat=True)
        )
        self.assertEqual(remaining, {1, 2}, "Запись id=3 должна быть удалена как настоящая сирота")

    def test_midway_empty_page_keeps_data(self):
        """Обрыв посередине (собрано < 50% от БД) → порог 2.1 блокирует удаление.

        Шаг 1 (сидирование): 4 страницы по 50 элементов (ids 1-200).
          Каждая страница имеет count=50=page_size → цикл продолжается.
          Пятый вызов возвращает [] → цикл прерывается.
          traversal_complete=False, но current_count=0 в начале → safe_to_delete=True
          (защита «пустая БД» из 2.1). Все 200 записей сохраняются.

        Шаг 2 (обрыв): 1 страница с ids 1-50, затем пустая.
          traversal_complete=False, collected=50 из current_count=200 → 25% < 50%
          → safe_to_delete=False → удаление пропущено → 200 записей целы.
        """
        # --- Шаг 1: сидирование 200 записей ---
        pages_seed = [
            {"result": {"items": [_item(i) for i in range(1, 51)]}},    # ids 1-50,  count=50
            {"result": {"items": [_item(i) for i in range(51, 101)]}},  # ids 51-100, count=50
            {"result": {"items": [_item(i) for i in range(101, 151)]}}, # ids 101-150, count=50
            {"result": {"items": [_item(i) for i in range(151, 201)]}}, # ids 151-200, count=50
            {"result": {"items": []}},  # конец — пустая страница
        ]
        TimesheetSyncService(_ScriptedClient(pages_seed), self.account, _Config.make())._sync_full()

        seeded = TimesheetItem.objects.filter(bitrix24_account=self.account).count()
        self.assertEqual(seeded, 200, "После сидирования должно быть ровно 200 записей")

        # --- Шаг 2: оборванный синк ---
        # Первая страница full (50 элементов = page_size → цикл продолжится),
        # вторая — пустая (обрыв). Итого: собрано 50/200 = 25% < порог 50%.
        broken = [
            {"result": {"items": [_item(i) for i in range(1, 51)]}},  # count=50=page_size → continue
            {"result": {"items": []}},                                  # обрыв
        ]
        TimesheetSyncService(_ScriptedClient(broken), self.account, _Config.make())._sync_full()

        self.assertEqual(
            TimesheetItem.objects.filter(bitrix24_account=self.account).count(),
            200,
            "Порог 2.1 должен заблокировать удаление при неполном обходе (25% < 50%)",
        )


# ---------------------------------------------------------------------------
# 3. Частичный сбой _save_batch
# ---------------------------------------------------------------------------

class SyncPartialBatchFailureTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1,
            is_b24_user_admin=True,
            member_id="m-int-3",
            is_master_account=True,
            domain_url="example.bitrix24.ru",
            status="active",
            application_version=1,
        )

    def test_save_batch_failure_on_nth_batch_leaves_consistent_state(self):
        """RuntimeError в _save_batch пробрасывается до orphan-delete (который НЕ выполняется).

        Предусловие: в БД есть запись bitrix_id=1 с employee_id="emp-old".
        _save_batch замещается бомбой (бросает RuntimeError на любом вызове).
        _sync_full должен пробросить исключение, НЕ дойдя до блока orphan-delete.
        Запись id=1 должна остаться нетронутой (employee_id="emp-old").
        """
        # Сидируем валидную запись id=1
        day = timezone.make_aware(datetime(2026, 1, 1, 9, 0))
        TimesheetItem.objects.create(
            bitrix24_account=self.account,
            bitrix_id=1,
            task_id="1",
            employee_id="emp-old",
            hours=1,
            project_id="p",
            project_title="P",
            date_reflection=day,
        )

        # Клиент отдаёт страницу с id 1,2 (count=2 < page_size → traversal_complete=True при успехе)
        page = {"result": {"items": [_item(1), _item(2)]}}
        svc = TimesheetSyncService(_ScriptedClient([page]), self.account, _Config.make())

        def _boom(items):
            raise RuntimeError("batch save failed")

        svc._save_batch = _boom  # падение на первой же пачке

        with self.assertRaises(RuntimeError, msg="_sync_full должен пробросить RuntimeError из _save_batch"):
            svc._sync_full()

        # Состояние согласовано:
        # 1. Исходная запись id=1 не перезаписана (employee_id остался "emp-old").
        # 2. Запись id=2 не создана.
        # 3. Блок orphan-delete не достигнут → запись id=1 не удалена.
        all_items = TimesheetItem.objects.filter(bitrix24_account=self.account)
        self.assertEqual(
            all_items.count(),
            1,
            "В БД должна остаться ровно одна запись (id=1); id=2 не создана, сироты не удалены",
        )
        item = all_items.get(bitrix_id=1)
        self.assertEqual(
            item.employee_id,
            "emp-old",
            "employee_id записи id=1 не должен быть изменён после сбоя _save_batch",
        )
