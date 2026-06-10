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
        with patch("main.utils.decorators.sync_lock.account_sync_lock", side_effect=SyncLockBusy):
            response = Client().post(
                "/api/sync-timesheets",
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {token}",
            )
        self.assertEqual(response.status_code, 409)
        self.assertIn("error", response.json())
