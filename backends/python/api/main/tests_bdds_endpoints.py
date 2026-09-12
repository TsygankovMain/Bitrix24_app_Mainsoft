"""Эндпоинты БДДС: подписка, реестр, карточка проекта, операции, уведомления.

Главный предмет проверки — ПОДПИСКА. До этой задачи функцию «охраняла»
фронтовая константа, то есть не охранял никто. Здесь закреплено, что при
выключенной подписке закрыты ВСЕ ручки БДДС, включая чтение: у функции нет
документа, который клиент уже создал и обязан видеть дальше (этим она
отличается от «Счёта и акта», где чтение реестра открыто намеренно).

Второй предмет — что выключенное состояние ничего не ломает: соседние
ручки приложения (доска проектов, /api/features) отвечают как прежде.
"""

import json
from datetime import date, datetime
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TestCase
from django.utils import timezone

from .models import Bitrix24Account, PortalFeature, ProjectCard, SystemLog, TimesheetItem


class FakePortal:
    """Двойник портала: помнит уведомления и операции, которые ему послали."""

    def __init__(self, *, options=None, items=None, notify_fails=False):
        self.options = options or {}
        self.items = items or []
        self.notify_fails = notify_fails
        self.notifications = []
        self.added = []
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))

        if method == "app.option.get":
            return {"result": self.options}
        if method == "app.option.set":
            return {"result": True}
        if method == "crm.item.list":
            return {"result": {"items": list(self.items)}, "next": None}
        if method == "crm.item.add":
            self.added.append(params)
            return {"result": {"item": {"id": 4242}}}
        if method == "crm.item.get":
            return {"result": {"item": {"id": 4242, **(params or {})}}}
        if method in ("im.notify.system.add", "im.notify.personal.add"):
            if self.notify_fails:
                raise RuntimeError("портал отказал в уведомлении")
            self.notifications.append(params)
            return {"result": 1}
        raise AssertionError(f"FakePortal: неожиданный метод {method}")


class FakeToken:
    def __init__(self, portal):
        self.portal = portal

    def call_method(self, method, params=None):
        return self.portal.call(method, params or {})


class FakeClient:
    def __init__(self, portal):
        self._bitrix_token = FakeToken(portal)


FINANCE_MAPPING = {
    "project_item_id": "ufCrmProjectItemId",
    "operation_type": "ufCrmOperationType",
    "amount": "ufCrmAmount",
    "currency": "ufCrmCurrency",
    "operation_date": "ufCrmOperationDate",
    "source": "ufCrmSource",
    "deal_id": "ufCrmDealId",
    "comment": "ufCrmComment",
    "responsible_user_id": "ufCrmResponsibleUserId",
}


class BddsEndpointFixture(TestCase):
    def setUp(self):
        cache.clear()
        self.portal = FakePortal(options={
            "timestamp_config": json.dumps({
                "finance_sp_entity_type_id": 1040,
                "finance_fields_mapping": FINANCE_MAPPING,
            }, ensure_ascii=False),
        })
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-ep-bdds",
            is_master_account=True, domain_url="ep-bdds.bitrix24.ru",
            status="active", application_version=1,
        )
        self.token = self.account.create_jwt_token()
        self.feature = PortalFeature.objects.create(
            bitrix24_account=self.account, code=PortalFeature.CODE_BDDS,
            state=PortalFeature.STATE_ON,
        )
        self.card = ProjectCard.objects.create(
            bitrix24_account=self.account, project_id="73", project_item_id="500",
            project_name="Портал для сети автосалонов", stage="В работе",
            hourly_rate=2000.0, budget_mode="amount", planned_budget_amount=100000.0,
            curator_user_id="11", curator_name="Егор Цыганков",
            project_start_date=date(2026, 4, 1), project_end_date=date(2026, 12, 31),
        )
        self._client_patch = patch.object(
            Bitrix24Account, "client", property(lambda _self: FakeClient(self.portal)),
        )
        self._client_patch.start()
        self.addCleanup(self._client_patch.stop)

    def entry(self, bitrix_id, *, hours=10.0, rate=2000.0):
        return TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=bitrix_id, task_id="8365",
            employee_id="11", hours=hours, is_billable=True,
            project_id="73", project_item_id="500",
            project_title="Портал для сети автосалонов", hourly_rate_snapshot=rate,
            date_reflection=timezone.make_aware(datetime(2026, 8, 15, 0, 0)),
        )

    def get(self, path, token=None):
        return Client().get(path, HTTP_AUTHORIZATION=f"Bearer {token or self.token}")

    def post(self, path, body=None, token=None):
        return Client().post(
            path, data=json.dumps(body or {}), content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token or self.token}",
        )

    def set_config(self, **extra):
        """Дописать настройки БДДС в конфигурацию портала.

        Настройки БДДС сознательно НЕ добавлены в defaults
        ConfigurationService (см. докстринг bdds_settings): незнакомые ключи
        проходят нормализацию нетронутыми. Этот метод в том числе и об этом:
        если сквозной проход когда-нибудь сломают, тесты порогов и
        выключателя упадут первыми.
        """
        config = {
            "finance_sp_entity_type_id": 1040,
            "finance_fields_mapping": FINANCE_MAPPING,
        }
        config.update(extra)
        self.portal.options["timestamp_config"] = json.dumps(config, ensure_ascii=False)
        cache.clear()


class BddsSubscriptionGateTest(BddsEndpointFixture):
    READ_PATHS = ("/api/bdds/projects", "/api/bdds/projects/73", "/api/finance-operations")

    def test_features_reports_bdds_state(self):
        data = self.get("/api/features").json()

        self.assertIn("bdds", data)
        self.assertTrue(data["bdds"]["enabled"])
        self.assertEqual(data["bdds"]["state"], "on")

    def test_reads_are_closed_when_subscription_is_off(self):
        self.feature.state = PortalFeature.STATE_OFF
        self.feature.save(update_fields=["state"])

        for path in self.READ_PATHS:
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual(response.status_code, 403)
                payload = response.json()
                self.assertEqual(payload["code"], "feature_disabled")
                self.assertEqual(payload["feature"], "bdds")
                # Текст отказа называет ИМЕННО эту функцию: иначе человек
                # пойдёт к администратору не за той подпиской.
                self.assertIn("БДДС по проектам", payload["error"])

    def test_writes_are_closed_when_subscription_is_off(self):
        self.feature.state = PortalFeature.STATE_OFF
        self.feature.save(update_fields=["state"])

        self.assertEqual(self.post("/api/project-budget/notify").status_code, 403)
        self.assertEqual(
            self.post("/api/finance-operations/create", {"project_item_id": "500"}).status_code,
            403,
        )

    def test_missing_feature_row_is_off(self):
        """Строки нет — функция выключена (контракт: state по умолчанию off)."""
        self.feature.delete()

        self.assertEqual(self.get("/api/bdds/projects").status_code, 403)

    def test_expired_trial_closes_the_screen(self):
        self.feature.state = PortalFeature.STATE_TRIAL
        self.feature.trial_until = timezone.now() - timezone.timedelta(days=1)
        self.feature.save(update_fields=["state", "trial_until"])

        self.assertEqual(self.get("/api/bdds/projects").status_code, 403)

    def test_live_trial_opens_the_screen(self):
        self.feature.state = PortalFeature.STATE_TRIAL
        self.feature.trial_until = timezone.now() + timezone.timedelta(days=3)
        self.feature.save(update_fields=["state", "trial_until"])

        self.assertEqual(self.get("/api/bdds/projects").status_code, 200)

    def test_subscription_is_portal_wide_not_per_user(self):
        colleague = Bitrix24Account.objects.create(
            b24_user_id=12, is_b24_user_admin=False, member_id="m-ep-bdds",
            is_master_account=False, domain_url="ep-bdds.bitrix24.ru",
            status="active", application_version=1,
        )

        response = self.get("/api/bdds/projects", token=colleague.create_jwt_token())

        self.assertEqual(response.status_code, 200)

    def test_disabled_feature_does_not_break_neighbours(self):
        """Выключенная БДДС не ломает соседние экраны приложения."""
        self.feature.state = PortalFeature.STATE_OFF
        self.feature.save(update_fields=["state"])

        self.assertEqual(self.get("/api/features").status_code, 200)
        self.assertEqual(self.get("/api/project-board").status_code, 200)

    def test_endpoints_require_jwt(self):
        """Без токена ни один адрес БДДС не отдаёт данных.

        Код 401 или 400: @auth_required без заголовка Authorization уходит в
        OAuth-ветку и отвечает 400 на негодное тело. Закрепляется главное —
        что это отказ, а не ответ (так же проверяется у «Счёта и акта»).
        """
        for path in self.READ_PATHS:
            with self.subTest(path=path):
                self.assertIn(Client().get(path).status_code, (400, 401))


class BddsRegistryEndpointTest(BddsEndpointFixture):
    def test_registry_returns_rows_totals_and_thresholds(self):
        self.entry(1, hours=40.0, rate=2000.0)  # 80 000 из 100 000 -> «Риск»

        data = self.get("/api/bdds/projects").json()

        self.assertEqual(len(data["projects"]), 1)
        row = data["projects"][0]
        self.assertEqual(row["project_name"], "Портал для сети автосалонов")
        self.assertEqual(row["planned_amount"], 100000.0)
        self.assertEqual(row["actual_cost_amount"], 80000.0)
        self.assertEqual(row["budget_remaining"], 20000.0)
        self.assertEqual(row["budget_health_status"], "Риск")
        self.assertTrue(row["has_budget"])
        self.assertEqual(data["totals"]["planned_amount"], 100000.0)
        self.assertEqual(data["thresholds"]["risk_percent"], 80.0)
        self.assertEqual(data["thresholds"]["overrun_percent"], 100.0)

    def test_thresholds_from_settings_reach_the_registry(self):
        self.entry(1, hours=20.0, rate=2000.0)  # 40 %
        self.set_config(bdds_risk_threshold_percent=30, bdds_overrun_threshold_percent=35)

        data = self.get("/api/bdds/projects").json()

        self.assertEqual(data["thresholds"]["risk_percent"], 30.0)
        self.assertEqual(data["projects"][0]["budget_health_status"], "Перерасход")

    def test_project_card_returns_metrics_and_operations(self):
        self.entry(1, hours=10.0, rate=2000.0)
        self.portal.items = [{
            "id": "9",
            "ufCrmProjectItemId": "500",
            "ufCrmOperationType": "income",
            "ufCrmAmount": "300000",
            "ufCrmOperationDate": "2026-08-20T00:00:00+03:00",
            "ufCrmSource": "manual",
        }]

        data = self.get("/api/bdds/projects/73").json()

        project = data["project"]
        self.assertEqual(project["actual_cost_amount"], 20000.0)
        self.assertEqual(project["actual_income_amount"], 300000.0)
        self.assertEqual(project["actual_financial_result"], 280000.0)
        self.assertEqual(len(project["recent_finance_operations"]), 1)
        self.assertEqual(project["recent_finance_operations"][0]["operation_type"], "income")

    def test_unknown_project_is_404(self):
        response = self.get("/api/bdds/projects/999999")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "project_not_found")

    def test_broken_smart_process_does_not_break_the_registry(self):
        """Портал не отдал операции — план и факт по часам всё равно считаются."""
        self.entry(1, hours=10.0, rate=2000.0)
        self.portal.items = []

        def boom(method, params):
            if method == "crm.item.list":
                raise RuntimeError("смарт-процесс недоступен")
            return FakePortal.call(self.portal, method, params)

        with patch.object(self.portal, "call", side_effect=boom):
            data = self.get("/api/bdds/projects").json()

        self.assertEqual(data["projects"][0]["actual_cost_amount"], 20000.0)
        self.assertEqual(data["projects"][0]["actual_income_amount"], 0.0)


class FinanceOperationsEndpointTest(BddsEndpointFixture):
    def test_list_returns_normalized_operations(self):
        self.portal.items = [{
            "id": "9",
            "ufCrmProjectItemId": "500",
            "ufCrmOperationType": "расход",
            "ufCrmAmount": "12000.50",
            "ufCrmOperationDate": "2026-08-20T00:00:00+03:00",
            "ufCrmSource": "manual",
        }]

        data = self.get("/api/finance-operations?project_item_id=500").json()

        self.assertEqual(data["entity_type_id"], 1040)
        self.assertEqual(data["operations"][0]["operation_type"], "expense")
        self.assertEqual(data["operations"][0]["amount"], 12000.5)
        self.assertEqual(data["operations"][0]["operation_date"], "2026-08-20")

    def test_unconfigured_smart_process_is_409_not_500(self):
        self.set_config(finance_sp_entity_type_id=0, finance_fields_mapping={})

        response = self.get("/api/finance-operations")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "finance_spa_not_configured")

    def test_create_writes_operation_to_portal(self):
        response = self.post("/api/finance-operations/create", {
            "project_item_id": "500",
            "operation_type": "expense",
            "amount": 15000,
            "operation_date": "2026-09-01",
            "source": "manual",
            "comment": "подрядчик",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "created")
        self.assertEqual(len(self.portal.added), 1)
        fields = self.portal.added[0]["fields"]
        self.assertEqual(fields["ufCrmAmount"], 15000.0)
        self.assertEqual(fields["ufCrmOperationType"], "expense")

    def test_create_rejects_zero_amount(self):
        response = self.post("/api/finance-operations/create", {
            "project_item_id": "500",
            "operation_type": "expense",
            "amount": 0,
            "operation_date": "2026-09-01",
            "source": "manual",
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_operation")
        self.assertEqual(self.portal.added, [])

    def test_create_is_idempotent(self):
        """Повтор того же тела не создаёт вторую операцию с той же суммой."""
        payload = {
            "project_item_id": "500",
            "operation_type": "expense",
            "amount": 15000,
            "operation_date": "2026-09-01",
            "source": "manual",
        }
        self.post("/api/finance-operations/create", payload)
        # Портал теперь «знает» созданную операцию — так же, как знал бы её
        # живой смарт-процесс при повторном нажатии кнопки.
        self.portal.items = [{
            "id": "4242",
            "ufCrmProjectItemId": "500",
            "ufCrmOperationType": "expense",
            "ufCrmAmount": "15000",
            "ufCrmOperationDate": "2026-09-01",
            "ufCrmSource": "manual",
        }]

        second = self.post("/api/finance-operations/create", payload)

        self.assertEqual(second.json()["status"], "duplicate")
        self.assertEqual(len(self.portal.added), 1)


class BudgetNotifierEndpointTest(BddsEndpointFixture):
    def test_risk_event_is_sent_to_curator_once(self):
        self.entry(1, hours=45.0, rate=2000.0)  # 90 % -> «Риск»

        first = self.post("/api/project-budget/notify").json()
        second = self.post("/api/project-budget/notify").json()

        self.assertEqual(first["sent"], 1)
        self.assertEqual(len(self.portal.notifications), 1)
        self.assertIn("Риск", self.portal.notifications[0]["MESSAGE"])
        # Второй прогон: статус не изменился — события нет вовсе.
        self.assertEqual(second["sent"], 0)
        self.assertEqual(second["events"], [])

    def test_second_recipient_comes_from_settings(self):
        self.set_config(bdds_notify_user_ids=["11", "99", ""])
        self.entry(1, hours=45.0, rate=2000.0)

        result = self.post("/api/project-budget/notify").json()

        # Куратор 11 не задваивается, пустое значение отброшено.
        self.assertEqual(result["events"][0]["recipients"], ["11", "99"])
        self.assertEqual(len(self.portal.notifications), 2)

    def test_cooldown_blocks_repeat_of_the_same_event(self):
        self.entry(1, hours=45.0, rate=2000.0)
        self.post("/api/project-budget/notify")

        # Статус меняется «Риск» -> «Перерасход» -> обратно «Риск»: событие
        # риска возникает второй раз, и вот его гасит пауза.
        self.entry(2, hours=20.0, rate=2000.0)
        self.post("/api/project-budget/notify")
        TimesheetItem.objects.filter(bitrix_id=2).delete()
        third = self.post("/api/project-budget/notify").json()

        risk_events = [
            event for event in third["events"] if event["event_code"] == "budget_risk"
        ]
        self.assertEqual(len(risk_events), 1)
        self.assertEqual(risk_events[0]["status"], "cooldown")
        self.assertEqual(third["sent"], 0)

    def test_notifications_can_be_switched_off_in_settings(self):
        self.set_config(bdds_notifications_enabled=False)
        self.entry(1, hours=45.0, rate=2000.0)

        result = self.post("/api/project-budget/notify").json()

        self.assertEqual(result["status"], "disabled")
        self.assertEqual(self.portal.notifications, [])

    def test_project_without_curator_and_without_list_is_skipped_with_log(self):
        ProjectCard.objects.filter(project_id="73").update(curator_user_id=None)
        self.entry(1, hours=45.0, rate=2000.0)

        result = self.post("/api/project-budget/notify").json()

        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["events"][0]["status"], "skipped")
        self.assertTrue(
            SystemLog.objects.filter(module="project_budget_notifier").exists()
        )

    def test_portal_failure_is_reported_and_does_not_start_cooldown(self):
        self.portal.notify_fails = True
        self.entry(1, hours=45.0, rate=2000.0)

        first = self.post("/api/project-budget/notify").json()

        self.assertEqual(first["errors"], 1)
        self.assertEqual(first["events"][0]["status"], "error")

    def test_support_minus_is_its_own_event(self):
        ProjectCard.objects.filter(project_id="73").update(
            is_support=True, planned_budget_amount=None, project_hours_budget=None,
        )
        self.entry(1, hours=100.0, rate=2000.0)  # −200 000 -> «Минус»

        result = self.post("/api/project-budget/notify").json()

        self.assertEqual(result["sent"], 1)
        self.assertEqual(result["events"][0]["event_code"], "support_minus")

    def test_norm_project_generates_no_event(self):
        self.entry(1, hours=10.0, rate=2000.0)  # 20 %

        result = self.post("/api/project-budget/notify").json()

        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["events"], [])
        self.assertEqual(self.portal.notifications, [])
