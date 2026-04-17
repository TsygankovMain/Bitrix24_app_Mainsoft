from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.db import ProgrammingError
from django.http import JsonResponse
from django.test import Client, RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone

from .bitrix_data_access import BitrixDataService
from .middleware import ApiTrailingSlashNormalizeMiddleware, RequestLoggingMiddleware
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
from .project_board_shared import PROJECT_CARD_SCHEMA_CACHE_KEY, ensure_project_card_schema
from .services import (
    PROJECT_STAGE_ESTIMATE,
    PROJECT_STAGE_IN_WORK,
    PROJECT_STAGE_NO_WRITEOFF_30,
    PROJECT_STAGE_NO_WRITEOFF_90,
    ProjectCardService,
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


class RequestLoggingMiddlewareTest(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = RequestLoggingMiddleware(lambda request: JsonResponse({"ok": True}))

    @patch("main.middleware.RequestLog.objects.create")
    def test_healthz_request_is_not_written_to_db(self, create_mock):
        request = self.factory.get("/healthz")
        self.middleware.process_request(request)
        response = JsonResponse({"status": "ok"})

        self.middleware.process_response(request, response)

        create_mock.assert_not_called()

    @patch("main.middleware.RequestLog.objects.create")
    def test_successful_get_request_is_not_written_to_db(self, create_mock):
        request = self.factory.get("/api/report-daily-workload")
        self.middleware.process_request(request)
        response = JsonResponse({"rows": []})

        self.middleware.process_response(request, response)

        create_mock.assert_not_called()

    @patch("main.middleware.RequestLog.objects.create")
    def test_error_response_is_still_logged(self, create_mock):
        request = self.factory.get("/api/report-daily-workload")
        self.middleware.process_request(request)
        response = JsonResponse({"error": "boom"}, status=500)

        self.middleware.process_response(request, response)

        create_mock.assert_called_once()


class ApiTrailingSlashNormalizeMiddlewareTest(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = ApiTrailingSlashNormalizeMiddleware(lambda request: JsonResponse({"ok": True}))

    def test_normalizes_api_path_with_trailing_slash(self):
        request = self.factory.get("/api/configuration/")
        self.middleware.process_request(request)
        self.assertEqual(request.path_info, "/api/configuration")

    def test_keeps_non_api_path_intact(self):
        request = self.factory.get("/settings/")
        original_path = request.path_info
        self.middleware.process_request(request)
        self.assertEqual(request.path_info, original_path)


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

    def test_api_configuration_trailing_slash_does_not_fallback_to_spa_html(self):
        response = Client().get("/api/configuration/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("application/json", response["Content-Type"])
        self.assertIn("error", response.json())

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

    def test_timesheet_sync_save_batch_updates_and_creates_records(self):
        existing = TimesheetItem.objects.create(
            bitrix24_account=self.account,
            bitrix_id=401,
            task_id="401",
            employee_id="emp-old",
            hours=1,
            project_id="project-old",
            project_title="Old Project",
            date_reflection=timezone.make_aware(datetime(2026, 4, 1, 9, 0)),
        )
        service = TimesheetSyncService(Mock(), self.account, {"fields_mapping": {}})

        service._save_batch(
            [
                {
                    "id_elem": "401",
                    "id_zadachi": "401",
                    "sotrudnik_id": "emp-new",
                    "kolichestvo_chasov": 7.5,
                    "uchitivaem": True,
                    "ne_uchitivaemie_chasi": 0.0,
                    "opisanie": "updated",
                    "project_name": "New Project",
                    "project_id": "project-new",
                    "id_zadach_ierarhiya": ["1"],
                    "title_zadach_ierarhiya": ["Task"],
                    "data": timezone.make_aware(datetime(2026, 4, 2, 9, 0)),
                    "source_created_at": timezone.make_aware(datetime(2026, 4, 2, 10, 0)),
                },
                {
                    "id_elem": "402",
                    "id_zadachi": "402",
                    "sotrudnik_id": "emp-created",
                    "kolichestvo_chasov": 3.0,
                    "uchitivaem": False,
                    "ne_uchitivaemie_chasi": 3.0,
                    "opisanie": "created",
                    "project_name": "Created Project",
                    "project_id": "project-created",
                    "id_zadach_ierarhiya": [],
                    "title_zadach_ierarhiya": [],
                    "data": timezone.make_aware(datetime(2026, 4, 3, 9, 0)),
                    "source_created_at": None,
                },
            ]
        )

        existing.refresh_from_db()
        created = TimesheetItem.objects.get(bitrix24_account=self.account, bitrix_id=402)

        self.assertEqual(existing.employee_id, "emp-new")
        self.assertEqual(existing.project_title, "New Project")
        self.assertEqual(existing.hours, 7.5)
        self.assertEqual(created.employee_id, "emp-created")
        self.assertEqual(created.project_id, "project-created")

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

    @patch("main.views.ProjectSyncService.sync", side_effect=RuntimeError("project sync failed"))
    def test_project_board_sync_endpoint_returns_warning_instead_of_500(self, _sync_mock):
        token = self.account.create_jwt_token()
        response = Client().post(
            "/api/project-board/sync",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "warning")
        self.assertEqual(payload["synced"], 0)
        self.assertEqual(payload["created"], 0)
        self.assertEqual(payload["updated"], 0)
        self.assertIn("warning", payload)

    @patch("main.views.ProjectSyncService.backfill_timesheet_project_items", return_value={"status": "success", "updated": 0, "unresolved": 0})
    @patch("main.views.ProjectSyncService.sync", side_effect=RuntimeError("sync failed"))
    @patch("main.views.ConfigurationService.save_configuration_sync", return_value=None)
    @patch("main.views.ConfigurationService.normalize_configuration_sync", side_effect=lambda cfg: cfg)
    @patch("main.views._build_project_spa_validation_payload", return_value={"is_valid": True})
    def test_save_configuration_returns_success_when_project_sync_fails(
        self,
        _validation_mock,
        _normalize_mock,
        _save_mock,
        _sync_mock,
        _backfill_mock,
    ):
        token = self.account.create_jwt_token()
        response = Client().post(
            "/api/configuration/save",
            data={
                "config": {
                    "sp_entity_type_id": 0,
                    "fields_mapping": {},
                    "project_sp_entity_type_id": 1164,
                    "project_fields_mapping": {"bitrix_group_id": "UF_CRM_1"},
                    "is_configured": True,
                }
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload.get("status"), "success")
        self.assertIn("warning", payload)
        self.assertIn("project_sync", payload)

    @patch("main.views.ProjectSyncService.backfill_timesheet_project_items", return_value={"status": "success", "updated": 0, "unresolved": 0})
    @patch("main.views.ProjectSyncService.sync", return_value={"status": "success", "synced": 0, "created": 0, "updated": 0})
    @patch("main.views.ConfigurationService.save_configuration_sync", return_value=None)
    @patch("main.views.ConfigurationService.normalize_configuration_sync", side_effect=lambda cfg: cfg)
    @patch("main.views._build_project_spa_validation_payload", side_effect=RuntimeError("validation unavailable"))
    def test_save_configuration_returns_success_when_validation_fails_temporarily(
        self,
        _validation_mock,
        _normalize_mock,
        _save_mock,
        _sync_mock,
        _backfill_mock,
    ):
        token = self.account.create_jwt_token()
        response = Client().post(
            "/api/configuration/save",
            data={
                "config": {
                    "sp_entity_type_id": 0,
                    "fields_mapping": {},
                    "project_sp_entity_type_id": 1164,
                    "project_fields_mapping": {"bitrix_group_id": "UF_CRM_1"},
                    "is_configured": True,
                }
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload.get("status"), "success")
        self.assertIn("warning", payload)


class ProjectBoardEndpointStabilityTest(TestCase):
    def setUp(self):
        cache.clear()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11,
            is_b24_user_admin=True,
            member_id="member-board",
            is_master_account=True,
            domain_url="board.bitrix24.ru",
            status="active",
            application_version=1,
        )
        self.token = self.account.create_jwt_token()

        ProjectCard.objects.create(
            bitrix24_account=self.account,
            project_id="p-healthy",
            project_name="Healthy Project",
            stage=PROJECT_STAGE_IN_WORK,
            manual_stage=PROJECT_STAGE_IN_WORK,
            is_archived=False,
        )

    @patch("main.project_board_service.ProjectCardService.refresh_writeoff_stats", side_effect=RuntimeError("writeoff failed"))
    def test_project_board_returns_200_when_writeoff_refresh_fails(self, _refresh_mock):
        response = Client().get(
            "/api/project-board",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("summary", payload)
        self.assertTrue(payload.get("warning"))

    @patch("main.project_board_service.ProjectCardService.serialize_card", autospec=True)
    def test_project_board_skips_broken_cards_and_returns_partial_payload(self, serialize_mock):
        ProjectCard.objects.create(
            bitrix24_account=self.account,
            project_id="p-broken",
            project_name="Broken Project",
            stage=PROJECT_STAGE_IN_WORK,
            manual_stage=PROJECT_STAGE_IN_WORK,
            is_archived=False,
        )

        def serialize_side_effect(service, card):
            if card.project_id == "p-broken":
                raise RuntimeError("broken card")
            return {
                "id": str(card.id),
                "project_item_id": card.project_item_id,
                "project_id": card.project_id,
                "project_name": card.project_name,
                "stage": card.stage,
                "manual_stage": card.manual_stage,
                "is_archived": card.is_archived,
                "archived_at": None,
                "project_hours_budget": card.project_hours_budget,
                "hourly_rate": card.hourly_rate,
                "is_support": card.is_support,
                "curator_user_id": card.curator_user_id,
                "curator_name": card.curator_name,
                "project_start_date": None,
                "project_end_date": None,
                "company_id": card.company_id,
                "company_name": card.company_name,
                "company_inn": None,
                "our_legal_entity_id": card.our_legal_entity_id,
                "our_legal_entity_name": card.our_legal_entity_name,
                "our_legal_entity_inn": None,
                "last_writeoff_at": None,
                "last_writeoff_days": 0,
                "stage_source": card.stage_source,
                "created_at": card.created_at.isoformat() if card.created_at else None,
                "updated_at": card.updated_at.isoformat() if card.updated_at else None,
            }

        serialize_mock.side_effect = serialize_side_effect

        response = Client().get(
            "/api/project-board",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload.get("cards", [])), 1)
        self.assertTrue(payload.get("warning"))

    @patch("main.project_board_service.ProjectCardService.get_fallback_board_data", side_effect=RuntimeError("fallback failed"))
    @patch("main.project_board_service.ensure_project_card_schema", return_value=False)
    def test_project_board_returns_minimal_payload_when_fallback_fails(self, _schema_mock, _fallback_mock):
        response = Client().get(
            "/api/project-board",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload.get("cards"), [])
        self.assertEqual(payload.get("summary", {}).get("total_count"), 0)
        self.assertTrue(payload.get("warning"))

    @patch("main.project_board_shared.connection.introspection.get_table_description")
    @patch("main.project_board_shared.connection.introspection.table_names")
    def test_ensure_project_card_schema_returns_false_when_project_item_columns_missing(
        self,
        table_names_mock,
        table_description_mock,
    ):
        class _Col:
            def __init__(self, name: str):
                self.name = name

        table_names_mock.return_value = ["project_card", "timesheet_item"]
        table_description_mock.side_effect = [
            [_Col("id"), _Col("project_id"), _Col("project_name")],  # project_card without project_item_id
            [_Col("id"), _Col("project_id"), _Col("project_title")],  # timesheet_item without project_item_id
        ]

        cache.delete(PROJECT_CARD_SCHEMA_CACHE_KEY)
        self.assertFalse(ensure_project_card_schema(force_refresh=True))

    def test_collect_writeoff_maps_falls_back_when_project_item_column_missing(self):
        now = timezone.make_aware(datetime(2026, 4, 10, 10, 0))
        TimesheetItem.objects.create(
            bitrix24_account=self.account,
            bitrix_id=9001,
            task_id="9001",
            employee_id="u-1",
            hours=2.5,
            project_id="p-legacy",
            project_title="Legacy Project",
            date_reflection=now,
        )

        service = ProjectCardService(Mock(), self.account)
        original_filter = TimesheetItem.objects.filter
        call_counter = {"count": 0}

        def filter_side_effect(*args, **kwargs):
            call_counter["count"] += 1
            if call_counter["count"] == 1:
                raise ProgrammingError('column "timesheet_item"."project_item_id" does not exist')
            return original_filter(*args, **kwargs)

        with patch("main.project_board_service.TimesheetItem.objects.filter", side_effect=filter_side_effect):
            by_item, by_project_id, by_project_title = service.collect_writeoff_maps()

        self.assertEqual(by_item, {})
        self.assertIn("p-legacy", by_project_id)
        self.assertIn("Legacy Project", by_project_title)


class HomepagePortfolioStabilityTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=3,
            is_b24_user_admin=True,
            member_id="member-3",
            is_master_account=True,
            domain_url="portfolio.bitrix24.ru",
            status="active",
            application_version=1,
        )
        self.service = ProjectCardService(Mock(), self.account)

    @patch.object(ProjectCardService, "_get_revenue_leakage_rows", side_effect=RuntimeError("leakage failed"))
    @patch.object(ProjectCardService, "get_board_data", side_effect=RuntimeError("board failed"))
    def test_homepage_snapshot_handles_board_and_leakage_failures(self, _board_mock, _leakage_mock):
        snapshot = self.service.get_homepage_snapshot()

        self.assertIsInstance(snapshot, dict)
        self.assertEqual(snapshot.get("cards"), [])
        self.assertEqual(snapshot.get("top_loss_projects"), [])
        self.assertTrue(snapshot.get("warning"))
        self.assertIn("временно", snapshot.get("warning").lower())

    @patch.object(ProjectCardService, "_get_revenue_leakage_rows", side_effect=RuntimeError("leakage failed"))
    @patch.object(
        ProjectCardService,
        "get_board_data",
        return_value={
            "summary": {"total_count": 1, "active_count": 1, "archived_count": 0, "support_count": 0, "inactive_30_count": 0, "inactive_90_count": 0},
            "cards": [
                {
                    "project_id": "p-1",
                    "project_name": "Project 1",
                    "is_archived": False,
                    "curator_user_id": "42",
                    "curator_name": "Иван Иванов",
                    "last_writeoff_days": 5,
                }
            ],
            "stages": [],
            "warning": None,
        },
    )
    def test_homepage_snapshot_keeps_board_when_only_leakage_fails(self, _board_mock, _leakage_mock):
        snapshot = self.service.get_homepage_snapshot()

        self.assertEqual(snapshot["summary"]["total_count"], 1)
        self.assertEqual(len(snapshot["cards"]), 1)
        self.assertEqual(snapshot["top_loss_projects"], [])
        self.assertTrue(snapshot.get("warning"))


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
