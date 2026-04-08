from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from django.db.models import Q
from django.utils import timezone

from .models import Bitrix24Account, TimesheetItem
from .project_board_shared import get_project_card_queryset


TREE_REPORT_FIELDS = (
    "employee_id",
    "project_title",
    "hours",
    "task_hierarchy_ids",
    "task_hierarchy_titles",
    "is_billable",
    "description",
    "date_reflection",
    "bitrix_id",
    "task_id",
)


def build_filtered_timesheet_queryset(account: Bitrix24Account, params: Mapping[str, Any]):
    queryset = TimesheetItem.objects.filter(bitrix24_account=account)

    date_from = _parse_date_value(params.get("date_from"))
    date_to = _parse_date_value(params.get("date_to"))
    if date_from:
        queryset = queryset.filter(date_reflection__gte=_day_start(date_from))
    if date_to:
        queryset = queryset.filter(date_reflection__lt=_next_day_start(date_to))

    archived_cards = get_project_card_queryset(account).filter(is_archived=True)
    archived_ids = archived_cards.exclude(project_id__isnull=True).exclude(project_id="").values("project_id")
    archived_names = archived_cards.exclude(project_name__isnull=True).exclude(project_name="").values("project_name")
    queryset = queryset.exclude(Q(project_id__in=archived_ids) | Q(project_title__in=archived_names))

    employee_ids = _normalize_multi_value(params.get("employee_ids") or params.get("employee_ids[]"))
    employee_mode = str(params.get("employee_mode") or "include")
    if employee_ids:
        if employee_mode == "exclude":
            queryset = queryset.exclude(employee_id__in=employee_ids)
        else:
            queryset = queryset.filter(employee_id__in=employee_ids)

    project_ids = _normalize_multi_value(params.get("project_ids") or params.get("project_ids[]"))
    project_mode = str(params.get("project_mode") or "include")
    if project_ids:
        project_q = Q(project_id__in=project_ids) | Q(project_title__in=project_ids)
        if project_mode == "exclude":
            queryset = queryset.exclude(project_q)
        else:
            queryset = queryset.filter(project_q)

    return queryset


def materialize_rows(queryset, fields: Sequence[str]) -> List[Dict[str, Any]]:
    return list(queryset.values(*fields).iterator())


def build_tree_report_items(rows: Iterable[Dict[str, Any]], include_task_id: bool = False) -> List[Dict[str, Any]]:
    items = []
    for row in rows:
        item = {
            "sotrudnik_id": row["employee_id"],
            "project_name": row["project_title"],
            "kolichestvo_chasov": row["hours"],
            "id_zadach_ierarhiya": row["task_hierarchy_ids"],
            "title_zadach_ierarhiya": row["task_hierarchy_titles"],
            "uchitivaem": row["is_billable"],
            "opisanie": row["description"],
            "data": row["date_reflection"].isoformat() if row.get("date_reflection") else None,
            "nazvanie_zadachi": row["task_hierarchy_titles"][-1] if row.get("task_hierarchy_titles") else "No Title",
            "id_elem": row["bitrix_id"],
        }
        if include_task_id:
            item["id_zadachi"] = row["task_id"]
        items.append(item)
    return items


def _normalize_multi_value(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw_values = value
    else:
        raw_values = [value]
    normalized = []
    for item in raw_values:
        item_str = str(item).strip()
        if item_str:
            normalized.append(item_str)
    return normalized


def _parse_date_value(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _day_start(day_value: date) -> datetime:
    return timezone.make_aware(datetime.combine(day_value, time.min), timezone.get_current_timezone())


def _next_day_start(day_value: date) -> datetime:
    return _day_start(day_value + timedelta(days=1))
