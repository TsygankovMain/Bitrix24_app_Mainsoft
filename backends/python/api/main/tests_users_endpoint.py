"""GET /api/users — пагинированный список сотрудников из локальной БД."""
from django.test import Client, TestCase

from .models import Bitrix24Account, PortalUser


class GetUsersEndpointTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-users-ep-1",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        self.token = self.account.create_jwt_token()

    def _get(self, query=""):
        return Client().get(f"/api/users{query}", HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def test_returns_paginated_users_from_db(self):
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="1", name="Иван", last_name="Абрамов", active=True)
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="2", name="Анна", last_name="Багрова", active=False)

        response = self._get()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual([item["id"] for item in data["items"]], ["1", "2"])  # order_by last_name
        self.assertIn("has_next", data)
        self.assertFalse(data["has_next"])

    def test_active_only_filter(self):
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="1", name="Иван", last_name="Абрамов", active=True)
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="2", name="Анна", last_name="Багрова", active=False)

        response = self._get("?active_only=1")

        data = response.json()
        self.assertEqual([item["id"] for item in data["items"]], ["1"])

    def test_pagination_limit_and_page_params(self):
        for i in range(1, 4):
            PortalUser.objects.create(bitrix24_account=self.account, bitrix_id=str(i), name=f"U{i}", last_name="L", active=True)

        response = self._get("?limit=2&page=2")
        data = response.json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["page"], 2)
        self.assertEqual(data["pages"], 2)

    def test_requires_auth(self):
        # Без Authorization заголовка auth_required уходит в OAuth-ветку и падает
        # на пустом теле запроса -> 400 (см. QueryStabilityTest для /api/configuration/,
        # тот же паттерн для GET-эндпоинтов без тела).
        response = Client().get("/api/users")
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_does_not_leak_other_tenant_users(self):
        other = Bitrix24Account.objects.create(
            b24_user_id=2, is_b24_user_admin=True, member_id="m-users-ep-2",
            is_master_account=True, domain_url="other.bitrix24.ru",
            status="active", application_version=1,
        )
        PortalUser.objects.create(bitrix24_account=other, bitrix_id="1", name="Чужой", last_name="Юзер", active=True)

        response = self._get()
        data = response.json()
        self.assertEqual(data["total"], 0)

    # --- Ревью Задачи 5, Important #1: `limit` из query string шёл прямо в
    # Paginator(queryset, page_size) без валидации -> 500 на limit=0
    # ("division by zero"), limit=-1 ("That page number is less than 1",
    # вводит в заблуждение — жалуется на page, хотя проблема в limit),
    # limit=abc ("invalid literal for int()"). Клиент не должен получать
    # 500 и сырой текст Python-исключения на банальной ошибке ввода.

    def test_limit_zero_is_clamped_to_minimum_not_500(self):
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="1", name="Иван", last_name="Абрамов", active=True)
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="2", name="Анна", last_name="Багрова", active=True)

        response = self._get("?limit=0")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["items"]), 1)  # limit=0 -> клэмп к минимуму 1
        self.assertEqual(data["pages"], 2)

    def test_limit_negative_is_clamped_to_minimum_not_500(self):
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="1", name="Иван", last_name="Абрамов", active=True)
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="2", name="Анна", last_name="Багрова", active=True)

        response = self._get("?limit=-1")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["pages"], 2)

    def test_limit_non_numeric_falls_back_to_default_not_500(self):
        for i in range(1, 4):
            PortalUser.objects.create(bitrix24_account=self.account, bitrix_id=str(i), name=f"U{i}", last_name="L", active=True)

        response = self._get("?limit=abc")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["items"]), 3)  # дефолт 50 -> все 3 влезают на одну страницу
        self.assertEqual(data["pages"], 1)

    def test_limit_above_upper_bound_is_clamped(self):
        PortalUser.objects.bulk_create([
            PortalUser(bitrix24_account=self.account, bitrix_id=str(i), name=f"U{i}", last_name="L", active=True)
            for i in range(1, 202)
        ])

        response = self._get("?limit=100000")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["items"]), 200)  # верхний предел — не весь справочник в одном ответе
        self.assertEqual(data["pages"], 2)

    # --- Ревью Задачи 5, Important #2: order_by("last_name", "name") без
    # тайбрейкера не гарантирует стабильный порядок между запросами разных
    # страниц при совпадении last_name/name -> риск дублей/пропусков при
    # постраничном обходе с фронта (Задача 6).

    def test_pagination_stable_across_pages_for_duplicate_names(self):
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="30", name="Иван", last_name="Петров", active=True)
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="10", name="Иван", last_name="Петров", active=True)
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="20", name="Иван", last_name="Петров", active=True)

        ids_in_page_order = [
            self._get(f"?limit=1&page={page}").json()["items"][0]["id"]
            for page in (1, 2, 3)
        ]

        # Тайбрейкер bitrix_id (уникален в пределах тенанта) гарантирует
        # детерминированный возрастающий порядок при равенстве last_name/name
        # -> обход постранично не теряет и не дублирует записи.
        self.assertEqual(ids_in_page_order, ["10", "20", "30"])
