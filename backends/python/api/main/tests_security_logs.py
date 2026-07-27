"""
Security tests for request/system log isolation and secret redaction.
Task 1.1 — Sprint Security.

Tests must FAIL against the current (vulnerable) code and PASS after the fix.
"""
import json
import re

from django.test import Client, TestCase

from .middleware import RequestLoggingMiddleware
from .models import Bitrix24Account, RequestLog, SystemLog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_account(domain_url: str, b24_user_id: int = 1) -> Bitrix24Account:
    """Create a minimal Bitrix24Account for testing.

    The log-viewing endpoints (/api/logs/*) are admin-only since Task 1.4, so the
    isolation tests below use admin accounts — they verify per-portal *scoping*,
    not role gating (role gating is covered by tests_security_roles).
    """
    return Bitrix24Account.objects.create(
        b24_user_id=b24_user_id,
        member_id=f"member_{b24_user_id}_{domain_url}",
        domain_url=domain_url,
        status="active",
        application_version=1,
        is_b24_user_admin=True,
        is_master_account=False,
    )


def _auth_header(account: Bitrix24Account) -> str:
    return f"Bearer {account.create_jwt_token()}"


# ---------------------------------------------------------------------------
# (а) Log isolation — each portal sees only its own records
# ---------------------------------------------------------------------------

class LogIsolationTest(TestCase):
    """get_request_logs and get_system_logs must return only records
    belonging to the authenticated account."""

    def setUp(self):
        self.client_a = Client()
        self.client_b = Client()

        self.account_a = _make_account("portal-a.bitrix24.ru", b24_user_id=1)
        self.account_b = _make_account("portal-b.bitrix24.ru", b24_user_id=2)

        # Records belonging to account A
        RequestLog.objects.create(
            method="POST",
            path="/api/someAction",
            status_code=200,
            duration_ms=5.0,
            request_body="bodyA",
            response_body="respA",
            bitrix24_account=self.account_a,
        )
        SystemLog.objects.create(
            level="INFO",
            module="test",
            message="syslog for A",
            bitrix24_account=self.account_a,
        )

        # Records belonging to account B
        RequestLog.objects.create(
            method="POST",
            path="/api/otherAction",
            status_code=200,
            duration_ms=5.0,
            request_body="bodyB",
            response_body="respB",
            bitrix24_account=self.account_b,
        )
        SystemLog.objects.create(
            level="ERROR",
            module="test",
            message="syslog for B",
            bitrix24_account=self.account_b,
        )

    def test_request_logs_return_only_own_portal_records(self):
        """Account A must not see records of account B."""
        resp = self.client_a.get(
            "/api/logs/requests",
            HTTP_AUTHORIZATION=_auth_header(self.account_a),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        paths = [item["path"] for item in data["items"]]
        self.assertIn("/api/someAction", paths, "Account A should see its own request log")
        self.assertNotIn("/api/otherAction", paths, "Account A must not see account B request log")

    def test_system_logs_return_only_own_portal_records(self):
        """Account A must not see system log records of account B."""
        resp = self.client_a.get(
            "/api/logs/system",
            HTTP_AUTHORIZATION=_auth_header(self.account_a),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        messages = [item["message"] for item in data["items"]]
        self.assertIn("syslog for A", messages, "Account A should see its own system log")
        self.assertNotIn("syslog for B", messages, "Account A must not see account B system log")

    def test_request_logs_account_b_does_not_see_account_a_records(self):
        """Account B must not see records of account A."""
        resp = self.client_b.get(
            "/api/logs/requests",
            HTTP_AUTHORIZATION=_auth_header(self.account_b),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        paths = [item["path"] for item in data["items"]]
        self.assertNotIn("/api/someAction", paths, "Account B must not see account A request log")
        self.assertIn("/api/otherAction", paths, "Account B should see its own request log")


# ---------------------------------------------------------------------------
# (б) Sensitive paths are NOT logged at all
# ---------------------------------------------------------------------------

class SensitivePathNotLoggedTest(TestCase):
    """POST /api/getToken and /api/install must not produce RequestLog entries."""

    def setUp(self):
        self.client = Client()

    def _count_request_logs_for(self, path: str) -> int:
        return RequestLog.objects.filter(path=path).count()

    def test_get_token_path_not_logged(self):
        """POST /api/getToken must not create a RequestLog entry."""
        before = self._count_request_logs_for("/api/getToken")
        # We expect a non-200 response (no valid payload) but the important
        # thing is that no log entry is written for this path.
        self.client.post(
            "/api/getToken",
            data=json.dumps({"some": "data"}),
            content_type="application/json",
        )
        after = self._count_request_logs_for("/api/getToken")
        self.assertEqual(before, after, "POST /api/getToken must not be logged in RequestLog")

    def test_install_path_not_logged(self):
        """POST /api/install must not create a RequestLog entry."""
        before = self._count_request_logs_for("/api/install")
        self.client.post(
            "/api/install",
            data=json.dumps({"some": "data"}),
            content_type="application/json",
        )
        after = self._count_request_logs_for("/api/install")
        self.assertEqual(before, after, "POST /api/install must not be logged in RequestLog")


# ---------------------------------------------------------------------------
# (в) _redact_secrets masks sensitive field values
# ---------------------------------------------------------------------------

class RedactSecretsTest(TestCase):
    """_redact_secrets must mask secret values while preserving other content."""

    def _redact(self, text: str) -> str:
        # Import from middleware so the function is exercised as shipped
        from .middleware import _redact_secrets
        return _redact_secrets(text)

    # --- JSON format ---

    def test_redacts_access_token_in_json(self):
        body = '{"access_token":"secret123","other":"keep"}'
        result = self._redact(body)
        self.assertNotIn("secret123", result)
        self.assertIn("keep", result)
        self.assertIn("***", result)

    def test_redacts_refresh_token_in_json(self):
        body = '{"refresh_token": "tok_refresh_xyz"}'
        result = self._redact(body)
        self.assertNotIn("tok_refresh_xyz", result)

    def test_redacts_auth_id_in_json(self):
        body = '{"AUTH_ID":"abc_auth","DOMAIN":"portal.bitrix24.ru"}'
        result = self._redact(body)
        self.assertNotIn("abc_auth", result)
        self.assertIn("portal.bitrix24.ru", result)

    def test_redacts_refresh_id_in_json(self):
        body = '{"REFRESH_ID":"ref_secret","data":"visible"}'
        result = self._redact(body)
        self.assertNotIn("ref_secret", result)
        self.assertIn("visible", result)

    def test_redacts_token_in_json(self):
        body = '{"token":"jwt_value_123"}'
        result = self._redact(body)
        self.assertNotIn("jwt_value_123", result)

    def test_redacts_case_insensitive_in_json(self):
        body = '{"Access_Token":"CaseSensitiveVal"}'
        result = self._redact(body)
        self.assertNotIn("CaseSensitiveVal", result)

    # --- Form-encoded format ---

    def test_redacts_access_token_in_form(self):
        body = "access_token=formtokenvalue&other=keep"
        result = self._redact(body)
        self.assertNotIn("formtokenvalue", result)
        self.assertIn("keep", result)

    def test_redacts_auth_id_in_form(self):
        body = "AUTH_ID=form_auth_id_val&DOMAIN=portal.bitrix24.ru"
        result = self._redact(body)
        self.assertNotIn("form_auth_id_val", result)
        self.assertIn("portal.bitrix24.ru", result)

    def test_redacts_refresh_token_in_form(self):
        body = "refresh_token=ref123&user=john"
        result = self._redact(body)
        self.assertNotIn("ref123", result)
        self.assertIn("john", result)

    # --- Authorization header format ---

    def test_redacts_bearer_token_in_header(self):
        body = "Authorization: Bearer supersecret_jwt_token"
        result = self._redact(body)
        self.assertNotIn("supersecret_jwt_token", result)

    def test_redacts_authorization_key_value(self):
        body = '{"Authorization":"Bearer the_token_value"}'
        result = self._redact(body)
        self.assertNotIn("the_token_value", result)

    # --- Non-secret fields are preserved ---

    def test_preserves_non_secret_fields(self):
        body = '{"user_id":"42","project":"alpha","access_token":"hidden"}'
        result = self._redact(body)
        self.assertIn("user_id", result)
        self.assertIn("42", result)
        self.assertIn("project", result)
        self.assertIn("alpha", result)

    def test_handles_empty_string(self):
        self.assertEqual(self._redact(""), "")

    def test_handles_plain_text_no_secrets(self):
        body = "just some plain text with no secrets"
        result = self._redact(body)
        self.assertEqual(result, body)


# ---------------------------------------------------------------------------
# (г) `limit` из query string валидируется перед Paginator
# ---------------------------------------------------------------------------

class LogEndpointPageSizeValidationTest(TestCase):
    """`limit` шёл в Paginator(queryset, page_size) невалидированным: limit=0 ->
    ZeroDivisionError, limit=-1 -> вводящее в заблуждение EmptyPage ("page number
    is less than 1" — жалуется на page, хотя проблема в limit), limit=abc ->
    ValueError из int(). Все три давали 500 с сырым текстом Python-исключения
    и ERROR с traceback в SystemLog на каждый запрос.

    Диагностические эндпоинты админские, разбор инцидента выигрывает от большой
    страницы, поэтому верхняя граница здесь 500, а не 200 как у /api/users.
    """

    MAX_PAGE_SIZE = 500

    def setUp(self):
        self.account = _make_account("portal-limits.bitrix24.ru", b24_user_id=7)
        self.client = Client()

    def _get(self, path, query=""):
        return self.client.get(f"{path}{query}", HTTP_AUTHORIZATION=_auth_header(self.account))

    def _request_logs(self, count):
        RequestLog.objects.bulk_create([
            RequestLog(
                method="GET", path=f"/api/thing/{i}", status_code=200, duration_ms=1.0,
                request_body="", response_body="", bitrix24_account=self.account,
            )
            for i in range(count)
        ])

    def _system_logs(self, count):
        SystemLog.objects.bulk_create([
            SystemLog(level="INFO", module="test", message=f"msg {i}", bitrix24_account=self.account)
            for i in range(count)
        ])

    def _seed(self, path, count):
        if path == "/api/logs/requests":
            self._request_logs(count)
        else:
            self._system_logs(count)

    def _both(self):
        return ("/api/logs/requests", "/api/logs/system")

    def test_limit_zero_is_clamped_to_minimum_not_500(self):
        for path in self._both():
            with self.subTest(path=path):
                self._seed(path, 2)

                response = self._get(path, "?limit=0")

                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(len(data["items"]), 1)  # limit=0 -> клэмп к минимуму 1
                self.assertEqual(data["pages"], 2)

    def test_limit_negative_is_clamped_to_minimum_not_500(self):
        for path in self._both():
            with self.subTest(path=path):
                self._seed(path, 2)

                response = self._get(path, "?limit=-1")

                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(len(data["items"]), 1)
                self.assertEqual(data["pages"], 2)

    def test_limit_non_numeric_falls_back_to_default_not_500(self):
        for path in self._both():
            with self.subTest(path=path):
                self._seed(path, 3)

                response = self._get(path, "?limit=abc")

                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(len(data["items"]), 3)  # дефолт 50 -> всё на одной странице
                self.assertEqual(data["pages"], 1)

    def test_limit_above_upper_bound_is_clamped(self):
        for path in self._both():
            with self.subTest(path=path):
                self._seed(path, self.MAX_PAGE_SIZE + 1)

                response = self._get(path, "?limit=100000")

                self.assertEqual(response.status_code, 200)
                data = response.json()
                # верхний предел — не вся таблица логов в одном ответе
                self.assertEqual(len(data["items"]), self.MAX_PAGE_SIZE)
                self.assertEqual(data["pages"], 2)

    def test_invalid_limit_does_not_write_error_to_system_log(self):
        # log_errors ловит исключение вьюхи и пишет SystemLog(level="ERROR") с
        # полным traceback: каждый запрос с кривым limit давал шум в мониторинге
        # — причём в той самой таблице, которую эти эндпоинты и показывают.
        for path in self._both():
            with self.subTest(path=path):
                SystemLog.objects.all().delete()
                self._seed(path, 2)

                for query in ("?limit=0", "?limit=-1", "?limit=abc", "?limit=100000"):
                    self._get(path, query)

                self.assertEqual(SystemLog.objects.filter(level="ERROR").count(), 0)
