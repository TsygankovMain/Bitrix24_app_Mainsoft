from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from b24pysdk import Client
from django.core.cache import cache

from .configuration_service import ConfigurationService
from .models import Bitrix24Account
from .project_board_shared import BITRIX_REFERENCE_CACHE_TTL, build_account_cache_key


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


class FinanceOperationService:
    DEFAULT_CURRENCY = "RUB"
    SOURCE_DEAL_EMBED = "deal_embed"
    SOURCE_MANUAL = "manual"

    def __init__(self, client: Client, account: Bitrix24Account):
        self.client = client
        self.account = account
        self._config_service = ConfigurationService(client, account)
        self._config = self._config_service.get_configuration_sync()
        self._entity_type_id, self._mapping = self._resolve_finance_config(self._config)

    @property
    def entity_type_id(self) -> int:
        return self._entity_type_id

    @property
    def mapping(self) -> Dict[str, str]:
        return dict(self._mapping)

    def is_configured(self) -> bool:
        return self.entity_type_id > 0 and bool(self.mapping)

    def list_operations(
        self,
        *,
        project_item_id: Optional[str] = None,
        deal_id: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        self._ensure_configured()
        limit = max(1, min(int(limit or 20), 100))

        filter_payload: Dict[str, Any] = {}
        project_item_field = self._mapping.get("project_item_id")
        deal_id_field = self._mapping.get("deal_id")

        normalized_project_item_id = self._clean_str(project_item_id)
        normalized_deal_id = self._clean_str(deal_id)
        if normalized_project_item_id and project_item_field:
            filter_payload[project_item_field] = self._to_bitrix_scalar(normalized_project_item_id)
        if normalized_deal_id and deal_id_field:
            filter_payload[deal_id_field] = self._to_bitrix_scalar(normalized_deal_id)

        select_fields = ["id", "title", "createdTime", "updatedTime", "*", "UF_*"]
        rows = self._fetch_paginated(
            "crm.item.list",
            {
                "entityTypeId": self.entity_type_id,
                "select": select_fields,
                "order": {"id": "DESC"},
                "filter": filter_payload,
            },
            max_items=limit,
        )
        operations = [self._normalize_operation(row) for row in rows]
        operations.sort(
            key=lambda row: (
                str(row.get("operation_date") or ""),
                str(row.get("id") or ""),
            ),
            reverse=True,
        )
        return {
            "operations": operations[:limit],
            "count": len(operations[:limit]),
            "entity_type_id": self.entity_type_id,
        }

    def create_operation(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_configured()
        normalized_payload = self._normalize_create_payload(payload)
        duplicate = self._find_duplicate(normalized_payload)
        if duplicate is not None:
            return {
                "status": "duplicate",
                "operation": duplicate,
                "idempotency_key": normalized_payload["idempotency_key"],
            }

        fields = self._build_create_fields(normalized_payload)
        response = self.client._bitrix_token.call_method(
            "crm.item.add",
            {
                "entityTypeId": self.entity_type_id,
                "fields": fields,
            },
        )
        created_item_id = self._extract_created_item_id(response)
        if not created_item_id:
            raise RuntimeError("Finance operation created, but API did not return item id.")

        item_response = self.client._bitrix_token.call_method(
            "crm.item.get",
            {
                "entityTypeId": self.entity_type_id,
                "id": self._to_bitrix_scalar(created_item_id),
            },
        )
        item_data = item_response.get("result", {})
        if isinstance(item_data, dict):
            item_data = item_data.get("item") or item_data.get("result") or item_data
        if not isinstance(item_data, dict):
            item_data = {"id": created_item_id}

        self.invalidate_cache()
        return {
            "status": "created",
            "operation": self._normalize_operation(item_data),
            "idempotency_key": normalized_payload["idempotency_key"],
        }

    def get_sums_by_project_item_id(self) -> Dict[str, Dict[str, float]]:
        if not self.is_configured():
            return {}
        cache_key = build_account_cache_key(self.account, "finance-sums-by-project-item")
        cached = cache.get(cache_key)
        if isinstance(cached, dict):
            return cached

        project_item_field = self.mapping.get("project_item_id")
        amount_field = self.mapping.get("amount")
        if not project_item_field or not amount_field:
            return {}

        rows = self._fetch_paginated(
            "crm.item.list",
            {
                "entityTypeId": self.entity_type_id,
                "select": ["id", "createdTime", "updatedTime", project_item_field, amount_field, *(list(self._collect_optional_select_fields()))],
                "order": {"id": "DESC"},
            },
            max_items=2000,
        )

        result: Dict[str, Dict[str, float]] = {}
        for row in rows:
            operation = self._normalize_operation(row)
            project_item_id = self._clean_str(operation.get("project_item_id"))
            if not project_item_id:
                continue
            bucket = result.setdefault(project_item_id, {"income": 0.0, "expense": 0.0})
            operation_type = str(operation.get("operation_type") or "").strip().lower()
            amount = self._to_float(operation.get("amount"))
            if amount <= 0:
                continue
            if operation_type.startswith("exp"):
                bucket["expense"] = round(bucket["expense"] + amount, 2)
            else:
                bucket["income"] = round(bucket["income"] + amount, 2)

        cache.set(cache_key, result, BITRIX_REFERENCE_CACHE_TTL)
        return result

    def get_recent_operations_by_project_item_id(self, project_item_id: Optional[str], limit: int = 5) -> List[Dict[str, Any]]:
        normalized = self._clean_str(project_item_id)
        if not normalized:
            return []
        payload = self.list_operations(project_item_id=normalized, limit=limit)
        return payload.get("operations", [])

    def invalidate_cache(self) -> None:
        cache.delete(build_account_cache_key(self.account, "finance-sums-by-project-item"))

    def _find_duplicate(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        query = self.list_operations(
            project_item_id=payload["project_item_id"],
            deal_id=payload.get("deal_id"),
            limit=50,
        )
        for row in query.get("operations", []):
            normalized_existing_key = self._build_idempotency_key(
                project_item_id=row.get("project_item_id"),
                deal_id=row.get("deal_id"),
                operation_type=row.get("operation_type"),
                amount=row.get("amount"),
                operation_date=row.get("operation_date"),
                source=row.get("source"),
                comment=row.get("comment"),
            )
            if normalized_existing_key == payload["idempotency_key"]:
                return row
        return None

    def _build_create_fields(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        fields: Dict[str, Any] = {}
        assign = self._assign_mapped
        assign(fields, "project_item_id", self._to_bitrix_scalar(payload["project_item_id"]))
        assign(fields, "operation_type", payload["operation_type"])
        assign(fields, "amount", payload["amount"])
        assign(fields, "currency", payload["currency"])
        assign(fields, "operation_date", payload["operation_date"])
        assign(fields, "source", payload["source"])
        assign(fields, "deal_id", self._to_bitrix_scalar(payload.get("deal_id")))
        assign(fields, "comment", payload.get("comment"))
        assign(fields, "responsible_user_id", self._to_bitrix_scalar(payload.get("responsible_user_id")))
        return fields

    def _normalize_create_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        project_item_id = self._clean_str(payload.get("project_item_id"))
        operation_type = self._normalize_operation_type(payload.get("operation_type"))
        amount = self._to_float(payload.get("amount"))
        if amount <= 0:
            raise ValueError("amount must be greater than zero")
        operation_date = self._normalize_date(payload.get("operation_date"))
        currency = self._clean_str(payload.get("currency")) or self.DEFAULT_CURRENCY
        source = self._clean_str(payload.get("source")) or self.SOURCE_DEAL_EMBED
        deal_id = self._clean_str(payload.get("deal_id"))
        comment = self._clean_str(payload.get("comment"))
        responsible_user_id = self._clean_str(payload.get("responsible_user_id"))

        if not project_item_id:
            raise ValueError("project_item_id is required")
        if not operation_type:
            raise ValueError("operation_type is required")
        if not operation_date:
            raise ValueError("operation_date is required")
        if not deal_id and source != self.SOURCE_MANUAL:
            raise ValueError("deal_id is required for non-manual finance operations")

        return {
            "project_item_id": project_item_id,
            "operation_type": operation_type,
            "amount": round(amount, 2),
            "currency": currency,
            "operation_date": operation_date,
            "source": source,
            "deal_id": deal_id,
            "comment": comment,
            "responsible_user_id": responsible_user_id,
            "idempotency_key": self._build_idempotency_key(
                project_item_id=project_item_id,
                deal_id=deal_id,
                operation_type=operation_type,
                amount=round(amount, 2),
                operation_date=operation_date,
                source=source,
                comment=comment,
            ),
        }

    def _normalize_operation(self, row: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(row, dict):
            row = {}
        mapped_value = lambda key: self._extract_scalar(self._get_mapped_value(row, key))
        amount = self._to_float(mapped_value("amount"))
        operation_type = self._normalize_operation_type(mapped_value("operation_type"))
        return {
            "id": self._clean_str(row.get("id") or row.get("ID")),
            "title": self._clean_str(row.get("title") or row.get("TITLE")),
            "project_item_id": self._clean_str(mapped_value("project_item_id")),
            "deal_id": self._clean_str(mapped_value("deal_id")),
            "operation_type": operation_type or self._normalize_operation_type(
                self._clean_str(row.get("stageId") or row.get("STAGE_ID"))
            ),
            "amount": round(amount, 2),
            "currency": self._clean_str(mapped_value("currency")) or self.DEFAULT_CURRENCY,
            "operation_date": self._normalize_date(mapped_value("operation_date")),
            "source": self._clean_str(mapped_value("source")) or self.SOURCE_DEAL_EMBED,
            "comment": self._clean_str(mapped_value("comment")),
            "responsible_user_id": self._clean_str(mapped_value("responsible_user_id")),
            "created_at": self._clean_str(row.get("createdTime") or row.get("createdAt") or row.get("CREATED_TIME")),
            "updated_at": self._clean_str(row.get("updatedTime") or row.get("updatedAt") or row.get("UPDATED_TIME")),
            "raw": row,
        }

    def _fetch_paginated(self, method: str, params: Dict[str, Any], *, max_items: int = 0) -> List[Dict[str, Any]]:
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
            if max_items and len(items) >= max_items:
                break
            if next_value is None or int(next_value) <= start:
                break
            start = int(next_value)
        return items[:max_items] if max_items else items

    def _get_mapped_value(self, item: Dict[str, Any], mapping_key: str) -> Any:
        field_code = self.mapping.get(mapping_key)
        if field_code and field_code in item:
            return item.get(field_code)
        # legacy/fallback aliases
        aliases = {
            "project_item_id": ["UF_CRM_PROJECT_ITEM_ID", "ufCrmProjectItemId"],
            "operation_type": ["UF_CRM_OPERATION_TYPE", "ufCrmOperationType", "stageId", "STAGE_ID"],
            "amount": ["UF_CRM_AMOUNT", "ufCrmAmount"],
            "currency": ["UF_CRM_CURRENCY", "ufCrmCurrency"],
            "operation_date": ["UF_CRM_OPERATION_DATE", "ufCrmOperationDate"],
            "source": ["UF_CRM_SOURCE", "ufCrmSource"],
            "deal_id": ["UF_CRM_DEAL_ID", "ufCrmDealId"],
            "comment": ["UF_CRM_COMMENT", "ufCrmComment"],
            "responsible_user_id": ["UF_CRM_RESPONSIBLE_USER_ID", "ufCrmResponsibleUserId", "assignedById", "ASSIGNED_BY_ID"],
        }.get(mapping_key, [])
        for alias in aliases:
            if alias in item:
                return item.get(alias)
        return None

    def _assign_mapped(self, fields: Dict[str, Any], mapping_key: str, value: Any) -> None:
        field_code = self.mapping.get(mapping_key)
        if not field_code or value in (None, ""):
            return
        fields[field_code] = value

    @staticmethod
    def _extract_scalar(value: Any) -> Optional[str]:
        if isinstance(value, list):
            for entry in value:
                normalized = FinanceOperationService._extract_scalar(entry)
                if normalized:
                    return normalized
            return None
        if isinstance(value, dict):
            for key in ("id", "ID", "value", "VALUE"):
                nested = value.get(key)
                normalized = FinanceOperationService._extract_scalar(nested)
                if normalized:
                    return normalized
            return None
        return FinanceOperationService._clean_str(value)

    @staticmethod
    def _normalize_operation_type(value: Any) -> Optional[str]:
        normalized = FinanceOperationService._clean_str(value)
        if not normalized:
            return None
        lowered = normalized.lower()
        if lowered in {"income", "in", "поступление", "доход"}:
            return "income"
        if lowered in {"expense", "out", "расход", "затрата"}:
            return "expense"
        return lowered

    @staticmethod
    def _normalize_date(value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        raw = str(value).strip()
        if len(raw) >= 10:
            return raw[:10]
        return None

    @staticmethod
    def _clean_str(value: Any) -> Optional[str]:
        if value is None:
            return None
        value_str = str(value).strip()
        return value_str or None

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_bitrix_scalar(value: Any) -> Any:
        normalized = FinanceOperationService._clean_str(value)
        if not normalized:
            return None
        return int(normalized) if normalized.isdigit() else normalized

    @staticmethod
    def _extract_created_item_id(response: Dict[str, Any]) -> Optional[str]:
        result = response.get("result")
        if isinstance(result, (str, int)):
            return str(result)
        if isinstance(result, dict):
            for key in ("itemId", "id", "ID"):
                if key in result and result.get(key) not in (None, ""):
                    return str(result.get(key))
            nested_item = result.get("item")
            if isinstance(nested_item, dict):
                nested_id = nested_item.get("id") or nested_item.get("ID")
                if nested_id not in (None, ""):
                    return str(nested_id)
        return None

    @staticmethod
    def _resolve_finance_config(config: Dict[str, Any]) -> Tuple[int, Dict[str, str]]:
        try:
            entity_type_id = int(config.get("finance_sp_entity_type_id") or 0)
        except (TypeError, ValueError):
            entity_type_id = 0
        mapping = config.get("finance_fields_mapping") or {}
        if not isinstance(mapping, dict):
            mapping = {}
        normalized_mapping = {
            str(key).strip(): str(value).strip()
            for key, value in mapping.items()
            if str(key).strip() and str(value).strip()
        }
        return entity_type_id, normalized_mapping

    def _ensure_configured(self) -> None:
        if not self.entity_type_id:
            raise ValueError("Finance SPA is not configured")
        if not self.mapping:
            raise ValueError("Finance fields mapping is empty")
        required_keys = ("project_item_id", "operation_type", "amount", "operation_date", "source")
        missing = [key for key in required_keys if not self.mapping.get(key)]
        if missing:
            raise ValueError(f"Finance mapping is incomplete: {', '.join(missing)}")

    def _collect_optional_select_fields(self) -> set:
        keys = ("operation_type", "currency", "operation_date", "source", "deal_id", "comment", "responsible_user_id")
        return {self.mapping.get(key) for key in keys if self.mapping.get(key)}

    @staticmethod
    def _build_idempotency_key(
        *,
        project_item_id: Any,
        deal_id: Any,
        operation_type: Any,
        amount: Any,
        operation_date: Any,
        source: Any,
        comment: Any,
    ) -> str:
        normalized = "|".join(
            [
                str(FinanceOperationService._clean_str(project_item_id) or ""),
                str(FinanceOperationService._clean_str(deal_id) or ""),
                str(FinanceOperationService._normalize_operation_type(operation_type) or ""),
                f"{FinanceOperationService._to_float(amount):.2f}",
                str(FinanceOperationService._normalize_date(operation_date) or ""),
                str(FinanceOperationService._clean_str(source) or ""),
                str(FinanceOperationService._clean_str(comment) or ""),
            ]
        )
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
