from unittest.mock import patch

from django.test import TestCase, Client

from .models import Bitrix24Account


class SyncHonestErrorTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-2-3", is_master_account=True,
            domain_url="example.bitrix24.ru", status="active", application_version=1,
        )

    @patch("main.views.TimesheetSyncService.sync_all", side_effect=RuntimeError("secret trace 12345"))
    @patch("main.views.ConfigurationService.get_configuration_sync",
           return_value={"sp_entity_type_id": 1, "fields_mapping": {}})
    def test_sync_failure_is_not_success_and_hides_trace(self, _cfg, _sync):
        token = self.account.create_jwt_token()
        response = Client().post(
            "/api/sync-timesheets",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotEqual(payload.get("status"), "success")
        self.assertEqual(payload.get("status"), "warning")
        body = response.content.decode("utf-8")
        self.assertNotIn("secret trace 12345", body)
        self.assertNotIn("error", payload)  # ключ error удалён из ответа

    @patch("main.views.ProjectSyncService.sync", side_effect=RuntimeError("pg dsn db:5432 secret"))
    def test_project_board_sync_failure_hides_trace(self, _sync):
        token = self.account.create_jwt_token()
        response = Client().post(
            "/api/project-board/sync",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload.get("status"), "warning")
        body = response.content.decode("utf-8")
        self.assertNotIn("pg dsn db:5432 secret", body)  # текст исключения не утекает
        self.assertNotIn("error", payload)  # ключ error удалён
