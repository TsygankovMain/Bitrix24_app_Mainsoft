"""
Генерация структурированного Excel-файла для отчёта «Учет по проектам/задачам».

Сохраняет иерархию (проект → задача → подзадача → сотрудник → метка времени):
- объединённая шапка с названием отчёта и параметрами периода/фильтров;
- цветовая заливка и отступ по уровням;
- сворачивание групп (outline-группировка строк);
- числа как настоящие числа (формат «0.0») — суммируются в Excel;
- финальная строка ИТОГО.

Структура входных данных `nodes` совпадает с тем, что отдаёт
ReportService().generate_project_task_employees(...):
узел = {name, total_hours, billable_hours, non_billable_hours,
        children?: [...], employees?: [{name, ..., items?: [...]}]}.
"""

import io
from typing import Any, Dict, List, Optional, Sequence

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

# Колонки: A — название, B — всего, C — учтено, D — не учтено
_HOURS_FORMAT = "0.0"
_THIN = Side(style="thin", color="E2E8F0")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

# Заливки уровней (HEX без #)
_FILL_TITLE = PatternFill("solid", fgColor="1F2937")
_FILL_SUBTITLE = PatternFill("solid", fgColor="374151")
_FILL_HEAD = PatternFill("solid", fgColor="E5E7EB")
_FILL_PROJECT = PatternFill("solid", fgColor="ECFCCB")
_FILL_TASK = PatternFill("solid", fgColor="F1F5F9")
_FILL_SUBTASK = PatternFill("solid", fgColor="F8FAFC")
_FILL_EMPLOYEE = PatternFill("solid", fgColor="FFFFFF")
_FILL_ITEM = PatternFill("solid", fgColor="FBFDFF")
_FILL_TOTAL = PatternFill("solid", fgColor="CBD5E1")

_COLOR_BILL = "047857"
_COLOR_NONBILL = "BE123C"


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _write_row(
    ws: Worksheet,
    row: int,
    *,
    name: str,
    total: float,
    billable: float,
    non_billable: float,
    depth: int,
    fill: PatternFill,
    bold: bool = False,
    italic: bool = False,
    name_color: Optional[str] = None,
    outline_level: int = 0,
) -> None:
    """Записывает одну строку из 4 колонок с форматированием и уровнем группировки."""
    name_cell = ws.cell(row=row, column=1, value=name)
    name_cell.alignment = Alignment(horizontal="left", vertical="center", indent=depth)
    name_cell.font = Font(bold=bold, italic=italic, color=name_color or "0F172A")
    name_cell.fill = fill
    name_cell.border = _BORDER

    for col, value, color in (
        (2, total, "0F172A"),
        (3, billable, _COLOR_BILL),
        (4, non_billable, _COLOR_NONBILL),
    ):
        cell = ws.cell(row=row, column=col, value=round(_num(value), 2))
        cell.number_format = _HOURS_FORMAT
        cell.alignment = Alignment(horizontal="right", vertical="center")
        cell.font = Font(bold=bold, color=color)
        cell.fill = fill
        cell.border = _BORDER

    if outline_level > 0:
        ws.row_dimensions[row].outline_level = min(outline_level, 7)


def _format_iso_date(value: Any) -> str:
    """ISO-дата (YYYY-MM-DD...) -> ДД.ММ.ГГГГ, без зависимости от локали сервера."""
    if not isinstance(value, str) or len(value) < 10:
        return ""
    y, m, d = value[0:4], value[5:7], value[8:10]
    if value[4] == "-" and value[7] == "-" and y.isdigit() and m.isdigit() and d.isdigit():
        return f"{d}.{m}.{y}"
    return value[:10]


def _write_item(ws: Worksheet, row: int, item: Dict[str, Any], depth: int) -> None:
    name = item.get("nazvanie_zadachi") or item.get("opisanie") or "Без названия"
    formatted_date = _format_iso_date(item.get("data"))
    if formatted_date:
        name = f"{name} · {formatted_date}"
    hours = _num(item.get("kolichestvo_chasov"))
    is_billable = bool(item.get("uchitivaem"))
    _write_row(
        ws,
        row,
        name=name,
        total=hours,
        billable=hours if is_billable else 0.0,
        non_billable=0.0 if is_billable else hours,
        depth=depth,
        fill=_FILL_ITEM,
        italic=True,
        name_color="64748B",
        outline_level=depth,
    )


def _write_employee(ws: Worksheet, start_row: int, employee: Dict[str, Any], depth: int) -> int:
    row = start_row
    _write_row(
        ws,
        row,
        name=employee.get("name") or "—",
        total=employee.get("total_hours"),
        billable=employee.get("billable_hours"),
        non_billable=employee.get("non_billable_hours"),
        depth=depth,
        fill=_FILL_EMPLOYEE,
        name_color="334155",
        outline_level=depth,
    )
    row += 1
    for item in employee.get("items") or []:
        _write_item(ws, row, item, depth + 1)
        row += 1
    return row


def _write_node(ws: Worksheet, start_row: int, node: Dict[str, Any], depth: int) -> int:
    """Рекурсивно пишет узел (проект/задача/подзадача) и его потомков. Возвращает следующий свободный row."""
    is_project = depth == 0
    if is_project:
        fill, bold, name_color = _FILL_PROJECT, True, "3F6212"
    elif depth == 1:
        fill, bold, name_color = _FILL_TASK, True, "1E293B"
    else:
        fill, bold, name_color = _FILL_SUBTASK, False, "334155"

    row = start_row
    _write_row(
        ws,
        row,
        name=node.get("name") or "—",
        total=node.get("total_hours"),
        billable=node.get("billable_hours"),
        non_billable=node.get("non_billable_hours"),
        depth=depth,
        fill=fill,
        bold=bold,
        name_color=name_color,
        outline_level=depth,
    )
    row += 1

    for child in node.get("children") or []:
        row = _write_node(ws, row, child, depth + 1)
    for employee in node.get("employees") or []:
        row = _write_employee(ws, row, employee, depth + 1)
    return row


def build_project_task_workbook(
    nodes: Sequence[Dict[str, Any]],
    *,
    date_from: str = "",
    date_to: str = "",
    filters_label: str = "",
) -> io.BytesIO:
    """Строит xlsx-файл отчёта и возвращает BytesIO (указатель в начале)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Проект-Задача"

    # Группировка: кнопка сворачивания на строке-родителе (она ВЫШЕ потомков)
    ws.sheet_properties.outlinePr.summaryBelow = False
    ws.sheet_properties.outlinePr.summaryRight = False

    # --- Шапка отчёта (объединённые ячейки) ---
    period = f"{date_from} — {date_to}".strip(" —")
    title = "Учет по проектам/задачам"
    if period:
        title = f"{title} · период {period}"

    ws.merge_cells("A1:D1")
    c = ws.cell(row=1, column=1, value=title)
    c.font = Font(bold=True, color="FFFFFF", size=12)
    c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    c.fill = _FILL_TITLE
    ws.row_dimensions[1].height = 24

    ws.merge_cells("A2:D2")
    subtitle = filters_label or "Сотрудники: все · Проекты: все"
    c2 = ws.cell(row=2, column=1, value=subtitle)
    c2.font = Font(color="CBD5E1", size=10)
    c2.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    c2.fill = _FILL_SUBTITLE

    # --- Шапка колонок ---
    headers = ["Название", "Всего, ч", "Учтено, ч", "Не учтено, ч"]
    for col, label in enumerate(headers, start=1):
        cell = ws.cell(row=3, column=col, value=label)
        cell.font = Font(bold=True, color="111827")
        cell.fill = _FILL_HEAD
        cell.border = _BORDER
        cell.alignment = Alignment(
            horizontal="left" if col == 1 else "right", vertical="center"
        )

    # --- Данные ---
    row = 4
    grand_total = grand_bill = grand_nonbill = 0.0
    for node in nodes:
        grand_total += _num(node.get("total_hours"))
        grand_bill += _num(node.get("billable_hours"))
        grand_nonbill += _num(node.get("non_billable_hours"))
        row = _write_node(ws, row, node, 0)

    # --- ИТОГО ---
    _write_row(
        ws,
        row,
        name="ИТОГО",
        total=grand_total,
        billable=grand_bill,
        non_billable=grand_nonbill,
        depth=0,
        fill=_FILL_TOTAL,
        bold=True,
    )

    # Ширина колонок и закрепление заголовков
    widths = {1: 55, 2: 12, 3: 12, 4: 14}
    for col, width in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.freeze_panes = "A4"

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output
