"""Тесты источников справочников: пользовательские пути не обходят портал."""
from django.core.cache import cache
from django.test import TestCase

from .models import Bitrix24Account
from .project_board_service import ProjectCardService


class _FakeClient:
    def __init__(self, responses=None):
        self._responses = dict(responses or {})
        self.calls = []
        self._bitrix_token = self

    def call_method(self, method, params=None):
        self.calls.append((method, params or {}))
        value = self._responses.get(method, {"result": []})
        if isinstance(value, Exception):
            raise value
        return value

    def methods_called(self):
        return [m for m, _ in self.calls]


class LegalEntitiesTest(TestCase):
    def setUp(self):
        cache.clear()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-refs-1",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )

    def test_uses_server_side_filter_not_full_scan(self):
        client = _FakeClient({
            "crm.company.list": {"result": [{"ID": "7", "TITLE": "ООО Мейнсофт"}]},
        })
        entities = ProjectCardService(client, self.account).get_legal_entities()

        self.assertEqual([e["id"] for e in entities], ["7"])
        # Ровно один вызов, без постраничного обхода и без crm.requisite.list.
        self.assertEqual(client.methods_called(), ["crm.company.list"])
        _, params = client.calls[0]
        self.assertEqual(params["filter"]["IS_MY_COMPANY"], "Y")

    def test_bitrix_failure_falls_back_to_project_cards(self):
        client = _FakeClient({"crm.company.list": RuntimeError("нет прав")})
        entities = ProjectCardService(client, self.account).get_legal_entities()

        self.assertEqual(entities, [])
