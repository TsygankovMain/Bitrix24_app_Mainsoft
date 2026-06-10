"""Backfill FK portal на данных (этап 1 перестройки мультитенантности).

Проставляет TimesheetItem.portal / ProjectCard.portal от их bitrix24_account.portal.
Идемпотентно (обрабатывает только portal IS NULL), батчами (память/блокировки на
103k+ записях). Запускается командой backfill_portal_links, НЕ миграцией.
"""
import logging
from typing import Dict

from django.db import transaction

from .models import TimesheetItem, ProjectCard

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 2000


def _backfill_model(model, batch_size: int) -> Dict[str, int]:
    linked = 0
    unlinked = 0
    while True:
        # Берём пачку незаполненных pk + portal их аккаунта.
        rows = list(
            model.objects
            .filter(portal__isnull=True)
            .values_list("pk", "bitrix24_account__portal_id")[:batch_size]
        )
        if not rows:
            break

        to_link = {pk: portal_id for pk, portal_id in rows if portal_id is not None}
        unlinkable = [pk for pk, portal_id in rows if portal_id is None]

        if to_link:
            # Группируем по portal_id, чтобы делать пачкой UPDATE ... WHERE pk IN (...).
            by_portal: Dict[str, list] = {}
            for pk, portal_id in to_link.items():
                by_portal.setdefault(portal_id, []).append(pk)
            with transaction.atomic():
                for portal_id, pks in by_portal.items():
                    model.objects.filter(pk__in=pks).update(portal_id=portal_id)
            linked += len(to_link)

        if unlinkable:
            unlinked += len(unlinkable)
            # Защита от бесконечного цикла: если в пачке ТОЛЬКО непривязываемые,
            # дальнейшие выборки вернут те же записи (portal остаётся NULL).
            if not to_link:
                break

    return {"linked": linked, "unlinked": unlinked}


def backfill_portal_links(batch_size: int = DEFAULT_BATCH_SIZE) -> Dict[str, int]:
    ts = _backfill_model(TimesheetItem, batch_size)
    cards = _backfill_model(ProjectCard, batch_size)
    report = {
        "timesheets_linked": ts["linked"],
        "timesheets_unlinked": ts["unlinked"],
        "cards_linked": cards["linked"],
        "cards_unlinked": cards["unlinked"],
    }
    logger.info("backfill_portal_links report: %s", report)
    return report
