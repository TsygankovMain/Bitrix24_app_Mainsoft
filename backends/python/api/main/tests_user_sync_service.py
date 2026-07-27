"""Тесты UserSyncService: полный постраничный синк user.get -> upsert PortalUser.

Паттерн _FakeClient — как в tests_sync_threshold.py.
"""
from django.test import TestCase

from .models import Bitrix24Account, PortalUser
from .user_sync_service import UserSyncService


class _FakeClient:
    """Минимальный двойник Client: возвращает заранее заданные страницы по порядку."""

    def __init__(self, pages):
        self._pages = list(pages)
        self._calls = 0
        self._bitrix_token = self

    def call_method(self, method, params):
        if self._calls < len(self._pages):
            resp = self._pages[self._calls]
        else:
            resp = {"result": []}
        self._calls += 1
        return resp


class UserSyncServiceTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-usersync-1",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )

    def test_sync_creates_new_users_including_inactive(self):
        pages = [
            {
                "result": [
                    {"ID": "1", "NAME": "Иван", "LAST_NAME": "Петров", "ACTIVE": "Y"},
                    {"ID": "2", "NAME": "Анна", "LAST_NAME": "Сидорова", "ACTIVE": "N"},
                ],
            },
        ]
        service = UserSyncService(_FakeClient(pages), self.account)
        result = service.sync()

        self.assertEqual(result, {"synced": 2, "created": 2, "updated": 0})
        rows = {row.bitrix_id: row for row in PortalUser.objects.filter(bitrix24_account=self.account)}
        self.assertEqual(rows["1"].name, "Иван")
        self.assertTrue(rows["1"].active)
        self.assertFalse(rows["2"].active)  # неактивный тоже сохранён (для истории отчётов)

    def test_sync_updates_existing_user_on_name_change(self):
        PortalUser.objects.create(
            bitrix24_account=self.account, bitrix_id="1", name="Old", last_name="Name", active=True,
        )
        pages = [{"result": [{"ID": "1", "NAME": "New", "LAST_NAME": "Name", "ACTIVE": "Y"}]}]
        service = UserSyncService(_FakeClient(pages), self.account)
        result = service.sync()

        self.assertEqual(result, {"synced": 1, "created": 0, "updated": 1})
        row = PortalUser.objects.get(bitrix24_account=self.account, bitrix_id="1")
        self.assertEqual(row.name, "New")

    def test_sync_paginates_using_next_cursor(self):
        page1_users = [
            {"ID": str(i), "NAME": f"U{i}", "LAST_NAME": "L", "ACTIVE": "Y"} for i in range(1, 51)
        ]
        pages = [
            {"result": page1_users, "next": 50, "total": 51},
            {"result": [{"ID": "51", "NAME": "U51", "LAST_NAME": "L", "ACTIVE": "Y"}], "total": 51},
        ]
        service = UserSyncService(_FakeClient(pages), self.account)
        result = service.sync()
        self.assertEqual(result["synced"], 51)
        self.assertTrue(PortalUser.objects.filter(bitrix24_account=self.account, bitrix_id="51").exists())

    def test_sync_does_not_delete_users_missing_from_response(self):
        PortalUser.objects.create(
            bitrix24_account=self.account, bitrix_id="99", name="Stale", last_name="User", active=True,
        )
        pages = [{"result": [{"ID": "1", "NAME": "Иван", "LAST_NAME": "Петров", "ACTIVE": "Y"}]}]
        service = UserSyncService(_FakeClient(pages), self.account)
        service.sync()
        # upsert-only: юзер, не вернувшийся в этом ответе, НЕ удаляется (Global Constraint).
        self.assertTrue(PortalUser.objects.filter(bitrix24_account=self.account, bitrix_id="99").exists())

    def test_sync_scoped_to_account_does_not_touch_other_portal(self):
        other = Bitrix24Account.objects.create(
            b24_user_id=2, is_b24_user_admin=True, member_id="m-usersync-2",
            is_master_account=True, domain_url="other.bitrix24.ru",
            status="active", application_version=1,
        )
        PortalUser.objects.create(bitrix24_account=other, bitrix_id="1", name="Чужой", last_name="Юзер", active=True)

        pages = [{"result": [{"ID": "1", "NAME": "Свой", "LAST_NAME": "Юзер", "ACTIVE": "Y"}]}]
        service = UserSyncService(_FakeClient(pages), self.account)
        service.sync()

        other_row = PortalUser.objects.get(bitrix24_account=other, bitrix_id="1")
        self.assertEqual(other_row.name, "Чужой")  # не тронут синком другого аккаунта
