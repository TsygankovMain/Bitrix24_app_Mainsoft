"""Демо-данные для мастера выставления счёта («Счёт и акт»).

Зачем. Показать функцию на стенде нечем: реальных списаний хватает, но
мастеру нужен закрытый месяц, один клиент на документ и несколько проектов
под ним. Команда достраивает именно это — списания за нужные месяцы и
закрытый период, — не трогая ни реальные записи, ни портал.

Четыре решения, без которых команду нельзя читать.

1. НОВЫХ КАРТОЧЕК И КОМПАНИЙ НЕ СОЗДАЁМ. Счёт — штатный смарт-счёт CRM:
   выдуманный company_id упрётся в портал на шаге создания счёта, и демо
   доедет до самого интересного места, чтобы там сломаться. Поэтому
   списания вешаются на СУЩЕСТВУЮЩИЕ карточки проектов с непустым
   company_id и ненулевой ставкой — те, что синхронизированы с портала.

2. ДЕМО-ЗАПИСЬ ВИДНА ГЛАЗОМ И НАЙДЁТСЯ ЗАПРОСОМ. Описание начинается с
   «ДЕМО: », bitrix_id лежит в выделенном диапазоне от 900 000 000. Признак
   двойной, и удаление (--purge) требует обоих: id из диапазона мог бы
   когда-нибудь прийти с портала, а префикс в описании человек может
   набрать руками — по отдельности ни то, ни другое не основание удалять
   чужой час.

3. ПОЛНАЯ СИНХРОНИЗАЦИЯ СНЕСЁТ ЭТО ВСЁ. timesheet_sync_service физически
   удаляет списания, которых нет в Битриксе, а демо-строк там нет по
   определению. Команда предупреждает об этом всегда и умеет выключить синк
   порталу на год (--freeze-sync, поле Bitrix24Account.sync_disabled_until).
   Выключать по умолчанию нельзя: стенд синкается не только ради демо.

4. МЕСЯЦ ЗАКРЫВАЕТСЯ ШТАТНОЙ СЕМАНТИКОЙ. Не «create(ClosedPeriod)», а
   PeriodCheckService.run + PeriodService.close с настоящим снимком stats —
   тем же, что кладёт эндпоинт period_close. Иначе демо показывало бы
   закрытие, которого в приложении нет.

Учётка или портал. Bitrix24Account в этом приложении — запись НА
СОТРУДНИКА, а данные скоуплены через tenant_scoping: при
USE_PORTAL_SCOPING=False у каждой учётки СВОЯ копия списаний, при True они
общие на портал. Команда повторяет выбор фонового синка
(sync_scheduler_service._account_scoped_sync_accounts): под флагом OFF пишет
каждой учётке портала, у которой есть карточки проектов, под ON — одному
представителю. Иначе демо было бы видно администратору и не видно
бухгалтеру.

Примеры:

    # план, ничего не пишем
    python manage.py billing_demo_data --domain nfr-mainsoft.bitrix24.ru --dry-run

    # наполнить август и сентябрь, август закрыть, синк выключить
    python manage.py billing_demo_data --domain nfr-mainsoft.bitrix24.ru \\
        --close-month 2026-08 --freeze-sync

    # убрать за собой
    python manage.py billing_demo_data --domain nfr-mainsoft.bitrix24.ru --purge
"""

import calendar
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from main.models import (
    Bitrix24Account,
    ClosedPeriod,
    PortalTask,
    PortalUser,
    ProjectCard,
    TimesheetItem,
)
from main.period_check_service import PeriodCheckService
from main.period_service import MONTHS, PeriodService
from main.tenant_scoping import portal_scoping_enabled, scope_to_tenant

# Признак демо-записи. Оба условия обязательны и при создании, и при удалении
# (см. докстринг модуля, пункт 2).
DEMO_PREFIX = "ДЕМО: "
DEMO_ID_BASE = 900_000_000

# Сдвиг для синтетических номеров задач: они живут в том же диапазоне, но
# заведомо выше любого разумного числа списаний, чтобы демо-задачу нельзя было
# перепутать с демо-списанием при чтении логов.
DEMO_TASK_OFFSET = 900_000

# Ключ в ClosedPeriod.stats: по нему --purge узнаёт свои периоды. Отдельного
# поля в модели не заводим — команда не повод менять схему, а stats для
# пометок и существует.
DEMO_STATS_FLAG = "demo_data"
DEMO_AUTHOR = "Демо-данные (billing_demo_data)"

FREEZE_DAYS = 365
FREEZE_REASON = "billing_demo_data --freeze-sync: демо-данные, синк выключен вручную"

DEFAULT_MONTHS = "2026-08,2026-09"
DEFAULT_ENTRIES = 120
DEFAULT_PROJECTS = 6
DEFAULT_CLIENTS = 3
DEFAULT_EMPLOYEES = 6
DEFAULT_SEED = 20260912

# Правдоподобные часы: шаг 0,5, перевес в сторону 1–3 часов. Ровно восьмёрки
# и получасовки бывают, но редко — если их сделать равновероятными, средний
# день в отчёте разъедется с реальностью.
HOUR_CHOICES = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0)
HOUR_WEIGHTS = (3, 7, 7, 9, 6, 6, 4, 3, 2, 1)

# Доля неоплачиваемых записей (is_billable=False) и доля записей без снимка
# ставки — чтобы в предпросмотре был виден путь «ставка из карточки проекта».
NON_BILLABLE_SHARE = 0.15
NO_SNAPSHOT_SHARE = 0.2

WORK_KINDS = (
    "консультация по настройке воронки",
    "доработка отчёта по проектам",
    "разбор обращения поддержки",
    "настройка бизнес-процесса согласования",
    "созвон с заказчиком по требованиям",
    "правка прав доступа в CRM",
    "перенос справочника контрагентов",
    "тестирование приёмки",
    "описание интеграции с 1С",
    "обновление шаблонов документов",
)


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


@dataclass
class DemoCard:
    """Карточка проекта, на которую вешаются демо-списания."""

    project_item_id: str
    project_id: str
    project_name: str
    hourly_rate: float
    company_id: str
    company_name: str
    tasks: List[Tuple[str, str]] = field(default_factory=list)


@dataclass
class DemoRow:
    """Одна запланированная запись. Пишется только при нормальном прогоне."""

    bitrix_id: int
    card: DemoCard
    employee_id: str
    employee_name: str
    task_id: str
    task_title: str
    day: date
    hours: float
    is_billable: bool
    rate_snapshot: Optional[float]
    description: str

    @property
    def rate(self) -> float:
        """Та же логика, что в BillingService.collect: снимок, иначе карточка."""
        if self.rate_snapshot is not None:
            return self.rate_snapshot
        return self.card.hourly_rate

    @property
    def amount(self) -> float:
        return round(self.hours * self.rate, 2)


class Command(BaseCommand):
    help = "Наполняет портал демо-списаниями под мастер выставления счёта «Счёт и акт»."

    # ------------------------------------------------------------------
    # Аргументы
    # ------------------------------------------------------------------

    def add_arguments(self, parser):
        parser.add_argument("--domain", default="", help="Домен портала (domain_url). Обязателен.")
        parser.add_argument(
            "--months", default=DEFAULT_MONTHS,
            help=f"Месяцы генерации через запятую, вид YYYY-MM (по умолчанию {DEFAULT_MONTHS}).",
        )
        parser.add_argument(
            "--entries-per-month", type=int, default=DEFAULT_ENTRIES,
            help=f"Сколько списаний создать на каждый месяц (по умолчанию {DEFAULT_ENTRIES}).",
        )
        parser.add_argument(
            "--projects", type=int, default=DEFAULT_PROJECTS,
            help=f"Сколько карточек проектов задействовать (по умолчанию {DEFAULT_PROJECTS}).",
        )
        parser.add_argument(
            "--clients", type=int, default=DEFAULT_CLIENTS,
            help=(
                "По скольким клиентам разложить проекты (по умолчанию "
                f"{DEFAULT_CLIENTS}). Один документ — один клиент, поэтому в демо "
                "их должно быть несколько, но немного."
            ),
        )
        parser.add_argument(
            "--employees", type=int, default=DEFAULT_EMPLOYEES,
            help=f"Сколько сотрудников задействовать (по умолчанию {DEFAULT_EMPLOYEES}).",
        )
        parser.add_argument(
            "--close-month", default="",
            help="Какие месяцы закрыть после генерации, вид YYYY-MM через запятую.",
        )
        parser.add_argument(
            "--freeze-sync", action="store_true",
            help=f"Выключить синхронизацию порталу на {FREEZE_DAYS} дней, чтобы демо не снесло.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Только план, ничего не писать.")
        parser.add_argument(
            "--purge", action="store_true",
            help="Удалить демо-списания и закрытые демо-периоды и выйти.",
        )
        parser.add_argument(
            "--replace", action="store_true",
            help="Сначала удалить прежнее демо, потом сгенерировать заново.",
        )
        parser.add_argument(
            "--id-base", type=int, default=DEMO_ID_BASE,
            help=f"Начало диапазона bitrix_id для демо-записей (по умолчанию {DEMO_ID_BASE}).",
        )
        parser.add_argument(
            "--seed", type=int, default=DEFAULT_SEED,
            help="Зерно генератора: с одним зерном прогон повторяется один в один.",
        )

    # ------------------------------------------------------------------
    # Основной сценарий
    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        self.dry_run = bool(options["dry_run"])
        self.id_base = int(options["id_base"])
        if self.id_base <= 0:
            raise CommandError("--id-base должен быть положительным числом.")

        domain = _clean(options["domain"])
        if not domain:
            raise CommandError("Нужен --domain: команда работает по конкретному порталу.")

        accounts = self._portal_accounts(domain)
        targets = self._data_accounts(accounts)

        self._say(f"Портал {domain}: учёток — {len(accounts)}, под запись попадают {len(targets)}.")
        if self.dry_run:
            self._say(self.style.WARNING("Режим --dry-run: ниже только план, в базу ничего не пишется."))

        if options["purge"] or options["replace"]:
            self._purge(targets)
            if options["purge"] and not options["replace"]:
                self._say("Готово: демо-данные удалены, генерация не запускалась.")
                return

        months = self._parse_months(options["months"], "--months")
        if not months:
            raise CommandError("Список --months пуст: генерировать нечего.")
        close_months = self._parse_months(options["close_month"], "--close-month")
        unknown = [m for m in close_months if m not in months]
        if unknown:
            # Не отказ: закрыть можно и месяц с реальными данными. Но молчать
            # нельзя — чаще всего это опечатка в YYYY-MM.
            self._say(self.style.WARNING(
                "Внимание: в --close-month месяцы, которых нет в --months: "
                + ", ".join(f"{y}-{mo:02d}" for y, mo in unknown)
            ))

        plans: List[Tuple[Bitrix24Account, List[DemoRow]]] = []
        for account in targets:
            self._check_id_range(account, options)
            plans.append((account, self._build_plan(account, months, options)))

        if not self.dry_run:
            for account, rows in plans:
                self._write(account, rows)

        closed = self._close_months(targets, close_months)
        frozen = self._freeze_sync(accounts) if options["freeze_sync"] else []

        self._report(domain, plans, months, closed, frozen, options)

    # ------------------------------------------------------------------
    # Порталы и учётки
    # ------------------------------------------------------------------

    def _portal_accounts(self, domain: str) -> List[Bitrix24Account]:
        """Все учётки портала. Домен мог быть задан один, а учёток несколько.

        Добор по member_id — тот же приём, что в billing_feature: портал, а не
        учётка, иначе демо будет видно одному сотруднику.
        """
        found = list(Bitrix24Account.objects.filter(domain_url=domain))
        if not found:
            known = sorted({
                row["domain_url"] for row in Bitrix24Account.objects.values("domain_url")
            })
            raise CommandError(
                f"Портал {domain} не найден. Известные домены: "
                + (", ".join(known) if known else "ни одного — приложение никуда не установлено.")
            )
        member_ids = {account.member_id for account in found if account.member_id}
        if member_ids:
            found = list(Bitrix24Account.objects.filter(member_id__in=member_ids))
        return sorted(found, key=lambda a: (not a.is_master_account, a.b24_user_id))

    def _data_accounts(self, accounts: Sequence[Bitrix24Account]) -> List[Bitrix24Account]:
        """Учётки, которым реально нужно писать демо.

        Под USE_PORTAL_SCOPING=True данные общие на портал — хватает одного
        представителя, и писать всем означало бы размножить каждую запись.
        Под False копия своя у каждой учётки, но интересны только те, у кого
        есть карточки проектов: остальным вешать списания не на что.
        """
        if portal_scoping_enabled():
            with_portal = [account for account in accounts if account.portal_id]
            return (with_portal or list(accounts))[:1]

        targets = [
            account for account in accounts
            if ProjectCard.objects.filter(bitrix24_account=account)
            .exclude(company_id__in=["", None]).exists()
        ]
        if not targets:
            raise CommandError(
                "Ни у одной учётки портала нет карточек проектов с заполненным клиентом. "
                "Сначала синхронизируйте проекты: manage.py sync_all_portals --scope project."
            )
        return targets

    # ------------------------------------------------------------------
    # Разбор аргументов
    # ------------------------------------------------------------------

    def _parse_months(self, raw: str, flag: str) -> List[Tuple[int, int]]:
        result: List[Tuple[int, int]] = []
        for chunk in _clean(raw).split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                year, month = chunk.split("-")
                key = (int(year), int(month))
            except (ValueError, TypeError) as exc:
                raise CommandError(f"{flag}: «{chunk}» не похоже на YYYY-MM.") from exc
            if not 1 <= key[1] <= 12:
                raise CommandError(f"{flag}: месяц {key[1]} не существует.")
            if key not in result:
                result.append(key)
        return result

    # ------------------------------------------------------------------
    # Проверка диапазона id
    # ------------------------------------------------------------------

    def _check_id_range(self, account: Bitrix24Account, options) -> None:
        """Диапазон демо-id должен быть свободен — иначе отказ, а не перезапись.

        Два разных отказа. Чужая запись в диапазоне значит, что база
        рассчитана не на наш base: перебить её было бы утратой реального часа.
        Своя демо-запись значит «команда уже прогонялась»: повторный прогон
        плодил бы дубли, поэтому просим --purge или --replace явно.
        """
        scope = scope_to_tenant(account)
        in_range = TimesheetItem.objects.filter(**scope, bitrix_id__gte=self.id_base)

        intruders = in_range.exclude(description__startswith=DEMO_PREFIX).count()
        if intruders:
            raise CommandError(
                f"В диапазоне от {self.id_base} есть {intruders} НЕ демо-записей "
                f"(учётка {account.b24_user_id}). Возьмите свободный диапазон: --id-base."
            )

        existing = in_range.count()
        if existing and not self.dry_run:
            raise CommandError(
                f"Демо-записи уже есть ({existing} шт., учётка {account.b24_user_id}). "
                "Повторный прогон плодил бы дубли: запустите с --purge (убрать) "
                "или с --replace (пересоздать)."
            )
        if existing:
            self._say(self.style.WARNING(
                f"Учётка {account.b24_user_id}: демо-записей уже {existing} — "
                "настоящий прогон потребует --purge или --replace."
            ))

    # ------------------------------------------------------------------
    # План генерации
    # ------------------------------------------------------------------

    def _cards(self, account: Bitrix24Account, options) -> List[DemoCard]:
        """Карточки под демо: свой клиент, своя ставка, разложены по клиентам.

        Ставка обязательна: нулевая даёт предупреждение no_rate и счёт на
        нуль — демо, которое показывает не то, что нужно показать.

        Раскладка по клиентам не косметика. Документ — один клиент (правило 4
        контракта), поэтому проекты берутся кругами по нескольким крупнейшим
        клиентам: так у каждого клиента демо оказывается по 2–3 проекта, то
        есть счёт из нескольких строк, а не из одной.
        """
        rows = (
            ProjectCard.objects.filter(**scope_to_tenant(account))
            .exclude(company_id__in=["", None])
            .filter(hourly_rate__gt=0)
            .values(
                "project_item_id", "project_id", "project_name",
                "hourly_rate", "company_id", "company_name",
            )
        )
        by_company: Dict[str, List[DemoCard]] = {}
        for row in rows:
            card = DemoCard(
                project_item_id=_clean(row["project_item_id"]),
                project_id=_clean(row["project_id"]),
                project_name=_clean(row["project_name"]) or f"Проект {_clean(row['project_id'])}",
                hourly_rate=float(row["hourly_rate"] or 0),
                company_id=_clean(row["company_id"]),
                company_name=_clean(row["company_name"]) or f"Компания {_clean(row['company_id'])}",
            )
            by_company.setdefault(card.company_id, []).append(card)

        if not by_company:
            raise CommandError(
                f"У учётки {account.b24_user_id} нет карточек проектов с клиентом и ставкой. "
                "Демо-списание вешать не на что, а новые карточки команда не создаёт: "
                "выдуманная компания не даст создать смарт-счёт в CRM."
            )

        for cards in by_company.values():
            cards.sort(key=lambda item: item.project_name)
        order = sorted(by_company, key=lambda key: (-len(by_company[key]), key))
        wanted_clients = max(1, int(options["clients"]))
        order = order[:wanted_clients]

        wanted = max(1, int(options["projects"]))
        picked: List[DemoCard] = []
        depth = 0
        while len(picked) < wanted:
            added = False
            for company_id in order:
                cards = by_company[company_id]
                if depth < len(cards) and len(picked) < wanted:
                    picked.append(cards[depth])
                    added = True
            if not added:
                break
            depth += 1

        if len(picked) < wanted:
            self._say(self.style.WARNING(
                f"Учётка {account.b24_user_id}: запрошено проектов {wanted}, "
                f"подходящих карточек — {len(picked)}."
            ))
        self._attach_tasks(account, picked)
        return picked

    def _attach_tasks(self, account: Bitrix24Account, cards: Sequence[DemoCard]) -> None:
        """Задачи проекта из справочника портала, иначе — свои демо-задачи.

        Брать задачу «любую, какая была в списаниях» нельзя: проверка перед
        закрытием считает блокером расхождение проекта записи с группой
        задачи (PeriodCheckService._diverged_tasks), и демо само себе закрыло
        бы дорогу к закрытию месяца. Поэтому либо задача, которая ДЕЙСТВИТЕЛЬНО
        лежит в этой группе, либо синтетическая — её в справочнике нет вовсе,
        и расхождения не возникает по определению.
        """
        scope = scope_to_tenant(account)
        for index, card in enumerate(cards):
            real = list(
                PortalTask.objects.filter(**scope, group_id=card.project_id)
                .exclude(bitrix_id="")
                .order_by("bitrix_id")
                .values("bitrix_id", "title")[:5]
            )
            if real:
                card.tasks = [
                    (_clean(row["bitrix_id"]), _clean(row["title"]) or f"Задача {row['bitrix_id']}")
                    for row in real
                ]
                continue
            card.tasks = [
                (
                    str(self.id_base + DEMO_TASK_OFFSET + index * 10 + offset),
                    f"{DEMO_PREFIX}задача {offset + 1} по проекту «{card.project_name}»",
                )
                for offset in range(3)
            ]

    def _employees(self, account: Bitrix24Account, options) -> List[Tuple[str, str]]:
        """Сотрудники: справочник портала, иначе — те, кто уже списывал часы."""
        rows = (
            PortalUser.objects.filter(**scope_to_tenant(account), active=True)
            .exclude(bitrix_id="")
            .order_by("bitrix_id")
            .values("bitrix_id", "name", "last_name")
        )
        people = [
            (
                _clean(row["bitrix_id"]),
                f"{_clean(row['last_name'])} {_clean(row['name'])}".strip() or _clean(row["bitrix_id"]),
            )
            for row in rows
        ]
        if not people:
            ids = (
                TimesheetItem.objects.filter(**scope_to_tenant(account))
                .exclude(employee_id__in=["", None])
                .values_list("employee_id", flat=True)
                .distinct()
                .order_by("employee_id")
            )
            people = [(_clean(value), f"Сотрудник {_clean(value)}") for value in ids]
        if not people:
            raise CommandError(
                f"У учётки {account.b24_user_id} нет ни пользователей портала, ни списаний — "
                "взять сотрудников для демо неоткуда."
            )
        return people[: max(1, int(options["employees"]))]

    def _working_days(self, year: int, month: int) -> List[date]:
        """Рабочие дни месяца, не позже сегодняшнего.

        Списания «из будущего» в отчёте выглядят ошибкой синка, а не демо,
        поэтому текущий месяц заполняется только по сегодня.
        """
        last = calendar.monthrange(year, month)[1]
        today = timezone.localdate()
        days = [
            date(year, month, day)
            for day in range(1, last + 1)
            if date(year, month, day).weekday() < 5
        ]
        days = [day for day in days if day <= today]
        return days

    def _build_plan(self, account: Bitrix24Account, months: Sequence[Tuple[int, int]], options) -> List[DemoRow]:
        cards = self._cards(account, options)
        people = self._employees(account, options)
        # Зерно НЕ зависит от учётки сознательно: под USE_PORTAL_SCOPING=False
        # у каждой учётки портала своя копия одних и тех же данных, и демо
        # обязано совпадать у администратора и у бухгалтера — иначе они видят
        # разные часы и спорят о суммах.
        rng = random.Random(options["seed"])

        per_month = max(0, int(options["entries_per_month"]))
        rows: List[DemoRow] = []
        next_id = self.id_base
        # Ключ «задача + день + сотрудник + часы» — ровно тот, по которому
        # проверка перед закрытием ищет дубли. Совпадений не допускаем: демо
        # не должно приносить с собой находок, которых в нём нет по смыслу.
        seen: set = set()

        for year, month in months:
            days = self._working_days(year, month)
            if not days:
                self._say(self.style.WARNING(
                    f"{MONTHS[month]} {year}: рабочих дней в прошлом нет — месяц пропущен."
                ))
                continue
            for index in range(per_month):
                card = cards[index % len(cards)]
                employee_id, employee_name = people[rng.randrange(len(people))]
                task_id, task_title = card.tasks[rng.randrange(len(card.tasks))]
                day = days[rng.randrange(len(days))]

                hours = 0.0
                for _attempt in range(12):
                    hours = rng.choices(HOUR_CHOICES, weights=HOUR_WEIGHTS, k=1)[0]
                    if (task_id, day, employee_id, hours) not in seen:
                        break
                else:
                    continue
                seen.add((task_id, day, employee_id, hours))

                is_billable = rng.random() >= NON_BILLABLE_SHARE
                rate_snapshot = None if rng.random() < NO_SNAPSHOT_SHARE else card.hourly_rate
                rows.append(DemoRow(
                    bitrix_id=next_id,
                    card=card,
                    employee_id=employee_id,
                    employee_name=employee_name,
                    task_id=task_id,
                    task_title=task_title,
                    day=day,
                    hours=hours,
                    is_billable=is_billable,
                    rate_snapshot=rate_snapshot,
                    description=(
                        f"{DEMO_PREFIX}{WORK_KINDS[index % len(WORK_KINDS)]} "
                        f"({card.project_name})"
                    ),
                ))
                next_id += 1
        return rows

    # ------------------------------------------------------------------
    # Запись
    # ------------------------------------------------------------------

    @transaction.atomic
    def _write(self, account: Bitrix24Account, rows: Sequence[DemoRow]) -> None:
        scope = scope_to_tenant(account, write=True)
        items = [
            TimesheetItem(
                **scope,
                bitrix_id=row.bitrix_id,
                task_id=row.task_id,
                employee_id=row.employee_id,
                hours=row.hours,
                is_billable=row.is_billable,
                non_billable_hours=0.0 if row.is_billable else row.hours,
                description=row.description,
                project_id=row.card.project_id,
                project_item_id=row.card.project_item_id or None,
                project_title=row.card.project_name,
                hourly_rate_snapshot=row.rate_snapshot,
                task_hierarchy_ids=[row.card.project_id, row.task_id],
                task_hierarchy_titles=[row.card.project_name, row.task_title],
                date_reflection=self._aware(row.day),
                source_created_at=self._aware(row.day) + timedelta(hours=18),
            )
            for row in rows
        ]
        TimesheetItem.objects.bulk_create(items, batch_size=500)

    def _aware(self, day: date) -> datetime:
        """Полночь той же календарной даты — как в реальных данных портала.

        PeriodService намеренно берёт месяц прямо из даты: на проде почти все
        списания лежат ровно на 00:00, потому что дату выбирают в календаре.
        Демо повторяет это, иначе запись у границы месяца уедет в соседний.
        """
        return timezone.make_aware(datetime(day.year, day.month, day.day, 0, 0))

    # ------------------------------------------------------------------
    # Удаление
    # ------------------------------------------------------------------

    def _purge(self, targets: Sequence[Bitrix24Account]) -> None:
        items_total = 0
        periods_total = 0
        for account in targets:
            scope = scope_to_tenant(account)
            queryset = TimesheetItem.objects.filter(
                **scope,
                bitrix_id__gte=self.id_base,
                description__startswith=DEMO_PREFIX,
            )
            count = queryset.count()
            if count and not self.dry_run:
                queryset.delete()
            items_total += count

            # stats фильтруем в Python: JSON-лукапы ведут себя по-разному на
            # PostgreSQL и sqlite, а периодов на портале единицы.
            periods = [
                period
                for period in ClosedPeriod.objects.filter(**scope)
                if (period.stats or {}).get(DEMO_STATS_FLAG) is True
            ]
            for period in periods:
                if not self.dry_run:
                    period.delete()
            periods_total += len(periods)

        verb = "нашлось" if self.dry_run else "удалено"
        self._say(f"Очистка: демо-списаний {verb} — {items_total}, демо-периодов — {periods_total}.")

    # ------------------------------------------------------------------
    # Закрытие месяца
    # ------------------------------------------------------------------

    def _close_months(
        self, targets: Sequence[Bitrix24Account], months: Sequence[Tuple[int, int]]
    ) -> List[str]:
        """Закрывает месяцы штатной семантикой — снимком stats и порядком.

        Порядок закрытия (от старых к новым) и блокеры проверки здесь не
        отказ, а предупреждение: на стенде в реальных данных вполне может
        лежать запись без проекта, и демо не должно из-за неё останавливаться.
        Зато находки уезжают в stats.blockers_at_close — тем же полем, каким
        их фиксирует пакетное закрытие в views.period_close_bulk.
        """
        done: List[str] = []
        for year, month in months:
            title = f"{MONTHS[month]} {year}"
            for account in targets:
                periods = PeriodService(account)
                earliest = periods.earliest_open_period()
                if earliest is not None and earliest != (year, month):
                    self._say(self.style.WARNING(
                        f"{title}: раньше него открыт {MONTHS[earliest[1]]} {earliest[0]}. "
                        "Штатное закрытие требует порядка от старых к новым — демо закрывает всё равно."
                    ))

                check = PeriodCheckService(account).run(year, month)
                if not check["can_close"]:
                    codes = ", ".join(item["code"] for item in check["blockers"])
                    self._say(self.style.WARNING(
                        f"{title}: проверка нашла блокеры ({codes}) — записаны в stats, закрываем."
                    ))
                if self.dry_run:
                    continue

                stats = dict(check["stats"])
                stats["blockers_at_close"] = check["blockers"]
                stats[DEMO_STATS_FLAG] = True
                periods.close(
                    year, month, stats=stats,
                    by_id=str(account.b24_user_id or ""), by_name=DEMO_AUTHOR,
                )
            done.append(title)
        return done

    # ------------------------------------------------------------------
    # Пауза синка
    # ------------------------------------------------------------------

    def _freeze_sync(self, accounts: Sequence[Bitrix24Account]) -> List[str]:
        """Выключает синк ВСЕМ учёткам портала на год.

        Всем, а не только тем, кому писали демо: полную сверку запускает любая
        учётка, способная авторизоваться (sync_scheduler_service), и одна
        забытая снесёт демо у всего портала.
        """
        until = timezone.now() + timedelta(days=FREEZE_DAYS)
        touched: List[str] = []
        for account in accounts:
            touched.append(str(account.b24_user_id))
            if self.dry_run:
                continue
            account.sync_disabled_until = until
            account.sync_failure_reason = FREEZE_REASON[:255]
            account.save(update_fields=["sync_disabled_until", "sync_failure_reason"])
        self._say(
            ("Синк был бы выключен до " if self.dry_run else "Синк выключен до ")
            + f"{until:%d.%m.%Y} у учёток: {', '.join(touched)}."
        )
        return touched

    # ------------------------------------------------------------------
    # Итог
    # ------------------------------------------------------------------

    def _report(self, domain, plans, months, closed, frozen, options) -> None:
        self._say("")
        self._say(self.style.MIGRATE_HEADING(
            "План демо-данных" if self.dry_run else "Демо-данные созданы"
        ))

        if not plans or not any(rows for _account, rows in plans):
            self._say("Записей не запланировано: проверьте --months и --entries-per-month.")
            return

        # Отчёт по первой учётке: под USE_PORTAL_SCOPING=False остальным
        # пишется та же выборка, и повторять её числа незачем — вместо этого
        # ниже одна строка «столько же у остальных».
        account, rows = plans[0]
        self._say(f"Портал: {domain}, учётка-образец {account.b24_user_id}.")
        if len(plans) > 1:
            others = ", ".join(
                f"{acc.b24_user_id} — {len(other)}" for acc, other in plans[1:]
            )
            self._say(
                f"Остальным учёткам портала записан тот же набор (учётка {others}); "
                "всего по учётке-образцу — "
                f"{len(rows)}."
            )

        for year, month in months:
            month_rows = [row for row in rows if (row.day.year, row.day.month) == (year, month)]
            if not month_rows:
                continue
            billable = [row for row in month_rows if row.is_billable]
            self._say("")
            self._say(f"— {MONTHS[month]} {year}: записей {len(month_rows)}, "
                      f"из них оплачиваемых {len(billable)}")
            self._say(f"  часы: всего {self._hours(month_rows)}, оплачиваемых {self._hours(billable)}")
            self._say(f"  сумма по оплачиваемым: {self._money(billable)} ₽")
            self._say(f"  без снимка ставки: {sum(1 for r in month_rows if r.rate_snapshot is None)} "
                      "(ставка возьмётся из карточки проекта)")

            for company_id, company_rows in self._by_company(billable):
                name = company_rows[0].card.company_name
                projects = sorted({row.card.project_name for row in company_rows})
                self._say(
                    f"  · {name} (company_id {company_id}): "
                    f"{self._hours(company_rows)} ч, {self._money(company_rows)} ₽"
                )
                self._say(f"    проекты: {', '.join(projects)}")

        self._say("")
        if closed:
            verb = "закрылись бы" if self.dry_run else "закрыты"
            self._say(f"Периоды {verb}: {', '.join(closed)} (автор — «{DEMO_AUTHOR}»).")
        else:
            self._say(self.style.WARNING(
                "Закрытых периодов нет. Мастер по умолчанию выставляет только за закрытый "
                "месяц: перезапустите с --close-month YYYY-MM либо включите настройку портала "
                "«Разрешить выставление за открытый период»."
            ))

        self._say("")
        self._say(self.style.WARNING(
            "ВАЖНО: полная синхронизация (sync_all_portals --scope timesheet --full, "
            "она же ночная) физически удаляет списания, которых нет в Битриксе. "
            "Демо-строк на портале нет — она снесёт их целиком."
        ))
        if frozen:
            self._say("Синк выключен на год — демо не пропадёт. Вернуть: обнулить "
                      "sync_disabled_until у учёток портала.")
        else:
            self._say("Чтобы демо жило дольше первой ночи, перезапустите с --freeze-sync.")

        self._say("")
        self._say("Что дальше:")
        self._say(f"  1. Включить функцию: manage.py billing_feature --domain {domain} --state on")
        example = self._example(rows, closed)
        if example:
            self._say(f"  2. В мастере выставления выбрать клиента «{example[0]}» за {example[1]}.")
        else:
            self._say("  2. Открыть мастер выставления и выбрать клиента с созданными часами.")
        self._say("  3. Группировка по умолчанию — по проектам: строк в счёте будет столько же, "
                  "сколько проектов у клиента.")
        self._say(f"  4. Убрать за собой: тот же вызов с --purge (ищет «{DEMO_PREFIX}» "
                  f"и id от {self.id_base}).")

    def _example(self, rows: Sequence[DemoRow], closed: Sequence[str]) -> Optional[Tuple[str, str]]:
        """Крупнейший клиент закрытого месяца — им и показывать функцию."""
        if not closed:
            return None
        target = closed[0]
        candidates = [
            row for row in rows
            if row.is_billable and f"{MONTHS[row.day.month]} {row.day.year}" == target
        ]
        if not candidates:
            return None
        best = max(self._by_company(candidates), key=lambda pair: self._raw_money(pair[1]))
        return best[1][0].card.company_name, target

    def _by_company(self, rows: Sequence[DemoRow]) -> List[Tuple[str, List[DemoRow]]]:
        buckets: Dict[str, List[DemoRow]] = {}
        for row in rows:
            buckets.setdefault(row.card.company_id, []).append(row)
        return sorted(buckets.items(), key=lambda pair: pair[1][0].card.company_name)

    def _hours(self, rows: Sequence[DemoRow]) -> str:
        return f"{round(sum(row.hours for row in rows), 2):g}"

    def _raw_money(self, rows: Sequence[DemoRow]) -> float:
        return round(sum(row.amount for row in rows), 2)

    def _money(self, rows: Sequence[DemoRow]) -> str:
        return f"{self._raw_money(rows):,.2f}".replace(",", " ")

    def _say(self, text: str) -> None:
        self.stdout.write(text)
