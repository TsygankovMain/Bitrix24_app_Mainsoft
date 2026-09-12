"""Эндпоинты «Счёт и акт»: выставление, отмена, права, подписка, акт, XLSX.

Портал здесь всегда двойник (FakePortal): доступа на запись к боевому порталу
у разработки нет, а главное — проверять надо не то, что Битрикс отвечает, а
то, как приложение ведёт себя с его ответами. Отсюда основная группа тестов:
портал отвечает «успех» с чужой суммой — выставление обязано отказать.

Про права. Серверный гейт есть ровно на пишущих эндпоинтах счёта: это
точечное исключение из решения от 11.06.2026 (общего гейта по ролям нет), то
же по классу, что @admin_required на закрытии месяца.
"""

import io
import json
from datetime import datetime
from unittest.mock import patch

import openpyxl
from django.core.cache import cache
from django.test import Client, TestCase
from django.utils import timezone

from .models import (
    BillingDocument,
    BillingEntry,
    Bitrix24Account,
    PortalFeature,
    PortalUser,
    ProjectCard,
    TimesheetItem,
)
from .period_service import PeriodService


class FakeToken:
    def __init__(self, portal):
        self.portal = portal

    def call_method(self, method, params=None):
        return self.portal.call(method, params or {})


class FakeClient:
    def __init__(self, portal):
        self._bitrix_token = FakeToken(portal)


class FakePortal:
    """Двойник портала: помнит, что ему отправили, и этим же отвечает.

    Честное поведение по умолчанию (счёт создан с теми суммами, что послали)
    — чтобы «испорченный» портал приходилось задавать явно, а не наоборот.
    """

    def __init__(self, *, invoice_id=777, account_number="Б-00042",
                 opportunity=None, rows=None, templates=None,
                 errors=None, act=None, my_companies=None):
        self.invoice_id = invoice_id
        # Свои юрлица портала (crm.company.list с IS_MY_COMPANY=Y). Нужны
        # проверке настройки «наше юрлицо по умолчанию»: перед выставлением
        # приложение сверяет заданный id с этим списком.
        self.my_companies = my_companies if my_companies is not None else [
            {"ID": "7", "TITLE": "ООО Майнсофт"},
            {"ID": "68", "TITLE": "Мейнсофт"},
        ]
        self.account_number = account_number
        self.opportunity_override = opportunity
        self.rows_override = rows
        self.templates = templates if templates is not None else [
            {"id": 5, "name": "Счёт", "entityTypeId": ["31"]},
            {"id": 6, "name": "Акт выполненных работ", "entityTypeId": ["31"]},
        ]
        self.errors = errors or {}
        self.act = act or {
            "id": 991, "number": "АКТ-1",
            "downloadUrl": "https://portal/download/991",
            "publicUrl": "", "pdfUrl": "",
        }
        self.calls = []
        self.sent_invoice_fields = {}
        self.sent_rows = []

    def call(self, method, params):
        self.calls.append((method, params))
        if method in self.errors:
            raise self.errors[method]

        if method == "app.option.get":
            return {"result": {}}
        if method == "crm.item.add":
            self.sent_invoice_fields = dict(params.get("fields") or {})
            return {"result": {"item": {"id": self.invoice_id}}}
        if method == "crm.item.productrow.set":
            self.sent_rows = list(params.get("productRows") or [])
            return {"result": {"productRows": self.sent_rows}}
        if method == "crm.item.get":
            opportunity = (
                self.opportunity_override
                if self.opportunity_override is not None
                else self.sent_invoice_fields.get("opportunity")
            )
            return {"result": {"item": {
                "id": self.invoice_id,
                "opportunity": opportunity,
                "accountNumber": self.account_number,
            }}}
        if method == "crm.item.productrow.list":
            rows = self.rows_override if self.rows_override is not None else self.sent_rows
            return {"result": {"productRows": rows}}
        if method == "crm.company.list":
            return {"result": list(self.my_companies), "total": len(self.my_companies)}
        if method == "crm.documentgenerator.template.list":
            return {"result": {"templates": self.templates}}
        if method == "crm.documentgenerator.template.add":
            return {"result": {"template": {"id": 42}}}
        if method == "crm.documentgenerator.document.add":
            return {"result": {"document": self.act}}
        raise AssertionError(f"FakePortal: неожиданный метод {method}")

    def methods(self):
        return [method for method, _ in self.calls]


BILLING_SETTINGS = {"allow_open_period": False, "accountants": [], "act_template_id": 0}


class BillingEndpointFixture(TestCase):
    def setUp(self):
        cache.clear()
        self.portal = FakePortal()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-ep-billing",
            is_master_account=True, domain_url="ep.bitrix24.ru",
            status="active", application_version=1,
        )
        self.token = self.account.create_jwt_token()
        PortalUser.objects.create(
            bitrix24_account=self.account, bitrix_id="11", name="Егор", last_name="Цыганков",
        )
        ProjectCard.objects.create(
            bitrix24_account=self.account, project_id="73", project_name="Мейнсофт",
            stage="in_work", hourly_rate=2000.0,
            company_id="15", company_name="ООО Клиент",
            our_legal_entity_id="7", our_legal_entity_name="ООО Майнсофт",
        )
        self.feature = PortalFeature.objects.create(
            bitrix24_account=self.account, code=PortalFeature.CODE_BILLING,
            state=PortalFeature.STATE_ON,
        )
        self._client_patch = patch.object(
            Bitrix24Account, "client", property(lambda _self: FakeClient(self.portal)),
        )
        self._client_patch.start()
        self.addCleanup(self._client_patch.stop)

        self._settings_patch = patch(
            "main.billing_settings.load_billing_settings",
            side_effect=lambda account, client=None: dict(self.billing_settings),
        )
        self.billing_settings = dict(BILLING_SETTINGS)
        self._settings_patch.start()
        self.addCleanup(self._settings_patch.stop)

    def entry(self, bitrix_id, *, hours=2.0, rate=2000.0, day=15, employee_id="11",
              task_id="8365", project_id="73"):
        return TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=bitrix_id, task_id=task_id,
            employee_id=employee_id, hours=hours, is_billable=True,
            project_id=project_id, project_title="Мейнсофт", hourly_rate_snapshot=rate,
            description="разработка", task_hierarchy_ids=[task_id],
            task_hierarchy_titles=["Задача"],
            date_reflection=timezone.make_aware(datetime(2026, 8, day, 0, 0)),
        )

    def close_august(self):
        PeriodService(self.account).close(2026, 8, stats={}, by_id="11", by_name="Егор")

    def post(self, path, body=None, token=None):
        return Client().post(
            path, data=json.dumps(body or {}), content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token or self.token}",
        )

    def get(self, path, token=None):
        return Client().get(path, HTTP_AUTHORIZATION=f"Bearer {token or self.token}")

    def default_filter(self, **kwargs):
        payload = {"date_from": "2026-08-01", "date_to": "2026-08-31", "company_id": "15"}
        payload.update(kwargs)
        return payload


class PreviewEndpointTest(BillingEndpointFixture):
    def test_preview_returns_lines_and_warnings(self):
        self.entry(1)
        self.entry(2, hours=3.0)

        data = self.post("/api/billing/preview", self.default_filter()).json()

        self.assertEqual(data["entries_count"], 2)
        self.assertEqual(data["total_hours"], 5.0)
        self.assertEqual(data["total_amount"], 10000.0)
        self.assertIn("period_open", [w["code"] for w in data["warnings"]])

    def test_preview_writes_nothing(self):
        self.entry(1)

        self.post("/api/billing/preview", self.default_filter())

        self.assertEqual(BillingDocument.objects.count(), 0)
        self.assertEqual(self.portal.methods(), [])


class IssueEndpointTest(BillingEndpointFixture):
    def test_issue_creates_invoice_and_document(self):
        self.entry(1)
        self.entry(2)
        self.close_august()

        response = self.post("/api/billing/documents", self.default_filter())

        self.assertEqual(response.status_code, 201)
        document = BillingDocument.objects.get()
        self.assertEqual(document.status, BillingDocument.STATUS_ISSUED)
        self.assertEqual(document.crm_entity_id, "777")
        self.assertEqual(document.crm_account_number, "Б-00042")
        self.assertEqual(document.total_hours, 4.0)
        self.assertEqual(document.total_amount, 8000.0)
        self.assertEqual(document.company_id, "15")
        self.assertEqual(document.our_company_id, "7")
        self.assertEqual(document.lines.count(), 1)
        self.assertEqual(document.entries.filter(is_active=True).count(), 2)

    def test_issue_calls_crm_in_the_right_order(self):
        """Создать -> записать строки -> ПЕРЕЧИТАТЬ счёт и строки."""
        self.entry(1)
        self.close_august()

        self.post("/api/billing/documents", self.default_filter())

        self.assertEqual(
            self.portal.methods(),
            ["crm.item.add", "crm.item.productrow.set", "crm.item.get", "crm.item.productrow.list"],
        )

    def test_invoice_is_bound_to_both_companies(self):
        self.entry(1)
        self.close_august()

        self.post("/api/billing/documents", self.default_filter())

        self.assertEqual(self.portal.sent_invoice_fields["companyId"], 15)
        self.assertEqual(self.portal.sent_invoice_fields["mycompanyId"], 7)
        self.assertEqual(self.portal.sent_invoice_fields["currencyId"], "RUB")

    def test_product_rows_carry_hours_and_rate(self):
        self.entry(1, hours=2.0, rate=2000.0)
        self.entry(2, hours=1.0, rate=2000.0)
        self.close_august()

        self.post("/api/billing/documents", self.default_filter())

        self.assertEqual(len(self.portal.sent_rows), 1)
        row = self.portal.sent_rows[0]
        self.assertEqual(row["quantity"], 3.0)
        self.assertEqual(row["price"], 2000.0)
        # В товарную строку счёта уходит НАЗВАНИЕ ЗАДАЧИ по шаблону портала,
        # а не имя карточки проекта: обе записи отражены в одной задаче.
        self.assertEqual(row["productName"], "Задача, август 2026")

    def test_repeat_issue_of_same_entries_is_409(self):
        self.entry(1)
        self.close_august()
        self.post("/api/billing/documents", self.default_filter())

        response = self.post("/api/billing/documents", self.default_filter())

        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertEqual(data["code"], "already_invoiced")
        self.assertEqual(data["document_ids"], [str(BillingDocument.objects.get().pk)])
        self.assertEqual(BillingDocument.objects.count(), 1)

    def test_cancel_frees_entries_for_reissue(self):
        self.entry(1)
        self.close_august()
        first = self.post("/api/billing/documents", self.default_filter()).json()["document"]

        cancelled = self.post(
            f"/api/billing/documents/{first['id']}/cancel", {"reason": "ошиблись периодом"},
        )
        second = self.post("/api/billing/documents", self.default_filter())

        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["document"]["status"], "cancelled")
        self.assertEqual(second.status_code, 201)
        self.assertEqual(BillingEntry.objects.filter(is_active=True).count(), 1)

    def test_cancel_without_reason_is_rejected(self):
        self.entry(1)
        self.close_august()
        document = self.post("/api/billing/documents", self.default_filter()).json()["document"]

        response = self.post(f"/api/billing/documents/{document['id']}/cancel", {})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "cancel_reason_required")

    def test_empty_selection_is_400(self):
        self.close_august()

        response = self.post("/api/billing/documents", self.default_filter())

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "empty_selection")

    def test_unknown_document_is_404(self):
        response = self.get("/api/billing/documents/00000000-0000-0000-0000-000000000000")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "not_found")


class ClosedPeriodEndpointTest(BillingEndpointFixture):
    def test_open_period_is_refused_by_default(self):
        self.entry(1)

        response = self.post("/api/billing/documents", self.default_filter())

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "period_open")
        self.assertEqual(BillingDocument.objects.count(), 0)
        self.assertEqual(self.portal.methods(), [])

    def test_setting_allows_open_period(self):
        self.entry(1)
        self.billing_settings["allow_open_period"] = True

        response = self.post("/api/billing/documents", self.default_filter())

        self.assertEqual(response.status_code, 201)


class CrmVerificationTest(BillingEndpointFixture):
    """Ответам REST Битрикс24 верить нельзя — и это проверяется здесь."""

    def test_wrong_invoice_total_fails_the_issue(self):
        self.entry(1)
        self.close_august()
        self.portal.opportunity_override = 1.0

        response = self.post("/api/billing/documents", self.default_filter())

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "crm_amount_mismatch")

    def test_failed_issue_frees_the_entries(self):
        """Счёт в CRM остался — документ снят, списания свободны для повтора."""
        self.entry(1)
        self.close_august()
        self.portal.opportunity_override = 1.0

        self.post("/api/billing/documents", self.default_filter())

        document = BillingDocument.objects.get()
        self.assertEqual(document.status, BillingDocument.STATUS_CANCELLED)
        self.assertEqual(document.crm_entity_id, "777")
        self.assertEqual(BillingEntry.objects.filter(is_active=True).count(), 0)

    def test_wrong_product_rows_total_fails_the_issue(self):
        self.entry(1)
        self.close_august()
        self.portal.rows_override = [{"price": 1.0, "quantity": 1.0}]

        response = self.post("/api/billing/documents", self.default_filter())

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "crm_amount_mismatch")

    def test_unparseable_invoice_answer_fails_the_issue(self):
        self.entry(1)
        self.close_august()
        self.portal.errors["crm.item.get"] = RuntimeError("портал молчит")

        response = self.post("/api/billing/documents", self.default_filter())

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "crm_verify_failed")

    def test_failed_invoice_creation_removes_the_document(self):
        """id счёта не получен — документа не остаётся вовсе, реестр чистый."""
        self.entry(1)
        self.close_august()
        self.portal.errors["crm.item.add"] = RuntimeError("нет прав на crm")

        response = self.post("/api/billing/documents", self.default_filter())

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "crm_invoice_failed")
        self.assertEqual(BillingDocument.objects.count(), 0)
        self.assertEqual(BillingEntry.objects.count(), 0)


class ConcurrencyTest(BillingEndpointFixture):
    """Гонка двух «Выставить» на одном портале.

    Замок — postgres-advisory (на sqlite он no-op), поэтому проверяется не он
    сам, а реакция эндпоинта на занятость: понятный 409 со своим кодом, а не
    чужой текст про синхронизацию и не исключение наружу.
    """

    def test_busy_lock_gives_its_own_409(self):
        from .utils.decorators.sync_lock import SyncLockBusy

        self.entry(1)
        self.close_august()

        with patch("main.views.account_sync_lock", side_effect=SyncLockBusy):
            response = self.post("/api/billing/documents", self.default_filter())

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "billing_busy")
        self.assertEqual(BillingDocument.objects.count(), 0)
        self.assertEqual(self.portal.methods(), [])


class PermissionTest(BillingEndpointFixture):
    def _plain_user(self, user_id=99):
        account = Bitrix24Account.objects.create(
            b24_user_id=user_id, is_b24_user_admin=False, member_id="m-ep-billing",
            is_master_account=False, domain_url="ep.bitrix24.ru",
            status="active", application_version=1,
        )
        return account, account.create_jwt_token()

    def test_plain_user_cannot_issue(self):
        self.entry(1)
        self.close_august()
        _account, token = self._plain_user()

        response = self.post("/api/billing/documents", self.default_filter(), token=token)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "billing_forbidden")

    def test_plain_user_cannot_cancel(self):
        self.entry(1)
        self.close_august()
        document = self.post("/api/billing/documents", self.default_filter()).json()["document"]
        _account, token = self._plain_user()

        response = self.post(
            f"/api/billing/documents/{document['id']}/cancel", {"reason": "нет"}, token=token,
        )

        self.assertEqual(response.status_code, 403)

    def test_accountant_from_settings_can_issue(self):
        """Данные заводим на саму учётку бухгалтера: строки списаний в этом
        приложении лежат по учёткам (уникальность «учётка + bitrix_id»), и
        чужих он бы просто не увидел — тест проверял бы не право, а пустоту."""
        account, token = self._plain_user(user_id=99)
        self.billing_settings["accountants"] = ["99"]
        ProjectCard.objects.create(
            bitrix24_account=account, project_id="73", project_name="Мейнсофт",
            stage="in_work", hourly_rate=2000.0,
            company_id="15", company_name="ООО Клиент",
            our_legal_entity_id="7", our_legal_entity_name="ООО Майнсофт",
        )
        TimesheetItem.objects.create(
            bitrix24_account=account, bitrix_id=1, task_id="8365", employee_id="99",
            hours=2.0, is_billable=True, project_id="73", project_title="Мейнсофт",
            hourly_rate_snapshot=2000.0, task_hierarchy_ids=["8365"],
            task_hierarchy_titles=["Задача"],
            date_reflection=timezone.make_aware(datetime(2026, 8, 15, 0, 0)),
        )
        PeriodService(account).close(2026, 8, stats={}, by_id="99", by_name="Бухгалтер")

        response = self.post("/api/billing/documents", self.default_filter(), token=token)

        self.assertEqual(response.status_code, 201)

    def test_plain_user_can_read_the_registry(self):
        """Чтение реестра гейта не имеет: гейт только на пишущих операциях."""
        _account, token = self._plain_user()

        response = self.get("/api/billing/documents", token=token)

        self.assertEqual(response.status_code, 200)

    def test_endpoints_require_jwt(self):
        """Без токена ни один адрес счёта не отдаёт данных.

        Код — 401 или 400: @auth_required без заголовка Authorization уходит
        в OAuth-ветку и отвечает 400 на негодное тело. Закрепляется главное —
        что это отказ, а не ответ.
        """
        for path in ("/api/features", "/api/billing/documents"):
            with self.subTest(path=path):
                self.assertIn(Client().get(path).status_code, (400, 401))


class FeatureFlagTest(BillingEndpointFixture):
    def test_features_endpoint_reports_state(self):
        data = self.get("/api/features").json()

        self.assertEqual(data["billing"]["state"], "on")
        self.assertTrue(data["billing"]["enabled"])

    def test_missing_row_means_off(self):
        self.feature.delete()

        data = self.get("/api/features").json()

        self.assertEqual(data["billing"]["state"], "off")
        self.assertFalse(data["billing"]["enabled"])

    def test_disabled_feature_blocks_issue(self):
        self.entry(1)
        self.close_august()
        self.feature.state = PortalFeature.STATE_OFF
        self.feature.save(update_fields=["state"])

        response = self.post("/api/billing/documents", self.default_filter())

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "feature_disabled")

    def test_disabled_feature_allows_reading_and_cancelling(self):
        """Контракт, п. 2: отключение подписки не отбирает уже выставленное."""
        self.entry(1)
        self.close_august()
        document = self.post("/api/billing/documents", self.default_filter()).json()["document"]
        self.feature.state = PortalFeature.STATE_OFF
        self.feature.save(update_fields=["state"])

        listed = self.get("/api/billing/documents")
        card = self.get(f"/api/billing/documents/{document['id']}")
        cancelled = self.post(
            f"/api/billing/documents/{document['id']}/cancel", {"reason": "подписка кончилась"},
        )

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(card.status_code, 200)
        self.assertEqual(cancelled.status_code, 200)

    def test_expired_trial_is_off(self):
        self.feature.state = PortalFeature.STATE_TRIAL
        self.feature.trial_until = timezone.now() - timezone.timedelta(days=1)
        self.feature.save(update_fields=["state", "trial_until"])

        self.assertFalse(self.get("/api/features").json()["billing"]["enabled"])

    def test_live_trial_is_on(self):
        self.feature.state = PortalFeature.STATE_TRIAL
        self.feature.trial_until = timezone.now() + timezone.timedelta(days=3)
        self.feature.save(update_fields=["state", "trial_until"])

        self.assertTrue(self.get("/api/features").json()["billing"]["enabled"])

    def test_feature_is_portal_wide_not_per_user(self):
        """Учётка — на сотрудника, подписка — на портал (см. billing_features)."""
        colleague = Bitrix24Account.objects.create(
            b24_user_id=12, is_b24_user_admin=True, member_id="m-ep-billing",
            is_master_account=False, domain_url="ep.bitrix24.ru",
            status="active", application_version=1,
        )

        data = self.get("/api/features", token=colleague.create_jwt_token()).json()

        self.assertTrue(data["billing"]["enabled"])


class DocumentCardTest(BillingEndpointFixture):
    def test_card_shows_lines_entries_and_drift(self):
        self.entry(1, hours=2.0)
        self.close_august()
        created = self.post("/api/billing/documents", self.default_filter()).json()["document"]
        TimesheetItem.objects.filter(bitrix_id=1).update(hours=7.0)

        card = self.get(f"/api/billing/documents/{created['id']}").json()

        # Строки, списания и расхождения лежат и наверху ответа, и внутри
        # document — закрепляем обе формы, интерфейс читает верхнюю.
        self.assertEqual(len(card["lines"]), 1)
        self.assertEqual(len(card["entries"]), 1)
        self.assertEqual(card["drift"][0]["kind"], "changed")
        self.assertEqual(card["drift"][0]["current_hours"], 7.0)
        self.assertEqual(card["document"]["drift"], card["drift"])

    def test_registry_filters_by_company_and_status(self):
        self.entry(1)
        self.close_august()
        self.post("/api/billing/documents", self.default_filter())

        matched = self.get("/api/billing/documents?company_id=15&status=issued").json()
        missed = self.get("/api/billing/documents?company_id=999").json()

        self.assertEqual(matched["total"], 1)
        self.assertEqual(missed["total"], 0)

    def test_registry_finds_document_by_overlapping_period(self):
        self.entry(1)
        self.close_august()
        self.post("/api/billing/documents", self.default_filter())

        overlapping = self.get("/api/billing/documents?date_from=2026-08-15&date_to=2026-09-30")

        self.assertEqual(overlapping.json()["total"], 1)


class ActTest(BillingEndpointFixture):
    def _issued(self):
        self.entry(1)
        self.close_august()
        return self.post("/api/billing/documents", self.default_filter()).json()["document"]

    def test_act_is_printed_by_template_named_act(self):
        document = self._issued()

        response = self.post(f"/api/billing/documents/{document['id']}/act", {})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["act_document_id"], "991")
        self.assertEqual(data["act_download_url"], "https://portal/download/991")
        add_call = next(p for m, p in self.portal.calls if m == "crm.documentgenerator.document.add")
        self.assertEqual(add_call["templateId"], 6)
        self.assertEqual(add_call["entityTypeId"], 31)
        self.assertEqual(add_call["entityId"], 777)

    def test_act_number_equals_invoice_number_when_generator_gives_none(self):
        """Контракт, п. 6: номер акта равен номеру счёта."""
        self.portal.act = {"id": 991, "number": ""}
        document = self._issued()

        self.post(f"/api/billing/documents/{document['id']}/act", {})

        self.assertEqual(BillingDocument.objects.get().act_number, "Б-00042")

    def test_missing_template_gives_code_not_500(self):
        self.portal.templates = []
        document = self._issued()

        response = self.post(f"/api/billing/documents/{document['id']}/act", {})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "act_template_missing")
        self.assertIn("шаблон", BillingDocument.objects.get().act_error.lower())

    def test_only_foreign_templates_give_missing_code(self):
        self.portal.templates = [{"id": 9, "name": "Счёт", "entityTypeId": ["31"]}]
        document = self._issued()

        response = self.post(f"/api/billing/documents/{document['id']}/act", {})

        self.assertEqual(response.json()["code"], "act_template_missing")

    def test_unavailable_generator_gives_code_not_500(self):
        self.portal.errors["crm.documentgenerator.template.list"] = RuntimeError(
            "ERROR_METHOD_NOT_FOUND: Method not found!"
        )
        document = self._issued()

        response = self.post(f"/api/billing/documents/{document['id']}/act", {})

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "documentgenerator_unavailable")
        self.assertIn("генератор", BillingDocument.objects.get().act_error.lower())

    def test_generation_failure_gives_code_not_500(self):
        self.portal.errors["crm.documentgenerator.document.add"] = RuntimeError("шаблон битый")
        document = self._issued()

        response = self.post(f"/api/billing/documents/{document['id']}/act", {})

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "act_generation_failed")

    def test_explicit_template_id_wins(self):
        document = self._issued()

        self.post(f"/api/billing/documents/{document['id']}/act", {"template_id": 77})

        self.assertNotIn("crm.documentgenerator.template.list", self.portal.methods())
        add_call = next(p for m, p in self.portal.calls if m == "crm.documentgenerator.document.add")
        self.assertEqual(add_call["templateId"], 77)

    def test_own_template_is_created_only_on_demand(self):
        """Свой шаблон — предусмотренный, но не обязательный путь."""
        document = self._issued()

        self.post(
            f"/api/billing/documents/{document['id']}/act",
            {"template_docx_base64": "UEsDBBQA"},
        )

        self.assertIn("crm.documentgenerator.template.add", self.portal.methods())
        add_call = next(p for m, p in self.portal.calls if m == "crm.documentgenerator.document.add")
        self.assertEqual(add_call["templateId"], 42)

    def test_act_of_cancelled_document_is_refused(self):
        document = self._issued()
        self.post(f"/api/billing/documents/{document['id']}/cancel", {"reason": "отбой"})

        response = self.post(f"/api/billing/documents/{document['id']}/act", {})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "document_cancelled")

    def test_act_needs_the_feature(self):
        document = self._issued()
        self.feature.state = PortalFeature.STATE_OFF
        self.feature.save(update_fields=["state"])

        response = self.post(f"/api/billing/documents/{document['id']}/act", {})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "feature_disabled")


class DetailExportTest(BillingEndpointFixture):
    def test_xlsx_contains_entries_and_total(self):
        self.entry(1, hours=2.0)
        self.entry(2, hours=3.0)
        self.close_august()
        document = self.post("/api/billing/documents", self.default_filter()).json()["document"]

        response = self.get(f"/api/billing/documents/{document['id']}/detail.xlsx")

        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml", response["Content-Type"])
        workbook = openpyxl.load_workbook(io.BytesIO(response.content))
        rows = list(workbook.active.values)
        header = rows[1]
        self.assertEqual(
            list(header),
            ["Дата", "Сотрудник", "Задача", "Описание", "Часы", "Ставка", "Сумма"],
        )
        self.assertEqual(len(rows), 5)  # заголовок, шапка, две записи, итог
        self.assertEqual(rows[-1][0], "ИТОГО")
        self.assertEqual(rows[-1][4], 5.0)
        self.assertEqual(rows[-1][6], 10000.0)
        self.assertEqual(rows[2][1], "Цыганков Егор")

    def test_export_of_unknown_document_is_404(self):
        response = self.get("/api/billing/documents/нет-такого/detail.xlsx")

        self.assertEqual(response.status_code, 404)


class ApprovedLinesEndpointTest(BillingEndpointFixture):
    """Мастер прислал утверждённые строки — сквозь всю ручку выставления.

    Проверяется главное обещание интерфейса: исключённая строка не попадает
    ни в наш документ, ни в счёт CRM, и её часы остаются свободными — их
    можно выставить следующим счётом.
    """

    def setUp(self):
        super().setUp()
        ProjectCard.objects.create(
            bitrix24_account=self.account, project_id="74", project_name="Второй проект",
            stage="in_work", hourly_rate=1000.0,
            company_id="15", company_name="ООО Клиент",
            our_legal_entity_id="7", our_legal_entity_name="ООО Майнсофт",
        )

    @staticmethod
    def line(**overrides):
        row = {
            "project_id": "73", "title": "Мейнсофт",
            "hours": 2.0, "rate": 2000.0, "amount": 4000.0, "sort": 10,
        }
        row.update(overrides)
        return row

    @staticmethod
    def second_line(**overrides):
        row = {
            "project_id": "74", "title": "Второй проект",
            "hours": 2.0, "rate": 1000.0, "amount": 2000.0, "sort": 10,
        }
        row.update(overrides)
        return row

    def test_excluded_line_is_free_for_the_next_invoice(self):
        self.entry(1, project_id="73")
        self.entry(2, project_id="74", rate=1000.0)
        self.close_august()

        # Группировка задана явно: строки этого теста — по проектам, а обе
        # записи отражены в одной и той же задаче.
        first = self.post("/api/billing/documents", self.default_filter(
            grouping="project", lines=[self.line()],
        ))

        self.assertEqual(first.status_code, 201)
        document = BillingDocument.objects.get()
        self.assertEqual(document.lines.count(), 1)
        self.assertEqual(document.total_hours, 2.0)
        self.assertEqual(document.total_amount, 4000.0)
        self.assertEqual([row.timesheet_bitrix_id for row in document.entries.all()], [1])
        self.assertEqual(len(self.portal.sent_rows), 1)

        # Часы исключённой строки не потреблены — второй счёт их забирает.
        second = self.post("/api/billing/documents", self.default_filter(
            grouping="project", lines=[self.second_line()],
        ))

        self.assertEqual(second.status_code, 201)
        self.assertEqual(BillingDocument.objects.count(), 2)
        self.assertEqual(BillingEntry.objects.filter(is_active=True).count(), 2)
        latest = BillingDocument.objects.exclude(pk=document.pk).get()
        self.assertEqual(latest.total_amount, 2000.0)
        self.assertEqual([row.timesheet_bitrix_id for row in latest.entries.all()], [2])

    def test_edited_rate_and_title_reach_document_and_crm(self):
        self.entry(1)
        self.close_august()

        response = self.post("/api/billing/documents", self.default_filter(
            lines=[self.line(title="Разработка, август 2026", rate=2500.0, amount=5000.0)],
        ))

        self.assertEqual(response.status_code, 201)
        document = BillingDocument.objects.get()
        line = document.lines.get()
        self.assertEqual(line.title, "Разработка, август 2026")
        self.assertEqual(line.rate, 2500.0)
        self.assertEqual(line.amount, 5000.0)
        self.assertEqual(document.total_amount, 5000.0)
        # В CRM уезжает утверждённое, а не собранное заново из отбора.
        self.assertEqual(self.portal.sent_rows[0]["price"], 2500.0)
        self.assertEqual(self.portal.sent_rows[0]["productName"], "Разработка, август 2026")
        self.assertEqual(self.portal.sent_invoice_fields["opportunity"], 5000.0)

    def test_foreign_project_is_400_and_writes_nothing(self):
        self.entry(1)
        self.close_august()

        response = self.post("/api/billing/documents", self.default_filter(
            lines=[self.line(project_id="999")],
        ))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "lines_mismatch")
        self.assertEqual(BillingDocument.objects.count(), 0)
        self.assertEqual(BillingEntry.objects.count(), 0)
        self.assertEqual(self.portal.methods(), [])

    def test_inflated_hours_are_400(self):
        self.entry(1, hours=2.0)
        self.close_august()

        response = self.post("/api/billing/documents", self.default_filter(
            lines=[self.line(hours=40.0, amount=80000.0)],
        ))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "lines_mismatch")
        self.assertEqual(BillingDocument.objects.count(), 0)
        self.assertEqual(self.portal.methods(), [])

    def test_negative_rate_is_400(self):
        self.entry(1)
        self.close_august()

        response = self.post("/api/billing/documents", self.default_filter(
            lines=[self.line(rate=-2000.0, amount=-4000.0)],
        ))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "lines_mismatch")
        self.assertEqual(BillingDocument.objects.count(), 0)

    def test_all_lines_excluded_is_400(self):
        self.entry(1)
        self.close_august()

        response = self.post("/api/billing/documents", self.default_filter(lines=[]))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "empty_selection")
        self.assertEqual(BillingDocument.objects.count(), 0)
        self.assertEqual(self.portal.methods(), [])

    def test_without_lines_whole_selection_is_invoiced(self):
        """Обратная совместимость: тела без lines[] ведут себя как раньше."""
        self.entry(1, project_id="73")
        self.entry(2, project_id="74", rate=1000.0)
        self.close_august()

        response = self.post("/api/billing/documents", self.default_filter(grouping="project"))

        self.assertEqual(response.status_code, 201)
        document = BillingDocument.objects.get()
        self.assertEqual(document.lines.count(), 2)
        self.assertEqual(document.total_hours, 4.0)
        self.assertEqual(document.total_amount, 6000.0)
        self.assertEqual(document.entries.filter(is_active=True).count(), 2)
        self.assertEqual(len(self.portal.sent_rows), 2)
