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
