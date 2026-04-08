import logging
from typing import Any, Dict, List

from django.core.cache import cache
from django.db import connection

from .models import Bitrix24Account, ProjectCard, TimesheetItem


logger = logging.getLogger(__name__)

PROJECT_STAGE_NEW = "Новый"
PROJECT_STAGE_ESTIMATE = "В просчете"
PROJECT_STAGE_IN_WORK = "В работе"
PROJECT_STAGE_NO_WRITEOFF_30 = "Нет списаний 1 месяц"
PROJECT_STAGE_NO_WRITEOFF_90 = "Нет списаний 3 месяца"
PROJECT_STAGE_SUCCESS = "Успех"
PROJECT_STAGE_FAILED = "Провал"

PROJECT_MANUAL_STAGES = [
    PROJECT_STAGE_NEW,
    PROJECT_STAGE_ESTIMATE,
    PROJECT_STAGE_IN_WORK,
    PROJECT_STAGE_SUCCESS,
    PROJECT_STAGE_FAILED,
]

PROJECT_AUTO_STAGES = [
    PROJECT_STAGE_NO_WRITEOFF_30,
    PROJECT_STAGE_NO_WRITEOFF_90,
]

PROJECT_STAGE_ORDER = [
    PROJECT_STAGE_NEW,
    PROJECT_STAGE_ESTIMATE,
    PROJECT_STAGE_IN_WORK,
    PROJECT_STAGE_NO_WRITEOFF_30,
    PROJECT_STAGE_NO_WRITEOFF_90,
    PROJECT_STAGE_SUCCESS,
    PROJECT_STAGE_FAILED,
]

PROJECT_CARD_TABLE_NAME = ProjectCard._meta.db_table
PROJECT_CARD_SCHEMA_CACHE_KEY = "mainsoft:v2:project-card-schema-ready"
PROJECT_CARD_SCHEMA_TTL = 60
BITRIX_REFERENCE_CACHE_TTL = 60 * 30
PROJECT_BOARD_CACHE_TTL = 60 * 2
HOMEPAGE_CACHE_TTL = 60 * 2
FILTER_EMPLOYEES_CACHE_SUFFIX = "filter-employees-v3"


def build_account_cache_key(account: Bitrix24Account, suffix: str) -> str:
    return f"mainsoft:v2:{account.pk}:{suffix}"


def invalidate_account_cache(account: Bitrix24Account, suffixes: List[str]) -> None:
    for suffix in suffixes:
        try:
            cache.delete(build_account_cache_key(account, suffix))
        except Exception as exc:
            logger.warning("Cache delete failed for %s: %s", suffix, exc)


def invalidate_project_runtime_caches(account: Bitrix24Account) -> None:
    invalidate_account_cache(
        account,
        [
            "filter-employees",
            FILTER_EMPLOYEES_CACHE_SUFFIX,
            "filter-projects",
            "project-board",
            "project-board-meta",
            "project-board-companies",
            "project-board-legal-entities",
            "project-board-homepage",
        ],
    )


def ensure_project_card_schema(force_refresh: bool = False) -> bool:
    if not force_refresh:
        cached = cache.get(PROJECT_CARD_SCHEMA_CACHE_KEY)
        if isinstance(cached, bool):
            return cached

    try:
        is_available = PROJECT_CARD_TABLE_NAME in connection.introspection.table_names()
    except Exception as exc:
        logger.warning("ProjectCard schema check failed: %s", exc)
        is_available = False

    cache.set(PROJECT_CARD_SCHEMA_CACHE_KEY, is_available, PROJECT_CARD_SCHEMA_TTL)
    return is_available


def get_project_card_queryset(account: Bitrix24Account):
    if not ensure_project_card_schema():
        return ProjectCard.objects.none()
    return ProjectCard.objects.filter(bitrix24_account=account)


def build_local_project_groups(account: Bitrix24Account) -> List[Dict[str, Any]]:
    rows = (
        TimesheetItem.objects.filter(bitrix24_account=account)
        .exclude(project_id__isnull=True)
        .exclude(project_id="")
        .values("project_id", "project_title")
        .distinct()
    )

    items: List[Dict[str, Any]] = []
    seen_ids = set()

    for row in rows:
        project_id = str(row.get("project_id") or "").strip()
        project_name = str(row.get("project_title") or "").strip() or f"Проект {project_id}"
        if not project_id or project_id in seen_ids:
            continue
        seen_ids.add(project_id)
        items.append(
            {
                "ID": project_id,
                "NAME": project_name,
                "PROJECT": "Y",
                "CLOSED": "N",
            }
        )

    return items
