"""Тесты оркестратора создания связки «компания + группа + карточка».

Паттерн _FakeClient — как в tests_user_sync_service.py: подменяем call_method и
записываем вызовы, чтобы проверять идемпотентность без сети.
"""
from django.test import TestCase

from .models import Bitrix24Account
from .project_creation_service import ProjectCreationService


class _FakeClient:
    """Двойник Client: отдаёт ответы по имени метода, пишет журнал вызовов.

    responses — {метод: ответ} либо {метод: [ответ1, ответ2, ...]} когда метод
    вызывается несколько раз и ответы должны отличаться.
    """

    def __init__(self, responses=None):
        self._responses = dict(responses or {})
        self.calls = []
        self._bitrix_token = self

    def call_method(self, method, params=None):
        self.calls.append((method, params or {}))
        value = self._responses.get(method, {"result": []})
        if isinstance(value, list):
            if not value:
                return {"result": []}
            return value.pop(0) if len(value) > 1 else value[0]
        if isinstance(value, Exception):
            raise value
        return value

    def methods_called(self):
        return [method for method, _ in self.calls]


class _ServiceTestCase(TestCase):
    def setUp(self):
        # Очищаем кеш для изоляции тестов. Каждый тест работает с новым аккаунтом
        # и не должен видеть результаты других тестов.
        from django.core.cache import cache
        cache.clear()

        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-create-1",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )

    def service(self, client):
        return ProjectCreationService(client, self.account)


class EnsureCompanyTest(_ServiceTestCase):
    def test_explicit_id_is_used_without_search(self):
        client = _FakeClient()
        result = self.service(client).ensure_company("15", "АО Ромашка")

        self.assertEqual(result.status, "found")
        self.assertEqual(result.id, "15")
        self.assertEqual(client.methods_called(), [])

    def test_single_match_is_reused_not_recreated(self):
        client = _FakeClient({
            "crm.company.list": {"result": [{"ID": "15", "TITLE": "АО Ромашка"}]},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка")

        self.assertEqual(result.status, "found")
        self.assertEqual(result.id, "15")
        self.assertNotIn("crm.company.add", client.methods_called())

    def test_no_match_creates_company(self):
        client = _FakeClient({
            "crm.company.list": {"result": []},
            "crm.company.add": {"result": 77},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка")

        self.assertEqual(result.status, "created")
        self.assertEqual(result.id, "77")
        method, params = client.calls[-1]
        self.assertEqual(method, "crm.company.add")
        self.assertEqual(params["fields"]["TITLE"], "АО Ромашка")

    def test_two_matches_return_ambiguous_and_create_nothing(self):
        client = _FakeClient({
            "crm.company.list": {"result": [
                {"ID": "15", "TITLE": "АО Ромашка"},
                {"ID": "16", "TITLE": "АО Ромашка"},
            ]},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка")

        self.assertEqual(result.status, "ambiguous")
        self.assertIsNone(result.id)
        self.assertEqual(
            sorted(c["id"] for c in result.candidates), ["15", "16"]
        )
        self.assertNotIn("crm.company.add", client.methods_called())

    def test_bitrix_failure_becomes_error_status_not_exception(self):
        client = _FakeClient({"crm.company.list": RuntimeError("портал недоступен")})
        result = self.service(client).ensure_company(None, "АО Ромашка")

        self.assertEqual(result.status, "error")
        self.assertIn("портал недоступен", result.error)

    def test_blank_input_is_an_error(self):
        client = _FakeClient()
        result = self.service(client).ensure_company(None, "")

        self.assertEqual(result.status, "error")
        self.assertEqual(client.methods_called(), [])

    def test_search_uses_exact_match_filter(self):
        """Проверяем что поиск использует точное совпадение =TITLE."""
        client = _FakeClient({
            "crm.company.list": {"result": [{"ID": "15", "TITLE": "АО Ромашка"}]},
        })
        self.service(client).ensure_company(None, "АО Ромашка")

        # Первый вызов должен быть crm.company.list с оператором =TITLE
        method, params = client.calls[0]
        self.assertEqual(method, "crm.company.list")
        self.assertIn("=TITLE", params["filter"])
        self.assertEqual(params["filter"]["=TITLE"], "АО Ромашка")

    def test_step_result_as_dict_method(self):
        """Проверяем что as_dict() возвращает все поля."""
        client = _FakeClient({
            "crm.company.list": {"result": [{"ID": "15", "TITLE": "АО Ромашка"}]},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка")

        result_dict = result.as_dict()
        self.assertIsInstance(result_dict, dict)
        self.assertEqual(result_dict["status"], "found")
        self.assertEqual(result_dict["id"], "15")
        self.assertEqual(result_dict["name"], "АО Ромашка")
        self.assertEqual(result_dict["candidates"], [])
        self.assertIsNone(result_dict["error"])

    def test_malformed_list_response_dict_instead_of_list(self):
        """crm.company.list вернул result как словарь вместо списка."""
        client = _FakeClient({
            "crm.company.list": {"result": {"unexpected": "shape"}},
            "crm.company.add": {"result": 77},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка")

        # Должны обработать как пустой результат, попытаться создать
        self.assertEqual(result.status, "created")

    def test_malformed_list_response_strings_instead_of_dicts(self):
        """crm.company.list вернул result как список строк."""
        client = _FakeClient({
            "crm.company.list": {"result": ["15", "16"]},
            "crm.company.add": {"result": 77},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка")

        # Список строк не может быть распарсен, должны создать
        self.assertEqual(result.status, "created")

    def test_malformed_add_response_none(self):
        """crm.company.add вернул None вместо словаря."""
        client = _FakeClient({
            "crm.company.list": {"result": []},
            "crm.company.add": None,
        })
        result = self.service(client).ensure_company(None, "АО Ромашка")

        self.assertEqual(result.status, "error")
        self.assertIn("валидный идентификатор", result.error)

    def test_malformed_add_response_result_is_dict(self):
        """crm.company.add вернул result как словарь вместо скалярного ID."""
        client = _FakeClient({
            "crm.company.list": {"result": []},
            "crm.company.add": {"result": {"ID": 77}},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка")

        self.assertEqual(result.status, "error")
        self.assertIn("валидный идентификатор", result.error)

    def test_add_throws_exception(self):
        """crm.company.add бросает исключение."""
        client = _FakeClient({
            "crm.company.list": {"result": []},
            "crm.company.add": RuntimeError("Ошибка при создании компании"),
        })
        result = self.service(client).ensure_company(None, "АО Ромашка")

        self.assertEqual(result.status, "error")
        self.assertIn("Ошибка при создании компании", result.error)

    def test_add_returns_empty_id(self):
        """crm.company.add вернул пустой result."""
        client = _FakeClient({
            "crm.company.list": {"result": []},
            "crm.company.add": {"result": ""},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка")

        self.assertEqual(result.status, "error")
        self.assertIn("валидный идентификатор", result.error)
