"""Тесты сервиса отправки часов в 1С.

Сеть подменяется: проверяется, что уезжает, что сохраняется в истории отправок
и как сервис ведёт себя, когда 1С недоступна или отказывает.
"""
from datetime import date, datetime, timezone

from django.test import TestCase

from .models import Bitrix24Account, OneCExportRun, ProjectCard, TimesheetItem
from .one_c_export_service import OneCExportService


class FakeTransport:
    """Подставной транспорт: помнит, что отправляли, и отвечает заготовкой."""

    def __init__(self, response=None, exception=None):
        self.response = response or {"ok": True, "принято": 0, "отклонено": 0,
                                     "документы": [], "строки": []}
        self.exception = exception
        self.sent = []

    def __call__(self, payload):
        self.sent.append(payload)
        if self.exception:
            raise self.exception
        return self.response


class OneCExportServiceTests(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-one-c-1",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        ProjectCard.objects.create(
            bitrix24_account=self.account, project_id="147", project_item_id="207",
            project_name="Восход", stage="in_progress",
            company_id="8047", company_name="ООО «Клиент»",
            our_legal_entity_id="15", our_legal_entity_name="ООО «Мейнсофт»",
        )
        TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=1, task_id="9483",
            employee_id="17", hours=3.5, is_billable=True, description="Правки",
            project_item_id="207", project_title="Восход",
            date_reflection=datetime(2026, 8, 14, 3, 0, tzinfo=timezone.utc),
        )
        # запись соседнего месяца — в пакет попадать не должна
        TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=2, task_id="9484",
            employee_id="17", hours=1.0, is_billable=True, description="Сентябрь",
            project_item_id="207", project_title="Восход",
            date_reflection=datetime(2026, 9, 2, 3, 0, tzinfo=timezone.utc),
        )

    def _service(self, transport):
        return OneCExportService(
            account=self.account,
            transport=transport,
            inn_maps=({"8047": "7719021450"}, {"15": "7325175133"}),
            employee_names={"17": "Иванов Пётр"},
        )

    def test_only_period_rows_are_sent(self):
        """Отправка за август не должна утаскивать сентябрьские часы."""
        transport = FakeTransport()

        self._service(transport).run(date(2026, 8, 1), date(2026, 8, 31))

        rows = transport.sent[0]["строки"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["идЗаписи"], "1")

    def test_successful_run_is_recorded(self):
        transport = FakeTransport({
            "ok": True, "принято": 1, "отклонено": 0,
            "документы": ["ЛУРВ-000000123"],
            "строки": [{"идЗаписи": "1", "статус": "принято", "причина": "", "текст": "ЛУРВ-000000123"}],
        })

        run = self._service(transport).run(date(2026, 8, 1), date(2026, 8, 31))

        self.assertEqual(run.status, OneCExportRun.STATUS_OK)
        self.assertEqual(run.accepted, 1)
        self.assertEqual(run.rejected, 0)
        self.assertEqual(run.documents, ["ЛУРВ-000000123"])
        self.assertEqual(OneCExportRun.objects.count(), 1)

    def test_partial_success_is_not_a_failure(self):
        """Одна отклонённая строка не отменяет остальные: это штатный исход."""
        transport = FakeTransport({
            "ok": True, "принято": 1, "отклонено": 1, "документы": ["ЛУРВ-1"],
            "строки": [
                {"идЗаписи": "1", "статус": "принято", "причина": "", "текст": "ЛУРВ-1"},
                {"идЗаписи": "9", "статус": "отклонено", "причина": "сотрудник_не_сопоставлен",
                 "текст": "id=42"},
            ],
        })

        run = self._service(transport).run(date(2026, 8, 1), date(2026, 8, 31))

        self.assertEqual(run.status, OneCExportRun.STATUS_PARTIAL)
        self.assertEqual(run.rejected, 1)
        self.assertEqual(run.rows[1]["reason"], "сотрудник_не_сопоставлен")

    def test_refusal_is_recorded_with_message(self):
        """501 «нет расширения» — отказ, и причина обязана сохраниться."""
        transport = FakeTransport({"ok": False, "сообщение": "В базе нет расширения IT_Lab"})

        run = self._service(transport).run(date(2026, 8, 1), date(2026, 8, 31))

        self.assertEqual(run.status, OneCExportRun.STATUS_FAILED)
        self.assertIn("IT_Lab", run.message)

    def test_network_failure_is_recorded_not_raised(self):
        """1С может быть недоступна. Это не 500 приложению, а запись в истории
        со статусом «не доставлено» — повтор потом безопасен."""
        transport = FakeTransport(exception=OSError("connection refused"))

        run = self._service(transport).run(date(2026, 8, 1), date(2026, 8, 31))

        self.assertEqual(run.status, OneCExportRun.STATUS_FAILED)
        self.assertIn("connection refused", run.message)
        self.assertEqual(run.accepted, 0)

    def test_each_run_has_its_own_sending_id(self):
        """Идентификатор отправки уходит в журнал обмена 1С и разбирает инциденты."""
        transport = FakeTransport()
        service = self._service(transport)

        first = service.run(date(2026, 8, 1), date(2026, 8, 31))
        second = service.run(date(2026, 8, 1), date(2026, 8, 31))

        self.assertNotEqual(first.sending_id, second.sending_id)
        self.assertEqual(transport.sent[0]["отправка"], first.sending_id)


class ConnectionSettingsTests(TestCase):
    """Откуда сервис берёт адрес приёмника и реквизиты."""

    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-one-c-conn",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )

    def test_portal_settings_win_over_environment(self):
        """Адрес 1С у каждого портала свой: настройка портала важнее .env."""
        service = OneCExportService(
            account=self.account,
            config={"one_c": {"inbox_url": "http://1c.local/hs/msbx24/v1/inbox/timesheet",
                              "token": "portal-token", "user": "admin", "password": ""}},
        )

        connection = service._connection()

        self.assertEqual(connection["url"], "http://1c.local/hs/msbx24/v1/inbox/timesheet")
        self.assertEqual(connection["token"], "portal-token")
        self.assertEqual(connection["user"], "admin")

    def test_environment_is_a_fallback(self):
        """Пока настройки портала не заполнены, работает конфигурация стенда."""
        with self.settings(ONE_C_INBOX_URL="http://stand/inbox", ONE_C_TOKEN="env-token",
                           ONE_C_USER="admin", ONE_C_PASSWORD=""):
            service = OneCExportService(account=self.account, config={})

            connection = service._connection()

        self.assertEqual(connection["url"], "http://stand/inbox")
        self.assertEqual(connection["token"], "env-token")

    def test_empty_settings_produce_readable_failure(self):
        """Без адреса отправка не падает 500, а объясняет, чего не хватает."""
        with self.settings(ONE_C_INBOX_URL="", ONE_C_TOKEN="", ONE_C_USER="", ONE_C_PASSWORD=""):
            service = OneCExportService(account=self.account, config={})
            run = service.run(date(2026, 8, 1), date(2026, 8, 31))

        self.assertEqual(run.status, OneCExportRun.STATUS_FAILED)
        self.assertIn("адрес приёмника", run.message.lower())
