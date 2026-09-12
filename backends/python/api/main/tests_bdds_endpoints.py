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

from .models import Bitrix24Account, PortalRole, PortalSubscription, ProjectCard, SystemLog, TimesheetItem
from .pro_plan_service import set_account_plan


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
        self.feature = set_account_plan(self.account)
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
        self.feature.state = PortalSubscription.STATE_OFF
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
        self.feature.state = PortalSubscription.STATE_OFF
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

    def test_expired_trial_keeps_reading_and_closes_writing(self):
        """Истёкший пробный — «только чтение»: данные клиента остаются его данными."""
        self.feature.state = PortalSubscription.STATE_TRIAL
        self.feature.trial_until = timezone.localdate() - timezone.timedelta(days=2)
        self.feature.save(update_fields=["state", "trial_until"])

        self.assertEqual(self.get("/api/bdds/projects").status_code, 200)
        response = self.post("/api/project-budget/notify")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["reason"], "expired")

    def test_unpaid_pro_after_grace_is_read_only(self):
        """После paid_until и 7 дней грейса: чтение открыто, запись и создание закрыты."""
        self.feature.paid_until = timezone.localdate() - timezone.timedelta(days=9)
        self.feature.save(update_fields=["paid_until"])

        for path in self.READ_PATHS:
            with self.subTest(path=path):
                self.assertEqual(self.get(path).status_code, 200)

        notify = self.post("/api/project-budget/notify")
        create = self.post("/api/finance-operations/create", {"project_item_id": "500"})
        for response in (notify, create):
            with self.subTest(path=response.wsgi_request.path):
                self.assertEqual(response.status_code, 403)
                payload = response.json()
                self.assertEqual(payload["code"], "feature_disabled")
                self.assertEqual(payload["reason"], "expired")
                self.assertEqual(payload["access"], "read_only")
                self.assertIn("просмотр и выгрузки работают", payload["error"])

        features = self.get("/api/features").json()["bdds"]
        self.assertEqual(features["access"], "read_only")
        self.assertFalse(features["enabled"])

    def test_unpaid_pro_inside_grace_still_writes(self):
        self.feature.paid_until = timezone.localdate() - timezone.timedelta(days=3)
        self.feature.save(update_fields=["paid_until"])

        self.assertEqual(self.post("/api/project-budget/notify").status_code, 200)
        self.assertEqual(self.get("/api/features").json()["bdds"]["status"], "grace")

    def test_live_trial_opens_the_screen(self):
        self.feature.state = PortalSubscription.STATE_TRIAL
        self.feature.trial_until = timezone.localdate() + timezone.timedelta(days=3)
        self.feature.save(update_fields=["state", "trial_until"])

        self.assertEqual(self.get("/api/bdds/projects").status_code, 200)

    def test_subscription_is_portal_wide_not_per_user(self):
        colleague = Bitrix24Account.objects.create(
            b24_user_id=12, is_b24_user_admin=False, member_id="m-ep-bdds",
            is_master_account=False, domain_url="ep-bdds.bitrix24.ru",
            status="active", application_version=1,
        )
        # Pro включает и ролевую модель: суммы видят роли с правом money_view
        # (main/roles.py). Коллеге даём «Руководителя проекта» — проверяется
        # по-прежнему подписка на портал, а не права конкретного человека.
        PortalRole.objects.create(member_id="m-ep-bdds", b24_user_id="12", role=PortalRole.ROLE_PROJECT_MANAGER)

        response = self.get("/api/bdds/projects", token=colleague.create_jwt_token())

        self.assertEqual(response.status_code, 200)

    def test_disabled_feature_does_not_break_neighbours(self):
        """Выключенная БДДС не ломает соседние экраны приложения."""
        self.feature.state = PortalSubscription.STATE_OFF
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


class FinanceOperationsPagingTest(BddsEndpointFixture):
    """Страницы, период, тип и итоги реестра операций.

    Предмет проверки — честность ответа. Реестр денег обязан отличать «это
    все операции» от «это первая страница», а итог по выборке от итога по
    видимым строкам: итог по странице не итог, и человек, сложивший его с
    бюджетом, получит неверный вывод, не заметив этого.
    """

    def setUp(self):
        super().setUp()
        # Порядок — как у портала при order: {id: DESC}: двойник фильтры и
        # сортировку не применяет, и «правильный» ответ на неупорядоченном
        # наборе ничего бы не доказал.
        self.portal.items = [
            self.operation("5", "expense", "1000", "2026-09-05"),
            self.operation("4", "expense", "3000", "2026-08-20"),
            self.operation("3", "Поступление", "5000", "2026-08-01"),
            self.operation("2", "расход", "2000", "2026-07-15"),
            self.operation("1", "income", "10000", "2026-07-01"),
        ]

    @staticmethod
    def operation(item_id, operation_type, amount, day):
        return {
            "id": item_id,
            "ufCrmProjectItemId": "500",
            "ufCrmOperationType": operation_type,
            "ufCrmAmount": amount,
            "ufCrmOperationDate": day,
            "ufCrmSource": "manual",
        }

    def test_first_page_reports_more_without_claiming_a_total(self):
        data = self.get("/api/finance-operations?project_item_id=500&limit=2").json()

        self.assertEqual([row["id"] for row in data["operations"]], ["5", "4"])
        self.assertTrue(data["has_more"])
        # total на коротком пути НЕ считается: мы видели окно, а не выборку.
        self.assertIsNone(data["total"])

    def test_second_page_continues_and_knows_the_total(self):
        data = self.get("/api/finance-operations?project_item_id=500&limit=2&offset=2").json()

        self.assertEqual([row["id"] for row in data["operations"]], ["3", "2"])
        self.assertEqual(data["offset"], 2)
        self.assertEqual(data["total"], 5)
        self.assertTrue(data["has_more"])

    def test_last_page_says_there_is_nothing_more(self):
        data = self.get("/api/finance-operations?project_item_id=500&limit=2&offset=4").json()

        self.assertEqual([row["id"] for row in data["operations"]], ["1"])
        self.assertFalse(data["has_more"])

    def test_type_filter_understands_portal_spellings(self):
        """«расход» и «Поступление» — те же тип, что expense и income."""
        income = self.get("/api/finance-operations?operation_type=income&totals=1").json()
        expense = self.get("/api/finance-operations?operation_type=expense&totals=1").json()

        self.assertEqual([row["id"] for row in income["operations"]], ["3", "1"])
        self.assertEqual(income["totals"]["income"], 15000.0)
        self.assertEqual([row["id"] for row in expense["operations"]], ["5", "4", "2"])
        self.assertEqual(expense["totals"]["expense"], 6000.0)

    def test_totals_are_counted_over_selection_not_over_page(self):
        data = self.get("/api/finance-operations?limit=1&totals=1").json()

        self.assertEqual(len(data["operations"]), 1)
        self.assertEqual(data["totals"], {
            "income": 15000.0,
            "expense": 6000.0,
            "net": 9000.0,
            "count": 5,
        })

    def test_period_is_filtered_by_the_portal(self):
        """Период уходит фильтром crm.item.list, а не отбирается у нас.

        Проверяем именно параметры вызова: двойник портала фильтры не
        применяет, и «правильный» ответ здесь ничего не доказал бы.
        """
        self.get("/api/finance-operations?date_from=2026-08-01&date_to=2026-08-31")

        list_calls = [params for method, params in self.portal.calls if method == "crm.item.list"]
        self.assertEqual(list_calls[-1]["filter"][">=ufCrmOperationDate"], "2026-08-01")
        self.assertEqual(list_calls[-1]["filter"]["<=ufCrmOperationDate"], "2026-08-31")

    def test_unparseable_period_is_dropped_not_guessed(self):
        """Не-ISO граница в фильтр не уходит вовсе.

        «01.08.2026» портал сравнил бы со своими датами как строку и вернул
        не ту выборку — неверный отбор в реестре денег хуже отсутствующего.
        """
        self.get("/api/finance-operations?date_from=01.08.2026")

        list_calls = [params for method, params in self.portal.calls if method == "crm.item.list"]
        self.assertNotIn(">=ufCrmOperationDate", list_calls[-1]["filter"])

    def test_garbage_paging_params_do_not_break_the_answer(self):
        data = self.get("/api/finance-operations?limit=abc&offset=-5").json()

        self.assertEqual(data["limit"], 20)
        self.assertEqual(data["offset"], 0)
        self.assertEqual(len(data["operations"]), 5)


class FinanceOperationWriteRightsTest(BddsEndpointFixture):
    """Кто заводит операции: администратор портала или «Бухгалтерия».

    Список тот же, что у выставления счёта (billing_accountants) — операция
    попадает в финансовый результат проекта так же, как счёт, а второй
    список тех же людей разошёлся бы с первым.
    """

    PAYLOAD = {
        "project_item_id": "500",
        "operation_type": "expense",
        "amount": 15000,
        "operation_date": "2026-09-01",
        "source": "manual",
    }

    def demote(self):
        self.account.is_b24_user_admin = False
        self.account.save(update_fields=["is_b24_user_admin"])

    def test_plain_employee_cannot_create_an_operation(self):
        self.demote()

        response = self.post("/api/finance-operations/create", self.PAYLOAD)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "bdds_operations_forbidden")
        self.assertEqual(self.portal.added, [])

    def test_accountant_from_settings_can_create_an_operation(self):
        self.demote()
        self.set_config(billing_accountants=["11"])

        response = self.post("/api/finance-operations/create", self.PAYLOAD)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.portal.added), 1)

    def test_project_manager_reads_but_employee_without_role_does_not(self):
        """Чтение операций — право money_view ролевой модели, которая входит в Pro.

        Прежде чтение правами закрыто не было. Теперь Pro включает роли, и
        сотрудник без роли сумм не видит, а «Руководитель проекта» — видит.
        Добавлять операции он при этом не может (tests_roles).
        """
        self.demote()
        self.assertEqual(self.get("/api/finance-operations").status_code, 403)

        PortalRole.objects.create(member_id="m-ep-bdds", b24_user_id="11", role=PortalRole.ROLE_PROJECT_MANAGER)
        self.assertEqual(self.get("/api/finance-operations").status_code, 200)

    def test_purpose_becomes_the_item_title(self):
        response = self.post("/api/finance-operations/create", {
            **self.PAYLOAD,
            "title": "Аванс подрядчику по этапу 2",
            "comment": "договор 14/26",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.portal.added[0]["fields"]["title"], "Аванс подрядчику по этапу 2")

    def test_operations_differing_only_in_purpose_are_treated_as_a_repeat(self):
        """Назначение НЕ входит в ключ идемпотентности — и это осознанно.

        Учёт заголовка в ключе перестал бы узнавать дубль в элементах,
        заведённых руками в CRM: у них заголовок свой. Цена обратная и
        безопасная — повтор, про который интерфейс обязан сказать человеку.
        """
        self.post("/api/finance-operations/create", {**self.PAYLOAD, "title": "Первый платёж"})
        self.portal.items = [{
            "id": "4242",
            "title": "Первый платёж",
            "ufCrmProjectItemId": "500",
            "ufCrmOperationType": "expense",
            "ufCrmAmount": "15000",
            "ufCrmOperationDate": "2026-09-01",
            "ufCrmSource": "manual",
        }]

        second = self.post("/api/finance-operations/create", {**self.PAYLOAD, "title": "Второй платёж"})

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
