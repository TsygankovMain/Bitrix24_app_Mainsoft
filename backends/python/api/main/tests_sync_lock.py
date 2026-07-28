import uuid

from unittest.mock import MagicMock, patch

from django.test import TestCase, Client

from .models import Bitrix24Account
from .utils.decorators.sync_lock import account_sync_lock, SyncLockBusy, _advisory_key

# pg_try_advisory_lock(key bigint) — диапазон signed int64.
BIGINT_MIN = -(2 ** 63)
BIGINT_MAX = 2 ** 63 - 1


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

    def test_users_scope_produces_distinct_key(self):
        k_ts = _advisory_key(account_pk=10, scope="timesheet")
        k_pr = _advisory_key(account_pk=10, scope="project")
        k_us = _advisory_key(account_pk=10, scope="users")
        self.assertNotEqual(k_us, k_ts)
        self.assertNotEqual(k_us, k_pr)

    def test_project_create_scope_produces_distinct_key(self):
        """scope="project_create" — кнопка «Создать проект»
        (main.project_creation_service), намеренно отдельный от
        scope="project" (фоновая ProjectSyncService.sync()); см. докстринг
        модуля. sqlite в тестовом окружении не доходит до _advisory_key при
        реальном вызове account_sync_lock (no-op раньше), поэтому ключ
        отдельно проверяем здесь напрямую."""
        k_pr = _advisory_key(account_pk=10, scope="project")
        k_pc = _advisory_key(account_pk=10, scope="project_create")
        k_ts = _advisory_key(account_pk=10, scope="timesheet")
        k_us = _advisory_key(account_pk=10, scope="users")
        self.assertNotEqual(k_pc, k_pr)
        self.assertNotEqual(k_pc, k_ts)
        self.assertNotEqual(k_pc, k_us)


class AdvisoryKeyBigintRangeTest(TestCase):
    """PK аккаунта — UUID (128 бит). Наивный int(pk) << 4 переполняет bigint:
    PostgreSQL отвергает вызов pg_try_advisory_lock => 500 на каждом синке
    (инцидент прод-деплоя спринта 2 от 2026-06-10). Ключ обязан помещаться
    в signed int64 для ЛЮБОГО UUID."""

    def test_key_from_uuid_pk_fits_signed_bigint(self):
        for scope in ("timesheet", "project"):
            for _ in range(50):
                key = _advisory_key(account_pk=uuid.uuid4(), scope=scope)
                self.assertGreaterEqual(key, BIGINT_MIN)
                self.assertLessEqual(key, BIGINT_MAX)

    def test_key_from_int_pk_fits_signed_bigint(self):
        key = _advisory_key(account_pk=10, scope="timesheet")
        self.assertGreaterEqual(key, BIGINT_MIN)
        self.assertLessEqual(key, BIGINT_MAX)

    def test_key_is_deterministic_across_calls(self):
        # Два gunicorn-воркера и cron-команда должны получать одинаковый ключ
        # для одного аккаунта (иначе advisory-замок не замок).
        pk = uuid.UUID("12345678-1234-5678-1234-567812345678")
        self.assertEqual(
            _advisory_key(account_pk=pk, scope="timesheet"),
            _advisory_key(account_pk=pk, scope="timesheet"),
        )

    def test_uuid_scopes_and_accounts_produce_distinct_keys(self):
        pk1, pk2 = uuid.uuid4(), uuid.uuid4()
        self.assertNotEqual(
            _advisory_key(account_pk=pk1, scope="timesheet"),
            _advisory_key(account_pk=pk1, scope="project"),
        )
        self.assertNotEqual(
            _advisory_key(account_pk=pk1, scope="timesheet"),
            _advisory_key(account_pk=pk2, scope="timesheet"),
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
