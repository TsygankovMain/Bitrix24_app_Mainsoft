"""Логика seed-миграции 0015 (этап 0): один Portal на member_id.

Вынесена сюда отдельной функцией, принимающей классы моделей, чтобы:
(1) тестировать на реальных моделях через manage.py test;
(2) вызывать из data-migration 0015 через historical-модели (apps.get_model).
Идемпотентна: повторный вызов не плодит Portal и не перетирает связи.
"""
from typing import Type

from django.db.models import F


def seed_portals_from_accounts(portal_model: Type, account_model: Type) -> int:
    """Создаёт по одному Portal на каждый member_id и проставляет
    Bitrix24Account.portal. Возвращает число СОЗДАННЫХ Portal."""
    created = 0
    seen_member_ids = set(
        portal_model.objects.values_list("member_id", flat=True)
    )

    # Группируем аккаунты по member_id; мастер-аккаунт приоритетен как источник
    # домена. is_master_account — nullable BooleanField: на PostgreSQL
    # "-is_master_account" ставит NULL ПЕРЕД True (NULLS FIRST — умолчание для
    # DESC), поэтому учётка с is_master_account=None обгоняла бы настоящего
    # мастера. F(...).desc(nulls_last=True) кладёт NULL в конец.
    accounts = list(
        account_model.objects.all().order_by(
            "member_id", F("is_master_account").desc(nulls_last=True), "b24_user_id"
        )
    )
    portal_by_member = {}
    for acc in accounts:
        member_id = (acc.member_id or "").strip()
        if not member_id:
            continue
        portal = portal_by_member.get(member_id)
        if portal is None:
            if member_id in seen_member_ids:
                portal = portal_model.objects.get(member_id=member_id)
            else:
                portal = portal_model.objects.create(
                    member_id=member_id,
                    domain_url=acc.domain_url,   # первый в порядке = мастер (если есть)
                    status=acc.status or "active",
                )
                created += 1
                seen_member_ids.add(member_id)
            portal_by_member[member_id] = portal
        # Проставляем FK аккаунта, если ещё не проставлен.
        if acc.portal_id != portal.id:
            account_model.objects.filter(pk=acc.pk).update(portal_id=portal.id)
    return created
