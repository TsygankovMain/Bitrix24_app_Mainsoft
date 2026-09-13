"""Покупка Pro: расчёт, назначение платежа, код портала, заявка, CRM, оплата.

Оба портала здесь двойники. Портал клиента — FakeClientPortal (реквизиты,
user.current, app.option). Портал Mainsoft — FakeMainsoft: живых вызовов к
mainsoft.bitrix24.ru из тестов нет и быть не может, транспорт подменяется
целиком (build_transport), а вебхук в окружении — заведомо ненастоящий.
"""

import io
import json
import logging
import os
import urllib.error
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.test import Client, SimpleTestCase, TestCase

from . import pro_plan_service
from .billing_features import subscription_today
from .models import (
    Bitrix24Account,
    Portal,
    PortalBillingCode,
    PortalRole,
    PortalRoleState,
    PortalSubscription,
    PortalUser,
    ProRequest,
)
from .pro_purchase_crm import CrmSyncError, WebhookTransport, load_crm_settings
from .pro_purchase_pricing import (
    PAYMENT_PURPOSE_LIMIT,
    VAT_INCLUDED,
    VAT_NONE,
    VAT_ON_TOP,
    add_business_days,
    build_payment_purpose,
    calculate_quote,
    load_purchase_settings,
    validate_purchase_form,
)
from . import pro_purchase_service as service

FAKE_WEBHOOK = "https://mainsoft-test.invalid/rest/1/SECRET-TOKEN-123/"


def settings_with(vat_mode=VAT_INCLUDED, **env):
    return load_purchase_settings({"PRO_VAT_MODE": vat_mode, **env})


class PricingTest(SimpleTestCase):
    def quote(self, months, vat_mode=VAT_INCLUDED, **env):
        settings = settings_with(vat_mode, **env)
        return calculate_quote(settings, settings.term(months))

    def test_defaults_are_the_agreed_decision(self):
        settings = load_purchase_settings({})
        self.assertEqual(settings.price_month_rub, 3000)
        self.assertEqual(settings.vat_mode, VAT_NONE)
        self.assertEqual(settings.vat_rate, Decimal("22"))
        self.assertEqual([term.months for term in settings.terms], [1, 3, 6, 12])
        self.assertEqual(settings.default_months, 12)
        self.assertEqual(settings.invoice_prefix, "УТ-")

    def test_one_and_three_months_have_no_discount(self):
        for months in (1, 3):
            quote = self.quote(months)
            self.assertEqual(quote.discount, Decimal("0.00"))
            self.assertEqual(quote.total, Decimal(3000 * months))

    def test_six_months_minus_five_percent(self):
        quote = self.quote(6)
        self.assertEqual(quote.base, Decimal("18000.00"))
        self.assertEqual(quote.discount, Decimal("900.00"))
        self.assertEqual(quote.total, Decimal("17100.00"))
        self.assertEqual(quote.label, "−5%")

    def test_twelve_months_for_the_price_of_ten(self):
        quote = self.quote(12)
        self.assertEqual(quote.base, Decimal("36000.00"))
        self.assertEqual(quote.discount, Decimal("6000.00"))
        self.assertEqual(quote.total, Decimal("30000.00"))
        self.assertEqual(quote.label, "12 по цене 10")
        self.assertEqual(quote.per_month, Decimal("2500.00"))

    def test_vat_included_is_extracted_from_the_price(self):
        quote = self.quote(12, VAT_INCLUDED)
        self.assertEqual(quote.total, Decimal("30000.00"))
        self.assertEqual(quote.vat, Decimal("5409.84"))  # 30000 × 22 / 122
        self.assertEqual(self.quote(1, VAT_INCLUDED).vat, Decimal("540.98"))

    def test_vat_on_top_increases_the_total(self):
        quote = self.quote(1, VAT_ON_TOP)
        self.assertEqual(quote.subtotal, Decimal("3000.00"))
        self.assertEqual(quote.vat, Decimal("660.00"))
        self.assertEqual(quote.total, Decimal("3660.00"))

    def test_no_vat(self):
        quote = self.quote(12, VAT_NONE)
        self.assertEqual(quote.vat, Decimal("0"))
        self.assertEqual(quote.total, Decimal("30000.00"))
        self.assertEqual(quote.as_payload()["vat_text"], "Без НДС")

    def test_rate_and_terms_are_settings(self):
        settings = load_purchase_settings({
            "PRO_PRICE_MONTH_RUB": "4000",
            "PRO_VAT_MODE": VAT_INCLUDED,
            "PRO_VAT_RATE": "20",
            "PRO_TERMS": json.dumps([{"months": 2}, {"months": 24, "discount_percent": 10}]),
            "PRO_DEFAULT_MONTHS": "24",
        })
        self.assertEqual([term.months for term in settings.terms], [2, 24])
        quote = calculate_quote(settings, settings.term(24))
        self.assertEqual(quote.total, Decimal("86400.00"))
        self.assertEqual(quote.vat, Decimal("14400.00"))
        self.assertEqual(settings.default_months, 24)

    def test_broken_settings_fall_back_to_defaults(self):
        with self.assertLogs("main.pro_purchase_pricing", level="WARNING"):
            settings = load_purchase_settings({
                "PRO_VAT_MODE": "halfway", "PRO_TERMS": "[{\"months\": -1}]", "PRO_PRICE_MONTH_RUB": "дорого",
            })
        self.assertEqual(settings.vat_mode, VAT_NONE)
        self.assertEqual([term.months for term in settings.terms], [1, 3, 6, 12])
        self.assertEqual(settings.price_month_rub, 3000)

    def test_due_date_counts_business_days(self):
        self.assertEqual(add_business_days(date(2026, 9, 12), 5), date(2026, 9, 18))  # суббота -> пятница
        self.assertEqual(add_business_days(date(2026, 9, 14), 5), date(2026, 9, 21))


class PaymentPurposeTest(SimpleTestCase):
    def build(self, domain="kvarc-int.bitrix24.ru", vat_mode=VAT_NONE, vat=Decimal("0"), **kwargs):
        params = dict(invoice_number="УТ-0047", invoice_date=date(2026, 9, 12), months=12, domain=domain,
                      portal_code="482137", vat_mode=vat_mode, vat_rate=Decimal("22"), vat_amount=vat)
        params.update(kwargs)
        return build_payment_purpose(**params)

    def test_template_from_the_note(self):
        self.assertEqual(
            self.build(),
            "Оплата по счёту № УТ-0047 от 12.09.2026. Подписка Pro «Учёт трудозатрат» на 12 мес., "
            "портал kvarc-int.bitrix24.ru, код 482137. Без НДС",
        )

    def test_vat_included_text(self):
        text = self.build(vat_mode=VAT_INCLUDED, vat=Decimal("5409.84"))
        self.assertTrue(text.endswith("код 482137. В т.ч. НДС 22% 5409,84 руб."))
        self.assertLessEqual(len(text), PAYMENT_PURPOSE_LIMIT)

    def test_long_domain_is_shortened_but_keys_stay(self):
        for length in (60, 120, 200, 255):
            domain = ("a" * (length - len(".bitrix24.ru"))) + ".bitrix24.ru"
            text = self.build(domain=domain, vat_mode=VAT_INCLUDED, vat=Decimal("5409.84"))
            self.assertLessEqual(len(text), PAYMENT_PURPOSE_LIMIT, length)
            self.assertIn("УТ-0047", text)
            self.assertIn("482137", text)

    def test_long_invoice_prefix_still_fits(self):
        text = self.build(invoice_number="ДЛИННЫЙ-999999", domain="x" * 250, vat_mode=VAT_INCLUDED,
                          vat=Decimal("999999.99"))
        self.assertLessEqual(len(text), PAYMENT_PURPOSE_LIMIT)
        self.assertIn("ДЛИННЫЙ-999999", text)
        self.assertIn("482137", text)


class FormValidationTest(SimpleTestCase):
    def form(self, **overrides):
        data = {
            "payer_inn": "7325148066", "payer_kpp": "732501001",
            "payer_name": "ООО «Кварц Интеграция»", "payer_address": "432017, г. Ульяновск, ул. Спасская, 19",
            "contact_name": "Ирина Ковалёва", "contact_email": "i.kovaleva@kvarc-int.ru",
            "contact_cc": "", "contact_phone": "", "months": 12, "offer_accepted": True,
        }
        data.update(overrides)
        return validate_purchase_form(data, load_purchase_settings({}))

    def test_valid_organisation(self):
        cleaned, errors = self.form()
        self.assertEqual(errors, {})
        self.assertEqual(cleaned["payer_type"], "org")

    def test_inn_length_decides_payer_type_and_ip_has_no_kpp(self):
        cleaned, errors = self.form(payer_inn="732501947362", payer_kpp="732501001",
                                    payer_name="Индивидуальный предприниматель Ковалёва И. А.")
        self.assertEqual(errors, {})
        self.assertEqual(cleaned["payer_type"], "ip")
        self.assertEqual(cleaned["payer_kpp"], "")

    def test_errors(self):
        _, errors = self.form(payer_inn="12345", payer_kpp="", contact_email="почта", contact_cc="bad",
                              contact_phone="12", months=5, offer_accepted=False, payer_address="коротко")
        self.assertEqual(
            set(errors),
            {"payer_inn", "payer_kpp", "contact_email", "contact_cc", "contact_phone", "months", "offer_accepted",
             "payer_address"},
        )
        _, errors = self.form(payer_kpp="")
        self.assertIn("payer_kpp", errors)
        _, errors = self.form(payer_kpp="7325AB0010")
        self.assertIn("payer_kpp", errors)

    def test_offer_must_be_literal_true(self):
        _, errors = self.form(offer_accepted="true")
        self.assertIn("offer_accepted", errors)


# ---------------------------------------------------------------------------
# Двойники порталов
# ---------------------------------------------------------------------------


class FakeToken:
    def __init__(self, portal):
        self.portal = portal

    def call_method(self, method, params=None):
        return self.portal.call(method, params or {})


class FakeClient:
    def __init__(self, portal):
        self._bitrix_token = FakeToken(portal)


class FakeClientPortal:
    def __init__(self):
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "app.option.get":
            return {"result": {}}
        if method == "user.current":
            return {"result": {"NAME": "Ирина", "LAST_NAME": "Ковалёва", "EMAIL": "i.kovaleva@kvarc-int.ru"}}
        if method == "crm.company.list":
            return {"result": [{"ID": "5", "TITLE": "Кварц"}], "total": 1}
        if method == "crm.requisite.list":
            flt = params.get("filter") or {}
            row = {"ID": "91", "ENTITY_ID": "5", "RQ_INN": "7325148066", "RQ_KPP": "732501001",
                   "RQ_COMPANY_FULL_NAME": "Общество с ограниченной ответственностью «Кварц Интеграция»"}
            if flt.get("RQ_INN") in (None, "7325148066"):
                return {"result": [row]}
            return {"result": []}
        if method == "crm.address.list":
            return {"result": [{"TYPE_ID": "6", "POSTAL_CODE": "432017", "CITY": "г. Ульяновск",
                                "ADDRESS_1": "ул. Спасская, д. 19/9"}]}
        raise AssertionError(f"FakeClientPortal: неожиданный метод {method}")


class FakeMainsoft:
    """Портал Mainsoft: помнит вызовы, отвечает честно, сбой задаётся явно."""

    def __init__(self, *, fail=None, opportunity=None, existing_deal_title=None):
        self.calls = []
        self.fail = dict(fail or {})
        self.opportunity = opportunity
        self.existing_deal_title = existing_deal_title
        self.next_id = 100
        self.invoice_fields = {}
        self.deals = {}

    def _new_id(self):
        self.next_id += 1
        return self.next_id

    def methods(self, name=None):
        methods = [method for method, _ in self.calls]
        return [m for m in methods if m == name] if name else methods

    def call(self, method, params=None):
        self.calls.append((method, params or {}))
        if self.fail.get(method):
            self.fail[method] -= 1
            raise CrmSyncError(f"{method}: портал Mainsoft не ответил (URLError)", method=method)
        if method == "crm.requisite.list":
            return {"result": []}
        if method == "crm.company.add":
            return {"result": self._new_id()}
        if method in ("crm.requisite.add", "crm.address.add"):
            return {"result": self._new_id()}
        if method == "crm.deal.list":
            if self.existing_deal_title:
                return {"result": [{"ID": "777", "TITLE": self.existing_deal_title}]}
            return {"result": []}
        if method == "crm.deal.add":
            deal_id = self._new_id()
            self.deals[str(deal_id)] = params["fields"]
            return {"result": deal_id}
        if method == "crm.deal.update":
            return {"result": True}
        if method == "crm.deal.get":
            return {"result": {"ID": str(params["id"])}}
        if method == "crm.item.list":
            return {"result": {"items": []}}
        if method == "crm.item.add":
            self.invoice_fields = params["fields"]
            return {"result": {"item": {"id": self._new_id()}}}
        if method == "crm.item.update":
            self.invoice_fields = params["fields"]
            return {"result": {"item": {"id": params["id"]}}}
        if method == "crm.item.productrow.set":
            return {"result": {"productRows": params["productRows"]}}
        if method == "crm.item.get":
            opportunity = self.opportunity if self.opportunity is not None else self.invoice_fields.get("opportunity")
            return {"result": {"item": {"id": params["id"], "opportunity": opportunity}}}
        if method == "crm.documentgenerator.document.add":
            return {"result": {"document": {"id": 55, "pdfUrl": "https://mainsoft-test.invalid/pdf?token=x"}}}
        if method in ("crm.timeline.comment.add", "im.notify.system.add"):
            return {"result": 1}
        if method == "tasks.task.add":
            return {"result": {"task": {"id": self._new_id()}}}
        if method in ("task.commentitem.add", "tasks.task.complete"):
            return {"result": True}
        raise AssertionError(f"FakeMainsoft: неожиданный метод {method}")


FORM = {
    "payer_inn": "7325148066", "payer_kpp": "732501001",
    "payer_name": "Общество с ограниченной ответственностью «Кварц Интеграция»",
    "payer_address": "432017, Ульяновская обл., г. Ульяновск, ул. Спасская, д. 19/9, офис 305",
    "contact_name": "Ирина Ковалёва", "contact_email": "i.kovaleva@kvarc-int.ru",
    "contact_cc": "buh@kvarc-int.ru", "contact_phone": "+7 842 250-14-80",
    "months": 12, "offer_accepted": True,
}


class ProPurchaseFixture(TestCase):
    def setUp(self):
        cache.clear()
        self.client_portal = FakeClientPortal()
        self.mainsoft = FakeMainsoft()
        self.admin = self.make_account(11, admin=True)
        self.token = self.admin.create_jwt_token()
        PortalUser.objects.create(bitrix24_account=self.admin, bitrix_id="11", name="Ирина", last_name="Ковалёва")

        client_patch = patch.object(
            Bitrix24Account, "client", property(lambda _self: FakeClient(self.client_portal)),
        )
        client_patch.start()
        self.addCleanup(client_patch.stop)

        transport_patch = patch("main.pro_purchase_service.build_transport", lambda _settings: self.mainsoft)
        transport_patch.start()
        self.addCleanup(transport_patch.stop)

        env_patch = patch.dict(os.environ, {}, clear=False)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        for name in list(os.environ):
            if name.startswith("MAINSOFT_BILLING_") or name.startswith("PRO_"):
                os.environ.pop(name)

    def make_account(self, user_id, *, admin=False, member_id="m-kvarc", domain="kvarc-int.bitrix24.ru"):
        return Bitrix24Account.objects.create(
            b24_user_id=user_id, is_b24_user_admin=admin, member_id=member_id,
            is_master_account=admin, domain_url=domain, status="active", application_version=1,
        )

    def enable_webhook(self, **extra):
        os.environ["MAINSOFT_BILLING_WEBHOOK"] = FAKE_WEBHOOK
        os.environ["MAINSOFT_BILLING_INVOICE_TEMPLATE_ID"] = "9"
        os.environ["MAINSOFT_BILLING_NOTIFY_USER_ID"] = "1"
        os.environ["MAINSOFT_BILLING_MY_COMPANY_ID"] = "77"
        os.environ.update(extra)

    def post(self, path, body=None, token=None):
        return Client().post(path, data=json.dumps(body if body is not None else {}),
                             content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token or self.token}")

    def get(self, path, token=None):
        return Client().get(path, HTTP_AUTHORIZATION=f"Bearer {token or self.token}")

    def create(self, **overrides):
        body = dict(FORM)
        body.update(overrides)
        return self.post("/api/pro/requests", body)


class PortalCodeTest(ProPurchaseFixture):
    def test_code_is_six_digits_and_given_once(self):
        portal = service.portal_for_account(self.admin)
        code = service.portal_code(portal)
        self.assertRegex(code, r"^[1-9]\d{5}$")
        self.assertEqual(service.portal_code(portal), code)
        self.assertEqual(PortalBillingCode.objects.count(), 1)

    def test_code_survives_domain_change(self):
        portal = service.portal_for_account(self.admin)
        code = service.portal_code(portal)
        Portal.objects.filter(pk=portal.pk).update(domain_url="kvarc-new.bitrix24.ru")
        Bitrix24Account.objects.filter(pk=self.admin.pk).update(domain_url="kvarc-new.bitrix24.ru")
        moved = Bitrix24Account.objects.get(pk=self.admin.pk)
        self.assertEqual(service.portal_code(service.portal_for_account(moved)), code)

        offer = self.get("/api/pro/offer", token=moved.create_jwt_token()).json()
        self.assertEqual(offer["portal"]["code"], code)
        self.assertEqual(offer["portal"]["domain"], "kvarc-new.bitrix24.ru")

    def test_other_portal_gets_other_code(self):
        other = self.make_account(5, admin=True, member_id="m-other", domain="other.bitrix24.ru")
        first = service.portal_code(service.portal_for_account(self.admin))
        second = service.portal_code(service.portal_for_account(other))
        self.assertNotEqual(first, second)

    def test_invoice_numbers_are_sequential(self):
        from django.db import transaction

        with transaction.atomic():
            self.assertEqual(service.next_invoice_number("УТ-"), (1, "УТ-0001"))
            self.assertEqual(service.next_invoice_number("УТ-"), (2, "УТ-0002"))


class OfferEndpointTest(ProPurchaseFixture):
    def test_offer_for_admin(self):
        data = self.get("/api/pro/offer").json()
        self.assertTrue(data["can_request"])
        self.assertEqual(data["price_month_rub"], 3000)
        self.assertEqual([term["months"] for term in data["terms"]], [1, 3, 6, 12])
        self.assertEqual(data["terms"][-1]["total"], "30000.00")
        self.assertEqual(data["vat"], {"mode": "none", "rate": "22"})
        self.assertEqual(data["default_months"], 12)
        self.assertEqual(data["contact"], {"name": "Ирина Ковалёва", "email": "i.kovaleva@kvarc-int.ru"})
        self.assertEqual(data["crm_mode"], "manual")
        self.assertIsNone(data["current_request"])

    def test_offer_for_employee_names_who_connects(self):
        employee = self.make_account(20)
        PortalUser.objects.create(bitrix24_account=employee, bitrix_id="11", name="Ирина", last_name="Ковалёва")
        PortalUser.objects.create(bitrix24_account=employee, bitrix_id="30", name="Павел", last_name="Орлов")
        PortalRoleState.objects.create(member_id="m-kvarc", accountants_imported_at="2026-09-01T00:00:00Z")
        PortalRole.objects.create(member_id="m-kvarc", b24_user_id="30", role="accountant")

        data = self.get("/api/pro/offer", token=employee.create_jwt_token()).json()

        self.assertFalse(data["can_request"])
        self.assertEqual(data["managers"], ["Ирина Ковалёва", "Павел Орлов"])
        self.assertEqual(data["contact"], {"name": "", "email": ""})

    def test_individual_portal_price_wins(self):
        pro_plan_service.set_account_plan(self.admin, state=PortalSubscription.STATE_TRIAL,
                                          trial_until=subscription_today() + timedelta(days=5))
        PortalSubscription.objects.update(price_month_rub=2000)
        data = self.get("/api/pro/offer").json()
        self.assertEqual(data["price_month_rub"], 2000)
        self.assertEqual(data["terms"][0]["total"], "2000.00")
        self.assertEqual(data["subscription"]["status"], "trial")

    def test_quote_endpoint(self):
        data = self.get("/api/pro/quote?months=6").json()
        self.assertEqual(data["total"], "17100.00")
        self.assertEqual(self.get("/api/pro/quote?months=7").status_code, 400)

    def test_requisites_from_client_crm(self):
        suggestions = self.get("/api/pro/requisites").json()["suggestions"]
        self.assertEqual(suggestions[0]["inn"], "7325148066")
        self.assertEqual(suggestions[0]["address"], "432017, г. Ульяновск, ул. Спасская, д. 19/9")

        found = self.get("/api/pro/requisites?inn=7325148066").json()
        self.assertTrue(found["found"])
        self.assertEqual(found["requisite"]["kpp"], "732501001")
        self.assertFalse(self.get("/api/pro/requisites?inn=7329102577").json()["found"])
        self.assertEqual(self.get("/api/pro/requisites?inn=12").status_code, 400)


class CreateRequestSafeModeTest(ProPurchaseFixture):
    def test_without_webhook_request_waits_for_crm(self):
        response = self.create()

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["crm_mode"], "manual")
        request = data["request"]
        self.assertEqual(request["status"], "pending")
        self.assertEqual(request["crm_state"], "manual")
        self.assertEqual(request["invoice_number"], "УТ-0001")
        self.assertEqual(request["total"], "30000.00")
        self.assertEqual(request["amounts"]["vat"], "0.00")
        self.assertEqual(request["amounts"]["vat_text"], "Без НДС")
        self.assertLessEqual(len(request["payment_purpose"]), 210)
        self.assertIn("УТ-0001", request["payment_purpose"])
        self.assertIn(request["portal"]["code"], request["payment_purpose"])
        self.assertEqual(self.mainsoft.calls, [])
        stored = ProRequest.objects.get()
        self.assertEqual(stored.requested_by_name, "Ирина Ковалёва")
        self.assertTrue(stored.requested_by_admin)

    def test_pro_is_not_enabled_before_payment(self):
        self.create()
        features = self.get("/api/features").json()
        self.assertFalse(features["billing"]["enabled"])
        self.assertFalse(PortalSubscription.objects.filter(state=PortalSubscription.STATE_ACTIVE).exists())

    def test_portal_comes_from_auth_not_from_body(self):
        other = self.make_account(5, admin=True, member_id="m-other", domain="other.bitrix24.ru")
        other_portal = service.portal_for_account(other)
        other_code = service.portal_code(other_portal)

        response = self.create(member_id="m-other", domain="other.bitrix24.ru", portal_code=other_code,
                               portal=str(other_portal.pk), portal_id=str(other_portal.pk))

        self.assertEqual(response.status_code, 201)
        stored = ProRequest.objects.get()
        self.assertEqual(stored.member_id_snapshot, "m-kvarc")
        self.assertEqual(stored.domain_snapshot, "kvarc-int.bitrix24.ru")
        self.assertNotEqual(stored.portal_id, other_portal.pk)
        self.assertNotEqual(stored.portal_code, other_code)

    def test_validation_errors_come_back_by_field(self):
        response = self.create(payer_inn="123", offer_accepted=False)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "validation_failed")
        self.assertEqual(set(response.json()["errors"]), {"payer_inn", "offer_accepted"})
        self.assertEqual(ProRequest.objects.count(), 0)

    def test_employee_cannot_request(self):
        employee = self.make_account(20)
        response = self.post("/api/pro/requests", FORM, token=employee.create_jwt_token())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "pro_request_forbidden")
        self.assertEqual(self.get("/api/pro/requisites", token=employee.create_jwt_token()).status_code, 403)

    def test_accountant_role_can_request(self):
        accountant = self.make_account(30)
        PortalRoleState.objects.create(member_id="m-kvarc", accountants_imported_at="2026-09-01T00:00:00Z")
        PortalRole.objects.create(member_id="m-kvarc", b24_user_id="30", role="accountant")
        response = self.post("/api/pro/requests", FORM, token=accountant.create_jwt_token())
        self.assertEqual(response.status_code, 201)
        self.assertFalse(ProRequest.objects.get().requested_by_admin)

    def test_same_term_updates_requisites_and_keeps_number(self):
        first = self.create().json()["request"]
        response = self.create(payer_name="ООО «Кварц Интеграция» (новое наименование)")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["updated_in_place"])
        self.assertEqual(data["request"]["invoice_number"], first["invoice_number"])
        self.assertEqual(ProRequest.objects.count(), 1)

    def test_other_term_replaces_open_request(self):
        first = self.create().json()["request"]
        data = self.create(months=3).json()
        self.assertEqual(data["replaced_invoice_number"], first["invoice_number"])
        self.assertEqual(data["request"]["invoice_number"], "УТ-0002")
        old = ProRequest.objects.get(invoice_number=first["invoice_number"])
        self.assertEqual(old.status, ProRequest.STATUS_CANCELLED)
        self.assertEqual(old.replaced_by.invoice_number, "УТ-0002")
        self.assertEqual(ProRequest.objects.filter(status__in=ProRequest.OPEN_STATUSES).count(), 1)

    def test_current_request_hides_requisites_from_employee(self):
        self.create()
        self.assertEqual(self.get("/api/pro/requests/current").json()["request"]["payer"]["inn"], "7325148066")
        employee = self.make_account(20)
        limited = self.get("/api/pro/requests/current", token=employee.create_jwt_token()).json()["request"]
        self.assertEqual(limited["status"], "pending")
        self.assertNotIn("payer", limited)
        self.assertNotIn("contact", limited)

    def test_cancel_own_request_and_not_other_portal(self):
        request_id = self.create().json()["request"]["id"]
        other = self.make_account(5, admin=True, member_id="m-other", domain="other.bitrix24.ru")
        self.assertEqual(
            self.post(f"/api/pro/requests/{request_id}/cancel", {}, token=other.create_jwt_token()).status_code, 404,
        )
        response = self.post(f"/api/pro/requests/{request_id}/cancel", {"reason": "передумали"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["request"]["status"], "cancelled")
        self.assertEqual(self.post("/api/pro/requests/not-a-uuid/cancel", {}).status_code, 404)

    def test_pdf_is_not_ready_in_safe_mode(self):
        request_id = self.create().json()["request"]["id"]
        response = self.get(f"/api/pro/requests/{request_id}/invoice.pdf")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "pdf_not_ready")


class CreateRequestRaceTest(ProPurchaseFixture):
    """Два быстрых POST без открытой заявки: select_for_update().first()
    ничего не блокирует, когда блокировать ещё нечего, поэтому оба запроса
    доходят до INSERT и второй ловит partial unique index
    pro_request_one_open_per_portal (IntegrityError). До фикса это долетало
    до log_errors и клиент получал сырой 500 с текстом Postgres — ручка
    (pro_requests_create в views.py) ловит только PurchaseError.

    Гонку эмулируем патчем service._locked_open_request: первый вызов (в
    начале create_request) возвращает None — «конкурент ещё не виден», а
    request.save() бросает настоящий IntegrityError на тот же частичный
    индекс, как это сделал бы sqlite/postgres при реальном столкновении.
    Второй вызов _locked_open_request (внутри except) уже отдаёт
    per-side-effect то, что нужно проверить в каждом тесте.
    """

    def _integrity_error(self):
        return IntegrityError(
            'duplicate key value violates unique constraint "pro_request_one_open_per_portal"'
            '\nDETAIL:  Key (portal_id) already exists.'
        )

    def test_same_term_race_merges_into_the_winner_not_500(self):
        """Конкурент выиграл гонку с тем же тарифом — сливаемся в его заявку,
        как при обычном «уже есть заявка», а не 500."""
        winner = self.create().json()["request"]
        winner_row = ProRequest.objects.get(invoice_number=winner["invoice_number"])

        with patch.object(service, "_locked_open_request", side_effect=[None, winner_row]), \
             patch.object(ProRequest, "save", side_effect=self._integrity_error()) as fake_save:
            # Первый save() (нашей новой заявки) должен упасть с IntegrityError;
            # чтобы не сорвать и последующий save() слияния (winner.save()),
            # разрешаем ему пройти нормально после первого вызова.
            fake_save.side_effect = [self._integrity_error(), None]
            response = self.create(payer_name="ООО «Кварц Интеграция» (новое наименование)")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["updated_in_place"])
        self.assertEqual(data["request"]["invoice_number"], winner["invoice_number"])
        self.assertEqual(ProRequest.objects.count(), 1)

    def test_different_term_race_gives_understandable_409_not_500(self):
        """Конкурент выиграл гонку с ДРУГИМ тарифом — понятный 409, без
        текста ошибки БД в ответе, вместо давки второй попытки вставки."""
        winner = self.create(months=3).json()["request"]
        winner_row = ProRequest.objects.get(invoice_number=winner["invoice_number"])

        with patch.object(service, "_locked_open_request", side_effect=[None, winner_row]), \
             patch.object(ProRequest, "save", side_effect=self._integrity_error()):
            response = self.create(months=12)

        self.assertEqual(response.status_code, 409)
        payload = response.json()
        self.assertEqual(payload["code"], "request_conflict")
        self.assertNotIn("constraint", payload["error"])
        self.assertNotIn("DETAIL", payload["error"])
        # Проигранной вставки не осталось, выигранная заявка на месте одна.
        self.assertEqual(ProRequest.objects.count(), 1)

    def test_missing_winner_after_race_gives_409_not_500(self):
        """Крайний случай: после проигранной вставки перечитать конкурента не
        удалось — тоже понятный 409, а не необработанное исключение."""
        with patch.object(service, "_locked_open_request", side_effect=[None, None]), \
             patch.object(ProRequest, "save", side_effect=self._integrity_error()):
            response = self.create()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "request_conflict")
        self.assertEqual(ProRequest.objects.count(), 0)


class CrmDispatchTest(ProPurchaseFixture):
    def test_request_goes_to_mainsoft_crm(self):
        self.enable_webhook(MAINSOFT_BILLING_FIELD_PORTAL_CODE="UF_CRM_CODE",
                            MAINSOFT_BILLING_FIELD_MEMBER_ID="UF_CRM_MEMBER",
                            MAINSOFT_BILLING_DEAL_CATEGORY_ID="7", MAINSOFT_BILLING_STAGE_NEW="C7:NEW")

        response = self.create()

        data = response.json()
        self.assertEqual(data["crm_mode"], "auto")
        self.assertEqual(data["request"]["status"], "sent")
        self.assertEqual(data["request"]["crm_state"], "sent")
        self.assertTrue(data["request"]["pdf_available"])
        stored = ProRequest.objects.get()
        self.assertTrue(stored.crm_deal_id and stored.crm_invoice_id and stored.crm_company_id)
        self.assertEqual(stored.crm_error, "")
        deal = self.mainsoft.deals[stored.crm_deal_id]
        self.assertEqual(deal["UF_CRM_CODE"], stored.portal_code)
        self.assertEqual(deal["UF_CRM_MEMBER"], "m-kvarc")
        self.assertEqual(deal["CATEGORY_ID"], "7")
        self.assertEqual(deal["STAGE_ID"], "C7:NEW")
        self.assertIn("kvarc-int.bitrix24.ru", deal["COMMENTS"])
        self.assertEqual(self.mainsoft.invoice_fields["comments"], stored.payment_purpose)
        self.assertEqual(
            self.mainsoft.methods()[:9],
            ["crm.requisite.list", "crm.company.add", "crm.requisite.add", "crm.address.add",
             "crm.deal.list", "crm.deal.add", "crm.deal.get", "crm.item.list", "crm.item.add"],
        )
        self.assertIn("crm.documentgenerator.document.add", self.mainsoft.methods())
        self.assertIn("im.notify.system.add", self.mainsoft.methods())

    def test_secret_webhook_never_leaks_into_response_or_client(self):
        self.enable_webhook()
        payload = self.create().content.decode("utf-8")
        offer = self.get("/api/pro/offer").content.decode("utf-8")
        current = self.get("/api/pro/requests/current").content.decode("utf-8")
        for text in (payload, offer, current):
            self.assertNotIn("SECRET-TOKEN", text)
            self.assertNotIn("pdf?token", text)

    def test_repeat_dispatch_does_not_create_second_deal(self):
        self.enable_webhook(MAINSOFT_BILLING_DEAL_CATEGORY_ID="7")
        self.create()
        request = ProRequest.objects.get()

        service.dispatch(request)
        self.create(contact_phone="+7 900 000-00-00")  # та же заявка, правка реквизитов

        self.assertEqual(self.mainsoft.methods("crm.deal.add"), ["crm.deal.add"])
        self.assertEqual(self.mainsoft.methods("crm.item.add"), ["crm.item.add"])
        self.assertEqual(self.mainsoft.methods("crm.company.add"), ["crm.company.add"])
        self.assertEqual(len(self.mainsoft.methods("crm.deal.update")), 2)
        self.assertEqual(self.mainsoft.methods("im.notify.system.add"), ["im.notify.system.add"])
        self.assertEqual(self.mainsoft.methods("tasks.task.add"), ["tasks.task.add"])

    def test_failure_after_deal_keeps_ids_and_retry_reuses_them(self):
        self.enable_webhook(MAINSOFT_BILLING_DEAL_CATEGORY_ID="7")
        self.mainsoft.fail = {"crm.item.add": 1}

        data = self.create().json()["request"]

        self.assertEqual(data["status"], "pending")
        self.assertEqual(data["crm_state"], "retry")
        request = ProRequest.objects.get()
        self.assertTrue(request.crm_deal_id)
        self.assertIn("crm.item.add", request.crm_error)
        self.assertNotIn("SECRET-TOKEN", request.crm_error)

        out = io.StringIO()
        call_command("pro_requests", "sync", stdout=out)

        request.refresh_from_db()
        self.assertEqual(request.status, ProRequest.STATUS_SENT)
        self.assertEqual(self.mainsoft.methods("crm.deal.add"), ["crm.deal.add"])
        self.assertEqual(request.crm_attempts, 2)

    def test_lost_deal_id_is_found_by_invoice_number(self):
        self.enable_webhook(MAINSOFT_BILLING_DEAL_CATEGORY_ID="7")
        self.mainsoft.existing_deal_title = "Pro · kvarc-int.bitrix24.ru · 12 месяцев · УТ-0001"
        self.create()
        self.assertEqual(self.mainsoft.methods("crm.deal.add"), [])
        self.assertEqual(ProRequest.objects.get().crm_deal_id, "777")

    def test_amount_mismatch_in_crm_is_not_accepted(self):
        self.enable_webhook()
        self.mainsoft.opportunity = 3000
        data = self.create().json()["request"]
        self.assertEqual(data["status"], "pending")
        self.assertIn("не совпала", ProRequest.objects.get().crm_error)

    def test_cancel_moves_deal_to_lost_stage(self):
        self.enable_webhook(MAINSOFT_BILLING_DEAL_CATEGORY_ID="7", MAINSOFT_BILLING_STAGE_LOST="C7:LOSE")
        request_id = self.create().json()["request"]["id"]
        self.post(f"/api/pro/requests/{request_id}/cancel", {"reason": "передумали"})
        updates = [params for method, params in self.mainsoft.calls if method == "crm.deal.update"]
        self.assertEqual(updates[-1]["fields"], {"STAGE_ID": "C7:LOSE"})
        self.assertIsNotNone(ProRequest.objects.get().crm_cancel_synced_at)
        comments = [params for method, params in self.mainsoft.calls if method == "task.commentitem.add"]
        self.assertIn("отменена", comments[-1]["FIELDS"]["POST_MESSAGE"])

    def test_cancel_without_deal_comments_only_the_task(self):
        """Без воронки (MAINSOFT_BILLING_DEAL_CATEGORY_ID пуст) сделки нет —
        отмена комментирует только задачу, крашей и обращений к сделке нет."""
        self.enable_webhook()
        request_id = self.create().json()["request"]["id"]
        response = self.post(f"/api/pro/requests/{request_id}/cancel", {"reason": "передумали"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.mainsoft.methods("crm.deal.update"), [])
        comments = [params for method, params in self.mainsoft.calls if method == "task.commentitem.add"]
        self.assertIn("отменена", comments[-1]["FIELDS"]["POST_MESSAGE"])
        self.assertIsNotNone(ProRequest.objects.get().crm_cancel_synced_at)


class ProRequestTaskTest(ProPurchaseFixture):
    """Задача tasks.task.add на контроль оплаты: создаётся вместе со
    смарт-счётом (со сделкой или без), привязывается к CRM через
    UF_CRM_TASK, попадает в комментарии при отмене и оплате. Настоящих
    вызовов к порталу Mainsoft нет — только FakeMainsoft."""

    def _task_fields(self):
        return [params["fields"] for method, params in self.mainsoft.calls if method == "tasks.task.add"]

    def test_invoice_without_deal_creates_task_with_uf_crm_task(self):
        self.enable_webhook(MAINSOFT_BILLING_TASK_RESPONSIBLE_ID="5")
        data = self.create().json()["request"]

        self.assertEqual(data["status"], "sent")
        request = ProRequest.objects.get()
        self.assertTrue(request.crm_task_id)
        self.assertFalse(request.crm_deal_id)
        task_calls = self._task_fields()
        self.assertEqual(len(task_calls), 1)
        fields = task_calls[0]
        self.assertEqual(fields["RESPONSIBLE_ID"], "5")
        self.assertEqual(fields["UF_CRM_TASK"], [f"SI_{request.crm_invoice_id}", f"CO_{request.crm_company_id}"])
        self.assertIn(request.invoice_number, fields["TITLE"])
        self.assertTrue(fields["DEADLINE"].startswith(request.due_date.isoformat()))
        self.assertIn("18:00:00", fields["DEADLINE"])
        self.assertIn("+03:00", fields["DEADLINE"])
        self.assertIn(request.payment_purpose, fields["DESCRIPTION"])
        notify = [params for method, params in self.mainsoft.calls if method == "im.notify.system.add"]
        self.assertIn("Задача:", notify[-1]["MESSAGE"])

    def test_invoice_with_deal_task_points_to_deal_too(self):
        self.enable_webhook(MAINSOFT_BILLING_DEAL_CATEGORY_ID="7")
        self.create()
        request = ProRequest.objects.get()
        fields = self._task_fields()[0]
        self.assertEqual(
            fields["UF_CRM_TASK"],
            [f"SI_{request.crm_invoice_id}", f"CO_{request.crm_company_id}", f"D_{request.crm_deal_id}"],
        )

    def test_task_responsible_prefers_task_specific_id(self):
        self.enable_webhook(MAINSOFT_BILLING_TASK_RESPONSIBLE_ID="5", MAINSOFT_BILLING_RESPONSIBLE_ID="9")
        self.create()
        self.assertEqual(self._task_fields()[0]["RESPONSIBLE_ID"], "5")

    def test_task_responsible_falls_back_to_deal_responsible(self):
        self.enable_webhook(MAINSOFT_BILLING_RESPONSIBLE_ID="9")
        self.create()
        self.assertEqual(self._task_fields()[0]["RESPONSIBLE_ID"], "9")

    def test_task_responsible_falls_back_to_notify_user(self):
        self.enable_webhook()  # NOTIFY_USER_ID="1" по умолчанию фикстуры
        self.create()
        self.assertEqual(self._task_fields()[0]["RESPONSIBLE_ID"], "1")

    def test_missing_task_responsible_is_a_soft_failure(self):
        self.enable_webhook()
        del os.environ["MAINSOFT_BILLING_NOTIFY_USER_ID"]
        data = self.create().json()["request"]
        self.assertEqual(data["status"], "sent")  # счёт уже создан — не откатываем
        request = ProRequest.objects.get()
        self.assertFalse(request.crm_task_id)
        self.assertTrue(request.crm_invoice_id)
        self.assertIn("ответственный", request.crm_error)

    def test_task_failure_does_not_roll_back_invoice_and_sync_recreates_only_the_task(self):
        self.enable_webhook()
        self.mainsoft.fail = {"tasks.task.add": 1}
        data = self.create().json()["request"]

        self.assertEqual(data["status"], "sent")
        request = ProRequest.objects.get()
        self.assertTrue(request.crm_invoice_id)
        self.assertFalse(request.crm_task_id)
        self.assertIn("Задача не создана", request.crm_error)

        call_command("pro_requests", "sync", stdout=io.StringIO())

        request.refresh_from_db()
        self.assertTrue(request.crm_task_id)
        self.assertEqual(request.crm_error, "")
        self.assertEqual(self.mainsoft.methods("crm.item.add"), ["crm.item.add"])
        self.assertEqual(self.mainsoft.methods("crm.company.add"), ["crm.company.add"])
        self.assertEqual(len(self.mainsoft.methods("tasks.task.add")), 2)

    def test_missing_my_company_id_fails_clearly_and_keeps_request_pending(self):
        self.enable_webhook()
        del os.environ["MAINSOFT_BILLING_MY_COMPANY_ID"]
        data = self.create().json()["request"]
        self.assertEqual(data["status"], "pending")
        self.assertIn("MAINSOFT_BILLING_MY_COMPANY_ID", ProRequest.objects.get().crm_error)
        self.assertEqual(self.mainsoft.calls, [])

    def test_paid_comments_and_completes_the_task(self):
        self.enable_webhook()
        self.create()

        call_command("pro_requests", "paid", "--invoice", "УТ-0001", stdout=io.StringIO())

        request = ProRequest.objects.get()
        comments = [params for method, params in self.mainsoft.calls if method == "task.commentitem.add"]
        self.assertIn("Оплата отмечена", comments[-1]["FIELDS"]["POST_MESSAGE"])
        self.assertIn(f"{request.pro_paid_until:%d.%m.%Y}", comments[-1]["FIELDS"]["POST_MESSAGE"])
        complete = [params for method, params in self.mainsoft.calls if method == "tasks.task.complete"]
        self.assertEqual(complete, [{"taskId": int(request.crm_task_id)}])

    def test_invoice_stage_changes_on_cancellation(self):
        self.enable_webhook(MAINSOFT_BILLING_INVOICE_STAGE_LOST="DT31_3:D")
        request_id = self.create().json()["request"]["id"]
        invoice_id = ProRequest.objects.get().crm_invoice_id

        self.post(f"/api/pro/requests/{request_id}/cancel", {"reason": "передумали"})

        updates = [params for method, params in self.mainsoft.calls
                  if method == "crm.item.update" and params.get("id") == int(invoice_id)]
        self.assertEqual(updates[-1]["fields"], {"stageId": "DT31_3:D"})

    def test_invoice_stage_changes_on_payment(self):
        self.enable_webhook(MAINSOFT_BILLING_INVOICE_STAGE_PAID="DT31_3:P")
        self.create()
        invoice_id = ProRequest.objects.get().crm_invoice_id

        call_command("pro_requests", "paid", "--invoice", "УТ-0001", stdout=io.StringIO())

        updates = [params for method, params in self.mainsoft.calls
                  if method == "crm.item.update" and params.get("id") == int(invoice_id)]
        self.assertEqual(updates[-1]["fields"], {"stageId": "DT31_3:P"})

    def test_safe_mode_without_webhook_creates_no_task(self):
        self.create()
        self.assertEqual(self.mainsoft.calls, [])
        self.assertEqual(ProRequest.objects.get().crm_task_id, "")


class InvoicePdfTest(ProPurchaseFixture):
    def test_pdf_goes_through_our_server_only_from_mainsoft_host(self):
        self.enable_webhook()
        request_id = self.create().json()["request"]["id"]
        self.mainsoft.fetch_bytes = lambda url: b"%PDF-1.4 test"

        response = self.get(f"/api/pro/requests/{request_id}/invoice.pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response.content, b"%PDF-1.4 test")

        ProRequest.objects.update(crm_pdf_url="https://evil.invalid/steal")
        self.assertEqual(self.get(f"/api/pro/requests/{request_id}/invoice.pdf").status_code, 502)


class WebhookTransportTest(SimpleTestCase):
    def test_network_error_does_not_reveal_webhook(self):
        transport = WebhookTransport(FAKE_WEBHOOK)
        error = urllib.error.URLError(f"cannot reach {FAKE_WEBHOOK}")
        with patch("main.pro_purchase_crm.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(CrmSyncError) as ctx:
                transport.call("crm.deal.add", {})
        self.assertNotIn("SECRET-TOKEN", str(ctx.exception))

    def test_portal_error_description_is_scrubbed(self):
        transport = WebhookTransport(FAKE_WEBHOOK)
        body = json.dumps({"error": "x", "error_description": f"bad call {FAKE_WEBHOOK}crm.deal.add"}).encode()

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch("main.pro_purchase_crm.urllib.request.urlopen", return_value=Response(body)):
            with self.assertRaises(CrmSyncError) as ctx:
                transport.call("crm.deal.add", {})
        self.assertNotIn("SECRET-TOKEN", str(ctx.exception))

    def test_settings_require_https_webhook(self):
        self.assertIsNone(load_crm_settings({}))
        with self.assertLogs("main.pro_purchase_crm", level="ERROR") as logs:
            self.assertIsNone(load_crm_settings({"MAINSOFT_BILLING_WEBHOOK": "http://mainsoft-test.invalid/rest/1/SECRET/"}))
        self.assertNotIn("SECRET", "".join(logs.output))
        settings = load_crm_settings({"MAINSOFT_BILLING_WEBHOOK": FAKE_WEBHOOK})
        self.assertEqual(settings.portal_url, "https://mainsoft-test.invalid")


class ConsoleCommandTest(ProPurchaseFixture):
    def run_command(self, *args):
        out = io.StringIO()
        call_command("pro_requests", *args, stdout=out)
        return out.getvalue()

    def test_paid_by_invoice_enables_pro_for_paid_term(self):
        self.create()
        today = subscription_today()

        output = self.run_command("paid", "--invoice", "УТ-0001", "--by", "egor")

        request = ProRequest.objects.get()
        self.assertEqual(request.status, ProRequest.STATUS_PAID)
        expected_until = pro_plan_service.add_months(today, 12) - timedelta(days=1)
        self.assertEqual(request.pro_paid_until, expected_until)
        subscription = PortalSubscription.objects.get(portal=request.portal)
        self.assertEqual(subscription.state, PortalSubscription.STATE_ACTIVE)
        self.assertEqual(subscription.paid_until, expected_until)
        self.assertIn("Pro включён", output)
        self.assertTrue(self.get("/api/features").json()["billing"]["enabled"])
        event = subscription.events.first()
        self.assertIn("УТ-0001", event.comment)
        self.assertEqual(event.actor, "console:egor")

    def test_paid_by_portal_code(self):
        code = self.create().json()["request"]["portal"]["code"]
        self.run_command("paid", "--code", code)
        self.assertEqual(ProRequest.objects.get().status, ProRequest.STATUS_PAID)

    def test_payment_extends_active_pro_without_losing_days(self):
        until = subscription_today() + timedelta(days=10)
        pro_plan_service.set_account_plan(self.admin, paid_until=until)
        self.create(months=1)
        self.run_command("paid", "--invoice", "1")
        expected = pro_plan_service.add_months(until + timedelta(days=1), 1) - timedelta(days=1)
        self.assertEqual(ProRequest.objects.get().pro_paid_until, expected)

    def test_paid_twice_is_refused(self):
        self.create()
        self.run_command("paid", "--invoice", "УТ-0001")
        with self.assertRaises(CommandError):
            self.run_command("paid", "--invoice", "УТ-0001")

    def test_cancelled_request_cannot_be_paid(self):
        request_id = self.create().json()["request"]["id"]
        self.post(f"/api/pro/requests/{request_id}/cancel", {})
        with self.assertRaises(CommandError):
            self.run_command("paid", "--invoice", "УТ-0001")
        self.assertFalse(PortalSubscription.objects.filter(state=PortalSubscription.STATE_ACTIVE).exists())

    def test_list_show_and_sync_in_safe_mode(self):
        self.create()
        listing = self.run_command("list", "--open")
        self.assertIn("УТ-0001", listing)
        self.assertIn("ожидает отправки", listing)
        shown = self.run_command("show", "--invoice", "УТ-0001")
        self.assertIn("m-kvarc", shown)
        self.assertIn("MAINSOFT_BILLING_WEBHOOK не задан", shown)
        self.assertIn("не задан", self.run_command("sync"))
        self.assertEqual(self.run_command("sync", "--quiet"), "")

    def test_unknown_invoice(self):
        with self.assertRaises(CommandError):
            self.run_command("show", "--invoice", "УТ-9999")


class PurposeOnModelTest(ProPurchaseFixture):
    def test_long_domain_purpose_fits_the_model(self):
        long_domain = ("очень-длинное-название-компании-" * 8)[:230] + ".bitrix24.ru"
        account = self.make_account(40, admin=True, member_id="m-long", domain=long_domain)
        response = self.post("/api/pro/requests", FORM, token=account.create_jwt_token())
        self.assertEqual(response.status_code, 201, response.content)
        purpose = ProRequest.objects.get().payment_purpose
        self.assertLessEqual(len(purpose), 210)
        self.assertIn("УТ-0001", purpose)


class LoggingDoesNotLeakTest(ProPurchaseFixture):
    def test_failed_dispatch_log_has_no_secret(self):
        self.enable_webhook()
        self.mainsoft.fail = {"crm.requisite.list": 1}
        with self.assertLogs("main.pro_purchase_service", level=logging.WARNING) as logs:
            self.create()
        self.assertNotIn("SECRET-TOKEN", "".join(logs.output))



class MoneyHumanTest(SimpleTestCase):
    def test_groups_thousands_and_hides_zero_kopecks(self):
        from decimal import Decimal
        from .pro_purchase_pricing import money_human
        self.assertEqual(money_human(Decimal("3000")), "3 000")
        self.assertEqual(money_human(Decimal("36000.00")), "36 000")
        self.assertEqual(money_human(Decimal("5409.84")), "5 409,84")
        self.assertEqual(money_human(Decimal("999")), "999")
