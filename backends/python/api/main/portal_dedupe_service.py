"""Дедупликация данных портала (этап 2 перестройки мультитенантности).

В пределах Portal схлопывает дубли TimesheetItem по (portal, bitrix_id) и
ProjectCard по (portal, project_id) и (portal, project_item_id), оставляя
«правильную» копию: мастер-аккаунт портала, иначе свежайшую (max updated_at,
tie-break по b24_user_id). По умолчанию DRY-RUN: только считает и печатает,
НИЧЕГО не удаляет. Реальное удаление — только при apply=True.

ВАЖНО: запускать ПОСЛЕ backfill_portal_links (4.1). До включения portal-
уникальности (этап 4, Часть B) дубли ОБЯЗАНЫ быть устранены — иначе
уникальный индекс упадёт. Команда, НЕ миграция.
"""
import logging
from collections import defaultdict
from typing import Any, Dict, List, Tuple

from django.db import transaction

from .models import TimesheetItem, ProjectCard

logger = logging.getLogger(__name__)


def _master_account_ids() -> set:
    from .models import Bitrix24Account
    return set(
        Bitrix24Account.objects
        .filter(is_master_account=True)
        .values_list("pk", flat=True)
    )


def _backfill_incomplete() -> bool:
    """True, если есть записи с portal=NULL у аккаунта, у которого portal есть."""
    ts_pending = TimesheetItem.objects.filter(
        portal__isnull=True, bitrix24_account__portal__isnull=False
    ).exists()
    card_pending = ProjectCard.objects.filter(
        portal__isnull=True, bitrix24_account__portal__isnull=False
    ).exists()
    return ts_pending or card_pending


def _pick_keeper(rows: List[Tuple], master_ids: set) -> Any:
    """rows: список кортежей (pk, account_pk, sort_key, b24_user_id).
    Возвращает pk копии, которую ОСТАВЛЯЕМ."""
    # 1) мастер-аккаунт.
    masters = [r for r in rows if r[1] in master_ids]
    pool = masters or rows
    # 2) свежайшая (sort_key), tie-break по b24_user_id (оба — больше=лучше).
    pool_sorted = sorted(pool, key=lambda r: (r[2] or 0, r[3] or 0), reverse=True)
    return pool_sorted[0][0]


def _dedupe_timesheets(apply: bool, master_ids: set) -> Dict[str, int]:
    # Группируем по (portal_id, bitrix_id).
    groups: Dict[Tuple, List[Tuple]] = defaultdict(list)
    qs = (
        TimesheetItem.objects
        .filter(portal__isnull=False)
        .values_list("pk", "bitrix24_account_id", "updated_at", "bitrix24_account__b24_user_id",
                     "portal_id", "bitrix_id")
    )
    for pk, acc_pk, updated_at, b24_user_id, portal_id, bitrix_id in qs.iterator(chunk_size=5000):
        ts = updated_at.timestamp() if updated_at else 0
        groups[(portal_id, bitrix_id)].append((pk, acc_pk, ts, b24_user_id))

    to_delete: List[Any] = []
    dup_groups = 0
    for key, rows in groups.items():
        if len(rows) <= 1:
            continue
        dup_groups += 1
        keeper = _pick_keeper(rows, master_ids)
        to_delete.extend(r[0] for r in rows if r[0] != keeper)

    if apply and to_delete:
        with transaction.atomic():
            # Батчами по 5000 pk.
            for i in range(0, len(to_delete), 5000):
                TimesheetItem.objects.filter(pk__in=to_delete[i:i + 5000]).delete()

    return {"duplicate_groups": dup_groups, "rows_to_delete": len(to_delete)}


def _dedupe_cards(apply: bool, master_ids: set) -> Dict[str, int]:
    dup_groups = 0
    to_delete: set = set()

    def _collect(group_field: str):
        nonlocal dup_groups
        groups: Dict[Tuple, List[Tuple]] = defaultdict(list)
        qs = (
            ProjectCard.objects
            .filter(portal__isnull=False)
            .exclude(**{f"{group_field}__isnull": True})
            .exclude(**{group_field: ""})
            .values_list("pk", "bitrix24_account_id", "updated_at",
                         "bitrix24_account__b24_user_id", "portal_id", group_field)
        )
        for pk, acc_pk, updated_at, b24_user_id, portal_id, gval in qs.iterator(chunk_size=5000):
            ts = updated_at.timestamp() if updated_at else 0
            groups[(portal_id, gval)].append((pk, acc_pk, ts, b24_user_id))
        for key, rows in groups.items():
            if len(rows) <= 1:
                continue
            dup_groups += 1
            keeper = _pick_keeper(rows, master_ids)
            for r in rows:
                if r[0] != keeper:
                    to_delete.add(r[0])

    _collect("project_id")
    _collect("project_item_id")

    if apply and to_delete:
        ids = list(to_delete)
        with transaction.atomic():
            for i in range(0, len(ids), 5000):
                ProjectCard.objects.filter(pk__in=ids[i:i + 5000]).delete()

    return {"duplicate_groups": dup_groups, "rows_to_delete": len(to_delete)}


def dedupe_portal_data(apply: bool = False) -> Dict[str, Any]:
    incomplete = _backfill_incomplete()
    if incomplete and apply:
        logger.warning("dedupe_portal_data: backfill incomplete, refusing to apply.")
        return {"applied": False, "backfill_incomplete": True,
                "timesheets": {"duplicate_groups": 0, "rows_to_delete": 0},
                "cards": {"duplicate_groups": 0, "rows_to_delete": 0}}

    master_ids = _master_account_ids()
    ts_report = _dedupe_timesheets(apply=apply, master_ids=master_ids)
    card_report = _dedupe_cards(apply=apply, master_ids=master_ids)

    report = {
        "applied": bool(apply) and not incomplete,
        "backfill_incomplete": incomplete,
        "timesheets": ts_report,
        "cards": card_report,
    }
    logger.info("dedupe_portal_data report (apply=%s): %s", apply, report)
    return report
