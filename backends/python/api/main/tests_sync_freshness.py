from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from .models import Bitrix24Account


class LastSyncedFieldTest(TestCase):
    def test_field_defaults_to_none_and_persists(self):
        acc = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m1",
            is_master_account=True, domain_url="ex.bitrix24.ru",
            status="active", application_version=1,
        )
        self.assertIsNone(acc.last_timesheet_synced_at)
        now = timezone.now()
        acc.last_timesheet_synced_at = now
        acc.save(update_fields=["last_timesheet_synced_at"])
        acc.refresh_from_db()
        self.assertEqual(acc.last_timesheet_synced_at, now)


class TimesheetSyncGateHelperTest(TestCase):
    """should_skip_timesheet_sync(account, now, gate_minutes) — чистый хелпер гейта
    свежести (Задача 2, Step 3). Вьюха напрямую не тестируется — она обёрнута
    декораторами (auth_required/sync_lock/...), интеграция покрыта регрессом
    (tests_sync_freshness + tests_sync_threshold + tests_sync_lock)."""

    def _acc(self, last=None):
        return Bitrix24Account.objects.create(
            b24_user_id=2, is_b24_user_admin=True, member_id="m2",
            is_master_account=True, domain_url="ex2.bitrix24.ru",
            status="active", application_version=1,
            last_timesheet_synced_at=last,
        )

    def test_helper_skips_when_fresh(self):
        from .views import should_skip_timesheet_sync
        acc = self._acc(last=timezone.now() - timedelta(minutes=1))
        self.assertTrue(should_skip_timesheet_sync(acc, timezone.now()))

    def test_helper_syncs_when_stale(self):
        from .views import should_skip_timesheet_sync
        acc = self._acc(last=timezone.now() - timedelta(minutes=10))
        self.assertFalse(should_skip_timesheet_sync(acc, timezone.now()))

    def test_helper_syncs_when_never(self):
        from .views import should_skip_timesheet_sync
        acc = self._acc(last=None)
        self.assertFalse(should_skip_timesheet_sync(acc, timezone.now()))
