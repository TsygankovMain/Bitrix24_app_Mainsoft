"""Операции над тарифом портала — для консольной команды pro_plan.

Отдельно от команды, чтобы тот же код позже позвал экран управления
подписками, а тесты — без разбора вывода консоли. REST-ручки на запись у
этих операций нет и не должно быть (см. докстринг PortalSubscription).

Каждая операция пишет строку в журнал PortalSubscriptionEvent: кто, что,
было -> стало.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

from django.db import transaction
from django.db.models import F

from .billing_features import (
    GRACE_DAYS,
    SubscriptionStatus,
    resolve_subscription,
    subscription_today,
)
from .models import Bitrix24Account, Portal, PortalSubscription, PortalSubscriptionEvent

DEFAULT_TRIAL_DAYS = 14
TRACKED_FIELDS = ("plan", "state", "paid_until", "trial_until", "price_month_rub")


class PlanError(Exception):
    """Операция невозможна; текст — для человека в консоли."""


def normalize_domain(raw: str) -> str:
    value = str(raw or "").strip().lower()
    for prefix in ("https://", "http://"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value.split("/", 1)[0]


def add_months(start: date, months: int) -> date:
    """Та же дата через N месяцев; последний день месяца остаётся последним.

    31.01 + 1 = 28.02 (29.02), 30.11 + 1 = 31.12: иначе оплата «по конец
    месяца» уползала бы на день раньше с каждым продлением.
    """
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    is_last_day = start.day == calendar.monthrange(start.year, start.month)[1]
    day = last_day if is_last_day else min(start.day, last_day)
    return date(year, month, day)


def _portal_by_member_id(member_id: str) -> Optional[Portal]:
    portal = Portal.objects.filter(member_id=member_id).first()
    if portal is not None:
        return portal
    # Portal заводит seed-миграция и не заводит установка: у портала, который
    # поставил приложение позже, строки может не быть. Учётки есть — значит
    # портал существует, заводим его здесь.
    # is_master_account — nullable BooleanField: на PostgreSQL "-is_master_account"
    # ставит NULL ПЕРЕД True (NULLS FIRST — умолчание для DESC), поэтому учётка
    # без флага обгоняла бы настоящего мастера. nulls_last=True кладёт NULL в конец.
    accounts = list(
        Bitrix24Account.objects.filter(member_id=member_id).order_by(
            F("is_master_account").desc(nulls_last=True), "b24_user_id"
        )
    )
    if not accounts:
        return None
    portal = Portal.objects.create(
        member_id=member_id, domain_url=accounts[0].domain_url, status=accounts[0].status or "active",
    )
    Bitrix24Account.objects.filter(member_id=member_id, portal__isnull=True).update(portal=portal)
    return portal


def resolve_portal(member_id: str = "", domain: str = "") -> Portal:
    """Портал по member_id (ключ) или по домену (удобство, резолвится в member_id)."""
    member_id = str(member_id or "").strip()
    domain = normalize_domain(domain)
    if not member_id and not domain:
        raise PlanError("Укажите портал: --member-id <member_id> или --domain <домен>.")

    if member_id:
        portal = _portal_by_member_id(member_id)
        if portal is None:
            raise PlanError(f"Портал с member_id «{member_id}» не найден: приложение на нём не открывали.")
        if domain:
            known = set(Bitrix24Account.objects.filter(member_id=member_id).values_list("domain_url", flat=True))
            known.add(portal.domain_url or "")
            if domain not in {normalize_domain(value) for value in known}:
                raise PlanError(
                    f"member_id «{member_id}» принадлежит порталу {portal.domain_url}, а не {domain}. "
                    "Проверьте, какой портал имеется в виду."
                )
        return portal

    member_ids = set(
        Bitrix24Account.objects.filter(domain_url__iexact=domain)
        .exclude(member_id="").values_list("member_id", flat=True)
    )
    member_ids |= set(Portal.objects.filter(domain_url__iexact=domain).values_list("member_id", flat=True))
    if not member_ids:
        raise PlanError(f"Портал с доменом «{domain}» не найден. Домен мог смениться — попробуйте --member-id.")
    if len(member_ids) > 1:
        listed = ", ".join(sorted(member_ids))
        raise PlanError(
            f"Домен «{domain}» встречается у нескольких порталов ({listed}): укажите --member-id."
        )
    return _portal_by_member_id(member_ids.pop())


def _snapshot(subscription: PortalSubscription) -> dict:
    return {field: getattr(subscription, field) for field in TRACKED_FIELDS}


def _jsonable(value):
    return value.isoformat() if isinstance(value, date) else value


@dataclass
class PlanChange:
    portal: Portal
    subscription: PortalSubscription
    before: SubscriptionStatus
    after: SubscriptionStatus
    action: str


def _apply(portal: Portal, action: str, actor: str, comment: str, today: date, **fields) -> PlanChange:
    with transaction.atomic():
        subscription, created = PortalSubscription.objects.select_for_update().get_or_create(portal=portal)
        before_fields = {name: None for name in TRACKED_FIELDS} if created else _snapshot(subscription)
        before = None if created else resolve_subscription(subscription, today)
        for name, value in fields.items():
            setattr(subscription, name, value)
        subscription.plan = PortalSubscription.PLAN_PRO
        subscription.updated_by = actor
        if comment:
            subscription.comment = comment
        subscription.save()
        after_fields = _snapshot(subscription)
        changes = {
            name: [_jsonable(before_fields[name]), _jsonable(after_fields[name])]
            for name in TRACKED_FIELDS if before_fields[name] != after_fields[name]
        }
        PortalSubscriptionEvent.objects.create(
            subscription=subscription, action=action, changes=changes, actor=actor, comment=comment,
        )
    return PlanChange(
        portal=portal,
        subscription=subscription,
        before=before,
        after=resolve_subscription(subscription, today),
        action=action,
    )


def _current(portal: Portal) -> Optional[PortalSubscription]:
    return PortalSubscription.objects.filter(portal=portal).first()


def enable(portal: Portal, *, until: Optional[date] = None, months: Optional[int] = None,
           price: Optional[int] = None, actor: str, comment: str = "",
           today: Optional[date] = None) -> PlanChange:
    """Включить Pro до даты (включительно) или на N месяцев с сегодняшнего дня."""
    today = today or subscription_today()
    if (until is None) == (months is None):
        raise PlanError("Для enable нужен ровно один срок: --until ГГГГ-ММ-ДД или --months N.")
    if months is not None:
        if months <= 0:
            raise PlanError("--months должно быть положительным числом.")
        until = add_months(today, months) - timedelta(days=1)
    if until < today:
        raise PlanError(f"Дата окончания {until:%d.%m.%Y} уже прошла. Для «только чтения» есть команда expire.")
    fields = {"state": PortalSubscription.STATE_ACTIVE, "paid_until": until}
    if price is not None:
        fields["price_month_rub"] = _checked_price(price)
    return _apply(portal, "enable", actor, comment, today, **fields)


def extend(portal: Portal, *, months: int, price: Optional[int] = None, actor: str,
           comment: str = "", today: Optional[date] = None) -> PlanChange:
    """Продлить оплату на N месяцев.

    Пока оплата действует или идёт грейс, срок продолжается от paid_until:
    опоздавший с оплатой клиент не получает дни грейса бесплатно. Если Pro
    уже истёк, был пробным или выключен — отсчёт с сегодняшнего дня.
    """
    today = today or subscription_today()
    if months is None or months <= 0:
        raise PlanError("Для extend нужно --months N (N > 0).")
    subscription = _current(portal)
    if (subscription is not None and subscription.state == PortalSubscription.STATE_ACTIVE
            and subscription.paid_until is None):
        raise PlanError("Pro на этом портале бессрочный — продлевать нечего. Задать срок: enable --until.")

    continues = (
        subscription is not None
        and subscription.state == PortalSubscription.STATE_ACTIVE
        and subscription.paid_until is not None
        and today <= subscription.paid_until + timedelta(days=GRACE_DAYS)
    )
    if continues:
        until = add_months(subscription.paid_until + timedelta(days=1), months) - timedelta(days=1)
    else:
        until = add_months(today, months) - timedelta(days=1)
    fields = {"state": PortalSubscription.STATE_ACTIVE, "paid_until": until}
    if price is not None:
        fields["price_month_rub"] = _checked_price(price)
    return _apply(portal, "extend", actor, comment, today, **fields)


def trial(portal: Portal, *, days: Optional[int] = None, until: Optional[date] = None,
          force: bool = False, actor: str, comment: str = "",
          today: Optional[date] = None) -> PlanChange:
    """Пробный период: N дней (по умолчанию 14) или до даты включительно."""
    today = today or subscription_today()
    if days is not None and until is not None:
        raise PlanError("Для trial укажите что-то одно: --days N или --until ГГГГ-ММ-ДД.")
    if until is None:
        days = DEFAULT_TRIAL_DAYS if days is None else days
        if days <= 0:
            raise PlanError("--days должно быть положительным числом.")
        until = today + timedelta(days=days - 1)
    if until < today:
        raise PlanError(f"Дата окончания пробного периода {until:%d.%m.%Y} уже прошла.")

    subscription = _current(portal)
    if subscription is not None and not force:
        status = resolve_subscription(subscription, today)
        if subscription.state == PortalSubscription.STATE_ACTIVE and status.can_write:
            raise PlanError(
                "На портале действует оплаченный Pro — пробный период его заменит. "
                "Если это и нужно, повторите с --force."
            )
    return _apply(portal, "trial", actor, comment, today,
                  state=PortalSubscription.STATE_TRIAL, trial_until=until)


def expire(portal: Portal, *, actor: str, comment: str = "", today: Optional[date] = None) -> PlanChange:
    """Закрыть запись сразу, оставив чтение и выгрузки (без ожидания грейса)."""
    today = today or subscription_today()
    if _current(portal) is None:
        raise PlanError("У портала нет тарифа — закрывать нечего.")
    return _apply(portal, "expire", actor, comment, today, state=PortalSubscription.STATE_EXPIRED)


def turn_off(portal: Portal, *, actor: str, comment: str = "", today: Optional[date] = None) -> PlanChange:
    """Выключить Pro совсем: платные функции закрыты, включая чтение."""
    today = today or subscription_today()
    return _apply(portal, "off", actor, comment, today, state=PortalSubscription.STATE_OFF)


def _checked_price(price: int) -> int:
    if price is None or int(price) < 0:
        raise PlanError("--price должно быть неотрицательным числом рублей.")
    return int(price)


@dataclass
class PortalRow:
    member_id: str
    domain: str
    subscription: Optional[PortalSubscription]
    status: SubscriptionStatus


def list_portals(*, include_without_plan: bool = True, status_filter: str = "",
                 today: Optional[date] = None) -> List[PortalRow]:
    """Порталы со статусом тарифа. Порталы без строки Portal тоже видны."""
    today = today or subscription_today()
    rows: List[PortalRow] = []
    seen = set()
    for portal in Portal.objects.select_related("subscription").order_by("domain_url", "member_id"):
        subscription = getattr(portal, "subscription", None)
        seen.add(portal.member_id)
        rows.append(PortalRow(
            member_id=portal.member_id,
            domain=portal.domain_url or "",
            subscription=subscription,
            status=resolve_subscription(subscription, today),
        ))

    if include_without_plan:
        orphan = (
            Bitrix24Account.objects.exclude(member_id="").exclude(member_id__in=seen)
            # nulls_last=True: см. комментарий у _portal_by_member_id — иначе
            # NULL в is_master_account обгоняет True на PostgreSQL.
            .order_by("member_id", F("is_master_account").desc(nulls_last=True))
            .values_list("member_id", "domain_url")
        )
        for member_id, domain in orphan:
            if member_id in seen:
                continue
            seen.add(member_id)
            rows.append(PortalRow(member_id=member_id, domain=domain or "", subscription=None,
                                  status=resolve_subscription(None, today)))

    if not include_without_plan:
        rows = [row for row in rows if row.subscription is not None]
    if status_filter:
        rows = [row for row in rows if row.status.status == status_filter]
    return sorted(rows, key=lambda row: (row.subscription is None, row.domain, row.member_id))


def set_account_plan(account, *, state: str = PortalSubscription.STATE_ACTIVE,
                     paid_until: Optional[date] = None, trial_until: Optional[date] = None,
                     actor: str = "fixture") -> PortalSubscription:
    """Выставить тариф порталу учётки напрямую, без проверок и журнала.

    Для тестов и демо-данных: одна строка вместо «завести Portal, связать
    учётку, создать тариф». Функции соседних задач (например, ролевой модели)
    включаются в тестах так же: set_account_plan(self.account).
    """
    member_id = str(account.member_id or "").strip()
    portal = _portal_by_member_id(member_id) if member_id else None
    if portal is None:
        portal = Portal.objects.create(member_id=member_id or f"account-{account.pk}",
                                       domain_url=account.domain_url)
        Bitrix24Account.objects.filter(pk=account.pk).update(portal=portal)
    subscription, _ = PortalSubscription.objects.update_or_create(
        portal=portal,
        defaults={
            "plan": PortalSubscription.PLAN_PRO,
            "state": state,
            "paid_until": paid_until,
            "trial_until": trial_until,
            "updated_by": actor,
        },
    )
    return subscription
