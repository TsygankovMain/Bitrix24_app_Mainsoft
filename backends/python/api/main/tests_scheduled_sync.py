"""Тесты автосинхронизации по расписанию (задача 3.6).

Django TestCase, sqlite, мок Bitrix/сервисов.
БЕЗ sys.modules/django.setup() — Django уже настроен test-раннером.
"""
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Bitrix24Account, Portal, ProjectCard, SyncRun, TimesheetItem
from .project_board_shared import get_project_card_queryset
from .report_queries import build_filtered_timesheet_queryset
from .sync_scheduler_service import run_scheduled_sync, select_portal_accounts
from .tenant_scoping import scope_to_tenant


def _account(member_id, master=True, b24_user_id=1, status="active", portal=None, refresh_token="rt"):
    """refresh_token по умолчанию непустой: реальные аккаунты Bitrix24Account

    ВСЕГДА получают refresh_token при установке (см.
    update_or_create_from_oauth_placement_data) — это и есть новый критерий
    синк-пригодности (Дефект 1 fixwave-ревью). status ("active" по умолчанию)
    больше НЕ влияет на выбор аккаунтов для синка — в реальности это поле
    хранит статус подписки Битрикса (F/D/T/P/L/S), а не "active"/"inactive"
    (см. SelectPortalAccountsStatusFilterTest); параметр оставлен для тестов,
    которым нужно проверить именно значение поля status."""
    return Bitrix24Account.objects.create(
        b24_user_id=b24_user_id, is_b24_user_admin=True, member_id=member_id,
        is_master_account=master, domain_url=f"{member_id}.bitrix24.ru",
        status=status, application_version=1, portal=portal,
        refresh_token=refresh_token,
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

    def test_skips_accounts_without_refresh_token(self):
        """Критерий синк-пригодности — refresh_token, не status (см.
        SelectPortalAccountsStatusFilterTest). status оставлен дефолтным
        ("active" — как и у любого другого фикстурного аккаунта в этом
        файле), чтобы тест был RED именно из-за refresh_token, а не
        случайно проходил из-за нереалистичного значения status."""
        _account("m3", master=True, refresh_token="")
        reps = select_portal_accounts()
        self.assertEqual(len(reps), 0)


class SelectPortalAccountsStatusFilterTest(TestCase):
    """Дефект 1 (боевой инцидент, найден на прод-БД): Bitrix24Account.status

    хранит статус ПОДПИСКИ ПРИЛОЖЕНИЯ из Битрикса
    (OAuthPlacementData.status — см. models.update_or_create_from_oauth_placement_data,
    единственное место записи поля), а не "active"/"inactive". Значения на
    проде — только буквенные коды F/D/T/P/L/S ("подписка"), литерал "active"
    в это поле не попадает НИКОГДА. Прежний фильтр
    Bitrix24Account.objects.filter(status="active") поэтому не совпадал ни с
    одним реальным аккаунтом (прод: 157/157 аккаунтов status='S') — и
    select_portal_accounts()/_timesheet_sync_accounts() всегда возвращали
    пустой список: планировщик не синкал ни одного портала ни разу, ни для
    timesheet, ни для project.

    Новый критерий синк-пригодности — refresh_token: если он есть, аккаунт
    в принципе способен обновить access_token и авторизоваться в Bitrix24.
    """

    def test_selects_accounts_with_real_bitrix_statuses(self):
        for i, status in enumerate(["S", "L", "F", "T", "D", "P"], start=1):
            _account(f"m{i}", master=True, b24_user_id=i, status=status)

        reps = select_portal_accounts()

        self.assertEqual(len(reps), 6)

    def test_excludes_account_with_null_refresh_token(self):
        # status оставлен дефолтным ("active"), чтобы этот тест был RED до
        # фикса именно из-за refresh_token=None, а не из-за status.
        _account("m1", master=True, refresh_token=None)

        reps = select_portal_accounts()

        self.assertEqual(reps, [])


class AccountScopedSyncAccountsStatusFilterTest(TestCase):
    """Тот же Дефект 1, но для приватной _timesheet_sync_accounts() (переезжает

    в _account_scoped_sync_accounts() вместе с фиксом Дефекта 2) — проверяется
    через run_scheduled_sync(scope="timesheet"), т.к. функция не публичная."""

    @override_settings(USE_PORTAL_SCOPING=False)
    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_selects_accounts_with_real_bitrix_statuses(self, mock_cfg_cls, mock_svc_cls):
        for i, status in enumerate(["S", "L", "F", "T", "D", "P"], start=1):
            _account(f"m{i}", master=True, b24_user_id=i, status=status)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {
            "sp_entity_type_id": 1, "fields_mapping": {"data": "createdTime"},
            "auto_sync_enabled": True,
        }
        mock_cfg_cls.return_value = mock_cfg
        mock_svc_cls.return_value.sync_all.return_value = 0

        run = run_scheduled_sync(scope="timesheet")

        self.assertEqual(run.portals_total, 6)

    @override_settings(USE_PORTAL_SCOPING=False)
    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_excludes_account_without_refresh_token(self, mock_cfg_cls, mock_svc_cls):
        _account("m1", master=True, refresh_token="")  # status дефолтный "active"
        mock_cfg_cls.return_value = MagicMock()

        run = run_scheduled_sync(scope="timesheet")

        self.assertEqual(run.portals_total, 0)


class MarkPortalAccountsStatusFilterTest(TestCase):
    """Тот же Дефект 1 (status vs refresh_token), третье и последнее место в

    этом файле: маркер last_timesheet_synced_at, который run_scheduled_sync
    проставляет ВСЕМ аккаунтам портала под USE_PORTAL_SCOPING=True (данные
    общие на портал, синкает один представитель, но индикатор «данные свежи
    на» должен обновиться у каждого аккаунта портала).

    Bitrix24Account.objects.filter(status="active", portal_id=...) — тот же
    фильтр, что не совпадал НИ С ОДНИМ реальным аккаунтом в
    select_portal_accounts()/_account_scoped_sync_accounts() (см.
    SelectPortalAccountsStatusFilterTest). Сейчас это латентно, потому что
    флаг USE_PORTAL_SCOPING выключен в проде — при флаге OFF работает другая
    ветка (else, без фильтра по status). Но при этом фильтре не обновляется
    даже сам представитель: в ветке if нет .save() на account, только
    bulk .update() выше и присваивание атрибута в памяти — если .update() не
    находит ни одной строки (статус не "active"), в БД не долетает ничей
    маркер, включая представителя, который реально сходил в Bitrix."""

    @override_settings(USE_PORTAL_SCOPING=True)
    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_marks_whole_portal_with_realistic_bitrix_status(self, mock_cfg_cls, mock_svc_cls):
        """status="S" (боевое значение, а не тестовый дефолт "active") —
        маркер обязан долететь и до представителя, и до второго аккаунта
        портала."""
        portal = Portal.objects.create(member_id="m1", domain_url="m1.bitrix24.ru", status="active")
        acc1 = _account("m1", master=True, b24_user_id=1, portal=portal, status="S")
        acc2 = _account("m1", master=False, b24_user_id=2, portal=portal, status="S")
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

        acc1.refresh_from_db()
        acc2.refresh_from_db()
        self.assertIsNotNone(
            acc1.last_timesheet_synced_at,
            "маркер не долетел даже до представителя (синкавшего аккаунта) — "
            "фильтр status=\"active\" не совпадает с боевым статусом 'S'",
        )
        self.assertIsNotNone(
            acc2.last_timesheet_synced_at,
            "маркер не долетел до второго аккаунта портала — "
            "фильтр status=\"active\" не совпадает с боевым статусом 'S'",
        )


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


class RunScheduledSyncUsersScopeTest(TestCase):
    """Тесты scope="users": синк пользователей без timesheet/project."""

    @patch("main.sync_scheduler_service.UserSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_users_scope_calls_user_sync_service(self, mock_cfg_cls, mock_user_cls):
        _account("m1", master=True)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg
        mock_user_svc = MagicMock()
        mock_user_svc.sync.return_value = {"synced": 42, "created": 10, "updated": 32}
        mock_user_cls.return_value = mock_user_svc

        run = run_scheduled_sync(scope="users")

        self.assertIsInstance(run, SyncRun)
        self.assertEqual(run.scope, "users")
        self.assertEqual(run.status, "success")
        self.assertEqual(run.portals_total, 1)
        self.assertEqual(run.portals_synced, 1)
        self.assertEqual(run.items_synced, 42)
        mock_user_svc.sync.assert_called_once()

    @patch("main.sync_scheduler_service.UserSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_users_scope_lock_uses_users_scope(self, mock_cfg_cls, mock_user_cls):
        _account("m1", master=True)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg
        mock_user_cls.return_value.sync.return_value = {"synced": 1, "created": 1, "updated": 0}

        with patch("main.sync_scheduler_service.account_sync_lock") as mock_lock:
            mock_lock.return_value.__enter__ = MagicMock(return_value=None)
            mock_lock.return_value.__exit__ = MagicMock(return_value=False)
            run_scheduled_sync(scope="users")

        mock_lock.assert_called_once()
        _, kwargs = mock_lock.call_args
        self.assertEqual(kwargs.get("scope"), "users")

    @patch("main.sync_scheduler_service.UserSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_users_scope_auto_sync_disabled_skips_portal(self, mock_cfg_cls, mock_user_cls):
        _account("m1", master=True)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": False}
        mock_cfg_cls.return_value = mock_cfg
        mock_user_cls.return_value = MagicMock()

        run = run_scheduled_sync(scope="users")
        self.assertEqual(run.portals_synced, 0)
        mock_user_cls.return_value.sync.assert_not_called()

    @patch("main.sync_scheduler_service.UserSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_users_scope_one_portal_failure_does_not_abort_run(self, mock_cfg_cls, mock_user_cls):
        _account("m1", master=True, b24_user_id=1)
        _account("m2", master=True, b24_user_id=3)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg
        mock_user_svc = MagicMock()
        mock_user_svc.sync.side_effect = [RuntimeError("users_boom"), {"synced": 7, "created": 2, "updated": 5}]
        mock_user_cls.return_value = mock_user_svc

        run = run_scheduled_sync(scope="users")
        self.assertEqual(run.portals_total, 2)
        self.assertEqual(run.portals_synced, 1)
        self.assertEqual(run.status, "partial")
        self.assertIn("users_boom", run.error_summary or "")

    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ProjectSyncService")
    @patch("main.sync_scheduler_service.UserSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_users_scope_does_not_call_other_services(self, mock_cfg_cls, mock_user_cls, mock_proj_cls, mock_ts_cls):
        _account("m1", master=True)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg
        mock_user_cls.return_value.sync.return_value = {"synced": 1, "created": 1, "updated": 0}

        run_scheduled_sync(scope="users")

        mock_proj_cls.assert_not_called()
        mock_ts_cls.assert_not_called()


class RunScheduledSyncTimesheetAccountSetTest(TestCase):
    """CRITICAL fixwave finding #1.

    scope="timesheet" раньше ВСЕГДА синкал один представитель на портал
    (select_portal_accounts()), но TimesheetItem скоуплен по-разному в
    зависимости от USE_PORTAL_SCOPING (см. tenant_scoping.scope_to_tenant):
    под флагом OFF (дефолт) — ПО АККАУНТУ. Значит представитель освежал только
    свои же строки, а отчёты остальных пользователей того же портала замирали
    навсегда (планировщик их никогда не трогал). scope="project" болеет ТЕМ ЖЕ
    (ProjectCard скоуплена через тот же tenant_scoping.scope_to_tenant) — см.
    RunScheduledSyncProjectAccountSetTest и ProjectBoardCrossAccountVisibilityTest
    ниже.
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


class RunScheduledSyncProjectAccountSetTest(TestCase):
    """ProjectCard-версия fixwave CRITICAL #1 (тот же класс бага, что у

    timesheet/users, см. RunScheduledSyncTimesheetAccountSetTest /
    RunScheduledSyncUsersAccountSetTest).

    ProjectSyncService пишет ProjectCard через tenant_scoping.scope_to_tenant —
    ТАК ЖЕ, как TimesheetItem и PortalUser. Множество аккаунтов для
    scope="project" поэтому должно совпадать с scope="timesheet"/"users"
    (_account_scoped_sync_accounts), а не всегда быть одним представителем
    (select_portal_accounts): под USE_PORTAL_SCOPING=False (боевой дефолт)
    представитель писал бы ProjectCard только под своим account FK, а
    остальные сотрудники портала (у каждого свой Bitrix24Account — заводится
    /api/getToken при первом открытии приложения) читают строго под своим FK
    и не расширяются на портал -> доска проектов пуста навсегда у всех, кроме
    представителя. См. также ProjectBoardCrossAccountVisibilityTest ниже —
    регресс через реальную точку чтения (get_project_card_queryset)."""

    @override_settings(USE_PORTAL_SCOPING=False)
    @patch("main.sync_scheduler_service.ProjectSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_project_flag_off_syncs_every_active_account(self, mock_cfg_cls, mock_proj_cls):
        """Флаг OFF: ProjectCard скоуплена по аккаунту -> синкать нужно ВСЕХ
        аккаунтов портала (а не одного представителя), иначе доска проектов
        пуста у всех, кроме представителя."""
        _account("m1", master=True, b24_user_id=1)
        _account("m1", master=False, b24_user_id=2)  # тот же портал (member_id)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg
        mock_proj = MagicMock()
        mock_proj.sync.return_value = {"synced": 1, "created": 1, "updated": 0}
        mock_proj_cls.return_value = mock_proj

        run = run_scheduled_sync(scope="project")

        self.assertEqual(run.portals_total, 2)
        self.assertEqual(run.portals_synced, 2)
        self.assertEqual(mock_proj_cls.call_count, 2)  # оба аккаунта реально синканы

    @override_settings(USE_PORTAL_SCOPING=True)
    @patch("main.sync_scheduler_service.ProjectSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_project_flag_on_syncs_one_representative(self, mock_cfg_cls, mock_proj_cls):
        """Флаг ON: ProjectCard общая на портал (write=True пишет portal+account,
        read по флагу читает по portal) -> одного представителя достаточно,
        как и раньше."""
        portal = Portal.objects.create(member_id="m1", domain_url="m1.bitrix24.ru", status="active")
        _account("m1", master=True, b24_user_id=1, portal=portal)
        _account("m1", master=False, b24_user_id=2, portal=portal)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg
        mock_proj = MagicMock()
        mock_proj.sync.return_value = {"synced": 1, "created": 1, "updated": 0}
        mock_proj_cls.return_value = mock_proj

        run = run_scheduled_sync(scope="project")

        self.assertEqual(run.portals_total, 1)
        self.assertEqual(mock_proj_cls.call_count, 1)


class ProjectBoardCrossAccountVisibilityTest(TestCase):
    """Регресс ЧТЕНИЯ: доска проектов (и отчёты) должны быть видны КАЖДОМУ

    сотруднику портала, а не только тому аккаунту, которого планировщик
    выбрал представителем для scope="project".

    Проверяется через реальные точки чтения: get_project_card_queryset —
    воронка, через которую читают ВСЕ потребители карточек
    (ProjectCardService.get_board_data/get_meta/get_card_data/
    get_homepage_snapshot, report_queries, stage_automation_service,
    project_budget_notifier, inn_backfill_service) — и
    build_filtered_timesheet_queryset, который использует список карточек для
    исключения архивных проектов из отчётов. Пустой ответ там — это HTTP 200
    с cards: [], то есть молча пустая доска, а не ошибка."""

    @override_settings(USE_PORTAL_SCOPING=False)
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_both_accounts_of_portal_see_cards_after_scheduled_sync(self, mock_cfg_cls):
        acc1 = _account("m1", master=True, b24_user_id=1)
        acc2 = _account("m1", master=False, b24_user_id=2)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg

        # Заглушка ProjectSyncService, повторяющая реальную запись карточки:
        # ProjectCard.objects.create(**scope_to_tenant(self.account, write=True), ...)
        # — то есть привязку строго к тому аккаунту, который ей передали.
        def fake_project_sync(client, account):
            service = MagicMock()

            def _sync(*args, **kwargs):
                ProjectCard.objects.create(
                    **scope_to_tenant(account, write=True),
                    project_id="777", project_name="Проект Альфа", stage="Новый",
                )
                return {"synced": 1, "created": 1, "updated": 0}

            service.sync.side_effect = _sync
            return service

        with patch("main.sync_scheduler_service.ProjectSyncService", side_effect=fake_project_sync):
            run_scheduled_sync(scope="project")

        for account in (acc1, acc2):
            names = list(get_project_card_queryset(account).values_list("project_name", flat=True))
            self.assertEqual(
                names, ["Проект Альфа"],
                f"аккаунт b24_user_id={account.b24_user_id} не видит карточек портала",
            )

    @override_settings(USE_PORTAL_SCOPING=False)
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_archived_projects_excluded_from_reports_for_every_account(self, mock_cfg_cls):
        """Симптом хуже пустой доски: НЕВЕРНЫЕ ЦИФРЫ в отчётах.

        build_filtered_timesheet_queryset строит список архивных проектов из
        get_project_card_queryset(account) (report_queries.py) и исключает их
        строки из отчёта. У аккаунта без карточек этот список пуст, .exclude()
        превращается в no-op — и часы архивных проектов молча попадают в отчёт.
        Двое сотрудников одного портала видят РАЗНЫЕ суммы по одному отчёту.

        Симптом активировался, когда timesheet стал синкаться по каждому
        аккаунту (fixwave CRITICAL #1): у всех аккаунтов появились строки
        TimesheetItem, но карточки для их фильтрации до этого фикса
        оставались только у представителя.
        """
        acc1 = _account("m1", master=True, b24_user_id=1)
        acc2 = _account("m1", master=False, b24_user_id=2)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg

        # Списание по архивному проекту есть у ОБОИХ аккаунтов: timesheet
        # синкается для каждого активного аккаунта (fixwave CRITICAL #1).
        for account in (acc1, acc2):
            TimesheetItem.objects.create(
                bitrix24_account=account, bitrix_id=account.b24_user_id, task_id="1",
                employee_id="1", hours=8.0, project_id="500",
                project_title="Архивный", date_reflection=timezone.now(),
            )

        def fake_project_sync(client, account):
            service = MagicMock()

            def _sync(*args, **kwargs):
                ProjectCard.objects.create(
                    **scope_to_tenant(account, write=True),
                    project_id="500", project_name="Архивный", stage="Успех",
                    is_archived=True,
                )
                return {"synced": 1, "created": 1, "updated": 0}

            service.sync.side_effect = _sync
            return service

        with patch("main.sync_scheduler_service.ProjectSyncService", side_effect=fake_project_sync):
            run_scheduled_sync(scope="project")

        for account in (acc1, acc2):
            rows = build_filtered_timesheet_queryset(account, {}).count()
            self.assertEqual(
                rows, 0,
                f"аккаунт b24_user_id={account.b24_user_id}: часы архивного проекта "
                f"протекли в отчёт ({rows} строк вместо 0)",
            )


class RunScheduledSyncUsersAccountSetTest(TestCase):
    """Дефект 2 финального ревью Фазы 2 (тот же класс бага, что fixwave

    CRITICAL #1 у timesheet, см. RunScheduledSyncTimesheetAccountSetTest).

    UserSyncService пишет PortalUser через tenant_scoping.scope_to_tenant —
    ТАК ЖЕ, как TimesheetItem. Значит множество аккаунтов для scope="users"
    должно совпадать с scope="timesheet" (_account_scoped_sync_accounts), а
    не всегда быть одним представителем (select_portal_accounts): под
    USE_PORTAL_SCOPING=False (боевой дефолт) представитель писал бы
    PortalUser только под своим account FK, а остальные сотрудники портала
    (у каждого свой Bitrix24Account — заводится /api/getToken при первом
    открытии приложения) читают строго под своим FK и не расширяются на
    портал -> справочник пуст навсегда у всех, кроме представителя.

    scope="project" болеет ТЕМ ЖЕ — см. RunScheduledSyncProjectAccountSetTest
    и ProjectBoardCrossAccountVisibilityTest выше."""

    @override_settings(USE_PORTAL_SCOPING=False)
    @patch("main.sync_scheduler_service.UserSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_flag_off_syncs_every_active_account(self, mock_cfg_cls, mock_user_cls):
        """Флаг OFF: PortalUser скоуплен по аккаунту -> синкать нужно ВСЕХ
        аккаунтов портала (а не одного представителя), иначе GET /api/users
        отдаёт пустой список всем, кроме представителя."""
        acc1 = _account("m1", master=True, b24_user_id=1)
        acc2 = _account("m1", master=False, b24_user_id=2)  # тот же портал (member_id)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg
        mock_user_svc = MagicMock()
        mock_user_svc.sync.return_value = {"synced": 1, "created": 1, "updated": 0}
        mock_user_cls.return_value = mock_user_svc

        run = run_scheduled_sync(scope="users")

        self.assertEqual(run.portals_total, 2)
        self.assertEqual(run.portals_synced, 2)
        self.assertEqual(mock_user_cls.call_count, 2)  # оба аккаунта реально синканы

    @override_settings(USE_PORTAL_SCOPING=True)
    @patch("main.sync_scheduler_service.UserSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_flag_on_syncs_one_representative(self, mock_cfg_cls, mock_user_cls):
        """Флаг ON: PortalUser общий на портал (write=True пишет portal+account,
        read по флагу читает по portal) -> одного представителя достаточно,
        как и раньше."""
        portal = Portal.objects.create(member_id="m1", domain_url="m1.bitrix24.ru", status="active")
        _account("m1", master=True, b24_user_id=1, portal=portal)
        _account("m1", master=False, b24_user_id=2, portal=portal)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg
        mock_user_svc = MagicMock()
        mock_user_svc.sync.return_value = {"synced": 1, "created": 1, "updated": 0}
        mock_user_cls.return_value = mock_user_svc

        run = run_scheduled_sync(scope="users")

        self.assertEqual(run.portals_total, 1)
        self.assertEqual(mock_user_cls.call_count, 1)
