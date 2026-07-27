"""Фоновая синхронизация по расписанию (задача 3.6).

Запускается management-командой sync_all_portals из встроенного планировщика
(фоновый цикл в start.sh) или вручную. Для каждого портала (group by member_id)
берёт один представительный аккаунт (мастер, иначе первый активный), читает
его конфиг (app.option), и если автосинк включён — выполняет синк согласно
параметру scope:

- scope="project"  : полный синк проектов (ProjectSyncService.sync()), раз в 3 часа.
- scope="timesheet": инкрементальный синк трудозатрат (TimesheetSyncService.sync_all()
                     с окном date_from/date_to), фоновый цикл каждые 20 минут.
- scope="timesheet", full=True: полная сверка без окна дат (TimesheetSyncService.sync_all()
                     -> _sync_full), фоновый цикл раз в сутки — ловит удаления/пропуски,
                     которые инкремент не видит. Параметр `full` игнорируется при scope="project".

После успешного синка представительного аккаунта в ветке timesheet проставляется
account.last_timesheet_synced_at — тот же маркер, что ставит on-demand дозагрузка
на endpoint timesheet_sync (задача 2.2), чтобы индикатор «данные на ЧЧ:ММ» в отчёте
отражал и фоновые синки, а не только визиты пользователя.

Падение одного портала не прерывает остальные. Совместимо с advisory-lock из 2.2
(на Postgres лок берётся честно, на sqlite no-op).
"""

import logging
from datetime import timedelta
from typing import List

from django.utils import timezone

from .models import Bitrix24Account, SyncRun
from .configuration_service import ConfigurationService
from .project_sync_service import ProjectSyncService
from .timesheet_sync_service import TimesheetSyncService
# Под USE_PORTAL_SCOPING account_sync_lock ключуется по portal.pk (замок «по
# компании»), выбор субъекта — внутри замка по флагу; вызовы ниже не меняются.
from .utils.decorators.sync_lock import account_sync_lock, SyncLockBusy

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_DAYS = 7


def select_portal_accounts() -> List[Bitrix24Account]:
    """Один представитель на портал (member_id): мастер, иначе первый активный."""
    active = Bitrix24Account.objects.filter(status="active").order_by("member_id", "-is_master_account")
    seen = set()
    reps: List[Bitrix24Account] = []
    for acc in active:
        if not acc.member_id or acc.member_id in seen:
            continue
        seen.add(acc.member_id)
        reps.append(acc)
    return reps


def run_scheduled_sync(days: int = DEFAULT_WINDOW_DAYS, scope: str = "timesheet", full: bool = False) -> SyncRun:
    run = SyncRun.objects.create(scope=scope, status="running", window_days=days)

    now = timezone.now()
    date_to = now.date().isoformat()
    date_from = (now - timedelta(days=days)).date().isoformat()

    reps = select_portal_accounts()
    run.portals_total = len(reps)

    synced = 0
    items_total = 0
    errors: List[str] = []

    for account in reps:
        try:
            cfg_service = ConfigurationService(account.client, account)
            config = cfg_service.get_configuration_sync()

            if not config.get("auto_sync_enabled", True):
                logger.info("Auto-sync disabled for portal %s (account %s); skip.",
                            account.member_id, account.pk)
                continue

            if scope == "project":
                try:
                    with account_sync_lock(account, scope="project"):
                        service = ProjectSyncService(account.client, account)
                        result = service.sync()
                except SyncLockBusy:
                    logger.info("Portal %s project-sync skipped: lock busy.",
                                account.member_id)
                    continue

                # ProjectSyncService.sync() возвращает dict с ключами synced/created/updated
                count = result.get("synced", 0) if isinstance(result, dict) else 0
                synced += 1
                items_total += int(count or 0)
                logger.info("Scheduled project-sync portal %s: %s items.", account.member_id, count)

            else:  # scope == "timesheet"
                if not config.get("sp_entity_type_id"):
                    logger.info("Portal %s not configured (no sp_entity_type_id); skip.",
                                account.member_id)
                    continue

                try:
                    with account_sync_lock(account, scope="timesheet"):
                        service = TimesheetSyncService(account.client, account, config)
                        if full:
                            count = service.sync_all()  # без дат → _sync_full (ночная сверка)
                        else:
                            count = service.sync_all(date_from=date_from, date_to=date_to)
                        # Маркер «данные свежи на» для индикатора отчёта (гейт в timesheet_sync,
                        # задача 2.2) — иначе фоновые синки его не двигают, и виджет всегда
                        # показывал бы устаревшее время, пока пользователь не откроет отчёт сам.
                        account.last_timesheet_synced_at = timezone.now()
                        account.save(update_fields=["last_timesheet_synced_at"])
                except SyncLockBusy:
                    logger.info("Portal %s sync skipped: lock busy (manual sync running).",
                                account.member_id)
                    continue

                synced += 1
                items_total += int(count or 0)
                logger.info("Scheduled sync portal %s: %s items.", account.member_id, count)

        except Exception as exc:  # noqa: BLE001
            logger.exception("Scheduled sync failed for portal %s (account %s)",
                             account.member_id, account.pk)
            errors.append(f"{account.member_id}: {type(exc).__name__}: {exc}")

    run.portals_synced = synced
    run.items_synced = items_total
    run.finished_at = timezone.now()
    if errors and synced > 0:
        run.status = "partial"
    elif errors and synced == 0:
        run.status = "error"
    else:
        run.status = "success"
    run.error_summary = "\n".join(errors)[:4000] if errors else None
    run.save()
    return run
