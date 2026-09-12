from __future__ import annotations

from datetime import date
from typing import Any, Dict, Iterable, Optional, Tuple

from .bdds_settings import (
    DEFAULT_OVERRUN_THRESHOLD_PERCENT,
    DEFAULT_RISK_THRESHOLD_PERCENT,
    DEFAULT_SUPPORT_BOUNDARY_AMOUNT,
    normalize_bdds_settings,
)
from .finance_operation_service import FinanceOperationService
from .models import Bitrix24Account, ProjectCard, TimesheetItem
from .tenant_scoping import scope_to_tenant


class ProjectBudgetService:
    """Метрики бюджета проекта: план, факт, остаток, освоение, статус, прогноз.

    Факт собирается из ДВУХ источников и это принципиально:
      - затраты по часам — сумма списаний, каждое по своей ставке на момент
        списания (``TimesheetItem.hourly_rate_snapshot``), а не по текущей
        ставке карточки: внутри периода ставка могла меняться, и пересчёт от
        общих часов разошёлся бы с детализацией счёта
        (``BillingLine`` считает так же);
      - поступления и внешние платежи — суммы операций смарт-процесса
        «Доходы-расходы (App)» (``FinanceOperationService``).

    Пороги статуса приходят настройкой портала (``bdds_settings``), а
    константы класса остались значениями по умолчанию — на случай вызова без
    настроек (так зовёт, например, код, которому нужны только часы).
    """

    RISK_THRESHOLD_RATIO = DEFAULT_RISK_THRESHOLD_PERCENT / 100.0
    OVERRUN_THRESHOLD_RATIO = DEFAULT_OVERRUN_THRESHOLD_PERCENT / 100.0
    SUPPORT_BOUNDARY_THRESHOLD = DEFAULT_SUPPORT_BOUNDARY_AMOUNT

    def __init__(
        self,
        account: Bitrix24Account,
        *,
        settings: Optional[Dict[str, Any]] = None,
        today: Optional[date] = None,
    ):
        self.account = account
        normalized = normalize_bdds_settings(settings) if isinstance(settings, dict) else None
        if normalized is None:
            self.risk_threshold_ratio = self.RISK_THRESHOLD_RATIO
            self.overrun_threshold_ratio = self.OVERRUN_THRESHOLD_RATIO
            self.support_boundary_threshold = self.SUPPORT_BOUNDARY_THRESHOLD
        else:
            self.risk_threshold_ratio = normalized["risk_threshold_percent"] / 100.0
            self.overrun_threshold_ratio = normalized["overrun_threshold_percent"] / 100.0
            self.support_boundary_threshold = normalized["support_boundary_amount"]
        self.today = today or date.today()

    def build_metrics_map(self, cards: Iterable[ProjectCard]) -> Dict[str, Dict[str, Any]]:
        cards_list = list(cards or [])
        if not cards_list:
            return {}

        aggregates_by_item, aggregates_by_group, aggregates_by_title = self._collect_timesheet_aggregates()
        finance_sums: Dict[str, Dict[str, float]] = {}
        try:
            finance_sums = FinanceOperationService(self.account.client, self.account).get_sums_by_project_item_id()
        except Exception:
            finance_sums = {}
        metrics: Dict[str, Dict[str, Any]] = {}
        for card in cards_list:
            metrics[card.project_id] = self._build_card_metrics(
                card,
                aggregates_by_item,
                aggregates_by_group,
                aggregates_by_title,
                finance_sums=finance_sums,
            )
        return metrics

    def get_card_metrics(self, card: ProjectCard) -> Dict[str, Any]:
        return self.build_metrics_map([card]).get(card.project_id, self._empty_metrics(card))

    def _collect_timesheet_aggregates(
        self,
    ) -> Tuple[Dict[str, Dict[str, float]], Dict[str, Dict[str, float]], Dict[str, Dict[str, float]]]:
        by_item: Dict[str, Dict[str, float]] = {}
        by_group: Dict[str, Dict[str, float]] = {}
        by_title: Dict[str, Dict[str, float]] = {}

        rows = (
            TimesheetItem.objects.filter(**scope_to_tenant(self.account))
            .values(
                "project_item_id",
                "project_id",
                "project_title",
                "hours",
                "hourly_rate_snapshot",
            )
        )

        for row in rows:
            hours = self._to_float(row.get("hours"))
            if hours <= 0:
                continue

            snapshot = self._to_optional_float(row.get("hourly_rate_snapshot"))
            project_item_id = self._clean_str(row.get("project_item_id"))
            project_id = self._clean_str(row.get("project_id"))
            project_title = self._clean_str(row.get("project_title"))

            if project_item_id:
                self._append_aggregate(by_item, project_item_id, hours, snapshot)
                continue
            if project_id:
                self._append_aggregate(by_group, project_id, hours, snapshot)
                continue
            if project_title:
                self._append_aggregate(by_title, project_title, hours, snapshot)

        return by_item, by_group, by_title

    def _append_aggregate(
        self,
        target: Dict[str, Dict[str, float]],
        key: str,
        hours: float,
        snapshot_rate: Optional[float],
    ) -> None:
        bucket = target.setdefault(
            key,
            {
                "hours": 0.0,
                "snapshot_cost": 0.0,
                "hours_without_snapshot": 0.0,
            },
        )
        bucket["hours"] = self._round_hours(bucket["hours"] + hours)
        if snapshot_rate is None:
            bucket["hours_without_snapshot"] = self._round_hours(bucket["hours_without_snapshot"] + hours)
            return
        bucket["snapshot_cost"] = self._round_amount(bucket["snapshot_cost"] + (hours * snapshot_rate))

    def _build_card_metrics(
        self,
        card: ProjectCard,
        aggregates_by_item: Dict[str, Dict[str, float]],
        aggregates_by_group: Dict[str, Dict[str, float]],
        aggregates_by_title: Dict[str, Dict[str, float]],
        finance_sums: Dict[str, Dict[str, float]],
    ) -> Dict[str, Any]:
        actual_hours = self._resolve_actual_hours(card, aggregates_by_item, aggregates_by_group, aggregates_by_title)
        hourly_rate = self._to_float(card.hourly_rate)
        planned_hours = self._to_optional_float(card.project_hours_budget)
        planned_amount = self._to_optional_float(card.planned_budget_amount)
        actual_cost_amount = self._resolve_actual_cost(
            card,
            aggregates_by_item,
            aggregates_by_group,
            aggregates_by_title,
            default_hourly_rate=hourly_rate,
        )
        hours_without_rate_snapshot = self._resolve_hours_without_snapshot(
            card,
            aggregates_by_item,
            aggregates_by_group,
            aggregates_by_title,
        )

        project_item_id = self._clean_str(card.project_item_id)
        finance_bucket = finance_sums.get(project_item_id or "", {}) if project_item_id else {}
        actual_income_amount = self._round_amount(finance_bucket.get("income", 0.0))
        actual_expense_amount = self._round_amount(finance_bucket.get("expense", 0.0))
        actual_financial_result = self._round_amount(actual_income_amount - actual_expense_amount - actual_cost_amount)

        is_support = self._is_support_project(card)
        support_health_status: Optional[str] = None
        support_health_reason: Optional[str] = None
        forecast: Dict[str, Any] = self._empty_forecast(
            "Прогноз у проектов поддержки не считается: у них нет плана, контролируется финансовый результат."
            if is_support
            else "Прогноз не посчитан."
        )
        if is_support:
            hours_remaining = None
            budget_remaining = None
            utilization_mode = "support"
            utilization_ratio = None
            support_health_status, support_health_reason = self._resolve_support_status(actual_financial_result)
            budget_health_status = support_health_status
            budget_health_reason = support_health_reason
        else:
            hours_remaining = (
                self._round_hours(planned_hours - actual_hours) if planned_hours is not None else None
            )
            budget_remaining = (
                self._round_amount(planned_amount - actual_cost_amount) if planned_amount is not None else None
            )

            utilization_mode, utilization_ratio = self._resolve_utilization(
                card,
                planned_hours=planned_hours,
                planned_amount=planned_amount,
                actual_hours=actual_hours,
                actual_cost_amount=actual_cost_amount,
            )

            budget_health_status = self._resolve_status(utilization_ratio)
            budget_health_reason = self._build_status_reason(utilization_mode, utilization_ratio)
            forecast = self._resolve_forecast(
                card,
                actual_cost_amount=actual_cost_amount,
                planned_amount=planned_amount,
            )

        return {
            "planned_hours": planned_hours,
            "planned_amount": planned_amount,
            "actual_hours": actual_hours,
            "actual_cost_amount": actual_cost_amount,
            "actual_income_amount": actual_income_amount,
            "actual_expense_amount": actual_expense_amount,
            "actual_financial_result": actual_financial_result,
            "hours_remaining": hours_remaining,
            "budget_remaining": budget_remaining,
            "budget_utilization_mode": utilization_mode,
            "budget_utilization_ratio": utilization_ratio,
            "budget_utilization_percent": self._ratio_to_percent(utilization_ratio),
            "budget_health_status": budget_health_status,
            "budget_health_reason": budget_health_reason,
            "support_health_status": support_health_status,
            "support_health_reason": support_health_reason,
            "risk_threshold_ratio": self.risk_threshold_ratio,
            "overrun_threshold_ratio": self.overrun_threshold_ratio,
            # Проект «без бюджета» — это НЕ ошибка данных: поддержка живёт
            # финансовым результатом, а не освоением, и полосу освоения ей
            # рисовать нельзя (так же сделано на доске проектов). Флаг отдаём
            # явно, чтобы интерфейс не выводил его из нулей и пустот.
            "has_budget": (not is_support) and (planned_hours is not None or planned_amount is not None),
            "is_support": is_support,
            # Часы, у которых на списании нет снимка ставки: их стоимость
            # посчитана по ТЕКУЩЕЙ ставке карточки. На стенде такие записи
            # есть, и сумма факта по ним — оценка, а не факт; интерфейс
            # обязан это подписать, а не молчать.
            "actual_hours_without_rate_snapshot": hours_without_rate_snapshot,
            "fallback_hourly_rate": hourly_rate,
            **forecast,
        }

    def _resolve_actual_hours(
        self,
        card: ProjectCard,
        aggregates_by_item: Dict[str, Dict[str, float]],
        aggregates_by_group: Dict[str, Dict[str, float]],
        aggregates_by_title: Dict[str, Dict[str, float]],
    ) -> float:
        actual_hours = 0.0
        project_item_id = self._clean_str(card.project_item_id)
        project_id = self._clean_str(card.project_id)
        project_name = self._clean_str(card.project_name)

        if project_item_id:
            actual_hours += self._to_float(aggregates_by_item.get(project_item_id, {}).get("hours"))
        if project_id:
            actual_hours += self._to_float(aggregates_by_group.get(project_id, {}).get("hours"))
        if project_name:
            actual_hours += self._to_float(aggregates_by_title.get(project_name, {}).get("hours"))

        return self._round_hours(actual_hours)

    def _resolve_hours_without_snapshot(
        self,
        card: ProjectCard,
        aggregates_by_item: Dict[str, Dict[str, float]],
        aggregates_by_group: Dict[str, Dict[str, float]],
        aggregates_by_title: Dict[str, Dict[str, float]],
    ) -> float:
        total = 0.0
        project_item_id = self._clean_str(card.project_item_id)
        project_id = self._clean_str(card.project_id)
        project_name = self._clean_str(card.project_name)

        if project_item_id:
            total += self._to_float(aggregates_by_item.get(project_item_id, {}).get("hours_without_snapshot"))
        if project_id:
            total += self._to_float(aggregates_by_group.get(project_id, {}).get("hours_without_snapshot"))
        if project_name:
            total += self._to_float(aggregates_by_title.get(project_name, {}).get("hours_without_snapshot"))

        return self._round_hours(total)

    def _resolve_actual_cost(
        self,
        card: ProjectCard,
        aggregates_by_item: Dict[str, Dict[str, float]],
        aggregates_by_group: Dict[str, Dict[str, float]],
        aggregates_by_title: Dict[str, Dict[str, float]],
        *,
        default_hourly_rate: float,
    ) -> float:
        total_cost = 0.0
        project_item_id = self._clean_str(card.project_item_id)
        project_id = self._clean_str(card.project_id)
        project_name = self._clean_str(card.project_name)

        if project_item_id:
            total_cost += self._resolve_cost_from_bucket(
                aggregates_by_item.get(project_item_id, {}),
                default_hourly_rate=default_hourly_rate,
            )
        if project_id:
            total_cost += self._resolve_cost_from_bucket(
                aggregates_by_group.get(project_id, {}),
                default_hourly_rate=default_hourly_rate,
            )
        if project_name:
            total_cost += self._resolve_cost_from_bucket(
                aggregates_by_title.get(project_name, {}),
                default_hourly_rate=default_hourly_rate,
            )

        return self._round_amount(total_cost)

    def _resolve_cost_from_bucket(self, bucket: Dict[str, float], *, default_hourly_rate: float) -> float:
        snapshot_cost = self._to_float(bucket.get("snapshot_cost"))
        hours_without_snapshot = self._to_float(bucket.get("hours_without_snapshot"))
        return self._round_amount(snapshot_cost + (hours_without_snapshot * default_hourly_rate))

    def _resolve_utilization(
        self,
        card: ProjectCard,
        *,
        planned_hours: Optional[float],
        planned_amount: Optional[float],
        actual_hours: float,
        actual_cost_amount: float,
    ) -> Tuple[str, Optional[float]]:
        mode = self._clean_str(card.budget_mode) or "hours_and_amount"
        normalized_mode = mode.lower()
        ratios: Dict[str, float] = {}

        if normalized_mode in {"hours", "hours_and_amount"} and planned_hours and planned_hours > 0:
            ratios["hours"] = actual_hours / planned_hours
        if normalized_mode in {"amount", "hours_and_amount"} and planned_amount and planned_amount > 0:
            ratios["amount"] = actual_cost_amount / planned_amount

        if not ratios:
            if planned_hours and planned_hours > 0:
                ratios["hours"] = actual_hours / planned_hours
            if planned_amount and planned_amount > 0:
                ratios["amount"] = actual_cost_amount / planned_amount

        if not ratios:
            return "none", None

        selected_mode = max(ratios, key=ratios.get)
        return selected_mode, ratios[selected_mode]

    # --- Прогноз ---------------------------------------------------------
    #
    # Формула — вариант A из записки к макету (вопрос 3), то есть ЛИНЕЙНАЯ
    # ЭКСТРАПОЛЯЦИЯ ПО ТЕКУЩЕМУ ТЕМПУ:
    #
    #     темп        = факт затрат / число начавшихся месяцев проекта
    #     прогноз     = факт затрат + темп × число полных месяцев до конца
    #
    # Почему именно она на первом этапе. Варианты B (темп за последние три
    # месяца) и C (остаток плана по месяцам) требуют разреза по месяцам,
    # которого на первом этапе нет вовсе: план — одно число на проект.
    # Вариант A считается из того, что уже есть, и объясним одной фразой —
    # а объяснимость здесь важнее точности: цифра «прогноз» нужна, чтобы
    # ЗАРАНЕЕ увидеть проект, который «в норме» сегодня и выйдет за план
    # через два месяца, и человек обязан понимать, откуда она.
    #
    # Слабое место названо честно и в интерфейсе, и здесь: на проектах с
    # неровной загрузкой (разработка в начале, приёмка в конце) средний темп
    # врёт. Поэтому прогноз никогда не меняет СТАТУС проекта — статус
    # считается только по факту, — и подписан как оценка.

    def _resolve_forecast(
        self,
        card: ProjectCard,
        *,
        actual_cost_amount: float,
        planned_amount: Optional[float],
    ) -> Dict[str, Any]:
        start_date = card.project_start_date
        end_date = card.project_end_date

        if start_date is None:
            return self._empty_forecast("Прогноз не посчитан: в карточке проекта не задана дата начала.")
        if end_date is None:
            return self._empty_forecast("Прогноз не посчитан: в карточке проекта не задана дата окончания.")
        if end_date < start_date:
            return self._empty_forecast("Прогноз не посчитан: дата окончания проекта раньше даты начала.")

        months_elapsed = self.months_elapsed(start_date, self.today)
        months_left = self.months_left(self.today, end_date)
        # Округляем ТОЛЬКО для показа, а считаем от неокруглённого темпа:
        # 700 000 / 6 × 3 при округлении темпа до копеек даёт 350 000,01 —
        # лишняя копейка в прогнозе выглядит как ошибка расчёта.
        raw_monthly_rate = actual_cost_amount / months_elapsed
        monthly_rate = self._round_amount(raw_monthly_rate)
        forecast_amount = self._round_amount(actual_cost_amount + (raw_monthly_rate * months_left))

        overrun = None
        if planned_amount is not None:
            overrun = self._round_amount(forecast_amount - planned_amount)

        return {
            "forecast_cost_amount": forecast_amount,
            "forecast_overrun_amount": overrun,
            "forecast_monthly_rate": monthly_rate,
            "forecast_months_elapsed": months_elapsed,
            "forecast_months_left": months_left,
            "forecast_method": "linear_pace",
            "forecast_reason": (
                f"Факт {actual_cost_amount:.2f} ₽ за {months_elapsed} мес. "
                f"плюс текущий темп {monthly_rate:.2f} ₽/мес. × {months_left} мес. до конца проекта."
            ),
        }

    @staticmethod
    def _empty_forecast(reason: str) -> Dict[str, Any]:
        return {
            "forecast_cost_amount": None,
            "forecast_overrun_amount": None,
            "forecast_monthly_rate": None,
            "forecast_months_elapsed": None,
            "forecast_months_left": None,
            "forecast_method": "linear_pace",
            "forecast_reason": reason,
        }

    @staticmethod
    def months_elapsed(start_date: date, today: date) -> int:
        """Сколько месяцев проекта УЖЕ НАЧАЛОСЬ, включая текущий. Минимум 1.

        Считаем начавшиеся, а не завершённые: в первый месяц проекта
        завершённых нет ни одного, и делить факт было бы не на что, а темп
        «весь факт за нулевой срок» — бесконечность. Минимум 1 закрывает и
        проект, который по датам ещё не начался (так бывает: даты в карточке
        заводят заранее, а часы уже списывают).
        """
        months = (today.year - start_date.year) * 12 + (today.month - start_date.month) + 1
        return max(1, months)

    @staticmethod
    def months_left(today: date, end_date: date) -> int:
        """Сколько ПОЛНЫХ месяцев осталось до конца проекта. Не меньше нуля.

        Текущий месяц не считается: его часть уже в факте, и добавить к
        факту ещё целый месячный темп значило бы посчитать её дважды.
        Просроченный проект даёт 0 — прогноз для него равен факту, и это
        честно: планового будущего у него больше нет.
        """
        months = (end_date.year - today.year) * 12 + (end_date.month - today.month)
        return max(0, months)

    def _resolve_status(self, utilization_ratio: Optional[float]) -> str:
        if utilization_ratio is None:
            return "Без лимита"
        if utilization_ratio > self.overrun_threshold_ratio:
            return "Перерасход"
        if utilization_ratio >= self.risk_threshold_ratio:
            return "Риск"
        return "Норма"

    def _build_status_reason(self, mode: str, utilization_ratio: Optional[float]) -> Optional[str]:
        if utilization_ratio is None:
            return "Не задан плановый лимит."
        ratio_percent = round(utilization_ratio * 100.0, 1)
        risk_percent = round(self.risk_threshold_ratio * 100.0, 1)
        overrun_percent = round(self.overrun_threshold_ratio * 100.0, 1)
        thresholds = f" Порог риска {risk_percent}%, перерасхода {overrun_percent}%."
        if mode == "hours":
            return f"Освоение часов: {ratio_percent}%.{thresholds}"
        if mode == "amount":
            return f"Освоение бюджета: {ratio_percent}%.{thresholds}"
        return f"Освоение лимита: {ratio_percent}%.{thresholds}"

    def _resolve_support_status(self, actual_financial_result: float) -> Tuple[str, str]:
        if actual_financial_result >= 0:
            return "Плюс", "Поддержка в положительной или нулевой маржинальности."

        if abs(actual_financial_result) < self.support_boundary_threshold:
            return "Граница", (
                "Поддержка в пограничной зоне: финансовый результат отрицательный, "
                "но в допустимом пороге."
            )

        return "Минус", "Поддержка уходит в выраженный минус, требуется управленческая реакция."

    @staticmethod
    def _is_support_project(card: ProjectCard) -> bool:
        if bool(card.is_support):
            return True
        project_type = str(card.project_type or "").strip().lower()
        budget_mode = str(card.budget_mode or "").strip().lower()
        return project_type == "support" or budget_mode == "support"

    def _empty_metrics(self, card: ProjectCard) -> Dict[str, Any]:
        return self._build_card_metrics(card, {}, {}, {}, finance_sums={})

    @staticmethod
    def _clean_str(value: Any) -> Optional[str]:
        if value is None:
            return None
        value_str = str(value).strip()
        return value_str or None

    @staticmethod
    def _to_optional_float(value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _round_hours(value: Any) -> float:
        return round(ProjectBudgetService._to_float(value), 2)

    @staticmethod
    def _round_amount(value: Any) -> float:
        return round(ProjectBudgetService._to_float(value), 2)

    @staticmethod
    def _ratio_to_percent(value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        return round(float(value) * 100.0, 1)
