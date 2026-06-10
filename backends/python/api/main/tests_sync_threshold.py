"""Тесты защиты от массового удаления при неполном обходе keyset (_sync_full).

Sprint 2, задача 2.1 — DELETE_SAFETY_RATIO + traversal_complete.

Запуск:
    cd backends/python/api
    ./.venv/bin/python manage.py test main.tests_sync_threshold --settings=test_settings
"""

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
        # Ключевой кейс порога: обход оборвался НЕ по count<page_size, а по пустой странице
        # ПОСЛЕ непустой, собрав < 50% от БД. Эмулируем: стр.1 = [1..50] (count==page_size -> цикл
        # продолжится), стр.2 = [] (обрыв). traversal_complete=False, collected=50 из 200 (25% < 50%).
        ids = list(range(1, 201))
        self._seed(*ids)
        first_page = {"result": {"items": [_make_item(i) for i in range(1, 51)]}}  # count==50 -> цикл продолжится
        empty_page = {"result": {"items": []}}                                      # обрыв на середине
        service = TimesheetSyncService(_FakeClient([first_page, empty_page]), self.account, self.config)
        service._sync_full()
        remaining_count = TimesheetItem.objects.filter(bitrix24_account=self.account).count()
        # Собрано 50 id из 200 (25% < 50%) и traversal_complete=False -> удаление ПРОПУЩЕНО.
        self.assertEqual(remaining_count, 200)
