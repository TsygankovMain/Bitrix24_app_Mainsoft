"""Расширенное логирование ошибок в БД (31.08.2026).

Повод. Пользователи ловили 429 на открытии приложения, а в request_log за весь
месяц не было НИ ОДНОЙ записи со статусом 429 — потому что _should_skip_logging
отсекал префикс /api/getToken целиком, при любом статусе, а лимит с ключом по
IP+домену висит именно на нём. Одновременно system_log содержал одну строку за
месяц: туда писал только @log_errors, то есть исключительно необработанные
исключения вьюх, а все logger.warning/exception из сервисов уходили в stdout
контейнера и пропадали.

Здесь закреплены оба исправления: ошибка не пропускается логом никогда, и всё
уровня WARNING и выше оседает в system_log.
"""

import json
import logging

from django.test import RequestFactory, TestCase

from .middleware import RequestLoggingMiddleware
from .models import SystemLog
from .utils.db_log_handler import DatabaseLogHandler


class _Response:
    """Минимальная замена HttpResponse для _should_skip_logging."""

    def __init__(self, status_code):
        self.status_code = status_code


class SkipLoggingRulesTest(TestCase):
    def setUp(self):
        self.middleware = RequestLoggingMiddleware(lambda request: None)
        self.factory = RequestFactory()

    def _skip(self, method, path, status):
        request = getattr(self.factory, method.lower())(path)
        return self.middleware._should_skip_logging(request, _Response(status))

    def test_sensitive_paths_never_logged_even_on_error(self):
        """Запрет на запись тел getToken/install — жёсткий, статус его не снимает.

        Дублирует по смыслу SensitivePathNotLoggedTest, но с той стороны, где
        соблазн ослабить инвариант возникает: при расширении логирования
        напрашивалось «ошибки-то давайте писать». Нельзя — там OAuth-пейлоад,
        которого _redact_secrets не знает. Видимость по 429 даёт system_log
        (RateLimitLeavesTraceTest ниже), а не тела запросов.
        """
        for status in (400, 429, 500):
            with self.subTest(status=status):
                self.assertTrue(self._skip("POST", "/api/getToken", status))
                self.assertTrue(self._skip("POST", "/api/install", status))

    def test_errors_on_technical_paths_are_logged(self):
        """Раньше упавший healthcheck не оставлял следа вообще."""
        for method, path, status in [
            ("GET", "/api/health", 500),
            ("GET", "/healthz", 503),
            ("GET", "/api/logs/requests", 403),
        ]:
            with self.subTest(method=method, path=path, status=status):
                self.assertFalse(self._skip(method, path, status))

    def test_errors_on_regular_paths_are_logged(self):
        for method, path, status in [
            ("GET", "/api/timesheets", 403),
            ("POST", "/api/sync-timesheets", 409),
        ]:
            with self.subTest(method=method, path=path, status=status):
                self.assertFalse(self._skip(method, path, status))

    def test_successful_noise_is_still_skipped(self):
        """Мотив исходного пропуска — объём — сохранён."""
        self.assertTrue(self._skip("GET", "/api/health", 200))
        self.assertTrue(self._skip("GET", "/api/timesheets", 200))

    def test_successful_write_is_still_logged(self):
        """Успешные POST по обычным путям писались и раньше — не потеряли."""
        self.assertFalse(self._skip("POST", "/api/sync-timesheets", 200))


class RateLimitLeavesTraceTest(TestCase):
    """429 обязан оставлять след, даже когда тело запроса писать нельзя.

    Ради этого всё и затевалось: пользователи ловили 429 на открытии
    приложения, а в request_log за месяц не было ни одной такой записи, потому
    что /api/getToken исключён из него навсегда. Теперь отказ по лимиту пишет
    предупреждение через logging — и оно оседает в system_log.
    """

    def test_rejection_is_logged_with_scope_and_path(self):
        from django.http import HttpResponse

        from .utils.decorators.rate_limit import rate_limit

        @rate_limit("get_token", 1, 60, key="ip_domain")
        def view(request):
            return HttpResponse("ok")

        factory = RequestFactory()
        request = factory.post("/api/getToken", data="{}", content_type="application/json")

        self.assertEqual(view(request).status_code, 200)

        with self.assertLogs("main.utils.decorators.rate_limit", level="WARNING") as captured:
            self.assertEqual(view(request).status_code, 429)

        message = captured.output[0]
        self.assertIn("Rate limit hit", message)
        self.assertIn("/api/getToken", message)
        self.assertIn("get_token", message)

    def test_rejection_message_carries_no_request_body(self):
        """В сообщение не должно утечь тело — там прилетает OAuth-пейлоад."""
        from django.http import HttpResponse

        from .utils.decorators.rate_limit import rate_limit

        @rate_limit("get_token", 1, 60, key="ip_domain")
        def view(request):
            return HttpResponse("ok")

        factory = RequestFactory()
        secret_body = json.dumps({"domain": "example.bitrix24.ru", "AUTH_ID": "s3cr3t-token"})
        request = factory.post("/api/getToken", data=secret_body, content_type="application/json")

        view(request)
        with self.assertLogs("main.utils.decorators.rate_limit", level="WARNING") as captured:
            view(request)

        self.assertNotIn("s3cr3t-token", captured.output[0])


class DatabaseLogHandlerTest(TestCase):
    def setUp(self):
        self.handler = DatabaseLogHandler()
        self.logger = logging.getLogger("main.tests_error_logging")
        self.logger.handlers = [self.handler]
        self.logger.setLevel(logging.WARNING)
        self.logger.propagate = False
        SystemLog.objects.all().delete()

    def tearDown(self):
        self.logger.handlers = []

    def test_warning_lands_in_system_log(self):
        self.logger.warning("INN autofill failed for reference %s", "C1")

        row = SystemLog.objects.get()
        self.assertEqual(row.level, "WARNING")
        self.assertEqual(row.message, "INN autofill failed for reference C1")
        self.assertIn("main.tests_error_logging", row.module)
        self.assertIsNone(row.traceback)

    def test_exception_stores_traceback(self):
        try:
            raise ValueError("Битрикс не отдал реквизит")
        except ValueError:
            self.logger.exception("Timesheet sync failed")

        row = SystemLog.objects.get()
        self.assertEqual(row.level, "ERROR")
        self.assertIn("ValueError", row.traceback)
        self.assertIn("Битрикс не отдал реквизит", row.traceback)

    def test_info_is_below_threshold(self):
        """INFO не пишем: на нём приложение логирует каждую страницу синка."""
        self.logger.info("Fetching batch id>0")
        self.assertEqual(SystemLog.objects.count(), 0)

    def test_skip_db_suppresses_duplicate(self):
        """@log_errors кладёт свою строку сам — обработчик не должен дублировать."""
        self.logger.error("уже записано вручную", extra={"skip_db": True})
        self.assertEqual(SystemLog.objects.count(), 0)

    def test_long_message_is_truncated_not_dropped(self):
        self.logger.warning("x" * 20000)

        row = SystemLog.objects.get()
        self.assertLess(len(row.message), 20000)
        self.assertTrue(row.message.endswith("[Truncated]"))

    def test_module_fits_column(self):
        """SystemLog.module — CharField(max_length=100); длинное имя логгера
        не должно ронять запись на уровне БД."""
        long_logger = logging.getLogger("main." + "very_long_module_name" * 10)
        long_logger.handlers = [self.handler]
        long_logger.setLevel(logging.WARNING)
        long_logger.propagate = False
        try:
            long_logger.warning("сообщение")
        finally:
            long_logger.handlers = []

        row = SystemLog.objects.get()
        self.assertLessEqual(len(row.module), 100)

    def test_handler_never_breaks_the_caller(self):
        """Сбой записи не имеет права вылететь наружу: логирование не должно
        ломать запрос, ради которого оно случилось."""
        broken = DatabaseLogHandler()
        # raiseExceptions=False — как в проде; иначе handleError печатает в stderr.
        previous = logging.raiseExceptions
        logging.raiseExceptions = False
        self.logger.handlers = [broken]
        try:
            with self.settings(DATABASES={}):
                self.logger.warning("БД недоступна")
        finally:
            logging.raiseExceptions = previous
