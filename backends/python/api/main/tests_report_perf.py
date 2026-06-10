from datetime import datetime

from django.test import TestCase
from django.utils import timezone

from .models import Bitrix24Account, ProjectCard, TimesheetItem
from .project_board_shared import PROJECT_STAGE_IN_WORK
from .report_queries import build_filtered_timesheet_queryset, build_project_title_lookups


class ReportPerfEquivalenceTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-2-5", is_master_account=True,
            domain_url="example.bitrix24.ru", status="active", application_version=1,
        )

    def test_archived_exclusion_unchanged(self):
        ProjectCard.objects.create(
            bitrix24_account=self.account, project_id="arch-id", project_item_id="arch-item",
            project_name="Архив", stage=PROJECT_STAGE_IN_WORK, manual_stage=PROJECT_STAGE_IN_WORK,
            is_archived=True,
        )
        ProjectCard.objects.create(
            bitrix24_account=self.account, project_id="live-id", project_item_id="live-item",
            project_name="Живой", stage=PROJECT_STAGE_IN_WORK, manual_stage=PROJECT_STAGE_IN_WORK,
            is_archived=False,
        )
        day = timezone.make_aware(datetime(2026, 3, 1, 9, 0))
        TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=1, task_id="1", employee_id="e1", hours=2,
            project_id="arch-id", project_item_id="arch-item", project_title="Архив", date_reflection=day,
        )
        keep = TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=2, task_id="2", employee_id="e1", hours=3,
            project_id="live-id", project_item_id="live-item", project_title="Живой", date_reflection=day,
        )
        qs = build_filtered_timesheet_queryset(self.account, {})
        self.assertEqual(list(qs.values_list("bitrix_id", flat=True)), [keep.bitrix_id])

    def test_title_lookups_unchanged(self):
        ProjectCard.objects.create(
            bitrix24_account=self.account, project_id="g1", project_item_id="i1",
            project_name="Проект-1", stage=PROJECT_STAGE_IN_WORK, manual_stage=PROJECT_STAGE_IN_WORK,
            is_archived=False,
        )
        by_item, by_group = build_project_title_lookups(self.account)
        self.assertEqual(by_item.get("i1"), "Проект-1")
        self.assertEqual(by_group.get("g1"), "Проект-1")
