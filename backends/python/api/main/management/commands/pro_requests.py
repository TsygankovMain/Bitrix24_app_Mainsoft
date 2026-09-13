"""Заявки на Pro из консоли сервера: список, карточка, оплата, отмена, повтор отправки.

    python manage.py pro_requests list [--status draft|pending|sent|paid|cancelled] [--open]
                                       [--code 482137] [--inn 7325148066] [--limit 50]
    python manage.py pro_requests show   --invoice УТ-0047 | --code 482137
    python manage.py pro_requests paid   --invoice УТ-0047 | --code 482137 [--date 2026-09-15]
                                         [--comment "платёжка 118"] [--by egor]
    python manage.py pro_requests cancel --invoice УТ-0047 [--reason "не оплачен"] [--by egor]
    python manage.py pro_requests sync   [--invoice УТ-0047] [--quiet]

Сопоставление платежа: сначала номер счёта (--invoice), он однозначен; если
в назначении платежа номера нет — код портала (--code), он тоже однозначен.
ИНН (list --inn) — только подсказка: у организации бывает несколько порталов.

`paid` отмечает заявку оплаченной и СРАЗУ включает Pro на оплаченный срок
через pro_plan (extend: действующий Pro продолжается от даты окончания,
истёкший или пробный — с сегодняшнего дня). Повторно оплату по той же заявке
отметить нельзя.

`sync` повторяет отправку в CRM Mainsoft заявок «ожидает отправки», досоздаёт
задачу на контроль оплаты у уже отправленных заявок (если она не создалась
с первого раза) и доносит отмены. Без MAINSOFT_BILLING_WEBHOOK ничего не
отправляет.
"""

import getpass
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from main import pro_purchase_service as service
from main.models import ProRequest
from main.pro_purchase_crm import load_crm_settings
from main.pro_purchase_pricing import money_str, months_text

STATUS_LABELS = {
    ProRequest.STATUS_DRAFT: "черновик",
    ProRequest.STATUS_PENDING: "ожидает отправки в CRM",
    ProRequest.STATUS_SENT: "отправлена в CRM",
    ProRequest.STATUS_PAID: "оплачена",
    ProRequest.STATUS_CANCELLED: "отменена",
}


def _fmt(value) -> str:
    return f"{value:%d.%m.%Y}" if value else "—"


class Command(BaseCommand):
    help = "Заявки на Pro: list, show, paid, cancel, sync."

    def add_arguments(self, parser):
        actions = parser.add_subparsers(dest="action", title="действия", required=True)

        def target(sub):
            sub.add_argument("--invoice", default="", help="Номер счёта, например УТ-0047 (или просто 47).")
            sub.add_argument("--code", default="", help="Код портала из назначения платежа, 6 цифр.")
            return sub

        listing = actions.add_parser("list", help="Заявки, новые сверху.")
        listing.add_argument("--status", default="", choices=("",) + ProRequest.STATUSES)
        listing.add_argument("--open", action="store_true", help="Только открытые (ждут оплаты).")
        listing.add_argument("--code", default="", help="Код портала.")
        listing.add_argument("--inn", default="", help="ИНН плательщика (подсказка).")
        listing.add_argument("--limit", type=int, default=50)

        target(actions.add_parser("show", help="Карточка заявки."))

        paid = target(actions.add_parser("paid", help="Отметить оплату и включить Pro."))
        paid.add_argument("--date", default="", help="Дата платежа ГГГГ-ММ-ДД (по умолчанию сегодня).")
        paid.add_argument("--comment", default="", help="Платёжка, выписка.")
        paid.add_argument("--by", default="", help="Кто отмечает (по умолчанию пользователь ОС).")

        cancel = target(actions.add_parser("cancel", help="Отменить заявку."))
        cancel.add_argument("--reason", default="", help="Причина.")
        cancel.add_argument("--by", default="")

        sync = actions.add_parser("sync", help="Повторить отправку в CRM Mainsoft.")
        sync.add_argument("--invoice", default="", help="Только эту заявку.")
        sync.add_argument("--quiet", action="store_true", help="Молчать, если отправлять нечего.")

    def handle(self, *args, **options):
        action = options["action"]
        try:
            if action == "list":
                return self._list(options)
            if action == "sync":
                return self._sync(options)
            request = service.find_request(invoice=options.get("invoice"), code=options.get("code"),
                                           open_only=action in ("paid", "cancel"))
            if action == "show":
                return self._show(request)
            if action == "paid":
                return self._paid(request, options)
            if action == "cancel":
                return self._cancel(request, options)
        except service.PurchaseError as exc:
            raise CommandError(str(exc)) from exc
        raise CommandError(f"Неизвестное действие: {action}")

    @staticmethod
    def _actor(options) -> str:
        who = options.get("by")
        if not who:
            try:
                who = getpass.getuser()
            except Exception:  # noqa: BLE001
                who = "unknown"
        return f"console:{who}"

    def _list(self, options):
        queryset = ProRequest.objects.select_related("portal").order_by("-created_at")
        if options.get("status"):
            queryset = queryset.filter(status=options["status"])
        if options.get("open"):
            queryset = queryset.filter(status__in=ProRequest.OPEN_STATUSES)
        if options.get("code"):
            queryset = queryset.filter(portal_code=options["code"].strip())
        if options.get("inn"):
            queryset = queryset.filter(payer_inn=options["inn"].strip())
        rows = list(queryset[: max(1, options.get("limit") or 50)])
        if not rows:
            self.stdout.write("Заявок под этот отбор нет.")
            return
        if options.get("inn"):
            portals = {row.portal_id for row in rows}
            if len(portals) > 1:
                self.stdout.write(self.style.WARNING(
                    f"У ИНН {options['inn']} заявки с {len(portals)} порталов — ИНН не однозначен, "
                    "сверяйте по номеру счёта или коду портала."
                ))
        header = f"{'счёт':<10} {'дата':<10} {'статус':<22} {'код':<7} {'портал':<30} {'срок':<11} {'сумма, ₽':>11} {'плательщик'}"
        self.stdout.write(header)
        self.stdout.write("-" * len(header))
        for row in rows:
            self.stdout.write(
                f"{row.invoice_number:<10} {_fmt(row.invoice_date):<10} {STATUS_LABELS.get(row.status, row.status):<22} "
                f"{row.portal_code:<7} {row.domain_snapshot[:30]:<30} {months_text(row.months):<11} "
                f"{money_str(row.total_amount):>11} {row.payer_name[:40]} (ИНН {row.payer_inn})"
            )

    def _show(self, request: ProRequest):
        crm = load_crm_settings()
        write = self.stdout.write
        write(f"Счёт {request.invoice_number} от {_fmt(request.invoice_date)} — {STATUS_LABELS.get(request.status, request.status)}")
        write(f"  портал:      {request.domain_snapshot} (сейчас {request.portal.domain_url or '—'})")
        write(f"  member_id:   {request.member_id_snapshot}")
        write(f"  код портала: {request.portal_code}")
        write(f"  плательщик:  {request.payer_name}, ИНН {request.payer_inn}"
              + (f", КПП {request.payer_kpp}" if request.payer_kpp else ""))
        write(f"  адрес:       {request.payer_address or '—'}")
        write(f"  контакт:     {request.contact_name}, {request.contact_email}"
              + (f", копия {request.contact_cc}" if request.contact_cc else "")
              + (f", тел. {request.contact_phone}" if request.contact_phone else ""))
        write(f"  запросил:    {request.requested_by_name or request.requested_by_id}"
              + (" (администратор портала)" if request.requested_by_admin else ""))
        write(f"  срок:        {months_text(request.months)}, цена {money_str(request.price_month)} ₽/мес")
        write(f"  сумма:       база {money_str(request.base_amount)}, скидка {money_str(request.discount_amount)}, "
              f"НДС {request.vat_mode} {request.vat_rate}% = {money_str(request.vat_amount)}, "
              f"итого {money_str(request.total_amount)} ₽")
        write(f"  оплатить до: {_fmt(request.due_date)}")
        write(f"  назначение:  {request.payment_purpose} ({len(request.payment_purpose)} симв.)")
        write(f"  CRM:         сделка {request.crm_deal_id or '—'}, счёт {request.crm_invoice_id or '—'}, "
              f"компания {request.crm_company_id or '—'}, документ {request.crm_document_id or '—'}, "
              f"задача {request.crm_task_id or '—'}, попыток {request.crm_attempts}")
        if crm is not None and request.crm_deal_id:
            write(f"               {crm.deal_link(request.crm_deal_id)}")
        if crm is not None and request.crm_invoice_id:
            write(f"               {crm.invoice_link(request.crm_invoice_id)}")
        if crm is not None and request.crm_task_id:
            write(f"               {crm.task_link(request.crm_task_id)}")
        if crm is None:
            write("               вебхук MAINSOFT_BILLING_WEBHOOK не задан — счёт выставляется вручную")
        if request.crm_error:
            write(self.style.WARNING(f"  ошибка CRM:  {request.crm_error}"))
        if request.status == ProRequest.STATUS_PAID:
            write(f"  оплата:      {_fmt(request.paid_on)}, отметил {request.paid_by}, Pro до {_fmt(request.pro_paid_until)}")
        if request.status == ProRequest.STATUS_CANCELLED:
            write(f"  отменена:    {request.cancelled_at:%d.%m.%Y %H:%M} UTC, {request.cancelled_by}: {request.cancel_reason}")

    def _paid(self, request: ProRequest, options):
        if request.status == ProRequest.STATUS_CANCELLED:
            raise CommandError(
                f"Счёт {request.invoice_number} отменён ({request.cancel_reason}). Если деньги пришли по нему, "
                "уточните у клиента, какая заявка действует: `pro_requests list --code "
                f"{request.portal_code}`."
            )
        paid_on = None
        if options.get("date"):
            try:
                paid_on = date.fromisoformat(options["date"].strip())
            except ValueError as exc:
                raise CommandError("--date: ожидается ГГГГ-ММ-ДД.") from exc
        request, change = service.mark_paid(
            request, actor=self._actor(options), paid_on=paid_on, comment=options.get("comment") or "",
        )
        self.stdout.write(self.style.SUCCESS(
            f"Счёт {request.invoice_number} оплачен, Pro включён: {request.domain_snapshot} "
            f"(код {request.portal_code}) до {_fmt(request.pro_paid_until)}."
        ))
        from main.management.commands.pro_plan import describe

        self.stdout.write(f"  было:  {describe(change.before)}")
        self.stdout.write(f"  стало: {describe(change.after)}")

    def _cancel(self, request: ProRequest, options):
        service.cancel_request(request, actor=self._actor(options), reason=options.get("reason") or "Отменена менеджером")
        self.stdout.write(self.style.SUCCESS(f"Заявка {request.invoice_number} отменена."))

    def _sync(self, options):
        crm = load_crm_settings()
        if crm is None:
            if not options.get("quiet"):
                self.stdout.write("MAINSOFT_BILLING_WEBHOOK не задан — отправлять некуда (безопасный режим).")
            return
        queryset = ProRequest.objects.all()
        if options.get("invoice"):
            queryset = queryset.filter(pk=service.find_request(invoice=options["invoice"]).pk)
        pending = list(queryset.filter(status__in=(ProRequest.STATUS_DRAFT, ProRequest.STATUS_PENDING)))
        # Счёт уже отправлен, но задача на контроль оплаты не создалась (сбой
        # tasks.task.add) — dispatch() идемпотентен: компанию, сделку и счёт
        # не пересоздаст, попытается только задачу.
        needs_task = [
            request for request in queryset.filter(status=ProRequest.STATUS_SENT, crm_task_id="")
            if request.crm_invoice_id
        ]
        cancels = [
            request for request in queryset.filter(status=ProRequest.STATUS_CANCELLED,
                                                    crm_cancel_synced_at__isnull=True)
            if request.crm_deal_id or request.crm_task_id
        ]
        if not pending and not needs_task and not cancels:
            if not options.get("quiet"):
                self.stdout.write("Отправлять нечего.")
            return
        for request in pending:
            service.dispatch(request, crm_settings=crm)
            label = STATUS_LABELS.get(request.status, request.status)
            suffix = f" — {request.crm_error}" if request.crm_error else ""
            self.stdout.write(f"{request.invoice_number}: {label}{suffix}")
        for request in needs_task:
            service.dispatch(request, crm_settings=crm)
            outcome = "задача досоздана" if request.crm_task_id else "задача не создана"
            suffix = f" — {request.crm_error}" if request.crm_error else ""
            self.stdout.write(f"{request.invoice_number}: {outcome}{suffix}")
        for request in cancels:
            done = service.sync_cancellation(request, crm_settings=crm)
            self.stdout.write(f"{request.invoice_number}: отмена {'донесена' if done else 'не дошла'} до CRM")
