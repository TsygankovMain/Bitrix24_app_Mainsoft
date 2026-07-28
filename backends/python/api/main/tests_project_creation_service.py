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
        })
        result = self.service(client).ensure_company(None, "АО Ромашка")

        # Непонятный ответ — не создаём, возвращаем ошибку
        self.assertEqual(result.status, "error")
        self.assertIn("неожиданном формате", result.error)
        self.assertNotIn("crm.company.add", client.methods_called())

    def test_malformed_list_response_strings_instead_of_dicts(self):
        """crm.company.list вернул result как список строк."""
        client = _FakeClient({
            "crm.company.list": {"result": ["15", "16"]},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка")

        # Список строк не может быть распарсен, ошибка разбора
        self.assertEqual(result.status, "error")
        self.assertIn("неожиданном формате", result.error)
        self.assertNotIn("crm.company.add", client.methods_called())

    def test_empty_list_result_creates_company(self):
        """crm.company.list вернул пустой список — это нормально, создаём."""
        client = _FakeClient({
            "crm.company.list": {"result": []},
            "crm.company.add": {"result": 77},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка")

        # Пустой результат означает ноль совпадений, создаём компанию
        self.assertEqual(result.status, "created")
        self.assertEqual(result.id, "77")

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

    def test_created_id_scalar_form(self):
        """_extract_created_id: скалярный ID как число."""
        client = _FakeClient({
            "crm.company.list": {"result": []},
            "crm.company.add": {"result": 77},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка")

        self.assertEqual(result.status, "created")
        self.assertEqual(result.id, "77")

    def test_created_id_item_form(self):
        """_extract_created_id: ID в форме crm.item.add — вложенный объект."""
        client = _FakeClient({
            "crm.company.list": {"result": []},
            "crm.company.add": {"result": {"item": {"id": 501}}},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка")

        self.assertEqual(result.status, "created")
        self.assertEqual(result.id, "501")

    def test_created_id_nested_direct_form(self):
        """_extract_created_id: ID в форме с прямым вложением {"id": 501}."""
        client = _FakeClient({
            "crm.company.list": {"result": []},
            "crm.company.add": {"result": {"id": 501}},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка")

        self.assertEqual(result.status, "created")
        self.assertEqual(result.id, "501")

    def test_mixed_list_with_garbage_is_error(self):
        """crm.company.list вернул смешанный список — некоторые элементы не словари."""
        client = _FakeClient({
            "crm.company.list": {"result": [{"ID": "15", "TITLE": "АО Ромашка"}, "garbage"]},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка")

        # Примесь не-словарей — ошибка разбора, не создаём (мусор может быть испорченным совпадением)
        self.assertEqual(result.status, "error")
        self.assertIn("неожиданном формате", result.error)
        self.assertNotIn("crm.company.add", client.methods_called())


class EnsureGroupTest(_ServiceTestCase):
    def test_single_match_is_reused(self):
        client = _FakeClient({
            "sonet_group.get": {"result": [{"ID": "31", "NAME": "Портал АО Ромашка"}]},
        })
        result = self.service(client).ensure_group("Портал АО Ромашка")

        self.assertEqual(result.status, "found")
        self.assertEqual(result.id, "31")
        self.assertNotIn("sonet_group.create", client.methods_called())

    def test_no_match_creates_project_group(self):
        client = _FakeClient({
            "sonet_group.get": {"result": []},
            "sonet_group.create": {"result": 44},
        })
        result = self.service(client).ensure_group("Портал АО Ромашка")

        self.assertEqual(result.status, "created")
        self.assertEqual(result.id, "44")
        method, params = client.calls[-1]
        self.assertEqual(method, "sonet_group.create")
        self.assertEqual(params["NAME"], "Портал АО Ромашка")
        self.assertEqual(params["PROJECT"], "Y")
        # Владельца не назначаем: им становится создатель — текущий сотрудник.
        self.assertNotIn("OWNER_ID", params)

    def test_two_matches_return_ambiguous_and_create_nothing(self):
        client = _FakeClient({
            "sonet_group.get": {"result": [
                {"ID": "31", "NAME": "Портал АО Ромашка"},
                {"ID": "32", "NAME": "Портал АО Ромашка"},
            ]},
        })
        result = self.service(client).ensure_group("Портал АО Ромашка")

        self.assertEqual(result.status, "ambiguous")
        self.assertIsNone(result.id)
        self.assertEqual(sorted(c["id"] for c in result.candidates), ["31", "32"])
        self.assertNotIn("sonet_group.create", client.methods_called())

    def test_search_matches_by_exact_name_only(self):
        """sonet_group.get фильтрует по подстроке — одноимённый префикс не должен
        считаться совпадением, иначе привяжемся к чужому проекту."""
        client = _FakeClient({
            "sonet_group.get": {"result": [{"ID": "31", "NAME": "Портал АО Ромашка 2"}]},
            "sonet_group.create": {"result": 44},
        })
        result = self.service(client).ensure_group("Портал АО Ромашка")

        self.assertEqual(result.status, "created")
        self.assertEqual(result.id, "44")

    def test_bitrix_failure_becomes_error_status(self):
        client = _FakeClient({"sonet_group.get": RuntimeError("нет прав")})
        result = self.service(client).ensure_group("Портал АО Ромашка")

        self.assertEqual(result.status, "error")
        self.assertIn("нет прав", result.error)

    def test_blank_name_is_an_error(self):
        client = _FakeClient()
        result = self.service(client).ensure_group("  ")

        self.assertEqual(result.status, "error")
        self.assertEqual(client.methods_called(), [])

    def test_unreadable_response_does_not_create_group(self):
        """Ответ непонятного вида — не повод создавать: если совпадение там
        было, в Задачах навсегда останется дубль проекта."""
        client = _FakeClient({"sonet_group.get": {"result": {"unexpected": "shape"}}})
        result = self.service(client).ensure_group("Портал АО Ромашка")

        self.assertEqual(result.status, "error")
        self.assertNotIn("sonet_group.create", client.methods_called())

    def test_empty_result_list_still_creates(self):
        """Пустой список — честный ответ «не нашлось», а не ошибка разбора."""
        client = _FakeClient({
            "sonet_group.get": {"result": []},
            "sonet_group.create": {"result": 44},
        })
        result = self.service(client).ensure_group("Портал АО Ромашка")

        self.assertEqual(result.status, "created")
