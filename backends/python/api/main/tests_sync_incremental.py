"""Тесты инкрементального синка таймшитов по updatedTime.

Спека: docs/superpowers/specs/2026-07-31-timesheet-incremental-updatedtime-design.md
План:  docs/superpowers/plans/2026-07-31-timesheet-incremental-updatedtime.md

Запуск:
    cd backends/python/api
    python3 manage.py test main.tests_sync_incremental --settings=test_settings
"""

import time as _time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from .models import Bitrix24Account, TimesheetItem
from .sync_scheduler_service import run_scheduled_sync
from .timesheet_sync_service import (
    INCREMENTAL_OVERLAP,
    TimesheetSyncService,
    build_incremental_filter,
    incremental_since,
    resolve_sync_mode,
)


def _raw_item(bitrix_id):
    """Сырой элемент crm.item.list (поля под маппинг _Config ниже)."""
    return {
        "id": bitrix_id,
        "ufCrmTask": str(bitrix_id),
        "createdTime": "2026-01-01T09:00:00+03:00",
    }


class _FakeClient:
    """Двойник Client: отдаёт заранее заданные страницы и пишет параметры вызовов.

    Паттерн из main/tests_sync_threshold.py: _call_with_retry дергает
    self.client._bitrix_token.call_method(method, params).
    """

    def __init__(self, pages=None):
        self._pages = list(pages or [])
        self._idx = 0
        self.calls = []            # список params каждого вызова
        self._bitrix_token = self

    def call_method(self, method, params):
        self.calls.append(params)
        if self._idx < len(self._pages):
            resp = self._pages[self._idx]
        else:
            resp = {"result": {"items": []}}
        self._idx += 1
        return resp

    @property
    def filters(self):
        return [c.get("filter", {}) for c in self.calls]


def _config():
    return {
        "sp_entity_type_id": 1,
        "fields_mapping": {"data": "createdTime", "id_zadachi": "ufCrmTask"},
    }


class _AccountMixin:
    def _account(self, member_id="m-inc"):
        return Bitrix24Account.objects.create(
            b24_user_id=1,
            is_b24_user_admin=True,
            member_id=member_id,
            is_master_account=True,
            domain_url="example.bitrix24.ru",
            status="active",
            application_version=1,
            refresh_token="rt",
        )

    def _seed(self, account, *bitrix_ids):
        day = timezone.make_aware(datetime(2026, 1, 1, 9, 0))
        for bid in bitrix_ids:
            TimesheetItem.objects.create(
                bitrix24_account=account,
                bitrix_id=bid,
                task_id=str(bid),
                employee_id="emp-1",
                hours=1,
                project_id="p1",
                project_title="P1",
                date_reflection=day,
            )


# ---------------------------------------------------------------------------
# 1. КРИТИЧНО (§4.5 спеки): инкремент не удаляет НИЧЕГО и НИКОГДА
# ---------------------------------------------------------------------------

class IncrementalNeverDeletesTest(_AccountMixin, TestCase):
    """§4.5: у инкремента нет окна, а выдача — единицы записей. Перенос
    orphan-логики _sync_scoped сюда удалил бы почти всю таблицу."""

    def setUp(self):
        self.account = self._account("m-inc-nodel")
        self.since = timezone.now() - timedelta(minutes=5)

    def test_does_not_delete_records_missing_from_response(self):
        """В БД 1..6, Битрикс вернул только 1 и 2 — остальные ОСТАЮТСЯ."""
        self._seed(self.account, 1, 2, 3, 4, 5, 6)
        client = _FakeClient([{"result": {"items": [_raw_item(1), _raw_item(2)]}}])
        service = TimesheetSyncService(client, self.account, _config())

        service._sync_incremental(self.since)

        remaining = set(
            TimesheetItem.objects.filter(bitrix24_account=self.account)
            .values_list("bitrix_id", flat=True)
        )
        self.assertEqual(
            remaining, {1, 2, 3, 4, 5, 6},
            "инкремент удалил записи, которых не было в выдаче — это §4.5 спеки, "
            "так теряется почти вся таблица",
        )

    def test_empty_response_deletes_nothing(self):
        """Пустая выдача — 0 записей, 0 удалений, без исключений."""
        self._seed(self.account, 1, 2, 3, 4, 5, 6)
        client = _FakeClient([{"result": {"items": []}}])
        service = TimesheetSyncService(client, self.account, _config())

        count = service._sync_incremental(self.since)

        self.assertEqual(count, 0)
        self.assertEqual(
            TimesheetItem.objects.filter(bitrix24_account=self.account).count(), 6,
            "пустая выдача Битрикса вычистила таблицу — инкремент не должен удалять ничего",
        )

    def test_never_calls_delete_scoped_orphans(self):
        """_delete_scoped_orphans не вызывается ни при какой выдаче."""
        self._seed(self.account, 1, 2, 3)
        for label, pages in (
            ("непустая выдача", [{"result": {"items": [_raw_item(1)]}}]),
            ("пустая выдача", [{"result": {"items": []}}]),
        ):
            with self.subTest(label):
                service = TimesheetSyncService(_FakeClient(pages), self.account, _config())
                service._delete_scoped_orphans = MagicMock()

                service._sync_incremental(self.since)

                service._delete_scoped_orphans.assert_not_called()

    def test_no_queryset_delete_is_issued(self):
        """Ни один .delete() по TimesheetItem не выполняется (страховка на
        случай, если удаление напишут не через _delete_scoped_orphans)."""
        self._seed(self.account, 1, 2, 3)
        client = _FakeClient([{"result": {"items": [_raw_item(1)]}}])
        service = TimesheetSyncService(client, self.account, _config())

        with patch(
            "django.db.models.query.QuerySet.delete",
            side_effect=AssertionError("инкремент вызвал QuerySet.delete()"),
        ):
            service._sync_incremental(self.since)


# ---------------------------------------------------------------------------
# 2. Граница фильтра (регресс на боевой баг 2fcd176)
# ---------------------------------------------------------------------------

class IncrementalFilterBoundaryTest(_AccountMixin, TestCase):
    """Битрикс читает строку-дату без времени как НАЧАЛО суток — именно так
    createdTime-фильтр молча терял всё созданное сегодня (2fcd176). Граница
    инкремента обязана быть полным ISO с таймзоной, а верхней границы нет
    вообще: ни одного ключа с '<' или '<='."""

    def test_filter_value_is_full_iso_with_timezone(self):
        since = timezone.now() - INCREMENTAL_OVERLAP
        flt = build_incremental_filter(since)

        self.assertEqual(list(flt.keys()), [">=updatedTime"])
        value = flt[">=updatedTime"]
        self.assertIsInstance(value, str)
        self.assertGreater(
            len(value), 10,
            f"граница сериализована как дата без времени ({value!r}) — "
            "Битрикс прочитает её как начало суток (боевой баг 2fcd176)",
        )
        self.assertEqual(value, since.isoformat())
        self.assertIn("T", value)

    def test_filter_has_no_upper_bound_keys(self):
        flt = build_incremental_filter(timezone.now())
        for key in flt:
            self.assertFalse(
                key.startswith("<"),
                f"в фильтре инкремента есть верхняя граница {key!r} — "
                "именно она дала оба бага 31.07",
            )

    def test_request_filter_has_no_upper_bound_keys(self):
        """Тот же инвариант на реальных параметрах запроса к crm.item.list."""
        account = self._account("m-inc-filter")
        since = timezone.now() - INCREMENTAL_OVERLAP
        client = _FakeClient([{"result": {"items": [_raw_item(1)]}}])
        service = TimesheetSyncService(client, account, _config())

        service._sync_incremental(since)

        self.assertTrue(client.filters, "не было ни одного вызова crm.item.list")
        for flt in client.filters:
            self.assertIn(">=updatedTime", flt)
            self.assertGreater(len(str(flt[">=updatedTime"])), 10)
            for key in flt:
                self.assertFalse(
                    key.startswith("<"),
                    f"верхняя граница {key!r} в фильтре запроса инкремента",
                )

    def test_incremental_since_subtracts_overlap(self):
        marker = timezone.now()
        self.assertEqual(incremental_since(marker, timedelta(minutes=5)), marker - timedelta(minutes=5))
        self.assertEqual(INCREMENTAL_OVERLAP, timedelta(minutes=5))
        self.assertEqual(incremental_since(marker), marker - INCREMENTAL_OVERLAP)


# ---------------------------------------------------------------------------
# 3. Продвижение маркера last_timesheet_synced_at (§4.3)
# ---------------------------------------------------------------------------

class SyncMarkerAdvanceTest(_AccountMixin, TestCase):
    """Маркер сдвигается на started_at, зафиксированное ДО обхода, и только
    после полностью успешного обхода. Правка во время обхода имеет
    updatedTime >= started_at и попадёт в следующую выборку."""

    CFG = {
        "sp_entity_type_id": 1,
        "fields_mapping": {"data": "createdTime"},
        "auto_sync_enabled": True,
    }

    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_marker_not_moved_when_traversal_raises(self, mock_cfg_cls, mock_svc_cls):
        account = self._account("m-marker-fail")
        account.last_timesheet_synced_at = None
        account.save(update_fields=["last_timesheet_synced_at"])
        mock_cfg_cls.return_value.get_configuration_sync.return_value = self.CFG
        mock_svc_cls.return_value.sync_all.side_effect = RuntimeError("boom")

        run_scheduled_sync(scope="timesheet")

        account.refresh_from_db()
        self.assertIsNone(
            account.last_timesheet_synced_at,
            "маркер сдвинулся при упавшем обходе — следующий запуск не перекроет "
            "пропущенный интервал, образуется дыра",
        )

    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_existing_marker_untouched_when_traversal_raises(self, mock_cfg_cls, mock_svc_cls):
        account = self._account("m-marker-keep")
        old = timezone.now() - timedelta(hours=3)
        account.last_timesheet_synced_at = old
        account.save(update_fields=["last_timesheet_synced_at"])
        mock_cfg_cls.return_value.get_configuration_sync.return_value = self.CFG
        mock_svc_cls.return_value.sync_all.side_effect = RuntimeError("boom")

        run_scheduled_sync(scope="timesheet")

        account.refresh_from_db()
        self.assertEqual(account.last_timesheet_synced_at, old)

    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_marker_moves_to_started_at_captured_before_traversal(self, mock_cfg_cls, mock_svc_cls):
        account = self._account("m-marker-ok")
        mock_cfg_cls.return_value.get_configuration_sync.return_value = self.CFG

        captured = {}

        def _slow_sync(*args, **kwargs):
            _time.sleep(0.05)
            captured["during"] = timezone.now()
            _time.sleep(0.05)
            return 7

        mock_svc_cls.return_value.sync_all.side_effect = _slow_sync

        run_scheduled_sync(scope="timesheet")

        account.refresh_from_db()
        self.assertIsNotNone(account.last_timesheet_synced_at)
        self.assertLess(
            account.last_timesheet_synced_at, captured["during"],
            "маркер поставлен на время ПОСЛЕ обхода: правки, сделанные во время "
            "обхода, потеряются — маркер обязан быть started_at, снятым ДО него",
        )


# ---------------------------------------------------------------------------
# 4. Выбор режима синка (§4.1)
# ---------------------------------------------------------------------------

class ResolveSyncModeTest(TestCase):
    def test_no_marker_is_full(self):
        self.assertEqual(
            resolve_sync_mode(marker=None, date_from=None, date_to=None, full=False),
            "full",
        )

    def test_marker_without_dates_is_incremental(self):
        self.assertEqual(
            resolve_sync_mode(marker=timezone.now(), date_from=None, date_to=None, full=False),
            "incremental",
        )

    def test_full_flag_wins(self):
        self.assertEqual(
            resolve_sync_mode(marker=timezone.now(), date_from=None, date_to=None, full=True),
            "full",
        )

    def test_both_dates_are_scoped(self):
        self.assertEqual(
            resolve_sync_mode(
                marker=timezone.now(),
                date_from="2026-07-01",
                date_to="2026-07-31",
                full=False,
            ),
            "scoped",
        )
