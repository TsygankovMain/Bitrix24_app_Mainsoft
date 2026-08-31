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
  Timesheet: инкремент — TimesheetSyncService.sync_all() БЕЗ дат, режим
  выбирает сам сервис по маркеру last_timesheet_synced_at (спека
  2026-07-31: выборка по ">=updatedTime" от маркера минус 5 минут, без
  верхней границы). Фоновый цикл каждые 20 минут. С full=True — полная
  сверка (-> _sync_full), фоновый цикл раз в сутки: только она ловит
  удаления, которых инкремент не видит в принципе (запись просто
  отсутствует в выдаче), отключать её нельзя. Параметр `full`
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

from django.db.models import Q
from django.utils import timezone

from b24pysdk.error import (
    BitrixAPIForbidden,
    BitrixAPIServiceUnavailable,
    BitrixAPIUnauthorized,
    BitrixRequestTimeout,
    BitrixResponseJSONDecodeError,
)

from .models import Bitrix24Account, SyncRun
from .configuration_service import ConfigurationService
from .project_sync_service import ProjectSyncService
from .tenant_scoping import portal_scoping_enabled
from .timesheet_sync_service import TimesheetSyncService
from .task_sync_service import TaskSyncService
from .user_sync_service import UserSyncService
# Под USE_PORTAL_SCOPING account_sync_lock ключуется по portal.pk (замок «по
# компании»), выбор субъекта — внутри замка по флагу; вызовы ниже не меняются.
from .utils.decorators.sync_lock import account_sync_lock, SyncLockBusy

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_DAYS = 7

# Пауза для мёртвых порталов: первая постоянная ошибка -> 6ч, вторая и
# последующие подряд -> 24ч (см. is_permanent_sync_failure/run_scheduled_sync).
COOLDOWN_FIRST_FAILURE = timedelta(hours=6)
COOLDOWN_REPEAT_FAILURE = timedelta(hours=24)

# Временные сигналы — сеть моргнула/лимит запросов. Портал НЕ ставится на
# паузу: он просто повторится в следующем цикле (каждые 20 минут для
# timesheet), поэтому проверяются раньше и с приоритетом над permanent-текстом.
_TEMPORARY_TEXT_MARKERS = (
    "timed out",
    "timeout",
    "too many requests",
    "over_limit",
    "connection reset",
    "connection aborted",
    "connection refused",
    "remotedisconnected",
    "broken pipe",
)

# Постоянные сигналы — портал объективно мёртв (снесено приложение, кончилась
# подписка, заблокирован сканером лицензий, авторизация невосстановима, домен
# не резолвится, ответ — не JSON). Тексты дословно из прод-лога
# sync_all_portals --scope timesheet.
_PERMANENT_TEXT_MARKERS = (
    "application not installed",
    "subscription has been ended",
    "portal is blocked",
    "nameresolutionerror",
    "failed to resolve",
    "name or service not known",
    "getaddrinfo failed",
    "unauthorized",
    "forbidden",
)


def is_permanent_sync_failure(exc: BaseException) -> bool:
    """Классификация ошибки планировщика: постоянная (мёртвый портал -> пауза,

    см. run_scheduled_sync) или временная (сеть моргнула/лимит -> ничего не
    трогаем, портал просто повторится в следующем цикле).

    Классифицируем и по типу исключения (реальные классы b24pysdk, когда
    долетают как есть — например BitrixAPIErrorOAuth, подкласс
    BitrixAPIUnauthorized), и по тексту сообщения (прод-строки вроде
    "Subscription has been ended"/"Portal is blocked by the license scanner",
    для которых отдельного класса SDK нет, плюс устойчивость на случай, если
    исключение обёрнуто/переупаковано выше по стеку).

    Неизвестная ошибка -> временная. Осторожная сторона: лучше лишний повтор
    через 20 минут, чем молча выключить синк живому порталу.
    """
    # Явные временные сигналы SDK — проверяем первыми, чтобы их не мог
    # перекрыть более широкий permanent-матч (по типу или по тексту).
    if isinstance(exc, (BitrixRequestTimeout, BitrixAPIServiceUnavailable)):
        return False

    haystack = f"{type(exc).__name__}: {exc}".lower()

    if any(marker in haystack for marker in _TEMPORARY_TEXT_MARKERS):
        return False

    # Явные постоянные сигналы SDK: авторизация невосстановима (401/403,
    # включая BitrixAPIErrorOAuth "Application not installed") или портал
    # отдаёт не-JSON ответ (HTML/пусто вместо REST API).
    if isinstance(exc, (BitrixAPIUnauthorized, BitrixAPIForbidden, BitrixResponseJSONDecodeError)):
        return True

    if any(marker in haystack for marker in _PERMANENT_TEXT_MARKERS):
        return True

    return False


def select_portal_accounts() -> List[Bitrix24Account]:
    """Один представитель на портал (member_id): мастер, иначе первый по порядку.

    Критерий синк-пригодности — refresh_token, а НЕ status: Bitrix24Account.status
    хранит статус подписки приложения из Битрикса (OAuthPlacementData.status —
    F/D/T/P/L/S), а не "active"/"inactive", и литерал "active" в него никогда не
    попадает (см. models.update_or_create_from_oauth_placement_data). Старый
    фильтр status="active" не совпадал НИ С ОДНИМ реальным аккаунтом — боевой
    инцидент, планировщик не синкал ни одного портала ни разу.

    Используется только под USE_PORTAL_SCOPING=True, для любого scope (см.
    _account_scoped_sync_accounts).

    Аккаунты на паузе (sync_disabled_until в будущем — мёртвый портал,
    см. is_permanent_sync_failure/run_scheduled_sync) исключены: планировщик
    не должен долбиться в заведомо мёртвый портал каждые 20 минут/час/3 часа."""
    now = timezone.now()
    eligible = (
        Bitrix24Account.objects.exclude(refresh_token__isnull=True)
        .exclude(refresh_token="")
        .filter(Q(sync_disabled_until__isnull=True) | Q(sync_disabled_until__lte=now))
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
    now = timezone.now()
    return list(
        Bitrix24Account.objects.exclude(refresh_token__isnull=True)
        .exclude(refresh_token="")
        .filter(Q(sync_disabled_until__isnull=True) | Q(sync_disabled_until__lte=now))
    )


def run_scheduled_sync(days: int = DEFAULT_WINDOW_DAYS, scope: str = "timesheet", full: bool = False) -> SyncRun:
    run = SyncRun.objects.create(scope=scope, status="running", window_days=days)

    now = timezone.now()

    # date_from/date_to здесь больше НЕ вычисляются: инкремент таймшитов ходит
    # по updatedTime от маркера (спека 2026-07-31), а не окном по дате
    # отражения. Окно в 7 дней не видело записей, внесённых задним числом, и
    # пристроенная к нему выборка по createdTime теряла всё созданное сегодня
    # (боевой баг 2fcd176). DEFAULT_WINDOW_DAYS остаётся только параметром
    # --days management-команды и полем журнала SyncRun.window_days.

    # Множество одинаково для всех скоупов и зависит только от
    # USE_PORTAL_SCOPING (fixwave CRITICAL #1, см. _account_scoped_sync_accounts):
    # TimesheetItem, ProjectCard и PortalUser скоуплены одинаково, поэтому под
    # флагом OFF один представитель на портал оставлял бы остальных
    # сотрудников с пустой доской проектов/справочником, а свои строки
    # timesheet — незасинканными.
    reps = _account_scoped_sync_accounts()
    run.portals_total = len(reps)

    # Мёртвые порталы уже исключены из reps (см. _account_scoped_sync_accounts/
    # select_portal_accounts — фильтр по sync_disabled_until), поэтому здесь
    # только считаем, сколько было пропущено для итоговой строки прогона —
    # без этого числа "portals X/Y" молча ужимается, и непонятно, то ли
    # аккаунтов стало меньше, то ли часть просто на паузе.
    skipped_cooldown = (
        Bitrix24Account.objects.exclude(refresh_token__isnull=True)
        .exclude(refresh_token="")
        .filter(sync_disabled_until__gt=now)
        .count()
    )

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

            elif scope == "tasks":
                try:
                    with account_sync_lock(account, scope="tasks"):
                        service = TaskSyncService(account.client, account)
                        result = service.sync()
                        # Уборка за событийным механизмом: остаток от
                        # интерактивных вызовов, историческое расхождение и
                        # любые пропуски. Только в фоне — здесь есть время.
                        # Порция 50, а не 5 по умолчанию. Пять ставились из
                        # соображения «фоновой уборке некуда спешить», но на
                        # практике это два часа на разбор накопленного, и всё
                        # это время периоды не закрываются: расхождение
                        # проектов — блокер проверки перед закрытием.
                        #
                        # Замер на проде 31.08.2026: расходятся 23 задачи и 48
                        # записей, плюс 11 записей вовсе без проекта. Это ~60
                        # обновлений карточек с комментариями, то есть минута-
                        # две работы. Прогон идёт отдельным процессом из
                        # start.sh, HTTP-таймаута над ним нет — потолок здесь
                        # только про то, чтобы не держать advisory-замок
                        # сколько угодно долго.
                        #
                        # Когда накопленное разобрано, стоимость нулевая: при
                        # отсутствии расхождений это один SELECT.
                        service.reconcile_project_divergence(limit=50)
                except SyncLockBusy:
                    logger.info("Portal %s task-sync skipped: lock busy.",
                                account.member_id)
                    continue

                count = result.get("synced", 0) if isinstance(result, dict) else 0
                synced += 1
                items_total += int(count or 0)
                logger.info("Scheduled task-sync portal %s: %s tasks.", account.member_id, count)

            else:  # scope == "timesheet"
                if not config.get("sp_entity_type_id"):
                    logger.info("Portal %s not configured (no sp_entity_type_id); skip.",
                                account.member_id)
                    continue

                try:
                    with account_sync_lock(account, scope="timesheet"):
                        service = TimesheetSyncService(account.client, account, config)
                        # started_at снимается ДО обхода (спека 2026-07-31, §4.3):
                        # правка, случившаяся во время обхода, имеет
                        # updatedTime >= started_at и гарантированно попадёт в
                        # следующую выборку. Маркер «сейчас после обхода» её бы
                        # проглотил — обход длится минуты.
                        started_at = timezone.now()
                        # Без дат: режим выбирает сам сервис (resolve_sync_mode) —
                        # маркер есть → инкремент по updatedTime, маркера нет →
                        # первый полный синк. full=True → ночная полная сверка.
                        count = service.sync_all(full=full)
                        # Маркер «данные свежи на» для индикатора отчёта (гейт в timesheet_sync,
                        # задача 2.2) — иначе фоновые синки его не двигают, и виджет всегда
                        # показывал бы устаревшее время, пока пользователь не откроет отчёт сам.
                        # Проставляется только здесь, после успешного обхода: любой сбой
                        # оставляет маркер на месте, и следующий запуск перекрывает
                        # пропущенный интервал целиком (§4.3 — дыр не образуется).
                        sync_marker = started_at
                        if portal_scoping_enabled() and account.portal_id:
                            # Под portal-скоупингом синкает один представитель, но данные
                            # общие на портал -> маркер получают ВСЕ аккаунты портала,
                            # способные авторизоваться (fixwave CRITICAL #1), иначе их
                            # отчёты показывали бы «устарело», хотя данные уже свежие.
                            # account.portal_id (а не account.portal) — чтобы не тянуть
                            # лишний SELECT. Критерий — refresh_token, а не status: то же
                            # поле, тот же боевой инцидент, что и в select_portal_accounts/
                            # _account_scoped_sync_accounts (status="active" не совпадает
                            # НИ С ОДНИМ реальным аккаунтом — см. модульный докстринг выше).
                            # Без этого фильтра bulk .update() не находит ни одной строки,
                            # включая самого представителя (ниже нет .save() — только
                            # присваивание атрибута в памяти), и маркер не долетает вообще
                            # ни до кого.
                            Bitrix24Account.objects.filter(portal_id=account.portal_id).exclude(
                                refresh_token__isnull=True
                            ).exclude(refresh_token="").update(last_timesheet_synced_at=sync_marker)
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
            if is_permanent_sync_failure(exc):
                # Мёртвый портал (снесли приложение, кончилась подписка,
                # заблокирован, домен не резолвится...) — не трейсбек в лог на
                # разбор заказчику, а одна строка + пауза, чтобы планировщик
                # не долбился сюда каждые 20 минут/час/3 часа.
                account.sync_failure_count = (account.sync_failure_count or 0) + 1
                account.sync_failure_reason = f"{type(exc).__name__}: {exc}"[:255]
                cooldown = COOLDOWN_FIRST_FAILURE if account.sync_failure_count == 1 else COOLDOWN_REPEAT_FAILURE
                account.sync_disabled_until = timezone.now() + cooldown
                account.save(update_fields=["sync_failure_count", "sync_failure_reason", "sync_disabled_until"])
                logger.warning(
                    "Scheduled sync: portal %s (account %s) looks permanently dead (%s) — "
                    "paused until %s (failure #%s).",
                    account.member_id, account.pk, account.sync_failure_reason,
                    account.sync_disabled_until, account.sync_failure_count,
                )
            else:
                # Временная ошибка (сеть моргнула/лимит запросов) — портал может
                # быть живым, паузу не ставим, логируем с трейсбеком как раньше:
                # это может быть настоящая проблема, которую нужно разобрать.
                logger.exception("Scheduled sync failed for portal %s (account %s)",
                                 account.member_id, account.pk)
            errors.append(f"{account.member_id}: {type(exc).__name__}: {exc}")
        else:
            # Успешный синк (или явный skip выше по continue сюда не попадает —
            # else у try выполняется только при чистом завершении try без
            # исключений) — сбрасываем состояние "мёртвого портала", если оно
            # было: портал ожил, следующий сбой снова начнёт счёт с 6ч.
            if account.sync_failure_count or account.sync_disabled_until or account.sync_failure_reason:
                account.sync_failure_count = 0
                account.sync_failure_reason = None
                account.sync_disabled_until = None
                account.save(update_fields=["sync_failure_count", "sync_failure_reason", "sync_disabled_until"])

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
    logger.info(
        "Scheduled sync done: scope=%s, portals %s/%s, items=%s, skipped_cooldown=%s",
        scope, synced, run.portals_total, items_total, skipped_cooldown,
    )
    return run
