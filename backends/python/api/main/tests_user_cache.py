from unittest.mock import Mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from .bitrix_data_access import BitrixDataService
from .models import Bitrix24Account


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class FetchUsersCacheTest(TestCase):
    def setUp(self):
        cache.clear()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-2-4", is_master_account=True,
            domain_url="example.bitrix24.ru", status="active", application_version=1,
        )

    def _service(self):
        client = Mock()
        client._bitrix_token.call_method.return_value = {
            "result": [
                {"ID": "1", "NAME": "Иван", "LAST_NAME": "Петров"},
                {"ID": "2", "NAME": "Анна", "LAST_NAME": "Сидорова"},
            ]
        }
        return BitrixDataService(client, {}, self.account), client

    def test_second_fetch_same_ids_does_not_call_user_get(self):
        service, client = self._service()
        first = service.fetch_users(["1", "2"])
        second = service.fetch_users(["1", "2"])
        self.assertEqual(first, second)
        self.assertEqual(client._bitrix_token.call_method.call_count, 1)  # второй раз из кэша

    def test_different_ids_use_different_keys(self):
        service, client = self._service()
        service.fetch_users(["1", "2"])
        service.fetch_users(["1"])  # другой набор -> новый вызов
        self.assertEqual(client._bitrix_token.call_method.call_count, 2)

    def test_id_order_does_not_affect_key(self):
        service, client = self._service()
        service.fetch_users(["1", "2"])
        service.fetch_users(["2", "1"])  # та же множественность -> кэш
        self.assertEqual(client._bitrix_token.call_method.call_count, 1)

    def test_empty_result_not_cached(self):
        client = Mock()
        client._bitrix_token.call_method.return_value = {"result": []}
        service = BitrixDataService(client, {}, self.account)
        service.fetch_users(["99"])
        service.fetch_users(["99"])
        # пустой результат не кэшируется -> повторный вызов снова бьёт в Bitrix
        self.assertEqual(client._bitrix_token.call_method.call_count, 2)
