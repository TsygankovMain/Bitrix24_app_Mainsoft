"""Тесты автосинхронизации по расписанию (задача 3.6).

Django TestCase, sqlite, мок Bitrix/сервисов.
БЕЗ sys.modules/django.setup() — Django уже настроен test-раннером.
"""
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.utils import timezone

from .models import Bitrix24Account, SyncRun
from .sync_scheduler_service import run_scheduled_sync, select_portal_accounts


def _account(member_id, master=True, b24_user_id=1, status="active"):
    return Bitrix24Account.objects.create(
        b24_user_id=b24_user_id, is_b24_user_admin=True, member_id=member_id,
        is_master_account=master, domain_url=f"{member_id}.bitrix24.ru",
        status=status, application_version=1,
    )


class SelectPortalAccountsTest(TestCase):
    def test_one_representative_per_member_prefers_master(self):
        m1_master = _account("m1", master=True, b24_user_id=1)
        _account("m1", master=False, b24_user_id=2)   # тот же портал, не мастер
        m2 = _account("m2", master=True, b24_user_id=3)
        reps = select_portal_accounts()
        rep_ids = {a.pk for a in reps}
        self.assertIn(m1_master.pk, rep_ids)
        self.assertIn(m2.pk, rep_ids)
        self.assertEqual(len(reps), 2)  # по одному на member_id

    def test_skips_inactive_accounts(self):
        _account("m3", master=True, status="inactive")
        reps = select_portal_accounts()
        self.assertEqual(len(reps), 0)


class RunScheduledSyncTest(TestCase):
    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_writes_syncrun_journal_and_calls_sync(self, mock_cfg_cls, mock_svc_cls):
        _account("m1", master=True)
        # конфиг портала: автосинк включён, маппинг есть
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {
            "sp_entity_type_id": 1, "fields_mapping": {"data": "createdTime"},
            "auto_sync_enabled": True,
        }
        mock_cfg_cls.return_value = mock_cfg
        mock_svc = MagicMock()
        mock_svc.sync_all.return_value = 42
        mock_svc_cls.return_value = mock_svc

        run = run_scheduled_sync(days=7)

        self.assertIsInstance(run, SyncRun)
        self.assertEqual(run.status, "success")
        self.assertEqual(run.portals_total, 1)
        self.assertEqual(run.portals_synced, 1)
        self.assertEqual(run.items_synced, 42)
        self.assertIsNotNone(run.finished_at)
        # sync_all вызван с окном дат (инкремент), не пустой
        args, kwargs = mock_svc.sync_all.call_args
        self.assertTrue(kwargs.get("date_from"))
        self.assertTrue(kwargs.get("date_to"))

    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_disabled_portal_is_skipped(self, mock_cfg_cls, mock_svc_cls):
        _account("m1", master=True)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {
            "sp_entity_type_id": 1, "fields_mapping": {"data": "createdTime"},
            "auto_sync_enabled": False,   # автосинк выключен на портале
        }
        mock_cfg_cls.return_value = mock_cfg
        mock_svc_cls.return_value = MagicMock()

        run = run_scheduled_sync(days=7)
        self.assertEqual(run.portals_total, 1)
        self.assertEqual(run.portals_synced, 0)   # пропущен по флагу
        mock_svc_cls.return_value.sync_all.assert_not_called()

    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_one_portal_failure_does_not_abort_run(self, mock_cfg_cls, mock_svc_cls):
        _account("m1", master=True, b24_user_id=1)
        _account("m2", master=True, b24_user_id=3)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {
            "sp_entity_type_id": 1, "fields_mapping": {"data": "createdTime"},
            "auto_sync_enabled": True,
        }
        mock_cfg_cls.return_value = mock_cfg
        mock_svc = MagicMock()
        mock_svc.sync_all.side_effect = [RuntimeError("boom"), 10]  # m1 падает, m2 ок
        mock_svc_cls.return_value = mock_svc

        run = run_scheduled_sync(days=7)
        # запуск не упал; один портал успешен, статус partial
        self.assertEqual(run.portals_total, 2)
        self.assertEqual(run.portals_synced, 1)
        self.assertEqual(run.status, "partial")
        self.assertIn("boom", run.error_summary or "")
