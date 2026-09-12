"""Включение и выключение платной функции порталу.

Единственный способ поменять PortalFeature. REST на запись нет и быть не
должно: app.option портала пишется токеном приложения, то есть из консоли
браузера, и подписка включалась бы бесплатно.

Портал, а не учётка. Bitrix24Account в этом приложении — запись НА
СОТРУДНИКА (уникальность по паре «пользователь + домен»), поэтому команда
пишет строку КАЖДОЙ учётке портала: иначе функция, включённая
администратору, была бы выключена у бухгалтера. Чтение состояния устроено
симметрично (billing_features.get_feature_state).

Примеры:

    python manage.py billing_feature --list
    python manage.py billing_feature --domain mainsoft.bitrix24.ru --state on
    python manage.py billing_feature --member-id abc123 --state trial --trial-days 14
    python manage.py billing_feature --domain client.bitrix24.ru --state off \\
        --comment "подписка не продлена"
"""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from main.models import Bitrix24Account, PortalFeature


class Command(BaseCommand):
    help = "Включает и выключает платные функции портала (PortalFeature)."

    def add_arguments(self, parser):
        parser.add_argument("--domain", default="", help="Домен портала (domain_url).")
        parser.add_argument("--member-id", default="", help="member_id портала.")
        parser.add_argument(
            "--code", default=PortalFeature.CODE_BILLING,
            help=f"Код функции: {', '.join(PortalFeature.CODES)} (по умолчанию billing).",
        )
        parser.add_argument(
            "--state", default="",
            help=f"Новое состояние: {', '.join(PortalFeature.STATES)}.",
        )
        parser.add_argument("--trial-days", type=int, default=0, help="Срок теста в днях для state=trial.")
        parser.add_argument("--trial-until", default="", help="Дата окончания теста, YYYY-MM-DD.")
        parser.add_argument("--comment", default="", help="Комментарий к записи.")
        parser.add_argument("--list", action="store_true", help="Показать текущие состояния и выйти.")

    def handle(self, *args, **options):
        code = (options["code"] or "").strip()
        if code not in PortalFeature.CODES:
            raise CommandError(f"Неизвестный код функции: {code}. Допустимы: {', '.join(PortalFeature.CODES)}.")

        if options["list"]:
            self._list(code, options)
            return

        state = (options["state"] or "").strip()
        if state not in PortalFeature.STATES:
            raise CommandError(
                f"Укажите --state из списка: {', '.join(PortalFeature.STATES)} (или --list для просмотра)."
            )

        accounts = self._accounts(options)
        if not accounts:
            raise CommandError("Портал не найден: укажите существующий --domain или --member-id.")

        trial_until = self._trial_until(state, options)

        touched = 0
        for account in accounts:
            PortalFeature.objects.update_or_create(
                bitrix24_account=account,
                code=code,
                defaults={
                    "portal": account.portal,
                    "state": state,
                    "trial_until": trial_until,
                    "comment": options["comment"] or "",
                },
            )
            touched += 1

        target = options["domain"] or options["member_id"]
        self.stdout.write(self.style.SUCCESS(
            f"{code}={state} для портала {target}: обновлено учёток — {touched}"
            + (f", тест до {trial_until:%d.%m.%Y}" if trial_until else "")
        ))

    def _accounts(self, options):
        domain = (options["domain"] or "").strip()
        member_id = (options["member_id"] or "").strip()
        if not domain and not member_id:
            raise CommandError("Нужен --domain или --member-id: функция включается порталу целиком.")

        queryset = Bitrix24Account.objects.all()
        if member_id:
            queryset = queryset.filter(member_id=member_id)
        if domain:
            queryset = queryset.filter(domain_url=domain)

        accounts = list(queryset)
        if not accounts:
            return []

        # Домен мог быть задан один, а учёток портала — несколько; добираем
        # всех по member_id найденных, иначе функция включится не всем.
        member_ids = {account.member_id for account in accounts if account.member_id}
        if member_ids:
            accounts = list(Bitrix24Account.objects.filter(member_id__in=member_ids))
        return accounts

    def _trial_until(self, state, options):
        if state != PortalFeature.STATE_TRIAL:
            return None
        raw = (options["trial_until"] or "").strip()
        if raw:
            parsed = timezone.datetime.fromisoformat(raw)
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed)
            return parsed
        days = int(options["trial_days"] or 0)
        if days > 0:
            return timezone.now() + timedelta(days=days)
        # Бессрочный тест — сознательный выбор оператора, а не оплошность:
        # молча выключать выданный доступ хуже, чем оставить его до явной
        # команды. См. PortalFeature.is_enabled.
        return None

    def _list(self, code, options):
        rows = PortalFeature.objects.filter(code=code).select_related("bitrix24_account")
        domain = (options["domain"] or "").strip()
        member_id = (options["member_id"] or "").strip()
        if domain:
            rows = rows.filter(bitrix24_account__domain_url=domain)
        if member_id:
            rows = rows.filter(bitrix24_account__member_id=member_id)

        seen = {}
        for row in rows:
            key = row.bitrix24_account.member_id or str(row.bitrix24_account.pk)
            seen.setdefault(key, (row.bitrix24_account.domain_url, row.state, row.trial_until, 0))
            domain_url, state, until, count = seen[key]
            seen[key] = (domain_url, state, until, count + 1)

        if not seen:
            self.stdout.write(f"Функция {code} не включена ни одному порталу.")
            return

        for key, (domain_url, state, until, count) in sorted(seen.items()):
            suffix = f", тест до {until:%d.%m.%Y}" if until else ""
            self.stdout.write(f"{domain_url or key}: {code}={state}{suffix} (учёток: {count})")
