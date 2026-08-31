from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from django.db.models import Q
from django.utils import timezone

from .employee_ids import build_employee_id_aliases
from .models import Bitrix24Account, PortalTask, TimesheetItem
from .project_board_shared import get_project_card_queryset
from .tenant_scoping import scope_to_tenant


TREE_REPORT_FIELDS = (
    "employee_id",
    "project_item_id",
    "project_id",
    "project_title",
    "hours",
    "task_hierarchy_ids",
    "task_hierarchy_titles",
    "is_billable",
    "description",
    "date_reflection",
    "bitrix_id",
    "task_id",
)


def build_filtered_timesheet_queryset(account: Bitrix24Account, params: Mapping[str, Any]):
    queryset = TimesheetItem.objects.filter(**scope_to_tenant(account))

    date_from = _parse_date_value(params.get("date_from"))
    date_to = _parse_date_value(params.get("date_to"))
    if date_from:
        queryset = queryset.filter(date_reflection__gte=_day_start(date_from))
    if date_to:
        queryset = queryset.filter(date_reflection__lt=_next_day_start(date_to))

    archived_cards = get_project_card_queryset(account).filter(is_archived=True)
    archived_rows = archived_cards.values_list("project_item_id", "project_id", "project_name")
    archived_item_ids = set()
    archived_ids = set()
    archived_names = set()
    for item_id, group_id, name in archived_rows:
        if item_id:
            archived_item_ids.add(item_id)
        if group_id:
            archived_ids.add(group_id)
        if name:
            archived_names.add(name)
    queryset = queryset.exclude(
        Q(project_item_id__in=archived_item_ids)
        | Q(project_id__in=archived_ids)
        | Q(project_title__in=archived_names)
    )

    employee_ids = _normalize_multi_value(params.get("employee_ids") or params.get("employee_ids[]"))
    employee_filter_ids = build_employee_id_aliases(employee_ids)
    employee_mode = str(params.get("employee_mode") or "include")
    if employee_filter_ids:
        if employee_mode == "exclude":
            queryset = queryset.exclude(employee_id__in=employee_filter_ids)
        else:
            queryset = queryset.filter(employee_id__in=employee_filter_ids)

    project_ids = _normalize_multi_value(params.get("project_ids") or params.get("project_ids[]"))
    project_mode = str(params.get("project_mode") or "include")
    if project_ids:
        project_q = _build_project_match_q(account, project_ids)
        if project_mode == "exclude":
            queryset = queryset.exclude(project_q)
        else:
            queryset = queryset.filter(project_q)

    return queryset


def _build_project_match_q(account: Bitrix24Account, project_ids: Sequence[str]) -> Q:
    """Разворачивает выбранную опцию в полный набор ключей её карточки.

    Опция несёт один идентификатор (id группы), а строка списания привязана к
    проекту одним из трёх ключей — project_item_id, project_id, project_title.
    Без разворота выбор проекта, чьи списания привязаны через элемент
    смарт-процесса, давал пустой отчёт.

    Каждый ключ матчится СО СВОЕЙ колонкой. Раньше выбранное значение шло во
    все три колонки разом, а id группы и id элемента смарт-процесса живут в
    одном числовом пространстве: id группы одного проекта мог совпасть с id
    элемента другого и затащить в отчёт чужие строки. Поэтому сырое значение
    кладём только в project_id/project_title (именно их несут опции), а в
    project_item_id — только то, что пришло из найденной карточки.
    """
    selected = set(project_ids)
    item_ids: set = set()
    group_ids: set = set(selected)
    titles: set = set(selected)

    matched_cards = (
        get_project_card_queryset(account)
        .filter(Q(project_id__in=selected) | Q(project_name__in=selected))
        .values("project_item_id", "project_id", "project_name")
    )
    for card in matched_cards:
        item_id = _clean_key(card.get("project_item_id"))
        group_id = _clean_key(card.get("project_id"))
        title = _clean_key(card.get("project_name"))
        if item_id:
            item_ids.add(item_id)
        if group_id:
            group_ids.add(group_id)
        if title:
            titles.add(title)

    project_q = Q(project_id__in=group_ids) | Q(project_title__in=titles)
    if item_ids:
        project_q |= Q(project_item_id__in=item_ids)
    return project_q


def materialize_rows(queryset, fields: Sequence[str]) -> List[Dict[str, Any]]:
    return list(queryset.values(*fields).iterator())


def build_project_filter_options(account: Bitrix24Account) -> List[Dict[str, str]]:
    """Опции фильтра «Проекты» — из реестра карточек, а не из строк списаний.

    Раньше список собирался обходом timesheet_item, а реестр работал только
    отсечкой. Активная карточка без подходящих строк в список не попадала
    никогда: у нового проекта списаний ещё нет, а у старого они могут быть
    привязаны через project_item_id, который здесь не смотрели вовсе (доска
    смотрит — ProjectCardService.refresh_writeoff_stats, и сам запрос отчёта
    смотрит — build_filtered_timesheet_queryset). Отсюда боевая жалоба
    06.08.2026: проект виден в рабочем пространстве, в фильтре — «Ничего не
    найдено».

    Имя опции — project_name карточки, тем же именем проект подписан в теле
    отчёта (resolve_project_name_for_row) и в рабочем пространстве. Сырой
    project_title из списания сюда больше не попадает: он мог разойтись с
    карточкой, и человек искал имя, которое видит везде.
    """
    cards = get_project_card_queryset(account)
    active_rows = list(cards.filter(is_archived=False).values("project_item_id", "project_id", "project_name"))

    if not active_rows:
        # Пустой реестр (свежая установка, либо таблица карточек недоступна и
        # get_project_card_queryset вернул .none()) — падаем на прежний путь,
        # иначе фильтр остался бы пустым, а это хуже сегодняшнего. Именно
        # «карточек нет вообще», а не «нет активных»: если все карточки в
        # архиве, фильтру нечего предлагать — строки архивных проектов
        # build_filtered_timesheet_queryset и так выкидывает из всех отчётов.
        if cards.exists():
            return []
        return _build_project_filter_options_from_timesheets(account)

    options: List[Dict[str, str]] = []
    seen_ids = set()

    for row in active_rows:
        option_id = _clean_key(row.get("project_id")) or _clean_key(row.get("project_item_id"))
        if not option_id or option_id in seen_ids:
            continue
        seen_ids.add(option_id)
        options.append({
            "id": option_id,
            "name": _clean_key(row.get("project_name")) or "Без названия",
        })

    return sorted(options, key=lambda item: item["name"])


def _build_project_filter_options_from_timesheets(account: Bitrix24Account) -> List[Dict[str, str]]:
    rows = (
        TimesheetItem.objects.filter(**scope_to_tenant(account))
        .values("project_id", "project_title")
        .distinct()
    )

    options: List[Dict[str, str]] = []
    seen_ids = set()

    for row in rows:
        project_id = _clean_key(row.get("project_id"))
        project_title = _clean_key(row.get("project_title"))
        final_id = project_id or project_title
        if not final_id or final_id in seen_ids:
            continue
        seen_ids.add(final_id)
        options.append({"id": final_id, "name": project_title or "Без названия"})

    return sorted(options, key=lambda item: item["name"])


def _clean_key(value: Any) -> str:
    return str(value or "").strip()


def build_project_title_lookups(account: Bitrix24Account) -> tuple[Dict[str, str], Dict[str, str]]:
    rows = (
        get_project_card_queryset(account)
        .exclude(project_name__isnull=True)
        .exclude(project_name="")
        .values_list("project_item_id", "project_id", "project_name")
    )
    by_item: Dict[str, str] = {}
    by_group: Dict[str, str] = {}
    for project_item_id, project_id, project_name in rows:
        if project_item_id:
            by_item[str(project_item_id).strip()] = project_name
        if project_id:
            by_group[str(project_id).strip()] = project_name
    return by_item, by_group


def resolve_project_name_for_row(
    row: Mapping[str, Any],
    project_name_by_item: Optional[Mapping[str, str]] = None,
    project_name_by_group: Optional[Mapping[str, str]] = None,
) -> str:
    project_item_id = str(row.get("project_item_id") or "").strip()
    if project_item_id and project_name_by_item:
        mapped = project_name_by_item.get(project_item_id)
        if mapped:
            return mapped

    project_id = str(row.get("project_id") or "").strip()
    if project_id and project_name_by_group:
        mapped = project_name_by_group.get(project_id)
        if mapped:
            return mapped

    fallback_name = str(row.get("project_title") or "").strip()
    if fallback_name:
        return fallback_name
    return "Не определён"


def build_task_lookup(account: Bitrix24Account) -> Dict[str, Dict[str, str]]:
    """Справочник задач портала: task_id -> {title, group_id}.

    Источник актуальной правды для отчётов. Название задачи и её проект
    хранятся в записи СНИМКОМ на момент списания и не обновляются никогда:
    перенос или переименование меняют задачу, а не карточку списания, поэтому
    её updatedTime не двигается и синк её не перечитывает.

    Наполняет таблицу TaskSyncService (фоновый scope=tasks, раз в час).
    Задача, которой в справочнике ещё нет, отдаёт снимок — деградация мягкая.
    """
    rows = PortalTask.objects.filter(**scope_to_tenant(account)).values(
        "bitrix_id", "title", "group_id"
    )
    return {
        str(row["bitrix_id"]): {
            "title": row["title"] or "",
            "group_id": str(row["group_id"] or ""),
        }
        for row in rows.iterator()
    }


def resolve_current_group_for_row(
    row: Mapping[str, Any],
    task_lookup: Optional[Mapping[str, Mapping[str, str]]] = None,
) -> str:
    """Актуальная группа (проект) задачи из справочника; '' если неизвестна."""
    if not task_lookup:
        return ""
    task = task_lookup.get(str(row.get("task_id") or "").strip())
    if not task:
        return ""
    return str(task.get("group_id") or "").strip()


def resolve_task_titles_for_row(
    row: Mapping[str, Any],
    task_lookup: Optional[Mapping[str, Mapping[str, str]]] = None,
) -> List[str]:
    """Иерархия названий задач с актуальными именами вместо снимка.

    Поэлементно: если задача есть в справочнике и у неё непустое название —
    берём его, иначе оставляем снимок. Длина и порядок цепочки сохраняются,
    потому что по ней строится дерево отчёта.
    """
    snapshot = list(row.get("task_hierarchy_titles") or [])
    if not task_lookup:
        return snapshot

    ids = list(row.get("task_hierarchy_ids") or [])
    resolved = list(snapshot)
    for index, task_id in enumerate(ids):
        if index >= len(resolved):
            break
        task = task_lookup.get(str(task_id).strip())
        if task and task.get("title"):
            resolved[index] = task["title"]
    return resolved


def resolve_project_key_for_row(row: Mapping[str, Any]) -> str:
    """Устойчивый ключ проекта для группировки в отчётах.

    Дерево отчёта раньше ключевало узел проекта ПО ИМЕНИ
    (report_services: emp_node["children"][proj_name]), и любое расхождение в
    тексте немедленно давало вторую строку одного и того же проекта. Расхождения
    берутся не из воздуха: project_title — это снимок на момент списания, а
    normalize_items при пустом поле проекта подставлял туда НАЗВАНИЕ ЗАДАЧИ.
    На проде это 18 задач, чьи записи несут больше одного значения проекта, и
    185 записей без опоры на карточку проекта.

    Приоритет: project_item_id (элемент СП «Проект») -> project_id (группа
    Битрикса) -> имя. Имя остаётся последним рубежом для записей, где нет ни
    того ни другого (12 строк на проде), — иначе они схлопнулись бы в один
    общий узел, что хуже.

    Ключ используется ТОЛЬКО для группировки; отображаемое имя по-прежнему
    даёт resolve_project_name_for_row, то есть актуальное имя карточки.
    """
    project_item_id = str(row.get("project_item_id") or "").strip()
    if project_item_id:
        return f"item:{project_item_id}"

    project_id = str(row.get("project_id") or "").strip()
    if project_id:
        return f"group:{project_id}"

    return f"name:{str(row.get('project_title') or '').strip()}"


def build_tree_report_items(
    rows: Iterable[Dict[str, Any]],
    include_task_id: bool = False,
    project_name_by_item: Optional[Mapping[str, str]] = None,
    project_name_by_group: Optional[Mapping[str, str]] = None,
    task_lookup: Optional[Mapping[str, Mapping[str, str]]] = None,
) -> List[Dict[str, Any]]:
    """Строки БД -> элементы отчёта.

    Про task_lookup. Приоритет — АКТУАЛЬНЫЕ показатели: если задачу
    переименовали или перенесли в другой проект, отчёт обязан показывать
    новое состояние, а не то, что было записано в момент списания. Поэтому
    название задачи и её проект берутся из справочника PortalTask, а снимок в
    записи остаётся нетронутым как след «под чем списывалось».

    Резолв идёт НА ЧТЕНИИ, а не переписыванием строк: вся история становится
    актуальной сразу, без миграции, и решение обратимо.

    Заморозка закрытых периодов здесь не нужна — закрытие сделано правами
    Битрикса и распространяется и на задачи, и на проекты, поэтому перенести
    что-либо в закрытом периоде нельзя в принципе.

    Без task_lookup (справочник ещё не наполнен, вызов из тестов) поведение
    прежнее: во всём используется снимок.
    """
    items = []
    for row in rows:
        current_group = resolve_current_group_for_row(row, task_lookup)
        current_titles = resolve_task_titles_for_row(row, task_lookup)
        # Актуальная группа замещает снимок и в имени проекта, и в ключе
        # группировки — иначе перенесённая задача осталась бы под старым
        # проектом.
        effective_row = dict(row)
        if current_group:
            effective_row["project_id"] = current_group
            # project_item_id — снимок элемента СП «Проект» СТАРОГО проекта;
            # при переносе он ведёт не туда, поэтому уступает группе.
            effective_row["project_item_id"] = ""

        item = {
            "sotrudnik_id": row["employee_id"],
            "project_name": resolve_project_name_for_row(
                effective_row, project_name_by_item, project_name_by_group
            ),
            "project_key": resolve_project_key_for_row(effective_row),
            "kolichestvo_chasov": row["hours"],
            "id_zadach_ierarhiya": row["task_hierarchy_ids"],
            # Названия — актуальные из справочника, снимок только там, где
            # задачи в справочнике ещё нет.
            "title_zadach_ierarhiya": current_titles,
            "uchitivaem": row["is_billable"],
            "opisanie": row["description"],
            "data": row["date_reflection"].isoformat() if row.get("date_reflection") else None,
            "nazvanie_zadachi": current_titles[-1] if current_titles else "No Title",
            "id_elem": row["bitrix_id"],
        }
        if include_task_id:
            item["id_zadachi"] = row["task_id"]
        items.append(item)
    return items


def _normalize_multi_value(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw_values = value
    else:
        raw_values = [value]
    normalized = []
    for item in raw_values:
        item_str = str(item).strip()
        if item_str:
            normalized.append(item_str)
    return normalized


def _parse_date_value(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _day_start(day_value: date) -> datetime:
    return timezone.make_aware(datetime.combine(day_value, time.min), timezone.get_current_timezone())


def _next_day_start(day_value: date) -> datetime:
    return _day_start(day_value + timedelta(days=1))
