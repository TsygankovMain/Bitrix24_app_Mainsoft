"""GET /api/timesheets — пагинированный список трудозатрат из локальной БД."""
from django.test import Client, TestCase
from django.utils import timezone

from .models import Bitrix24Account, SystemLog, TimesheetItem


class TimesheetListEndpointTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-timesheets-ep-1",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        self.token = self.account.create_jwt_token()

    def _get(self, query=""):
        return Client().get(f"/api/timesheets{query}", HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def _timesheets(self, count, *, first_bitrix_id=1):
        TimesheetItem.objects.bulk_create([
            TimesheetItem(
                bitrix24_account=self.account, bitrix_id=i, task_id=str(i),
                employee_id="1", hours=1.0, date_reflection=timezone.now(),
            )
            for i in range(first_bitrix_id, first_bitrix_id + count)
        ])

    def test_returns_paginated_timesheets_from_db(self):
        self._timesheets(2)

        response = self._get()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(len(data["items"]), 2)
        self.assertFalse(data["has_next"])

    def test_pagination_limit_and_page_params(self):
        self._timesheets(3)

        response = self._get("?limit=2&page=2")

        data = response.json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["page"], 2)
        self.assertEqual(data["pages"], 2)

    def test_does_not_leak_other_tenant_timesheets(self):
        other = Bitrix24Account.objects.create(
            b24_user_id=2, is_b24_user_admin=True, member_id="m-timesheets-ep-2",
            is_master_account=True, domain_url="other.bitrix24.ru",
            status="active", application_version=1,
        )
        TimesheetItem.objects.create(
            bitrix24_account=other, bitrix_id=1, task_id="1",
            employee_id="1", hours=1.0, date_reflection=timezone.now(),
        )

        data = self._get().json()

        self.assertEqual(data["total"], 0)

    # --- `limit` из query string шёл прямо в Paginator(queryset, page_size)
    # без валидации -> 500 на limit=0 ("division by zero"), limit=-1
    # ("That page number is less than 1" — вводит в заблуждение, жалуется на
    # page, хотя проблема в limit), limit=abc ("invalid literal for int()").
    # Клиент не должен получать 500 и сырой текст Python-исключения на
    # банальной ошибке ввода.

    def test_limit_zero_is_clamped_to_minimum_not_500(self):
        self._timesheets(2)

        response = self._get("?limit=0")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["items"]), 1)  # limit=0 -> клэмп к минимуму 1
        self.assertEqual(data["pages"], 2)

    def test_limit_negative_is_clamped_to_minimum_not_500(self):
        self._timesheets(2)

        response = self._get("?limit=-1")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["pages"], 2)

    def test_limit_non_numeric_falls_back_to_default_not_500(self):
        self._timesheets(3)

        response = self._get("?limit=abc")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["items"]), 3)  # дефолт 50 -> все 3 влезают на одну страницу
        self.assertEqual(data["pages"], 1)

    def test_limit_above_upper_bound_is_clamped(self):
        self._timesheets(201)

        response = self._get("?limit=100000")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["items"]), 200)  # верхний предел — не вся таблица в одном ответе
        self.assertEqual(data["pages"], 2)

    def test_invalid_limit_does_not_write_error_to_system_log(self):
        # log_errors ловит исключение вьюхи и пишет SystemLog(level="ERROR")
        # с полным traceback: каждый запрос с кривым limit давал шум в
        # мониторинге. Валидный ввод такого следа оставлять не должен.
        self._timesheets(2)

        for query in ("?limit=0", "?limit=-1", "?limit=abc", "?limit=100000"):
            with self.subTest(query=query):
                self._get(query)

        self.assertEqual(SystemLog.objects.filter(level="ERROR").count(), 0)
