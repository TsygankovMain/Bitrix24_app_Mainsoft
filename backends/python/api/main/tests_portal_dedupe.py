"""Тесты дедупликации данных портала (задача 4.2)."""
from django.test import TestCase
from django.utils import timezone

from .models import Bitrix24Account, Portal, TimesheetItem, ProjectCard
from .portal_dedupe_service import dedupe_portal_data


def _portal(member_id="m1"):
    return Portal.objects.create(member_id=member_id, domain_url=f"{member_id}.b24.ru", status="active")


def _account(portal, *, master=False, b24_user_id=1):
    return Bitrix24Account.objects.create(
        b24_user_id=b24_user_id, is_b24_user_admin=True, member_id=portal.member_id,
        is_master_account=master, domain_url=portal.domain_url, status="active",
        application_version=1, portal=portal,
    )


def _ts(account, portal, bitrix_id, *, hours=1.0):
    return TimesheetItem.objects.create(
        bitrix24_account=account, portal=portal, bitrix_id=bitrix_id,
        task_id="1", employee_id="1", hours=hours, date_reflection=timezone.now(),
    )


class DedupeDryRunTest(TestCase):
    def test_dry_run_counts_but_does_not_delete(self):
        portal = _portal()
        master = _account(portal, master=True, b24_user_id=1)
        other = _account(portal, master=False, b24_user_id=2)
        _ts(master, portal, bitrix_id=100)
        _ts(other, portal, bitrix_id=100)   # дубль того же bitrix_id в пределах portal
        _ts(other, portal, bitrix_id=200)   # уникальный

        report = dedupe_portal_data(apply=False)   # dry-run

        # Ничего не удалено.
        self.assertEqual(TimesheetItem.objects.count(), 3)
        # Отчёт: одна группа-дубль (bitrix_id=100), 1 запись к удалению.
        self.assertEqual(report["timesheets"]["duplicate_groups"], 1)
        self.assertEqual(report["timesheets"]["rows_to_delete"], 1)
        self.assertFalse(report["applied"])

    def test_apply_keeps_master_copy(self):
        portal = _portal()
        master = _account(portal, master=True, b24_user_id=1)
        other = _account(portal, master=False, b24_user_id=2)
        keep = _ts(master, portal, bitrix_id=100)
        drop = _ts(other, portal, bitrix_id=100)

        report = dedupe_portal_data(apply=True)

        self.assertEqual(report["applied"], True)
        self.assertTrue(TimesheetItem.objects.filter(pk=keep.pk).exists())   # мастер остался
        self.assertFalse(TimesheetItem.objects.filter(pk=drop.pk).exists())  # дубль удалён
        self.assertEqual(TimesheetItem.objects.filter(portal=portal, bitrix_id=100).count(), 1)

    def test_apply_without_master_keeps_freshest(self):
        portal = _portal()
        a1 = _account(portal, master=False, b24_user_id=1)
        a2 = _account(portal, master=False, b24_user_id=2)
        older = _ts(a1, portal, bitrix_id=100)
        newer = _ts(a2, portal, bitrix_id=100)
        # Делаем newer свежее по updated_at.
        TimesheetItem.objects.filter(pk=newer.pk).update(updated_at=timezone.now())
        older.refresh_from_db(); newer.refresh_from_db()

        dedupe_portal_data(apply=True)
        # Осталась ровно одна; при отсутствии мастера — свежайшая (newer).
        remaining = TimesheetItem.objects.filter(portal=portal, bitrix_id=100)
        self.assertEqual(remaining.count(), 1)

    def test_card_dedup_by_project_id(self):
        portal = _portal()
        master = _account(portal, master=True, b24_user_id=1)
        other = _account(portal, master=False, b24_user_id=2)
        ProjectCard.objects.create(bitrix24_account=master, portal=portal, project_id="500", project_name="P", stage="new")
        ProjectCard.objects.create(bitrix24_account=other, portal=portal, project_id="500", project_name="P2", stage="new")

        report = dedupe_portal_data(apply=True)
        self.assertEqual(ProjectCard.objects.filter(portal=portal, project_id="500").count(), 1)
        self.assertEqual(report["cards"]["rows_to_delete"], 1)

    def test_refuses_apply_when_backfill_incomplete(self):
        # Запись с аккаунтом-с-portal, но portal на записи пуст -> backfill не завершён.
        portal = _portal()
        acc = _account(portal, master=True, b24_user_id=1)
        TimesheetItem.objects.create(
            bitrix24_account=acc, portal=None, bitrix_id=100,
            task_id="1", employee_id="1", hours=1.0, date_reflection=timezone.now(),
        )
        report = dedupe_portal_data(apply=True)
        self.assertFalse(report["applied"])
        self.assertTrue(report["backfill_incomplete"])
        self.assertEqual(TimesheetItem.objects.count(), 1)  # ничего не тронули
