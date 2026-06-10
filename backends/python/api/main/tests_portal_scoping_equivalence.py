"""Эквивалентность отчётов при account- и portal-скоупинге (задача 4.4).

Доказывает: на данных, приведённых к виду «один Portal, backfill сделан,
дублей нет», отчёт даёт ОДИНАКОВЫЙ результат при USE_PORTAL_SCOPING=False и True.
И демонстрирует, что при двух аккаунтах одной компании portal-скоупинг устраняет
расхождение отчётов (текущая болезнь).
"""
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Bitrix24Account, Portal, TimesheetItem, ProjectCard
from .report_queries import build_filtered_timesheet_queryset
from .project_board_shared import get_project_card_queryset


def _portal(member_id="m1"):
    return Portal.objects.create(member_id=member_id, domain_url=f"{member_id}.b24.ru", status="active")


def _account(portal, *, master=False, b24_user_id=1):
    return Bitrix24Account.objects.create(
        b24_user_id=b24_user_id, is_b24_user_admin=True, member_id=portal.member_id,
        is_master_account=master, domain_url=portal.domain_url, status="active",
        application_version=1, portal=portal,
    )


def _ts(account, portal, bitrix_id, *, project_id="100", hours=1.0):
    return TimesheetItem.objects.create(
        bitrix24_account=account, portal=portal, bitrix_id=bitrix_id,
        task_id="1", employee_id="1", hours=hours, project_id=project_id,
        project_title="Проект", date_reflection=timezone.now(),
    )


class ReportEquivalenceTest(TestCase):
    def _ids(self, queryset):
        return sorted(str(pk) for pk in queryset.values_list("pk", flat=True))

    def test_single_account_report_identical_on_and_off(self):
        portal = _portal()
        acc = _account(portal, master=True, b24_user_id=1)
        _ts(acc, portal, 100)
        _ts(acc, portal, 200)
        params = {}

        with override_settings(USE_PORTAL_SCOPING=False):
            off_ids = self._ids(build_filtered_timesheet_queryset(acc, params))
        with override_settings(USE_PORTAL_SCOPING=True):
            on_ids = self._ids(build_filtered_timesheet_queryset(acc, params))

        self.assertEqual(off_ids, on_ids)   # эквивалентность
        self.assertEqual(len(on_ids), 2)

    def test_project_cards_identical_on_and_off(self):
        portal = _portal()
        acc = _account(portal, master=True, b24_user_id=1)
        ProjectCard.objects.create(bitrix24_account=acc, portal=portal, project_id="100", project_name="P", stage="new")
        ProjectCard.objects.create(bitrix24_account=acc, portal=portal, project_id="200", project_name="Q", stage="new")

        with override_settings(USE_PORTAL_SCOPING=False):
            off_ids = self._ids(get_project_card_queryset(acc))
        with override_settings(USE_PORTAL_SCOPING=True):
            on_ids = self._ids(get_project_card_queryset(acc))
        self.assertEqual(off_ids, on_ids)

    def test_two_accounts_portal_scoping_unifies_view(self):
        # После дедупа: данные компании привязаны к ОДНОМУ аккаунту, но к общему portal.
        portal = _portal()
        master = _account(portal, master=True, b24_user_id=1)
        other = _account(portal, master=False, b24_user_id=2)
        # Одна копия на компанию (после дедупа), принадлежит мастеру.
        _ts(master, portal, 100)
        _ts(master, portal, 200)
        params = {}

        # OFF: мастер видит 2, other видит 0 -> РАСХОЖДЕНИЕ (текущая болезнь).
        with override_settings(USE_PORTAL_SCOPING=False):
            master_off = self._ids(build_filtered_timesheet_queryset(master, params))
            other_off = self._ids(build_filtered_timesheet_queryset(other, params))
        self.assertEqual(len(master_off), 2)
        self.assertEqual(len(other_off), 0)
        self.assertNotEqual(master_off, other_off)

        # ON: оба видят ОДНО И ТО ЖЕ (portal) -> расхождение устранено.
        with override_settings(USE_PORTAL_SCOPING=True):
            master_on = self._ids(build_filtered_timesheet_queryset(master, params))
            other_on = self._ids(build_filtered_timesheet_queryset(other, params))
        self.assertEqual(master_on, other_on)
        self.assertEqual(len(master_on), 2)

    def test_fallback_when_portal_empty_matches_off(self):
        # Аккаунт без portal (backfill не добил): ON ведёт себя как OFF (фолбэк).
        portal = _portal()
        acc_no_portal = Bitrix24Account.objects.create(
            b24_user_id=9, is_b24_user_admin=True, member_id="m1", is_master_account=False,
            domain_url="m1.b24.ru", status="active", application_version=1, portal=None,
        )
        # Запись привязана к аккаунту без portal (portal=None).
        TimesheetItem.objects.create(
            bitrix24_account=acc_no_portal, portal=None, bitrix_id=300,
            task_id="1", employee_id="1", hours=1.0, date_reflection=timezone.now(),
        )
        params = {}
        with override_settings(USE_PORTAL_SCOPING=False):
            off_ids = self._ids(build_filtered_timesheet_queryset(acc_no_portal, params))
        with override_settings(USE_PORTAL_SCOPING=True):
            on_ids = self._ids(build_filtered_timesheet_queryset(acc_no_portal, params))
        self.assertEqual(off_ids, on_ids)   # фолбэк: portal пуст -> account-скоупинг
        self.assertEqual(len(on_ids), 1)
