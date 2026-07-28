"""Тесты оркестратора создания связки «компания + группа + карточка».

Паттерн _FakeClient — как в tests_user_sync_service.py: подменяем call_method и
записываем вызовы, чтобы проверять идемпотентность без сети.
"""
from datetime import date

from django.test import TestCase

from .models import Bitrix24Account, ProjectCard
from .project_creation_defaults import resolve_project_fields
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

    def test_create_throws_exception(self):
        """sonet_group.create бросает исключение — по образцу
        EnsureCompanyTest.test_add_throws_exception (пробел отмечен ревью
        задачи 3: у этого шага не было теста на отказ создания)."""
        client = _FakeClient({
            "sonet_group.get": {"result": []},
            "sonet_group.create": RuntimeError("Ошибка при создании группы"),
        })
        result = self.service(client).ensure_group("Портал АО Ромашка")

        self.assertEqual(result.status, "error")
        self.assertIn("Ошибка при создании группы", result.error)

    def test_create_returns_empty_id(self):
        """sonet_group.create ответил без пригодного идентификатора — по
        образцу EnsureCompanyTest.test_add_returns_empty_id."""
        client = _FakeClient({
            "sonet_group.get": {"result": []},
            "sonet_group.create": {"result": ""},
        })
        result = self.service(client).ensure_group("Портал АО Ромашка")

        self.assertEqual(result.status, "error")
        self.assertIn("идентификатор", result.error)


def _resolved_fields(**overrides):
    form = {
        "project_name": "Портал АО Ромашка",
        "company_id": "15",
        "company_name": "АО Ромашка",
        "project_hours_budget": "10",
    }
    form.update(overrides)
    fields, _ = resolve_project_fields(
        form,
        config={"hourly_rate": 1500},
        current_user_id="42",
        current_user_name="Петров Иван",
        today=date(2026, 7, 28),
        legal_entities=[{"id": "7", "name": "ООО Мейнсофт"}],
        stage_options=[{"id": "DT180_7:NEW", "title": "Новый"}],
    )
    return fields


_MAPPING = {
    "title": "title",
    "bitrix_group_id": "ufCrm7Group",
    "stage_id": "stageId",
    "company_id": "ufCrm7Company",
    "our_legal_entity_id": "ufCrm7Legal",
    "curator_id": "ufCrm7Curator",
    "hourly_rate": "ufCrm7Rate",
    "project_hours_budget": "ufCrm7Hours",
    "start_date": "ufCrm7Start",
    "finish_date": "ufCrm7Finish",
    "is_support": "ufCrm7Support",
}


class BuildCardFieldsTest(_ServiceTestCase):
    def test_maps_every_configured_field(self):
        service = self.service(_FakeClient())
        built = service.build_card_fields(_resolved_fields(), "44", _MAPPING)

        self.assertEqual(built["title"], "Портал АО Ромашка")
        self.assertEqual(built["ufCrm7Group"], 44)
        self.assertEqual(built["stageId"], "DT180_7:NEW")
        self.assertEqual(built["ufCrm7Company"], 15)
        self.assertEqual(built["ufCrm7Legal"], 7)
        self.assertEqual(built["ufCrm7Curator"], 42)
        self.assertEqual(built["ufCrm7Rate"], 1500.0)
        self.assertEqual(built["ufCrm7Hours"], 10.0)
        self.assertEqual(built["ufCrm7Start"], "2026-07-28")
        self.assertEqual(built["ufCrm7Finish"], "2027-07-28")
        self.assertEqual(built["ufCrm7Support"], "N")

    def test_unmapped_keys_are_skipped_not_guessed(self):
        service = self.service(_FakeClient())
        built = service.build_card_fields(_resolved_fields(), "44", {"title": "title"})

        self.assertEqual(list(built.keys()), ["title"])

    def test_empty_hours_budget_is_not_written_as_zero(self):
        service = self.service(_FakeClient())
        fields = _resolved_fields(project_hours_budget="")
        built = service.build_card_fields(fields, "44", _MAPPING)

        self.assertNotIn("ufCrm7Hours", built)


class EnsureCardTest(_ServiceTestCase):
    def test_existing_card_for_group_is_reused(self):
        client = _FakeClient({"crm.item.list": {"result": {"items": [{"id": 900}]}}})
        result = self.service(client).ensure_card(
            _resolved_fields(), "44", entity_type_id=180, mapping=_MAPPING
        )

        self.assertEqual(result.status, "found")
        self.assertEqual(result.id, "900")
        self.assertNotIn("crm.item.add", client.methods_called())

    def test_no_card_creates_one(self):
        client = _FakeClient({
            "crm.item.list": {"result": {"items": []}},
            "crm.item.add": {"result": {"item": {"id": 901}}},
        })
        result = self.service(client).ensure_card(
            _resolved_fields(), "44", entity_type_id=180, mapping=_MAPPING
        )

        self.assertEqual(result.status, "created")
        self.assertEqual(result.id, "901")

    def test_unconfigured_smart_process_is_skipped_not_crashed(self):
        client = _FakeClient()
        result = self.service(client).ensure_card(
            _resolved_fields(), "44", entity_type_id=0, mapping=_MAPPING
        )

        self.assertEqual(result.status, "skipped")
        self.assertEqual(client.methods_called(), [])

    def test_bitrix_failure_becomes_error_status(self):
        client = _FakeClient({
            "crm.item.list": {"result": {"items": []}},
            "crm.item.add": RuntimeError("поле не найдено"),
        })
        result = self.service(client).ensure_card(
            _resolved_fields(), "44", entity_type_id=180, mapping=_MAPPING
        )

        self.assertEqual(result.status, "error")
        self.assertIn("поле не найдено", result.error)

    def test_created_card_without_id_becomes_error(self):
        """crm.item.add ответил без пригодного идентификатора — тот же класс
        тестов, что и test_create_returns_empty_id у EnsureGroupTest
        (пробел, отмеченный ревью задачи 3, закрывается по образцу
        EnsureCompanyTest и для этого шага). Разбор ответа — только через
        _extract_created_id, вручную не трогаем."""
        client = _FakeClient({
            "crm.item.list": {"result": {"items": []}},
            "crm.item.add": {"result": {"item": {}}},
        })
        result = self.service(client).ensure_card(
            _resolved_fields(), "44", entity_type_id=180, mapping=_MAPPING
        )

        self.assertEqual(result.status, "error")
        self.assertIn("идентификатор", result.error)


class WriteThroughTest(_ServiceTestCase):
    def test_creates_local_row_so_board_shows_project_immediately(self):
        service = self.service(_FakeClient())
        service.write_through(_resolved_fields(), "44", "901")

        card = ProjectCard.objects.get(bitrix24_account=self.account, project_id="44")
        self.assertEqual(card.project_name, "Портал АО Ромашка")
        self.assertEqual(card.project_item_id, "901")
        self.assertEqual(card.company_id, "15")
        self.assertEqual(card.our_legal_entity_id, "7")
        self.assertEqual(card.curator_user_id, "42")
        self.assertEqual(card.hourly_rate, 1500.0)
        self.assertEqual(card.project_hours_budget, 10.0)
        self.assertEqual(card.planned_budget_amount, 15000.0)
        self.assertEqual(card.project_start_date, date(2026, 7, 28))
        self.assertEqual(card.project_end_date, date(2027, 7, 28))
        self.assertEqual(card.stage, "DT180_7:NEW")
        self.assertFalse(card.is_archived)

    def test_second_call_updates_instead_of_duplicating(self):
        service = self.service(_FakeClient())
        service.write_through(_resolved_fields(), "44", "901")
        service.write_through(_resolved_fields(project_name="Переименован"), "44", "901")

        cards = ProjectCard.objects.filter(bitrix24_account=self.account, project_id="44")
        self.assertEqual(cards.count(), 1)
        self.assertEqual(cards.first().project_name, "Переименован")

    def test_other_portal_does_not_see_the_row(self):
        """Изоляция между порталами (§9 спеки): чужой аккаунт не должен видеть
        созданный проект ни при account-, ни при portal-скоупинге."""
        from .tenant_scoping import scope_to_tenant

        other = Bitrix24Account.objects.create(
            b24_user_id=2, is_b24_user_admin=True, member_id="m-create-2",
            is_master_account=True, domain_url="other.bitrix24.ru",
            status="active", application_version=1,
        )
        self.service(_FakeClient()).write_through(_resolved_fields(), "44", "901")

        visible_here = ProjectCard.objects.filter(**scope_to_tenant(self.account), project_id="44")
        visible_there = ProjectCard.objects.filter(**scope_to_tenant(other), project_id="44")
        self.assertEqual(visible_here.count(), 1)
        self.assertEqual(visible_there.count(), 0)
