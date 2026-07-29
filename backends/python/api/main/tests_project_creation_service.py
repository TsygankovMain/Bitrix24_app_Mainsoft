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


class EnsureCompanyByInnTest(_ServiceTestCase):
    """Шаг 1 ensure_company при переданном ИНН (решение заказчика 29.07.2026,
    inn-brief.md): точный поиск по РЕКВИЗИТУ (crm.requisite.list, RQ_INN), а
    не по названию — компания у Битрикса привязана к ИНН, а не к тексту,
    который ввёл человек. Без inn= (или с inn="") поведение полностью
    совпадает с EnsureCompanyTest — см. test_inn_not_provided_skips_inn_
    search_entirely ниже и весь класс EnsureCompanyTest, оставшийся
    нетронутым."""

    VALID_INN = "7707083893"  # проверенный валидный ИНН юрлица (10 цифр)

    def test_inn_match_is_used_without_creating(self):
        client = _FakeClient({
            "crm.requisite.list": {"result": [{"ENTITY_ID": "77", "RQ_INN": self.VALID_INN}]},
            "crm.company.list": {"result": [{"ID": "77", "TITLE": "АО Ромашка"}]},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка", inn=self.VALID_INN)

        self.assertEqual(result.status, "found")
        self.assertEqual(result.id, "77")
        self.assertIsNone(result.entered_name)
        self.assertNotIn("crm.company.add", client.methods_called())

    def test_inn_match_under_different_name_is_flagged_not_silently_renamed(self):
        client = _FakeClient({
            "crm.requisite.list": {"result": [{"ENTITY_ID": "77", "RQ_INN": self.VALID_INN}]},
            "crm.company.list": {"result": [{"ID": "77", "TITLE": "ООО Старое Название"}]},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка", inn=self.VALID_INN)

        self.assertEqual(result.status, "found")
        self.assertEqual(result.id, "77")
        # .name — НАСТОЯЩЕЕ (найденное) название, не то, что ввёл человек.
        self.assertEqual(result.name, "ООО Старое Название")
        # .entered_name — то, что ввёл человек, отдельным полем (не в error).
        self.assertEqual(result.entered_name, "АО Ромашка")
        self.assertIsNone(result.error)
        self.assertNotIn("crm.company.add", client.methods_called())

    def test_as_dict_exposes_entered_name(self):
        client = _FakeClient({
            "crm.requisite.list": {"result": [{"ENTITY_ID": "77", "RQ_INN": self.VALID_INN}]},
            "crm.company.list": {"result": [{"ID": "77", "TITLE": "ООО Старое Название"}]},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка", inn=self.VALID_INN)

        self.assertEqual(result.as_dict()["entered_name"], "АО Ромашка")

    def test_inn_search_uses_exact_filter_not_substring(self):
        client = _FakeClient({
            "crm.requisite.list": {"result": []},
            "crm.company.list": {"result": []},
            "crm.company.add": {"result": 77},
        })
        self.service(client).ensure_company(None, "АО Ромашка", inn=self.VALID_INN)

        method, params = client.calls[0]
        self.assertEqual(method, "crm.requisite.list")
        self.assertEqual(params["filter"]["ENTITY_TYPE_ID"], 4)
        self.assertNotIn("%RQ_INN", params["filter"])
        self.assertEqual(params["filter"]["RQ_INN"], self.VALID_INN)

    def test_no_inn_match_falls_back_to_name_search_and_creates(self):
        client = _FakeClient({
            "crm.requisite.list": {"result": []},
            "crm.company.list": {"result": []},
            "crm.company.add": {"result": 77},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка", inn=self.VALID_INN)

        self.assertEqual(result.status, "created")
        self.assertEqual(
            client.methods_called(), ["crm.requisite.list", "crm.company.list", "crm.company.add"]
        )

    def test_inn_not_provided_skips_inn_search_entirely(self):
        client = _FakeClient({"crm.company.list": {"result": [{"ID": "15", "TITLE": "АО Ромашка"}]}})
        result = self.service(client).ensure_company(None, "АО Ромашка")

        self.assertEqual(result.status, "found")
        self.assertNotIn("crm.requisite.list", client.methods_called())

    def test_blank_inn_string_skips_inn_search_entirely(self):
        client = _FakeClient({"crm.company.list": {"result": [{"ID": "15", "TITLE": "АО Ромашка"}]}})
        result = self.service(client).ensure_company(None, "АО Ромашка", inn="   ")

        self.assertEqual(result.status, "found")
        self.assertNotIn("crm.requisite.list", client.methods_called())

    def test_explicit_company_id_skips_inn_search_even_if_inn_is_sent(self):
        """Оборонительная проверка "не трогается" на уровне сервиса, не
        только чистой функции resolve_project_fields: даже если inn=
        передан вместе с company_id, ensure_company не должен полезть за
        реквизитами уже выбранной компании (inn-brief.md, "Решение")."""
        client = _FakeClient()
        result = self.service(client).ensure_company("15", "АО Ромашка", inn=self.VALID_INN)

        self.assertEqual(result.status, "found")
        self.assertEqual(result.id, "15")
        self.assertEqual(client.methods_called(), [])

    def test_multiple_inn_matches_return_ambiguous(self):
        client = _FakeClient({
            "crm.requisite.list": {"result": [
                {"ENTITY_ID": "77", "RQ_INN": self.VALID_INN},
                {"ENTITY_ID": "78", "RQ_INN": self.VALID_INN},
            ]},
            "crm.company.list": [
                {"result": [{"ID": "77", "TITLE": "АО Ромашка"}]},
                {"result": [{"ID": "78", "TITLE": "АО Ромашка Два"}]},
            ],
        })
        result = self.service(client).ensure_company(None, "АО Ромашка", inn=self.VALID_INN)

        self.assertEqual(result.status, "ambiguous")
        self.assertEqual(sorted(c["id"] for c in result.candidates), ["77", "78"])
        self.assertNotIn("crm.company.add", client.methods_called())

    def test_orphaned_requisite_falls_back_to_name_search(self):
        """Реквизит с этим ИНН есть, а компании уже нет (удалена) — не
        считаем совпадением, ищем по названию как обычно."""
        client = _FakeClient({
            "crm.requisite.list": {"result": [{"ENTITY_ID": "999", "RQ_INN": self.VALID_INN}]},
            "crm.company.list": [
                {"result": []},  # резолв TITLE для ENTITY_ID=999 — компании нет
                {"result": []},  # поиск по названию — тоже пусто
            ],
            "crm.company.add": {"result": 77},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка", inn=self.VALID_INN)

        self.assertEqual(result.status, "created")
        self.assertEqual(result.id, "77")

    def test_inn_search_malformed_response_is_error(self):
        client = _FakeClient({"crm.requisite.list": {"result": {"unexpected": "shape"}}})
        result = self.service(client).ensure_company(None, "АО Ромашка", inn=self.VALID_INN)

        self.assertEqual(result.status, "error")
        self.assertNotIn("crm.company.add", client.methods_called())

    def test_inn_search_bitrix_failure_becomes_error(self):
        client = _FakeClient({"crm.requisite.list": RuntimeError("портал недоступен")})
        result = self.service(client).ensure_company(None, "АО Ромашка", inn=self.VALID_INN)

        self.assertEqual(result.status, "error")
        self.assertIn("портал недоступен", result.error)

    def test_inn_match_company_lookup_malformed_response_is_error(self):
        client = _FakeClient({
            "crm.requisite.list": {"result": [{"ENTITY_ID": "77", "RQ_INN": self.VALID_INN}]},
            "crm.company.list": {"result": {"unexpected": "shape"}},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка", inn=self.VALID_INN)

        self.assertEqual(result.status, "error")
        self.assertNotIn("crm.company.add", client.methods_called())

    def test_inn_match_company_lookup_failure_becomes_error(self):
        client = _FakeClient({
            "crm.requisite.list": {"result": [{"ENTITY_ID": "77", "RQ_INN": self.VALID_INN}]},
            "crm.company.list": RuntimeError("нет доступа"),
        })
        result = self.service(client).ensure_company(None, "АО Ромашка", inn=self.VALID_INN)

        self.assertEqual(result.status, "error")

    def test_inn_search_accepts_lower_camel_case_fields(self):
        """Остальной код проекта проверяет оба варианта регистра полей
        Битрикса (ENTITY_ID/entityId, RQ_INN/rqInn — см.
        project_board_service.py/company_search_service.py); та же защита
        нужна и здесь."""
        client = _FakeClient({
            "crm.requisite.list": {"result": [{"entityId": "77", "rqInn": self.VALID_INN}]},
            "crm.company.list": {"result": [{"ID": "77", "TITLE": "АО Ромашка"}]},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка", inn=self.VALID_INN)

        self.assertEqual(result.status, "found")
        self.assertEqual(result.id, "77")


class EnsureRequisiteTest(_ServiceTestCase):
    """Шаг реквизита (ИНН) для новой компании — inn-brief.md, раздел
    «Реквизит — отдельный шаг со своим статусом». В create()/
    _create_under_lock вызывается безусловно после ensure_company, но сам
    решает применимость по company_id/inn (см. test_blank_*_is_skipped_
    ниже) — тот же приём, что и у ensure_card с entity_type_id/mapping.

    Выбор шаблона реквизита (два раунда ре-ревью координатора после сверки с
    документацией Битрикса, см. inn-backend-report.md): у
    crm.requisite.preset.list НЕТ признака "по умолчанию" — полный список
    полей шаблона: ID, ENTITY_TYPE_ID, COUNTRY_ID, DATE_CREATE, DATE_MODIFY,
    CREATED_BY_ID, MODIFY_BY_ID, NAME, XML_ID, ACTIVE, SORT. Выбор идёт по
    ACTIVE="Y" + детерминированному порядку {"SORT": "ASC", "ID": "ASC"}, и
    ОБЯЗАТЕЛЬНО проверяется поддержка поля RQ_INN конкретным шаблоном через
    crm.requisite.preset.field.list — состав полей шаблона настраиваемый,
    без этой проверки crm.requisite.add мог бы молча создать реквизит без
    ИНН (шаг отчитался бы успехом, ИНН потерян).

    Второй раунд (см. test_field_list_request_uses_preset_object_not_scalar_id):
    запрос crm.requisite.preset.field.list — {"preset": {"ID": ...}}, НЕ
    {"id": ...}; форма ответа ПОДТВЕРЖДЕНА — result это список объектов с
    кодом поля в FIELD_NAME (словарь по кодам — не основной, а лишь
    защитный вариант для этого метода); один запрос без обхода страниц —
    решение осознанное (шаблон реквизита физически не превышает одну
    страницу ответа), задокументировано в докстринге
    _requisite_preset_supports_inn.

    Третий раунд, задача на вычитание (см. inn-trim-report.md): пагинация
    убрана целиком (константа лимита страниц и цикл обхода — код и тесты).
    Заодно чинится ре-ревью координатора — текст ошибки при
    _resolve_requisite_preset_id() -> None различает "отсутствие шаблона
    ПОДТВЕРЖДЕНО" (настройка портала, повтор не поможет) от "не удалось
    ПРОВЕРИТЬ" (временный сбой Битрикса, повтор имеет смысл) — см.
    test_no_template_error_states_it_is_a_portal_setting_not_a_retry_case
    и test_verification_failure_error_states_retry_may_help_not_a_portal_
    setting ниже."""

    VALID_INN = "7707083893"

    def setUp(self):
        super().setUp()
        # _resolve_requisite_preset_id кэширует по account.pk — Django
        # TestCase откатывает транзакцию между тестами, и pk легко
        # повторяется у SQLite (см. cache.clear() в CreateCacheInvalidationTest
        # этого же файла, тот же повод). Без явной очистки один тест мог бы
        # унаследовать PRESET_ID, закэшированный другим тестом этого класса.
        cache.clear()

    def _preset_response(self, presets):
        return {"result": presets}

    def _active_preset(self, preset_id, name="Российская компания", **overrides):
        row = {"ID": preset_id, "ENTITY_TYPE_ID": "4", "NAME": name, "ACTIVE": "Y"}
        row.update(overrides)
        return row

    def _field_list_response(self, codes):
        """Форма ответа crm.requisite.preset.field.list по умолчанию в
        тестах — список объектов-описаний поля с кодом в FIELD_NAME.
        ПОДТВЕРЖДЕНО документацией Битрикса (см. докстринг
        _extract_preset_field_codes) — основной вариант, не один из
        нескольких равновероятных."""
        return {"result": [{"FIELD_NAME": code} for code in codes]}

    def _field_list_dict_response(self, codes):
        """Второй, ЗАЩИТНЫЙ вариант формы ответа — словарь, ключи которого
        коды полей (семейство crm.*.fields; для ЭТОГО метода документацией
        не подтверждён, см. докстринг _extract_preset_field_codes)."""
        return {"result": {code: {} for code in codes}}


    def test_creates_requisite_with_single_qualifying_preset(self):
        client = _FakeClient({
            "crm.requisite.list": {"result": []},
            "crm.requisite.preset.list": self._preset_response([self._active_preset("5")]),
            "crm.requisite.preset.field.list": self._field_list_response(["RQ_INN", "RQ_COMPANY_NAME"]),
            "crm.requisite.add": {"result": 501},
        })
        result = self.service(client).ensure_requisite("77", "АО Ромашка", self.VALID_INN)

        self.assertEqual(result.status, "created")
        self.assertEqual(result.id, "501")

        method, params = client.calls[-1]
        self.assertEqual(method, "crm.requisite.add")
        req_fields = params["fields"]
        self.assertEqual(req_fields["PRESET_ID"], 5)
        self.assertEqual(req_fields["ENTITY_TYPE_ID"], 4)
        self.assertEqual(req_fields["ENTITY_ID"], 77)
        self.assertEqual(req_fields["RQ_INN"], self.VALID_INN)
        self.assertEqual(req_fields["NAME"], "АО Ромашка")

    def test_preset_list_request_uses_active_filter_and_deterministic_order(self):
        client = _FakeClient({
            "crm.requisite.list": {"result": []},
            "crm.requisite.preset.list": self._preset_response([self._active_preset("5")]),
            "crm.requisite.preset.field.list": self._field_list_response(["RQ_INN"]),
            "crm.requisite.add": {"result": 501},
        })
        self.service(client).ensure_requisite("77", "АО Ромашка", self.VALID_INN)

        preset_list_call = next(c for c in client.calls if c[0] == "crm.requisite.preset.list")
        params = preset_list_call[1]
        self.assertEqual(params["filter"]["ENTITY_TYPE_ID"], 4)
        self.assertEqual(params["filter"]["ACTIVE"], "Y")
        self.assertEqual(params["order"], {"SORT": "ASC", "ID": "ASC"})

    def test_multiple_qualifying_presets_pick_first_by_order(self):
        """Оба шаблона активны и поддерживают RQ_INN — берётся ПЕРВЫЙ в
        порядке, который вернул сервер (SORT/ID ASC), а не последний и не
        произвольный."""
        client = _FakeClient({
            "crm.requisite.list": {"result": []},
            "crm.requisite.preset.list": self._preset_response(
                [self._active_preset("5", name="Первый"), self._active_preset("6", name="Второй")]
            ),
            "crm.requisite.preset.field.list": self._field_list_response(["RQ_INN"]),
            "crm.requisite.add": {"result": 501},
        })
        self.service(client).ensure_requisite("77", "АО Ромашка", self.VALID_INN)

        _, params = client.calls[-1]
        self.assertEqual(params["fields"]["PRESET_ID"], 5)


    def test_inactive_preset_is_not_considered_even_if_server_returns_it(self):
        """Оборонительная проверка (та же практика, что и для ENTITY_TYPE_ID
        выше): не доверяем одному только серверному filter=ACTIVE:"Y" —
        перепроверяем на клиенте. Неактивный шаблон идёт первым в списке (по
        SORT), но не должен быть выбран — используется активный."""
        client = _FakeClient({
            "crm.requisite.list": {"result": []},
            "crm.requisite.preset.list": self._preset_response([
                self._active_preset("5", name="Неактивный", ACTIVE="N"),
                self._active_preset("6", name="Активный"),
            ]),
            "crm.requisite.preset.field.list": self._field_list_response(["RQ_INN"]),
            "crm.requisite.add": {"result": 501},
        })
        result = self.service(client).ensure_requisite("77", "АО Ромашка", self.VALID_INN)

        self.assertEqual(result.status, "created")
        _, params = client.calls[-1]
        self.assertEqual(params["fields"]["PRESET_ID"], 6)

    def test_only_inactive_presets_is_the_same_as_no_template_error(self):
        client = _FakeClient({
            "crm.requisite.list": {"result": []},
            "crm.requisite.preset.list": self._preset_response(
                [self._active_preset("5", ACTIVE="N")]
            ),
        })
        result = self.service(client).ensure_requisite("77", "АО Ромашка", self.VALID_INN)

        self.assertEqual(result.status, "error")
        self.assertNotIn("crm.requisite.preset.field.list", client.methods_called())
        self.assertNotIn("crm.requisite.add", client.methods_called())

    def test_preset_is_taken_from_an_existing_requisite_with_inn(self):
        """Шаблон берётся по ФАКТУ: каким уже записаны ИНН на этом портале.

        Дефект прода 29.07.2026: шаблон проверялся через
        crm.requisite.preset.field.list, а тот отдаёт только поля,
        ДОБАВЛЕННЫЕ в шаблон вручную. На портале, где состав полей не
        настраивали, список пуст — и проверка отвергала шаблон, которым на
        том же портале уже записаны 16 395 реквизитов с ИНН. Создание
        проектов вставало с «на портале не настроен шаблон».
        """
        client = _FakeClient({
            "crm.requisite.list": {"result": [
                {"ID": "10", "PRESET_ID": "1", "RQ_INN": ""},
                {"ID": "11", "PRESET_ID": "3", "RQ_INN": "5018154843"},  # ЧУЖОЙ ИНН: шаблон подсказывает, но идемпотентность не срабатывает
            ]},
            "crm.requisite.add": {"result": 501},
        })
        result = self.service(client).ensure_requisite("77", "АО Ромашка", self.VALID_INN)

        self.assertEqual(result.status, "created")
        _, params = client.calls[-1]
        self.assertEqual(params["fields"]["PRESET_ID"], 3)
        # Справочник шаблонов не понадобился вовсе — факт надёжнее догадки.
        self.assertNotIn("crm.requisite.preset.list", client.methods_called())

    def test_requisite_without_inn_does_not_define_the_preset(self):
        """Реквизит с пустым ИНН не доказывает, что его шаблон хранит ИНН —
        такой кандидат обязан быть пропущен, иначе мы выберем шаблон,
        который молча не сохранит значение."""
        client = _FakeClient({
            "crm.requisite.list": {"result": [{"ID": "10", "PRESET_ID": "1", "RQ_INN": ""}]},
            "crm.requisite.preset.list": self._preset_response([self._active_preset("6")]),
            "crm.requisite.add": {"result": 501},
        })
        self.service(client).ensure_requisite("77", "АО Ромашка", self.VALID_INN)

        _, params = client.calls[-1]
        self.assertEqual(params["fields"]["PRESET_ID"], 6)

    def test_preset_filtered_by_entity_type_id_four(self):
        """Пресеты для физлиц/ИП (другой ENTITY_TYPE_ID) не должны попасть
        в выбор — даже если сервер вернул их вперемешку."""
        client = _FakeClient({
            "crm.requisite.list": {"result": []},
            "crm.requisite.preset.list": self._preset_response([
                {"ID": "9", "ENTITY_TYPE_ID": "1", "NAME": "Физлицо", "ACTIVE": "Y"},
                self._active_preset("6"),
            ]),
            "crm.requisite.preset.field.list": self._field_list_response(["RQ_INN"]),
            "crm.requisite.add": {"result": 501},
        })
        self.service(client).ensure_requisite("77", "АО Ромашка", self.VALID_INN)

        _, params = client.calls[-1]
        self.assertEqual(params["fields"]["PRESET_ID"], 6)

    def test_preset_response_wrapped_in_items_key_is_parsed(self):
        """crm.item.list-подобная форма ({"result": {"items": [...]}}) — форма
        ответа именно этого метода нигде в проекте раньше не проверялась
        (inn-brief.md: «уже дважды... разбор ответа оказывался неверным»)."""
        client = _FakeClient({
            "crm.requisite.list": {"result": []},
            "crm.requisite.preset.list": {"result": {"items": [self._active_preset("6")]}},
            "crm.requisite.preset.field.list": self._field_list_response(["RQ_INN"]),
            "crm.requisite.add": {"result": 501},
        })
        result = self.service(client).ensure_requisite("77", "АО Ромашка", self.VALID_INN)

        self.assertEqual(result.status, "created")

    def test_preset_field_list_dict_shaped_response_is_still_parsed_defensively(self):
        """Второй, ЗАЩИТНЫЙ вариант формы ответа — словарь по кодам полей
        (семейство crm.*.fields). Для ЭТОГО метода документацией не
        подтверждён (основной и подтверждённый — список с FIELD_NAME, см.
        test_creates_requisite_with_single_qualifying_preset и докстринг
        _extract_preset_field_codes), но разбор всё равно его переживает —
        чистая защита на случай расхождения версии/локали портала."""
        client = _FakeClient({
            "crm.requisite.list": {"result": []},
            "crm.requisite.preset.list": self._preset_response([self._active_preset("5")]),
            "crm.requisite.preset.field.list": self._field_list_dict_response(["RQ_INN", "RQ_COMPANY_NAME"]),
            "crm.requisite.add": {"result": 501},
        })
        result = self.service(client).ensure_requisite("77", "АО Ромашка", self.VALID_INN)

        self.assertEqual(result.status, "created")


    def test_no_preset_template_is_a_clear_error_not_invented(self):
        client = _FakeClient({
            "crm.requisite.list": {"result": []},
            "crm.requisite.preset.list": {"result": []},
        })
        result = self.service(client).ensure_requisite("77", "АО Ромашка", self.VALID_INN)

        self.assertEqual(result.status, "error")
        self.assertIsNotNone(result.error)
        self.assertNotIn("crm.requisite.add", client.methods_called())

    def test_no_template_error_states_it_is_a_portal_setting_not_a_retry_case(self):
        """Ре-ревью координатора: текст ошибки обязан прямо говорить, что
        нужна настройка портала, а не временный сбой — иначе человек будет
        жать «Повторить» бесконечно. Тут отсутствие шаблона ПОДТВЕРЖДЕНО —
        crm.requisite.preset.list честно отработал и отдал пустой список."""
        client = _FakeClient({
            "crm.requisite.list": {"result": []},
            "crm.requisite.preset.list": {"result": []},
        })
        result = self.service(client).ensure_requisite("77", "АО Ромашка", self.VALID_INN)

        self.assertIn("не настроен", result.error)
        self.assertIn("не поможет", result.error)

    def test_verification_failure_error_states_retry_may_help_not_a_portal_setting(self):
        """Второй раунд ре-ревью координатора (задача на вычитание, см.
        inn-trim-report.md): сетевой сбой crm.requisite.preset.list — НЕ то
        же самое, что подтверждённое отсутствие подходящего шаблона. Раньше
        текст ошибки был один на оба случая и ВСЕГДА обвинял настройку
        портала — здесь портал мог быть настроен верно, сообщение обязано
        звать повторить, а не отправлять администратора чинить то, что не
        сломано. Сравни с test_no_template_error_states_it_is_a_portal_
        setting_not_a_retry_case выше — тот же метод падает по другой
        причине и обязан дать ДРУГОЙ текст."""
        client = _FakeClient({
            "crm.requisite.list": {"result": []},
            "crm.requisite.preset.list": RuntimeError("сеть недоступна"),
        })
        result = self.service(client).ensure_requisite("77", "АО Ромашка", self.VALID_INN)

        self.assertEqual(result.status, "error")
        self.assertNotIn("crm.requisite.add", client.methods_called())
        self.assertNotIn("не настроен", result.error)
        self.assertNotIn("не поможет", result.error)
        self.assertIn("Не удалось проверить", result.error)

    def test_preset_list_malformed_response_is_error_not_crash(self):
        client = _FakeClient({
            "crm.requisite.list": {"result": []},
            "crm.requisite.preset.list": {"result": ["garbage", "strings"]},
        })
        result = self.service(client).ensure_requisite("77", "АО Ромашка", self.VALID_INN)

        self.assertEqual(result.status, "error")
        self.assertNotIn("crm.requisite.add", client.methods_called())
        self.assertNotIn("не настроен", result.error)
        self.assertNotIn("не поможет", result.error)

    def test_preset_list_bitrix_failure_is_error_not_crash(self):
        client = _FakeClient({
            "crm.requisite.list": {"result": []},
            "crm.requisite.preset.list": RuntimeError("сеть недоступна"),
        })
        result = self.service(client).ensure_requisite("77", "АО Ромашка", self.VALID_INN)

        self.assertEqual(result.status, "error")

    def test_existing_requisite_with_same_inn_is_found_not_recreated(self):
        client = _FakeClient({
            "crm.requisite.list": {"result": [{"ID": "900", "ENTITY_ID": "77", "RQ_INN": self.VALID_INN}]},
        })
        result = self.service(client).ensure_requisite("77", "АО Ромашка", self.VALID_INN)

        self.assertEqual(result.status, "found")
        self.assertEqual(result.id, "900")
        self.assertNotIn("crm.requisite.add", client.methods_called())
        self.assertNotIn("crm.requisite.preset.list", client.methods_called())

    def test_existing_requisite_with_different_inn_does_not_block_creation(self):
        client = _FakeClient({
            "crm.requisite.list": {"result": [{"ID": "900", "ENTITY_ID": "77", "RQ_INN": "9999999999"}]},
            "crm.requisite.preset.list": self._preset_response([self._active_preset("5")]),
            "crm.requisite.preset.field.list": self._field_list_response(["RQ_INN"]),
            "crm.requisite.add": {"result": 501},
        })
        result = self.service(client).ensure_requisite("77", "АО Ромашка", self.VALID_INN)

        self.assertEqual(result.status, "created")

    def test_idempotency_check_is_scoped_to_this_company(self):
        client = _FakeClient({
            "crm.requisite.list": {"result": []},
            "crm.requisite.preset.list": self._preset_response([self._active_preset("5")]),
            "crm.requisite.preset.field.list": self._field_list_response(["RQ_INN"]),
            "crm.requisite.add": {"result": 501},
        })
        self.service(client).ensure_requisite("77", "АО Ромашка", self.VALID_INN)

        method, params = client.calls[0]
        self.assertEqual(method, "crm.requisite.list")
        self.assertEqual(params["filter"]["ENTITY_TYPE_ID"], 4)
        self.assertEqual(params["filter"]["ENTITY_ID"], 77)

    def test_idempotency_check_malformed_response_is_error_not_crash(self):
        client = _FakeClient({"crm.requisite.list": {"result": {"unexpected": "shape"}}})
        result = self.service(client).ensure_requisite("77", "АО Ромашка", self.VALID_INN)

        self.assertEqual(result.status, "error")
        self.assertNotIn("crm.requisite.add", client.methods_called())

    def test_idempotency_check_bitrix_failure_is_error_not_crash(self):
        client = _FakeClient({"crm.requisite.list": RuntimeError("нет прав")})
        result = self.service(client).ensure_requisite("77", "АО Ромашка", self.VALID_INN)

        self.assertEqual(result.status, "error")

    def test_add_failure_becomes_error_status(self):
        client = _FakeClient({
            "crm.requisite.list": {"result": []},
            "crm.requisite.preset.list": self._preset_response([self._active_preset("5")]),
            "crm.requisite.preset.field.list": self._field_list_response(["RQ_INN"]),
            "crm.requisite.add": RuntimeError("поле не найдено"),
        })
        result = self.service(client).ensure_requisite("77", "АО Ромашка", self.VALID_INN)

        self.assertEqual(result.status, "error")
        self.assertIn("поле не найдено", result.error)

    def test_add_without_valid_id_becomes_error(self):
        client = _FakeClient({
            "crm.requisite.list": {"result": []},
            "crm.requisite.preset.list": self._preset_response([self._active_preset("5")]),
            "crm.requisite.preset.field.list": self._field_list_response(["RQ_INN"]),
            "crm.requisite.add": {"result": ""},
        })
        result = self.service(client).ensure_requisite("77", "АО Ромашка", self.VALID_INN)

        self.assertEqual(result.status, "error")

    def test_blank_inn_is_skipped_no_bitrix_calls(self):
        client = _FakeClient()
        result = self.service(client).ensure_requisite("77", "АО Ромашка", "")

        self.assertEqual(result.status, "skipped")
        self.assertEqual(client.methods_called(), [])

    def test_blank_company_id_is_skipped_no_bitrix_calls(self):
        client = _FakeClient()
        result = self.service(client).ensure_requisite("", "АО Ромашка", self.VALID_INN)

        self.assertEqual(result.status, "skipped")
        self.assertEqual(client.methods_called(), [])

    def test_preset_lookup_is_cached_across_calls(self):
        client = _FakeClient({
            "crm.requisite.list": {"result": []},
            "crm.requisite.preset.list": self._preset_response([self._active_preset("5")]),
            "crm.requisite.preset.field.list": self._field_list_response(["RQ_INN"]),
            "crm.requisite.add": {"result": 501},
        })
        service = self.service(client)
        service.ensure_requisite("77", "АО Ромашка", self.VALID_INN)
        service.ensure_requisite("78", "АО Вторая", "7736050003")

        # Кэшируется РЕЗУЛЬТАТ разрешения — ни preset.list, ни per-кандидатная
        # проверка RQ_INN не повторяются на второй вызов.
        self.assertEqual(client.methods_called().count("crm.requisite.preset.list"), 1)
        self.assertEqual(client.methods_called().count("crm.requisite.preset.list"), 1)


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


def _resolved_fields(*, stage_options=None, **overrides):
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
        stage_options=stage_options if stage_options is not None else [{"id": "DT180_7:NEW", "title": "Новый"}],
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

    def test_automatic_only_stage_options_do_not_reach_the_crm_card(self):
        """Блокер 1 финального ревью (полная цепочка, а не только

        resolve_project_fields): если stage_options на момент создания
        проекта деградировали до одних автостадий (сбой живого запроса
        статусов воронки к Битриксу — см. докстринг _first_manual_stage_id в
        project_creation_defaults.py), карточка CRM клиента не должна
        получить stage_id вовсе. Автостадия в поле карточки роняла бы её в
        автоколонку воронки, откуда её не вытащить мышью.
        """
        service = self.service(_FakeClient())
        degenerate_stage_options = [
            {"id": "Нет списаний 1 месяц", "title": "Нет списаний 1 месяц", "kind": "auto", "can_drop": False},
            {"id": "Нет списаний 3 месяца", "title": "Нет списаний 3 месяца", "kind": "auto", "can_drop": False},
        ]
        fields = _resolved_fields(stage_options=degenerate_stage_options)
        self.assertEqual(fields.stage, "")

        built = service.build_card_fields(fields, "44", _MAPPING)
        self.assertNotIn("stageId", built)


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
            "crm.requisite.list": {"result": []},
            "crm.requisite.preset.list": {"result": [
                {"ID": "5", "ENTITY_TYPE_ID": "4", "NAME": "Российская компания", "ACTIVE": "Y"}
            ]},
            "crm.requisite.preset.field.list": {"result": {"RQ_INN": {}, "RQ_COMPANY_NAME": {}}},
            "crm.requisite.add": {"result": 501},
            "sonet_group.get": {"result": []},
            "sonet_group.create": {"result": 44},
            "crm.item.list": {"result": {"items": []}},
            "crm.item.add": {"result": {"item": {"id": 901}}},
        }
        responses.update(overrides)
        return _FakeClient(responses)

    def _form(self, **overrides):
        form = {
            "project_name": "Портал АО Ромашка",
            "company_name": "АО Ромашка",
            # ИНН обязателен при создании новой компании (company_id не
            # передан) — решение заказчика 29.07.2026, inn-brief.md.
            "inn": "7707083893",
        }
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
        self.assertEqual(result["requisite"]["status"], "created")
        self.assertEqual(result["group"]["status"], "created")
        self.assertEqual(result["card"]["status"], "created")
        self.assertTrue(result["done"])
        self.assertEqual(ProjectCard.objects.filter(project_id="44").count(), 1)

    def test_repeat_call_does_not_create_second_entities(self):
        client = self._client(
            **{
                "crm.company.list": {"result": [{"ID": "77", "TITLE": "АО Ромашка"}]},
                # Реквизит с этим ИНН у этой компании уже есть (первый вызов
                # его записал) — идемпотентная проверка ensure_requisite
                # обязана найти его и не создавать заново (тот же принцип,
                # что и у company/group/card ниже).
                "crm.requisite.list": {"result": [
                    {"ID": "900", "ENTITY_ID": "77", "RQ_INN": "7707083893"}
                ]},
                "sonet_group.get": {"result": [{"ID": "44", "NAME": "Портал АО Ромашка"}]},
                "crm.item.list": {"result": {"items": [{"id": 901}]}},
            }
        )
        result = self._create(client)

        self.assertEqual(result["company"]["status"], "found")
        self.assertEqual(result["requisite"]["status"], "found")
        self.assertEqual(result["group"]["status"], "found")
        self.assertEqual(result["card"]["status"], "found")
        self.assertTrue(result["done"])
        for method in ("crm.company.add", "crm.requisite.add", "sonet_group.create", "crm.item.add"):
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
        # Компания не резолвилась — реквизиту нечего делать, шаг не пытался
        # (см. ранний return в _create_under_lock).
        self.assertEqual(result["requisite"]["status"], "skipped")
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

    def test_missing_inn_stops_before_any_bitrix_call_when_creating_new_company(self):
        # Сквозная (не только на уровне resolve_project_fields — см.
        # tests_project_creation_defaults.InnRequirementTest) проверка: без
        # ИНН при создании новой компании create() обязан остановиться на
        # missing_fields, ничего не создав и не изменив в Битриксе (не 500,
        # см. inn-brief.md "Битый ИНН — понятная ошибка, а не 500"). Ссылочные
        # чтения (config/legal_entities/stage_options) происходят раньше
        # проверки missing — так же, как и в
        # test_missing_required_fields_stop_before_any_bitrix_call выше, —
        # поэтому здесь, как и там, проверяется отсутствие МУТИРУЮЩИХ вызовов,
        # а не пустой журнал вызовов целиком.
        client = self._client()
        result = self._create(client, form={"project_name": "Портал", "company_name": "АО Ромашка"})

        self.assertIn("inn", result["missing_fields"])
        self.assertFalse(result["done"])
        for method in ("crm.company.add", "crm.requisite.add", "sonet_group.create", "crm.item.add"):
            self.assertNotIn(method, client.methods_called())

    def test_invalid_inn_stops_before_any_bitrix_call(self):
        # "٧٧٠٧٠٨٣٨٩٣" — аравийско-индийские цифры того же числа 7707083893,
        # что и валидный ИНН по умолчанию в _form() выше: та же ловушка, что
        # и в tests_inn_validation.test_unicode_digit_lookalikes_are_rejected_
        # not_crash, но здесь проверяется сквозной путь (значит, ASCII-
        # ограничение реально останавливает Bitrix-вызовы, а не только сам
        # validate_inn). Контрольная сумма сознательно не проверяется
        # (см. докстринг inn_validation.py) — поэтому пример невалидности
        # обязан быть про состав символов, не про контрольную цифру.
        client = self._client()
        result = self._create(
            client,
            form={"project_name": "Портал", "company_name": "АО Ромашка", "inn": "٧٧٠٧٠٨٣٨٩٣"},
        )

        self.assertIn("inn", result["missing_fields"])
        self.assertFalse(result["done"])
        for method in ("crm.company.add", "crm.requisite.add", "sonet_group.create", "crm.item.add"):
            self.assertNotIn(method, client.methods_called())

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
            "crm.requisite.list": {"result": []},
            "crm.requisite.preset.list": {"result": [
                {"ID": "5", "ENTITY_TYPE_ID": "4", "NAME": "Российская компания", "ACTIVE": "Y"}
            ]},
            "crm.requisite.preset.field.list": {"result": {"RQ_INN": {}, "RQ_COMPANY_NAME": {}}},
            "crm.requisite.add": {"result": 501},
            "sonet_group.get": {"result": []},
            "sonet_group.create": {"result": 44},
            "crm.item.list": {"result": {"items": []}},
            "crm.item.add": {"result": {"item": {"id": 901}}},
        }
        responses.update(overrides)
        return _FakeClient(responses)

    def _form(self, **overrides):
        form = {
            "project_name": "Портал АО Ромашка",
            "company_name": "АО Ромашка",
            "inn": "7707083893",
        }
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
        self.assertEqual(result["requisite"]["status"], "skipped")
        self.assertEqual(result["group"]["status"], "skipped")
        self.assertEqual(result["card"]["status"], "skipped")
        self.assertFalse(result["done"])
        self.assertEqual(result["missing_fields"], [])
        # Лок берётся до первого шага, а не после — ни один мутирующий или
        # поисковый вызов ensure_* не должен был случиться.
        for method in (
            "crm.company.add", "crm.requisite.list", "crm.requisite.add",
            "sonet_group.get", "sonet_group.create", "crm.item.list", "crm.item.add",
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


class RequisiteOrchestrationTest(_ServiceTestCase):
    """Реквизит (ИНН) как шаг оркестратора create() — inn-brief.md, разделы
    «Реквизит — отдельный шаг со своим статусом» и «Оценка» (новый режим
    частичного отказа). Юнит-тесты самого шага — в EnsureRequisiteTest выше;
    здесь — его место в create()/_create_under_lock: когда он вызывается,
    как влияет на done, и ключевой сценарий ретрая из брифа."""

    def setUp(self):
        super().setUp()
        cache.clear()

    def _client(self, **overrides):
        responses = {
            "app.option.get": {"result": {"timestamp_config": (
                '{"hourly_rate": 1500, "project_sp_entity_type_id": 180,'
                ' "project_fields_mapping": {"title": "title",'
                ' "bitrix_group_id": "ufCrm7Group", "stage_id": "stageId"}}'
            )}},
            "crm.company.list": {"result": []},
            "crm.company.add": {"result": 77},
            "crm.requisite.list": {"result": []},
            "crm.requisite.preset.list": {"result": [
                {"ID": "5", "ENTITY_TYPE_ID": "4", "NAME": "Российская компания", "ACTIVE": "Y"}
            ]},
            "crm.requisite.preset.field.list": {"result": {"RQ_INN": {}, "RQ_COMPANY_NAME": {}}},
            "crm.requisite.add": {"result": 501},
            "sonet_group.get": {"result": []},
            "sonet_group.create": {"result": 44},
            "crm.item.list": {"result": {"items": []}},
            "crm.item.add": {"result": {"item": {"id": 901}}},
        }
        responses.update(overrides)
        return _FakeClient(responses)

    def _form(self, **overrides):
        form = {
            "project_name": "Портал АО Ромашка",
            "company_name": "АО Ромашка",
            "inn": "7707083893",
        }
        form.update(overrides)
        return form

    def _create(self, client, form=None):
        return self.service(client).create(
            form or self._form(), current_user_id="42", current_user_name="Петров Иван",
            today=date(2026, 7, 28),
        )

    def test_requisite_step_runs_and_creates_after_new_company(self):
        result = self._create(self._client())

        self.assertEqual(result["company"]["status"], "created")
        self.assertEqual(result["requisite"]["status"], "created")
        self.assertTrue(result["done"])

    def test_requisite_step_is_skipped_for_existing_company_selected_by_id(self):
        client = self._client()
        result = self._create(
            client,
            form={"project_name": "Портал АО Ромашка", "company_id": "15", "company_name": "АО Ромашка"},
        )

        self.assertEqual(result["company"]["status"], "found")
        self.assertEqual(result["requisite"]["status"], "skipped")
        self.assertTrue(result["done"])
        for method in ("crm.requisite.list", "crm.requisite.preset.list", "crm.requisite.add"):
            self.assertNotIn(method, client.methods_called())

    def test_requisite_failure_does_not_block_group_and_card_but_clears_done(self):
        client = self._client(**{"crm.requisite.add": RuntimeError("нет прав на реквизиты")})
        result = self._create(client)

        self.assertEqual(result["company"]["status"], "created")
        self.assertEqual(result["requisite"]["status"], "error")
        self.assertEqual(result["group"]["status"], "created")
        self.assertEqual(result["card"]["status"], "created")
        self.assertFalse(result["done"])
        # Компания и группа реально созданы в Битриксе несмотря на сбой
        # реквизита — откатывать их нельзя (inn-brief.md, "новый режим
        # частичного отказа").
        self.assertEqual(ProjectCard.objects.filter(project_id="44").count(), 1)

    def test_no_preset_template_creates_company_but_flags_requisite_error(self):
        client = self._client(**{"crm.requisite.preset.list": {"result": []}})
        result = self._create(client)

        self.assertEqual(result["company"]["status"], "created")
        self.assertEqual(result["requisite"]["status"], "error")
        self.assertIsNotNone(result["requisite"]["error"])
        self.assertFalse(result["done"])
        # Компания не откатывается — остаётся созданной в CRM клиента.
        self.assertIsNotNone(result["company"]["id"])
        self.assertNotIn("crm.requisite.add", client.methods_called())

    def test_retry_after_requisite_failure_writes_missing_requisite_without_second_company(self):
        """Ключевой сценарий брифа: "компания создана, реквизит нет" — повтор
        не создаёт вторую компанию (шаг 2 ensure_company найдёт её по точному
        названию, раз по ИНН реквизита ещё нет ни у кого), но обязан дописать
        реквизит."""
        first_client = self._client(**{"crm.requisite.add": RuntimeError("временный сбой сети")})
        first_result = self._create(first_client)
        self.assertEqual(first_result["company"]["status"], "created")
        self.assertEqual(first_result["requisite"]["status"], "error")

        # Повтор: crm.requisite.list (поиск по ИНН в ensure_company) по-прежнему
        # пуст — реквизит так и не был записан, — компания находится по точному
        # названию (шаг 2), а реквизит на этот раз обязан дописаться.
        second_client = self._client(**{
            "crm.company.list": {"result": [{"ID": "77", "TITLE": "АО Ромашка"}]},
        })
        second_result = self._create(second_client)

        self.assertEqual(second_result["company"]["status"], "found")
        self.assertEqual(second_result["requisite"]["status"], "created")
        self.assertTrue(second_result["done"])
        self.assertNotIn("crm.company.add", second_client.methods_called())

    def test_repeat_call_after_full_success_does_not_recreate_anything(self):
        first_result = self._create(self._client())
        self.assertEqual(first_result["requisite"]["status"], "created")

        # Повтор: компания находится по ИНН (реквизит из первого вызова уже
        # существует — тот же crm.requisite.list отвечает и на поиск компании
        # в ensure_company, и на идемпотентную проверку в ensure_requisite:
        # _FakeClient различает ответы только по имени метода, не по фильтру
        # (см. докстринг _FakeClient в начале файла).
        second_client = self._client(**{
            "crm.requisite.list": {"result": [
                {"ID": "900", "ENTITY_ID": "77", "RQ_INN": "7707083893"}
            ]},
            "crm.company.list": {"result": [{"ID": "77", "TITLE": "АО Ромашка"}]},
        })
        second_result = self._create(second_client)

        self.assertEqual(second_result["company"]["status"], "found")
        self.assertEqual(second_result["requisite"]["status"], "found")
        self.assertTrue(second_result["done"])
        for method in ("crm.company.add", "crm.requisite.add"):
            self.assertNotIn(method, second_client.methods_called())


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
            "crm.requisite.list": {"result": []},
            "crm.requisite.preset.list": {"result": [
                {"ID": "5", "ENTITY_TYPE_ID": "4", "NAME": "Российская компания", "ACTIVE": "Y"}
            ]},
            "crm.requisite.preset.field.list": {"result": {"RQ_INN": {}, "RQ_COMPANY_NAME": {}}},
            "crm.requisite.add": {"result": 501},
            "sonet_group.get": {"result": []},
            "sonet_group.create": {"result": 44},
            "crm.item.list": {"result": {"items": []}},
            "crm.item.add": {"result": {"item": {"id": 901}}},
        }
        responses.update(overrides)
        return _FakeClient(responses)

    def _form(self, **overrides):
        form = {
            "project_name": "Портал АО Ромашка",
            "company_name": "АО Ромашка",
            "inn": "7707083893",
        }
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

    @override_settings(USE_PORTAL_SCOPING=True)
    def test_already_on_board_branch_still_invalidates_the_calling_accounts_cache(self):
        """Ре-ревью task-9-cache-fix-report.md: ветка already_on_board (строку
        для этого project_id уже написал ДРУГОЙ аккаунт того же портала —
        редкая гонка двух почти одновременных создателей, см. докстринг
        create()) не сбрасывала кэш ЭТОГО (self.account) аккаунта, хотя
        exists() только что подтвердил, что локальная строка гарантированно
        уже есть — просто её создал не он.

        Симптом идентичен основному багу: у кэша каждого аккаунта СВОЙ ключ
        (build_account_cache_key), и если доска сотрудника Б прогрелась ДО
        того, как коллега А дописал проект, кнопка Б отчитается успехом
        (done=True, get_project_board_create и до фикса, и после — карточка
        уже есть), а доска Б останется пустой до истечения
        PROJECT_BOARD_CACHE_TTL. Кто из двух сотрудников попадёт в эту ветку —
        вопрос гонки, но человек в моменте не знает, что попал в редкий путь:
        он просто видит, что кнопка соврала.

        Portal/USE_PORTAL_SCOPING=True — как и в
        CreateOrchestrationConcurrencyTest.test_second_account_same_portal_does_not_duplicate_local_row,
        без них already_on_board недостижима: scope_to_tenant(account) без
        portal падает на скоуп по одному аккаунту, и один аккаунт никогда не
        увидит строку другого."""
        portal = Portal.objects.create(
            member_id="m-create-cache-race", domain_url="cache-race.bitrix24.ru", status="active",
        )
        account_a = Bitrix24Account.objects.create(
            b24_user_id=30, is_b24_user_admin=True, member_id="m-create-cache-race",
            is_master_account=True, domain_url="cache-race.bitrix24.ru",
            status="active", application_version=1, portal=portal,
        )
        account_b = Bitrix24Account.objects.create(
            b24_user_id=31, is_b24_user_admin=False, member_id="m-create-cache-race",
            is_master_account=False, domain_url="cache-race.bitrix24.ru",
            status="active", application_version=1, portal=portal,
        )

        board_service_b = ProjectCardService(self._client(), account_b)
        # Сотрудник Б открыл доску РАНЬШЕ, чем коллега А создал проект —
        # кэш аккаунта Б прогревается пустым снимком.
        warm_b = board_service_b.get_board_data()
        self.assertEqual(warm_b["cards"], [])

        # Коллега А создаёт проект с нуля (обычный happy path).
        result_a = ProjectCreationService(self._client(), account_a).create(
            self._form(), current_user_id="10", current_user_name="Коллега А",
            today=date(2026, 7, 28),
        )
        self.assertTrue(result_a["done"])
        self.assertEqual(ProjectCard.objects.filter(portal=portal, project_id="44").count(), 1)

        # Сотрудник Б тоже нажимает «Создать проект» — попадает на уже
        # существующие компанию/группу/карточку (все found), локальную
        # строку уже написал А: already_on_board=True для Б, write_through
        # для Б не вызывается.
        client_b = self._client(**{
            "crm.company.list": {"result": [{"ID": "77", "TITLE": "АО Ромашка"}]},
            "sonet_group.get": {"result": [{"ID": "44", "NAME": "Портал АО Ромашка"}]},
            "crm.item.list": {"result": {"items": [{"id": 901}]}},
        })
        result_b = ProjectCreationService(client_b, account_b).create(
            self._form(), current_user_id="11", current_user_name="Сотрудник Б",
            today=date(2026, 7, 28),
        )
        self.assertEqual(result_b["company"]["status"], "found")
        self.assertEqual(result_b["group"]["status"], "found")
        self.assertTrue(result_b["done"])
        # Дедуп сработал: вторая строка не появилась, дубля на доске нет.
        self.assertEqual(ProjectCard.objects.filter(portal=portal, project_id="44").count(), 1)

        # Доска сотрудника Б обязана немедленно показать проект коллеги —
        # не через PROJECT_BOARD_CACHE_TTL.
        board_b = board_service_b.get_board_data()
        project_ids = [card["project_id"] for card in board_b["cards"]]
        self.assertIn(
            "44", project_ids,
            "Кэш аккаунта Б не сброшен в ветке already_on_board — проект коллеги не виден.",
        )
