"""Управление тарифом Pro портала из консоли сервера.

Единственный способ поменять тариф (PortalSubscription). REST на запись нет
и быть не должно. Портал задаётся по member_id (ключ, не меняется) или по
домену — домен только для удобства, внутри он резолвится в member_id.

Действия:

    python manage.py pro_plan list [--status active|grace|trial|expired|off] [--with-plan]
    python manage.py pro_plan show    --domain client.bitrix24.ru
    python manage.py pro_plan enable  --member-id abc123 --until 2026-12-31 [--price 3000]
    python manage.py pro_plan enable  --domain client.bitrix24.ru --months 12
    python manage.py pro_plan extend  --domain client.bitrix24.ru --months 1
    python manage.py pro_plan trial   --domain client.bitrix24.ru [--days 14 | --until 2026-09-30] [--force]
    python manage.py pro_plan expire  --domain client.bitrix24.ru --comment "счёт не оплачен"
    python manage.py pro_plan off     --member-id abc123 --comment "отказались"

У всех изменяющих действий есть --comment и --by (кто меняет; по умолчанию
пользователь ОС). Каждое изменение пишется в журнал тарифа.

Правило срока: оплачено по --until включительно (день по Москве), затем 7
дней грейса с полной работой, затем «только чтение»: создание и изменение в
платных функциях закрыты, просмотр и выгрузки работают. У ролевой модели в
«только чтении» закрыты назначение и правка ролей, а назначенные ограничения
продолжают действовать. Поэтому при неоплате — expire (или просто дождаться
срока), а off — только для портала, которому Pro не нужен совсем: off
снимает и ограничения ролей.
"""

import getpass
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from main import pro_plan_service as service
from main.billing_features import (
    ACCESS_FULL,
    ACCESS_READ_ONLY,
    EXPIRED_KEEPS,
    FEATURE_TITLES,
    GRACE_DAYS,
    PLAN_TITLES,
    STATUS_ACTIVE,
    STATUS_EXPIRED,
    STATUS_GRACE,
    STATUS_OFF,
    STATUS_TRIAL,
    SubscriptionStatus,
    subscription_today,
)
from main.models import PortalSubscriptionEvent

STATUS_LABELS = {
    STATUS_ACTIVE: "действует",
    STATUS_GRACE: "грейс",
    STATUS_TRIAL: "пробный",
    STATUS_EXPIRED: "истёк",
    STATUS_OFF: "выключен",
}
ACCESS_LABELS = {
    ACCESS_FULL: "всё работает",
    ACCESS_READ_ONLY: "только чтение и выгрузки",
    "none": "платные функции закрыты",
}
STATUSES = tuple(STATUS_LABELS)


def _fmt(value) -> str:
    return f"{value:%d.%m.%Y}" if value else "—"


def describe(status: SubscriptionStatus) -> str:
    """Одна строка итога: «Pro: действует по 31.12.2026 (грейс до 07.01.2027), всё работает»."""
    if status is None:
        return "тарифа не было"
    plan = PLAN_TITLES.get(status.plan or "", "Pro")
    label = STATUS_LABELS.get(status.status, status.status)
    if status.status in (STATUS_ACTIVE, STATUS_GRACE):
        if status.paid_until is None:
            term = "бессрочно"
        else:
            term = f"оплачен по {_fmt(status.paid_until)}, запись до {_fmt(status.grace_until)}"
    elif status.status == STATUS_TRIAL:
        term = f"до {_fmt(status.trial_until)}" if status.trial_until else "бессрочный"
    elif status.status == STATUS_EXPIRED:
        ended = status.grace_until or status.trial_until or status.paid_until
        term = f"запись закрыта после {_fmt(ended)}" if ended else "запись закрыта оператором"
    else:
        term = ""
    access = ACCESS_LABELS.get(status.access, status.access)
    return f"{plan}: {label}" + (f", {term}" if term else "") + f" — {access}"


def _parse_date(raw: str, option: str) -> date:
    try:
        return date.fromisoformat(str(raw).strip())
    except ValueError as exc:
        raise CommandError(f"{option}: ожидается дата ГГГГ-ММ-ДД, получено «{raw}».") from exc


class Command(BaseCommand):
    help = "Тариф Pro портала: list, show, enable, extend, trial, expire, off."

    def add_arguments(self, parser):
        actions = parser.add_subparsers(dest="action", title="действия", required=True)

        def with_target(sub, changes=True):
            sub.add_argument("--member-id", default="", help="member_id портала (надёжный ключ).")
            sub.add_argument("--domain", default="", help="Домен портала; резолвится в member_id.")
            if changes:
                sub.add_argument("--comment", default="", help="Комментарий: счёт, договор, причина.")
                sub.add_argument("--by", default="", help="Кто меняет (по умолчанию пользователь ОС).")
            return sub

        listing = actions.add_parser("list", help="Порталы со статусом и сроком.")
        listing.add_argument("--status", default="", choices=("",) + STATUSES, help="Только с этим статусом.")
        listing.add_argument("--with-plan", action="store_true", help="Скрыть порталы без тарифа.")

        with_target(actions.add_parser("show", help="Тариф портала и журнал изменений."), changes=False)

        enable = with_target(actions.add_parser("enable", help="Включить Pro до даты или на N месяцев."))
        enable.add_argument("--until", default="", help="Оплачено по дату включительно, ГГГГ-ММ-ДД.")
        enable.add_argument("--months", type=int, default=None, help="Оплачено на N месяцев с сегодня.")
        enable.add_argument("--price", type=int, default=None, help="Цена в месяц, ₽ (по умолчанию 3000).")

        extend = with_target(actions.add_parser("extend", help="Продлить оплату на N месяцев."))
        extend.add_argument("--months", type=int, required=True, help="На сколько месяцев.")
        extend.add_argument("--price", type=int, default=None, help="Новая цена в месяц, ₽.")

        trial = with_target(actions.add_parser("trial", help="Дать пробный период."))
        trial.add_argument("--days", type=int, default=None, help="Дней, считая сегодня (по умолчанию 14).")
        trial.add_argument("--until", default="", help="Пробный по дату включительно, ГГГГ-ММ-ДД.")
        trial.add_argument("--force", action="store_true", help="Заменить действующий оплаченный Pro.")

        with_target(actions.add_parser("expire", help="Закрыть запись сразу, чтение оставить."))
        with_target(actions.add_parser("off", help="Выключить Pro: платные функции закрыты полностью."))

    def handle(self, *args, **options):
        action = options["action"]
        try:
            if action == "list":
                self._list(options)
                return
            portal = service.resolve_portal(options.get("member_id", ""), options.get("domain", ""))
            if action == "show":
                self._show(portal)
                return
            change = self._change(action, portal, options)
        except service.PlanError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(
            f"{portal.domain_url or '—'} (member_id {portal.member_id}): {action} выполнено."
        ))
        self.stdout.write(f"  было:  {describe(change.before)}")
        self.stdout.write(f"  стало: {describe(change.after)}")
        self.stdout.write(f"  цена:  {change.subscription.price_month_rub} ₽ в месяц")
        if change.after.access == ACCESS_READ_ONLY:
            self._write_keeps()
        if action == "off":
            self.stdout.write(self.style.WARNING(
                "  Внимание: off выключает Pro целиком — ограничения ролевой модели перестают действовать, "
                "и сотрудники увидят ставки и деньги. При неоплате используйте expire: запись закроется, "
                "а назначенные ограничения останутся."
            ))

    def _write_keeps(self):
        self.stdout.write("  что осталось:")
        for code, keeps in EXPIRED_KEEPS.items():
            self.stdout.write(f"    {FEATURE_TITLES.get(code, code)}: {keeps}")

    def _change(self, action, portal, options):
        actor = f"console:{options.get('by') or self._os_user()}"
        comment = options.get("comment") or ""
        if action == "enable":
            until = _parse_date(options["until"], "--until") if options.get("until") else None
            return service.enable(portal, until=until, months=options.get("months"),
                                  price=options.get("price"), actor=actor, comment=comment)
        if action == "extend":
            return service.extend(portal, months=options["months"], price=options.get("price"),
                                  actor=actor, comment=comment)
        if action == "trial":
            until = _parse_date(options["until"], "--until") if options.get("until") else None
            return service.trial(portal, days=options.get("days"), until=until,
                                 force=options.get("force", False), actor=actor, comment=comment)
        if action == "expire":
            return service.expire(portal, actor=actor, comment=comment)
        if action == "off":
            return service.turn_off(portal, actor=actor, comment=comment)
        raise CommandError(f"Неизвестное действие: {action}")

    @staticmethod
    def _os_user() -> str:
        try:
            return getpass.getuser()
        except Exception:  # noqa: BLE001 — в контейнере пользователя может не быть
            return "unknown"

    def _list(self, options):
        today = subscription_today()
        rows = service.list_portals(
            include_without_plan=not options.get("with_plan"),
            status_filter=options.get("status") or "",
            today=today,
        )
        if not rows:
            self.stdout.write("Порталов под этот отбор нет.")
            return
        self.stdout.write(f"Сегодня {_fmt(today)} (МСК), грейс после оплаты — {GRACE_DAYS} дн.")
        header = f"{'домен':<32} {'member_id':<34} {'статус':<10} {'оплачен по':<11} {'запись до':<11} {'пробный до':<11} {'₽/мес':>6}"
        self.stdout.write(header)
        self.stdout.write("-" * len(header))
        for row in rows:
            status = row.status
            label = STATUS_LABELS.get(status.status, status.status) if row.subscription else "нет тарифа"
            price = str(status.price_month_rub) if row.subscription else ""
            self.stdout.write(
                f"{(row.domain or '—')[:32]:<32} {row.member_id[:34]:<34} {label:<10} "
                f"{_fmt(status.paid_until):<11} {_fmt(status.writable_until if status.status != STATUS_EXPIRED else None):<11} "
                f"{_fmt(status.trial_until):<11} {price:>6}"
            )

    def _show(self, portal):
        from main.billing_features import resolve_subscription

        subscription = getattr(portal, "subscription", None)
        self.stdout.write(f"Портал {portal.domain_url or '—'} (member_id {portal.member_id})")
        if subscription is None:
            self.stdout.write("  тарифа нет — платные функции закрыты")
            return
        status = resolve_subscription(subscription)
        self.stdout.write(f"  {describe(status)}")
        if status.access == ACCESS_READ_ONLY:
            self._write_keeps()
        self.stdout.write(f"  цена: {subscription.price_month_rub} ₽ в месяц")
        if subscription.comment:
            self.stdout.write(f"  комментарий: {subscription.comment}")
        self.stdout.write(f"  менял: {subscription.updated_by or '—'}, {subscription.updated_at:%d.%m.%Y %H:%M} UTC")
        events = PortalSubscriptionEvent.objects.filter(subscription=subscription).order_by("-created_at")[:10]
        if events:
            self.stdout.write("  журнал:")
        for event in events:
            changes = ", ".join(f"{name}: {old} → {new}" for name, (old, new) in event.changes.items()) or "без изменений"
            note = f" — {event.comment}" if event.comment else ""
            self.stdout.write(f"    {event.created_at:%d.%m.%Y %H:%M} {event.action} ({event.actor}): {changes}{note}")
