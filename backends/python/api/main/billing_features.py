"""Состояния платных функций портала (PortalFeature) и декоратор подписки.

Читать состояние по своей учётке НЕЛЬЗЯ. Bitrix24Account в этом приложении —
запись на СОТРУДНИКА (уникальность по паре «пользователь + домен», у каждого
свои токены), а подписка портальная. Если бы состояние искалось по
scope_to_tenant, функция, включённая администратору, оказалась бы выключена у
бухгалтера того же портала — и наоборот, при USE_PORTAL_SCOPING=True одна
строка неожиданно управляла бы всеми. Поэтому здесь свой резолв: по member_id
портала (все учётки одного портала), с падением на саму учётку, если
member_id почему-то пуст.

Отсутствие строки = выключено (контракт: state по умолчанию off).
"""

import logging
from functools import wraps
from typing import Dict, Optional

from django.http import JsonResponse
from django.utils import timezone

from .models import PortalFeature

logger = logging.getLogger(__name__)

FEATURE_BILLING = PortalFeature.CODE_BILLING
FEATURE_BDDS = PortalFeature.CODE_BDDS
KNOWN_FEATURES = (FEATURE_BILLING, FEATURE_BDDS)

#: Название функции для текста отказа. Человек читает «Счёт и акт» или
#: «БДДС по проектам», а не код: сообщение с чужим названием отправило бы
#: его к администратору не за той подпиской.
FEATURE_TITLES = {
    FEATURE_BILLING: "Счёт и акт",
    FEATURE_BDDS: "БДДС по проектам",
}


def feature_queryset(account, code: Optional[str] = None):
    """Строки PortalFeature всех учёток портала (см. докстринг модуля)."""
    queryset = PortalFeature.objects.all()
    member_id = str(getattr(account, "member_id", "") or "").strip()
    if member_id:
        queryset = queryset.filter(bitrix24_account__member_id=member_id)
    else:
        queryset = queryset.filter(bitrix24_account=account)
    if code:
        queryset = queryset.filter(code=code)
    return queryset


def get_feature(account, code: str) -> Optional[PortalFeature]:
    """Действующая строка функции портала.

    Строк на портал может быть несколько (по одной на учётку). Побеждает
    включённая: команда пишет всем учёткам разом, но если состояние успели
    разойтись, выключить клиенту уже оплаченную функцию из-за чужой
    устаревшей строки — худший из двух исходов.
    """
    rows = list(feature_queryset(account, code))
    if not rows:
        return None
    now = timezone.now()
    for row in rows:
        if row.is_enabled(now):
            return row
    return rows[0]


def get_feature_state(account, code: str) -> Dict[str, object]:
    row = get_feature(account, code)
    if row is None:
        return {"state": PortalFeature.STATE_OFF, "trial_until": None, "enabled": False}
    return {
        "state": row.state,
        "trial_until": row.trial_until.isoformat() if row.trial_until else None,
        "enabled": row.is_enabled(),
    }


def feature_states(account) -> Dict[str, Dict[str, object]]:
    return {code: get_feature_state(account, code) for code in KNOWN_FEATURES}


def feature_enabled(account, code: str) -> bool:
    row = get_feature(account, code)
    return bool(row and row.is_enabled())


def feature_required(code: str):
    """Декоратор на эндпоинты платной функции.

    Контракт «Счёта и акта»: при выключенной подписке создание и печать
    запрещены (403, код feature_disabled), а чтение реестра и ОТМЕНА
    разрешены — отключение подписки не должно лишать клиента уже
    выставленных документов и возможности исправить ошибку.

    У БДДС такого исключения нет и быть не может: там нет документа,
    который клиент уже создал и обязан видеть дальше. Поэтому у неё
    декоратор стоит и на ЧТЕНИИ — это и есть серверная проверка подписки,
    которой фронтовый флаг никогда не был.

    Применять ПОСЛЕ @auth_required — нужен request.bitrix24_account.
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            account = getattr(request, "bitrix24_account", None)
            if account is None or not feature_enabled(account, code):
                title = FEATURE_TITLES.get(code, code)
                return JsonResponse(
                    {
                        "error": f"Функция «{title}» не подключена на этом портале.",
                        "code": "feature_disabled",
                        "feature": code,
                    },
                    status=403,
                )
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
