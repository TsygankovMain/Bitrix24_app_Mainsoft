"""Тесты автосинхронизации по расписанию (задача 3.6).

Django TestCase, sqlite, мок Bitrix/сервисов.
БЕЗ sys.modules/django.setup() — Django уже настроен test-раннером.
"""
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Bitrix24Account, Portal, SyncRun
from .sync_scheduler_service import run_scheduled_sync, select_portal_accounts


def _account(member_id, master=True, b24_user_id=1, status="active", portal=None):
    return Bitrix24Account.objects.create(
        b24_user_id=b24_user_id, is_b24_user_admin=True, member_id=member_id,
        is_master_account=master, domain_url=f"{member_id}.bitrix24.ru",
        status=status, application_version=1, portal=portal,
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

    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_full_mode_calls_sync_all_without_dates(self, mock_cfg_cls, mock_svc_cls):
        _account("m1", master=True)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {
            "sp_entity_type_id": 1, "fields_mapping": {"data": "createdTime"},
            "auto_sync_enabled": True,
        }
        mock_cfg_cls.return_value = mock_cfg
        mock_svc = MagicMock()
        mock_svc.sync_all.return_value = 0
        mock_svc_cls.return_value = mock_svc

        run_scheduled_sync(days=7, scope="timesheet", full=True)

        # full → без date_from/date_to (ночная полная сверка, _sync_full)
        _, kwargs = mock_svc.sync_all.call_args
        self.assertIsNone(kwargs.get("date_from"))
        self.assertIsNone(kwargs.get("date_to"))

    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_incremental_mode_still_passes_dates(self, mock_cfg_cls, mock_svc_cls):
        _account("m1", master=True)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {
            "sp_entity_type_id": 1, "fields_mapping": {"data": "createdTime"},
            "auto_sync_enabled": True,
        }
        mock_cfg_cls.return_value = mock_cfg
        mock_svc = MagicMock()
        mock_svc.sync_all.return_value = 3
        mock_svc_cls.return_value = mock_svc

        run_scheduled_sync(days=7, scope="timesheet", full=False)

        _, kwargs = mock_svc.sync_all.call_args
        self.assertTrue(kwargs.get("date_from"))
        self.assertTrue(kwargs.get("date_to"))

    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_marks_last_timesheet_synced_at_after_incremental_sync(self, mock_cfg_cls, mock_svc_cls):
        account = _account("m1", master=True)
        self.assertIsNone(account.last_timesheet_synced_at)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {
            "sp_entity_type_id": 1, "fields_mapping": {"data": "createdTime"},
            "auto_sync_enabled": True,
        }
        mock_cfg_cls.return_value = mock_cfg
        mock_svc = MagicMock()
        mock_svc.sync_all.return_value = 5
        mock_svc_cls.return_value = mock_svc

        run_scheduled_sync(scope="timesheet")

        account.refresh_from_db()
        self.assertIsNotNone(account.last_timesheet_synced_at)

    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_marks_last_timesheet_synced_at_after_full_sync(self, mock_cfg_cls, mock_svc_cls):
        account = _account("m1", master=True)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {
            "sp_entity_type_id": 1, "fields_mapping": {"data": "createdTime"},
            "auto_sync_enabled": True,
        }
        mock_cfg_cls.return_value = mock_cfg
        mock_svc = MagicMock()
        mock_svc.sync_all.return_value = 12
        mock_svc_cls.return_value = mock_svc

        run_scheduled_sync(scope="timesheet", full=True)

        account.refresh_from_db()
        self.assertIsNotNone(account.last_timesheet_synced_at)

    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_does_not_mark_when_sync_fails(self, mock_cfg_cls, mock_svc_cls):
        account = _account("m1", master=True)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {
            "sp_entity_type_id": 1, "fields_mapping": {"data": "createdTime"},
            "auto_sync_enabled": True,
        }
        mock_cfg_cls.return_value = mock_cfg
        mock_svc = MagicMock()
        mock_svc.sync_all.side_effect = RuntimeError("boom")
        mock_svc_cls.return_value = mock_svc

        run_scheduled_sync(scope="timesheet")

        account.refresh_from_db()
        self.assertIsNone(account.last_timesheet_synced_at)


class RunScheduledSyncProjectScopeTest(TestCase):
    """Тесты scope="project": синк проектов без timesheet."""

    @patch("main.sync_scheduler_service.ProjectSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_project_scope_calls_project_sync_service(self, mock_cfg_cls, mock_proj_cls):
        """scope=project вызывает ProjectSyncService.sync(), а не TimesheetSyncService."""
        _account("m1", master=True)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg
        mock_proj = MagicMock()
        mock_proj.sync.return_value = {"synced": 15, "created": 5, "updated": 10}
        mock_proj_cls.return_value = mock_proj

        run = run_scheduled_sync(scope="project")

        self.assertIsInstance(run, SyncRun)
        self.assertEqual(run.scope, "project")
        self.assertEqual(run.status, "success")
        self.assertEqual(run.portals_total, 1)
        self.assertEqual(run.portals_synced, 1)
        # items_synced = result["synced"]
        self.assertEqual(run.items_synced, 15)
        mock_proj.sync.assert_called_once()

    @patch("main.sync_scheduler_service.ProjectSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_project_scope_lock_uses_project_scope(self, mock_cfg_cls, mock_proj_cls):
        """advisory-lock берётся со scope='project', а не 'timesheet'."""
        _account("m1", master=True)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg
        mock_proj = MagicMock()
        mock_proj.sync.return_value = {"synced": 5, "created": 2, "updated": 3}
        mock_proj_cls.return_value = mock_proj

        with patch("main.sync_scheduler_service.account_sync_lock") as mock_lock:
            mock_lock.return_value.__enter__ = MagicMock(return_value=None)
            mock_lock.return_value.__exit__ = MagicMock(return_value=False)
            run_scheduled_sync(scope="project")

        # lock вызван ровно один раз и с scope="project"
        mock_lock.assert_called_once()
        _, kwargs = mock_lock.call_args
        self.assertEqual(kwargs.get("scope"), "project")

    @patch("main.sync_scheduler_service.ProjectSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_project_scope_auto_sync_disabled_skips_portal(self, mock_cfg_cls, mock_proj_cls):
        """auto_sync_enabled=False при scope=project → портал пропущен."""
        _account("m1", master=True)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": False}
        mock_cfg_cls.return_value = mock_cfg
        mock_proj_cls.return_value = MagicMock()

        run = run_scheduled_sync(scope="project")
        self.assertEqual(run.portals_synced, 0)
        mock_proj_cls.return_value.sync.assert_not_called()

    @patch("main.sync_scheduler_service.ProjectSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_project_scope_one_failure_does_not_abort_run(self, mock_cfg_cls, mock_proj_cls):
        """Падение одного портала при scope=project не прерывает остальные."""
        _account("m1", master=True, b24_user_id=1)
        _account("m2", master=True, b24_user_id=3)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg
        mock_proj = MagicMock()
        mock_proj.sync.side_effect = [RuntimeError("proj_boom"), {"synced": 7, "created": 3, "updated": 4}]
        mock_proj_cls.return_value = mock_proj

        run = run_scheduled_sync(scope="project")
        self.assertEqual(run.portals_total, 2)
        self.assertEqual(run.portals_synced, 1)
        self.assertEqual(run.status, "partial")
        self.assertIn("proj_boom", run.error_summary or "")

    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ProjectSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_project_scope_does_not_call_timesheet_service(self, mock_cfg_cls, mock_proj_cls, mock_ts_cls):
        """scope=project НЕ должен вызывать TimesheetSyncService."""
        _account("m1", master=True)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg
        mock_proj = MagicMock()
        mock_proj.sync.return_value = {"synced": 3, "created": 1, "updated": 2}
        mock_proj_cls.return_value = mock_proj

        run_scheduled_sync(scope="project")

        mock_ts_cls.assert_not_called()


class RunScheduledSyncTimesheetAccountSetTest(TestCase):
    """CRITICAL fixwave finding #1.

    scope="timesheet" раньше ВСЕГДА синкал один представитель на портал
    (select_portal_accounts()), но TimesheetItem скоуплен по-разному в
    зависимости от USE_PORTAL_SCOPING (см. tenant_scoping.scope_to_tenant):
    под флагом OFF (дефолт) — ПО АККАУНТУ. Значит представитель освежал только
    свои же строки, а отчёты остальных пользователей того же портала замирали
    навсегда (планировщик их никогда не трогал). scope="project" эта проблема
    не касается (ProjectCard общая на портал) — регресс ниже это подтверждает.
    """

    @override_settings(USE_PORTAL_SCOPING=False)
    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_flag_off_syncs_every_active_account_and_marks_each(self, mock_cfg_cls, mock_svc_cls):
        """Флаг OFF: данные по аккаунту -> синкать нужно ВСЕХ активных, не
        только представителя портала."""
        acc1 = _account("m1", master=True, b24_user_id=1)
        acc2 = _account("m1", master=False, b24_user_id=2)  # тот же портал (member_id), второй юзер
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {
            "sp_entity_type_id": 1, "fields_mapping": {"data": "createdTime"},
            "auto_sync_enabled": True,
        }
        mock_cfg_cls.return_value = mock_cfg
        mock_svc = MagicMock()
        mock_svc.sync_all.return_value = 5
        mock_svc_cls.return_value = mock_svc

        run = run_scheduled_sync(scope="timesheet")

        self.assertEqual(run.portals_total, 2)
        self.assertEqual(run.portals_synced, 2)
        self.assertEqual(mock_svc_cls.call_count, 2)  # оба аккаунта реально синканы
        acc1.refresh_from_db()
        acc2.refresh_from_db()
        self.assertIsNotNone(acc1.last_timesheet_synced_at)
        self.assertIsNotNone(acc2.last_timesheet_synced_at)

    @override_settings(USE_PORTAL_SCOPING=True)
    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_flag_on_syncs_one_representative_but_marks_whole_portal(self, mock_cfg_cls, mock_svc_cls):
        """Флаг ON: данные общие на портал -> синкает один представитель, но
        маркер свежести проставляется ВСЕМ активным аккаунтам портала."""
        portal = Portal.objects.create(member_id="m1", domain_url="m1.bitrix24.ru", status="active")
        acc1 = _account("m1", master=True, b24_user_id=1, portal=portal)
        acc2 = _account("m1", master=False, b24_user_id=2, portal=portal)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {
            "sp_entity_type_id": 1, "fields_mapping": {"data": "createdTime"},
            "auto_sync_enabled": True,
        }
        mock_cfg_cls.return_value = mock_cfg
        mock_svc = MagicMock()
        mock_svc.sync_all.return_value = 5
        mock_svc_cls.return_value = mock_svc

        run = run_scheduled_sync(scope="timesheet")

        self.assertEqual(run.portals_total, 1)       # один представитель в множестве
        self.assertEqual(run.portals_synced, 1)
        self.assertEqual(mock_svc_cls.call_count, 1)  # реально синкается только он
        acc1.refresh_from_db()
        acc2.refresh_from_db()
        self.assertIsNotNone(acc1.last_timesheet_synced_at)
        self.assertIsNotNone(acc2.last_timesheet_synced_at)  # но маркер — обоим

    @override_settings(USE_PORTAL_SCOPING=True)
    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_flag_on_without_portal_marks_only_that_account(self, mock_cfg_cls, mock_svc_cls):
        """Флаг ON, но account.portal ещё null (переходный период backfill) ->
        фолбэк: маркер только этому аккаунту, без падения на portal=None."""
        acc = _account("m1", master=True, b24_user_id=1, portal=None)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {
            "sp_entity_type_id": 1, "fields_mapping": {"data": "createdTime"},
            "auto_sync_enabled": True,
        }
        mock_cfg_cls.return_value = mock_cfg
        mock_svc = MagicMock()
        mock_svc.sync_all.return_value = 5
        mock_svc_cls.return_value = mock_svc

        run_scheduled_sync(scope="timesheet")

        acc.refresh_from_db()
        self.assertIsNotNone(acc.last_timesheet_synced_at)

    @patch("main.sync_scheduler_service.ProjectSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_project_scope_still_uses_one_representative_regardless_of_flag(self, mock_cfg_cls, mock_proj_cls):
        """Регресс: scope="project" не должен трогаться этим фиксом — всегда
        один представитель на портал (member_id), независимо от USE_PORTAL_SCOPING."""
        _account("m1", master=True, b24_user_id=1)
        _account("m1", master=False, b24_user_id=2)  # тот же портал — должен быть пропущен
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg
        mock_proj = MagicMock()
        mock_proj.sync.return_value = {"synced": 1, "created": 1, "updated": 0}
        mock_proj_cls.return_value = mock_proj

        run = run_scheduled_sync(scope="project")

        self.assertEqual(run.portals_total, 1)
        self.assertEqual(mock_proj_cls.call_count, 1)
