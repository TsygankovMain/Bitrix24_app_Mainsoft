"""Тесты оркестратора создания связки «компания + группа + карточка».

Паттерн _FakeClient — как в tests_user_sync_service.py: подменяем call_method и
записываем вызовы, чтобы проверять идемпотентность без сети.
"""
from datetime import date
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from .models import Bitrix24Account, Portal, ProjectCard
from .project_board_service import ProjectCardService
from .project_creation_defaults import resolve_project_fields
from .project_creation_service import ProjectCreationService, StepResult
from .tenant_scoping import scope_to_tenant
from .utils.decorators.sync_lock import SyncLockBusy


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


class StepResultAsDictTest(TestCase):
    """Ревью фикс-раунда задачи 5: as_dict() клал self.candidates в ответ по
    ссылке. В create() один и тот же экземпляр StepResult(status="skipped")
    подставляется сразу в три ключа ответа (company/group/card) — общий
    список означал бы, что мутация candidates одного шага тихо портит два
    других. Сегодня безобидно (список пустой, ответ сразу уходит в JSON), но
    as_dict() обязан отдавать копию независимо от того, пуст список или нет."""

    def test_as_dict_candidates_is_independent_copy(self):
        result = StepResult(status="ambiguous", candidates=[{"id": "1", "name": "АО Ромашка"}])

        dict_1 = result.as_dict()
        dict_2 = result.as_dict()

        self.assertEqual(dict_1["candidates"], [{"id": "1", "name": "АО Ромашка"}])
        self.assertIsNot(dict_1["candidates"], result.candidates)
        self.assertIsNot(dict_1["candidates"], dict_2["candidates"])

        dict_1["candidates"].append({"id": "2", "name": "чужой кандидат"})
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(len(dict_2["candidates"]), 1)


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

    def test_mapping_without_group_link_is_skipped_not_duplicated(self):
        """mapping непуст, но без bitrix_group_id найти существующую карточку
        нечем: код не должен молча прыгать на создание — иначе два нажатия
        подряд дают две карточки, а приложение их не удаляет."""
        client = _FakeClient({"crm.item.add": {"result": {"item": {"id": 901}}}})
        mapping = dict(_MAPPING)
        del mapping["bitrix_group_id"]

        result = self.service(client).ensure_card(
            _resolved_fields(), "44", entity_type_id=180, mapping=mapping
        )

        self.assertEqual(result.status, "skipped")
        self.assertEqual(client.methods_called(), [])


def _account_with_portal(member_id, *, b24_user_id):
    """Аккаунт с проставленным Portal — прод-конфигурация под
    USE_PORTAL_SCOPING=True. `_ServiceTestCase.setUp` создаёт account без
    portal (см. tests_tenant_scoping.py::_account для того же паттерна)."""
    portal = Portal.objects.create(
        member_id=member_id, domain_url=f"{member_id}.bitrix24.ru", status="active"
    )
    account = Bitrix24Account.objects.create(
        b24_user_id=b24_user_id, is_b24_user_admin=True, member_id=member_id,
        is_master_account=True, domain_url=f"{member_id}.bitrix24.ru",
        status="active", application_version=1, portal=portal,
    )
    return account, portal


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

    # Три теста ниже гоняют реальную прод-конфигурацию: USE_PORTAL_SCOPING=True
    # и account с проставленным Portal. Без них проверялась только запасная
    # ветка scope_to_tenant ({"bitrix24_account": account}) — тесты выше не
    # переопределяют флаг, а test_settings наследует боевой дефолт False.

    @override_settings(USE_PORTAL_SCOPING=True)
    def test_portal_scoping_on_write_sets_both_portal_and_account(self):
        """Прод: без portal строка не попадёт в скоуп компании и доска её не
        покажет (§9 спеки) — двойная запись обязана проставить оба ключа."""
        account, portal = _account_with_portal("m-create-portal-1", b24_user_id=3)
        ProjectCreationService(_FakeClient(), account).write_through(_resolved_fields(), "44", "901")

        card = ProjectCard.objects.get(bitrix24_account=account, project_id="44")
        self.assertEqual(card.portal_id, portal.id)
        self.assertEqual(card.bitrix24_account_id, account.id)

    @override_settings(USE_PORTAL_SCOPING=True)
    def test_portal_scoping_on_second_call_updates_instead_of_duplicating(self):
        account, portal = _account_with_portal("m-create-portal-2", b24_user_id=3)
        service = ProjectCreationService(_FakeClient(), account)
        service.write_through(_resolved_fields(), "44", "901")
        service.write_through(_resolved_fields(project_name="Переименован"), "44", "901")

        cards = ProjectCard.objects.filter(bitrix24_account=account, project_id="44")
        self.assertEqual(cards.count(), 1)
        self.assertEqual(cards.first().project_name, "Переименован")
        self.assertEqual(cards.first().portal_id, portal.id)

    @override_settings(USE_PORTAL_SCOPING=True)
    def test_portal_scoping_on_other_portal_does_not_see_the_row(self):
        account, _ = _account_with_portal("m-create-portal-3a", b24_user_id=3)
        other_account, _ = _account_with_portal("m-create-portal-3b", b24_user_id=4)

        ProjectCreationService(_FakeClient(), account).write_through(_resolved_fields(), "44", "901")

        visible_here = ProjectCard.objects.filter(**scope_to_tenant(account), project_id="44")
        visible_there = ProjectCard.objects.filter(**scope_to_tenant(other_account), project_id="44")
        self.assertEqual(visible_here.count(), 1)
        self.assertEqual(visible_there.count(), 0)


class CreateOrchestrationTest(_ServiceTestCase):
    def _client(self, **overrides):
        responses = {
            "app.option.get": {"result": {"timestamp_config": (
                '{"hourly_rate": 1500, "project_sp_entity_type_id": 180,'
                ' "project_fields_mapping": {"title": "title",'
                ' "bitrix_group_id": "ufCrm7Group", "stage_id": "stageId"}}'
            )}},
            "crm.company.list": {"result": []},
            "crm.company.add": {"result": 77},
            "sonet_group.get": {"result": []},
            "sonet_group.create": {"result": 44},
            "crm.item.list": {"result": {"items": []}},
            "crm.item.add": {"result": {"item": {"id": 901}}},
        }
        responses.update(overrides)
        return _FakeClient(responses)

    def _form(self, **overrides):
        form = {"project_name": "Портал АО Ромашка", "company_name": "АО Ромашка"}
        form.update(overrides)
        return form

    def _create(self, client, form=None):
        return self.service(client).create(
            form or self._form(), current_user_id="42", current_user_name="Петров Иван",
            today=date(2026, 7, 28),
        )

    def test_happy_path_creates_all_three(self):
        result = self._create(self._client())

        self.assertEqual(result["company"]["status"], "created")
        self.assertEqual(result["group"]["status"], "created")
        self.assertEqual(result["card"]["status"], "created")
        self.assertTrue(result["done"])
        self.assertEqual(ProjectCard.objects.filter(project_id="44").count(), 1)

    def test_repeat_call_does_not_create_second_entities(self):
        client = self._client(
            **{
                "crm.company.list": {"result": [{"ID": "77", "TITLE": "АО Ромашка"}]},
                "sonet_group.get": {"result": [{"ID": "44", "NAME": "Портал АО Ромашка"}]},
                "crm.item.list": {"result": {"items": [{"id": 901}]}},
            }
        )
        result = self._create(client)

        self.assertEqual(result["company"]["status"], "found")
        self.assertEqual(result["group"]["status"], "found")
        self.assertEqual(result["card"]["status"], "found")
        self.assertTrue(result["done"])
        for method in ("crm.company.add", "sonet_group.create", "crm.item.add"):
            self.assertNotIn(method, client.methods_called())

    def test_group_failure_keeps_company_and_skips_card(self):
        client = self._client(**{"sonet_group.create": RuntimeError("нет прав на создание групп")})
        result = self._create(client)

        self.assertEqual(result["company"]["status"], "created")
        self.assertEqual(result["group"]["status"], "error")
        self.assertEqual(result["card"]["status"], "skipped")
        self.assertFalse(result["done"])
        self.assertNotIn("crm.item.add", client.methods_called())

    def test_ambiguous_company_stops_before_group(self):
        # crm.company.list звучит внутри create() дважды с разными фильтрами:
        # сперва get_legal_entities (IS_MY_COMPANY=Y), потом поиск компании в
        # ensure_company (=TITLE). _FakeClient различает вызовы одного метода
        # только по порядку (см. его докстринг про список ответов), поэтому
        # первый ответ — пусто (своих юрлиц с таким именем нет), второй —
        # два совпадения по названию, которые и должны дать ambiguous.
        # Один и тот же статичный ответ на оба вызова здесь не годится: тогда
        # ambiguous-пара «протекла» бы и в юрлица, our_legal_entity_id попал
        # бы в missing, и create() вышел бы раньше ensure_company вообще не
        # по той причине, которую проверяет этот тест.
        client = self._client(
            **{"crm.company.list": [
                {"result": []},
                {"result": [
                    {"ID": "77", "TITLE": "АО Ромашка"},
                    {"ID": "78", "TITLE": "АО Ромашка"},
                ]},
            ]}
        )
        result = self._create(client)

        self.assertEqual(result["company"]["status"], "ambiguous")
        self.assertEqual(result["group"]["status"], "skipped")
        self.assertEqual(result["card"]["status"], "skipped")
        self.assertFalse(result["done"])
        self.assertNotIn("sonet_group.create", client.methods_called())

    def test_missing_required_fields_stop_before_any_bitrix_call(self):
        client = self._client()
        result = self._create(client, form={"company_name": "АО Ромашка"})

        self.assertIn("project_name", result["missing_fields"])
        self.assertFalse(result["done"])
        self.assertNotIn("crm.company.add", client.methods_called())

    def test_card_error_still_reports_created_company_and_group(self):
        client = self._client(**{"crm.item.add": RuntimeError("поле не найдено")})
        result = self._create(client)

        self.assertEqual(result["company"]["status"], "created")
        self.assertEqual(result["group"]["status"], "created")
        self.assertEqual(result["card"]["status"], "error")
        self.assertFalse(result["done"])
        # Группа создана — локальную строку всё равно пишем, иначе доска её не покажет.
        self.assertEqual(ProjectCard.objects.filter(project_id="44").count(), 1)


class CreateOrchestrationConcurrencyTest(_ServiceTestCase):
    """Сверх брифа Task 5 — пункты, поднятые ревью Task 2/4 (см. progress.md):

    1. Гонка двух почти одновременных вызовов create(): лок должен закрыть
       окно гонки, а при занятости — вернуть частичный результат без
       исключения наружу и без единого мутирующего вызова Битрикса.
    2. Дубль строки ProjectCard в скоупе портала: unique_together стоит на
       паре (bitrix24_account, project_id), а не (portal, project_id) —
       второй сотрудник того же портала не должен получить вторую строку.

    _client/_form дублируют одноимённые методы CreateOrchestrationTest
    намеренно: тот класс воспроизведён из брифа дословно, трогать его не
    стоит, а тут нужен ещё и параметр account в _create."""

    def _client(self, **overrides):
        responses = {
            "app.option.get": {"result": {"timestamp_config": (
                '{"hourly_rate": 1500, "project_sp_entity_type_id": 180,'
                ' "project_fields_mapping": {"title": "title",'
                ' "bitrix_group_id": "ufCrm7Group", "stage_id": "stageId"}}'
            )}},
            "crm.company.list": {"result": []},
            "crm.company.add": {"result": 77},
            "sonet_group.get": {"result": []},
            "sonet_group.create": {"result": 44},
            "crm.item.list": {"result": {"items": []}},
            "crm.item.add": {"result": {"item": {"id": 901}}},
        }
        responses.update(overrides)
        return _FakeClient(responses)

    def _form(self, **overrides):
        form = {"project_name": "Портал АО Ромашка", "company_name": "АО Ромашка"}
        form.update(overrides)
        return form

    def _create(self, client, account=None, form=None):
        service = ProjectCreationService(client, account or self.account)
        return service.create(
            form or self._form(), current_user_id="42", current_user_name="Петров Иван",
            today=date(2026, 7, 28),
        )

    def test_lock_busy_returns_graceful_error_without_bitrix_mutation(self):
        client = self._client()
        with patch("main.project_creation_service.account_sync_lock", side_effect=SyncLockBusy):
            result = self._create(client)

        self.assertEqual(result["company"]["status"], "error")
        self.assertEqual(result["group"]["status"], "skipped")
        self.assertEqual(result["card"]["status"], "skipped")
        self.assertFalse(result["done"])
        self.assertEqual(result["missing_fields"], [])
        # Лок берётся до первого шага, а не после — ни один мутирующий или
        # поисковый вызов ensure_* не должен был случиться.
        for method in (
            "crm.company.add", "sonet_group.get", "sonet_group.create",
            "crm.item.list", "crm.item.add",
        ):
            self.assertNotIn(method, client.methods_called())
        self.assertEqual(ProjectCard.objects.count(), 0)

    def test_lock_uses_dedicated_scope_not_shared_with_background_sync(self):
        """scope="project_create", а не "project": тот занят фоновой
        ProjectSyncService.sync() (sync_scheduler_service,
        _save_configuration_with_project_sync). Общий scope привязал бы
        кнопку к длительности чужой синхронизации портала и наоборот —
        см. комментарий в utils/decorators/sync_lock.py."""
        client = self._client()
        with patch("main.project_creation_service.account_sync_lock") as mock_lock:
            mock_lock.return_value.__enter__ = MagicMock(return_value=None)
            mock_lock.return_value.__exit__ = MagicMock(return_value=False)
            self._create(client)

        mock_lock.assert_called_once()
        args, kwargs = mock_lock.call_args
        self.assertEqual(args[0], self.account)
        self.assertEqual(kwargs.get("scope"), "project_create")

    def test_missing_fields_do_not_touch_the_lock(self):
        """Проверка обязательных полей идёт раньше лока: блокировать нечего,
        Битрикс ещё не тронут (симметрично test_missing_required_fields_stop_
        before_any_bitrix_call в CreateOrchestrationTest)."""
        client = self._client()
        with patch("main.project_creation_service.account_sync_lock") as mock_lock:
            self._create(client, form={"company_name": "АО Ромашка"})

        mock_lock.assert_not_called()

    @override_settings(USE_PORTAL_SCOPING=True)
    def test_second_account_same_portal_does_not_duplicate_local_row(self):
        """Ревью Task 4 (progress.md): unique_together у ProjectCard стоит на
        паре (bitrix24_account, project_id), а не (portal, project_id) — два
        сотрудника ОДНОГО портала, создав тот же проект, получали две строки
        в скоупе портала и дубль на доске. Первый сотрудник создаёт с нуля,
        второй попадает на уже существующие компанию/группу/карточку — но
        локальная запись должна остаться одна на весь портал."""
        portal = Portal.objects.create(
            member_id="m-create-portal-race", domain_url="race.bitrix24.ru", status="active",
        )
        account_a = Bitrix24Account.objects.create(
            b24_user_id=10, is_b24_user_admin=True, member_id="m-create-portal-race",
            is_master_account=True, domain_url="race.bitrix24.ru",
            status="active", application_version=1, portal=portal,
        )
        account_b = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=False, member_id="m-create-portal-race",
            is_master_account=False, domain_url="race.bitrix24.ru",
            status="active", application_version=1, portal=portal,
        )

        result_a = self._create(self._client(), account=account_a)
        self.assertEqual(result_a["company"]["status"], "created")
        self.assertEqual(result_a["group"]["status"], "created")
        self.assertTrue(result_a["done"])

        client_b = self._client(**{
            "crm.company.list": {"result": [{"ID": "77", "TITLE": "АО Ромашка"}]},
            "sonet_group.get": {"result": [{"ID": "44", "NAME": "Портал АО Ромашка"}]},
            "crm.item.list": {"result": {"items": [{"id": 901}]}},
        })
        result_b = self._create(client_b, account=account_b)

        self.assertEqual(result_b["company"]["status"], "found")
        self.assertEqual(result_b["group"]["status"], "found")
        self.assertEqual(result_b["card"]["status"], "found")
        self.assertTrue(result_b["done"])
        for method in ("crm.company.add", "sonet_group.create", "crm.item.add"):
            self.assertNotIn(method, client_b.methods_called())

        # Один сотрудник портала уже написал строку — вторая запись не появилась.
        visible_on_portal = ProjectCard.objects.filter(portal=portal, project_id="44")
        self.assertEqual(visible_on_portal.count(), 1)
        self.assertEqual(visible_on_portal.first().bitrix24_account_id, account_a.id)

    def test_same_account_repeat_call_still_updates_local_row(self):
        """Дедуп по чужому аккаунту не должен помешать штатному апдейту СВОЕЙ
        же строки при повторном вызове (см. WriteThroughTest в Task 4) —
        exclude(bitrix24_account=self.account) обязан оставаться в фильтре."""
        client = self._client()
        self._create(client)

        client_again = self._client(**{
            "crm.company.list": {"result": [{"ID": "77", "TITLE": "АО Ромашка"}]},
            "sonet_group.get": {"result": [{"ID": "44", "NAME": "Портал АО Ромашка"}]},
            "crm.item.list": {"result": {"items": [{"id": 901}]}},
        })
        self._create(client_again, form=self._form(project_hours_budget="20"))

        cards = ProjectCard.objects.filter(bitrix24_account=self.account, project_id="44")
        self.assertEqual(cards.count(), 1)
        self.assertEqual(cards.first().project_hours_budget, 20.0)


class CreateEndpointRoutingTest(_ServiceTestCase):
    def test_route_is_registered(self):
        from django.urls import reverse
        self.assertEqual(reverse("create_project_board"), "/api/project-board/create")

    def test_view_rejects_get(self):
        from django.test import Client as HttpClient
        response = HttpClient().get("/api/project-board/create")
        self.assertEqual(response.status_code, 405)


class CreateCacheInvalidationTest(_ServiceTestCase):
    """Находка ревью, блокирующая выкатку кнопки (task-9-cache-fix-report.md):
    create() не сбрасывал серверный кэш доски после write_through.

    get_board_data/get_homepage_snapshot (project_board_service.py) читают
    свой кэш первым делом и отдают его как есть, пока не истёк
    PROJECT_BOARD_CACHE_TTL/HOMEPAGE_CACHE_TTL (2 минуты,
    project_board_shared.py). Кэш прогревается уже тем, что человек находится
    на доске — значит «создал -> кнопка отчиталась успехом -> на доске пусто
    -> нажал ещё раз» типичный случай, а не редкий крайний. Все остальные
    изменяющие пути (update_card/update_stage/archive_project/
    ProjectSyncService.sync/StageAutomationService/сохранение настроек/синк
    таймшитов — см. grep по invalidate_project_runtime_caches) зовут
    invalidate_project_runtime_caches сразу после своей записи; create() была
    единственным исключением.

    Тест воспроизводит ровно последовательность ревьюера: прогреть кэш чтением
    доски (как это происходит само собой при открытии доски), создать проект
    тем же путём, что и кнопка, перечитать доску — и увидеть проект без
    ожидания TTL."""

    def _client(self, **overrides):
        responses = {
            "app.option.get": {"result": {"timestamp_config": (
                '{"hourly_rate": 1500, "project_sp_entity_type_id": 180,'
                ' "project_fields_mapping": {"title": "title",'
                ' "bitrix_group_id": "ufCrm7Group", "stage_id": "stageId"}}'
            )}},
            "crm.company.list": {"result": []},
            "crm.company.add": {"result": 77},
            "sonet_group.get": {"result": []},
            "sonet_group.create": {"result": 44},
            "crm.item.list": {"result": {"items": []}},
            "crm.item.add": {"result": {"item": {"id": 901}}},
        }
        responses.update(overrides)
        return _FakeClient(responses)

    def _form(self, **overrides):
        form = {"project_name": "Портал АО Ромашка", "company_name": "АО Ромашка"}
        form.update(overrides)
        return form

    def setUp(self):
        super().setUp()
        cache.clear()

    def test_new_project_appears_on_board_right_after_create(self):
        client = self._client()
        board_service = ProjectCardService(client, self.account)

        # 1. Прогреваем серверный кэш доски — происходит само собой, когда
        # человек открывает доску, ещё до создания проекта.
        warm = board_service.get_board_data()
        self.assertEqual(warm["cards"], [])

        # 2. Создаём проект тем же путём, что и кнопка «Создать проект».
        result = self.service(client).create(
            self._form(), current_user_id="42", current_user_name="Петров Иван",
            today=date(2026, 7, 28),
        )
        self.assertTrue(result["done"])
        self.assertEqual(ProjectCard.objects.filter(project_id="44").count(), 1)

        # 3. Доска обязана показать проект немедленно — не через 2 минуты
        # (PROJECT_BOARD_CACHE_TTL, project_board_shared.py).
        board = board_service.get_board_data()
        project_ids = [card["project_id"] for card in board["cards"]]
        self.assertIn(
            "44", project_ids,
            "Кэш доски не сброшен после create() — новый проект не виден без ожидания TTL.",
        )

    def test_homepage_snapshot_also_reflects_new_project(self):
        """get_homepage_snapshot кэшируется ОТДЕЛЬНЫМ ключом
        ("project-board-homepage", HOMEPAGE_CACHE_TTL) и, если он уже тёплый,
        не перечитывает даже свежий get_board_data — invalidate_project_
        runtime_caches обязана сбросить оба ключа, не только "project-board"."""
        client = self._client()
        board_service = ProjectCardService(client, self.account)

        board_service.get_board_data()  # прогрев "project-board"
        board_service.get_homepage_snapshot()  # прогрев "project-board-homepage"

        result = self.service(client).create(
            self._form(), current_user_id="42", current_user_name="Петров Иван",
            today=date(2026, 7, 28),
        )
        self.assertTrue(result["done"])

        homepage = board_service.get_homepage_snapshot()
        project_ids = [card["project_id"] for card in homepage["cards"]]
        self.assertIn(
            "44", project_ids,
            "Кэш главного экрана не сброшен после create() — новый проект не виден без ожидания TTL.",
        )

    def test_repeat_found_found_found_call_still_invalidates(self):
        """Первый вызов create() создаёт всё с нуля и уже покрыт тестом выше.
        Этот тест — повторное нажатие: company/group/card все "found" (ничего
        не создано в Битриксе), а write_through всё равно безусловно
        перезаписывает локальную строку (update_or_create). Кэш обязан
        сброситься и здесь: "всё найдено" на уровне Битрикса не означает
        "локальная строка не изменилась" — это может быть первое появление
        строки для проекта, заведённого в Битриксе до этого приложения."""
        client = self._client()
        board_service = ProjectCardService(client, self.account)

        self.service(client).create(
            self._form(), current_user_id="42", current_user_name="Петров Иван",
            today=date(2026, 7, 28),
        )
        board_service.get_board_data()  # прогреваем кэш свежесозданным проектом

        client_repeat = self._client(**{
            "crm.company.list": {"result": [{"ID": "77", "TITLE": "АО Ромашка"}]},
            "sonet_group.get": {"result": [{"ID": "44", "NAME": "Портал АО Ромашка"}]},
            "crm.item.list": {"result": {"items": [{"id": 901}]}},
        })
        result = self.service(client_repeat).create(
            self._form(project_hours_budget="25"), current_user_id="42", current_user_name="Петров Иван",
            today=date(2026, 7, 28),
        )
        self.assertEqual(result["company"]["status"], "found")
        self.assertEqual(result["group"]["status"], "found")
        self.assertEqual(result["card"]["status"], "found")
        self.assertTrue(result["done"])

        board = board_service.get_board_data()
        budgets = {card["project_id"]: card["project_hours_budget"] for card in board["cards"]}
        self.assertEqual(
            budgets.get("44"), 25.0,
            "Кэш доски не сброшен после повторного create() (found/found/found) — правка не видна.",
        )
