"""Фоновая синхронизация по расписанию (задача 3.6; fixwave CRITICAL #1).

Запускается management-командой sync_all_portals из встроенного планировщика
(фоновый цикл в start.sh) или вручную. Множество аккаунтов, которое обходит
run_scheduled_sync, одинаково для ВСЕХ скоупов и зависит только от
settings.USE_PORTAL_SCOPING (_account_scoped_sync_accounts()), потому что все
три проекции — TimesheetItem, ProjectCard, PortalUser — скоуплены через один и
тот же tenant_scoping.scope_to_tenant:

    - флаг OFF (дефолт) -> данные ПО АККАУНТУ -> синкается КАЖДЫЙ аккаунт,
      способный авторизоваться (_account_scoped_sync_accounts()); один
      представитель освежал бы только свои же строки (timesheet) или писал
      бы ProjectCard/PortalUser только под своим FK (project/users), а
      остальные пользователи портала не видели бы свежих данных вовсе — для
      ProjectCard это давало пустую доску проектов всем, кроме представителя
      (тот же баг, что и с timesheet/users, найден отдельно и позже).
    - флаг ON -> данные по порталу (общие) -> один представитель
      (select_portal_accounts()); для timesheet маркер синка проставляется
      всем активным аккаунтам портала (см. run_scheduled_sync).

  Project: полный синк проектов (ProjectSyncService.sync()), раз в 3 часа.
  Параметр `full` игнорируется.
  Timesheet: инкремент — TimesheetSyncService.sync_all() с окном
  date_from/date_to, фоновый цикл каждые 20 минут. С full=True — полная
  сверка без окна дат (-> _sync_full), фоновый цикл раз в сутки — ловит
  удаления/пропуски, которые инкремент не видит. Параметр `full`
  используется только в этой ветке (для project/users игнорируется).
  Users: UserSyncService.sync() — полный синк справочника сотрудников, без
  инкремента (см. UserSyncService), часовой фоновый цикл (start.sh).

Множество для project/timesheet/users НЕ фильтруется по Bitrix24Account.status:
это поле хранит статус ПОДПИСКИ ПРИЛОЖЕНИЯ из Битрикса (OAuthPlacementData.status
— буквенные коды F/D/T/P/L/S, см. models.update_or_create_from_oauth_placement_data,
единственное место записи), а не "active"/"inactive" — литерал "active" в него не
попадает никогда. Прежний фильтр status="active" поэтому не совпадал НИ С ОДНИМ
реальным аккаунтом (боевой инцидент: планировщик не синкал ни одного портала ни
разу, ни для project, ни для timesheet/users). Критерий синк-пригодности —
refresh_token: если он есть, аккаунт в принципе способен авторизоваться.

Для каждого аккаунта из подобранного множества: читает конфиг (app.option) и,
если автосинк включён, выполняет синк. После успешного синка в ветке timesheet
проставляется last_timesheet_synced_at — тот же маркер, что ставит on-demand
дозагрузка на endpoint timesheet_sync (задача 2.2), чтобы индикатор «данные на
ЧЧ:ММ» в отчёте отражал и фоновые синки, а не только визиты пользователя.

Падение одного портала/аккаунта не прерывает остальные. Совместимо с
advisory-lock из 2.2 (на Postgres лок берётся честно, на sqlite no-op).
"""

import logging
from datetime import timedelta
from typing import List

from django.utils import timezone

from .models import Bitrix24Account, SyncRun
from .configuration_service import ConfigurationService
from .project_sync_service import ProjectSyncService
from .tenant_scoping import portal_scoping_enabled
from .timesheet_sync_service import TimesheetSyncService
from .user_sync_service import UserSyncService
# Под USE_PORTAL_SCOPING account_sync_lock ключуется по portal.pk (замок «по
# компании»), выбор субъекта — внутри замка по флагу; вызовы ниже не меняются.
from .utils.decorators.sync_lock import account_sync_lock, SyncLockBusy

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_DAYS = 7


def select_portal_accounts() -> List[Bitrix24Account]:
    """Один представитель на портал (member_id): мастер, иначе первый по порядку.

    Критерий синк-пригодности — refresh_token, а НЕ status: Bitrix24Account.status
    хранит статус подписки приложения из Битрикса (OAuthPlacementData.status —
    F/D/T/P/L/S), а не "active"/"inactive", и литерал "active" в него никогда не
    попадает (см. models.update_or_create_from_oauth_placement_data). Старый
    фильтр status="active" не совпадал НИ С ОДНИМ реальным аккаунтом — боевой
    инцидент, планировщик не синкал ни одного портала ни разу.

    Используется только под USE_PORTAL_SCOPING=True, для любого scope (см.
    _account_scoped_sync_accounts)."""
    eligible = (
        Bitrix24Account.objects.exclude(refresh_token__isnull=True)
        .exclude(refresh_token="")
        .order_by("member_id", "-is_master_account")
    )
    seen = set()
    reps: List[Bitrix24Account] = []
    for acc in eligible:
        if not acc.member_id or acc.member_id in seen:
            continue
        seen.add(acc.member_id)
        reps.append(acc)
    return reps


def _account_scoped_sync_accounts() -> List[Bitrix24Account]:
    """Множество аккаунтов для ЛЮБОГО scope (fixwave CRITICAL #1).

    TimesheetItem, ProjectCard и PortalUser скоуплены через один и тот же
    tenant_scoping.scope_to_tenant, поэтому множество аккаунтов для них общее:
    - USE_PORTAL_SCOPING=False -> ПО АККАУНТУ. Синкать нужно каждый аккаунт,
      способный авторизоваться (см. select_portal_accounts про refresh_token),
      отдельно — иначе один представитель обновляет только свои же строки
      (timesheet) или пишет ProjectCard/PortalUser только под своим FK
      (project/users), а остальные пользователи портала не видят свежих
      данных вовсе.
    - USE_PORTAL_SCOPING=True  -> по порталу (общие данные). Одного
      представителя достаточно; для timesheet маркер синка проставляется всем
      активным аккаунтам портала в run_scheduled_sync.
    """
    if portal_scoping_enabled():
        return select_portal_accounts()
    return list(
        Bitrix24Account.objects.exclude(refresh_token__isnull=True).exclude(refresh_token="")
    )


def run_scheduled_sync(days: int = DEFAULT_WINDOW_DAYS, scope: str = "timesheet", full: bool = False) -> SyncRun:
    run = SyncRun.objects.create(scope=scope, status="running", window_days=days)

    now = timezone.now()
    date_to = now.date().isoformat()
    date_from = (now - timedelta(days=days)).date().isoformat()

    # Множество одинаково для всех скоупов и зависит только от
    # USE_PORTAL_SCOPING (fixwave CRITICAL #1, см. _account_scoped_sync_accounts):
    # TimesheetItem, ProjectCard и PortalUser скоуплены одинаково, поэтому под
    # флагом OFF один представитель на портал оставлял бы остальных
    # сотрудников с пустой доской проектов/справочником, а свои строки
    # timesheet — незасинканными.
    reps = _account_scoped_sync_accounts()
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

            elif scope == "users":
                try:
                    with account_sync_lock(account, scope="users"):
                        service = UserSyncService(account.client, account)
                        result = service.sync()
                except SyncLockBusy:
                    logger.info("Portal %s user-sync skipped: lock busy.",
                                account.member_id)
                    continue

                # UserSyncService.sync() возвращает dict с ключами synced/created/updated
                count = result.get("synced", 0) if isinstance(result, dict) else 0
                synced += 1
                items_total += int(count or 0)
                logger.info("Scheduled user-sync portal %s: %s users.", account.member_id, count)

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
                        sync_marker = timezone.now()
                        if portal_scoping_enabled() and account.portal_id:
                            # Под portal-скоупингом синкает один представитель, но данные
                            # общие на портал -> маркер получают ВСЕ активные аккаунты
                            # портала (fixwave CRITICAL #1), иначе их отчёты показывали бы
                            # «устарело», хотя данные уже свежие. account.portal_id (а не
                            # account.portal) — чтобы не тянуть лишний SELECT.
                            Bitrix24Account.objects.filter(
                                status="active", portal_id=account.portal_id,
                            ).update(last_timesheet_synced_at=sync_marker)
                            account.last_timesheet_synced_at = sync_marker
                        else:
                            # Флаг OFF, либо portal ещё null (переходный период backfill) —
                            # маркер только этому аккаунту, как и раньше.
                            account.last_timesheet_synced_at = sync_marker
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
