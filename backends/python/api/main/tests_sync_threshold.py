"""Тесты защиты от массового удаления при неполном обходе keyset (_sync_full).

Sprint 2, задача 2.1 — DELETE_SAFETY_RATIO + traversal_complete.

Запуск:
    cd backends/python/api
    ./.venv/bin/python manage.py test main.tests_sync_threshold --settings=test_settings
"""

from datetime import datetime

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
    """Минимальный двойник Client: возвращает заранее заданные страницы по порядку."""

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
        # Ключевой кейс порога: обход оборвался по НЕПРОДВИНУВШЕМУСЯ курсору
        # (batch_max_id <= last_id), собрав < 50% от БД. Это единственная
        # ветка, которая после фикса Дефекта 5-довеска (пустая страница ->
        # traversal_complete=True, см. test_exact_multiple_of_page_size_*
        # ниже) всё ещё оставляет traversal_complete=False: курсор не
        # продвинулся — сигнал аномалии (не «дошли до конца», а «застряли»),
        # доверять такому обходу нельзя. Эмулируем: стр.1 = [1..50]
        # (count==page_size -> цикл продолжится, last_id=50), стр.2 — ТЕ ЖЕ
        # id 1..50 (курсор не продвинулся -> break без traversal_complete).
        ids = list(range(1, 201))
        self._seed(*ids)
        first_page = {"result": {"items": [_make_item(i) for i in range(1, 51)]}}  # count==50 -> цикл продолжится
        stuck_page = {"result": {"items": [_make_item(i) for i in range(1, 51)]}}  # курсор не продвинулся
        service = TimesheetSyncService(_FakeClient([first_page, stuck_page]), self.account, self.config)
        service._sync_full()
        remaining_count = TimesheetItem.objects.filter(bitrix24_account=self.account).count()
        # Собрано 50 id из 200 (25% < 50%) и traversal_complete=False -> удаление ПРОПУЩЕНО.
        self.assertEqual(remaining_count, 200)

    def test_exact_multiple_of_page_size_marks_traversal_complete(self):
        """Дефект 5 (довесок, fixwave): ветка `if not items: break` раньше НЕ

        ставила traversal_complete=True. Это било по датасетам, чей размер —
        точное кратное page_size (50): последняя страница ровно 50 записей
        (count == page_size -> цикл продолжается), следующая страница —
        уже настоящий, легитимный конец (items=[]). Без флага такой обход
        ошибочно считался НЕЗАВЕРШЁННЫМ, и если к этому моменту в Bitrix
        реально удалили часть записей (собрано меньше 50% от БД), сирот
        не подчищали вовсе.

        Эмулируем: в Bitrix реально осталось ровно 50 записей (id 1..50,
        кратно page_size) — стр.1 отдаёт все 50 (count==page_size, цикл
        продолжается), стр.2 — пустая (реальный конец). В БД при этом 150
        записей (100 из них — настоящие сироты, id 51..150, > 50% от 150 —
        то есть ratio-проверка сама по себе НЕ спасла бы, будь она одна)."""
        ids = list(range(1, 151))
        self._seed(*ids)
        full_page = {"result": {"items": [_make_item(i) for i in range(1, 51)]}}  # ровно page_size
        empty_page = {"result": {"items": []}}  # легитимный конец обхода
        service = TimesheetSyncService(_FakeClient([full_page, empty_page]), self.account, self.config)
        service._sync_full()
        remaining = set(TimesheetItem.objects.filter(bitrix24_account=self.account).values_list("bitrix_id", flat=True))
        # traversal_complete=True -> удаление настоящих сирот (51..150) выполняется,
        # несмотря на то, что collected(50) < 50% от current_count(150).
        self.assertEqual(remaining, set(range(1, 51)))
