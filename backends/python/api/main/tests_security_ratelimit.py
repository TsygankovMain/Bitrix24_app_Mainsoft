"""
Security tests for rate limiting.
Task 1.5 — Sprint Security.

Tests verify:
(а) N допустимых запросов проходят, N+1-й → 429 с JSON {"error": "..."}.
(б) После истечения окна — снова не-429.
(в) Лимиты раздельны по ключам.
(г) Обычный одиночный запрос работает как раньше.
"""
import json
import time
from http import HTTPStatus
from unittest.mock import MagicMock, PropertyMock, patch

from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from .models import Bitrix24Account


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RATELIMIT_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "ratelimit-tests"}}


def _make_account(domain_url: str = "portal-rl.bitrix24.ru", *, is_admin: bool = True, b24_user_id: int = 1) -> Bitrix24Account:
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


def _bitrix_mock():
    """Return a MagicMock that satisfies Bitrix24Account.client usage in views."""
    return MagicMock()


# ---------------------------------------------------------------------------
# (а) N допустимых запросов проходят, N+1-й → 429 с JSON {"error": "..."}
# ---------------------------------------------------------------------------

@override_settings(CACHES=RATELIMIT_CACHE)
class RateLimitBasicTest(TestCase):
    """Базовое поведение: после N запросов N+1-й блокируется с 429."""

    def setUp(self):
        cache.clear()
        self.client = Client()
        self.account = _make_account(is_admin=True)

    def test_get_token_passes_within_limit_and_blocks_on_overflow(self):
        """get_token: 10 запросов с одного IP разрешены, 11-й → 429."""
        GET_TOKEN_LIMIT = 10
        payload = json.dumps({
            "DOMAIN": "portal-rl.bitrix24.ru",
            "PROTOCOL": 1,
            "LANG": "ru",
            "APP_SID": "app-sid",
            "AUTH_ID": "auth-token",
            "REFRESH_ID": "refresh-token",
            "AUTH_EXPIRES": 3600,
            "member_id": "member-1",
            "status": "L",
        })

        bitrix_client = _bitrix_mock()
        bitrix_client._bitrix_token.call_method.return_value = {"result": True}

        with patch.object(Bitrix24Account, "update_or_create_from_oauth_placement_data", return_value=(self.account, False)), \
             patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=bitrix_client):

            # First GET_TOKEN_LIMIT requests must pass (not 429)
            for i in range(GET_TOKEN_LIMIT):
                resp = self.client.post(
                    "/api/getToken",
                    data=payload,
                    content_type="application/json",
                    REMOTE_ADDR="1.2.3.4",
                )
                self.assertNotEqual(
                    resp.status_code,
                    HTTPStatus.TOO_MANY_REQUESTS,
                    f"Request {i + 1}/{GET_TOKEN_LIMIT} must pass, got {resp.status_code}",
                )

            # N+1 must be blocked
            resp = self.client.post(
                "/api/getToken",
                data=payload,
                content_type="application/json",
                REMOTE_ADDR="1.2.3.4",
            )
            self.assertEqual(
                resp.status_code,
                HTTPStatus.TOO_MANY_REQUESTS,
                f"Request {GET_TOKEN_LIMIT + 1} must be blocked with 429, got {resp.status_code}",
            )
            body = resp.json()
            self.assertIn("error", body, "429 response must contain 'error' key")
            self.assertIsInstance(body["error"], str, "'error' value must be a string")

    def test_sync_view_passes_within_limit_and_blocks_on_overflow(self):
        """timesheet_sync: 6 запросов разрешены, 7-й → 429."""
        SYNC_LIMIT = 6
        bitrix_client = _bitrix_mock()

        with patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=bitrix_client):
            for i in range(SYNC_LIMIT):
                resp = self.client.post(
                    "/api/sync-timesheets",
                    data=json.dumps({}),
                    content_type="application/json",
                    HTTP_AUTHORIZATION=_auth_header(self.account),
                )
                self.assertNotEqual(
                    resp.status_code,
                    HTTPStatus.TOO_MANY_REQUESTS,
                    f"timesheet_sync request {i + 1}/{SYNC_LIMIT} must pass, got {resp.status_code}",
                )

            # N+1 must be blocked
            resp = self.client.post(
                "/api/sync-timesheets",
                data=json.dumps({}),
                content_type="application/json",
                HTTP_AUTHORIZATION=_auth_header(self.account),
            )
            self.assertEqual(
                resp.status_code,
                HTTPStatus.TOO_MANY_REQUESTS,
                f"timesheet_sync request {SYNC_LIMIT + 1} must be blocked with 429, got {resp.status_code}",
            )
            body = resp.json()
            self.assertIn("error", body)

    def test_export_view_passes_within_limit_and_blocks_on_overflow(self):
        """report_employee_project_export: 12 запросов разрешены, 13-й → 429."""
        EXPORT_LIMIT = 12
        bitrix_client = _bitrix_mock()

        with patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=bitrix_client):
            for i in range(EXPORT_LIMIT):
                resp = self.client.get(
                    "/api/report-employee-project-export",
                    HTTP_AUTHORIZATION=_auth_header(self.account),
                )
                self.assertNotEqual(
                    resp.status_code,
                    HTTPStatus.TOO_MANY_REQUESTS,
                    f"export request {i + 1}/{EXPORT_LIMIT} must pass, got {resp.status_code}",
                )

            # N+1 must be blocked
            resp = self.client.get(
                "/api/report-employee-project-export",
                HTTP_AUTHORIZATION=_auth_header(self.account),
            )
            self.assertEqual(
                resp.status_code,
                HTTPStatus.TOO_MANY_REQUESTS,
                f"export request {EXPORT_LIMIT + 1} must be blocked with 429, got {resp.status_code}",
            )
            body = resp.json()
            self.assertIn("error", body)


# ---------------------------------------------------------------------------
# (б) После истечения окна — снова не-429
# ---------------------------------------------------------------------------

@override_settings(CACHES=RATELIMIT_CACHE)
class RateLimitWindowExpiryTest(TestCase):
    """После истечения окна счётчик сбрасывается и запросы снова проходят."""

    def setUp(self):
        cache.clear()
        self.client = Client()
        self.account = _make_account(is_admin=True, b24_user_id=99, domain_url="portal-window.bitrix24.ru")

    def test_requests_allowed_after_window_expires(self):
        """После истечения окна (симулируем через cache.clear) — запросы снова проходят.

        Семантика фиксированного окна: cache.add с timeout=window_seconds.
        Когда cache очищен (TTL истёк), счётчик сбрасывается — следующий запрос проходит.
        """
        bitrix_client = _bitrix_mock()
        payload = json.dumps({
            "DOMAIN": "portal-window.bitrix24.ru",
            "PROTOCOL": 1, "LANG": "ru", "APP_SID": "x",
            "AUTH_ID": "tok", "REFRESH_ID": "ref", "AUTH_EXPIRES": 3600,
            "member_id": "member-window", "status": "L",
        })
        bitrix_client._bitrix_token.call_method.return_value = {"result": True}

        # Exhaust the limit (10 requests for get_token).
        with patch.object(Bitrix24Account, "update_or_create_from_oauth_placement_data", return_value=(self.account, False)), \
             patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=bitrix_client):

            for _ in range(10):
                self.client.post("/api/getToken", data=payload, content_type="application/json",
                                 REMOTE_ADDR="192.168.10.1")

            # Verify exhausted
            resp = self.client.post("/api/getToken", data=payload, content_type="application/json",
                                    REMOTE_ADDR="192.168.10.1")
            self.assertEqual(resp.status_code, HTTPStatus.TOO_MANY_REQUESTS,
                             "Must be blocked after exhaustion")

            # Simulate window expiry by clearing the relevant cache key directly.
            # (Equivalent to window_seconds elapsing — cache entry expires naturally.)
            cache.clear()

            # Now it must pass again
            resp = self.client.post("/api/getToken", data=payload, content_type="application/json",
                                    REMOTE_ADDR="192.168.10.1")
            self.assertNotEqual(
                resp.status_code,
                HTTPStatus.TOO_MANY_REQUESTS,
                f"After window reset (cache cleared) request must pass again, got {resp.status_code}",
            )


# ---------------------------------------------------------------------------
# (в) Лимиты раздельны по ключам
# ---------------------------------------------------------------------------

@override_settings(CACHES=RATELIMIT_CACHE)
class RateLimitKeyIsolationTest(TestCase):
    """Исчерпание лимита для одного ключа не блокирует другой."""

    def setUp(self):
        cache.clear()
        self.client = Client()

    def test_account_key_isolation_sync(self):
        """Аккаунт A исчерпывает лимит sync — аккаунт B не блокируется."""
        account_a = _make_account(domain_url="portal-key-a.bitrix24.ru", b24_user_id=10)
        account_b = _make_account(domain_url="portal-key-b.bitrix24.ru", b24_user_id=20)
        bitrix_client = _bitrix_mock()

        SYNC_LIMIT = 6
        with patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=bitrix_client):
            # Exhaust account A
            for _ in range(SYNC_LIMIT + 1):
                self.client.post(
                    "/api/sync-timesheets",
                    data=json.dumps({}),
                    content_type="application/json",
                    HTTP_AUTHORIZATION=_auth_header(account_a),
                )

            # Verify A is blocked
            resp_a = self.client.post(
                "/api/sync-timesheets",
                data=json.dumps({}),
                content_type="application/json",
                HTTP_AUTHORIZATION=_auth_header(account_a),
            )
            self.assertEqual(resp_a.status_code, HTTPStatus.TOO_MANY_REQUESTS,
                             "Account A must be rate-limited")

            # Account B must still work (not 429)
            resp_b = self.client.post(
                "/api/sync-timesheets",
                data=json.dumps({}),
                content_type="application/json",
                HTTP_AUTHORIZATION=_auth_header(account_b),
            )
            self.assertNotEqual(
                resp_b.status_code,
                HTTPStatus.TOO_MANY_REQUESTS,
                f"Account B must not be rate-limited because of Account A, got {resp_b.status_code}",
            )

    def test_account_key_isolation_export(self):
        """Аккаунт A исчерпывает лимит export — аккаунт B не блокируется."""
        account_a = _make_account(domain_url="portal-exp-a.bitrix24.ru", b24_user_id=30, is_admin=True)
        account_b = _make_account(domain_url="portal-exp-b.bitrix24.ru", b24_user_id=40, is_admin=True)
        bitrix_client = _bitrix_mock()

        EXPORT_LIMIT = 12
        with patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=bitrix_client):
            # Exhaust account A
            for _ in range(EXPORT_LIMIT + 1):
                self.client.get(
                    "/api/report-employee-project-export",
                    HTTP_AUTHORIZATION=_auth_header(account_a),
                )

            # Verify A is blocked
            resp_a = self.client.get(
                "/api/report-employee-project-export",
                HTTP_AUTHORIZATION=_auth_header(account_a),
            )
            self.assertEqual(resp_a.status_code, HTTPStatus.TOO_MANY_REQUESTS,
                             "Account A must be rate-limited on exports")

            # Account B must still work
            resp_b = self.client.get(
                "/api/report-employee-project-export",
                HTTP_AUTHORIZATION=_auth_header(account_b),
            )
            self.assertNotEqual(
                resp_b.status_code,
                HTTPStatus.TOO_MANY_REQUESTS,
                f"Account B must not be rate-limited because of Account A, got {resp_b.status_code}",
            )

    def test_ip_domain_key_isolation_get_token(self):
        """get_token: исчерпание IP 1.2.3.4 не блокирует 5.6.7.8."""
        account = _make_account(is_admin=True, b24_user_id=50, domain_url="portal-ip.bitrix24.ru")
        bitrix_client = _bitrix_mock()
        bitrix_client._bitrix_token.call_method.return_value = {"result": True}
        payload = json.dumps({
            "DOMAIN": "portal-ip.bitrix24.ru",
            "PROTOCOL": 1, "LANG": "ru", "APP_SID": "x",
            "AUTH_ID": "tok", "REFRESH_ID": "ref", "AUTH_EXPIRES": 3600,
            "member_id": "member-ip", "status": "L",
        })

        with patch.object(Bitrix24Account, "update_or_create_from_oauth_placement_data", return_value=(account, False)), \
             patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=bitrix_client):

            # Exhaust from IP 1
            for _ in range(11):
                self.client.post("/api/getToken", data=payload, content_type="application/json",
                                 REMOTE_ADDR="1.2.3.4")

            # IP 1 must be blocked
            resp_ip1 = self.client.post("/api/getToken", data=payload, content_type="application/json",
                                        REMOTE_ADDR="1.2.3.4")
            self.assertEqual(resp_ip1.status_code, HTTPStatus.TOO_MANY_REQUESTS,
                             "IP 1.2.3.4 must be rate-limited")

            # IP 2 must still work
            resp_ip2 = self.client.post("/api/getToken", data=payload, content_type="application/json",
                                        REMOTE_ADDR="5.6.7.8")
            self.assertNotEqual(
                resp_ip2.status_code,
                HTTPStatus.TOO_MANY_REQUESTS,
                f"IP 5.6.7.8 must not be blocked because of IP 1.2.3.4, got {resp_ip2.status_code}",
            )


# ---------------------------------------------------------------------------
# (г) Обычный одиночный запрос работает как раньше
# ---------------------------------------------------------------------------

@override_settings(CACHES=RATELIMIT_CACHE)
class RateLimitSingleRequestTest(TestCase):
    """Одиночный запрос на защищённый endpoint работает нормально."""

    def setUp(self):
        cache.clear()
        self.client = Client()
        self.account = _make_account(is_admin=True, b24_user_id=60, domain_url="portal-single.bitrix24.ru")

    def test_single_sync_request_not_blocked(self):
        """Один запрос к timesheet_sync не блокируется."""
        bitrix_client = _bitrix_mock()

        with patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=bitrix_client):
            resp = self.client.post(
                "/api/sync-timesheets",
                data=json.dumps({}),
                content_type="application/json",
                HTTP_AUTHORIZATION=_auth_header(self.account),
            )
        self.assertNotEqual(
            resp.status_code,
            HTTPStatus.TOO_MANY_REQUESTS,
            f"Single request must not be rate-limited, got {resp.status_code}",
        )

    def test_single_export_request_not_blocked(self):
        """Один запрос к export-эндпоинту не блокируется."""
        bitrix_client = _bitrix_mock()

        with patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=bitrix_client):
            resp = self.client.get(
                "/api/report-project-employee-export",
                HTTP_AUTHORIZATION=_auth_header(self.account),
            )
        self.assertNotEqual(
            resp.status_code,
            HTTPStatus.TOO_MANY_REQUESTS,
            f"Single export request must not be rate-limited, got {resp.status_code}",
        )

    def test_single_get_token_request_not_blocked(self):
        """Один запрос к getToken не блокируется."""
        account = _make_account(is_admin=True, b24_user_id=61, domain_url="portal-single2.bitrix24.ru")
        bitrix_client = _bitrix_mock()
        bitrix_client._bitrix_token.call_method.return_value = {"result": True}
        payload = json.dumps({
            "DOMAIN": "portal-single2.bitrix24.ru",
            "PROTOCOL": 1, "LANG": "ru", "APP_SID": "x",
            "AUTH_ID": "tok", "REFRESH_ID": "ref", "AUTH_EXPIRES": 3600,
            "member_id": "member-single", "status": "L",
        })

        with patch.object(Bitrix24Account, "update_or_create_from_oauth_placement_data", return_value=(account, False)), \
             patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=bitrix_client):
            resp = self.client.post(
                "/api/getToken",
                data=payload,
                content_type="application/json",
                REMOTE_ADDR="2.2.2.2",
            )

        self.assertNotEqual(
            resp.status_code,
            HTTPStatus.TOO_MANY_REQUESTS,
            f"Single getToken request must not be rate-limited, got {resp.status_code}",
        )


# (д) Removed 2026-06-11: there is no @admin_required gate any more, so the
#     "role gate fires before the rate limit" scenario no longer exists. Role
#     behaviour is covered by tests_security_roles.NoServerRoleGateTest.


# ---------------------------------------------------------------------------
# (е) Лимит get_token срабатывает ДО дорогой авторизации (защита от DoS)
# ---------------------------------------------------------------------------

@override_settings(CACHES=RATELIMIT_CACHE)
class RateLimitGetTokenBeforeAuthTest(TestCase):
    """@rate_limit стоит ВЫШЕ @auth_required на get_token.

    Это означает:
    - Каждый запрос (даже с невалидными данными, когда auth_required вернёт 400/500)
      инкрементит счётчик rate_limit.
    - После N+1 запросов лимит срабатывает и возвращает 429 БЕЗ вызова
      update_or_create_from_oauth_placement_data (дорогой сетевой вызов к Bitrix).

    Тест мокает update_or_create_from_oauth_placement_data с счётчиком вызовов:
    - До лимита: мок вызывается (auth-логика работает).
    - После лимита (429): мок НЕ вызывается — rate_limit перехватил запрос раньше.
    """

    GET_TOKEN_LIMIT = 10

    def setUp(self):
        cache.clear()
        self.client = Client()

    def test_rate_limit_fires_before_oauth_on_invalid_requests(self):
        """Невалидные запросы к getToken инкрементят счётчик; на N+1-м — 429 без auth.

        Реальный DoS-сценарий: атакующий передаёт структурно корректный payload
        (OAuthPlacementData.from_dict проходит), но update_or_create_from_oauth_placement_data
        делает сетевой вызов к Bitrix и возвращает ошибку. До исправления: лимит никогда
        не инкрементился (auth_required стоял снаружи). После исправления: каждый запрос
        инкрементит счётчик, на N+1-м — 429 без вызова дорогой авторизации.
        """
        # Структурно корректный payload — OAuthPlacementData.from_dict пройдёт,
        # но update_or_create_from_oauth_placement_data будет замокан с ошибкой.
        dos_payload = json.dumps({
            "DOMAIN": "portal-dos.bitrix24.ru",
            "PROTOCOL": 1,
            "LANG": "ru",
            "APP_SID": "attacker-app-sid",
            "AUTH_ID": "fake-auth-token",
            "REFRESH_ID": "fake-refresh-token",
            "AUTH_EXPIRES": 3600,
            "member_id": "fake-member-id",
            "status": "L",
        })

        oauth_call_counter = {"count": 0}

        def counting_mock(oauth_data):
            oauth_call_counter["count"] += 1
            # Симулируем сбой сетевого вызова к Bitrix (app.info возвращает ошибку)
            from b24pysdk.error import BitrixValidationError
            raise BitrixValidationError("Bitrix app.info validation failed")

        with patch.object(
            Bitrix24Account,
            "update_or_create_from_oauth_placement_data",
            side_effect=counting_mock,
        ):
            # Отправляем ровно GET_TOKEN_LIMIT запросов — все должны доходить до auth
            # (rate_limit ещё не исчерпан) и получать 400 (ошибка от Bitrix)
            for i in range(self.GET_TOKEN_LIMIT):
                resp = self.client.post(
                    "/api/getToken",
                    data=dos_payload,
                    content_type="application/json",
                    REMOTE_ADDR="9.8.7.6",
                )
                self.assertNotEqual(
                    resp.status_code,
                    HTTPStatus.TOO_MANY_REQUESTS,
                    f"Request {i + 1}: rate_limit not yet exhausted, must not be 429 (got {resp.status_code})",
                )

            auth_calls_before_limit = oauth_call_counter["count"]
            self.assertGreater(
                auth_calls_before_limit, 0,
                "update_or_create_from_oauth_placement_data must be called before limit is exhausted",
            )

            # N+1-й запрос — rate_limit должен сработать раньше auth
            resp = self.client.post(
                "/api/getToken",
                data=dos_payload,
                content_type="application/json",
                REMOTE_ADDR="9.8.7.6",
            )
            self.assertEqual(
                resp.status_code,
                HTTPStatus.TOO_MANY_REQUESTS,
                f"Request {self.GET_TOKEN_LIMIT + 1} must be blocked by rate_limit with 429 (got {resp.status_code})",
            )
            body = resp.json()
            self.assertIn("error", body, "429 response must contain 'error' key")

            # Ключевая проверка: после 429 счётчик вызовов oauth НЕ вырос
            auth_calls_after_limit = oauth_call_counter["count"]
            self.assertEqual(
                auth_calls_after_limit,
                auth_calls_before_limit,
                f"update_or_create_from_oauth_placement_data must NOT be called after 429 "
                f"(before={auth_calls_before_limit}, after={auth_calls_after_limit})",
            )

    def test_rate_limit_counts_body_domain_without_collect_request_data(self):
        """rate_limit с key=ip_domain корректно извлекает domain из request.body
        (без @collect_request_data) — ключ кэша содержит domain, не пустую строку."""
        from main.utils.decorators.rate_limit import _get_domain_from_request
        from django.test import RequestFactory

        factory = RequestFactory()
        body = json.dumps({"DOMAIN": "portal-body.bitrix24.ru", "AUTH_ID": "x"}).encode()
        request = factory.post(
            "/api/getToken",
            data=body,
            content_type="application/json",
            REMOTE_ADDR="10.0.0.1",
        )
        # request.data не установлен (@collect_request_data не запускался)
        self.assertFalse(hasattr(request, "data"), "request.data must not be set yet")

        domain = _get_domain_from_request(request)
        self.assertEqual(
            domain,
            "portal-body.bitrix24.ru",
            f"_get_domain_from_request must extract domain from body, got {domain!r}",
        )

    def test_rate_limit_falls_back_to_empty_string_on_malformed_body(self):
        """_get_domain_from_request возвращает пустую строку при кривом теле (без исключения)."""
        from main.utils.decorators.rate_limit import _get_domain_from_request
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.post(
            "/api/getToken",
            data=b"not-json-at-all!!!",
            content_type="application/json",
            REMOTE_ADDR="10.0.0.2",
        )
        # Не должно бросать исключение, должна вернуться пустая строка
        domain = _get_domain_from_request(request)
        self.assertEqual(
            domain,
            "",
            f"_get_domain_from_request must return empty string on malformed body, got {domain!r}",
        )
