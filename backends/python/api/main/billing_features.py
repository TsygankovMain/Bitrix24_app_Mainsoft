"""Платные функции портала: тариф Pro, правило просрочки и декоратор подписки.

Источник правды — PortalSubscription (тариф ПОРТАЛА, ключ member_id). Здесь
три вещи:

1. Правило. resolve_subscription превращает решение оператора (state) и даты
   в итог на сегодня: действует, грейс, истёк, выключено. Считается при
   каждом чтении, поэтому неоплаченный портал закрывается сам — без ночной
   задачи, которая могла бы не отработать.
2. Уровень доступа к функции: full (читать и писать), read_only (только
   чтение и выгрузки), none (ничего).
3. Декоратор feature_required(code) на ручки платной функции.

Правило просрочки (проработка подписки 12.09.2026, «Что происходит при
неоплате»): после paid_until портал ещё GRACE_DAYS дней работает полностью,
а затем закрываются запись и создание, но чтение и выгрузки остаются —
данные клиента остаются его данными. Пробный период грейса не имеет: после
trial_until сразу «только чтение». Выключенный тариф (off) и портал без
тарифа — функций нет совсем.

Ролевая модель (roles) при окончании Pro НЕ выключается целиком. Её «запись»
— это назначение и правка ролей, и только она закрывается. Применение уже
назначенных ограничений обязано продолжать работать: иначе неоплата
открыла бы всем сотрудникам ставки и деньги. Проверять «действуют ли
ограничения» надо через feature_restrictions_active, а не через
feature_enabled — последний при просрочке вернёт False.

Резолв портала по учётке. Bitrix24Account — запись на СОТРУДНИКА, поэтому
тариф ищется по member_id учётки (у всех сотрудников портала он один), с
падением на account.portal, если member_id почему-то пуст.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import wraps
from typing import Dict, Optional
from zoneinfo import ZoneInfo

from django.http import JsonResponse
from django.utils import timezone

from .models import PortalSubscription

logger = logging.getLogger(__name__)

FEATURE_BILLING = "billing"
FEATURE_BDDS = "bdds"
#: Ролевая модель. Ручки делает отдельная задача; ей достаточно повесить
#: @feature_required(FEATURE_ROLES) — код уже известен тарифу и /api/features.
FEATURE_ROLES = "roles"
KNOWN_FEATURES = (FEATURE_BDDS, FEATURE_BILLING, FEATURE_ROLES)

PLAN_PRO = PortalSubscription.PLAN_PRO
#: Какие функции открывает тариф. Сейчас тариф один, и в нём всё.
PLAN_FEATURES = {
    PLAN_PRO: frozenset(KNOWN_FEATURES),
}
PLAN_TITLES = {PLAN_PRO: "Pro"}

#: Грейс после paid_until, в днях. Семь — по проработке: за неделю счёт
#: успевают оплатить даже с согласованием, а бесплатно месяц не проживёшь.
GRACE_DAYS = 7

#: «Оплачено по 31.10» — это весь день 31.10 у клиента, а клиенты в России.
#: Сервер живёт в UTC, и без этого портал закрывался бы в 03:00 по Москве
#: накануне ожидаемого.
SUBSCRIPTION_TZ = ZoneInfo("Europe/Moscow")

#: Название функции для текста отказа: человек читает «Счёт и акт», а не код.
FEATURE_TITLES = {
    FEATURE_BILLING: "Счёт и акт",
    FEATURE_BDDS: "БДДС по проектам",
    FEATURE_ROLES: "Ролевая модель",
}

ACCESS_FULL = "full"
ACCESS_READ_ONLY = "read_only"
ACCESS_NONE = "none"

STATUS_ACTIVE = "active"
STATUS_GRACE = "grace"
STATUS_TRIAL = "trial"
STATUS_EXPIRED = "expired"
STATUS_OFF = "off"

#: Что остаётся у функции в «только чтении» (тариф закончился). Для
#: декоратора разницы нет — чтение открыто, запись закрыта; разница в смысле
#: «записи» и в тексте отказа.
EXPIRED_KEEPS = {
    FEATURE_BDDS: "чтение и выгрузки; закрыты создание и изменение",
    FEATURE_BILLING: "реестр, выгрузки и отмена; закрыты выставление и печать",
    FEATURE_ROLES: "назначенные ограничения ролей продолжают действовать; закрыты назначение и правка ролей",
}

#: Методы, которые считаются чтением. Всё прочее — запись.
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def subscription_today(now: Optional[datetime] = None) -> date:
    """Сегодняшняя дата по часовому поясу подписки (Москва)."""
    moment = now or timezone.now()
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    return moment.astimezone(SUBSCRIPTION_TZ).date()


@dataclass(frozen=True)
class SubscriptionStatus:
    """Итог тарифа на конкретный день."""

    status: str
    access: str
    plan: Optional[str] = None
    paid_until: Optional[date] = None
    trial_until: Optional[date] = None
    grace_until: Optional[date] = None
    #: Последний день, когда можно писать; None — бессрочно или неприменимо.
    writable_until: Optional[date] = None
    price_month_rub: int = PortalSubscription.DEFAULT_PRICE_MONTH_RUB

    @property
    def can_read(self) -> bool:
        return self.access in (ACCESS_FULL, ACCESS_READ_ONLY)

    @property
    def can_write(self) -> bool:
        return self.access == ACCESS_FULL


NO_SUBSCRIPTION = SubscriptionStatus(status=STATUS_OFF, access=ACCESS_NONE)


def resolve_subscription(
    subscription: Optional[PortalSubscription],
    today: Optional[date] = None,
) -> SubscriptionStatus:
    """Правило тарифа: решение оператора + даты -> итог на сегодня.

    Чистая функция от строки и даты: её и тестируем на границах.
    """
    if subscription is None:
        return NO_SUBSCRIPTION

    day = today or subscription_today()
    base = {
        "plan": subscription.plan,
        "paid_until": subscription.paid_until,
        "trial_until": subscription.trial_until,
        "price_month_rub": subscription.price_month_rub,
    }
    state = subscription.state

    if state == PortalSubscription.STATE_ACTIVE:
        paid_until = subscription.paid_until
        if paid_until is None:
            return SubscriptionStatus(status=STATUS_ACTIVE, access=ACCESS_FULL, **base)
        grace_until = paid_until + timedelta(days=GRACE_DAYS)
        if day <= paid_until:
            return SubscriptionStatus(
                status=STATUS_ACTIVE, access=ACCESS_FULL,
                grace_until=grace_until, writable_until=grace_until, **base,
            )
        if day <= grace_until:
            return SubscriptionStatus(
                status=STATUS_GRACE, access=ACCESS_FULL,
                grace_until=grace_until, writable_until=grace_until, **base,
            )
        return SubscriptionStatus(
            status=STATUS_EXPIRED, access=ACCESS_READ_ONLY, grace_until=grace_until, **base,
        )

    if state == PortalSubscription.STATE_TRIAL:
        trial_until = subscription.trial_until
        if trial_until is None or day <= trial_until:
            return SubscriptionStatus(
                status=STATUS_TRIAL, access=ACCESS_FULL, writable_until=trial_until, **base,
            )
        return SubscriptionStatus(status=STATUS_EXPIRED, access=ACCESS_READ_ONLY, **base)

    if state == PortalSubscription.STATE_EXPIRED:
        return SubscriptionStatus(status=STATUS_EXPIRED, access=ACCESS_READ_ONLY, **base)

    # off и любое незнакомое значение: ошибаемся в строгую сторону.
    return SubscriptionStatus(status=STATUS_OFF, access=ACCESS_NONE, **base)


def subscription_for_account(account) -> Optional[PortalSubscription]:
    """Тариф портала учётки (см. докстринг модуля про member_id)."""
    if account is None:
        return None
    member_id = str(getattr(account, "member_id", "") or "").strip()
    queryset = PortalSubscription.objects.select_related("portal")
    if member_id:
        return queryset.filter(portal__member_id=member_id).first()
    portal_id = getattr(account, "portal_id", None)
    if portal_id:
        return queryset.filter(portal_id=portal_id).first()
    return None


def account_subscription_status(account, today: Optional[date] = None) -> SubscriptionStatus:
    return resolve_subscription(subscription_for_account(account), today)


def feature_access_from_status(status: SubscriptionStatus, code: str) -> str:
    """Уровень доступа к функции при данном итоге тарифа."""
    if not status.plan or code not in PLAN_FEATURES.get(status.plan, ()):
        return ACCESS_NONE
    return status.access


def feature_access(account, code: str, today: Optional[date] = None) -> str:
    return feature_access_from_status(account_subscription_status(account, today), code)


def feature_enabled(account, code: str) -> bool:
    """Функция работает полностью (можно писать). Прежний смысл «включена»."""
    return feature_access(account, code) == ACCESS_FULL


def feature_readable(account, code: str) -> bool:
    return feature_access(account, code) in (ACCESS_FULL, ACCESS_READ_ONLY)


def restrictions_active_from_access(access: str) -> bool:
    return access in (ACCESS_FULL, ACCESS_READ_ONLY)


def feature_restrictions_active(account, code: str = FEATURE_ROLES) -> bool:
    """Применять ли ограничения функции (прежде всего ролевой модели).

    True при действующем Pro И при «только чтении» после его окончания:
    назначенные роли продолжают резать доступ к ставкам и деньгам, хотя
    менять роли уже нельзя. False — только когда Pro на портале нет или он
    выключен командой off.
    """
    return restrictions_active_from_access(feature_access(account, code))


def _iso(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value else None


def _legacy_state(status: SubscriptionStatus, access: str) -> str:
    """Поле state ответа в прежнем словаре on | trial | off.

    Словарь не расширен намеренно: state читают как «можно ли пользоваться»,
    и новое значение у старого читателя превратилось бы в «выключено» или,
    хуже, во что-то непредусмотренное. Подробности — в status и access.
    """
    if access != ACCESS_FULL:
        return "off"
    return "trial" if status.status == STATUS_TRIAL else "on"


def feature_state_payload(status: SubscriptionStatus, code: str) -> Dict[str, object]:
    access = feature_access_from_status(status, code)
    payload: Dict[str, object] = {
        # Прежние ключи — форма ответа /api/features не меняется.
        "state": _legacy_state(status, access),
        "trial_until": _iso(status.trial_until),
        "enabled": access == ACCESS_FULL,
        # Новое: тариф, итог и сроки.
        "access": access,
        "can_read": access in (ACCESS_FULL, ACCESS_READ_ONLY),
        "can_write": access == ACCESS_FULL,
        "status": status.status if access != ACCESS_NONE else STATUS_OFF,
        "plan": status.plan or PLAN_PRO,
        "paid_until": _iso(status.paid_until),
        "grace_until": _iso(status.grace_until),
        "writable_until": _iso(status.writable_until),
        "price_month_rub": status.price_month_rub,
    }
    if code == FEATURE_ROLES:
        # Ролевой модели мало «можно ли писать»: интерфейсу нужно знать, что
        # назначенные ограничения действуют и в «только чтении».
        payload["restrictions_active"] = restrictions_active_from_access(access)
    return payload


def get_feature_state(account, code: str) -> Dict[str, object]:
    return feature_state_payload(account_subscription_status(account), code)


def feature_states(account) -> Dict[str, Dict[str, object]]:
    """Ответ GET /api/features: по записи на каждый код функции."""
    status = account_subscription_status(account)
    return {code: feature_state_payload(status, code) for code in KNOWN_FEATURES}


def _denial(code: str, status: SubscriptionStatus, access: str) -> JsonResponse:
    title = FEATURE_TITLES.get(code, code)
    if access == ACCESS_READ_ONLY:
        until = status.grace_until or status.trial_until or status.paid_until
        since = f" {until:%d.%m.%Y}" if until else ""
        if code == FEATURE_ROLES:
            error = (
                f"Тариф Pro на этом портале закончился{since}: назначать и менять роли нельзя. "
                "Уже назначенные ограничения продолжают действовать. Продлите Pro, чтобы менять роли."
            )
        else:
            error = (
                f"Тариф Pro на этом портале закончился{since}: в «{title}» закрыты создание и "
                "изменение, просмотр и выгрузки работают. Продлите Pro, чтобы снова вносить данные."
            )
        reason = STATUS_EXPIRED
    else:
        error = f"Функция «{title}» не подключена на этом портале: она входит в тариф Pro."
        reason = STATUS_OFF
    return JsonResponse(
        {
            "error": error,
            # Код прежний: фронт и соседние задачи различают отказ подписки
            # по нему. Что именно закрыто — в reason и access.
            "code": "feature_disabled",
            "feature": code,
            "plan": PLAN_PRO,
            "reason": reason,
            "access": access,
        },
        status=403,
    )


def feature_required(code: str, *, write: Optional[bool] = None):
    """Декоратор на ручки платной функции.

    Что пропускается:
    - тариф действует (в том числе грейс и пробный) — всё;
    - тариф истёк — только ЧТЕНИЕ (GET/HEAD/OPTIONS): клиент видит и
      выгружает свои данные, но не создаёт и не меняет;
    - тарифа нет или он выключен — ничего.

    write=None — решает HTTP-метод. Ручке, которая читает POST-ом (или
    пишет GET-ом), тип задаётся явно: write=False / write=True.

    Ручки, которые должны работать даже без тарифа (реестр и отмена
    счетов), декоратор не носят вовсе — это решение самой функции.

    Ролевая модель: декоратор ставится на ручки НАЗНАЧЕНИЯ и ПРАВКИ ролей
    (и на чтение настроек ролей, если без Pro его не должно быть). На
    проверку прав в чужих ручках декоратор не ставится — там нужна
    feature_restrictions_active: ограничения действуют и после окончания Pro.

    Применять ПОСЛЕ @auth_required — нужен request.bitrix24_account.
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            account = getattr(request, "bitrix24_account", None)
            status = account_subscription_status(account) if account is not None else NO_SUBSCRIPTION
            access = feature_access_from_status(status, code)
            is_write = write if write is not None else request.method not in READ_METHODS
            allowed = access == ACCESS_FULL or (access == ACCESS_READ_ONLY and not is_write)
            if not allowed:
                return _denial(code, status, access)
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
