from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Optional

from b24pysdk import Client
from django.core.cache import cache

from config import config

from .models import Bitrix24Account, ProjectCard, SystemLog
from .project_board_shared import build_account_cache_key, get_project_card_queryset
from .project_budget_service import ProjectBudgetService


logger = logging.getLogger(__name__)


class ProjectBudgetNotifier:
    COOLDOWN_HOURS = 12
    LARGE_CHANGE_ABS_THRESHOLD = 100000.0
    LARGE_CHANGE_RATIO_THRESHOLD = 0.10

    STATUS_EVENT_MAP = {
        "Риск": "budget_risk",
        "Перерасход": "budget_overrun",
        "Минус": "support_minus",
    }

    def __init__(self, client: Optional[Client], account: Bitrix24Account):
        self.client = client or account.client
        self.account = account

    def evaluate_all(self, source: str = "manual") -> Dict[str, Any]:
        cards = list(get_project_card_queryset(self.account).filter(is_archived=False))
        return self._evaluate_cards(cards, source=source)

    def evaluate_project_ids(self, project_ids: Iterable[str], source: str = "manual") -> Dict[str, Any]:
        normalized_ids = [self._clean_str(project_id) for project_id in project_ids]
        normalized_ids = [project_id for project_id in normalized_ids if project_id]
        if not normalized_ids:
            return self._empty_result(source)
        cards = list(
            get_project_card_queryset(self.account)
            .filter(is_archived=False, project_id__in=normalized_ids)
        )
        return self._evaluate_cards(cards, source=source)

    def evaluate_project_item_ids(self, project_item_ids: Iterable[str], source: str = "manual") -> Dict[str, Any]:
        normalized_ids = [self._clean_str(project_item_id) for project_item_id in project_item_ids]
        normalized_ids = [project_item_id for project_item_id in normalized_ids if project_item_id]
        if not normalized_ids:
            return self._empty_result(source)
        cards = list(
            get_project_card_queryset(self.account)
            .filter(is_archived=False, project_item_id__in=normalized_ids)
        )
        return self._evaluate_cards(cards, source=source)

    def _evaluate_cards(self, cards: List[ProjectCard], *, source: str) -> Dict[str, Any]:
        if not cards:
            return self._empty_result(source)

        metrics_map = ProjectBudgetService(self.account).build_metrics_map(cards)
        summary = self._empty_result(source)
        summary["checked"] = len(cards)

        for card in cards:
            metrics = metrics_map.get(card.project_id, {})
            events = self._detect_events(card, metrics)
            for event in events:
                dispatch = self._dispatch_event(card, metrics, event, source=source)
                summary["events"].append(dispatch)
                if dispatch["status"] == "sent":
                    summary["sent"] += 1
                elif dispatch["status"] == "cooldown":
                    summary["cooldown_skipped"] += 1
                elif dispatch["status"] == "error":
                    summary["errors"] += 1
                else:
                    summary["skipped"] += 1

            self._persist_state(card, metrics)

        return summary

    def _detect_events(self, card: ProjectCard, metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        current_status = self._clean_str(metrics.get("budget_health_status")) or ""
        current_financial_result = self._to_float(metrics.get("actual_financial_result"))
        planned_amount = self._to_float(metrics.get("planned_amount"))

        status_key = self._status_state_key(card.project_id)
        prev_status = self._clean_str(cache.get(status_key))
        event_code = self.STATUS_EVENT_MAP.get(current_status)

        if event_code and prev_status != current_status:
            events.append(
                {
                    "code": event_code,
                    "title": f"Статус проекта: {current_status}",
                    "details": {
                        "prev_status": prev_status,
                        "current_status": current_status,
                    },
                }
            )

        prev_financial_result = cache.get(self._financial_result_state_key(card.project_id))
        prev_financial_result_value: Optional[float]
        if prev_financial_result in (None, ""):
            prev_financial_result_value = None
        else:
            prev_financial_result_value = self._to_float(prev_financial_result)

        if prev_financial_result_value is not None:
            delta = round(current_financial_result - prev_financial_result_value, 2)
            if self._is_large_change(delta, planned_amount):
                events.append(
                    {
                        "code": "financial_result_jump",
                        "title": "Резкое изменение финансового результата",
                        "details": {
                            "previous": prev_financial_result_value,
                            "current": current_financial_result,
                            "delta": delta,
                            "planned_amount": planned_amount,
                        },
                    }
                )

        return events

    def _dispatch_event(
        self,
        card: ProjectCard,
        metrics: Dict[str, Any],
        event: Dict[str, Any],
        *,
        source: str,
    ) -> Dict[str, Any]:
        result = {
            "project_id": card.project_id,
            "project_name": card.project_name,
            "event_code": event.get("code"),
            "status": "skipped",
            "reason": "",
        }

        curator_user_id = self._clean_str(card.curator_user_id)
        if not curator_user_id:
            result["reason"] = "curator_user_id is empty"
            self._log_event(
                level="INFO",
                message="Skip notifier event: curator is not assigned",
                payload={"result": result, "source": source},
            )
            return result

        cooldown_key = self._cooldown_key(card.project_id, str(event.get("code") or "event"))
        if cache.get(cooldown_key):
            result["status"] = "cooldown"
            result["reason"] = "cooldown active"
            self._log_event(
                level="INFO",
                message="Skip notifier event: cooldown active",
                payload={"result": result, "source": source},
            )
            return result

        message = self._build_message(card, metrics, event, source=source)
        tag = f"project-budget:{card.project_id}:{event.get('code')}"
        sent, error_message = self._send_notification(curator_user_id, message, tag)

        if sent:
            cache.set(cooldown_key, "1", timeout=self.COOLDOWN_HOURS * 3600)
            result["status"] = "sent"
            self._log_event(
                level="INFO",
                message="Budget notification sent",
                payload={"result": result, "source": source},
            )
            return result

        result["status"] = "error"
        result["reason"] = error_message or "unknown notification error"
        self._log_event(
            level="ERROR",
            message="Budget notification failed",
            payload={"result": result, "source": source},
        )
        return result

    def _send_notification(self, curator_user_id: str, message: str, tag: str) -> tuple[bool, Optional[str]]:
        user_id = int(curator_user_id) if str(curator_user_id).isdigit() else curator_user_id
        params = {
            "USER_ID": user_id,
            "MESSAGE": message,
            "TAG": tag,
            "SUB_TAG": "project_budget",
        }
        methods = ["im.notify.system.add", "im.notify.personal.add"]
        last_error: Optional[str] = None

        for method in methods:
            try:
                self.client._bitrix_token.call_method(method, params)
                return True, None
            except Exception as exc:  # pragma: no cover - external API behavior
                last_error = str(exc)
                logger.warning("Notifier method %s failed: %s", method, exc)

        return False, last_error

    def _build_message(self, card: ProjectCard, metrics: Dict[str, Any], event: Dict[str, Any], *, source: str) -> str:
        project_link = self._build_project_link(card)
        status = self._clean_str(metrics.get("budget_health_status")) or "—"
        cost = self._to_float(metrics.get("actual_cost_amount"))
        income = self._to_float(metrics.get("actual_income_amount"))
        expense = self._to_float(metrics.get("actual_expense_amount"))
        financial_result = self._to_float(metrics.get("actual_financial_result"))

        lines = [
            f"{event.get('title')}",
            f"Проект: {card.project_name} (#{card.project_id})",
            f"Статус бюджета: {status}",
            f"Факт затрат: {cost:.2f}",
            f"Доход/Расход: {income:.2f} / {expense:.2f}",
            f"Финрезультат: {financial_result:.2f}",
            f"Источник события: {source}",
        ]
        if project_link:
            lines.append(f"Карточка проекта: {project_link}")
        return "\n".join(lines)

    def _persist_state(self, card: ProjectCard, metrics: Dict[str, Any]) -> None:
        status = self._clean_str(metrics.get("budget_health_status")) or ""
        financial_result = self._to_float(metrics.get("actual_financial_result"))
        cache.set(self._status_state_key(card.project_id), status, timeout=90 * 24 * 3600)
        cache.set(self._financial_result_state_key(card.project_id), financial_result, timeout=90 * 24 * 3600)

    def _status_state_key(self, project_id: str) -> str:
        return build_account_cache_key(self.account, f"budget-notifier-status:{project_id}")

    def _financial_result_state_key(self, project_id: str) -> str:
        return build_account_cache_key(self.account, f"budget-notifier-financial:{project_id}")

    def _cooldown_key(self, project_id: str, event_code: str) -> str:
        return build_account_cache_key(self.account, f"budget-notifier-cooldown:{project_id}:{event_code}")

    def _build_project_link(self, card: ProjectCard) -> str:
        group_link = ""
        if self._clean_str(card.project_id) and str(card.project_id).isdigit():
            group_link = f"https://{self.account.domain_url}/workgroups/group/{card.project_id}/"

        app_url = str(config.app_base_url or "").strip()
        if app_url:
            if not app_url.startswith("http"):
                app_url = f"https://{app_url}"
            app_link = f"{app_url}/projects?project_id={card.project_id}"
            return app_link if not group_link else f"{app_link} | {group_link}"

        return group_link

    def _is_large_change(self, delta: float, planned_amount: float) -> bool:
        abs_delta = abs(delta)
        if abs_delta >= self.LARGE_CHANGE_ABS_THRESHOLD:
            return True
        if planned_amount > 0 and abs_delta >= (planned_amount * self.LARGE_CHANGE_RATIO_THRESHOLD):
            return True
        return False

    def _log_event(self, *, level: str, message: str, payload: Dict[str, Any]) -> None:
        try:
            SystemLog.objects.create(
                level=level,
                module="project_budget_notifier",
                message=message,
                traceback=json.dumps(payload, ensure_ascii=False, default=str)[:15000],
            )
        except Exception as exc:  # pragma: no cover - best effort logging
            logger.warning("Failed to write SystemLog event for notifier: %s", exc)

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clean_str(value: Any) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _empty_result(source: str) -> Dict[str, Any]:
        return {
            "status": "ok",
            "source": source,
            "checked": 0,
            "sent": 0,
            "skipped": 0,
            "cooldown_skipped": 0,
            "errors": 0,
            "events": [],
        }
