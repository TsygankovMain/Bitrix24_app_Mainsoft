"""Сборка, выставление и отмена документа «Счёт и акт».

Ядро функции. CRM здесь не вызывается — за неё отвечает billing_crm_service;
этот модуль отбирает списания, считает суммы и владеет транзакцией записи.

Три вещи, которые здесь важнее остального.

1. Документ хранит СНИМОК. Синхронизация физически удаляет списания,
   пропавшие в Битриксе (timesheet_sync_service), а само списание уникально
   по паре «учётка + bitrix_id»: ссылаться на TimesheetItem.pk нельзя.
   Поэтому BillingEntry помнит часы, ставку, сумму, сотрудника и задачу, а на
   списание ссылается только по bitrix_id. Пересчёта документа не бывает
   никогда; расхождение со снимком показывается как drift.

2. Двойное выставление ловит БАЗА, а не проверка в коде: частичный
   уникальный индекс на (bitrix24_account, timesheet_bitrix_id) при
   is_active=True. Проверка в коде остаётся — она нужна для понятного 409 со
   ссылкой на существующий документ, — но последнее слово за индексом: два
   бухгалтера, нажавшие «Выставить» одновременно, проверку в коде обходят.

3. Порядок «сначала наша БД, потом CRM». Документ и потреблённые списания
   пишутся в одной транзакции ДО создания счёта в CRM, потому что конфликт
   индекса должен всплыть раньше, чем на портале появится лишний счёт —
   удалить его мы не сможем. Если CRM-шаг падает, документ снимается
   (billing_crm_service.issue_document): без crm_entity_id — удалением, с
   полученным id — отменой, чтобы след остался.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .employee_ids import build_employee_id_aliases, resolve_employee_name
from .models import (
    BillingDocument,
    BillingEntry,
    BillingLine,
    PortalUser,
    TimesheetItem,
)
from .period_service import PeriodService, period_of
from .project_board_shared import get_project_card_queryset
from .report_queries import build_project_match_q, build_task_lookup
from .tenant_scoping import scope_to_tenant

logger = logging.getLogger(__name__)
audit = logging.getLogger("main.audit")

GROUPINGS = ("project", "task", "employee", "single")
DEFAULT_GROUPING = "project"

WARNING_PERIOD_OPEN = "period_open"
WARNING_ALREADY_INVOICED = "already_invoiced"
WARNING_NO_RATE = "no_rate"
WARNING_MIXED_COMPANIES = "mixed_companies"

# Отказ по утверждённым строкам (поле lines[] в теле выставления).
ERROR_LINES_MISMATCH = "lines_mismatch"

# Допуск сравнения строки с отбором. Часы и цена приходят от клиента
# округлёнными до копейки — «половина копейки» ловит настоящее расхождение и
# не ловит след округления.
LINE_TOLERANCE = 0.005


class BillingError(Exception):
    """Отказ выставления с кодом для интерфейса.

    status — HTTP-код ответа: 400 для негодного отбора, 409 для конфликта с
    уже выставленным документом, 502 для сбоя на стороне портала.
    """

    def __init__(self, message: str, code: str, *, status: int = 400, extra: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.extra = extra or {}

    def as_payload(self) -> Dict[str, Any]:
        payload = {"error": self.message, "code": self.code}
        payload.update(self.extra)
        return payload


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _money(value: float) -> float:
    """Копейки. Округляем каждую сумму строки отдельно, итог — сумма строк."""
    return round(_num(value) + 0.0, 2)


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _as_list(value: Any) -> List[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (str, int)):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    result: List[str] = []
    for item in value:
        if item is None:
            continue
        text = _clean(item)
        if text and text not in result:
            result.append(text)
    return result


def _opt_num(value: Any, what: str) -> Optional[float]:
    """Число из lines[]: None — «не прислали», мусор — отказ, а не ноль.

    _num() здесь не годится: он превращает в ноль всё, что не разобрал, а
    ноль в строке счёта — это отданная даром работа. Непонятное значение
    обязано остановить выставление, а не тихо обнулить сумму.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise BillingError(f"Не удалось прочитать {what}: ожидалось число.", ERROR_LINES_MISMATCH)
    try:
        if isinstance(value, str):
            return float(value.strip().replace(",", "."))
        return float(value)
    except (TypeError, ValueError) as exc:
        raise BillingError(f"Не удалось прочитать {what}: «{value}».", ERROR_LINES_MISMATCH) from exc


def _hours_text(value: Optional[float]) -> str:
    return f"{round(_num(value), 2):g}"


@dataclass
class ApprovedLine:
    """Строка, утверждённая человеком в предпросмотре (элемент lines[]).

    Часы здесь справочные: править их мастер не даёт, и сервер принимает
    только совпавшие с отбором. Править можно текст и цену.
    """

    position: int
    project_id: str = ""
    title: str = ""
    hours: Optional[float] = None
    rate: Optional[float] = None

    @property
    def label(self) -> str:
        return self.title or self.project_id or f"№{self.position + 1}"


def parse_approved_lines(raw: Any) -> Optional[List[ApprovedLine]]:
    """Разбор lines[]. None на выходе — поля не было, работаем по отбору."""
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        raise BillingError(
            "Поле lines[] должно быть списком строк документа.",
            ERROR_LINES_MISMATCH,
        )

    result: List[ApprovedLine] = []
    for position, item in enumerate(raw):
        if not isinstance(item, dict):
            raise BillingError(
                f"Строка №{position + 1} прислана не объектом — выставлять по ней нечего.",
                ERROR_LINES_MISMATCH,
            )
        line = ApprovedLine(
            position=position,
            project_id=_clean(item.get("project_id")),
            title=_clean(item.get("title")),
            hours=_opt_num(item.get("hours"), f"часы строки №{position + 1}"),
            rate=_opt_num(item.get("rate"), f"цену строки №{position + 1}"),
        )
        if line.hours is not None and line.hours < 0:
            raise BillingError(
                f"В строке «{line.label}» отрицательные часы. "
                "Сторно и корректировочные документы первая версия не выставляет.",
                ERROR_LINES_MISMATCH,
                extra={"line": line.label},
            )
        if line.rate is not None and line.rate < 0:
            raise BillingError(
                f"В строке «{line.label}» отрицательная цена. "
                "Сторно и корректировочные документы первая версия не выставляет.",
                ERROR_LINES_MISMATCH,
                extra={"line": line.label},
            )
        result.append(line)
    return result


@dataclass
class BillingFilter:
    """Разобранный фильтр отбора (тело preview и documents)."""

    date_from: Optional[date] = None
    date_to: Optional[date] = None
    company_id: str = ""
    our_company_id: str = ""
    project_ids: List[str] = field(default_factory=list)
    task_ids: List[str] = field(default_factory=list)
    employee_ids: List[str] = field(default_factory=list)
    billable_only: bool = True
    only_closed_periods: bool = False
    exclude_invoiced: bool = True
    grouping: str = DEFAULT_GROUPING

    @classmethod
    def from_payload(cls, payload: Optional[Dict[str, Any]]) -> "BillingFilter":
        payload = payload if isinstance(payload, dict) else {}

        def flag(key: str, default: bool) -> bool:
            if key not in payload or payload.get(key) is None:
                return default
            value = payload.get(key)
            if isinstance(value, bool):
                return value
            return _clean(value).lower() in {"1", "true", "yes", "y", "on"}

        grouping = _clean(payload.get("grouping")) or DEFAULT_GROUPING
        if grouping not in GROUPINGS:
            raise BillingError(
                f"Неизвестная группировка: {grouping}. Допустимы: {', '.join(GROUPINGS)}.",
                "bad_grouping",
            )

        return cls(
            date_from=_parse_date(payload.get("date_from")),
            date_to=_parse_date(payload.get("date_to")),
            company_id=_clean(payload.get("company_id")),
            our_company_id=_clean(payload.get("our_company_id")),
            project_ids=_as_list(payload.get("project_ids") or payload.get("project_ids[]")),
            task_ids=_as_list(payload.get("task_ids") or payload.get("task_ids[]")),
            employee_ids=_as_list(payload.get("employee_ids") or payload.get("employee_ids[]")),
            billable_only=flag("billable_only", True),
            only_closed_periods=flag("only_closed_periods", False),
            exclude_invoiced=flag("exclude_invoiced", True),
            grouping=grouping,
        )

    def as_snapshot(self) -> Dict[str, Any]:
        return {
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "company_id": self.company_id,
            "our_company_id": self.our_company_id,
            "project_ids": list(self.project_ids),
            "task_ids": list(self.task_ids),
            "employee_ids": list(self.employee_ids),
            "billable_only": self.billable_only,
            "only_closed_periods": self.only_closed_periods,
            "exclude_invoiced": self.exclude_invoiced,
            "grouping": self.grouping,
        }


@dataclass
class Selection:
    """Результат отбора: то, из чего собирается документ и что видит preview."""

    entries: List[Dict[str, Any]] = field(default_factory=list)
    lines: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    companies: List[Dict[str, str]] = field(default_factory=list)
    our_companies: List[Dict[str, str]] = field(default_factory=list)
    already_invoiced_ids: List[int] = field(default_factory=list)
    conflicting_documents: List[str] = field(default_factory=list)
    open_periods: List[str] = field(default_factory=list)

    @property
    def total_hours(self) -> float:
        return round(sum(_num(row["hours"]) for row in self.entries), 2)

    @property
    def total_amount(self) -> float:
        return _money(sum(_num(line["amount"]) for line in self.lines))

    def warning_codes(self) -> List[str]:
        return [item["code"] for item in self.warnings]

    def as_payload(self) -> Dict[str, Any]:
        """Ответ preview.

        Клиент отдаётся и списком (companies), и скаляром (company_id/
        company_name): список нужен, только чтобы показать mixed_companies —
        «вот эти клиенты смешались», — а в нормальном случае клиент ровно
        один, и интерфейсу удобнее скаляр, чем список из одного элемента.
        """
        company = self.companies[0] if len(self.companies) == 1 else {"id": "", "name": ""}
        our_company = self.our_companies[0] if len(self.our_companies) == 1 else {"id": "", "name": ""}
        return {
            "lines": self.lines,
            "entries_count": len(self.entries),
            "total_hours": self.total_hours,
            "total_amount": self.total_amount,
            "warnings": self.warnings,
            "companies": self.companies,
            "our_companies": self.our_companies,
            "company_id": company["id"],
            "company_name": company["name"],
            "our_company_id": our_company["id"],
            "our_company_name": our_company["name"],
            "currency": "RUB",
        }


class BillingService:
    def __init__(self, account, client: Any = None, settings: Optional[Dict[str, Any]] = None):
        self.account = account
        self._client = client
        self._settings = settings
        self._period_service: Optional[PeriodService] = None

    # ------------------------------------------------------------------
    # Вспомогательное
    # ------------------------------------------------------------------

    @property
    def client(self):
        if self._client is None:
            self._client = self.account.client
        return self._client

    @property
    def settings(self) -> Dict[str, Any]:
        if self._settings is None:
            from .billing_settings import load_billing_settings

            self._settings = load_billing_settings(self.account, self._client)
        return self._settings

    @property
    def period_service(self) -> PeriodService:
        if self._period_service is None:
            self._period_service = PeriodService(self.account)
        return self._period_service

    def _project_cards(self) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        """Три словаря поиска карточки проекта: по item_id, по group_id, по названию.

        Строка списания привязана к проекту одним из трёх ключей (см.
        report_queries._build_project_match_q) — искать надо всеми тремя,
        иначе у части списаний не найдётся ни клиент, ни ставка.
        """
        by_item: Dict[str, Dict[str, Any]] = {}
        by_group: Dict[str, Dict[str, Any]] = {}
        by_name: Dict[str, Dict[str, Any]] = {}
        rows = get_project_card_queryset(self.account).values(
            "project_item_id", "project_id", "project_name",
            "hourly_rate", "company_id", "company_name",
            "our_legal_entity_id", "our_legal_entity_name",
        )
        for row in rows.iterator():
            card = {
                "project_id": _clean(row.get("project_id")),
                "project_name": _clean(row.get("project_name")),
                "hourly_rate": _num(row.get("hourly_rate")),
                "company_id": _clean(row.get("company_id")),
                "company_name": _clean(row.get("company_name")),
                "our_company_id": _clean(row.get("our_legal_entity_id")),
                "our_company_name": _clean(row.get("our_legal_entity_name")),
            }
            item_id = _clean(row.get("project_item_id"))
            if item_id:
                by_item.setdefault(item_id, card)
            if card["project_id"]:
                by_group.setdefault(card["project_id"], card)
            if card["project_name"]:
                by_name.setdefault(card["project_name"], card)
        return by_item, by_group, by_name

    def _user_map(self, employee_ids: Iterable[str]) -> Dict[str, str]:
        """Имена сотрудников из локального справочника.

        Только PortalUser, без похода в Битрикс: счёт собирается по своим
        данным, а недостающее имя деградирует до «Сотрудник <id>» — это
        подпись строки детализации, а не основание суммы.
        """
        ids = {_clean(value) for value in employee_ids}
        ids.discard("")
        if not ids:
            return {}
        rows = PortalUser.objects.filter(
            **scope_to_tenant(self.account), bitrix_id__in=list(ids)
        ).values("bitrix_id", "name", "last_name")
        return {
            row["bitrix_id"]: (f"{row['last_name']} {row['name']}".strip() or row["bitrix_id"])
            for row in rows
        }

    def active_entry_map(self) -> Dict[int, BillingEntry]:
        """bitrix_id списания -> действующая запись документа."""
        rows = BillingEntry.objects.filter(
            **scope_to_tenant(self.account), is_active=True
        ).select_related("document")
        return {int(row.timesheet_bitrix_id): row for row in rows}

    # ------------------------------------------------------------------
    # Отбор
    # ------------------------------------------------------------------

    def _queryset(self, filters: BillingFilter):
        queryset = TimesheetItem.objects.filter(**scope_to_tenant(self.account))

        if filters.date_from:
            queryset = queryset.filter(date_reflection__gte=_day_start(filters.date_from))
        if filters.date_to:
            queryset = queryset.filter(date_reflection__lt=_next_day_start(filters.date_to))
        if filters.billable_only:
            queryset = queryset.filter(is_billable=True)
        if filters.employee_ids:
            aliases = build_employee_id_aliases(filters.employee_ids)
            if aliases:
                queryset = queryset.filter(employee_id__in=aliases)
        if filters.project_ids:
            queryset = queryset.filter(build_project_match_q(self.account, filters.project_ids))
        if filters.task_ids:
            queryset = queryset.filter(task_id__in=filters.task_ids)

        return queryset.order_by("date_reflection", "bitrix_id")

    def collect(self, filters: BillingFilter) -> Selection:
        """Отбор списаний и сборка строк. Ничего не пишет."""
        selection = Selection()

        rows = list(
            self._queryset(filters).values(
                "bitrix_id", "employee_id", "hours", "description", "date_reflection",
                "project_id", "project_item_id", "project_title", "task_id",
                "hourly_rate_snapshot",
            )
        )

        by_item, by_group, by_name = self._project_cards()
        task_lookup = build_task_lookup(self.account)
        user_map = self._user_map(row["employee_id"] for row in rows)
        active_entries = self.active_entry_map()

        companies: Dict[str, str] = {}
        our_companies: Dict[str, str] = {}
        no_rate = 0
        open_periods: Dict[Tuple[int, int], str] = {}
        conflicting: Dict[str, str] = {}

        for row in rows:
            card = (
                by_item.get(_clean(row.get("project_item_id")))
                or by_group.get(_clean(row.get("project_id")))
                or by_name.get(_clean(row.get("project_title")))
                or {}
            )

            company_id = card.get("company_id", "")
            if filters.company_id and company_id != filters.company_id:
                continue
            if filters.our_company_id and card.get("our_company_id", "") != filters.our_company_id:
                continue

            period_key = period_of(row.get("date_reflection"))
            is_closed = self.period_service.is_closed(row.get("date_reflection"))
            if filters.only_closed_periods and not is_closed:
                continue

            bitrix_id = int(row.get("bitrix_id") or 0)
            existing = active_entries.get(bitrix_id)
            if existing is not None:
                selection.already_invoiced_ids.append(bitrix_id)
                conflicting[str(existing.document_id)] = existing.document.crm_account_number or ""
                if filters.exclude_invoiced:
                    continue

            rate = row.get("hourly_rate_snapshot")
            rate = _num(rate) if rate not in (None, "") else _num(card.get("hourly_rate"))
            if rate <= 0:
                no_rate += 1

            hours = _num(row.get("hours"))
            employee_id = _clean(row.get("employee_id"))
            task_id = _clean(row.get("task_id"))
            task_meta = task_lookup.get(task_id) or {}

            if not is_closed and period_key:
                open_periods[period_key] = f"{period_key[0]}-{period_key[1]:02d}"

            if company_id:
                companies[company_id] = card.get("company_name", "") or company_id
            our_id = card.get("our_company_id", "")
            if our_id:
                our_companies[our_id] = card.get("our_company_name", "") or our_id

            selection.entries.append({
                "timesheet_bitrix_id": bitrix_id,
                "employee_id": employee_id,
                "employee_name": resolve_employee_name(user_map, employee_id),
                "date_reflection": row.get("date_reflection"),
                "hours": hours,
                "rate_snapshot": rate,
                "amount": _money(hours * rate),
                "project_id": card.get("project_id", "") or _clean(row.get("project_id")),
                "project_name": card.get("project_name", "") or _clean(row.get("project_title")),
                "task_id": task_id,
                "task_title": task_meta.get("title") or "",
                "description": _clean(row.get("description")),
                "company_id": company_id,
            })

        selection.companies = [{"id": key, "name": value} for key, value in sorted(companies.items())]
        selection.our_companies = [{"id": key, "name": value} for key, value in sorted(our_companies.items())]
        selection.conflicting_documents = sorted(conflicting)
        selection.open_periods = sorted(open_periods.values())
        selection.lines = self._build_lines(selection.entries, filters)

        if selection.already_invoiced_ids:
            count = len(set(selection.already_invoiced_ids))
            selection.warnings.append({
                "code": WARNING_ALREADY_INVOICED,
                "message": (
                    f"{count} записей уже выставлены "
                    + ("и исключены из отбора." if filters.exclude_invoiced else "и попали в отбор.")
                ),
                "count": count,
                "document_ids": selection.conflicting_documents,
                "details": selection.conflicting_documents,
                "blocking": not filters.exclude_invoiced,
            })

        if no_rate:
            selection.warnings.append({
                "code": WARNING_NO_RATE,
                "message": f"У {no_rate} записей нет ставки — они уйдут в счёт с нулевой суммой.",
                "count": no_rate,
                "blocking": False,
            })

        if selection.open_periods:
            allowed = bool(self.settings.get("allow_open_period"))
            selection.warnings.append({
                "code": WARNING_PERIOD_OPEN,
                "message": (
                    "В отбор попали незакрытые месяцы: "
                    + ", ".join(selection.open_periods)
                    + ("." if allowed else ". Закройте период или включите настройку "
                       "«Разрешить выставление за открытый период».")
                ),
                "periods": selection.open_periods,
                "details": selection.open_periods,
                "blocking": not allowed,
            })

        if len(selection.companies) > 1:
            selection.warnings.append({
                "code": WARNING_MIXED_COMPANIES,
                "message": (
                    "В отборе несколько клиентов: "
                    + ", ".join(item["name"] for item in selection.companies)
                    + ". Выставить одним документом нельзя — уточните фильтр."
                ),
                "companies": selection.companies,
                "details": [item["name"] for item in selection.companies],
                "blocking": True,
            })

        return selection

    def _build_lines(self, entries: Sequence[Dict[str, Any]], filters: BillingFilter) -> List[Dict[str, Any]]:
        """Группировка строк документа.

        Ставка строки — не «ставка проекта», а взвешенная: сумма строки
        делится на её часы. Внутри одной строки ставки могут быть разными
        (её помнит каждое списание), и подставить сюда любую одну означало бы
        разойтись с детализацией.
        """
        if not entries:
            return []

        if filters.grouping == "single":
            keyed = [("", "Услуги по договору", "", entries)]
        else:
            buckets: Dict[str, Dict[str, Any]] = {}
            for row in entries:
                if filters.grouping == "task":
                    key = row["task_id"] or "—"
                    title = row["task_title"] or (f"Задача {row['task_id']}" if row["task_id"] else "Без задачи")
                elif filters.grouping == "employee":
                    key = row["employee_id"] or "—"
                    title = row["employee_name"]
                else:
                    key = row["project_id"] or row["project_name"] or "—"
                    title = row["project_name"] or "Без проекта"
                bucket = buckets.setdefault(key, {"title": title, "project_id": row["project_id"], "rows": []})
                bucket["rows"].append(row)
            keyed = [
                (key, bucket["title"], bucket["project_id"], bucket["rows"])
                for key, bucket in buckets.items()
            ]
            keyed.sort(key=lambda item: item[1])

        lines: List[Dict[str, Any]] = []
        for sort, (_key, title, project_id, bucket_rows) in enumerate(keyed):
            hours = round(sum(_num(row["hours"]) for row in bucket_rows), 2)
            amount = _money(sum(_num(row["amount"]) for row in bucket_rows))
            project_name = bucket_rows[0]["project_name"] if bucket_rows else ""
            lines.append({
                "project_id": project_id or "",
                "project_name": project_name,
                "title": title,
                "hours": hours,
                "rate": _money(amount / hours) if hours else 0.0,
                "amount": amount,
                "sort": sort,
                "entry_ids": [row["timesheet_bitrix_id"] for row in bucket_rows],
            })
        return lines

    # ------------------------------------------------------------------
    # Утверждённые строки (lines[] в теле выставления)
    # ------------------------------------------------------------------

    def apply_approved_lines(self, selection: Selection, raw_lines: Any) -> Selection:
        """Оставить в отборе то, что человек утвердил в предпросмотре.

        Мастер показывает строки отбора и даёт исключить строку и поправить
        её текст и цену. Без этого шага правки оставались бы на экране:
        документ собирался бы заново из отбора, и счёт расходился бы с тем,
        что человек утвердил глазами.

        Три правила.

        1. Утверждённое СВЕРЯЕТСЯ с отбором, а не заменяет его. Строка, под
           которой нет строки отбора, — отказ: иначе через lines[] можно
           было бы выставить проект, которого в отборе нет, или часы,
           которых никто не списывал.
        2. Часы не правятся. Строка документа обязана оставаться суммой
           своих списаний (выставление части записи — за границей первой
           версии, см. контракт), поэтому принимаются только совпавшие с
           отбором часы, а расхождение значит «отбор изменился с момента
           предпросмотра».
        3. Исключённая строка НЕ ПОТРЕБЛЯЕТ списания: её BillingEntry не
           создаются вовсе, и те же часы остаются свободными для следующего
           счёта. Поэтому исключение — это отсев entries, а не пометка.

        Поля lines[] нет — возвращаем отбор как есть: контракт описывает
        тело этой ручки фильтром, и старый клиент обязан работать.
        """
        approved = parse_approved_lines(raw_lines)
        if approved is None:
            return selection

        pairs = self._match_approved_lines(selection, approved)

        result = Selection(
            warnings=selection.warnings,
            companies=selection.companies,
            our_companies=selection.our_companies,
            already_invoiced_ids=selection.already_invoiced_ids,
            conflicting_documents=selection.conflicting_documents,
            open_periods=selection.open_periods,
        )
        kept_ids = set()
        for sort, (item, line) in enumerate(pairs):
            source_rate = _num(line["rate"])
            rate = source_rate if item.rate is None else _money(item.rate)
            if abs(rate - source_rate) <= LINE_TOLERANCE:
                # Цену не трогали — сумму берём готовую. Пересчёт через
                # округлённую ставку разошёлся бы с суммой списаний на
                # копейку там, где сумма не делится на часы нацело.
                rate, amount = source_rate, _money(line["amount"])
            else:
                amount = _money(_num(line["hours"]) * rate)
            result.lines.append({
                **line,
                "title": item.title or line["title"],
                "rate": rate,
                "amount": amount,
                "sort": sort,
            })
            kept_ids.update(line["entry_ids"])

        result.entries = [
            row for row in selection.entries if row["timesheet_bitrix_id"] in kept_ids
        ]

        if not result.lines or not result.entries:
            raise BillingError(
                "Все строки предпросмотра исключены — выставлять нечего.",
                "empty_selection",
            )

        audit.info(
            "Billing lines approved by hand: %s из %s строк, часы %s, сумма %s",
            len(result.lines), len(selection.lines), result.total_hours, result.total_amount,
        )
        return result

    def _match_approved_lines(
        self, selection: Selection, approved: Sequence[ApprovedLine]
    ) -> List[Tuple[ApprovedLine, Dict[str, Any]]]:
        """Сопоставление утверждённых строк со строками отбора.

        Идём по обеим последовательностям вперёд. Мастер отдаёт строки в том
        же порядке, в каком их показал preview, выбросив исключённые, —
        значит утверждённое это подпоследовательность отбора, а пропущенные
        по дороге строки и есть исключённые. Указатель только растёт, и
        поэтому одна строка отбора не может быть потреблена дважды.

        Ключ сопоставления — проект и часы; текст ключом быть не может, его
        как раз правят. Но когда ключ неоднозначен (группировка по задаче
        или сотруднику даёт несколько строк одного проекта), совпадение
        текста разрешает неоднозначность в пользу очевидного кандидата.
        """
        lines = selection.lines
        pairs: List[Tuple[ApprovedLine, Dict[str, Any]]] = []
        pointer = 0

        for item in approved:
            same_project = [
                pos for pos in range(pointer, len(lines))
                if _clean(lines[pos]["project_id"]) == item.project_id
            ]
            if not same_project:
                known = any(_clean(line["project_id"]) == item.project_id for line in lines)
                raise BillingError(
                    (
                        f"Строка «{item.label}» повторяется чаще, чем в отборе, "
                        "или прислана не в том порядке. Обновите предпросмотр."
                    ) if known else (
                        f"Строка «{item.label}» не из этого отбора: такого проекта в нём нет. "
                        "Обновите предпросмотр."
                    ),
                    ERROR_LINES_MISMATCH,
                    extra={"line": item.label},
                )

            available = max(_num(lines[pos]["hours"]) for pos in same_project)
            if item.hours is not None and item.hours > available + LINE_TOLERANCE:
                raise BillingError(
                    f"В строке «{item.label}» {_hours_text(item.hours)} ч, "
                    f"а в отборе не больше {_hours_text(available)} ч. "
                    "Часы в счёте нельзя увеличить — поменяйте отбор.",
                    ERROR_LINES_MISMATCH,
                    extra={
                        "line": item.label,
                        "hours": round(item.hours, 2),
                        "available_hours": round(available, 2),
                    },
                )

            fitting = [
                pos for pos in same_project
                if item.hours is None
                or abs(item.hours - _num(lines[pos]["hours"])) <= LINE_TOLERANCE
            ]
            if not fitting:
                raise BillingError(
                    f"Часы строки «{item.label}» ({_hours_text(item.hours)} ч) не совпали с отбором: "
                    "он изменился с момента предпросмотра. Обновите предпросмотр.",
                    ERROR_LINES_MISMATCH,
                    extra={"line": item.label, "hours": round(_num(item.hours), 2)},
                )

            chosen = next(
                (pos for pos in fitting if item.title and _clean(lines[pos]["title"]) == item.title),
                fitting[0],
            )
            pointer = chosen + 1
            pairs.append((item, lines[chosen]))

        return pairs

    # ------------------------------------------------------------------
    # Выставление
    # ------------------------------------------------------------------

    def validate_for_issue(self, selection: Selection, filters: BillingFilter) -> None:
        """Блокеры выставления. Порядок важен.

        Конфликт с уже выставленным проверяется ПЕРВЫМ и раньше «пустого
        отбора»: повторный POST с тем же фильтром и exclude_invoiced=true
        отберёт ноль записей, и честный ответ на него — 409 со ссылкой на
        существующий документ, а не «нечего выставлять» (контракт, п. 8).
        """
        if selection.already_invoiced_ids and (
            not filters.exclude_invoiced or not selection.entries
        ):
            raise BillingError(
                "Эти списания уже выставлены — счёт по ним существует.",
                "already_invoiced",
                status=409,
                extra={
                    "document_ids": selection.conflicting_documents,
                    "count": len(set(selection.already_invoiced_ids)),
                },
            )

        if not selection.entries:
            raise BillingError(
                "По этому фильтру нечего выставлять: подходящих списаний не найдено.",
                "empty_selection",
            )

        if len(selection.companies) > 1:
            raise BillingError(
                "В отборе несколько клиентов — выставить одним документом нельзя.",
                WARNING_MIXED_COMPANIES,
                extra={"companies": selection.companies},
            )

        if not selection.companies:
            raise BillingError(
                "У проектов отбора не заполнен клиент — счёт выставлять не на кого.",
                "no_company",
            )

        if selection.open_periods and not self.settings.get("allow_open_period"):
            raise BillingError(
                "В отбор попали незакрытые месяцы: " + ", ".join(selection.open_periods)
                + ". Закройте период или включите настройку «Разрешить выставление за открытый период».",
                WARNING_PERIOD_OPEN,
                extra={"periods": selection.open_periods},
            )

    @transaction.atomic
    def create_document(
        self,
        selection: Selection,
        filters: BillingFilter,
        *,
        created_by_id: str = "",
        created_by_name: str = "",
        vat_mode: str = BillingDocument.VAT_INCLUDED,
        vat_rate: float = 0.0,
    ) -> BillingDocument:
        """Документ, строки и потреблённые списания — одной транзакцией.

        IntegrityError частичного индекса превращается в BillingError 409:
        это не сбой, а штатный исход гонки двух «Выставить».
        """
        company = selection.companies[0] if selection.companies else {"id": "", "name": ""}
        our_company = selection.our_companies[0] if selection.our_companies else {"id": "", "name": ""}
        if filters.our_company_id:
            for item in selection.our_companies:
                if item["id"] == filters.our_company_id:
                    our_company = item
                    break

        dates = [
            _parse_date(row["date_reflection"])
            for row in selection.entries
            if row.get("date_reflection")
        ]
        dates = [value for value in dates if value]

        document = BillingDocument.objects.create(
            **scope_to_tenant(self.account, write=True),
            status=BillingDocument.STATUS_ISSUED,
            period_from=filters.date_from or (min(dates) if dates else None),
            period_to=filters.date_to or (max(dates) if dates else None),
            company_id=company["id"],
            company_name=company["name"],
            our_company_id=our_company["id"],
            our_company_name=our_company["name"],
            vat_mode=vat_mode,
            vat_rate=_num(vat_rate),
            total_hours=selection.total_hours,
            total_amount=selection.total_amount,
            grouping=filters.grouping,
            filter_snapshot=filters.as_snapshot(),
            created_by_id=_clean(created_by_id),
            created_by_name=_clean(created_by_name),
        )

        entries_by_id = {row["timesheet_bitrix_id"]: row for row in selection.entries}
        line_objects: List[BillingLine] = []
        for line in selection.lines:
            line_objects.append(BillingLine.objects.create(
                document=document,
                project_id=line["project_id"],
                project_name=line["project_name"],
                title=line["title"],
                hours=line["hours"],
                rate=line["rate"],
                amount=line["amount"],
                sort=line["sort"],
            ))

        entry_objects: List[BillingEntry] = []
        for line, line_object in zip(selection.lines, line_objects):
            for bitrix_id in line["entry_ids"]:
                row = entries_by_id[bitrix_id]
                entry_objects.append(BillingEntry(
                    document=document,
                    line=line_object,
                    **scope_to_tenant(self.account, write=True),
                    timesheet_bitrix_id=bitrix_id,
                    is_active=True,
                    employee_id=row["employee_id"],
                    employee_name=row["employee_name"],
                    date_reflection=row["date_reflection"],
                    hours=row["hours"],
                    rate_snapshot=row["rate_snapshot"],
                    amount=row["amount"],
                    project_id=row["project_id"],
                    project_name=row["project_name"],
                    task_id=row["task_id"],
                    task_title=row["task_title"],
                    description=row["description"],
                ))

        try:
            BillingEntry.objects.bulk_create(entry_objects)
        except IntegrityError as exc:
            raise BillingError(
                "Эти списания уже выставлены — счёт по ним создан параллельно. Обновите отбор.",
                "already_invoiced",
                status=409,
                extra={"document_ids": selection.conflicting_documents},
            ) from exc

        audit.info(
            "Billing document issued: %s, company=%s, hours=%s, amount=%s, entries=%s, by %s (%s)",
            document.pk, document.company_name, document.total_hours,
            document.total_amount, len(entry_objects),
            created_by_name or "—", created_by_id or "—",
        )
        return document

    # ------------------------------------------------------------------
    # Отмена
    # ------------------------------------------------------------------

    @transaction.atomic
    def cancel(self, document: BillingDocument, reason: str, *,
               user_id: str = "", user_name: str = "") -> BillingDocument:
        """Отмена освобождает списания: is_active=False одним UPDATE.

        Пара «статус документа + is_active записей» поддерживается ТОЛЬКО
        здесь и в create_document — в этом смысл денормализации (см.
        докстринг BillingEntry).
        """
        reason = _clean(reason)
        if not reason:
            raise BillingError("Причина отмены обязательна.", "cancel_reason_required")
        if document.status == BillingDocument.STATUS_CANCELLED:
            raise BillingError("Документ уже отменён.", "already_cancelled", status=409)

        document.status = BillingDocument.STATUS_CANCELLED
        document.cancelled_at = timezone.now()
        document.cancelled_by_id = _clean(user_id)
        document.cancelled_by_name = _clean(user_name)
        document.cancel_reason = reason
        document.save(update_fields=[
            "status", "cancelled_at", "cancelled_by_id", "cancelled_by_name",
            "cancel_reason", "updated_at",
        ])
        BillingEntry.objects.filter(document=document).update(is_active=False)

        audit.info(
            "Billing document cancelled: %s by %s (%s), reason: %s",
            document.pk, user_name or "—", user_id or "—", reason,
        )
        return document

    def discard_failed(self, document: BillingDocument, reason: str) -> None:
        """Снятие документа, у которого не получился счёт в CRM.

        Без crm_entity_id документ удаляется: снаружи на него ещё никто не
        ссылается, а отменённая пустышка только засоряет реестр. Если id
        счёта всё-таки получен (ответам REST Битрикс24 верить нельзя — счёт
        мог создаться и при сбое на следующем шаге), документ ОТМЕНЯЕТСЯ:
        след обязан остаться, иначе живой счёт на портале потеряет связь с
        приложением. В обоих случаях списания освобождаются.
        """
        if document.crm_entity_id:
            try:
                self.cancel(document, f"Ошибка выставления: {reason}")
            except BillingError:
                logger.exception("discard_failed: не удалось отменить документ %s", document.pk)
            return
        document.delete()

    # ------------------------------------------------------------------
    # Карточка и реестр
    # ------------------------------------------------------------------

    def documents_queryset(self):
        return BillingDocument.objects.filter(**scope_to_tenant(self.account))

    def get_document(self, document_id: Any) -> BillingDocument:
        """Документ своего портала по id.

        ValidationError ловится наравне с DoesNotExist: первичный ключ —
        UUID, и на «id», который UUID-ом не является, Django бросает именно
        её. Для клиента это тот же «не найден», а не 500.
        """
        try:
            return self.documents_queryset().get(pk=document_id)
        except (BillingDocument.DoesNotExist, DjangoValidationError, ValueError, TypeError) as exc:
            raise BillingError("Документ не найден.", "not_found", status=404) from exc

    def drift(self, document: BillingDocument) -> List[Dict[str, Any]]:
        """Расхождения снимка с текущими списаниями.

        Закрытый период защищён приложением, но карточку списания можно
        поправить в интерфейсе Битрикса в обход. Документ сам не
        пересчитывается никогда — расхождение только показывается.

        Два вида: changed (часы или ставка разошлись) и deleted (списания
        больше нет в БД: синхронизация физически удаляет пропавшее в
        Битриксе).
        """
        entries = list(document.entries.all())
        if not entries:
            return []
        ids = [entry.timesheet_bitrix_id for entry in entries]
        current = {
            int(row["bitrix_id"]): row
            for row in TimesheetItem.objects.filter(
                **scope_to_tenant(self.account), bitrix_id__in=ids
            ).values("bitrix_id", "hours", "hourly_rate_snapshot")
        }

        result: List[Dict[str, Any]] = []
        for entry in entries:
            row = current.get(entry.timesheet_bitrix_id)
            if row is None:
                result.append({
                    "kind": "deleted",
                    "timesheet_bitrix_id": entry.timesheet_bitrix_id,
                    "employee_name": entry.employee_name,
                    "date_reflection": entry.date_reflection.isoformat() if entry.date_reflection else None,
                    "description": entry.description,
                    # hours/rate_snapshot — снимок документа, current_* —
                    # то, что в БД сейчас. У удалённого списания «сейчас»
                    # нет, и это None, а не ноль: ноль часов и отсутствие
                    # записи — разные вещи.
                    "hours": entry.hours,
                    "current_hours": None,
                    "rate_snapshot": entry.rate_snapshot,
                    "current_rate": None,
                })
                continue
            hours_now = _num(row.get("hours"))
            rate_now = _num(row.get("hourly_rate_snapshot"))
            hours_changed = abs(hours_now - _num(entry.hours)) > 0.001
            # Ставка сравнивается только когда она у списания есть: пустой
            # снимок ставки означает «бралась из карточки проекта», и
            # карточка с тех пор могла смениться — это не правка списания.
            rate_changed = (
                row.get("hourly_rate_snapshot") not in (None, "")
                and abs(rate_now - _num(entry.rate_snapshot)) > 0.001
            )
            if hours_changed or rate_changed:
                result.append({
                    "kind": "changed",
                    "timesheet_bitrix_id": entry.timesheet_bitrix_id,
                    "employee_name": entry.employee_name,
                    "date_reflection": entry.date_reflection.isoformat() if entry.date_reflection else None,
                    "description": entry.description,
                    "hours": entry.hours,
                    "current_hours": hours_now,
                    "rate_snapshot": entry.rate_snapshot,
                    "current_rate": rate_now if rate_changed else entry.rate_snapshot,
                })
        return result

    def serialize_document(self, document: BillingDocument, *, with_details: bool = False) -> Dict[str, Any]:
        payload = {
            "id": str(document.pk),
            "status": document.status,
            "period_from": document.period_from.isoformat() if document.period_from else None,
            "period_to": document.period_to.isoformat() if document.period_to else None,
            "company_id": document.company_id,
            "company_name": document.company_name,
            "our_company_id": document.our_company_id,
            "our_company_name": document.our_company_name,
            "currency": document.currency,
            "vat_mode": document.vat_mode,
            "vat_rate": document.vat_rate,
            "total_hours": document.total_hours,
            "total_amount": document.total_amount,
            "grouping": document.grouping,
            "crm_entity_id": document.crm_entity_id,
            "crm_account_number": document.crm_account_number,
            "act_document_id": document.act_document_id,
            "act_number": document.act_number,
            "act_download_url": document.act_download_url,
            "act_public_url": document.act_public_url,
            "act_pdf_url": document.act_pdf_url,
            "act_error": document.act_error,
            "created_by_id": document.created_by_id,
            "created_by_name": document.created_by_name,
            "created_at": document.created_at.isoformat() if document.created_at else None,
            "cancelled_at": document.cancelled_at.isoformat() if document.cancelled_at else None,
            "cancel_reason": document.cancel_reason,
        }
        if not with_details:
            return payload

        payload["filter"] = document.filter_snapshot or {}
        payload["lines"] = [
            {
                "id": str(line.pk),
                "project_id": line.project_id,
                "project_name": line.project_name,
                "title": line.title,
                "hours": line.hours,
                "rate": line.rate,
                "amount": line.amount,
                "sort": line.sort,
            }
            for line in document.lines.all()
        ]
        payload["entries"] = [
            {
                "id": str(entry.pk),
                "timesheet_bitrix_id": entry.timesheet_bitrix_id,
                "employee_id": entry.employee_id,
                "employee_name": entry.employee_name,
                "date_reflection": entry.date_reflection.isoformat() if entry.date_reflection else None,
                "hours": entry.hours,
                "rate_snapshot": entry.rate_snapshot,
                "amount": entry.amount,
                "project_id": entry.project_id,
                "project_name": entry.project_name,
                "task_id": entry.task_id,
                "task_title": entry.task_title,
                "description": entry.description,
            }
            for entry in document.entries.all().order_by("date_reflection", "timesheet_bitrix_id")
        ]
        payload["drift"] = self.drift(document)
        return payload


def _day_start(value: date):
    from datetime import datetime as _dt, time as _time

    return timezone.make_aware(_dt.combine(value, _time.min), timezone.get_current_timezone())


def _next_day_start(value: date):
    from datetime import timedelta

    return _day_start(value + timedelta(days=1))


# Публичные имена для соседних модулей функции (канал CRM, XLSX-детализация):
# одна арифметика округления на всю фичу, а не копия в каждом файле.
money = _money
num = _num
clean_str = _clean
parse_date = _parse_date
