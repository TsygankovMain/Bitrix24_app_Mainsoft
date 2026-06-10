"""Тесты backfill связей portal (задача 4.1)."""
from django.test import TestCase
from django.utils import timezone

from .models import Bitrix24Account, Portal, TimesheetItem, ProjectCard
from .portal_backfill_service import backfill_portal_links


def _account_with_portal(member_id, *, b24_user_id=1):
    portal = Portal.objects.create(member_id=member_id, domain_url=f"{member_id}.b24.ru", status="active")
    acc = Bitrix24Account.objects.create(
        b24_user_id=b24_user_id, is_b24_user_admin=True, member_id=member_id,
        is_master_account=True, domain_url=f"{member_id}.b24.ru", status="active",
        application_version=1, portal=portal,
    )
    return acc, portal


class BackfillPortalLinksTest(TestCase):
    def test_backfills_timesheet_and_card_portal_from_account(self):
        acc, portal = _account_with_portal("m1")
        ts = TimesheetItem.objects.create(
            bitrix24_account=acc, bitrix_id=1, task_id="1", employee_id="1",
            hours=1.0, date_reflection=timezone.now(),
        )
        card = ProjectCard.objects.create(
            bitrix24_account=acc, project_id="100", project_name="P", stage="new",
        )
        self.assertIsNone(ts.portal_id)
        self.assertIsNone(card.portal_id)

        report = backfill_portal_links(batch_size=10)

        ts.refresh_from_db(); card.refresh_from_db()
        self.assertEqual(ts.portal_id, portal.id)
        self.assertEqual(card.portal_id, portal.id)
        self.assertEqual(report["timesheets_linked"], 1)
        self.assertEqual(report["cards_linked"], 1)
        self.assertEqual(report["timesheets_unlinked"], 0)

    def test_idempotent_second_run_changes_nothing(self):
        acc, portal = _account_with_portal("m1")
        TimesheetItem.objects.create(
            bitrix24_account=acc, bitrix_id=1, task_id="1", employee_id="1",
            hours=1.0, date_reflection=timezone.now(),
        )
        backfill_portal_links(batch_size=10)
        report2 = backfill_portal_links(batch_size=10)
        self.assertEqual(report2["timesheets_linked"], 0)
        self.assertEqual(report2["cards_linked"], 0)

    def test_account_without_portal_leaves_items_unlinked(self):
        # Аккаунт без portal (например без member_id в seed) -> items не привязываются.
        acc = Bitrix24Account.objects.create(
            b24_user_id=9, is_b24_user_admin=True, member_id="", is_master_account=True,
            domain_url="x.b24.ru", status="active", application_version=1, portal=None,
        )
        TimesheetItem.objects.create(
            bitrix24_account=acc, bitrix_id=1, task_id="1", employee_id="1",
            hours=1.0, date_reflection=timezone.now(),
        )
        report = backfill_portal_links(batch_size=10)
        self.assertEqual(report["timesheets_linked"], 0)
        self.assertEqual(report["timesheets_unlinked"], 1)
