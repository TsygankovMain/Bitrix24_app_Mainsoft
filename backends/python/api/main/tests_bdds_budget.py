"""Метрики бюджета проекта: план, факт, статусы, пороги, прогноз, поддержка.

Портал здесь двойник: суммы операций «доход/расход» приходят из смарт-процесса,
и проверять надо не то, что Битрикс умеет считать, а то, что приложение
правильно складывает свой факт по часам с его суммами.

Главное, что закрепляют эти тесты:
  - факт по часам считается по СНИМКУ ставки на списании, а не по текущей
    ставке карточки, и часы без снимка честно помечаются;
  - статус определяется порогами из настроек портала, а не константами;
  - у проектов поддержки статус — про финансовый результат, а не про
    освоение, и полосы освоения у них нет (utilization = None);
  - прогноз — линейная экстраполяция по текущему темпу, и он НИКОГДА не
    меняет статус.
"""

from datetime import date, datetime
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from .bdds_service import BddsService
from .bdds_settings import normalize_bdds_settings
from .models import Bitrix24Account, ProjectCard, TimesheetItem
from .project_budget_service import ProjectBudgetService


class FakeToken:
    """Двойник портала: пустая конфигурация и пустой смарт-процесс.

    app.option.get отвечает пустой конфигурацией, а не исключением: иначе
    каждый тест писал бы в лог «Error loading configuration», и настоящий
    сбой чтения настроек в этом шуме было бы не видно. Пустая конфигурация —
    штатное состояние портала, где БДДС ещё не настраивали.
    """

    def __init__(self, options=None):
        self.options = options or {}

    def call_method(self, method, params=None):
        if method == "app.option.get":
            return {"result": self.options}
        if method == "crm.item.list":
            return {"result": {"items": []}, "next": None}
        raise AssertionError(f"FakeToken: неожиданный метод {method}")


class FakeClient:
    def __init__(self, options=None):
        self._bitrix_token = FakeToken(options)


class BudgetFixture(TestCase):
    """Общая обвязка: учётка, двойник портала, пустые суммы операций.

    Суммы операций по умолчанию пустые — так тест про часы не зависит от
    смарт-процесса. Где нужны деньги портала, они подставляются патчем
    get_sums_by_project_item_id: разбирать здесь ещё и пагинацию
    crm.item.list смысла нет, она проверена своими тестами.
    """

    finance_sums = {}

    def setUp(self):
        cache.clear()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-bdds",
            is_master_account=True, domain_url="bdds.bitrix24.ru",
            status="active", application_version=1,
        )
        self._client_patch = patch.object(
            Bitrix24Account, "client", property(lambda _self: FakeClient()),
        )
        self._client_patch.start()
        self.addCleanup(self._client_patch.stop)

        self._sums_patch = patch(
            "main.finance_operation_service.FinanceOperationService.get_sums_by_project_item_id",
            side_effect=lambda: dict(self.finance_sums),
        )
        self._sums_patch.start()
        self.addCleanup(self._sums_patch.stop)

    def card(self, **kwargs):
        payload = {
            "bitrix24_account": self.account,
            "project_id": "73",
            "project_item_id": "500",
            "project_name": "Портал для сети автосалонов",
            "stage": "В работе",
            "hourly_rate": 2000.0,
            "budget_mode": "amount",
            "planned_budget_amount": 1000000.0,
            "project_start_date": date(2026, 4, 1),
            "project_end_date": date(2026, 12, 31),
        }
        payload.update(kwargs)
        return ProjectCard.objects.create(**payload)

    def entry(self, bitrix_id, *, hours=10.0, rate=2000.0, project_item_id="500", day=15):
        return TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=bitrix_id, task_id="8365",
            employee_id="11", hours=hours, is_billable=True,
            project_id="73", project_item_id=project_item_id,
            project_title="Портал для сети автосалонов", hourly_rate_snapshot=rate,
            date_reflection=timezone.make_aware(datetime(2026, 8, day, 0, 0)),
        )

    def metrics(self, card, *, settings=None, today=date(2026, 9, 12)):
        service = ProjectBudgetService(self.account, settings=settings, today=today)
        return service.get_card_metrics(card)


class BudgetFactTest(BudgetFixture):
    def test_fact_uses_rate_snapshot_not_current_rate(self):
        """Ставка карточки выросла — уже списанные часы не переоцениваются."""
        card = self.card(hourly_rate=5000.0)
        self.entry(1, hours=10.0, rate=2000.0)
        self.entry(2, hours=5.0, rate=3000.0)

        metrics = self.metrics(card)

        self.assertEqual(metrics["actual_hours"], 15.0)
        self.assertEqual(metrics["actual_cost_amount"], 35000.0)
        self.assertEqual(metrics["actual_hours_without_rate_snapshot"], 0.0)

    def test_hours_without_snapshot_are_counted_by_card_rate_and_flagged(self):
        """Часть записей на стенде без снимка ставки: сумма — оценка, и это видно."""
        card = self.card(hourly_rate=1500.0)
        self.entry(1, hours=10.0, rate=2000.0)
        self.entry(2, hours=4.0, rate=None)

        metrics = self.metrics(card)

        self.assertEqual(metrics["actual_cost_amount"], 20000.0 + 4.0 * 1500.0)
        self.assertEqual(metrics["actual_hours_without_rate_snapshot"], 4.0)
        self.assertEqual(metrics["fallback_hourly_rate"], 1500.0)

    def test_financial_result_mixes_operations_and_hours(self):
        card = self.card()
        self.entry(1, hours=10.0, rate=2000.0)
        self.finance_sums = {"500": {"income": 500000.0, "expense": 120000.0}}

        metrics = self.metrics(card)

        self.assertEqual(metrics["actual_income_amount"], 500000.0)
        self.assertEqual(metrics["actual_expense_amount"], 120000.0)
        self.assertEqual(metrics["actual_financial_result"], 500000.0 - 120000.0 - 20000.0)


class BudgetStatusTest(BudgetFixture):
    def test_norm_risk_overrun_by_default_thresholds(self):
        card = self.card(planned_budget_amount=100000.0)

        self.entry(1, hours=10.0, rate=2000.0)  # 20 000 = 20 %
        self.assertEqual(self.metrics(card)["budget_health_status"], "Норма")

        self.entry(2, hours=30.0, rate=2000.0)  # 80 000 -> 80 % ровно
        metrics = self.metrics(card)
        self.assertEqual(metrics["budget_utilization_percent"], 80.0)
        self.assertEqual(metrics["budget_health_status"], "Риск")

        self.entry(3, hours=11.0, rate=2000.0)  # 102 000 -> 102 %
        self.assertEqual(self.metrics(card)["budget_health_status"], "Перерасход")

    def test_exactly_hundred_percent_is_not_overrun_yet(self):
        """Ровно 100 % — ещё «Риск»: план исчерпан, но не пробит."""
        card = self.card(planned_budget_amount=100000.0)
        self.entry(1, hours=50.0, rate=2000.0)

        metrics = self.metrics(card)

        self.assertEqual(metrics["budget_utilization_percent"], 100.0)
        self.assertEqual(metrics["budget_health_status"], "Риск")

    def test_thresholds_come_from_settings(self):
        card = self.card(planned_budget_amount=100000.0)
        self.entry(1, hours=30.0, rate=2000.0)  # 60 %
        settings = {
            "bdds_risk_threshold_percent": 50,
            "bdds_overrun_threshold_percent": 55,
        }

        metrics = self.metrics(card, settings=settings)

        self.assertEqual(metrics["budget_health_status"], "Перерасход")
        self.assertEqual(metrics["risk_threshold_ratio"], 0.5)
        self.assertEqual(metrics["overrun_threshold_ratio"], 0.55)

    def test_swapped_thresholds_are_fixed_not_trusted(self):
        """Риск выше перерасхода — поля перепутаны местами, а не «зона риска отменена»."""
        normalized = normalize_bdds_settings({
            "bdds_risk_threshold_percent": 120,
            "bdds_overrun_threshold_percent": 100,
        })

        self.assertEqual(normalized["risk_threshold_percent"], 100.0)
        self.assertEqual(normalized["overrun_threshold_percent"], 120.0)

    def test_garbage_thresholds_fall_back_to_defaults(self):
        normalized = normalize_bdds_settings({
            "bdds_risk_threshold_percent": "восемьдесят",
            "bdds_overrun_threshold_percent": 0,
        })

        self.assertEqual(normalized["risk_threshold_percent"], 80.0)
        self.assertEqual(normalized["overrun_threshold_percent"], 100.0)

    def test_project_without_budget_has_no_status_and_no_bar(self):
        card = self.card(planned_budget_amount=None, project_hours_budget=None)
        self.entry(1, hours=10.0, rate=2000.0)

        metrics = self.metrics(card)

        self.assertEqual(metrics["budget_health_status"], "Без лимита")
        self.assertIsNone(metrics["budget_utilization_percent"])
        self.assertIsNone(metrics["budget_remaining"])
        self.assertFalse(metrics["has_budget"])

    def test_support_project_is_judged_by_financial_result(self):
        card = self.card(
            project_id="74", project_item_id="501", is_support=True,
            planned_budget_amount=None, project_hours_budget=None,
        )
        self.entry(1, hours=10.0, rate=2000.0, project_item_id="501")
        self.finance_sums = {"501": {"income": 10000.0, "expense": 0.0}}

        metrics = self.metrics(card)

        self.assertEqual(metrics["budget_utilization_mode"], "support")
        self.assertIsNone(metrics["budget_utilization_percent"])
        self.assertFalse(metrics["has_budget"])
        self.assertTrue(metrics["is_support"])
        # 10 000 − 20 000 = −10 000: минус есть, но он меньше порога 100 000.
        self.assertEqual(metrics["budget_health_status"], "Граница")
        self.assertEqual(metrics["support_health_status"], "Граница")

    def test_support_boundary_amount_is_configurable(self):
        card = self.card(
            project_id="74", project_item_id="501", is_support=True,
            planned_budget_amount=None, project_hours_budget=None,
        )
        self.entry(1, hours=10.0, rate=2000.0, project_item_id="501")

        metrics = self.metrics(card, settings={"bdds_support_boundary_amount": 5000})

        self.assertEqual(metrics["budget_health_status"], "Минус")


class BudgetForecastTest(BudgetFixture):
    def test_forecast_extrapolates_current_pace(self):
        """Апрель—декабрь, сегодня 12.09: 6 начавшихся месяцев, 3 полных впереди."""
        card = self.card(planned_budget_amount=1000000.0)
        self.entry(1, hours=300.0, rate=2000.0)  # 600 000 ₽

        metrics = self.metrics(card, today=date(2026, 9, 12))

        self.assertEqual(metrics["forecast_months_elapsed"], 6)
        self.assertEqual(metrics["forecast_months_left"], 3)
        self.assertEqual(metrics["forecast_monthly_rate"], 100000.0)
        self.assertEqual(metrics["forecast_cost_amount"], 900000.0)
        self.assertEqual(metrics["forecast_overrun_amount"], -100000.0)

    def test_forecast_shows_overrun_while_status_is_still_norm(self):
        """Та самая строка, ради которой отчёт открывают."""
        card = self.card(planned_budget_amount=1000000.0)
        self.entry(1, hours=350.0, rate=2000.0)  # 700 000 = 70 %

        metrics = self.metrics(card, today=date(2026, 9, 12))

        self.assertEqual(metrics["budget_health_status"], "Норма")
        self.assertEqual(metrics["forecast_cost_amount"], 1050000.0)
        self.assertEqual(metrics["forecast_overrun_amount"], 50000.0)

    def test_forecast_needs_both_dates(self):
        no_end = self.card(project_end_date=None)
        self.entry(1, hours=10.0, rate=2000.0)
        self.assertIsNone(self.metrics(no_end)["forecast_cost_amount"])
        self.assertIn("дата окончания", self.metrics(no_end)["forecast_reason"])

        no_start = self.card(
            project_id="75", project_item_id="502", project_start_date=None,
        )
        self.assertIsNone(self.metrics(no_start)["forecast_cost_amount"])
        self.assertIn("дата начала", self.metrics(no_start)["forecast_reason"])

    def test_overdue_project_forecast_equals_fact(self):
        """Срок вышел — планового будущего нет, прогноз равен факту."""
        card = self.card(project_end_date=date(2026, 6, 30))
        self.entry(1, hours=100.0, rate=2000.0)

        metrics = self.metrics(card, today=date(2026, 9, 12))

        self.assertEqual(metrics["forecast_months_left"], 0)
        self.assertEqual(metrics["forecast_cost_amount"], 200000.0)

    def test_first_month_pace_does_not_divide_by_zero(self):
        card = self.card(
            project_start_date=date(2026, 9, 1), project_end_date=date(2026, 11, 30),
        )
        self.entry(1, hours=50.0, rate=2000.0)

        metrics = self.metrics(card, today=date(2026, 9, 12))

        self.assertEqual(metrics["forecast_months_elapsed"], 1)
        self.assertEqual(metrics["forecast_monthly_rate"], 100000.0)
        self.assertEqual(metrics["forecast_cost_amount"], 300000.0)

    def test_support_project_has_no_forecast(self):
        card = self.card(is_support=True, planned_budget_amount=None)
        self.entry(1, hours=10.0, rate=2000.0)

        metrics = self.metrics(card)

        self.assertIsNone(metrics["forecast_cost_amount"])
        self.assertIn("поддержки", metrics["forecast_reason"])

    def test_months_helpers_are_pure_and_clamped(self):
        self.assertEqual(ProjectBudgetService.months_elapsed(date(2026, 9, 1), date(2026, 9, 1)), 1)
        self.assertEqual(ProjectBudgetService.months_elapsed(date(2026, 12, 1), date(2026, 9, 1)), 1)
        self.assertEqual(ProjectBudgetService.months_elapsed(date(2025, 9, 30), date(2026, 9, 1)), 13)
        self.assertEqual(ProjectBudgetService.months_left(date(2026, 9, 30), date(2026, 12, 1)), 3)
        self.assertEqual(ProjectBudgetService.months_left(date(2026, 9, 1), date(2026, 8, 1)), 0)


class BddsRegistryTest(BudgetFixture):
    def test_registry_totals_exclude_budgetless_projects_from_plan(self):
        self.card(planned_budget_amount=100000.0)
        self.entry(1, hours=25.0, rate=2000.0)  # 50 000 -> 50 %

        self.card(
            project_id="74", project_item_id="501", project_name="Поддержка",
            is_support=True, planned_budget_amount=None, project_hours_budget=None,
        )
        self.entry(2, hours=10.0, rate=2000.0, project_item_id="501")

        payload = BddsService(
            self.account, settings={}, today=date(2026, 9, 12)
        ).list_projects()

        self.assertEqual(len(payload["projects"]), 2)
        totals = payload["totals"]
        self.assertEqual(totals["planned_amount"], 100000.0)
        self.assertEqual(totals["with_budget_count"], 1)
        self.assertEqual(totals["without_budget_count"], 1)
        # Факт — по всем проектам, освоение — только по тем, где есть план.
        self.assertEqual(totals["actual_cost_amount"], 70000.0)
        self.assertEqual(totals["actual_cost_amount_with_budget"], 50000.0)
        self.assertEqual(totals["budget_utilization_percent"], 50.0)

        # У поддержки в реестре нет ни плана, ни полосы освоения — только
        # финансовый результат. Полоса «0 %» читалась бы как «ничего не
        # освоено», а это неправда.
        support_row = next(row for row in payload["projects"] if row["project_id"] == "74")
        self.assertFalse(support_row["has_budget"])
        self.assertIsNone(support_row["budget_utilization_percent"])
        self.assertEqual(support_row["actual_financial_result"], -20000.0)

    def test_registry_sorts_burning_projects_first(self):
        self.card(project_id="80", project_item_id="600", project_name="Норма",
                  planned_budget_amount=1000000.0)
        self.entry(1, hours=10.0, rate=2000.0, project_item_id="600")

        self.card(project_id="81", project_item_id="601", project_name="Перерасход",
                  planned_budget_amount=10000.0)
        self.entry(2, hours=10.0, rate=2000.0, project_item_id="601")

        self.card(project_id="82", project_item_id="602", project_name="Риск",
                  planned_budget_amount=25000.0)
        self.entry(3, hours=10.0, rate=2000.0, project_item_id="602")

        payload = BddsService(self.account, settings={}, today=date(2026, 9, 12)).list_projects()
        names = [row["project_name"] for row in payload["projects"]]

        self.assertEqual(names, ["Перерасход", "Риск", "Норма"])
        self.assertEqual(payload["status_counts"]["attention"], 2)

    def test_archived_projects_are_hidden_by_default(self):
        self.card(project_id="90", project_item_id="700", is_archived=True)

        default_payload = BddsService(self.account, settings={}).list_projects()
        with_archive = BddsService(self.account, settings={}).list_projects(include_archived=True)

        self.assertEqual(default_payload["projects"], [])
        self.assertEqual(len(with_archive["projects"]), 1)

    def test_project_card_returns_none_for_unknown_id(self):
        self.assertIsNone(BddsService(self.account, settings={}).get_project("нет-такого"))
