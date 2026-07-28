"""Тесты ProjectCardService.serialize_card: одиночная карточка не должна
тянуть весь справочник компаний ради одного ИНН.

Хотфикс 2026-07-28: HAR с боевого портала — /api/project-board/card висел
218с и отдавал 502, потому что serialize_card() для ОДНОЙ карточки обходил
весь справочник Bitrix (23 252 компании, crm.company.list + crm.item.list, и
16 382 реквизита, crm.requisite.list) ради имени и ИНН одной компании, хотя
имя уже лежит в card.company_name. См.
backends/python/api/main/project_board_service.py:serialize_card.

Путь доски (get_board_data, много карточек в цикле) обязан сохранить старое
поведение: справочник компаний/юрлиц загружается один раз на всю доску и
передаётся в serialize_card явно через именованные параметры
companies=/legal_entities=. Одиночный путь (get_card_data,
update_project_card, update_stage, archive_project) эти параметры не
передаёт — тогда serialize_card идёт по точечному пути через новый метод
_resolve_reference_details_single (без общего обхода справочника).

Паттерн _FakeClient — как в tests_user_sync_service.py (call_method +
_bitrix_token = self), с добавленным журналом вызовов по методам.
"""
from django.core.cache import cache
from django.test import TestCase

from .models import Bitrix24Account, ProjectCard
from .project_board_service import ProjectCardService


class _FakeClient:
    """Минимальный двойник Client: логирует все вызовы call_method и отдаёт
    заранее настроенный ответ по имени метода Bitrix.

    responses: Dict[method_name, response] — response может быть:
      - dict (статичный ответ, например {"result": [...]})
      - Exception (будет поднято при вызове этого метода)
    Методы без записи в responses отвечают {"result": []} (как реальный
    Bitrix на пустой список) — см. tests_user_sync_service.py.
    """

    def __init__(self, responses=None):
        self._responses = dict(responses or {})
        self.calls = []  # List[Tuple[str, dict]]
        self._bitrix_token = self

    def call_method(self, method, params):
        self.calls.append((method, dict(params)))
        response = self._responses.get(method, {"result": []})
        if isinstance(response, Exception):
            raise response
        return response

    def calls_for(self, method):
        return [params for called_method, params in self.calls if called_method == method]

    def call_count(self, method):
        return len(self.calls_for(method))


def _requisite_response(entity_id, inn):
    return {"result": [{"ENTITY_ID": str(entity_id), "RQ_INN": inn}]}


class _FakeClientByEntityId(_FakeClient):
    """Вариант _FakeClient для crm.requisite.list: ИНН зависит от ENTITY_ID в
    фильтре запроса (а не фиксированный ответ по имени метода) — нужен, чтобы
    проверить, что компания и юрлицо резолвятся НЕЗАВИСИМЫМИ вызовами."""

    def __init__(self, inn_by_entity_id):
        super().__init__()
        self._inn_by_entity_id = dict(inn_by_entity_id)

    def call_method(self, method, params):
        self.calls.append((method, dict(params)))
        if method != "crm.requisite.list":
            return {"result": []}
        entity_id = params.get("filter", {}).get("ENTITY_ID")
        inn = self._inn_by_entity_id.get(entity_id)
        if inn is None:
            return {"result": []}
        return _requisite_response(entity_id, inn)


class ProjectCardServiceSerializeCardSingleTest(TestCase):
    """Одиночный путь: get_card_data / update_project_card / update_stage /
    archive_project — все зовут serialize_card(card) без companies=/
    legal_entities=."""

    def setUp(self):
        cache.clear()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-serialize-1",
            is_master_account=True, domain_url="serialize.bitrix24.ru",
            status="active", application_version=1,
        )

    def _make_card(self, **overrides):
        defaults = dict(
            bitrix24_account=self.account,
            project_id="p-1",
            project_name="Проект Один",
            stage="Новый",
            manual_stage="Новый",
            is_archived=False,
            company_id="555",
            company_name="ООО Клиент",
        )
        defaults.update(overrides)
        return ProjectCard.objects.create(**defaults)

    # 1. Одиночная карточка не обходит справочник целиком.
    def test_single_card_does_not_call_full_directory_methods(self):
        client = _FakeClient({"crm.requisite.list": _requisite_response("555", "7701234567")})
        service = ProjectCardService(client, self.account)
        card = self._make_card()

        service.serialize_card(card)

        self.assertEqual(client.call_count("crm.company.list"), 0)
        self.assertEqual(client.call_count("crm.item.list"), 0)

    # 2. ИНН запрашивается ровно одним вызовом crm.requisite.list, фильтр по конкретному ENTITY_ID.
    def test_single_card_fetches_inn_with_single_requisite_call(self):
        client = _FakeClient({"crm.requisite.list": _requisite_response("555", "7701234567")})
        service = ProjectCardService(client, self.account)
        card = self._make_card()

        result = service.serialize_card(card)

        self.assertEqual(client.call_count("crm.requisite.list"), 1)
        params = client.calls_for("crm.requisite.list")[0]
        self.assertEqual(params["filter"]["ENTITY_ID"], 555)
        self.assertEqual(result["company_inn"], "7701234567")

    # 3. Имя компании берётся из card.company_name, без обращения к Битрикс.
    def test_company_name_comes_from_card_without_bitrix_call(self):
        client = _FakeClient({"crm.requisite.list": _requisite_response("555", "7701234567")})
        service = ProjectCardService(client, self.account)
        card = self._make_card(company_name="ООО Ромашка Сервис")

        result = service.serialize_card(card)

        self.assertEqual(result["company_name"], "ООО Ромашка Сервис")
        self.assertEqual(client.call_count("crm.company.list"), 0)
        self.assertEqual(client.call_count("crm.item.list"), 0)

    # 4. Пустой company_id — за реквизитами/справочником в Битрикс не ходим
    # вообще, ИНН None. (get_project_stage_lookup() дергает app.option.get
    # независимо от company_id — это существующее поведение вне зоны этого
    # хотфикса, поэтому проверяем именно методы резолва компании/юрлица.)
    def test_empty_company_id_skips_bitrix_entirely(self):
        client = _FakeClient()
        service = ProjectCardService(client, self.account)
        card = self._make_card(company_id=None, company_name=None)

        result = service.serialize_card(card)

        self.assertEqual(client.call_count("crm.requisite.list"), 0)
        self.assertEqual(client.call_count("crm.company.list"), 0)
        self.assertEqual(client.call_count("crm.item.list"), 0)
        self.assertIsNone(result["company_id"])
        self.assertIsNone(result["company_inn"])

    # 5. Сбой crm.requisite.list не роняет карточку — ИНН None, исключение наружу не летит.
    def test_requisite_lookup_failure_does_not_raise(self):
        client = _FakeClient({"crm.requisite.list": RuntimeError("bitrix timeout")})
        service = ProjectCardService(client, self.account)
        card = self._make_card()

        result = service.serialize_card(card)  # не должно бросить исключение

        self.assertIsNone(result["company_inn"])
        self.assertEqual(result["company_id"], "555")
        self.assertEqual(result["company_name"], "ООО Клиент")

    # 6. Повторная сериализация той же карточки не делает второго запроса за ИНН.
    def test_repeated_serialize_uses_cached_inn(self):
        client = _FakeClient({"crm.requisite.list": _requisite_response("555", "7701234567")})
        service = ProjectCardService(client, self.account)
        card = self._make_card()

        first = service.serialize_card(card)
        second = service.serialize_card(card)

        self.assertEqual(client.call_count("crm.requisite.list"), 1)
        self.assertEqual(first["company_inn"], "7701234567")
        self.assertEqual(second["company_inn"], "7701234567")

    # 7. Компания без ИНН: отрицательный результат тоже кэшируется.
    def test_missing_inn_is_cached_negatively(self):
        client = _FakeClient({"crm.requisite.list": {"result": []}})
        service = ProjectCardService(client, self.account)
        card = self._make_card()

        first = service.serialize_card(card)
        second = service.serialize_card(card)

        self.assertIsNone(first["company_inn"])
        self.assertIsNone(second["company_inn"])
        self.assertEqual(client.call_count("crm.requisite.list"), 1)

    # Доп: тот же точечный путь применяется и к своему юрлицу (our_legal_entity_*),
    # каждая ссылка резолвится независимым вызовом с СВОИМ ENTITY_ID в фильтре.
    def test_legal_entity_resolved_via_single_lookup_independently(self):
        client = _FakeClientByEntityId({
            555: "7701234567",
            777: "5004001122",
        })

        service = ProjectCardService(client, self.account)
        card = self._make_card(our_legal_entity_id="777", our_legal_entity_name="ООО Наша Компания")

        result = service.serialize_card(card)

        self.assertEqual(result["company_inn"], "7701234567")
        self.assertEqual(result["our_legal_entity_inn"], "5004001122")
        self.assertEqual(result["our_legal_entity_name"], "ООО Наша Компания")
        self.assertEqual(client.call_count("crm.requisite.list"), 2)

    # --- Fix-round: пустое card.company_name должно резолвиться точечным
    # crm.company.list, а не сразу деградировать до идентификатора (регресс
    # найден при ревью: старый _resolve_reference_details умел взять имя из
    # справочника при пустом card.company_name, новый _resolve_reference_
    # details_single сразу подставлял id — узкий, но реальный случай, когда
    # синк не заполняет company_name). ---

    # 1. Имя в карточке заполнено -> crm.company.list не вызывается вообще.
    def test_single_card_name_present_skips_company_list_lookup(self):
        client = _FakeClient({"crm.requisite.list": _requisite_response("555", "7701234567")})
        service = ProjectCardService(client, self.account)
        card = self._make_card(company_name="ООО Клиент")

        result = service.serialize_card(card)

        self.assertEqual(result["company_name"], "ООО Клиент")
        self.assertEqual(client.call_count("crm.company.list"), 0)

    # 2. Имя пустое, company_id заполнен -> ровно один вызов crm.company.list,
    # в фильтре ID этой компании, TITLE из ответа попадает в результат.
    def test_single_card_empty_name_fetches_via_single_company_list_call(self):
        client = _FakeClient({
            "crm.requisite.list": _requisite_response("555", "7701234567"),
            "crm.company.list": {"result": [{"ID": "555", "TITLE": "АО Ромашка"}]},
        })
        service = ProjectCardService(client, self.account)
        card = self._make_card(company_name=None)

        result = service.serialize_card(card)

        self.assertEqual(client.call_count("crm.company.list"), 1)
        params = client.calls_for("crm.company.list")[0]
        self.assertEqual(params["filter"]["ID"], 555)
        self.assertEqual(result["company_name"], "АО Ромашка")

    # 3. Имя пустое, Битрикс вернул пусто -> идентификатор в результате,
    # отрицательный результат закэширован, второй вызов не идёт в Битрикс.
    def test_single_card_empty_name_bitrix_empty_degrades_to_id_and_caches(self):
        client = _FakeClient({
            "crm.requisite.list": _requisite_response("555", "7701234567"),
            "crm.company.list": {"result": []},
        })
        service = ProjectCardService(client, self.account)
        card = self._make_card(company_name=None)

        first = service.serialize_card(card)
        second = service.serialize_card(card)

        self.assertEqual(first["company_name"], "555")
        self.assertEqual(second["company_name"], "555")
        self.assertEqual(client.call_count("crm.company.list"), 1)

    # 4. Имя пустое, crm.company.list бросает исключение -> карточка не падает,
    # имя деградирует до id, ошибка НЕ кэшируется (повторный вызов снова идёт
    # в Битрикс — симметрично поведению точечного лукапа ИНН).
    def test_single_card_empty_name_lookup_failure_degrades_without_caching(self):
        client = _FakeClient({
            "crm.requisite.list": _requisite_response("555", "7701234567"),
            "crm.company.list": RuntimeError("bitrix timeout"),
        })
        service = ProjectCardService(client, self.account)
        card = self._make_card(company_name=None)

        first = service.serialize_card(card)  # не должно бросить исключение
        second = service.serialize_card(card)

        self.assertEqual(first["company_name"], "555")
        self.assertEqual(second["company_name"], "555")
        self.assertEqual(client.call_count("crm.company.list"), 2)

    # Форма ответа (набор ключей) не меняется относительно текущего API.
    def test_response_shape_keys_unchanged(self):
        client = _FakeClient({"crm.requisite.list": _requisite_response("555", "7701234567")})
        service = ProjectCardService(client, self.account)
        card = self._make_card()

        result = service.serialize_card(card)

        expected_keys = {
            "id", "project_item_id", "project_id", "project_name", "stage", "manual_stage",
            "is_archived", "archived_at", "project_hours_budget", "hourly_rate", "is_support",
            "curator_user_id", "curator_name", "project_start_date", "project_end_date",
            "company_id", "company_name", "company_inn", "our_legal_entity_id",
            "our_legal_entity_name", "our_legal_entity_inn", "last_writeoff_at",
            "last_writeoff_days", "stage_source", "created_at", "updated_at",
        }
        self.assertEqual(set(result.keys()), expected_keys)


class ProjectCardServiceSerializeCardBoardPathTest(TestCase):
    """Путь доски: get_board_data передаёт заранее загруженные справочники —
    точечных запросов на карточку быть не должно, поведение как раньше."""

    def setUp(self):
        cache.clear()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=2, is_b24_user_admin=True, member_id="m-serialize-board-1",
            is_master_account=True, domain_url="serialize-board.bitrix24.ru",
            status="active", application_version=1,
        )

    def _make_card(self, **overrides):
        defaults = dict(
            bitrix24_account=self.account,
            project_id="p-1",
            project_name="Проект Один",
            stage="Новый",
            manual_stage="Новый",
            is_archived=False,
            company_id="555",
            company_name="ООО Клиент",
        )
        defaults.update(overrides)
        return ProjectCard.objects.create(**defaults)

    # 8. serialize_card(card, companies=[...], legal_entities=[...]) берёт ИНН из
    # переданного списка и не делает запроса crm.requisite.list.
    def test_board_path_uses_passed_companies_without_requisite_call(self):
        client = _FakeClient({"crm.requisite.list": _requisite_response("555", "SHOULD-NOT-BE-USED")})
        service = ProjectCardService(client, self.account)
        card = self._make_card()
        companies = [{"id": "555", "name": "ООО Клиент из справочника", "inn": "9998887766"}]

        result = service.serialize_card(card, companies=companies, legal_entities=[])

        self.assertEqual(result["company_inn"], "9998887766")
        self.assertEqual(client.call_count("crm.requisite.list"), 0)

    # Fix-round: путь доски резолвит имя из переданного справочника даже при
    # пустом card.company_name — точечный лукап имени (crm.company.list) не
    # должен вызываться, когда companies= передан явно.
    def test_board_path_name_resolution_unaffected_by_point_lookup(self):
        client = _FakeClient({
            "crm.company.list": {"result": [{"ID": "555", "TITLE": "ДОЛЖНО-НЕ-ИСПОЛЬЗОВАТЬСЯ"}]},
        })
        service = ProjectCardService(client, self.account)
        card = self._make_card(company_name=None)
        companies = [{"id": "555", "name": "ООО Клиент из справочника", "inn": "9998887766"}]

        result = service.serialize_card(card, companies=companies, legal_entities=[])

        self.assertEqual(result["company_name"], "ООО Клиент из справочника")
        self.assertEqual(client.call_count("crm.company.list"), 0)

    # 9. get_board_data загружает справочники один раз, а не на каждую карточку.
    def test_get_board_data_loads_companies_once_for_multiple_cards(self):
        client = _FakeClient()
        service = ProjectCardService(client, self.account)
        for i in range(3):
            self._make_card(project_id=f"p-{i}", project_name=f"Проект {i}")

        companies_counter = {"count": 0}
        legal_entities_counter = {"count": 0}
        original_get_companies = service.get_companies
        original_get_legal_entities = service.get_legal_entities

        def counting_get_companies(*args, **kwargs):
            companies_counter["count"] += 1
            return original_get_companies(*args, **kwargs)

        def counting_get_legal_entities(*args, **kwargs):
            legal_entities_counter["count"] += 1
            return original_get_legal_entities(*args, **kwargs)

        service.get_companies = counting_get_companies
        service.get_legal_entities = counting_get_legal_entities

        board = service.get_board_data()

        self.assertEqual(companies_counter["count"], 1)
        self.assertEqual(legal_entities_counter["count"], 1)
        self.assertEqual(len(board["cards"]), 3)

    # Доп: количество карточек не влияет на число вызовов get_companies (5 карточек — тоже 1 раз).
    def test_get_board_data_loads_companies_once_regardless_of_card_count(self):
        client = _FakeClient()
        service = ProjectCardService(client, self.account)
        for i in range(5):
            self._make_card(project_id=f"p-many-{i}", project_name=f"Проект Много {i}")

        companies_counter = {"count": 0}
        original_get_companies = service.get_companies

        def counting_get_companies(*args, **kwargs):
            companies_counter["count"] += 1
            return original_get_companies(*args, **kwargs)

        service.get_companies = counting_get_companies

        board = service.get_board_data()

        self.assertEqual(companies_counter["count"], 1)
        self.assertEqual(len(board["cards"]), 5)
