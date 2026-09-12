"""Перенос прежних PortalFeature в тариф портала (миграции 0024/0025).

Логика вынесена из файла миграции, как у portal_seed: функции принимают
классы моделей, поэтому их зовёт и data-migration через apps.get_model, и
тест на настоящих моделях.

Как сворачиваются строки. Прежде строка была на КАЖДУЮ учётку и на КАЖДУЮ
функцию, и состояния могли разойтись. Тариф теперь один на портал, поэтому
по member_id берётся лучшее из включённого — выключить клиенту оплаченное
из-за чужой устаревшей строки хуже, чем оставить лишнее:

- хоть одна строка on -> active без даты (бессрочно: срока у on не было, и
  молча закрыть работающих клиентов миграцией нельзя);
- иначе хоть один trial без даты -> trial бессрочный;
- иначе trial -> trial до самой поздней даты (дата по Москве);
- иначе -> off.

Функции внутри тарифа не различаются: Pro открывает все платные функции.
Портал, где был включён только «Счёт и акт», после переноса получит и БДДС.
"""

from datetime import datetime, time
from typing import Dict, Iterable, Optional
from zoneinfo import ZoneInfo

MIGRATION_ACTOR = "migration:0024_portal_subscription"
MOSCOW = ZoneInfo("Europe/Moscow")


def _moscow_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.date()
        return value.astimezone(MOSCOW).date()
    return value


def merge_legacy_rows(rows: Iterable[dict]) -> Dict[str, dict]:
    """Строки {member_id, domain, code, state, trial_until} -> тариф по порталу."""
    grouped: Dict[str, list] = {}
    domains: Dict[str, Optional[str]] = {}
    for row in rows:
        member_id = str(row.get("member_id") or "").strip()
        if not member_id:
            continue
        grouped.setdefault(member_id, []).append(row)
        if not domains.get(member_id) and row.get("domain"):
            domains[member_id] = row["domain"]

    result: Dict[str, dict] = {}
    for member_id, items in grouped.items():
        states = {item["state"] for item in items}
        trial_dates = [_moscow_date(item.get("trial_until")) for item in items if item["state"] == "trial"]
        summary = ", ".join(sorted({f"{item['code']}={item['state']}" for item in items}))

        if "on" in states:
            plan_state, trial_until = "active", None
        elif "trial" in states and any(value is None for value in trial_dates):
            plan_state, trial_until = "trial", None
        elif "trial" in states:
            plan_state, trial_until = "trial", max(trial_dates)
        else:
            plan_state, trial_until = "off", None

        result[member_id] = {
            "state": plan_state,
            "trial_until": trial_until,
            "domain": domains.get(member_id),
            "comment": f"Перенесено из PortalFeature: {summary}",
        }
    return result


def copy_features_to_subscriptions(feature_model, account_model, portal_model,
                                   subscription_model, event_model) -> int:
    """Прямой перенос. Возвращает число созданных тарифов. Идемпотентен."""
    rows = []
    for feature in feature_model.objects.all().select_related("bitrix24_account"):
        account = feature.bitrix24_account
        member_id = (account.member_id or "").strip()
        if not member_id and account.portal_id:
            portal = portal_model.objects.filter(pk=account.portal_id).first()
            member_id = portal.member_id if portal else ""
        rows.append({
            "member_id": member_id,
            "domain": account.domain_url,
            "code": feature.code,
            "state": feature.state,
            "trial_until": feature.trial_until,
        })

    created = 0
    for member_id, plan in merge_legacy_rows(rows).items():
        portal = portal_model.objects.filter(member_id=member_id).first()
        if portal is None:
            portal = portal_model.objects.create(
                member_id=member_id, domain_url=plan["domain"], status="active",
            )
        account_model.objects.filter(member_id=member_id, portal__isnull=True).update(portal=portal)
        if subscription_model.objects.filter(portal=portal).exists():
            continue
        subscription = subscription_model.objects.create(
            portal=portal,
            plan="pro",
            state=plan["state"],
            trial_until=plan["trial_until"],
            comment=plan["comment"],
            updated_by=MIGRATION_ACTOR,
        )
        event_model.objects.create(
            subscription=subscription,
            action="migrate",
            changes={
                "state": [None, plan["state"]],
                "trial_until": [None, plan["trial_until"].isoformat() if plan["trial_until"] else None],
            },
            actor=MIGRATION_ACTOR,
            comment=plan["comment"],
        )
        created += 1
    return created


def copy_subscriptions_to_features(feature_model, account_model, subscription_model) -> int:
    """Обратный перенос на случай отката: действующий тариф -> строки учёткам.

    Истёкший и выключенный тариф строк не порождают: у старой модели не было
    «только чтения», а отсутствие строки и было «выключено».
    """
    created = 0
    for subscription in subscription_model.objects.all().select_related("portal"):
        if subscription.state == "active":
            state, trial_until = "on", None
        elif subscription.state == "trial":
            state = "trial"
            trial_until = (
                datetime.combine(subscription.trial_until, time(23, 59, 59), tzinfo=MOSCOW)
                if subscription.trial_until else None
            )
        else:
            continue
        for account in account_model.objects.filter(member_id=subscription.portal.member_id):
            for code in ("billing", "bdds"):
                _, was_created = feature_model.objects.update_or_create(
                    bitrix24_account=account, code=code,
                    defaults={
                        "portal_id": subscription.portal_id,
                        "state": state,
                        "trial_until": trial_until,
                        "comment": "Восстановлено из PortalSubscription при откате",
                    },
                )
                created += int(was_created)
    return created
