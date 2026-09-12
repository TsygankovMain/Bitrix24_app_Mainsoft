"""Портфель и карточка для функции «БДДС по проектам» (этап 1).

Что здесь считается и чего здесь НЕТ.

Есть: план, факт, остаток, освоение, статус и прогноз по каждому проекту
плюс итог по портфелю. План — ОДНО ЧИСЛО на проект (``ProjectCard.
planned_budget_amount`` и ``project_hours_budget``), как он и заведён
сегодня.

Нет: статей ДДС, плана по месяцам, колонки «в ожидании» и корректировок.
Это этапы 2 и 3, и они ждут ответов пользователя (записка к макету,
вопросы 1, 2, 5, 7, 8). Заводить под них пустые колонки сейчас нельзя:
пустая колонка «в ожидании» читается как «денег в пути нет», а это не то
же самое, что «мы этого ещё не считаем».

Третьего списка проектов не появляется. Строка портфеля — это ТА ЖЕ
карточка проекта (``ProjectCard``) с теми же полями, что отдаёт доска
(``project_board_service``), плюс метрики бюджета из
``ProjectBudgetService``. Поэтому интерфейс реестра переиспользует утилиты
доски (фильтр, поиск, полоса освоения), а не пишет свои.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, Iterable, List, Optional

from .bdds_settings import load_bdds_settings, normalize_bdds_settings
from .finance_operation_service import FinanceOperationService
from .models import Bitrix24Account, ProjectCard
from .project_board_shared import get_project_card_queryset
from .project_budget_service import ProjectBudgetService

logger = logging.getLogger(__name__)

#: Статусы, в которых проект требует управленческой реакции.
ATTENTION_STATUSES = ("Риск", "Перерасход", "Минус")


class BddsService:
    def __init__(
        self,
        account: Bitrix24Account,
        *,
        settings: Optional[Dict[str, Any]] = None,
        today: Optional[date] = None,
    ):
        self.account = account
        self.settings = (
            normalize_bdds_settings(settings)
            if isinstance(settings, dict)
            else load_bdds_settings(account)
        )
        self.today = today or date.today()
        self._budget_service = ProjectBudgetService(
            account, settings=self.settings, today=self.today
        )

    # --- Портфель --------------------------------------------------------

    def list_projects(self, *, include_archived: bool = False) -> Dict[str, Any]:
        cards = list(self._card_queryset(include_archived=include_archived))
        metrics_map = self._budget_service.build_metrics_map(cards)
        rows = [self._serialize(card, metrics_map.get(card.project_id, {})) for card in cards]
        rows.sort(key=self._registry_sort_key)

        return {
            "projects": rows,
            "totals": self.build_totals(rows),
            "status_counts": self.build_status_counts(rows),
            "thresholds": self.thresholds_payload(),
        }

    def get_project(self, project_id: str, *, operations_limit: int = 10) -> Optional[Dict[str, Any]]:
        normalized = str(project_id or "").strip()
        if not normalized:
            return None

        card = (
            self._card_queryset(include_archived=True)
            .filter(project_id=normalized)
            .first()
        )
        if card is None:
            return None

        metrics = self._budget_service.get_card_metrics(card)
        row = self._serialize(card, metrics)
        row["recent_finance_operations"] = self._recent_operations(card, limit=operations_limit)
        return {
            "project": row,
            "thresholds": self.thresholds_payload(),
        }

    # --- Сборка ----------------------------------------------------------

    def _card_queryset(self, *, include_archived: bool):
        queryset = get_project_card_queryset(self.account)
        if not include_archived:
            queryset = queryset.filter(is_archived=False)
        return queryset

    def _serialize(self, card: ProjectCard, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Карточка проекта + метрики одним плоским объектом.

        Плоско, а не вложенным ``budget``: ровно такую форму уже ждёт
        описанный контракт доски (``ProjectBoardCardRecord`` во фронте), и
        его утилиты (полоса освоения, фильтры, поиск) читают поля с верхнего
        уровня. Вкладывать те же значения означало бы либо второй контракт,
        либо копию утилит.
        """
        payload: Dict[str, Any] = {
            "project_id": card.project_id,
            "project_item_id": card.project_item_id,
            "project_name": card.project_name,
            "stage": card.stage,
            "is_archived": bool(card.is_archived),
            "is_support": bool(card.is_support),
            "project_type": card.project_type,
            "budget_mode": card.budget_mode,
            "hourly_rate": card.hourly_rate,
            "project_hours_budget": card.project_hours_budget,
            "planned_budget_amount": card.planned_budget_amount,
            "curator_user_id": card.curator_user_id,
            "curator_name": card.curator_name,
            "company_id": card.company_id,
            "company_name": card.company_name,
            "our_legal_entity_id": card.our_legal_entity_id,
            "our_legal_entity_name": card.our_legal_entity_name,
            "project_start_date": card.project_start_date.isoformat() if card.project_start_date else None,
            "project_end_date": card.project_end_date.isoformat() if card.project_end_date else None,
            "last_writeoff_at": card.last_writeoff_at.isoformat() if card.last_writeoff_at else None,
            "last_writeoff_days": card.last_writeoff_days,
        }
        payload.update(metrics or {})
        return payload

    def _recent_operations(self, card: ProjectCard, *, limit: int) -> List[Dict[str, Any]]:
        """Последние операции смарт-процесса по проекту.

        Сбой чтения портала НЕ роняет экран: план, факт и остаток считаются
        из нашей БД и списаний, и показывать вместо них ошибку смарт-процесса
        было бы неверно по существу. Пустой список — «операций не видно»,
        и это подписано в интерфейсе.
        """
        project_item_id = str(card.project_item_id or "").strip()
        if not project_item_id:
            return []
        try:
            service = FinanceOperationService(self.account.client, self.account)
            return service.get_recent_operations_by_project_item_id(project_item_id, limit=limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "BddsService: не удалось прочитать операции проекта %s: %s", card.project_id, exc
            )
            return []

    # --- Итоги -----------------------------------------------------------

    @staticmethod
    def build_totals(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        """Итог по портфелю.

        В итог ПЛАНА входят только проекты с заданным лимитом. Поддержка без
        лимита в план не попадает (у неё контролируется финансовый результат,
        а не освоение) — иначе освоение портфеля считалось бы от неполного
        плана и всегда выглядело бы хуже, чем есть. Факт и финрезультат при
        этом считаются по ВСЕМ проектам: деньги истрачены независимо от того,
        заведён ли по проекту лимит.
        """
        planned_amount = 0.0
        planned_hours = 0.0
        actual_cost_with_budget = 0.0
        actual_cost_amount = 0.0
        actual_hours = 0.0
        actual_income_amount = 0.0
        actual_expense_amount = 0.0
        financial_result = 0.0
        with_budget = 0
        without_budget = 0

        for row in rows:
            actual_cost_amount += _float(row.get("actual_cost_amount"))
            actual_hours += _float(row.get("actual_hours"))
            actual_income_amount += _float(row.get("actual_income_amount"))
            actual_expense_amount += _float(row.get("actual_expense_amount"))
            financial_result += _float(row.get("actual_financial_result"))

            if row.get("has_budget"):
                with_budget += 1
                planned_amount += _float(row.get("planned_amount"))
                planned_hours += _float(row.get("planned_hours"))
                actual_cost_with_budget += _float(row.get("actual_cost_amount"))
            else:
                without_budget += 1

        utilization_percent = (
            round(actual_cost_with_budget / planned_amount * 100.0, 1)
            if planned_amount > 0
            else None
        )

        return {
            "projects_count": with_budget + without_budget,
            "with_budget_count": with_budget,
            "without_budget_count": without_budget,
            "planned_amount": round(planned_amount, 2),
            "planned_hours": round(planned_hours, 2),
            "actual_cost_amount": round(actual_cost_amount, 2),
            "actual_cost_amount_with_budget": round(actual_cost_with_budget, 2),
            "actual_hours": round(actual_hours, 2),
            "actual_income_amount": round(actual_income_amount, 2),
            "actual_expense_amount": round(actual_expense_amount, 2),
            "actual_financial_result": round(financial_result, 2),
            "budget_remaining": round(planned_amount - actual_cost_with_budget, 2) if with_budget else None,
            "budget_utilization_percent": utilization_percent,
        }

    @staticmethod
    def build_status_counts(rows: Iterable[Dict[str, Any]]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        attention = 0
        for row in rows:
            status = str(row.get("budget_health_status") or "").strip() or "Без лимита"
            counts[status] = counts.get(status, 0) + 1
            if status in ATTENTION_STATUSES:
                attention += 1
        counts["attention"] = attention
        return counts

    def thresholds_payload(self) -> Dict[str, Any]:
        return {
            "risk_percent": self.settings["risk_threshold_percent"],
            "overrun_percent": self.settings["overrun_threshold_percent"],
            "support_boundary_amount": self.settings["support_boundary_amount"],
            "notifications_enabled": self.settings["notifications_enabled"],
            "notify_cooldown_hours": self.settings["notify_cooldown_hours"],
            "notify_user_ids": list(self.settings["notify_user_ids"]),
        }

    @staticmethod
    def _registry_sort_key(row: Dict[str, Any]):
        """Сверху — то, где горит: перерасход, риск, потом остальные.

        Внутри группы — по освоению вниз, потом по названию. Сортировка
        серверная, потому что реестр открывают ради первой строки, а не ради
        алфавита; переключатели порядка интерфейс добавляет поверх.
        """
        status = str(row.get("budget_health_status") or "")
        priority = {"Перерасход": 0, "Минус": 1, "Риск": 2, "Граница": 3}.get(status, 4)
        utilization = row.get("budget_utilization_percent")
        utilization_key = -_float(utilization) if utilization is not None else 0.0
        return (priority, utilization_key, str(row.get("project_name") or "").lower())


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
