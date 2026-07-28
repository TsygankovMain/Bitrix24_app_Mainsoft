"""Тесты источников справочников: пользовательские пути не обходят портал."""
from django.core.cache import cache
from django.test import TestCase

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

    def test_no_project_cards_gives_empty_list_not_full_scan(self):
        ProjectCard.objects.all().delete()
        client = _FakeClient()
        companies = ProjectCardService(client, self.account).get_companies()

        self.assertEqual(companies, [])
        self.assertEqual(client.methods_called(), [])

    def test_other_portal_companies_are_not_visible(self):
        other = Bitrix24Account.objects.create(
            b24_user_id=2, is_b24_user_admin=True, member_id="m-refs-3",
            is_master_account=True, domain_url="other.bitrix24.ru",
            status="active", application_version=1,
        )
        companies = ProjectCardService(_FakeClient(), other).get_companies()

        self.assertEqual(companies, [])

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
