"""Детализация к счёту и акту: сборка иерархии задача → сотрудник → списание.

Зачем отдельный модуль. Выгрузка детализации раньше была плоской таблицей
«строка на списание», и в колонке задачи стоял идентификатор Битрикса, если
снимок названия в документе пуст. Бухгалтер читает такое приложение к акту
как набор чисел: одно и то же название повторяется у каждого списания, а без
названия вообще непонятно, за что счёт.

Здесь собирается та же иерархия, что у отчётов (`report_services`), только
уровни свои: задача → сотрудник → списание. Рендер лежит в `report_excel`
(`render_billing_detail_workbook`) — вёрстка одна на все выгрузки приложения.

Данные берутся из снимка документа (`BillingEntry`), а не из текущих
списаний: это приложение к выставленному документу, оно обязано показывать
то, за что выставлен счёт. Расхождения со текущими часами живут отдельно, на
карточке документа (drift).

Про источник названия задачи — см. `resolve_task_titles`.
"""

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .models import PortalTask, TimesheetItem
from .report_excel import render_billing_detail_workbook
from .tenant_scoping import scope_to_tenant

# Ключ группы «списания без задачи»: пустой task_id нельзя пускать в общий
# словарь вперемешку с настоящими, иначе группа потеряется при сортировке.
NO_TASK_KEY = ""
NO_TASK_TITLE = "Без задачи"

# Источники названия задачи — в порядке доверия (см. resolve_task_titles).
SOURCE_ENTRY = "entry"
SOURCE_TIMESHEET = "timesheet"
SOURCE_PORTAL_TASK = "portal_task"
SOURCE_MISSING = "missing"


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _clean(value: Any) -> str:
    return str(value or "").strip()


def missing_title_label(task_id: str) -> str:
    """Заглушка для задачи, названия которой нет ни в одном источнике.

    Ни пустоты, ни голого идентификатора: пустая группа выглядит как ошибка
    выгрузки, а голый «8365» — это ровно то, на что жаловались. Текст говорит
    прямо: название не нашлось, вот по какому id искать в Битриксе.
    """
    return f"Задача {task_id} (название не найдено)"


def resolve_task_titles(
    account,
    entries: Sequence[Any],
) -> Dict[str, Tuple[str, str]]:
    """task_id -> (название, источник). Три источника, по убыванию доверия.

    1. `BillingEntry.task_title` — снимок названия на момент выставления.
       Первый по порядку именно потому, что документ подписан под этим
       названием: если задачу потом переименовали, в приложении к акту
       должно остаться то, за что выставлен счёт.
    2. `TimesheetItem.task_hierarchy_titles` связанных списаний — снимок
       названия на момент списания часов. Спасает документы, выставленные
       когда справочник задач (`PortalTask`) ещё не был наполнен: в
       `billing_service` название берётся только из справочника, и при
       промахе в документ уходит пустая строка.
    3. `PortalTask` — справочник задач портала, актуальное название. Годится
       как последняя опора: название могло измениться, но это лучше пустоты.

    Если не нашлось нигде — `missing_title_label` с идентификатором.

    Запросы к БД идут пачкой на весь документ (два `IN`), а не по строке:
    списаний в документе бывают сотни.
    """
    titles: Dict[str, Tuple[str, str]] = {}
    task_ids: List[str] = []
    timesheet_ids: List[int] = []

    for entry in entries:
        task_id = _clean(getattr(entry, "task_id", ""))
        if not task_id:
            continue
        if task_id not in titles:
            task_ids.append(task_id)
        snapshot = _clean(getattr(entry, "task_title", ""))
        if snapshot and task_id not in titles:
            titles[task_id] = (snapshot, SOURCE_ENTRY)
        bitrix_id = getattr(entry, "timesheet_bitrix_id", None)
        if bitrix_id is not None:
            timesheet_ids.append(bitrix_id)

    unresolved = [task_id for task_id in task_ids if task_id not in titles]
    if not unresolved:
        return titles

    # Источник 2: снимок названий в иерархии задач у связанных списаний.
    if timesheet_ids:
        rows = (
            TimesheetItem.objects.filter(
                bitrix_id__in=timesheet_ids, **scope_to_tenant(account)
            )
            .values("task_id", "task_hierarchy_ids", "task_hierarchy_titles")
        )
        for row in rows.iterator():
            for task_id, title in _pairs_from_hierarchy(row):
                if task_id in titles or task_id not in task_ids:
                    continue
                titles[task_id] = (title, SOURCE_TIMESHEET)

    unresolved = [task_id for task_id in task_ids if task_id not in titles]
    if not unresolved:
        return titles

    # Источник 3: справочник задач портала.
    rows = PortalTask.objects.filter(
        bitrix_id__in=unresolved, **scope_to_tenant(account)
    ).values("bitrix_id", "title")
    for row in rows.iterator():
        title = _clean(row.get("title"))
        task_id = _clean(row.get("bitrix_id"))
        if title and task_id and task_id not in titles:
            titles[task_id] = (title, SOURCE_PORTAL_TASK)

    for task_id in task_ids:
        if task_id not in titles:
            titles[task_id] = (missing_title_label(task_id), SOURCE_MISSING)

    return titles


def _pairs_from_hierarchy(row: Mapping[str, Any]) -> List[Tuple[str, str]]:
    """Пары (task_id, название) из иерархии списания.

    Иерархия — две параллельные последовательности (ids и titles) одной
    длины. Длина может разойтись на исторических записях, поэтому идём по
    минимальной и добираем название самой задачи из `task_id`, если пары для
    неё в иерархии нет.
    """
    ids = list(row.get("task_hierarchy_ids") or [])
    names = list(row.get("task_hierarchy_titles") or [])
    pairs: List[Tuple[str, str]] = []
    for index in range(min(len(ids), len(names))):
        task_id = _clean(ids[index])
        title = _clean(names[index])
        if task_id and title:
            pairs.append((task_id, title))
    # Иерархия пуста, а название последнего уровня всё же известно — редкий,
    # но встречающийся случай на старых записях.
    own_id = _clean(row.get("task_id"))
    if own_id and names and not any(task_id == own_id for task_id, _ in pairs):
        title = _clean(names[-1])
        if title:
            pairs.append((own_id, title))
    return pairs


def build_detail_groups(
    entries: Iterable[Any],
    task_titles: Optional[Mapping[str, Tuple[str, str]]] = None,
) -> List[Dict[str, Any]]:
    """Снимок документа -> уровни «задача → сотрудник → списание».

    Порядок: задачи по названию, сотрудники внутри задачи по имени, списания
    по дате. Группа «Без задачи» всегда последняя — она про недостающие
    данные, а не про работу, и в начале списка мешала бы читать.

    Ставка на уровне задачи и сотрудника показывается только если она одна на
    всю группу. Разные ставки внутри группы — обычное дело (ставка помнится
    каждым списанием), и подставить любую одну означало бы соврать; часы и
    сумма при этом складываются честно.
    """
    titles = dict(task_titles or {})
    groups: Dict[str, Dict[str, Any]] = {}

    for entry in entries:
        task_id = _clean(getattr(entry, "task_id", ""))
        key = task_id or NO_TASK_KEY
        group = groups.get(key)
        if group is None:
            if task_id:
                resolved = titles.get(task_id)
                if resolved is None:
                    # Без готового справочника (вызов без resolve_task_titles)
                    # остаётся снимок документа, и только потом заглушка.
                    snapshot = _clean(getattr(entry, "task_title", ""))
                    resolved = (
                        (snapshot, SOURCE_ENTRY) if snapshot
                        else (missing_title_label(task_id), SOURCE_MISSING)
                    )
                title, source = resolved
            else:
                title, source = NO_TASK_TITLE, SOURCE_MISSING
            group = {
                "task_id": task_id,
                "name": title,
                "title_source": source,
                "hours": 0.0,
                "amount": 0.0,
                "rates": set(),
                "employees": {},
            }
            groups[key] = group

        hours = _num(getattr(entry, "hours", 0))
        amount = _num(getattr(entry, "amount", 0))
        rate = _num(getattr(entry, "rate_snapshot", 0))

        employee_id = _clean(getattr(entry, "employee_id", ""))
        employee_name = _clean(getattr(entry, "employee_name", "")) or (
            f"Сотрудник {employee_id}" if employee_id else "Сотрудник не указан"
        )
        emp_key = employee_id or employee_name
        employee = group["employees"].get(emp_key)
        if employee is None:
            employee = {
                "employee_id": employee_id,
                "name": employee_name,
                "hours": 0.0,
                "amount": 0.0,
                "rates": set(),
                "items": [],
            }
            group["employees"][emp_key] = employee

        date_value = getattr(entry, "date_reflection", None)
        employee["items"].append({
            "date": date_value.strftime("%d.%m.%Y") if date_value else "",
            "sort_date": date_value.isoformat() if date_value else "",
            "description": _clean(getattr(entry, "description", "")) or "—",
            "hours": hours,
            "rate": rate,
            "amount": amount,
            "timesheet_bitrix_id": getattr(entry, "timesheet_bitrix_id", 0) or 0,
        })

        for bucket in (group, employee):
            bucket["hours"] += hours
            bucket["amount"] += amount
            bucket["rates"].add(round(rate, 2))

    result: List[Dict[str, Any]] = []
    for key, group in groups.items():
        employees = []
        for employee in group["employees"].values():
            employee["items"].sort(key=lambda item: (item["sort_date"], item["timesheet_bitrix_id"]))
            employees.append({
                "employee_id": employee["employee_id"],
                "name": employee["name"],
                "hours": round(employee["hours"], 2),
                "amount": round(employee["amount"], 2),
                "rate": _single_rate(employee["rates"]),
                "items": employee["items"],
            })
        employees.sort(key=lambda emp: emp["name"].lower())
        result.append({
            "task_id": group["task_id"],
            "name": group["name"],
            "title_source": group["title_source"],
            "hours": round(group["hours"], 2),
            "amount": round(group["amount"], 2),
            "rate": _single_rate(group["rates"]),
            "employees": employees,
        })

    result.sort(key=lambda grp: (0 if grp["task_id"] else 1, grp["name"].lower()))
    return result


def _single_rate(rates) -> Optional[float]:
    values = {rate for rate in rates if rate}
    if len(values) == 1:
        return next(iter(values))
    return None


def detail_export_filename(document) -> str:
    """Человеческое имя файла: «Детализация к счёту № Б-42 (01.08–31.08.2026).xlsx».

    Имя остаётся русским: Content-Disposition отдаёт его через filename*
    (RFC 5987), ASCII-фолбэк собирает view. Раньше файл назывался
    `billing_detail_<номер>.xlsx` — по такому имени в папке «Загрузки» не
    понять ни клиента, ни период.
    """
    number = _clean(getattr(document, "crm_account_number", ""))
    parts = ["Детализация"]
    parts.append(f"к счёту № {number}" if number else "к счёту")

    period = _period_label(document)
    if period:
        parts.append(f"({period})")

    company = _clean(getattr(document, "company_name", ""))
    if company:
        parts.insert(2, company)

    name = " ".join(parts)
    for bad in '\\/:*?"<>|\r\n\t':
        name = name.replace(bad, "-")
    return f"{name.strip()}.xlsx"


def _period_label(document) -> str:
    period_from = getattr(document, "period_from", None)
    period_to = getattr(document, "period_to", None)
    if period_from and period_to:
        return f"{period_from.strftime('%d.%m.%Y')} — {period_to.strftime('%d.%m.%Y')}"
    if period_from:
        return f"с {period_from.strftime('%d.%m.%Y')}"
    if period_to:
        return f"по {period_to.strftime('%d.%m.%Y')}"
    return ""


def build_billing_detail_workbook(document, entries, *, account=None):
    """Единая точка входа для view: снимок документа -> готовый xlsx.

    `account` нужен для запросов к справочникам (скоупинг по тенанту); по
    умолчанию берётся аккаунт самого документа.
    """
    entries = list(entries)
    titles = resolve_task_titles(account or document.bitrix24_account, entries)
    groups = build_detail_groups(entries, titles)
    return render_billing_detail_workbook(document, groups)
