from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from django.test import Client, SimpleTestCase, TestCase
from django.utils import timezone

from .bitrix_data_access import BitrixDataService
from .models import Bitrix24Account, ProjectCard, TimesheetItem
from .report_queries import build_filtered_timesheet_queryset
from .report_services import (
    DataProcessingService,
    FIELD_EMPLOYEE,
    FIELD_PROJECT_NAME,
    FIELD_TASK_ID,
    FIELD_TITLE_HIERARCHY,
    ReportService,
)
from .services import (
    PROJECT_STAGE_ESTIMATE,
    PROJECT_STAGE_IN_WORK,
    PROJECT_STAGE_NO_WRITEOFF_30,
    PROJECT_STAGE_NO_WRITEOFF_90,
    ProjectStageAutomationService,
)
from .timesheet_sync_service import TimesheetSyncService


class ReportServiceTest(SimpleTestCase):
    def test_normalization_project_logic(self):
        processor = DataProcessingService()

        item1 = {
            FIELD_TASK_ID: "1",
            FIELD_PROJECT_NAME: "Project A",
            FIELD_TITLE_HIERARCHY: '["Root", "Sub"]',
        }
        norm1 = processor.normalize_items([item1])[0]
        self.assertEqual(norm1["project_name"], "Project A")

        item2 = {
            FIELD_TASK_ID: "2",
            FIELD_PROJECT_NAME: "",
            FIELD_TITLE_HIERARCHY: '["Project B", "Sub"]',
        }
        norm2 = processor.normalize_items([item2])[0]
        self.assertEqual(norm2["project_name"], "Project B")

        item3 = {
            FIELD_TASK_ID: "3",
            FIELD_PROJECT_NAME: None,
            FIELD_TITLE_HIERARCHY: "[]",
        }
        norm3 = processor.normalize_items([item3])[0]
        self.assertEqual(norm3["project_name"], "Не определён")

    def test_report_aggregation(self):
        reporter = ReportService()
        items = [
            {
                "sotrudnik_id": "user1",
                "project_name": "Project A",
                "kolichestvo_chasov": 5.0,
                "data": "2023-10-01T00:00:00+03:00",
            },
            {
                "sotrudnik_id": "user1",
                "project_name": "Project A",
                "kolichestvo_chasov": 3.0,
                "data": "2023-10-02T00:00:00+03:00",
            },
            {
                "sotrudnik_id": "user2",
                "project_name": "Project B",
                "kolichestvo_chasov": 2.0,
                "data": "2023-10-01T00:00:00+03:00",
            },
        ]

        emp_report = reporter.generate_employee_projects(items)
        self.assertEqual(len(emp_report), 2)
        user1 = next(user for user in emp_report if user["id"] == "user1")
        self.assertEqual(user1["total_hours"], 8.0)

        ts_report = reporter.generate_timesheet(items)
        ts_user1 = next(user for user in ts_report if user["employee_id"] == "user1")
        self.assertEqual(ts_user1["total"], 8.0)
        self.assertEqual(ts_user1["days"]["1"], 5.0)
        self.assertEqual(ts_user1["days"]["2"], 3.0)

    def test_normalization_skips_items_with_invalid_numeric_fields(self):
        processor = DataProcessingService()

        invalid_item = {
            FIELD_TASK_ID: "10",
            FIELD_PROJECT_NAME: "Broken Project",
            FIELD_TITLE_HIERARCHY: '["Broken Project", "Task"]',
            "kolichestvo_chasov": "3,5,1",
        }
        valid_item = {
            FIELD_TASK_ID: "11",
            FIELD_PROJECT_NAME: "Valid Project",
            FIELD_TITLE_HIERARCHY: '["Valid Project", "Task"]',
            "kolichestvo_chasov": "3,5",
        }

        normalized = processor.normalize_items([invalid_item, valid_item])

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["id_zadachi"], "11")
        self.assertEqual(normalized[0]["kolichestvo_chasov"], 3.5)

    def test_timesheet_sync_extracts_items_from_multiple_response_shapes(self):
        shaped_as_dict = {"result": {"items": [{"id": 1}]}}
        shaped_as_list = {"result": [{"id": 2}]}

        self.assertEqual(TimesheetSyncService._extract_items(shaped_as_dict), [{"id": 1}])
        self.assertEqual(TimesheetSyncService._extract_items(shaped_as_list), [{"id": 2}])

    def test_normalization_canonicalizes_bracketed_employee_ids(self):
        processor = DataProcessingService()

        normalized = processor.normalize_items(
            [
                {
                    FIELD_TASK_ID: "12",
                    FIELD_PROJECT_NAME: "Project A",
                    FIELD_TITLE_HIERARCHY: '["Project A", "Task"]',
                    FIELD_EMPLOYEE: "[1167]",
                }
            ]
        )

        self.assertEqual(normalized[0]["sotrudnik_id"], "1167")

    def test_daily_workload_resolves_names_for_legacy_employee_ids(self):
        reporter = ReportService()

        report = reporter.generate_daily_workload(
            [
                {
                    "sotrudnik_id": "[1167]",
                    "project_name": "Project A",
                    "kolichestvo_chasov": 6,
                    "id_zadachi": "10",
                    "nazvanie_zadachi": "Task",
                    "opisanie": "",
                    "data": "2026-04-02T00:00:00+03:00",
                }
            ],
            {"1167": "Иванов Иван"},
            "2026-04-01",
            "2026-04-30",
        )

        self.assertEqual(report["rows"][0]["employee"]["id"], "1167")
        self.assertEqual(report["rows"][0]["employee"]["name"], "Иванов Иван")


class BitrixDataServiceTest(SimpleTestCase):
    def test_fetch_users_resolves_numeric_and_bracketed_ids(self):
        client = Mock()
        client._bitrix_token.call_method.return_value = {
            "result": [{"ID": "1167", "LAST_NAME": "Иванов", "NAME": "Иван"}]
        }

        service = BitrixDataService(client, {})
        result = service.fetch_users(["1167", "[1167]", '["1167"]'])

        self.assertEqual(result["1167"], "Иванов Иван")
        self.assertEqual(result["[1167]"], "Иванов Иван")
        self.assertEqual(result['["1167"]'], "Иванов Иван")
        client._bitrix_token.call_method.assert_called_once_with(
            "user.get",
            {"FILTER": {"ID": ["1167"]}},
        )

    def test_fetch_active_users_keeps_users_without_employee_user_type(self):
        client = Mock()
        client._bitrix_token.call_method.return_value = {
            "result": [
                {"ID": "1167", "LAST_NAME": "Иванов", "NAME": "Иван"},
                {"ID": "1199", "EMAIL": "user1199@example.com", "USER_TYPE": "unknown"},
            ]
        }

        service = BitrixDataService(client, {})
        result = service.fetch_active_users()

        self.assertEqual(
            result,
            [
                {"id": "1199", "name": "user1199@example.com"},
                {"id": "1167", "name": "Иванов Иван"},
            ],
        )
        client._bitrix_token.call_method.assert_called_once_with(
            "user.get",
            {
                "FILTER": {"ACTIVE": "Y"},
                "sort": "LAST_NAME",
                "order": "ASC",
                "start": 0,
            },
        )

    def test_fetch_active_users_paginates_all_pages(self):
        client = Mock()
        client._bitrix_token.call_method.side_effect = [
            {
                "result": [{"ID": "1167", "LAST_NAME": "Иванов", "NAME": "Иван"}],
                "total": 2,
                "next": 1,
            },
            {
                "result": [{"ID": "1199", "LAST_NAME": "Петров", "NAME": "Петр"}],
                "total": 2,
            },
        ]

        service = BitrixDataService(client, {})
        result = service.fetch_active_users()

        self.assertEqual(
            result,
            [
                {"id": "1167", "name": "Иванов Иван"},
                {"id": "1199", "name": "Петров Петр"},
            ],
        )
        self.assertEqual(client._bitrix_token.call_method.call_count, 2)


class QueryStabilityTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1,
            is_b24_user_admin=True,
            member_id="member",
            is_master_account=True,
            domain_url="example.bitrix24.ru",
            status="active",
            application_version=1,
        )

    def test_timesheet_filters_use_date_range_and_exclude_archived_projects(self):
        ProjectCard.objects.create(
            bitrix24_account=self.account,
            project_id="archived-id",
            project_name="Archived By Id",
            stage=PROJECT_STAGE_IN_WORK,
            manual_stage=PROJECT_STAGE_IN_WORK,
            is_archived=True,
        )
        ProjectCard.objects.create(
            bitrix24_account=self.account,
            project_id="active-id",
            project_name="Active Project",
            stage=PROJECT_STAGE_IN_WORK,
            manual_stage=PROJECT_STAGE_IN_WORK,
            is_archived=False,
        )
        ProjectCard.objects.create(
            bitrix24_account=self.account,
            project_id="title-marker",
            project_name="Archived By Title",
            stage=PROJECT_STAGE_IN_WORK,
            manual_stage=PROJECT_STAGE_IN_WORK,
            is_archived=True,
        )

        jan_31_evening = timezone.make_aware(datetime(2026, 1, 31, 23, 30))
        jan_01_morning = timezone.make_aware(datetime(2026, 1, 1, 9, 0))
        feb_01 = timezone.make_aware(datetime(2026, 2, 1, 9, 0))

        TimesheetItem.objects.create(
            bitrix24_account=self.account,
            bitrix_id=1,
            task_id="1",
            employee_id="emp-1",
            hours=2,
            project_id="archived-id",
            project_title="Archived By Id",
            date_reflection=jan_01_morning,
        )
        TimesheetItem.objects.create(
            bitrix24_account=self.account,
            bitrix_id=2,
            task_id="2",
            employee_id="emp-1",
            hours=4,
            project_id="",
            project_title="Archived By Title",
            date_reflection=jan_01_morning,
        )
        kept_item = TimesheetItem.objects.create(
            bitrix24_account=self.account,
            bitrix_id=3,
            task_id="3",
            employee_id="emp-1",
            hours=6,
            project_id="active-id",
            project_title="Active Project",
            date_reflection=jan_31_evening,
        )
        TimesheetItem.objects.create(
            bitrix24_account=self.account,
            bitrix_id=4,
            task_id="4",
            employee_id="emp-2",
            hours=8,
            project_id="active-id",
            project_title="Active Project",
            date_reflection=jan_31_evening,
        )
        TimesheetItem.objects.create(
            bitrix24_account=self.account,
            bitrix_id=5,
            task_id="5",
            employee_id="emp-1",
            hours=1,
            project_id="active-id",
            project_title="Active Project",
            date_reflection=feb_01,
        )

        queryset = build_filtered_timesheet_queryset(
            self.account,
            {
                "date_from": "2026-01-01",
                "date_to": "2026-01-31",
                "employee_ids[]": ["emp-1"],
                "project_ids[]": ["active-id"],
                "employee_mode": "include",
                "project_mode": "include",
            },
        )

        self.assertEqual(list(queryset.values_list("bitrix_id", flat=True)), [kept_item.bitrix_id])

    def test_employee_filter_matches_legacy_bracketed_ids(self):
        day = timezone.make_aware(datetime(2026, 4, 2, 9, 0))
        legacy_item = TimesheetItem.objects.create(
            bitrix24_account=self.account,
            bitrix_id=101,
            task_id="101",
            employee_id="[1167]",
            hours=4,
            project_id="active-id",
            project_title="Active Project",
            date_reflection=day,
        )
        TimesheetItem.objects.create(
            bitrix24_account=self.account,
            bitrix_id=102,
            task_id="102",
            employee_id="1199",
            hours=4,
            project_id="active-id",
            project_title="Active Project",
            date_reflection=day,
        )

        queryset = build_filtered_timesheet_queryset(
            self.account,
            {
                "date_from": "2026-04-01",
                "date_to": "2026-04-30",
                "employee_ids[]": ["1167"],
                "employee_mode": "include",
            },
        )

        self.assertEqual(list(queryset.values_list("bitrix_id", flat=True)), [legacy_item.bitrix_id])

    @patch("main.views.TimesheetSyncService.sync_all", side_effect=RuntimeError("sync failed"))
    @patch("main.views.ConfigurationService.get_configuration_sync", return_value={"sp_entity_type_id": 1, "fields_mapping": {}})
    def test_sync_endpoint_returns_warning_instead_of_500(self, _config_mock, _sync_mock):
        token = self.account.create_jwt_token()
        response = Client().post(
            "/api/sync-timesheets",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "warning")
        self.assertEqual(payload["count"], 0)
        self.assertIn("warning", payload)


class StageAutomationStabilityTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=2,
            is_b24_user_admin=True,
            member_id="member-2",
            is_master_account=True,
            domain_url="stage.bitrix24.ru",
            status="active",
            application_version=1,
        )

    def test_stage_automation_moves_and_restores_cards(self):
        now = timezone.now()
        TimesheetItem.objects.create(
            bitrix24_account=self.account,
            bitrix_id=301,
            task_id="301",
            employee_id="emp-stage",
            hours=2,
            project_id="p-30",
            project_title="Needs 30",
            date_reflection=now - timedelta(days=35),
        )
        TimesheetItem.objects.create(
            bitrix24_account=self.account,
            bitrix_id=302,
            task_id="302",
            employee_id="emp-stage",
            hours=2,
            project_id="p-90",
            project_title="Needs 90",
            date_reflection=now - timedelta(days=95),
        )
        TimesheetItem.objects.create(
            bitrix24_account=self.account,
            bitrix_id=303,
            task_id="303",
            employee_id="emp-stage",
            hours=2,
            project_id="p-restore",
            project_title="Restore",
            date_reflection=now - timedelta(days=5),
        )

        move_30 = ProjectCard.objects.create(
            bitrix24_account=self.account,
            project_id="p-30",
            project_name="Needs 30",
            stage=PROJECT_STAGE_IN_WORK,
            manual_stage=PROJECT_STAGE_IN_WORK,
            last_writeoff_at=now - timedelta(days=35),
            last_writeoff_days=35,
        )
        move_90 = ProjectCard.objects.create(
            bitrix24_account=self.account,
            project_id="p-90",
            project_name="Needs 90",
            stage=PROJECT_STAGE_IN_WORK,
            manual_stage=PROJECT_STAGE_IN_WORK,
            last_writeoff_at=now - timedelta(days=95),
            last_writeoff_days=95,
        )
        restore_manual = ProjectCard.objects.create(
            bitrix24_account=self.account,
            project_id="p-restore",
            project_name="Restore",
            stage=PROJECT_STAGE_NO_WRITEOFF_30,
            manual_stage=PROJECT_STAGE_ESTIMATE,
            last_writeoff_at=now - timedelta(days=5),
            last_writeoff_days=5,
        )

        result = ProjectStageAutomationService(self.account).run_daily_check()

        move_30.refresh_from_db()
        move_90.refresh_from_db()
        restore_manual.refresh_from_db()

        self.assertEqual(result["moved_to_30_days"], 1)
        self.assertEqual(result["moved_to_90_days"], 1)
        self.assertEqual(result["returned_to_work"], 1)
        self.assertEqual(move_30.stage, PROJECT_STAGE_NO_WRITEOFF_30)
        self.assertEqual(move_90.stage, PROJECT_STAGE_NO_WRITEOFF_90)
        self.assertEqual(restore_manual.stage, PROJECT_STAGE_ESTIMATE)
