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
