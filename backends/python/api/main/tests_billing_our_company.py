"""Наше юрлицо счёта: настройка приложения против карточки проекта.

Зачем настройка вообще нужна. До неё юрлицо счёта бралось из
``ProjectCard.our_legal_entity_id``, а карточки приходят с портала
синхронизацией: правка в нашей БД не живёт дольше следующего обмена. На
боевом портале там оказались идентификаторы компаний, своими юрлицами не
являющихся, — и счёт уходил бы от них.

Что здесь закрепляется:

1. Настройка ПЕРЕКРЫВАЕТ карточку — и в документе, и в полях смарт-счёта.
2. Без настройки поведение прежнее, до единого REST-вызова: сверка своих
   компаний портала не должна появляться там, где её раньше не было.
3. Фильтр ``our_company_id`` при заданной настройке остаётся фильтром ОТБОРА
   и состав счёта не меняет (решение — в докстринге BillingFilter).
4. Негодное юрлицо останавливает выставление кодом ``our_company_missing``
   ДО того, как на портале появится счёт без реквизитов.
5. Недоступный портал не превращается в «юрлица не существует».
"""

from unittest.mock import patch

from django.core.cache import cache

from .billing_service import (
    ERROR_OUR_COMPANY_MISSING,
    OUR_COMPANY_FROM_PROJECT_CARD,
    OUR_COMPANY_FROM_SETTINGS,
    BillingError,
)
from .models import BillingDocument, ProjectCard
from .tests_billing_endpoints import BillingEndpointFixture, FakePortal
from .tests_billing_selection import CLOSED_SETTINGS, BillingFixture


def settings_with(our_company_id, our_company_name=""):
    """Настройки счёта с заданным нашим юрлицом."""
    return {
        **CLOSED_SETTINGS,
        "our_company_id": our_company_id,
        "our_company_name": our_company_name,
    }


class ResolveOurCompanyTest(BillingFixture):
    """Выбор юрлица без портала: чистая логика «настройка или карточка»."""

    def resolve(self, settings=None, **filter_kwargs):
        service = self.service(settings)
        filters = self.filters(**filter_kwargs)
        return service.resolve_our_company(service.collect(filters), filters)

    def test_without_setting_entity_comes_from_project_card(self):
        self.entry(1)

        our_company = self.resolve()

        self.assertEqual(our_company.id, "7")
        self.assertEqual(our_company.name, "ООО Майнсофт")
        self.assertEqual(our_company.source, OUR_COMPANY_FROM_PROJECT_CARD)

    def test_setting_overrides_project_card(self):
        self.entry(1)

        our_company = self.resolve(settings_with("68", "Мейнсофт"))

        self.assertEqual(our_company.id, "68")
        self.assertEqual(our_company.name, "Мейнсофт")
        self.assertEqual(our_company.source, OUR_COMPANY_FROM_SETTINGS)
        self.assertTrue(our_company.from_settings)

    def test_setting_without_name_falls_back_to_id(self):
        """Название в настройке — снимок для интерфейса, id — обязателен.

        Пустое название не делает настройку незаданной: подпись деградирует
        до идентификатора, а юрлицо всё равно берётся из настройки.
        """
        self.entry(1)

        our_company = self.resolve(settings_with("68"))

        self.assertEqual(our_company.id, "68")
        self.assertEqual(our_company.label, "68")
        self.assertEqual(our_company.source, OUR_COMPANY_FROM_SETTINGS)

    def test_blank_setting_keeps_project_card(self):
        self.entry(1)

        our_company = self.resolve(settings_with("   ", "Мейнсофт"))

        self.assertEqual(our_company.id, "7")
        self.assertEqual(our_company.source, OUR_COMPANY_FROM_PROJECT_CARD)

    def test_filter_picks_card_entity_when_setting_is_empty(self):
        """Без настройки фильтр по-прежнему выбирает юрлицо из карточек."""
        ProjectCard.objects.filter(project_id="88").update(
            our_legal_entity_id="9", our_legal_entity_name="ООО Второе",
            company_id="15", company_name="ООО Клиент",
        )
        self.entry(1)
        self.entry(2, project_id="88")

        our_company = self.resolve(our_company_id="9")

        self.assertEqual(our_company.id, "9")
        self.assertEqual(our_company.name, "ООО Второе")

    def test_filter_still_narrows_selection_when_setting_is_set(self):
        """Настройка отвечает «от кого», фильтр — «какие часы». Это разное.

        Игнорировать фильтр при заданной настройке нельзя: сохранение
        настройки молча втянуло бы в счёт часы всех остальных юрлиц карточек.
        """
        ProjectCard.objects.filter(project_id="88").update(
            our_legal_entity_id="9", our_legal_entity_name="ООО Второе",
            company_id="15", company_name="ООО Клиент",
        )
        self.entry(1)
        self.entry(2, project_id="88")

        service = self.service(settings_with("68", "Мейнсофт"))
        filters = self.filters(our_company_id="9")
        selection = service.collect(filters)

        self.assertEqual([row["timesheet_bitrix_id"] for row in selection.entries], [2])
        self.assertEqual(service.resolve_our_company(selection, filters).id, "68")

    def test_preview_payload_names_the_source(self):
        self.entry(1)

        service = self.service(settings_with("68", "Мейнсофт"))
        filters = self.filters()
        selection = service.collect(filters)
        payload = selection.as_payload(service.resolve_our_company(selection, filters))

        self.assertEqual(payload["our_company_id"], "68")
        self.assertEqual(payload["our_company_name"], "Мейнсофт")
        self.assertEqual(payload["our_company_source"], OUR_COMPANY_FROM_SETTINGS)
        # Юрлица КАРТОЧЕК остаются в ответе: интерфейс показывает ими, что
        # именно подменяется настройкой.
        self.assertEqual(payload["our_companies"], [{"id": "7", "name": "ООО Майнсофт"}])

    def test_preview_payload_source_without_setting(self):
        self.entry(1)

        service = self.service()
        filters = self.filters()
        selection = service.collect(filters)
        payload = selection.as_payload(service.resolve_our_company(selection, filters))

        self.assertEqual(payload["our_company_id"], "7")
        self.assertEqual(payload["our_company_source"], OUR_COMPANY_FROM_PROJECT_CARD)

    def test_empty_entity_has_no_source(self):
        """Ни настройки, ни юрлица в карточке — источника нет, а не «карточка»."""
        ProjectCard.objects.filter(project_id="73").update(
            our_legal_entity_id="", our_legal_entity_name="",
        )
        self.entry(1)

        service = self.service()
        filters = self.filters()
        selection = service.collect(filters)
        payload = selection.as_payload(service.resolve_our_company(selection, filters))

        self.assertEqual(payload["our_company_id"], "")
        self.assertEqual(payload["our_company_source"], "")


class VerifyOurCompanyTest(BillingFixture):
    """Сверка заданного настройкой юрлица со своими компаниями портала."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

    def service_with_portal(self, settings, payload):
        service = self.service(settings)
        patcher = patch(
            "main.company_search_service.CompanySearchService.list_my_companies",
            return_value=payload,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return service

    def our_company(self, settings):
        service = self.service(settings)
        filters = self.filters()
        return service.resolve_our_company(service.collect(filters), filters)

    def test_card_entity_is_not_verified(self):
        """Юрлицо карточки пришло с портала — отдельной сверки не требует.

        Заодно это сохраняет прежнее поведение при незаданной настройке: без
        неё выставление не платит лишним REST-вызовом.
        """
        self.entry(1)
        calls = []
        service = self.service()
        with patch(
            "main.company_search_service.CompanySearchService.list_my_companies",
            side_effect=lambda *a, **kw: calls.append(1) or {"companies": [], "failed": False},
        ):
            result = service.verify_our_company(self.our_company(CLOSED_SETTINGS))

        self.assertEqual(calls, [])
        self.assertEqual(result.id, "7")

    def test_known_entity_takes_its_name_from_the_portal(self):
        """В настройке лежит снимок названия, в счёт идёт текущее."""
        self.entry(1)
        service = self.service_with_portal(
            settings_with("68", "Старое название"),
            {"companies": [{"id": "68", "name": "Мейнсофт"}], "failed": False},
        )

        result = service.verify_our_company(self.our_company(settings_with("68", "Старое название")))

        self.assertEqual(result.id, "68")
        self.assertEqual(result.name, "Мейнсофт")
        self.assertEqual(result.source, OUR_COMPANY_FROM_SETTINGS)

    def test_unknown_entity_is_rejected_with_code(self):
        self.entry(1)
        service = self.service_with_portal(
            settings_with("2568", "Не наше"),
            {"companies": [{"id": "68", "name": "Мейнсофт"}], "failed": False},
        )

        with self.assertRaises(BillingError) as caught:
            service.verify_our_company(self.our_company(settings_with("2568", "Не наше")))

        self.assertEqual(caught.exception.code, ERROR_OUR_COMPANY_MISSING)
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(caught.exception.extra["our_company_id"], "2568")

    def test_portal_failure_does_not_block_issuing(self):
        """failed=True — «не доверяй полноте списка», а не «юрлица нет».

        Отказать здесь значило бы запретить выставление из-за чужой
        недоступности: настройку выбирали из этого же списка, когда он
        отвечал.
        """
        self.entry(1)
        service = self.service_with_portal(
            settings_with("68", "Мейнсофт"),
            {"companies": [], "failed": True},
        )

        result = service.verify_our_company(self.our_company(settings_with("68", "Мейнсофт")))

        self.assertEqual(result.id, "68")
        self.assertEqual(result.name, "Мейнсофт")

    def test_exception_from_portal_does_not_block_issuing(self):
        self.entry(1)
        service = self.service(settings_with("68", "Мейнсофт"))
        with patch(
            "main.company_search_service.CompanySearchService.list_my_companies",
            side_effect=RuntimeError("сеть"),
        ):
            result = service.verify_our_company(self.our_company(settings_with("68", "Мейнсофт")))

        self.assertEqual(result.id, "68")


class IssueWithOurCompanySettingTest(BillingEndpointFixture):
    """Выставление через эндпоинт: документ, смарт-счёт, отказы."""

    def test_setting_goes_into_document_and_invoice(self):
        self.entry(1)
        self.close_august()
        self.billing_settings.update({"our_company_id": "68", "our_company_name": "Мейнсофт"})

        response = self.post("/api/billing/documents", self.default_filter())

        self.assertEqual(response.status_code, 201)
        document = BillingDocument.objects.get()
        self.assertEqual(document.our_company_id, "68")
        self.assertEqual(document.our_company_name, "Мейнсофт")
        # Карточка проекта говорит «7» — в счёт ушло юрлицо настройки.
        self.assertEqual(self.portal.sent_invoice_fields["mycompanyId"], 68)
        self.assertIn("crm.company.list", self.portal.methods())

    def test_document_name_is_refreshed_from_the_portal(self):
        self.entry(1)
        self.close_august()
        self.billing_settings.update({
            "our_company_id": "68", "our_company_name": "Мейнсофт (старое)",
        })

        self.post("/api/billing/documents", self.default_filter())

        self.assertEqual(BillingDocument.objects.get().our_company_name, "Мейнсофт")

    def test_without_setting_behaviour_is_unchanged(self):
        self.entry(1)
        self.close_august()

        response = self.post("/api/billing/documents", self.default_filter())

        self.assertEqual(response.status_code, 201)
        document = BillingDocument.objects.get()
        self.assertEqual(document.our_company_id, "7")
        self.assertEqual(document.our_company_name, "ООО Майнсофт")
        self.assertEqual(self.portal.sent_invoice_fields["mycompanyId"], 7)
        # Прежний порядок вызовов сохранён: сверки своих компаний нет.
        self.assertNotIn("crm.company.list", self.portal.methods())

    def test_unknown_setting_blocks_issuing_before_the_invoice(self):
        self.entry(1)
        self.close_august()
        self.billing_settings.update({"our_company_id": "2568", "our_company_name": ""})

        response = self.post("/api/billing/documents", self.default_filter())

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], ERROR_OUR_COMPANY_MISSING)
        # Ни документа у нас, ни счёта на портале: отказ пришёл до записи.
        self.assertEqual(BillingDocument.objects.count(), 0)
        self.assertNotIn("crm.item.add", self.portal.methods())

    def test_unavailable_portal_list_still_issues(self):
        self.entry(1)
        self.close_august()
        self.billing_settings.update({"our_company_id": "68", "our_company_name": "Мейнсофт"})
        self.portal.my_companies = []
        self.portal.errors["crm.company.list"] = RuntimeError("портал недоступен")

        response = self.post("/api/billing/documents", self.default_filter())

        self.assertEqual(response.status_code, 201)
        self.assertEqual(BillingDocument.objects.get().our_company_id, "68")

    def test_preview_reports_the_source(self):
        self.entry(1)
        self.billing_settings.update({"our_company_id": "68", "our_company_name": "Мейнсофт"})

        data = self.post("/api/billing/preview", self.default_filter()).json()

        self.assertEqual(data["our_company_id"], "68")
        self.assertEqual(data["our_company_source"], OUR_COMPANY_FROM_SETTINGS)

    def test_preview_does_not_touch_the_portal(self):
        """Предпросмотр — чтение: сверять юрлицо на портале он не должен.

        Негодная настройка обязана упереться в «Выставить», а не лишить
        человека строк и сумм, которые он пришёл проверить.
        """
        self.entry(1)
        self.billing_settings.update({"our_company_id": "2568", "our_company_name": ""})

        response = self.post("/api/billing/preview", self.default_filter())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.portal.methods(), [])


class FakePortalMyCompaniesTest(BillingEndpointFixture):
    """Двойник портала отдаёт свои юрлица в форме crm.company.list."""

    def test_portal_answers_my_companies(self):
        portal = FakePortal(my_companies=[{"ID": "68", "TITLE": "Мейнсофт"}])

        result = portal.call("crm.company.list", {"filter": {"IS_MY_COMPANY": "Y"}})

        self.assertEqual(result["result"], [{"ID": "68", "TITLE": "Мейнсофт"}])
