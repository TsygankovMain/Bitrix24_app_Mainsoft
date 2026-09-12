"""Тесты предохранителя по числу страниц у ручного (scoped) синка (Дефект 5, fixwave).

У синка задач (task_sync_service.py) уже были MAX_CHANGED_PAGES/MAX_CHUNKS,
у ручного синка таймшитов (_sync_scoped/_fetch_all_pages_batched в
timesheet_sync_service.py) предохранителя не было: на портале с большой
историей ручная кнопка синка тянула ВСЕ страницы одним батч-запросом и
занимала поток gunicorn на минуты.

Ключевая проверка — упор в MAX_PAGES не должен приводить к ложному удалению
"пропавших" записей: усечённая выборка неполна не потому, что записи реально
исчезли из Битрикса, а потому что мы сами остановили обход раньше.

Запуск:
    cd backends/python/api
    ./.venv/bin/python manage.py test main.tests_sync_scoped_max_pages --settings=test_settings
"""

from datetime import datetime

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


class _ScopedBatchFakeClient:
    """Двойник Client для _fetch_all_pages_batched: `total` записей, page_size=50.

    Первая страница — через call_method (start=0), остальные — одним
    call_batches (как и настоящий Bitrix-клиент в _fetch_all_pages_batched).
    Содержимое страницы определяется офсетом из params, а не порядком
    вызова — фильтр (A/B в _sync_scoped) игнорируется намеренно: обеим
    выборкам в тесте важно упереться в один и тот же MAX_PAGES.
    """

    def __init__(self, total, page_size=50):
        self.total = total
        self.page_size = page_size
        self._bitrix_token = self
        self.call_batches_calls = 0

    def call_method(self, method, params):
        start = params.get("start", 0)
        end = min(start + self.page_size, self.total)
        items = [_item(i) for i in range(start + 1, end + 1)] if start < self.total else []
        return {"result": {"items": items}, "total": self.total}

    def call_batches(self, methods, halt=False):
        self.call_batches_calls += 1
        sub_results = {}
        for key, (_method, params) in methods.items():
            start = params.get("start", 0)
            end = min(start + self.page_size, self.total)
            ids = range(start + 1, end + 1) if start < self.total else range(0)
            sub_results[key] = {"items": [_item(i) for i in ids]}
        return {"result": {"result": sub_results}}


class ScopedSyncMaxPagesTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1,
            is_b24_user_admin=True,
            member_id="m-scoped-max-pages",
            is_master_account=True,
            domain_url="example.bitrix24.ru",
            status="active",
            application_version=1,
        )
        self.config = {
            "sp_entity_type_id": 1,
            "fields_mapping": {"data": "createdTime", "id_zadachi": "ufCrmTask"},
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

    def test_hitting_max_pages_skips_deletion_and_warns(self):
        # В Bitrix "реально" 500 записей (10 страниц по 50) — воспроизводить
        # это в фикстуре БД не нужно, фейковый клиент отдаёт их по офсету.
        total = 500
        # В БД, кроме них, есть ещё 50 записей за пределами того, что урежет
        # MAX_PAGES=2 (первая страница + 1 офсетная = максимум 100 id).
        # Без фикса это выглядело бы как 450 "пропавших" и было бы удалено.
        self._seed(*range(1, total + 1))
        self._seed(*range(total + 1, total + 51))

        service = TimesheetSyncService(_ScopedBatchFakeClient(total), self.account, self.config)
        service.MAX_PAGES = 2

        with self.assertLogs("main.timesheet_sync_service", level="WARNING") as cm:
            service._sync_scoped("2026-01-01", "2026-01-01", "createdTime")

        remaining = TimesheetItem.objects.filter(bitrix24_account=self.account).count()
        self.assertEqual(remaining, total + 50)  # ничего не удалено

        joined = "\n".join(cm.output)
        self.assertIn("MAX_PAGES", joined)
        self.assertIn("skip deletion", joined.lower())

    def test_small_dataset_under_max_pages_deletes_true_orphans(self):
        """Контроль: тот же путь, но обход ПОЛНЫЙ (total ниже MAX_PAGES) —

        предохранитель не должен мешать нормальному удалению настоящих
        сирот внутри окна."""
        total = 30
        self._seed(*range(1, total + 1))
        self._seed(9001, 9002)  # сироты — Bitrix их больше не отдаёт

        service = TimesheetSyncService(_ScopedBatchFakeClient(total), self.account, self.config)
        service.MAX_PAGES = 400

        service._sync_scoped("2026-01-01", "2026-01-01", "createdTime")

        remaining_ids = set(
            TimesheetItem.objects.filter(bitrix24_account=self.account).values_list("bitrix_id", flat=True)
        )
        self.assertEqual(remaining_ids, set(range(1, total + 1)))
