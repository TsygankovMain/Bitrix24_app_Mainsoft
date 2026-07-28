"""Тесты источников справочников: пользовательские пути не обходят портал."""
from django.core.cache import cache
from django.test import TestCase

from .inn_backfill_service import InnBackfillService
from .models import Bitrix24Account, ProjectCard
from .project_board_service import ProjectCardService
from .project_board_shared import invalidate_project_runtime_caches
from .tenant_scoping import scope_to_tenant


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
        # Фикс-раунд ревью: исходный тест не заводил ни одной ProjectCard, поэтому
        # доказывал только "не упало", а не "фолбэк вернул то самое юрлицо" — он
        # остался бы зелёным и при полностью сломанном фолбэке. Ошибка в брифе,
        # не в реализации; чинится здесь.
        ProjectCard.objects.create(
            bitrix24_account=self.account,
            project_id="p-fallback-1",
            project_name="Проект с юрлицом",
            stage="Новый",
            manual_stage="Новый",
            our_legal_entity_id="9",
            our_legal_entity_name="ООО Резерв",
        )
        client = _FakeClient({"crm.company.list": RuntimeError("нет прав")})
        entities = ProjectCardService(client, self.account).get_legal_entities()

        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]["id"], "9")
        self.assertEqual(entities[0]["name"], "ООО Резерв")


class LegalEntitiesCacheInvalidationTest(TestCase):
    """Фикс-раунд ревью (Important): принудительное обновление доски проектов

    (ProjectSyncService.sync -> invalidate_project_runtime_caches) чистит
    ТОЛЬКО внешний кэш "project-board-legal-entities". Источник данных теперь
    CompanySearchService.list_my_companies(), а у него СВОЙ отдельный кэш
    "my-companies" на 6 часов, про который invalidate_project_runtime_caches
    ничего не знает. Без bypass_cache админ жмёт "Обновить", получает 200 — и
    новое юрлицо всё равно не видно до 6 часов, хотя внешний кэш уже пуст.
    """

    def setUp(self):
        cache.clear()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=2, is_b24_user_admin=True, member_id="m-refs-2",
            is_master_account=True, domain_url="example2.bitrix24.ru",
            status="active", application_version=1,
        )

    def test_forced_refresh_bypasses_stale_inner_cache(self):
        client = _FakeClient({
            "crm.company.list": {"result": [{"ID": "1", "TITLE": "ООО Старое"}]},
        })
        service = ProjectCardService(client, self.account)

        first = service.get_legal_entities()
        self.assertEqual([e["id"] for e in first], ["1"])

        # В Битриксе завели новое юрлицо.
        client._responses["crm.company.list"] = {"result": [{"ID": "2", "TITLE": "ООО Новое"}]}

        # Ровно то, что делает ProjectSyncService.sync() при "Обновить":
        # сначала общая инвалидация project-board-кэшей аккаунта...
        invalidate_project_runtime_caches(self.account)
        # ...затем тёплый форс-рефреш с bypass_cache=True — единственное, что
        # пробивает ВНУТРЕННИЙ кэш list_my_companies (invalidate_project_runtime_caches
        # его не трогает и трогать не должен: суффиксный список — это связь по
        # имени, которую легко забыть при следующем кэше).
        second = service.get_legal_entities(bypass_cache=True)
        self.assertEqual([e["id"] for e in second], ["2"])

        # Внешний кэш теперь прогрет свежими данными форс-рефрешем — обычный
        # вызов без флага (как на следующей загрузке доски) видит их же, а не
        # старые "1" и не повторный вызов Битрикса.
        client.calls.clear()
        third = service.get_legal_entities()
        self.assertEqual([e["id"] for e in third], ["2"])
        self.assertEqual(client.methods_called(), [])


class CompaniesFromDbTest(TestCase):
    def setUp(self):
        cache.clear()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-refs-2",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        ProjectCard.objects.create(
            **scope_to_tenant(self.account, write=True),
            project_id="44", project_name="Портал АО Ромашка", stage="NEW",
            company_id="15", company_name="АО Ромашка",
        )

    def test_companies_come_from_project_cards_without_touching_bitrix(self):
        client = _FakeClient()
        companies = ProjectCardService(client, self.account).get_companies()

        self.assertEqual([c["id"] for c in companies], ["15"])
        self.assertEqual([c["name"] for c in companies], ["АО Ромашка"])
        self.assertEqual(client.methods_called(), [])

    def test_companies_keys_do_not_include_inn(self):
        """Фиксирует набор ключей get_companies() (ревью Task 3): локальная
        проекция карточек проектов не хранит ИНН вовсе (в таблице project_card
        такого поля нет), поэтому "inn" здесь не появится ни сейчас, ни
        случайно в будущем. Если это когда-нибудь изменится, тест должен
        упасть громко — а не позволить кому-то снова опереться на
        company["inn"] из get_companies() и тихо получить пустые строки,
        как это уже случилось с inn_backfill_service (см. Task 6 плана:
        дозаполнение ИНН намеренно вызывает get_full_company_directory(),
        а не этот метод)."""
        client = _FakeClient()
        companies = ProjectCardService(client, self.account).get_companies()

        self.assertEqual(len(companies), 1)
        self.assertEqual(set(companies[0].keys()), {"id", "name", "search_text"})
        self.assertNotIn("inn", companies[0])

    def test_no_project_cards_gives_empty_list_not_full_scan(self):
        ProjectCard.objects.all().delete()
        client = _FakeClient()
        companies = ProjectCardService(client, self.account).get_companies()

        self.assertEqual(companies, [])
        self.assertEqual(client.methods_called(), [])

    def test_other_portal_companies_are_not_visible(self):
        # Фикс-раунд ревью: исходный тест заводил второй портал вообще без
        # карточек и проверял пустоту результата — такой тест проходит и при
        # полностью сломанном фильтре (запрос без scope_to_tenant тоже даёт
        # [], пока у "чужого" портала нет ни одной строки в таблице). Заводим
        # карточки с РАЗНЫМИ компаниями на обоих порталах и проверяем, что
        # каждый видит только свою — это ловит утечку в любую сторону.
        other = Bitrix24Account.objects.create(
            b24_user_id=2, is_b24_user_admin=True, member_id="m-refs-3",
            is_master_account=True, domain_url="other.bitrix24.ru",
            status="active", application_version=1,
        )
        ProjectCard.objects.create(
            **scope_to_tenant(other, write=True),
            project_id="77", project_name="Портал ООО Чужой", stage="NEW",
            company_id="99", company_name="ООО Чужой",
        )

        own_companies = ProjectCardService(_FakeClient(), self.account).get_companies()
        other_companies = ProjectCardService(_FakeClient(), other).get_companies()

        self.assertEqual([c["id"] for c in own_companies], ["15"])
        self.assertEqual([c["id"] for c in other_companies], ["99"])

    def test_board_data_does_not_scan_the_portal(self):
        """get_board_data() не должен ОБХОДИТЬ портал: не должно быть ни
        постраничного справочника компаний (crm.item.list — первый метод в
        _fetch_companies_live), ни постраничного обхода реквизитов за ИНН
        (crm.requisite.list — _fetch_company_inn_map). Оба уходят вместе со
        старым get_companies().

        crm.company.list НЕ включён в список запрещённых методов: он законно
        вызывается один раз (без пагинации, с серверным фильтром
        IS_MY_COMPANY=Y) из get_legal_entities() — это уже сделанная и
        отревьюженная Task 2 плана, вне скоупа этой задачи ("Не трогай",
        см. бриф). Разница видна и по счётчику вызовов: до этой правки
        get_board_data() дёргал crm.company.list ДВАЖДЫ (второй раз — как
        второй метод внутри старого get_companies()/_fetch_companies_live),
        после — ровно один раз, от get_legal_entities().
        """
        client = _FakeClient()
        ProjectCardService(client, self.account).get_board_data()

        methods_called = client.methods_called()
        for method in ("crm.item.list", "crm.requisite.list"):
            self.assertNotIn(method, methods_called)
        self.assertEqual(methods_called.count("crm.company.list"), 1)

    def test_full_directory_is_still_available_for_admin_path(self):
        """Полный обход не удалён — он нужен дозаполнению ИНН, но вызывается
        только явно и никогда с пользовательского пути."""
        client = _FakeClient({
            "crm.company.list": {"result": [{"ID": "15", "TITLE": "АО Ромашка"}]},
        })
        directory = ProjectCardService(client, self.account).get_full_company_directory()

        self.assertEqual([c["id"] for c in directory], ["15"])


class InnBackfillUsesFullDirectoryTest(TestCase):
    """Task 6 плана ("вне очереди", блокирует выкатку ветки): get_companies()
    после Task 3 читает локальную проекцию карточек и не отдаёт ИНН вовсе (в
    project_card такого поля нет). Дозаполнению ИНН (inn_backfill_service.py)
    нужен явный полный обход портала — единственное место во всём приложении,
    которому обход разрешён. Все пользовательские пути (доска/meta/главный
    экран/резолверы имён — см. остальные тесты этого файла) обход НЕ
    выполняют; здесь, наоборот, обход обязателен и ожидаем."""

    def setUp(self):
        cache.clear()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-refs-inn-1",
            is_master_account=True, domain_url="example-inn.bitrix24.ru",
            status="active", application_version=1,
        )
        # Карточка с той же компанией/юрлицом, что в фейковом ответе Битрикса
        # ниже — воспроизводит ровно репро ревьюера: до этой правки
        # get_companies()/get_legal_entities() отдали бы {'15': ''} / {'9': ''}
        # (ключи есть — из этой карточки, значения ИНН пусты, т.к. в
        # project_card ИНН не хранится).
        ProjectCard.objects.create(
            **scope_to_tenant(self.account, write=True),
            project_id="44", project_name="Портал АО Ромашка", stage="NEW",
            company_id="15", company_name="АО Ромашка",
            our_legal_entity_id="9", our_legal_entity_name="ООО Свои",
        )

    def _service(self, client):
        cfg = {"sp_entity_type_id": 123, "fields_mapping": {
            "our_inn": "UF_OUR", "client_inn": "UF_CLIENT"}}
        return InnBackfillService(client, self.account, cfg)

    def test_inn_maps_performs_full_scan_not_local_list(self):
        client = _FakeClient({
            "crm.item.list": {"result": [
                {"id": "15", "title": "АО Ромашка", "isMyCompany": "N"},
                {"id": "9", "title": "ООО Свои", "isMyCompany": "Y"},
            ]},
            "crm.requisite.list": {"result": [
                {"ENTITY_ID": "15", "RQ_INN": "7701234567"},
                {"ENTITY_ID": "9", "RQ_INN": "7709876543"},
            ]},
        })

        companies_inn, legal_inn = self._service(client)._inn_maps()

        # ИНН резолвится через полный обход. До этой правки _inn_maps()
        # звал get_companies()/get_legal_entities() — оба после Task 3 не
        # отдают "inn" вовсе, и карты были бы {'15': ''} / {'9': ''}
        # (ревьюер подтвердил прогоном: resolve_card_inn(...) -> ('', '')).
        self.assertEqual(companies_inn.get("15"), "7701234567")
        self.assertEqual(legal_inn.get("9"), "7709876543")
        # "Чужая" (не своя) компания попадает в общий справочник компаний,
        # но не в юрлица — is_my_company=N её отсеивает.
        self.assertNotIn("15", legal_inn)

        # Постраничный обход РЕАЛЬНО произошёл — здесь, в отличие от всех
        # пользовательских путей этого файла, это ожидаемо и правильно:
        # это разовое админское действие с экрана настроек, которому
        # действительно нужен весь справочник компаний с реквизитами.
        methods_called = client.methods_called()
        self.assertIn("crm.item.list", methods_called)
        self.assertIn("crm.requisite.list", methods_called)
