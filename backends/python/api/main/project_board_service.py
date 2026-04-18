import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

from b24pysdk import Client
from django.core.cache import cache
from django.db.models import Case, F, FloatField, Max, Sum, Value, When
from django.utils import timezone

from .bitrix_data_access import BitrixDataService
from .finance_operation_service import FinanceOperationService
from .project_budget_service import ProjectBudgetService
from .configuration_service import ConfigurationService
from .models import Bitrix24Account, ProjectCard, TimesheetItem
from .project_board_shared import (
    BITRIX_REFERENCE_CACHE_TTL,
    HOMEPAGE_CACHE_TTL,
    PROJECT_AUTO_STAGES,
    PROJECT_BOARD_CACHE_TTL,
    PROJECT_MANUAL_STAGES,
    PROJECT_STAGE_IN_WORK,
    PROJECT_STAGE_NEW,
    PROJECT_STAGE_NO_WRITEOFF_30,
    PROJECT_STAGE_NO_WRITEOFF_90,
    PROJECT_STAGE_ORDER,
    build_account_cache_key,
    build_local_project_groups,
    ensure_project_card_schema,
    get_project_card_queryset,
    invalidate_project_runtime_caches,
)


logger = logging.getLogger(__name__)


def _extract_items_from_response(response: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    result = response.get("result", [])
    next_value = response.get("next")

    if isinstance(result, dict):
        items = result.get("items")
        if items is None:
            items = result.get("result", [])
        if next_value is None:
            next_value = result.get("next")
    else:
        items = result

    if not isinstance(items, list):
        items = []

    if next_value in ("", False):
        next_value = None

    return items, int(next_value) if next_value is not None else None


def _get_group_value(source: Dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        value_str = str(value).strip()
        if value_str:
            return value_str
    return None


class ProjectCardService:
    def __init__(self, client: Optional[Client], account: Bitrix24Account):
        self.client = client or account.client
        self.account = account

    def get_card_data(self, project_id: str) -> Dict[str, Any]:
        if not ensure_project_card_schema():
            raise RuntimeError("Локальная таблица проектов пока недоступна. Повторите позже после завершения миграции.")
        card = self._get_card(project_id)
        budget_metrics = ProjectBudgetService(self.account).get_card_metrics(card)
        try:
            recent_finance_operations = FinanceOperationService(self.client, self.account).get_recent_operations_by_project_item_id(
                card.project_item_id,
                limit=5,
            )
        except Exception:
            recent_finance_operations = []
        return self.serialize_card(
            card,
            budget_metrics=budget_metrics,
            recent_finance_operations=recent_finance_operations,
        )

    def get_board_data(self) -> Dict[str, Any]:
        cached = cache.get(build_account_cache_key(self.account, "project-board"))
        if cached is not None:
            return cached

        if not ensure_project_card_schema():
            return self.get_fallback_board_data()

        self.refresh_writeoff_stats()
        config = self._load_config()
        stage_options = self.get_project_stage_options(config)
        stage_lookup = self.get_project_stage_lookup(config)
        company_options = self.get_companies()
        legal_entity_options = self.get_legal_entities(config)
        cards = list(get_project_card_queryset(self.account).order_by("is_archived", "project_name"))
        budget_metrics_map = ProjectBudgetService(self.account).build_metrics_map(cards)
        active_cards = [card for card in cards if not card.is_archived]

        payload = {
            "stages": stage_options,
            "cards": [
                self.serialize_card(
                    card,
                    stage_lookup=stage_lookup,
                    company_options=company_options,
                    legal_entity_options=legal_entity_options,
                    budget_metrics=budget_metrics_map.get(card.project_id),
                )
                for card in cards
            ],
            "summary": {
                "total_count": len(cards),
                "active_count": len(active_cards),
                "archived_count": len(cards) - len(active_cards),
                "support_count": sum(1 for card in active_cards if card.is_support),
                "inactive_30_count": sum(1 for card in active_cards if card.stage == PROJECT_STAGE_NO_WRITEOFF_30),
                "inactive_90_count": sum(1 for card in active_cards if card.stage == PROJECT_STAGE_NO_WRITEOFF_90),
            },
        }
        cache.set(build_account_cache_key(self.account, "project-board"), payload, PROJECT_BOARD_CACHE_TTL)
        return payload

    def get_fallback_board_data(self) -> Dict[str, Any]:
        _, by_project_id, by_project_title = self.collect_writeoff_maps()
        fallback_cards = []

        for group in build_local_project_groups(self.account):
            project_id = _get_group_value(group, "ID", "id")
            project_name = _get_group_value(group, "NAME", "name") or f"Проект {project_id}"
            last_writeoff_at = by_project_id.get(project_id) or by_project_title.get(project_name)
            last_writeoff_days = (timezone.localdate() - last_writeoff_at.date()).days if last_writeoff_at else 0
            stage = PROJECT_STAGE_IN_WORK if last_writeoff_at else PROJECT_STAGE_NEW

            fallback_cards.append(
                {
                    "id": f"fallback-{project_id}",
                    "project_item_id": None,
                    "project_id": project_id,
                    "project_name": project_name,
                    "stage": stage,
                    "manual_stage": stage,
                    "is_archived": False,
                    "archived_at": None,
                    "project_hours_budget": None,
                    "hourly_rate": 0.0,
                    "is_support": False,
                    "project_type": "delivery",
                    "budget_mode": "hours_and_amount",
                    "planned_budget_amount": None,
                    "planned_hours": None,
                    "planned_amount": None,
                    "actual_hours": 0.0,
                    "actual_cost_amount": 0.0,
                    "actual_income_amount": 0.0,
                    "actual_expense_amount": 0.0,
                    "actual_financial_result": 0.0,
                    "hours_remaining": None,
                    "budget_remaining": None,
                    "budget_utilization_mode": "none",
                    "budget_utilization_ratio": None,
                    "budget_utilization_percent": None,
                    "budget_health_status": "Без лимита",
                    "budget_health_reason": "Не задан плановый лимит.",
                    "budget": {
                        "planned_hours": None,
                        "planned_amount": None,
                        "actual_hours": 0.0,
                        "actual_cost_amount": 0.0,
                        "actual_income_amount": 0.0,
                        "actual_expense_amount": 0.0,
                        "actual_financial_result": 0.0,
                        "hours_remaining": None,
                        "budget_remaining": None,
                        "budget_utilization_mode": "none",
                        "budget_utilization_ratio": None,
                        "budget_utilization_percent": None,
                        "budget_health_status": "Без лимита",
                        "budget_health_reason": "Не задан плановый лимит.",
                    },
                    "recent_finance_operations": [],
                    "curator_user_id": None,
                    "curator_name": None,
                    "project_start_date": None,
                    "project_end_date": None,
                    "company_id": None,
                    "company_name": None,
                    "company_inn": None,
                    "our_legal_entity_id": None,
                    "our_legal_entity_name": None,
                    "our_legal_entity_inn": None,
                    "last_writeoff_at": last_writeoff_at.isoformat() if last_writeoff_at else None,
                    "last_writeoff_days": last_writeoff_days,
                    "stage_source": "manual",
                    "created_at": None,
                    "updated_at": None,
                }
            )

        payload = {
            "stages": self._build_legacy_stage_options(),
            "cards": sorted(fallback_cards, key=lambda card: card["project_name"]),
            "summary": {
                "total_count": len(fallback_cards),
                "active_count": len(fallback_cards),
                "archived_count": 0,
                "support_count": 0,
                "inactive_30_count": sum(1 for card in fallback_cards if card["stage"] == PROJECT_STAGE_NO_WRITEOFF_30),
                "inactive_90_count": sum(1 for card in fallback_cards if card["stage"] == PROJECT_STAGE_NO_WRITEOFF_90),
            },
            "warning": (
                "Локальная таблица проектов недоступна. Показан временный board по уже загруженным списаниям. "
                "Редактирование и архив могут быть недоступны до завершения миграции."
            ),
        }
        cache.set(build_account_cache_key(self.account, "project-board"), payload, PROJECT_BOARD_CACHE_TTL)
        return payload

    def get_meta(self) -> Dict[str, Any]:
        cache_key = build_account_cache_key(self.account, "project-board-meta")
        cached = cache.get(cache_key)
        if cached and self._meta_has_required_shape(cached) and self._meta_has_options(cached):
            return cached
        if cached is not None:
            cache.delete(cache_key)

        config = self._load_config()
        fallback_employees = self._get_project_card_fallback_options("curator_user_id", "curator_name")
        fallback_companies = self._get_project_card_fallback_options("company_id", "company_name")
        fallback_legal_entities = self._get_project_card_fallback_options("our_legal_entity_id", "our_legal_entity_name")

        directory_employees = self._merge_reference_options(
            BitrixDataService(self.client, config, self.account).fetch_active_users(),
            fallback_employees,
        )
        directory_companies = self._merge_reference_options(self.get_companies(), fallback_companies)
        directory_legal_entities = self._merge_reference_options(self.get_legal_entities(config), fallback_legal_entities)

        meta = {
            "filters": {
                "curators": directory_employees,
                "companies": directory_companies,
                "legal_entities": directory_legal_entities,
            },
            "directories": {
                "employees": directory_employees,
                "companies": directory_companies,
                "legal_entities": directory_legal_entities,
            },
            "employees": directory_employees,
            "companies": directory_companies,
            "legal_entities": directory_legal_entities,
        }
        if self._meta_has_options(meta):
            cache.set(cache_key, meta, BITRIX_REFERENCE_CACHE_TTL)
        else:
            cache.delete(cache_key)
        return meta

    def get_homepage_snapshot(self) -> Dict[str, Any]:
        cached = cache.get(build_account_cache_key(self.account, "project-board-homepage"))
        if cached is not None:
            return cached

        board = self.get_board_data()
        cards = board.get("cards", [])
        active_cards = [card for card in cards if not card.get("is_archived")]
        curators_map: Dict[str, Dict[str, str]] = {}

        for card in active_cards:
            curator_id = str(card.get("curator_user_id") or "").strip()
            curator_name = str(card.get("curator_name") or "").strip()
            if curator_id and curator_id not in curators_map:
                curators_map[curator_id] = {
                    "id": curator_id,
                    "name": curator_name or f"Сотрудник {curator_id}",
                }

        risk_cards = sorted(
            [card for card in active_cards if (card.get("last_writeoff_days") or 0) >= 30],
            key=lambda card: (card.get("last_writeoff_days") or 0, card.get("project_name") or ""),
            reverse=True,
        )[:6]

        snapshot = {
            "summary": board.get("summary", {}),
            "cards": active_cards,
            "stages": board.get("stages", []),
            "curators": sorted(curators_map.values(), key=lambda item: item["name"]),
            "risk_cards": risk_cards,
            "top_loss_projects": self._get_revenue_leakage_rows(limit=5),
            "warning": board.get("warning"),
            "generated_at": timezone.now().isoformat(),
        }
        cache.set(build_account_cache_key(self.account, "project-board-homepage"), snapshot, HOMEPAGE_CACHE_TTL)
        return snapshot

    def update_project_card(self, project_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not ensure_project_card_schema():
            raise RuntimeError("Локальная таблица проектов пока недоступна. Повторите позже после завершения миграции.")

        card = self._get_card(project_id)
        warning: Optional[str] = None

        next_project_name = self._clean_str(payload.get("project_name")) or card.project_name
        next_curator_user_id = self._clean_str(payload.get("curator_user_id")) if "curator_user_id" in payload else card.curator_user_id
        next_curator_name = self._clean_str(payload.get("curator_name")) if "curator_name" in payload else card.curator_name
        next_company_id = self._clean_str(payload.get("company_id")) if "company_id" in payload else card.company_id
        next_company_name = self._clean_str(payload.get("company_name")) if "company_name" in payload else card.company_name
        next_legal_entity_id = self._clean_str(payload.get("our_legal_entity_id")) if "our_legal_entity_id" in payload else card.our_legal_entity_id
        next_legal_entity_name = self._clean_str(payload.get("our_legal_entity_name")) if "our_legal_entity_name" in payload else card.our_legal_entity_name
        next_budget = self._to_optional_float(payload.get("project_hours_budget")) if "project_hours_budget" in payload else card.project_hours_budget
        next_hourly_rate = self._to_float(payload.get("hourly_rate"), default=card.hourly_rate) if "hourly_rate" in payload else card.hourly_rate
        next_is_support = self._to_bool(payload.get("is_support"), default=card.is_support) if "is_support" in payload else card.is_support
        next_project_type = self._clean_str(payload.get("project_type")) if "project_type" in payload else card.project_type
        next_budget_mode = self._clean_str(payload.get("budget_mode")) if "budget_mode" in payload else card.budget_mode
        next_planned_budget_amount = (
            self._to_optional_float(payload.get("planned_budget_amount"))
            if "planned_budget_amount" in payload
            else card.planned_budget_amount
        )
        next_start_date = self._parse_date(payload.get("project_start_date")) if "project_start_date" in payload else card.project_start_date
        next_end_date = self._parse_date(payload.get("project_end_date")) if "project_end_date" in payload else card.project_end_date
        if not next_project_type:
            next_project_type = "support" if next_is_support else "delivery"
        if not next_budget_mode:
            next_budget_mode = "support" if next_is_support else "hours_and_amount"

        if next_curator_user_id and not next_curator_name:
            next_curator_name = BitrixDataService(self.client, {}, self.account).fetch_users([next_curator_user_id]).get(next_curator_user_id)
        next_company_id, next_company_name = self._resolve_company_reference(next_company_id, next_company_name)
        next_legal_entity_id, next_legal_entity_name = self._resolve_legal_entity_reference(next_legal_entity_id, next_legal_entity_name)

        bitrix_payload: Dict[str, Any] = {"GROUP_ID": int(card.project_id)}
        if next_project_name != card.project_name:
            bitrix_payload["NAME"] = next_project_name
        if "project_start_date" in payload:
            bitrix_payload["PROJECT_DATE_START"] = datetime.combine(next_start_date, datetime.min.time()).isoformat() if next_start_date else None
        if "project_end_date" in payload:
            bitrix_payload["PROJECT_DATE_FINISH"] = datetime.combine(next_end_date, datetime.min.time()).isoformat() if next_end_date else None

        bitrix_payload = {key: value for key, value in bitrix_payload.items() if value is not None}
        if len(bitrix_payload) > 1:
            try:
                self.client._bitrix_token.call_method("sonet_group.update", bitrix_payload)
            except Exception as exc:
                warning = f"Не удалось полностью синхронизировать изменения с Битрикс24: {exc}"
                logger.warning("Project update Bitrix sync failed for %s: %s", card.project_id, exc)

        card.project_name = next_project_name
        card.project_hours_budget = next_budget
        card.hourly_rate = next_hourly_rate
        card.is_support = next_is_support
        card.project_type = next_project_type
        card.budget_mode = next_budget_mode
        card.planned_budget_amount = next_planned_budget_amount
        card.curator_user_id = next_curator_user_id
        card.curator_name = next_curator_name
        card.project_start_date = next_start_date
        card.project_end_date = next_end_date
        card.company_id = next_company_id
        card.company_name = next_company_name
        card.our_legal_entity_id = next_legal_entity_id
        card.our_legal_entity_name = next_legal_entity_name
        card.save()
        spa_warning = self._sync_project_card_to_project_spa(card)
        warning = self._merge_warning(warning, spa_warning)
        invalidate_project_runtime_caches(self.account)

        return {"card": self.serialize_card(card), "warning": warning}

    def update_stage(self, project_id: str, stage: str) -> Dict[str, Any]:
        if not ensure_project_card_schema():
            raise RuntimeError("Локальная таблица проектов пока недоступна. Повторите позже после завершения миграции.")
        if stage not in PROJECT_MANUAL_STAGES:
            stage_lookup = self.get_project_stage_lookup()
            resolved_stage = self.resolve_project_stage_title(stage, stage_lookup)
            if not resolved_stage or resolved_stage in PROJECT_AUTO_STAGES or not self._is_supported_stage(resolved_stage, stage_lookup):
                raise ValueError("Недопустимая стадия для ручного перевода")
            stage = resolved_stage

        card = self._get_card(project_id)
        card.stage = stage
        card.manual_stage = stage
        card.stage_source = "manual"
        card.save(update_fields=["stage", "manual_stage", "stage_source", "stage_updated_at", "updated_at"])
        warning = self._sync_project_card_to_project_spa(card)
        invalidate_project_runtime_caches(self.account)
        return {"card": self.serialize_card(card), "warning": warning}

    def archive_project(self, project_id: str, is_archived: bool) -> Dict[str, Any]:
        if not ensure_project_card_schema():
            raise RuntimeError("Локальная таблица проектов пока недоступна. Повторите позже после завершения миграции.")

        card = self._get_card(project_id)
        warning: Optional[str] = None
        card.is_archived = bool(is_archived)
        card.archived_at = timezone.now() if card.is_archived else None
        card.save(update_fields=["is_archived", "archived_at", "updated_at"])
        invalidate_project_runtime_caches(self.account)

        try:
            self.client._bitrix_token.call_method(
                "sonet_group.update",
                {"GROUP_ID": int(card.project_id), "CLOSED": "Y" if card.is_archived else "N"},
            )
        except Exception as exc:
            warning = f"Локальный архив обновлен, но Битрикс24 вернул ошибку: {exc}"
            logger.warning("Project archive Bitrix sync failed for %s: %s", card.project_id, exc)

        spa_warning = self._sync_project_card_to_project_spa(card)
        warning = self._merge_warning(warning, spa_warning)
        return {"card": self.serialize_card(card), "warning": warning}

    def refresh_writeoff_stats(self) -> None:
        if not ensure_project_card_schema():
            return

        by_project_item_id, by_project_id, by_project_title = self.collect_writeoff_maps()
        cards = list(get_project_card_queryset(self.account))
        today = timezone.localdate()
        updated_cards: List[ProjectCard] = []

        for card in cards:
            last_writeoff_at = by_project_item_id.get(card.project_item_id) if card.project_item_id else None
            if last_writeoff_at is None:
                last_writeoff_at = by_project_id.get(card.project_id)
            if last_writeoff_at is None and card.project_name:
                last_writeoff_at = by_project_title.get(card.project_name)
            last_writeoff_days = (today - last_writeoff_at.date()).days if last_writeoff_at else 0

            if card.last_writeoff_at != last_writeoff_at or card.last_writeoff_days != last_writeoff_days:
                card.last_writeoff_at = last_writeoff_at
                card.last_writeoff_days = last_writeoff_days
                updated_cards.append(card)

        if updated_cards:
            ProjectCard.objects.bulk_update(updated_cards, ["last_writeoff_at", "last_writeoff_days"])

    def collect_writeoff_maps(self) -> Tuple[Dict[str, datetime], Dict[str, datetime], Dict[str, datetime]]:
        by_project_item_id: Dict[str, datetime] = {}
        by_project_id: Dict[str, datetime] = {}
        by_project_title: Dict[str, datetime] = {}

        item_rows = (
            TimesheetItem.objects.filter(bitrix24_account=self.account)
            .exclude(project_item_id__isnull=True)
            .exclude(project_item_id="")
            .values("project_item_id")
            .annotate(last_writeoff_at=Max("date_reflection"))
        )
        for row in item_rows:
            project_item_id = self._clean_str(row.get("project_item_id"))
            if project_item_id and row.get("last_writeoff_at"):
                by_project_item_id[project_item_id] = row["last_writeoff_at"]

        id_rows = (
            TimesheetItem.objects.filter(bitrix24_account=self.account)
            .exclude(project_id__isnull=True)
            .exclude(project_id="")
            .values("project_id")
            .annotate(last_writeoff_at=Max("date_reflection"))
        )
        for row in id_rows:
            project_id = self._clean_str(row.get("project_id"))
            if project_id and row.get("last_writeoff_at"):
                by_project_id[project_id] = row["last_writeoff_at"]

        title_rows = (
            TimesheetItem.objects.filter(bitrix24_account=self.account)
            .exclude(project_title__isnull=True)
            .exclude(project_title="")
            .values("project_title")
            .annotate(last_writeoff_at=Max("date_reflection"))
        )
        for row in title_rows:
            project_title = self._clean_str(row.get("project_title"))
            if project_title and row.get("last_writeoff_at"):
                by_project_title[project_title] = row["last_writeoff_at"]

        return by_project_item_id, by_project_id, by_project_title

    def get_companies(self) -> List[Dict[str, Any]]:
        return self._fetch_references_with_cache(
            "project-board-companies",
            self._fetch_companies_live,
            fallback=self._get_project_card_fallback_options("company_id", "company_name"),
        )

    def get_legal_entities(self, config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return self._fetch_references_with_cache(
            "project-board-legal-entities",
            lambda: self._fetch_companies_live(only_my_company=True),
            fallback=self._get_project_card_fallback_options("our_legal_entity_id", "our_legal_entity_name"),
        )

    def serialize_card(
        self,
        card: ProjectCard,
        stage_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
        company_options: Optional[List[Dict[str, Any]]] = None,
        legal_entity_options: Optional[List[Dict[str, Any]]] = None,
        budget_metrics: Optional[Dict[str, Any]] = None,
        recent_finance_operations: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        stage_lookup = stage_lookup or self.get_project_stage_lookup()
        company_options = company_options if company_options is not None else self.get_companies()
        legal_entity_options = legal_entity_options if legal_entity_options is not None else self.get_legal_entities()
        budget_metrics = budget_metrics if budget_metrics is not None else ProjectBudgetService(self.account).get_card_metrics(card)
        recent_finance_operations = recent_finance_operations or []
        company_id, company_name, company_inn = self._resolve_reference_details(
            card.company_id,
            card.company_name,
            company_options,
        )
        legal_entity_id, legal_entity_name, legal_entity_inn = self._resolve_reference_details(
            card.our_legal_entity_id,
            card.our_legal_entity_name,
            legal_entity_options,
        )

        if company_id and not company_inn:
            logger.warning(
                "[ProjectBoard][INN] Missing client INN for domain=%s project_id=%s company_id=%s company_name=%s",
                self.account.domain_url,
                card.project_id,
                company_id,
                company_name,
            )
        if legal_entity_id and not legal_entity_inn:
            logger.warning(
                "[ProjectBoard][INN] Missing legal entity INN for domain=%s project_id=%s legal_entity_id=%s legal_entity_name=%s",
                self.account.domain_url,
                card.project_id,
                legal_entity_id,
                legal_entity_name,
            )

        return {
            "id": str(card.id),
            "project_item_id": card.project_item_id,
            "project_id": card.project_id,
            "project_name": card.project_name,
            "stage": self.resolve_project_stage_title(card.stage, stage_lookup),
            "manual_stage": self.resolve_project_stage_title(card.manual_stage, stage_lookup) if card.manual_stage else None,
            "is_archived": card.is_archived,
            "archived_at": card.archived_at.isoformat() if card.archived_at else None,
            "project_hours_budget": card.project_hours_budget,
            "hourly_rate": card.hourly_rate,
            "is_support": card.is_support,
            "project_type": card.project_type,
            "budget_mode": card.budget_mode,
            "planned_budget_amount": card.planned_budget_amount,
            "planned_hours": budget_metrics.get("planned_hours"),
            "planned_amount": budget_metrics.get("planned_amount"),
            "actual_hours": budget_metrics.get("actual_hours", 0.0),
            "actual_cost_amount": budget_metrics.get("actual_cost_amount", 0.0),
            "actual_income_amount": budget_metrics.get("actual_income_amount", 0.0),
            "actual_expense_amount": budget_metrics.get("actual_expense_amount", 0.0),
            "actual_financial_result": budget_metrics.get("actual_financial_result", 0.0),
            "hours_remaining": budget_metrics.get("hours_remaining"),
            "budget_remaining": budget_metrics.get("budget_remaining"),
            "budget_utilization_mode": budget_metrics.get("budget_utilization_mode"),
            "budget_utilization_ratio": budget_metrics.get("budget_utilization_ratio"),
            "budget_utilization_percent": budget_metrics.get("budget_utilization_percent"),
            "budget_health_status": budget_metrics.get("budget_health_status", "Без лимита"),
            "budget_health_reason": budget_metrics.get("budget_health_reason"),
            "budget": budget_metrics,
            "recent_finance_operations": recent_finance_operations,
            "curator_user_id": card.curator_user_id,
            "curator_name": card.curator_name,
            "project_start_date": card.project_start_date.isoformat() if card.project_start_date else None,
            "project_end_date": card.project_end_date.isoformat() if card.project_end_date else None,
            "company_id": company_id,
            "company_name": company_name,
            "company_inn": company_inn,
            "our_legal_entity_id": legal_entity_id,
            "our_legal_entity_name": legal_entity_name,
            "our_legal_entity_inn": legal_entity_inn,
            "last_writeoff_at": card.last_writeoff_at.isoformat() if card.last_writeoff_at else None,
            "last_writeoff_days": card.last_writeoff_days,
            "stage_source": card.stage_source,
            "created_at": card.created_at.isoformat() if card.created_at else None,
            "updated_at": card.updated_at.isoformat() if card.updated_at else None,
        }

    def _resolve_reference_details(
        self,
        reference_id: Any,
        reference_name: Any = None,
        options: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        resolved_id = self._clean_str(reference_id)
        resolved_name = self._clean_str(reference_name)
        resolved_inn: Optional[str] = None

        if not resolved_id:
            return resolved_id, resolved_name, resolved_inn

        lookup_name = None
        if options:
            for option in options:
                option_id = self._clean_str(option.get("id"))
                if option_id != resolved_id:
                    continue
                lookup_name = self._clean_str(option.get("name"))
                resolved_inn = self._clean_str(option.get("inn"))
                break

        if not resolved_name or resolved_name == resolved_id:
            resolved_name = lookup_name or resolved_name or resolved_id

        return resolved_id, resolved_name, resolved_inn

    def _load_config(self) -> Dict[str, Any]:
        return ConfigurationService(self.client, self.account).get_configuration_sync()

    def _get_project_card_fallback_options(self, id_field: str, name_field: str) -> List[Dict[str, Any]]:
        if not ensure_project_card_schema():
            return []

        rows = (
            get_project_card_queryset(self.account)
            .exclude(**{f"{id_field}__isnull": True})
            .exclude(**{id_field: ""})
            .values(id_field, name_field)
            .order_by(name_field)
        )

        seen_ids = set()
        result: List[Dict[str, Any]] = []
        for row in rows:
            option_id = self._clean_str(row.get(id_field))
            option_name = self._clean_str(row.get(name_field))
            if not option_id or option_id in seen_ids:
                continue
            seen_ids.add(option_id)
            result.append(
                {
                    "id": option_id,
                    "name": option_name or option_id,
                    "search_text": " ".join(part for part in [option_name or option_id] if part).strip(),
                }
            )
        return result

    def _build_legacy_stage_options(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": stage,
                "title": stage,
                "kind": "auto" if stage in PROJECT_AUTO_STAGES else "manual",
                "can_drop": stage in PROJECT_MANUAL_STAGES,
            }
            for stage in PROJECT_STAGE_ORDER
        ]

    def get_project_stage_options(self, config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        cache_key = build_account_cache_key(self.account, "project-board-stages")
        cached = cache.get(cache_key)
        if self._has_reference_options(cached):
            return cached
        if cached == []:
            cache.delete(cache_key)

        options = self._fetch_project_stage_options(config)
        if not options:
            options = self._build_legacy_stage_options()

        cache.set(cache_key, options, BITRIX_REFERENCE_CACHE_TTL)
        return options

    def get_project_stage_lookup(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
        stage_options = self.get_project_stage_options(config)
        by_id: Dict[str, Dict[str, Any]] = {}
        by_title: Dict[str, Dict[str, Any]] = {}
        for option in stage_options:
            option_id = self._clean_str(option.get("id"))
            option_title = self._clean_str(option.get("title"))
            if option_id and option_id not in by_id:
                by_id[option_id] = option
            if option_title and option_title not in by_title:
                by_title[option_title] = option
        return {"by_id": by_id, "by_title": by_title}

    def resolve_project_stage_title(self, value: Any, stage_lookup: Optional[Dict[str, Dict[str, Any]]] = None) -> Optional[str]:
        stage_value = self._clean_str(value)
        if not stage_value:
            return None
        lookup = stage_lookup or self.get_project_stage_lookup()
        resolved = lookup.get("by_title", {}).get(stage_value)
        if resolved:
            return self._clean_str(resolved.get("title")) or stage_value
        resolved = lookup.get("by_id", {}).get(stage_value)
        if resolved:
            return self._clean_str(resolved.get("title")) or stage_value
        return stage_value

    def resolve_project_stage_id(self, value: Any, stage_lookup: Optional[Dict[str, Dict[str, Any]]] = None) -> Optional[str]:
        stage_value = self._clean_str(value)
        if not stage_value:
            return None
        lookup = stage_lookup or self.get_project_stage_lookup()
        resolved = lookup.get("by_id", {}).get(stage_value)
        if resolved:
            return self._clean_str(resolved.get("id")) or stage_value
        resolved = lookup.get("by_title", {}).get(stage_value)
        if resolved:
            return self._clean_str(resolved.get("id")) or stage_value
        return stage_value

    def _is_supported_stage(self, stage: Optional[str], stage_lookup: Optional[Dict[str, Dict[str, Any]]] = None) -> bool:
        stage_value = self._clean_str(stage)
        if not stage_value:
            return False
        if stage_value in PROJECT_MANUAL_STAGES or stage_value in PROJECT_AUTO_STAGES:
            return True
        lookup = stage_lookup or self.get_project_stage_lookup()
        return stage_value in lookup.get("by_title", {}) or stage_value in lookup.get("by_id", {})

    def _fetch_project_stage_options(self, config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        if config is None:
            config = self._load_config()
        try:
            entity_type_id = int((config or {}).get("project_sp_entity_type_id") or 0)
        except (TypeError, ValueError):
            entity_type_id = 0
        if not entity_type_id:
            return []

        categories: List[Dict[str, Any]] = []
        try:
            response = self.client._bitrix_token.call_method("crm.category.list", {"entityTypeId": entity_type_id})
            result = response.get("result", [])
            if isinstance(result, dict):
                categories = result.get("categories") or result.get("items") or result.get("result") or []
            elif isinstance(result, list):
                categories = result
        except Exception as exc:
            logger.warning("Project stage categories fetch failed for %s: %s", entity_type_id, exc)

        category_id = None
        if categories:
            selected_category = next(
                (
                    category
                    for category in categories
                    if str(category.get("isDefault") or category.get("IS_DEFAULT") or "").strip().lower() in {"1", "y", "yes", "true"}
                ),
                next(
                    (
                        category
                        for category in categories
                        if str(category.get("id") or category.get("ID") or category.get("categoryId") or "").strip() in {"0", ""}
                    ),
                    categories[0],
                ),
            )
            category_id = self._clean_str(selected_category.get("id") or selected_category.get("ID") or selected_category.get("categoryId"))
        if category_id is None:
            category_id = "0"

        stage_entity_id = f"DYNAMIC_{entity_type_id}_STAGE_{category_id}"
        try:
            statuses = self._fetch_paginated(
                "crm.status.list",
                {"filter": {"ENTITY_ID": stage_entity_id}, "order": {"SORT": "ASC"}},
            )
        except Exception as exc:
            logger.warning("Project stage status fetch failed for %s: %s", stage_entity_id, exc)
            statuses = []

        if not statuses and category_id != "0":
            try:
                statuses = self._fetch_paginated(
                    "crm.status.list",
                    {"filter": {"ENTITY_ID": f"DYNAMIC_{entity_type_id}_STAGE_0"}, "order": {"SORT": "ASC"}},
                )
            except Exception as exc:
                logger.warning("Fallback project stage status fetch failed for %s: %s", entity_type_id, exc)
                statuses = []

        options: List[Dict[str, Any]] = []
        seen_ids = set()
        for status in statuses:
            status_id = self._clean_str(status.get("STATUS_ID") or status.get("statusId") or status.get("id") or status.get("ID"))
            title = self._clean_str(status.get("NAME") or status.get("name") or status.get("TITLE") or status.get("title") or status_id)
            if not status_id or status_id in seen_ids or not title:
                continue
            seen_ids.add(status_id)
            semantics = self._clean_str(status.get("SEMANTICS") or status.get("semantics"))
            options.append(
                {
                    "id": status_id,
                    "title": title,
                    "kind": "manual",
                    "can_drop": semantics not in {"S", "F"},
                    "semantics": semantics,
                    "sort": status.get("SORT"),
                }
            )

        for stage in PROJECT_AUTO_STAGES:
            if stage in seen_ids or stage in {item["title"] for item in options}:
                continue
            options.append(
                {
                    "id": stage,
                    "title": stage,
                    "kind": "auto",
                    "can_drop": False,
                }
            )

        return options

    def _resolve_company_reference(self, company_id: Any, company_name: Any = None) -> Tuple[Optional[str], Optional[str]]:
        resolved_id = self._clean_str(company_id)
        resolved_name = self._clean_str(company_name)
        if resolved_name and resolved_name != resolved_id:
            return resolved_id, resolved_name
        if not resolved_id:
            return resolved_id, resolved_name

        lookup = {self._clean_str(item.get("id")): self._clean_str(item.get("name")) for item in self.get_companies()}
        lookup_name = lookup.get(resolved_id)
        return resolved_id, lookup_name or resolved_name or resolved_id

    def _resolve_legal_entity_reference(self, entity_id: Any, entity_name: Any = None) -> Tuple[Optional[str], Optional[str]]:
        resolved_id = self._clean_str(entity_id)
        resolved_name = self._clean_str(entity_name)
        if resolved_name and resolved_name != resolved_id:
            return resolved_id, resolved_name
        if not resolved_id:
            return resolved_id, resolved_name

        lookup = {self._clean_str(item.get("id")): self._clean_str(item.get("name")) for item in self.get_legal_entities()}
        lookup_name = lookup.get(resolved_id)
        return resolved_id, lookup_name or resolved_name or resolved_id

    @staticmethod
    def _merge_reference_options(*option_groups: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        seen_ids = set()
        merged: List[Dict[str, Any]] = []

        for option_group in option_groups:
            if not option_group:
                continue
            for option in option_group:
                option_id = ProjectCardService._clean_str(option.get("id"))
                option_name = ProjectCardService._clean_str(option.get("name"))
                if not option_id or option_id in seen_ids:
                    continue

                seen_ids.add(option_id)
                normalized_option = dict(option)
                normalized_option["id"] = option_id
                normalized_option["name"] = option_name or option_id

                option_inn = ProjectCardService._clean_str(option.get("inn"))
                if option_inn:
                    normalized_option["inn"] = option_inn
                if "is_my_company" in option:
                    normalized_option["is_my_company"] = ProjectCardService._to_bool(option.get("is_my_company"), default=False)

                normalized_option["search_text"] = " ".join(
                    part
                    for part in [
                        normalized_option.get("name"),
                        option_inn,
                        ProjectCardService._clean_str(option.get("search_text")),
                    ]
                    if part
                ).strip()
                merged.append(normalized_option)

        return sorted(merged, key=lambda item: item["name"])

    @staticmethod
    def _has_reference_options(options: Optional[List[Dict[str, str]]]) -> bool:
        return bool(options and len(options) > 0)

    def _meta_has_options(self, meta: Optional[Dict[str, Any]]) -> bool:
        if not meta:
            return False

        directories = meta.get("directories") if isinstance(meta, dict) else None
        if isinstance(directories, dict):
            return any(self._has_reference_options(directories.get(key)) for key in ("employees", "companies"))
        return any(self._has_reference_options(meta.get(key)) for key in ("employees", "companies"))

    @staticmethod
    def _meta_has_required_shape(meta: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(meta, dict):
            return False
        return isinstance(meta.get("filters"), dict) and isinstance(meta.get("directories"), dict)

    def _fetch_references_with_cache(
        self,
        cache_suffix: str,
        fetcher,
        fallback: Optional[List[Dict[str, Any]]] = None,
        ttl: int = BITRIX_REFERENCE_CACHE_TTL,
    ) -> List[Dict[str, Any]]:
        cache_key = build_account_cache_key(self.account, cache_suffix)
        cached = cache.get(cache_key)
        if self._has_reference_options(cached):
            return cached
        if cached == []:
            cache.delete(cache_key)

        live_result: List[Dict[str, Any]] = []
        try:
            live_result = fetcher() or []
        except Exception as exc:
            logger.warning("Reference fetch failed for %s: %s", cache_suffix, exc)

        merged = self._merge_reference_options(live_result, fallback or [])
        if merged:
            cache.set(cache_key, merged, ttl)
        else:
            cache.delete(cache_key)
        return merged

    def _fetch_companies_live(self, only_my_company: bool = False) -> List[Dict[str, Any]]:
        inn_map = self._fetch_company_inn_map()
        methods = [
            ("crm.item.list", {"entityTypeId": 4, "select": ["id", "title", "isMyCompany"], "order": {"title": "ASC"}}),
            ("crm.company.list", {"select": ["ID", "TITLE", "IS_MY_COMPANY"], "order": {"TITLE": "ASC"}}),
        ]

        for method, params in methods:
            try:
                companies = self._fetch_paginated(method, params)
            except Exception as exc:
                logger.warning("Company fetch failed for %s: %s", method, exc)
                continue

            normalized: List[Dict[str, Any]] = []
            seen_ids = set()
            for company in companies:
                company_id = self._clean_str(company.get("ID") or company.get("id"))
                company_name = self._clean_str(company.get("TITLE") or company.get("title") or company.get("NAME") or company.get("name"))
                is_my_company = self._to_bool(company.get("IS_MY_COMPANY") or company.get("isMyCompany"), default=False)
                company_inn = self._clean_str(
                    company.get("RQ_INN")
                    or company.get("rqInn")
                    or company.get("INN")
                    or company.get("inn")
                    or inn_map.get(company_id)
                )
                if not company_id or not company_name or company_id in seen_ids:
                    continue
                if only_my_company and not is_my_company:
                    continue

                seen_ids.add(company_id)
                normalized.append(
                    {
                        "id": company_id,
                        "name": company_name,
                        "inn": company_inn,
                        "is_my_company": is_my_company,
                        "search_text": " ".join(part for part in [company_name, company_inn] if part).strip(),
                    }
                )

            if normalized:
                return sorted(normalized, key=lambda item: item["name"])

        return []

    def _fetch_company_inn_map(self) -> Dict[str, str]:
        try:
            requisites = self._fetch_paginated(
                "crm.requisite.list",
                {
                    "filter": {"ENTITY_TYPE_ID": 4},
                    "select": ["ENTITY_ID", "RQ_INN"],
                    "order": {"ID": "ASC"},
                },
            )
        except Exception as exc:
            logger.warning("Company requisites fetch failed: %s", exc)
            return {}

        inn_map: Dict[str, str] = {}
        for requisite in requisites:
            entity_id = self._clean_str(requisite.get("ENTITY_ID") or requisite.get("entityId"))
            inn = self._clean_str(requisite.get("RQ_INN") or requisite.get("rqInn"))
            if entity_id and inn and entity_id not in inn_map:
                inn_map[entity_id] = inn
        return inn_map

    def _get_revenue_leakage_rows(self, limit: int = 5) -> List[Dict[str, Any]]:
        recent_from = timezone.localdate() - timedelta(days=90)
        queryset = TimesheetItem.objects.filter(bitrix24_account=self.account, date_reflection__gte=datetime.combine(recent_from, datetime.min.time(), tzinfo=timezone.get_current_timezone()))

        archived_cards = get_project_card_queryset(self.account).filter(is_archived=True)
        archived_project_item_ids = archived_cards.exclude(project_item_id__isnull=True).exclude(project_item_id="").values("project_item_id")
        archived_project_ids = archived_cards.exclude(project_id__isnull=True).exclude(project_id="").values("project_id")
        archived_project_names = archived_cards.exclude(project_name__isnull=True).exclude(project_name="").values("project_name")
        queryset = queryset.exclude(project_item_id__in=archived_project_item_ids).exclude(project_id__in=archived_project_ids).exclude(project_title__in=archived_project_names)

        cards = get_project_card_queryset(self.account).exclude(project_name__isnull=True).exclude(project_name="")
        project_name_by_item = {
            self._clean_str(card.project_item_id): card.project_name
            for card in cards
            if self._clean_str(card.project_item_id)
        }
        project_name_by_group = {
            self._clean_str(card.project_id): card.project_name
            for card in cards
            if self._clean_str(card.project_id)
        }

        rows = list(
            queryset.values("project_item_id", "project_id", "project_title").annotate(
                total_hours=Sum("hours"),
                non_billable_hours=Sum(
                    Case(
                        When(is_billable=False, then=F("hours")),
                        default=Value(0.0),
                        output_field=FloatField(),
                    )
                ),
                billable_hours=Sum(
                    Case(
                        When(is_billable=True, then=F("hours")),
                        default=Value(0.0),
                        output_field=FloatField(),
                    )
                ),
            )
        )

        normalized: List[Dict[str, Any]] = []
        for row in rows:
            project_item_id = self._clean_str(row.get("project_item_id"))
            project_id = self._clean_str(row.get("project_id"))
            project_name = (
                (project_name_by_item.get(project_item_id) if project_item_id else None)
                or (project_name_by_group.get(project_id) if project_id else None)
                or row.get("project_title")
                or f"Проект {project_id or project_item_id or 'без названия'}"
            )
            total_hours = float(row.get("total_hours") or 0.0)
            non_billable_hours = float(row.get("non_billable_hours") or 0.0)
            if total_hours <= 0 or non_billable_hours <= 0:
                continue
            normalized.append(
                {
                    "project_id": project_id,
                    "project_item_id": project_item_id,
                    "project_name": project_name,
                    "total_hours": round(total_hours, 2),
                    "billable_hours": round(float(row.get("billable_hours") or 0.0), 2),
                    "non_billable_hours": round(non_billable_hours, 2),
                    "loss_rate": round((non_billable_hours / total_hours) * 100.0, 1),
                }
            )

        normalized.sort(key=lambda item: (item["non_billable_hours"], item["loss_rate"]), reverse=True)
        return normalized[:limit]

    def _sync_project_card_to_project_spa(self, card: ProjectCard) -> Optional[str]:
        config = self._load_config()
        try:
            entity_type_id = int(config.get("project_sp_entity_type_id") or 0)
        except (TypeError, ValueError):
            entity_type_id = 0
        mapping = config.get("project_fields_mapping") or {}
        if not entity_type_id or not isinstance(mapping, dict) or not mapping:
            return None

        if not card.project_item_id:
            return (
                f"Карточка проекта «{card.project_name}» сохранена локально, "
                "но не имеет project_item_id для синхронизации в Project SPA."
            )

        fields = self._build_project_spa_update_fields(card, mapping)
        if not fields:
            return None

        try:
            self.client._bitrix_token.call_method(
                "crm.item.update",
                {
                    "entityTypeId": entity_type_id,
                    "id": self._to_bitrix_id(card.project_item_id),
                    "fields": fields,
                },
            )
        except Exception as exc:
            logger.warning("Project SPA update failed for project %s (item %s): %s", card.project_id, card.project_item_id, exc)
            return f"Изменения сохранены локально, но не синхронизированы в Project SPA: {exc}"

        return None

    def _build_project_spa_update_fields(self, card: ProjectCard, mapping: Dict[str, Any]) -> Dict[str, Any]:
        fields: Dict[str, Any] = {}
        stage_lookup = self.get_project_stage_lookup()

        self._assign_mapped_spa_field(fields, mapping, "title", card.project_name)
        self._assign_mapped_spa_field(fields, mapping, "bitrix_group_id", self._to_bitrix_id(card.project_id))
        stage_mapping_key = self._resolve_stage_mapping_key(mapping)
        if stage_mapping_key:
            stage_source_value = card.manual_stage if card.stage_source == "auto" else (card.stage or card.manual_stage)
            mapped_stage_value = self.resolve_project_stage_id(stage_source_value, stage_lookup)
            self._assign_mapped_spa_field(fields, mapping, stage_mapping_key, mapped_stage_value)
        self._assign_mapped_spa_field(fields, mapping, "is_support", "Y" if card.is_support else "N")
        self._assign_mapped_spa_field(fields, mapping, "project_hours_budget", card.project_hours_budget)
        self._assign_mapped_spa_field(fields, mapping, "project_type", card.project_type)
        self._assign_mapped_spa_field(fields, mapping, "budget_mode", card.budget_mode)
        self._assign_mapped_spa_field(fields, mapping, "planned_budget_amount", card.planned_budget_amount)
        self._assign_mapped_spa_field(fields, mapping, "hourly_rate", card.hourly_rate)
        self._assign_mapped_spa_field(fields, mapping, "curator_id", self._to_bitrix_id(card.curator_user_id))
        self._assign_mapped_spa_field(fields, mapping, "company_id", self._to_bitrix_id(card.company_id))
        self._assign_mapped_spa_field(fields, mapping, "our_legal_entity_id", self._to_bitrix_id(card.our_legal_entity_id))
        self._assign_mapped_spa_field(fields, mapping, "start_date", card.project_start_date.isoformat() if card.project_start_date else None)
        self._assign_mapped_spa_field(fields, mapping, "finish_date", card.project_end_date.isoformat() if card.project_end_date else None)
        self._assign_mapped_spa_field(fields, mapping, "is_archived", "Y" if card.is_archived else "N")

        return fields

    @staticmethod
    def _assign_mapped_spa_field(target: Dict[str, Any], mapping: Dict[str, Any], mapping_key: str, value: Any) -> None:
        field_code = str(mapping.get(mapping_key) or "").strip() if isinstance(mapping, dict) else ""
        if not field_code or value in (None, ""):
            return
        target[field_code] = value

    @staticmethod
    def _resolve_stage_mapping_key(mapping: Dict[str, Any]) -> Optional[str]:
        if not isinstance(mapping, dict):
            return None
        for key in ("stage_id", "stage", "effective_stage", "manual_stage"):
            if str(mapping.get(key) or "").strip():
                return key
        return None

    @staticmethod
    def _to_bitrix_id(value: Any) -> Any:
        value_str = ProjectCardService._clean_str(value)
        if not value_str:
            return None
        return int(value_str) if value_str.isdigit() else value_str

    @staticmethod
    def _merge_warning(primary: Optional[str], secondary: Optional[str]) -> Optional[str]:
        if primary and secondary:
            return f"{primary} {secondary}".strip()
        return primary or secondary

    def _get_card(self, project_id: str) -> ProjectCard:
        return ProjectCard.objects.get(bitrix24_account=self.account, project_id=str(project_id))

    def _fetch_paginated(self, method: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        start = 0
        items: List[Dict[str, Any]] = []

        while True:
            request_params = dict(params)
            request_params["start"] = start
            response = self.client._bitrix_token.call_method(method, request_params)
            batch, next_value = _extract_items_from_response(response)
            if not batch:
                break
            items.extend(batch)
            if next_value is None or int(next_value) <= start:
                break
            start = int(next_value)

        return items

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
    def _to_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "y", "yes", "on"}

    @staticmethod
    def _parse_date(value: Any) -> Optional[date]:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value)[:10])
        except (TypeError, ValueError):
            return None
