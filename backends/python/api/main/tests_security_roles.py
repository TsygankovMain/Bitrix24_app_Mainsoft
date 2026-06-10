"""
Security tests for server-side admin role enforcement.
Task 1.4 — Sprint Security.

The vulnerability: no view checked Bitrix24Account.is_b24_user_admin, so a regular
employee could call admin operations and financial reports directly (admin gating
existed only in the UI).

These tests must FAIL against the pre-fix code and PASS after:
  * @admin_required gates the admin-only endpoints (403 for non-admin).
  * get_token refreshes is_b24_user_admin from the Bitrix user.admin method.
  * Error responses never leak a Python traceback to the client.
"""
import json
from http import HTTPStatus
from unittest.mock import MagicMock, PropertyMock, patch

from django.test import Client, TestCase

from .models import Bitrix24Account


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_account(domain_url: str = "portal-roles.bitrix24.ru", *, is_admin: bool, b24_user_id: int = 1) -> Bitrix24Account:
    return Bitrix24Account.objects.create(
        b24_user_id=b24_user_id,
        member_id=f"member_{b24_user_id}_{domain_url}",
        domain_url=domain_url,
        status="active",
        application_version=1,
        is_b24_user_admin=is_admin,
        is_master_account=False,
    )


def _auth_header(account: Bitrix24Account) -> str:
    return f"Bearer {account.create_jwt_token()}"


# (name, http_method, path) — must mirror main/urls.py.
ADMIN_ONLY_ENDPOINTS = [
    # Admin operations
    ("save_configuration", "post", "/api/configuration/save"),
    ("create_smart_process", "post", "/api/smart-processes/create"),
    ("create_fields", "post", "/api/smart-processes/create-fields"),
    ("create_mapped_field", "post", "/api/smart-processes/create-field"),
    ("get_request_logs", "get", "/api/logs/requests"),
    ("get_system_logs", "get", "/api/logs/system"),
    ("inn_backfill_scan", "get", "/api/inn-backfill/scan"),
    ("inn_backfill_apply", "post", "/api/inn-backfill/apply"),
    ("inn_backfill_project_items", "post", "/api/inn-backfill/project-items"),
    ("run_project_spa_backfill", "post", "/api/project-spa/backfill-timesheet"),
    ("run_project_board_daily_check", "post", "/api/project-board/run-daily-check"),
    ("sync_project_board", "post", "/api/project-board/sync"),
    ("update_project_board", "post", "/api/project-board/update"),
    ("update_project_board_stage", "post", "/api/project-board/update-stage"),
    ("archive_project_board", "post", "/api/project-board/archive"),
    ("export_raw_data", "post", "/api/export-raw-data"),
    ("timesheet_list", "get", "/api/timesheets"),
    ("projects_health", "get", "/api/projects-health"),
    # Financial reports (Sprint 1 product restriction)
    ("report_employee_project", "get", "/api/report-employee-project"),
    ("report_employee_project_export", "get", "/api/report-employee-project-export"),
    ("report_project_employee", "get", "/api/report-project-employee"),
    ("report_project_employee_export", "get", "/api/report-project-employee-export"),
    ("report_project_task_employee", "get", "/api/report-project-task-employee"),
    ("report_project_task_employee_export", "get", "/api/report-project-task-employee-export"),
    ("report_revenue_leakage", "get", "/api/report-revenue-leakage"),
    ("report_revenue_leakage_export", "get", "/api/report-revenue-leakage-export"),
]

# Endpoints that must stay open to any authenticated user (representative subset).
OPEN_ENDPOINTS = [
    ("get_configuration", "get", "/api/configuration"),
    ("report_daily_workload", "get", "/api/report-daily-workload"),
    ("report_time_entry_discipline", "get", "/api/report-time-entry-discipline"),
    ("report_focus_analysis", "get", "/api/report-focus-analysis"),
    ("get_project_board", "get", "/api/project-board"),
]


def _call(client: Client, method: str, path: str, account: Bitrix24Account):
    kwargs = {"HTTP_AUTHORIZATION": _auth_header(account)}
    if method == "post":
        return client.post(path, data=json.dumps({}), content_type="application/json", **kwargs)
    return client.get(path, **kwargs)


# ---------------------------------------------------------------------------
# (а) Non-admin is rejected with 403 on every admin-only endpoint
# ---------------------------------------------------------------------------

class AdminOnlyEndpointsRejectNonAdminTest(TestCase):
    """A regular employee (is_b24_user_admin=False) must receive 403 on every
    admin-only endpoint. The decorator runs before the view body, so no Bitrix
    call should be required to produce the 403 — we assert only the status."""

    def setUp(self):
        self.client = Client()
        self.account = _make_account(is_admin=False)

    def test_non_admin_gets_403_on_every_admin_endpoint(self):
        for name, method, path in ADMIN_ONLY_ENDPOINTS:
            with self.subTest(endpoint=name, method=method, path=path):
                resp = _call(self.client, method, path, self.account)
                self.assertEqual(
                    resp.status_code,
                    HTTPStatus.FORBIDDEN,
                    f"{name} ({method.upper()} {path}) must reject a non-admin with 403, "
                    f"got {resp.status_code}",
                )

    def test_403_response_carries_russian_permission_message(self):
        # Spot-check one endpoint to confirm the contract of the 403 body.
        resp = _call(self.client, "get", "/api/logs/system", self.account)
        self.assertEqual(resp.status_code, HTTPStatus.FORBIDDEN)
        self.assertIn("application/json", resp["Content-Type"])
        self.assertEqual(resp.json().get("error"), "Недостаточно прав")


# ---------------------------------------------------------------------------
# (б) Admin passes the decorator (view body may do anything except 403)
# ---------------------------------------------------------------------------

class AdminPassesAdminGateTest(TestCase):
    """An admin (is_b24_user_admin=True) must pass @admin_required. The view body
    then executes; its dependencies (Bitrix) are not available in tests, so the
    response may be 200/400/500 — the only forbidden outcome is 403."""

    def setUp(self):
        self.client = Client()
        self.account = _make_account(is_admin=True)

    def test_admin_is_not_blocked_on_any_admin_endpoint(self):
        # Neutralize all Bitrix traffic so the view body cannot make real calls.
        bitrix_client = MagicMock()
        with patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=bitrix_client):
            for name, method, path in ADMIN_ONLY_ENDPOINTS:
                with self.subTest(endpoint=name, method=method, path=path):
                    resp = _call(self.client, method, path, self.account)
                    self.assertNotEqual(
                        resp.status_code,
                        HTTPStatus.FORBIDDEN,
                        f"{name} ({method.upper()} {path}) must let an admin through "
                        f"(got 403 — admin gate is misconfigured)",
                    )


# ---------------------------------------------------------------------------
# (в) Open endpoints stay accessible to a non-admin
# ---------------------------------------------------------------------------

class OpenEndpointsAllowNonAdminTest(TestCase):
    """Hour-only reports, the task-screen configuration and the read-only project
    board must remain available to any authenticated user (never 403)."""

    def setUp(self):
        self.client = Client()
        self.account = _make_account(is_admin=False)

    def test_non_admin_is_not_blocked_on_open_endpoints(self):
        bitrix_client = MagicMock()
        with patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=bitrix_client):
            for name, method, path in OPEN_ENDPOINTS:
                with self.subTest(endpoint=name, method=method, path=path):
                    resp = _call(self.client, method, path, self.account)
                    self.assertNotEqual(
                        resp.status_code,
                        HTTPStatus.FORBIDDEN,
                        f"{name} ({method.upper()} {path}) must stay open to a non-admin, "
                        f"got 403",
                    )


# ---------------------------------------------------------------------------
# (г) get_token refreshes is_b24_user_admin from the Bitrix user.admin method
# ---------------------------------------------------------------------------

class GetTokenRefreshesAdminFlagTest(TestCase):
    """get_token must call user.admin for the account token and persist the result
    in is_b24_user_admin. A failure of that call must not break token issuance."""

    GET_TOKEN_PAYLOAD = {
        "DOMAIN": "portal-roles.bitrix24.ru",
        "PROTOCOL": 1,
        "LANG": "ru",
        "APP_SID": "app-sid",
        "AUTH_ID": "auth-token",
        "REFRESH_ID": "refresh-token",
        "AUTH_EXPIRES": 3600,
        "member_id": "member-1",
        "status": "L",
    }

    def _post_get_token(self):
        return Client().post(
            "/api/getToken",
            data=json.dumps(self.GET_TOKEN_PAYLOAD),
            content_type="application/json",
        )

    def _patch_oauth(self, account):
        # Bypass the real OAuth handshake: auth_required falls back to OAuth when
        # no Bearer header is present and resolves the account from placement data.
        return patch.object(
            Bitrix24Account,
            "update_or_create_from_oauth_placement_data",
            return_value=(account, False),
        )

    def _patch_user_admin(self, *, result=None, side_effect=None):
        bitrix_client = MagicMock()
        call_method = bitrix_client._bitrix_token.call_method
        if side_effect is not None:
            call_method.side_effect = side_effect
        else:
            call_method.return_value = {"result": result}
        return patch.object(
            Bitrix24Account, "client", new_callable=PropertyMock, return_value=bitrix_client
        ), call_method

    def test_get_token_sets_admin_true(self):
        account = _make_account(is_admin=False)
        client_patch, call_method = self._patch_user_admin(result=True)
        with self._patch_oauth(account), client_patch:
            resp = self._post_get_token()

        self.assertEqual(resp.status_code, 200)
        self.assertIn("token", resp.json())
        account.refresh_from_db()
        self.assertTrue(account.is_b24_user_admin, "user.admin=True must persist is_b24_user_admin=True")
        # user.admin must actually be the method that was queried.
        called_methods = [c.args[0] for c in call_method.call_args_list if c.args]
        self.assertIn("user.admin", called_methods)

    def test_get_token_sets_admin_false(self):
        account = _make_account(is_admin=True)
        client_patch, _ = self._patch_user_admin(result=False)
        with self._patch_oauth(account), client_patch:
            resp = self._post_get_token()

        self.assertEqual(resp.status_code, 200)
        account.refresh_from_db()
        self.assertFalse(account.is_b24_user_admin, "user.admin=False must persist is_b24_user_admin=False")

    def test_get_token_survives_user_admin_failure(self):
        account = _make_account(is_admin=True)
        client_patch, _ = self._patch_user_admin(side_effect=RuntimeError("bitrix down"))
        with self._patch_oauth(account), client_patch:
            resp = self._post_get_token()

        # Token must still be issued; prior role value is preserved.
        self.assertEqual(resp.status_code, 200)
        self.assertIn("token", resp.json())
        account.refresh_from_db()
        self.assertTrue(account.is_b24_user_admin, "a failed user.admin call must not flip the stored role")


# ---------------------------------------------------------------------------
# (д) No error response leaks a Python traceback to the client
# ---------------------------------------------------------------------------

class NoTracebackLeakTest(TestCase):
    """The OAuth-fallback branch of auth_required must not return a raw traceback
    in the JSON body when something unexpected blows up."""

    PAYLOAD = {
        "DOMAIN": "portal-roles.bitrix24.ru",
        "PROTOCOL": 1,
        "LANG": "ru",
        "APP_SID": "app-sid",
        "AUTH_ID": "auth-token",
        "REFRESH_ID": "refresh-token",
        "AUTH_EXPIRES": 3600,
        "member_id": "member-1",
        "status": "L",
    }

    def test_auth_required_internal_error_has_no_traceback(self):
        with patch.object(
            Bitrix24Account,
            "update_or_create_from_oauth_placement_data",
            side_effect=RuntimeError("boom secret internal detail"),
        ):
            resp = Client().post(
                "/api/getToken",
                data=json.dumps(self.PAYLOAD),
                content_type="application/json",
            )

        self.assertEqual(resp.status_code, HTTPStatus.INTERNAL_SERVER_ERROR)
        body = resp.content.decode("utf-8")
        self.assertNotIn("Traceback (most recent call last)", body)
        # The raw exception text / stack frames must not be echoed to the client.
        self.assertNotIn("boom secret internal detail", body)
        self.assertNotIn("traceback", resp.json())
