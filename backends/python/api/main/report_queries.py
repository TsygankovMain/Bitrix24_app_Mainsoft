from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from django.db.models import Q
from django.utils import timezone

from .employee_ids import build_employee_id_aliases
from .models import Bitrix24Account, TimesheetItem
from .project_board_shared import get_project_card_queryset
from .tenant_scoping import scope_to_tenant


TREE_REPORT_FIELDS = (
    "employee_id",
    "project_item_id",
    "project_id",
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
    queryset = TimesheetItem.objects.filter(**scope_to_tenant(account))

    date_from = _parse_date_value(params.get("date_from"))
    date_to = _parse_date_value(params.get("date_to"))
    if date_from:
        queryset = queryset.filter(date_reflection__gte=_day_start(date_from))
    if date_to:
        queryset = queryset.filter(date_reflection__lt=_next_day_start(date_to))

    archived_cards = get_project_card_queryset(account).filter(is_archived=True)
    archived_rows = archived_cards.values_list("project_item_id", "project_id", "project_name")
    archived_item_ids = set()
    archived_ids = set()
    archived_names = set()
    for item_id, group_id, name in archived_rows:
        if item_id:
            archived_item_ids.add(item_id)
        if group_id:
            archived_ids.add(group_id)
        if name:
            archived_names.add(name)
    queryset = queryset.exclude(
        Q(project_item_id__in=archived_item_ids)
        | Q(project_id__in=archived_ids)
        | Q(project_title__in=archived_names)
    )

    employee_ids = _normalize_multi_value(params.get("employee_ids") or params.get("employee_ids[]"))
    employee_filter_ids = build_employee_id_aliases(employee_ids)
    employee_mode = str(params.get("employee_mode") or "include")
    if employee_filter_ids:
        if employee_mode == "exclude":
            queryset = queryset.exclude(employee_id__in=employee_filter_ids)
        else:
            queryset = queryset.filter(employee_id__in=employee_filter_ids)

    project_ids = _normalize_multi_value(params.get("project_ids") or params.get("project_ids[]"))
    project_mode = str(params.get("project_mode") or "include")
    if project_ids:
        project_q = Q(project_item_id__in=project_ids) | Q(project_id__in=project_ids) | Q(project_title__in=project_ids)
        if project_mode == "exclude":
            queryset = queryset.exclude(project_q)
        else:
            queryset = queryset.filter(project_q)

    return queryset


def materialize_rows(queryset, fields: Sequence[str]) -> List[Dict[str, Any]]:
    return list(queryset.values(*fields).iterator())


def build_project_title_lookups(account: Bitrix24Account) -> tuple[Dict[str, str], Dict[str, str]]:
    rows = (
        get_project_card_queryset(account)
        .exclude(project_name__isnull=True)
        .exclude(project_name="")
        .values_list("project_item_id", "project_id", "project_name")
    )
    by_item: Dict[str, str] = {}
    by_group: Dict[str, str] = {}
    for project_item_id, project_id, project_name in rows:
        if project_item_id:
            by_item[str(project_item_id).strip()] = project_name
        if project_id:
            by_group[str(project_id).strip()] = project_name
    return by_item, by_group


def resolve_project_name_for_row(
    row: Mapping[str, Any],
    project_name_by_item: Optional[Mapping[str, str]] = None,
    project_name_by_group: Optional[Mapping[str, str]] = None,
) -> str:
    project_item_id = str(row.get("project_item_id") or "").strip()
    if project_item_id and project_name_by_item:
        mapped = project_name_by_item.get(project_item_id)
        if mapped:
            return mapped

    project_id = str(row.get("project_id") or "").strip()
    if project_id and project_name_by_group:
        mapped = project_name_by_group.get(project_id)
        if mapped:
            return mapped

    fallback_name = str(row.get("project_title") or "").strip()
    if fallback_name:
        return fallback_name
    return "Не определён"


def build_tree_report_items(
    rows: Iterable[Dict[str, Any]],
    include_task_id: bool = False,
    project_name_by_item: Optional[Mapping[str, str]] = None,
    project_name_by_group: Optional[Mapping[str, str]] = None,
) -> List[Dict[str, Any]]:
    items = []
    for row in rows:
        item = {
            "sotrudnik_id": row["employee_id"],
            "project_name": resolve_project_name_for_row(row, project_name_by_item, project_name_by_group),
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
