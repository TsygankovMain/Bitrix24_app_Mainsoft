"""Выбор шаблона генератора документов: список, права, сохранение, печать счёта.

Почему эти тесты вообще есть. До них шаблон акта задавался числом
``billing_act_template_id`` в конфигурации приложения, и узнать это число
можно было только запросом к порталу руками. Список шаблонов при этом
приложение УЖЕ умело читать — но читало с фильтром
``filter: {entityTypeId: 31}``, который на живом портале (nfr-mainsoft,
проверено 12.09.2026) обнуляет выборку: 0 шаблонов при любом значении
фильтра против 21 шаблона без фильтра. Двойник портала в
tests_billing_endpoints фильтр игнорировал, поэтому ловушка тестами не
ловилась.

Поэтому здесь двойник ПРИДИРЧИВЫЙ: он падает, если приложение пришло со
фильтром по entityTypeId, и отвечает в той же форме, что живой портал —
словарём по id, без поля entityTypeId в list и с ним в get.
"""

import json

from django.core.cache import cache
from django.test import Client, TestCase
from django.utils import timezone
from unittest.mock import patch

from .billing_crm_service import BillingCrmService
from .billing_service import BillingError
from .models import BillingDocument, Bitrix24Account, PortalFeature


# Живой ответ crm.documentgenerator.template.list (nfr-mainsoft, 12.09.2026),
# сокращённый до трёх шаблонов. Все значения — строками, как их отдаёт портал.
PORTAL_TEMPLATES = {
    "2": {
        "id": "2", "active": "Y", "name": "Акт (Россия)", "code": "ACT_RU",
        "region": "ru", "sort": "100", "numeratorId": "2", "withStamps": "N",
        "productsTableVariant": "service", "isDeleted": "N", "isDefault": "Y",
    },
    "4": {
        "id": "4", "active": "Y", "name": "Счет (Россия)", "code": "BILL_RU",
        "region": "ru", "sort": "200", "numeratorId": "4", "withStamps": "N",
        "productsTableVariant": "", "isDeleted": "N", "isDefault": "N",
    },
    "42": {
        "id": "42", "active": "Y", "name": "Тест", "code": None,
        "region": "ru", "sort": "300", "numeratorId": "0", "withStamps": "N",
        "productsTableVariant": "", "isDeleted": "Y", "isDefault": "N",
    },
}


class PortalError(Exception):
    """Ошибка портала так, как её видит приложение: разбор идёт по тексту."""


class TemplatePortal:
    """Двойник портала для шаблонов генератора документов.

    Отвечает в живой форме: list — словарь по id БЕЗ entityTypeId, get —
    объект В обёртке "template" и С entityTypeId вида "31_2".
    """

    def __init__(self, *, templates=None, list_error=None, get_error=None, document=None):
        self.templates = PORTAL_TEMPLATES if templates is None else templates
        self.list_error = list_error
        self.get_error = get_error
        self.document = document if document is not None else {
            "id": 36, "number": "1", "title": "Счет (Россия) 1",
            "downloadUrl": "https://portal/download/36",
            # publicUrl и pdfUrl портал в первом ответе отдаёт null: PDF
            # собирается асинхронно, и пустая ссылка здесь не ошибка.
            "publicUrl": None, "pdfUrl": None,
        }
        self.calls = []
        self.options = {}

    def call(self, method, params):
        self.calls.append((method, params))

        if method == "app.option.get":
            return {"result": dict(self.options)}
        if method == "app.option.set":
            self.options.update(params.get("options") or {})
            return {"result": True}
        if method == "crm.documentgenerator.template.list":
            if self.list_error:
                raise self.list_error
            # Фильтр по entityTypeId на живом портале обнуляет выборку —
            # приложение не имеет права его посылать.
            assert "entityTypeId" not in (params.get("filter") or {}), (
                "template.list получил фильтр по entityTypeId — на портале он обнуляет выборку"
            )
            return {"result": {"templates": dict(self.templates)}, "total": len(self.templates)}
        if method == "crm.documentgenerator.template.get":
            if self.get_error:
                raise self.get_error
            row = self.templates.get(str(params.get("id")))
            if not row:
                raise PortalError("Шаблон не найден")
            payload = dict(row)
            payload["entityTypeId"] = ["2_category_0", "31_2"]
            return {"result": {"template": payload}}
        if method == "crm.documentgenerator.document.add":
            return {"result": {"document": dict(self.document)}}
        raise AssertionError(f"TemplatePortal: неожиданный метод {method}")

    def methods(self):
        return [method for method, _ in self.calls]


class FakeToken:
    def __init__(self, portal):
        self.portal = portal

    def call_method(self, method, params=None):
        return self.portal.call(method, params or {})


class FakeClient:
    def __init__(self, portal):
        self._bitrix_token = FakeToken(portal)


class TemplateFixture(TestCase):
    def setUp(self):
        cache.clear()
        self.portal = TemplatePortal()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-tpl",
            is_master_account=True, domain_url="tpl.bitrix24.ru",
            status="active", application_version=1,
        )
        self.token = self.account.create_jwt_token()
        self._client_patch = patch.object(
            Bitrix24Account, "client", property(lambda _self: FakeClient(self.portal)),
        )
        self._client_patch.start()
        self.addCleanup(self._client_patch.stop)

    def service(self):
        return BillingCrmService(self.account, client=FakeClient(self.portal))

    def get(self, path, token=None):
        return Client().get(path, HTTP_AUTHORIZATION=f"Bearer {token or self.token}")

    def post(self, path, body=None, token=None):
        return Client().post(
            path, data=json.dumps(body or {}), content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token or self.token}",
        )


class TemplateListParsingTest(TemplateFixture):
    """Разбор того, что портал реально отдаёт на template.list."""

    def test_zapros_idet_bez_filtra_po_entity_type(self):
        self.service().list_templates()

        method, params = self.portal.calls[-1]
        self.assertEqual(method, "crm.documentgenerator.template.list")
        self.assertEqual(params, {})

    def test_slovar_po_id_razbiraetsya_s_flagami(self):
        templates = {row["id"]: row for row in self.service().list_templates()}

        self.assertEqual(sorted(templates), [2, 4])
        self.assertEqual(templates[2]["name"], "Акт (Россия)")
        self.assertEqual(templates[2]["code"], "ACT_RU")
        self.assertIs(templates[2]["is_default"], True)
        self.assertIs(templates[2]["active"], True)
        self.assertEqual(templates[2]["numerator_id"], 2)
        self.assertEqual(templates[2]["products_table_variant"], "service")
        self.assertIs(templates[4]["is_default"], False)

    def test_udalennyj_shablon_ne_popadaet_v_vybor(self):
        """isDeleted = Y отбрасывается: выбрать его — отложить ошибку печати."""
        ids = [row["id"] for row in self.service().list_templates()]

        self.assertNotIn(42, ids)

    def test_otsutstvie_entity_type_ne_vybrasyvaet_shablony(self):
        """В ответе list поля entityTypeId нет — это не причина вернуть пусто."""
        self.assertTrue(self.service().list_templates())

    def test_chuzhaya_privyazka_otbrasyvaetsya_esli_portal_ee_prislal(self):
        """Портал, который привязку всё-таки отдаёт, обязан быть услышан."""
        portal = TemplatePortal(templates={
            "2": {"id": "2", "name": "Акт (Россия)", "entityTypeId": ["31_2"]},
            "9": {"id": "9", "name": "Договор", "entityTypeId": ["2_category_0"]},
        })
        service = BillingCrmService(self.account, client=FakeClient(portal))

        self.assertEqual([row["id"] for row in service.list_templates()], [2])


class TemplateGetTest(TemplateFixture):
    def test_get_otdaet_shablon(self):
        self.assertEqual(self.service().get_template(4)["code"], "BILL_RU")

    def test_udalennyj_shablon_daet_ponyatnyj_kod(self):
        with self.assertRaises(BillingError) as ctx:
            self.service().get_template(99999)

        self.assertEqual(ctx.exception.code, "billing_template_not_found")
        self.assertIn("выберите шаблон заново", ctx.exception.message.lower())

    def test_nedostupnyj_metod_ne_putaetsya_s_udalennym_shablonom(self):
        portal = TemplatePortal(get_error=PortalError("Method not found"))
        service = BillingCrmService(self.account, client=FakeClient(portal))

        with self.assertRaises(BillingError) as ctx:
            service.get_template(4)

        self.assertEqual(ctx.exception.code, "documentgenerator_unavailable")


class TemplatesEndpointTest(TemplateFixture):
    def test_spisok_otdaetsya_adminu(self):
        response = self.get("/api/billing/templates")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual([row["id"] for row in data["templates"]], [2, 4])

    def test_bez_prav_403(self):
        """Не админ и не «Бухгалтерия» — тот же гейт, что у выставления."""
        other = Bitrix24Account.objects.create(
            b24_user_id=99, is_b24_user_admin=False, member_id="m-tpl",
            is_master_account=False, domain_url="tpl.bitrix24.ru",
            status="active", application_version=1,
        )

        response = self.get("/api/billing/templates", token=other.create_jwt_token())

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "billing_forbidden")

    def test_buhgalteriya_vidit_spisok(self):
        other = Bitrix24Account.objects.create(
            b24_user_id=99, is_b24_user_admin=False, member_id="m-tpl",
            is_master_account=False, domain_url="tpl.bitrix24.ru",
            status="active", application_version=1,
        )
        with patch(
            "main.billing_settings.load_billing_settings",
            side_effect=lambda account, client=None: {"accountants": ["99"]},
        ):
            response = self.get("/api/billing/templates", token=other.create_jwt_token())

        self.assertEqual(response.status_code, 200)

    def test_pustoj_spisok_eto_ne_oshibka(self):
        """Шаблонов нет — 200 и пустой список: объясняет это интерфейс."""
        self.portal.templates = {}

        response = self.get("/api/billing/templates")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"templates": [], "total": 0})

    def test_nedostupnyj_generator_otdaet_kod(self):
        self.portal.list_error = PortalError("Method not found")

        response = self.get("/api/billing/templates")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "documentgenerator_unavailable")

    def test_metod_post_ne_prinimaetsya(self):
        self.assertEqual(self.post("/api/billing/templates").status_code, 405)


class TemplateSettingsSaveTest(TemplateFixture):
    """Сохранение выбранного шаблона и живая проверка, что он существует."""

    def save(self, config):
        return self.post("/api/configuration/save", {"config": config})

    def test_vybrannyj_shablon_sohranyaetsya(self):
        response = self.save({
            "billing_act_template_id": "2",
            "billing_invoice_template_id": 4,
        })

        self.assertEqual(response.status_code, 200)
        saved = json.loads(self.portal.options["timestamp_config"])
        # Строка из select'а обязана лечь числом: иначе «настройка
        # изменилась» срабатывало бы на каждом сохранении.
        self.assertEqual(saved["billing_act_template_id"], 2)
        self.assertEqual(saved["billing_invoice_template_id"], 4)

    def test_udalennyj_shablon_ne_sohranyaetsya(self):
        response = self.save({"billing_act_template_id": 777})

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["code"], "billing_template_not_found")
        self.assertEqual(payload["setting"], "billing_act_template_id")
        self.assertIn("Выберите другой шаблон", payload["error"])
        self.assertNotIn("timestamp_config", self.portal.options)

    def test_nezamenennyj_shablon_portal_ne_pereprashivaet(self):
        """Проверка живая, значит платная: делаем её только на изменение."""
        self.portal.options["timestamp_config"] = json.dumps({"billing_act_template_id": 2})
        self.portal.calls.clear()

        response = self.save({"billing_act_template_id": 2})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("crm.documentgenerator.template.get", self.portal.methods())

    def test_snyatie_shablona_ne_trebuet_proverki(self):
        self.portal.options["timestamp_config"] = json.dumps({"billing_act_template_id": 2})
        self.portal.calls.clear()

        response = self.save({"billing_act_template_id": 0})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("crm.documentgenerator.template.get", self.portal.methods())

    def test_storonnie_nastrojki_generator_ne_trogayut(self):
        """Сохранение чужой настройки не платит за проверку шаблонов."""
        response = self.save({"hourly_rate": 2000})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("crm.documentgenerator.template.get", self.portal.methods())

    def test_nedostupnyj_portal_ne_zapiraet_nastrojki(self):
        """Отключённый генератор документов — не повод не дать сохранить."""
        self.portal.get_error = PortalError("Method not found")

        response = self.save({"billing_act_template_id": 2})

        self.assertEqual(response.status_code, 200)
        saved = json.loads(self.portal.options["timestamp_config"])
        self.assertEqual(saved["billing_act_template_id"], 2)


class InvoicePrintTest(TemplateFixture):
    """Печатная форма самого счёта — вторая половина комплекта «счёт + акт»."""

    def document(self, **kwargs):
        fields = {
            "bitrix24_account": self.account,
            "status": BillingDocument.STATUS_ISSUED,
            "crm_entity_id": "4",
            "crm_account_number": "1",
            "total_hours": 4.0,
            "total_amount": 8000.0,
        }
        fields.update(kwargs)
        return BillingDocument.objects.create(**fields)

    def service_with_settings(self, **settings):
        from .billing_service import BillingService

        base = {"act_template_id": 0, "invoice_template_id": 0}
        base.update(settings)
        return BillingCrmService(
            self.account,
            client=FakeClient(self.portal),
            service=BillingService(self.account, client=FakeClient(self.portal), settings=base),
        )

    def test_bez_nastrojki_chestnyj_otkaz(self):
        """Шаблон счёта НЕ угадывается: под «счёт» подходят и счёт-фактура, и УПД."""
        with self.assertRaises(BillingError) as ctx:
            self.service_with_settings().print_invoice_document(self.document())

        self.assertEqual(ctx.exception.code, "invoice_template_missing")
        self.assertEqual(self.portal.methods(), [])

    def test_pechataet_i_zapominaet_ssylki(self):
        document = self.document()

        result = self.service_with_settings(invoice_template_id=4).print_invoice_document(document)

        self.assertEqual(result["invoice_document_id"], "36")
        document.refresh_from_db()
        self.assertEqual(document.invoice_document_id, "36")
        self.assertEqual(document.invoice_document_number, "1")
        self.assertEqual(document.invoice_download_url, "https://portal/download/36")
        # pdfUrl портал отдаёт null — пустая строка, а не "None".
        self.assertEqual(document.invoice_pdf_url, "")
        self.assertEqual(document.invoice_print_error, "")

    def test_nomer_i_data_beryutsya_ot_scheta(self):
        """У клиента не должно оказаться счёта с одним номером, а акта с другим."""
        self.service_with_settings(invoice_template_id=4).print_invoice_document(self.document())

        method, params = self.portal.calls[-1]
        self.assertEqual(method, "crm.documentgenerator.document.add")
        self.assertEqual(params["templateId"], 4)
        self.assertEqual(params["entityTypeId"], 31)
        self.assertEqual(params["entityId"], 4)
        self.assertEqual(params["values"]["DocumentNumber"], "1")
        self.assertEqual(
            params["values"]["DocumentDate"], timezone.localdate().strftime("%d.%m.%Y")
        )

    def test_shablon_iz_zaprosa_silnee_nastrojki(self):
        self.service_with_settings(invoice_template_id=4).print_invoice_document(
            self.document(), template_id=2
        )

        self.assertEqual(self.portal.calls[-1][1]["templateId"], 2)

    def test_otmenennyj_dokument_ne_pechataetsya(self):
        document = self.document(status=BillingDocument.STATUS_CANCELLED)

        with self.assertRaises(BillingError) as ctx:
            self.service_with_settings(invoice_template_id=4).print_invoice_document(document)

        self.assertEqual(ctx.exception.code, "document_cancelled")
        self.assertEqual(ctx.exception.status, 409)

    def test_dokument_bez_scheta_v_crm(self):
        with self.assertRaises(BillingError) as ctx:
            self.service_with_settings(invoice_template_id=4).print_invoice_document(
                self.document(crm_entity_id="")
            )

        self.assertEqual(ctx.exception.code, "crm_invoice_missing")


class InvoicePrintEndpointTest(TemplateFixture):
    def setUp(self):
        super().setUp()
        PortalFeature.objects.create(
            bitrix24_account=self.account, code=PortalFeature.CODE_BILLING,
            state=PortalFeature.STATE_ON,
        )
        self.document = BillingDocument.objects.create(
            bitrix24_account=self.account, status=BillingDocument.STATUS_ISSUED,
            crm_entity_id="4", crm_account_number="1", total_hours=4.0, total_amount=8000.0,
        )
        self.path = f"/api/billing/documents/{self.document.pk}/invoice-print"

    def test_pechat_po_nastrojke(self):
        self.portal.options["timestamp_config"] = json.dumps({"billing_invoice_template_id": 4})

        response = self.post(self.path)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["invoice_document_number"], "1")
        self.assertEqual(data["document"]["invoice_document_id"], "36")

    def test_bez_shablona_400_s_kodom(self):
        response = self.post(self.path)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invoice_template_missing")
        self.document.refresh_from_db()
        # Причина отказа остаётся на документе: настройщик видит её в
        # карточке, не поднимая логи.
        self.assertIn("Шаблон счёта не выбран", self.document.invoice_print_error)

    def test_bez_prav_403(self):
        other = Bitrix24Account.objects.create(
            b24_user_id=99, is_b24_user_admin=False, member_id="m-tpl",
            is_master_account=False, domain_url="tpl.bitrix24.ru",
            status="active", application_version=1,
        )

        response = self.post(self.path, token=other.create_jwt_token())

        self.assertEqual(response.status_code, 403)

    def test_vyklyuchennaya_podpiska_ne_pechataet(self):
        PortalFeature.objects.filter(bitrix24_account=self.account).update(
            state=PortalFeature.STATE_OFF
        )

        response = self.post(self.path)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "feature_disabled")
