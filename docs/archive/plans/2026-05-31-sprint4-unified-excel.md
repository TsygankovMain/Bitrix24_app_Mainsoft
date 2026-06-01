# Спринт 4 — Единый структурный Excel + техдолг — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`). Реализация — Haiku-агентами под ревью.

**Goal:** Перевести выгрузку Excel всех 6 отчётов на серверный структурный openpyxl (как project-task) + закрыть 2 пункта техдолга (ESLint, изоляция finance на фронте).

**Architecture:** 3 переиспользуемых генератора в `report_excel.py` (иерархия/матрица/таблица). 6 новых export-endpoint по образцу `report_project_task_employee_export` мирорят данные JSON-версии своего отчёта и зовут нужный генератор. Фронт переключает `handleExport` на сервер, мёртвый фронтовый xlsx удаляется.

**Tech Stack:** Django/openpyxl (бэк), Nuxt3/Vue3 (фронт). Тесты бэка: `cd backends/python/api && DJANGO_SETTINGS_MODULE=test_settings .venv/bin/python -m unittest <module> -v`. Фронт: `npx nuxt prepare`, `npm run lint`.

---

## File Structure
- `backends/python/api/main/report_excel.py` — +3 генератора (`build_hierarchy_workbook`, `build_matrix_workbook`, `build_table_workbook`) + формат-хелпер.
- `backends/python/api/main/tests_report_excel.py` — НОВЫЙ, тесты генераторов.
- `backends/python/api/main/views.py` — +6 export-view; `urls.py` — +6 роутов.
- `frontend/app/stores/api.ts` — +6 export-методов.
- `frontend/app/pages/reports/{employee,project,daily,revenue-leakage,time-discipline,focus-analysis}.client.vue` — `handleExport` → сервер.
- `frontend/app/utils/reportExport.ts` / `exportXlsx.ts` — удалить мёртвый код.
- Техдолг: `frontend/app/utils/{iframe-resizer,openCrmItem,openProjectGroup}.ts`; `frontend/app/pages/handler/placement-crm-deal-detail-tab.client.vue`, `frontend/app/stores/api.ts`.

---

## Task 1: Генератор иерархии (TDD)

**Files:** Modify `report_excel.py`; Create `tests_report_excel.py`

- [ ] **Step 1: Тест** (`tests_report_excel.py`):

```python
import os, unittest
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
django.setup()
from main.report_excel import build_hierarchy_workbook  # noqa: E402

class HierarchyWB(unittest.TestCase):
    def test_valid_xlsx_with_totals(self):
        roots = [{"name": "Проект", "total_hours": 10, "billable_hours": 8, "non_billable_hours": 2,
                  "children": [{"name": "Сотрудник", "total_hours": 10, "billable_hours": 8,
                                "non_billable_hours": 2, "children": []}]}]
        out = build_hierarchy_workbook(roots, title="Отчёт по проектам", date_from="2026-05-01", date_to="2026-05-31")
        data = out.read()
        self.assertEqual(data[:2], b"PK")
        self.assertGreater(len(data), 0)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Запустить — упадёт** (нет `build_hierarchy_workbook`).

Run: `cd backends/python/api && DJANGO_SETTINGS_MODULE=test_settings .venv/bin/python -m unittest main.tests_report_excel -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Реализация** — добавить в `report_excel.py` (использует существующие `_FILL_TITLE/_FILL_HEAD/_FILL_PROJECT/_FILL_TASK/_FILL_SUBTASK/_FILL_TOTAL/_BORDER/_HOURS_FORMAT/_num`, импорты `openpyxl, io, Font, Alignment, get_column_letter` уже есть):

```python
def build_hierarchy_workbook(roots, *, title, date_from="", date_to="",
                             value_columns=(("Всего, ч", "total_hours"),
                                            ("Учтено, ч", "billable_hours"),
                                            ("Не учтено, ч", "non_billable_hours"))):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Отчёт"
    ws.sheet_properties.outlinePr.summaryBelow = False
    ncols = 1 + len(value_columns)
    last_col = get_column_letter(ncols)
    period = f"{date_from} — {date_to}".strip(" —")
    full_title = f"{title} · период {period}" if period else title
    ws.merge_cells(f"A1:{last_col}1")
    c = ws.cell(1, 1, full_title); c.font = Font(bold=True, color="FFFFFF", size=12)
    c.fill = _FILL_TITLE; c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    h = ws.cell(2, 1, "Название"); h.font = Font(bold=True, color="111827"); h.fill = _FILL_HEAD
    h.border = _BORDER; h.alignment = Alignment(horizontal="left", vertical="center")
    for i, (label, _) in enumerate(value_columns):
        cell = ws.cell(2, 2 + i, label); cell.font = Font(bold=True, color="111827")
        cell.fill = _FILL_HEAD; cell.border = _BORDER; cell.alignment = Alignment(horizontal="right", vertical="center")
    row = 3
    totals = [0.0] * len(value_columns)

    def _write(node, depth):
        nonlocal row
        fill = _FILL_PROJECT if depth == 0 else (_FILL_TASK if depth == 1 else _FILL_SUBTASK)
        bold = depth <= 1
        nc = ws.cell(row, 1, node.get("name") or "—")
        nc.alignment = Alignment(horizontal="left", vertical="center", indent=depth)
        nc.font = Font(bold=bold); nc.fill = fill; nc.border = _BORDER
        for i, (_, key) in enumerate(value_columns):
            cell = ws.cell(row, 2 + i, round(_num(node.get(key)), 2))
            cell.number_format = _HOURS_FORMAT; cell.alignment = Alignment(horizontal="right", vertical="center")
            cell.font = Font(bold=bold); cell.fill = fill; cell.border = _BORDER
        if depth > 0:
            ws.row_dimensions[row].outline_level = min(depth, 7)
        row += 1
        for ch in node.get("children") or []:
            _write(ch, depth + 1)

    for node in roots:
        for i, (_, key) in enumerate(value_columns):
            totals[i] += _num(node.get(key))
        _write(node, 0)

    tc = ws.cell(row, 1, "ИТОГО"); tc.font = Font(bold=True); tc.fill = _FILL_TOTAL; tc.border = _BORDER
    for i, t in enumerate(totals):
        cell = ws.cell(row, 2 + i, round(t, 2)); cell.number_format = _HOURS_FORMAT
        cell.font = Font(bold=True); cell.fill = _FILL_TOTAL
        cell.alignment = Alignment(horizontal="right", vertical="center"); cell.border = _BORDER
    ws.column_dimensions["A"].width = 55
    for idx in range(2, ncols + 1):
        ws.column_dimensions[get_column_letter(idx)].width = 14
    ws.freeze_panes = "A3"
    output = io.BytesIO(); wb.save(output); output.seek(0)
    return output
```

- [ ] **Step 4: Запустить — пройдёт.** Run: та же команда. Expected: PASS.
- [ ] **Step 5: Commit** `git add report_excel.py tests_report_excel.py && git commit -m "feat(excel): hierarchy workbook builder"`

---

## Task 2: Генератор матрицы (TDD)

**Files:** Modify `report_excel.py`, `tests_report_excel.py`

- [ ] **Step 1: Тест** (добавить класс):

```python
from main.report_excel import build_matrix_workbook  # вверху файла

class MatrixWB(unittest.TestCase):
    def test_valid(self):
        header_days = [{"date": "2026-05-01"}, {"date": "2026-05-02"}]
        rows = [{"employee": {"name": "Иванов"}, "days": {"2026-05-01": {"total": 8}, "2026-05-02": {"total": 7}}}]
        out = build_matrix_workbook(header_days, rows, title="Ежедневная нагрузка", date_from="2026-05-01", date_to="2026-05-02")
        self.assertEqual(out.read()[:2], b"PK")
```

- [ ] **Step 2: Запустить — упадёт.**
- [ ] **Step 3: Реализация** (`report_excel.py`):

```python
def build_matrix_workbook(header_days, rows, *, title, date_from="", date_to=""):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Нагрузка"
    days = [(d.get("date") if isinstance(d, dict) else d) for d in header_days]
    ncols = 1 + len(days) + 1
    last_col = get_column_letter(ncols)
    period = f"{date_from} — {date_to}".strip(" —")
    full_title = f"{title} · период {period}" if period else title
    ws.merge_cells(f"A1:{last_col}1")
    c = ws.cell(1, 1, full_title); c.font = Font(bold=True, color="FFFFFF", size=12)
    c.fill = _FILL_TITLE; c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    hh = ws.cell(2, 1, "Сотрудник"); hh.font = Font(bold=True); hh.fill = _FILL_HEAD; hh.border = _BORDER
    hh.alignment = Alignment(horizontal="left", vertical="center")
    for i, day in enumerate(days):
        cell = ws.cell(2, 2 + i, _format_iso_date(day) or str(day))
        cell.font = Font(bold=True); cell.fill = _FILL_HEAD; cell.border = _BORDER
        cell.alignment = Alignment(horizontal="right", vertical="center")
    th = ws.cell(2, ncols, "Итого"); th.font = Font(bold=True); th.fill = _FILL_HEAD; th.border = _BORDER
    th.alignment = Alignment(horizontal="right", vertical="center")
    col_tot = [0.0] * len(days); grand = 0.0; row = 3
    for r in rows:
        ws.cell(row, 1, (r.get("employee") or {}).get("name") or "—").border = _BORDER
        rowsum = 0.0; cells = r.get("days") or {}
        for i, day in enumerate(days):
            cd = cells.get(day) or {}
            v = _num(cd.get("total")) if isinstance(cd, dict) else _num(cd)
            cell = ws.cell(row, 2 + i, round(v, 2) if v else None)
            cell.number_format = _HOURS_FORMAT; cell.alignment = Alignment(horizontal="right", vertical="center"); cell.border = _BORDER
            rowsum += v; col_tot[i] += v
        rc = ws.cell(row, ncols, round(rowsum, 2)); rc.number_format = _HOURS_FORMAT
        rc.font = Font(bold=True); rc.fill = _FILL_TOTAL; rc.alignment = Alignment(horizontal="right", vertical="center"); rc.border = _BORDER
        grand += rowsum; row += 1
    tcell = ws.cell(row, 1, "ИТОГО"); tcell.font = Font(bold=True); tcell.fill = _FILL_TOTAL; tcell.border = _BORDER
    for i, ct in enumerate(col_tot):
        cell = ws.cell(row, 2 + i, round(ct, 2)); cell.number_format = _HOURS_FORMAT
        cell.font = Font(bold=True); cell.fill = _FILL_TOTAL; cell.alignment = Alignment(horizontal="right", vertical="center"); cell.border = _BORDER
    gc = ws.cell(row, ncols, round(grand, 2)); gc.number_format = _HOURS_FORMAT
    gc.font = Font(bold=True); gc.fill = _FILL_TOTAL; gc.alignment = Alignment(horizontal="right", vertical="center"); gc.border = _BORDER
    ws.column_dimensions["A"].width = 24
    for idx in range(2, ncols + 1):
        ws.column_dimensions[get_column_letter(idx)].width = 10
    ws.freeze_panes = "B3"
    output = io.BytesIO(); wb.save(output); output.seek(0)
    return output
```

- [ ] **Step 4: Запустить — пройдёт.**
- [ ] **Step 5: Commit** `git commit -am "feat(excel): matrix workbook builder"`

---

## Task 3: Генератор таблицы (TDD)

**Files:** Modify `report_excel.py`, `tests_report_excel.py`

- [ ] **Step 1: Тест**:

```python
from main.report_excel import build_table_workbook

class TableWB(unittest.TestCase):
    def test_valid_with_total(self):
        cols = [{"key": "proj", "label": "Проект", "fmt": "text"},
                {"key": "hours", "label": "Всего, ч", "fmt": "hours"},
                {"key": "loss", "label": "Потеря, ₽", "fmt": "money"},
                {"key": "pct", "label": "% потерь", "fmt": "percent"}]
        rows = [{"proj": "Сайт", "hours": 140, "loss": 36000, "pct": 0.086}]
        total = {"proj": "ИТОГО", "hours": 140, "loss": 36000, "pct": 0.086}
        out = build_table_workbook(cols, rows, title="Потери выручки", total_row=total)
        self.assertEqual(out.read()[:2], b"PK")
```

- [ ] **Step 2: Запустить — упадёт.**
- [ ] **Step 3: Реализация** (`report_excel.py`):

```python
_TABLE_FMT = {"text": "@", "hours": "0.0", "money": "#,##0", "percent": "0.0%"}

def build_table_workbook(columns, rows, *, title, date_from="", date_to="", total_row=None):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Отчёт"
    ncols = len(columns); last_col = get_column_letter(max(ncols, 1))
    period = f"{date_from} — {date_to}".strip(" —")
    full_title = f"{title} · период {period}" if period else title
    ws.merge_cells(f"A1:{last_col}1")
    c = ws.cell(1, 1, full_title); c.font = Font(bold=True, color="FFFFFF", size=12)
    c.fill = _FILL_TITLE; c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    for i, col in enumerate(columns):
        cell = ws.cell(2, 1 + i, col["label"]); cell.font = Font(bold=True, color="111827")
        cell.fill = _FILL_HEAD; cell.border = _BORDER
        cell.alignment = Alignment(horizontal="left" if col.get("fmt", "text") == "text" else "right", vertical="center")
    row = 3

    def _put(r, rownum, bold=False, fill=None):
        for i, col in enumerate(columns):
            fmt = col.get("fmt", "text"); val = r.get(col["key"])
            if fmt == "text" or val is None:
                cell = ws.cell(rownum, 1 + i, "" if val is None else str(val))
                cell.alignment = Alignment(horizontal="left", vertical="center")
                if fmt != "text":
                    cell.number_format = "@"
            else:
                cell = ws.cell(rownum, 1 + i, _num(val)); cell.number_format = _TABLE_FMT[fmt]
                cell.alignment = Alignment(horizontal="right", vertical="center")
            cell.border = _BORDER
            if bold:
                cell.font = Font(bold=True)
            if fill:
                cell.fill = fill

    for r in rows:
        _put(r, row); row += 1
    if total_row:
        _put(total_row, row, bold=True, fill=_FILL_TOTAL)
    for i, col in enumerate(columns):
        ws.column_dimensions[get_column_letter(1 + i)].width = col.get("width", 18)
    ws.freeze_panes = "A3"
    output = io.BytesIO(); wb.save(output); output.seek(0)
    return output
```

- [ ] **Step 4: Запустить — все тесты `tests_report_excel` PASS.**
- [ ] **Step 5: Commit** `git commit -am "feat(excel): table workbook builder"`

---

## Task 4: Export-endpoints для иерархии (employee, project)

**Files:** Modify `views.py`, `urls.py`

Образец — `report_project_task_employee_export` (`views.py`). Для каждого: повторить data-генерацию соответствующего JSON-view, затем `build_hierarchy_workbook` + `HttpResponse`.

- [ ] **Step 1:** Прочитать существующие JSON-views `report_employee_project` и `report_project_employee` в `views.py` — скопировать их блок построения данных (queryset → rows → иерархия `HierarchicalReportNode[]`).
- [ ] **Step 2:** Добавить `report_excel` импорт: в строке `from .report_excel import build_project_task_workbook` дополнить до `build_project_task_workbook, build_hierarchy_workbook, build_matrix_workbook, build_table_workbook`.
- [ ] **Step 3:** Добавить 2 view (декораторы как у export project-task: `@xframe_options_exempt @require_GET @log_errors(...) @auth_required`):

```python
def report_employee_project_export(request: AuthorizedRequest):
    # <повторить data-генерацию report_employee_project → roots (список узлов)>
    output = build_hierarchy_workbook(roots, title="Отчет по сотрудникам",
                                      date_from=request.GET.get("date_from", ""), date_to=request.GET.get("date_to", ""))
    response = HttpResponse(output.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="report_employee_project.xlsx"'
    return response
```
Аналогично `report_project_employee_export` (title="Отчет по проектам", filename `report_project_employee.xlsx`).

- [ ] **Step 4:** В `__all__` добавить `"report_employee_project_export"`, `"report_project_employee_export"`. В `urls.py` добавить роуты `api/report-employee-project-export`, `api/report-project-employee-export`.
- [ ] **Step 5: Проверка** `cd backends/python/api && .venv/bin/python -m py_compile main/views.py main/urls.py && DJANGO_SETTINGS_MODULE=test_settings .venv/bin/python manage.py check` → no issues.
- [ ] **Step 6: Commit** `git commit -am "feat(excel): employee/project hierarchy export endpoints"`

---

## Task 5: Export-endpoint для матрицы (daily)

**Files:** Modify `views.py`, `urls.py`

- [ ] **Step 1:** Прочитать `report_daily_workload` (JSON-view) — он возвращает структуру с `header_days` и `rows` (см. тип `DailyWorkloadReport`, `frontend/app/types/report.ts`; на бэке — `report_services`). Скопировать блок генерации `header_days`/`rows`.
- [ ] **Step 2:** Добавить view `report_daily_workload_export` (декораторы как выше):

```python
def report_daily_workload_export(request: AuthorizedRequest):
    # <повторить генерацию report_daily_workload → report с report["header_days"], report["rows"]>
    output = build_matrix_workbook(report["header_days"], report["rows"], title="Ежедневная нагрузка",
                                   date_from=request.GET.get("date_from", ""), date_to=request.GET.get("date_to", ""))
    response = HttpResponse(output.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="report_daily_workload.xlsx"'
    return response
```
(если ключи в ответе иные — взять реальные имена из JSON-view.)

- [ ] **Step 3:** `__all__` + роут `api/report-daily-workload-export`.
- [ ] **Step 4: Проверка** `py_compile` + `manage.py check`.
- [ ] **Step 5: Commit** `git commit -am "feat(excel): daily matrix export endpoint"`

---

## Task 6: Export-endpoints для сводных таблиц (revenue-leakage, time-discipline, focus-analysis)

**Files:** Modify `views.py`, `urls.py`

Для каждого: повторить data-генерацию JSON-view, определить `columns` (по реальным полям строк отчёта — прочитать JSON-view и тип в `types/report.ts`), вызвать `build_table_workbook`.

- [ ] **Step 1:** Прочитать JSON-views `report_revenue_leakage`, `report_time_entry_discipline`, `report_focus_analysis` и соответствующие типы (`RevenueLeakageReport`, `TimeEntryDisciplineReport`/аналог, `FocusAnalysisReport`) — выписать поля строк.
- [ ] **Step 2:** Добавить 3 view. Пример (revenue-leakage; `columns` — подставить реальные ключи полей строки):

```python
def report_revenue_leakage_export(request: AuthorizedRequest):
    # <повторить генерацию report_revenue_leakage → report; rows = report["rows"] (или нужный ключ)>
    columns = [
        {"key": "project_name", "label": "Проект", "fmt": "text", "width": 28},
        {"key": "employee_name", "label": "Сотрудник", "fmt": "text", "width": 22},
        {"key": "total_hours", "label": "Всего, ч", "fmt": "hours"},
        {"key": "non_billable_hours", "label": "Не учтено, ч", "fmt": "hours"},
        {"key": "loss_amount", "label": "Потеря, ₽", "fmt": "money"},
        {"key": "loss_percent", "label": "% потерь", "fmt": "percent"},
    ]  # ИМЕНА КЛЮЧЕЙ СВЕРИТЬ С РЕАЛЬНЫМ ОТВЕТОМ report_revenue_leakage
    output = build_table_workbook(columns, report_rows, title="Потери выручки",
                                  date_from=request.GET.get("date_from", ""), date_to=request.GET.get("date_to", ""))
    response = HttpResponse(output.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="report_revenue_leakage.xlsx"'
    return response
```
Аналогично для `report_time_entry_discipline_export` (title="Дисциплина внесения времени") и `report_focus_analysis_export` (title="Фокус и распыление") — `columns` под их реальные поля; проценты в `percent` нужно передавать как доля (0..1) — если в ответе проценты как 0..100, делить на 100 при сборке rows, либо использовать `fmt:"hours"` и label «%».

- [ ] **Step 3:** `__all__` + 3 роута (`…-export`).
- [ ] **Step 4: Проверка** `py_compile` + `manage.py check`.
- [ ] **Step 5: Commit** `git commit -am "feat(excel): summary table export endpoints"`

---

## Task 7: Фронт — api-методы экспорта (6 шт)

**Files:** Modify `frontend/app/stores/api.ts`

- [ ] **Step 1:** По образцу `exportReportProjectTaskEmployee` добавить 6 методов (GET + `responseType:'blob'` + JWT), каждый дёргает свой `…-export` endpoint с теми же query-параметрами (`buildReportSearchParams(dateFrom, dateTo, empIds, projIds)`):
`exportReportEmployeeProject`, `exportReportProjectEmployee`, `exportReportDailyWorkload`, `exportReportRevenueLeakage`, `exportReportTimeEntryDiscipline`, `exportReportFocusAnalysis` → `/api/report-{employee-project,project-employee,daily-workload,revenue-leakage,time-entry-discipline,focus-analysis}-export`.
- [ ] **Step 2:** Зарегистрировать все 6 в `return {...}` стора.
- [ ] **Step 3: Проверка** `cd frontend && npx nuxt prepare 2>&1 | grep -iE "error|cannot"` — пусто.
- [ ] **Step 4: Commit** `git commit -am "feat(excel): frontend export api methods"`

---

## Task 8: Фронт — переключить handleExport 6 страниц на сервер

**Files:** Modify 6 страниц `pages/reports/*.client.vue`

- [ ] **Step 1:** В каждой странице заменить тело `handleExport`/`handleExportExcel` на серверное скачивание blob по образцу project-task:

```ts
async function handleExportExcel() {
  try {
    const blob = await apiStore.exportReport<X>(dateFrom.value, dateTo.value, employeeFilter.value, projectFilter.value)
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url
    a.download = `<filename>_${dateFrom.value}_${dateTo.value}.xlsx`
    document.body.appendChild(a); a.click(); document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
  } catch (e) { processErrorGlobal(e) }
}
```
(подставить правильный метод и параметры под каждый отчёт; daily использует только dateFrom/dateTo, если у него нет фильтров emp/proj — взять как в текущем daily.)

- [ ] **Step 2:** Убрать импорты старых фронтовых функций экспорта из этих страниц.
- [ ] **Step 3: Проверка** `npx nuxt prepare` — пусто.
- [ ] **Step 4: Commit** `git commit -am "feat(excel): wire 6 report pages to server export"`

---

## Task 9: Фронт — удалить мёртвый фронтовый xlsx-код

**Files:** Modify `frontend/app/utils/reportExport.ts`, `frontend/app/utils/exportXlsx.ts`

- [ ] **Step 1:** Проверить, что функции больше не используются: `cd frontend && grep -rn "exportHierarchyReportToXlsx\|exportDailyWorkloadToXlsx\|flattenHierarchyReport\|flattenDailyWorkloadReport\|exportRowsToXlsx" app --include=*.vue --include=*.ts | grep -v node_modules`. Должны остаться только определения (не вызовы).
- [ ] **Step 2:** Удалить неиспользуемые функции из `reportExport.ts` и неиспользуемые импорты типов. Если `exportXlsx.ts::exportRowsToXlsx` больше нигде не вызывается — удалить файл; иначе оставить.
- [ ] **Step 3: Проверка** `npx nuxt prepare` + `npm run lint app/utils` (если эти файлы линтятся) — без новых ошибок.
- [ ] **Step 4: Commit** `git commit -am "chore(excel): remove dead frontend xlsx export"`

---

## Task 10: Техдолг — ESLint

**Files:** Modify `frontend/app/utils/iframe-resizer.ts`, `openCrmItem.ts`, `openProjectGroup.ts` (и др. из вывода lint)

- [ ] **Step 1:** Запустить `cd frontend && npm run lint` — получить полный список 24 ошибок.
- [ ] **Step 2:** Починить: `@ts-ignore` → `@ts-expect-error` (iframe-resizer.ts), `any` → конкретный тип (openCrmItem.ts:8, openProjectGroup.ts:8) и остальные. Поведение не менять.
- [ ] **Step 3: Проверка** `npm run lint` — 0 ошибок; `npx nuxt prepare` зелёный.
- [ ] **Step 4: Commit** `git commit -am "chore: fix preexisting eslint errors in utils"`

---

## Task 11: Техдолг — изоляция finance на фронте

**Files:** Modify `frontend/app/pages/handler/placement-crm-deal-detail-tab.client.vue`, `frontend/app/stores/api.ts`

- [ ] **Step 1:** Прочитать `placement-crm-deal-detail-tab.client.vue` — определить, finance-only ли это таб. Если да — отключить регистрацию/показать заглушку «функционал в планах»; если смешанный — изолировать только finance-секцию.
- [ ] **Step 2:** В `api.ts` закомментировать/пометить мёртвые методы (`getFinanceOperations`, `createFinanceOperation`, вызовы `/api/finance-spa/validation`, `/api/project-budget/notify`) и убрать их из `return`, если нигде кроме finance-виджета не используются (проверить grep).
- [ ] **Step 3: Проверка** `npx nuxt prepare`; `grep -rn "finance-operations\|finance-spa\|project-budget/notify" app --include=*.ts --include=*.vue | grep -v node_modules` — активных вызовов нет.
- [ ] **Step 4: Commit** `git commit -am "chore(finance): isolate planned finance functionality on frontend"`

---

## Task 12: Верификация и документация

**Files:** Modify `docs/CHANGELOG.md`, `docs/RELEASES.md`, `docs/BACKLOG.md`, `docs/architecture/feature-map.md`

- [ ] **Step 1:** Полный прогон: `cd backends/python/api && DJANGO_SETTINGS_MODULE=test_settings .venv/bin/python -m unittest main.tests_report_excel main.tests_inn_backfill -v && DJANGO_SETTINGS_MODULE=test_settings .venv/bin/python manage.py check`; `cd frontend && npx nuxt prepare && npm run lint`. Всё зелёное.
- [ ] **Step 2:** Записи в доках: CHANGELOG (Спринт 4), RELEASES (пользовательский), BACKLOG (вычеркнуть ESLint + finance-изоляцию), feature-map (3 генератора + export-endpoints).
- [ ] **Step 3:** e2e (вручную пользователем): по одному скачать Excel в каждом из 6 отчётов — структура верна; finance-виджет не шлёт битых запросов.
- [ ] **Step 4: Commit** `git commit -am "docs: sprint 4 changelog/releases/feature-map"`

---

## Self-Review (выполнено)
- **Покрытие спека:** 3 генератора → Task 1-3; иерархия-endpoints → Task 4; матрица → Task 5; таблицы → Task 6; фронт api → Task 7; переключение страниц → Task 8; удаление мёртвого кода → Task 9; ESLint → Task 10; finance-изоляция → Task 11; verify/docs → Task 12. ✔
- **Плейсхолдеры:** генераторы — полный код+тесты. Endpoints/фронт — образец project-task + явное указание «свериться с реальным JSON-view/типами» для имён полей (оправдано: точные ключи строк сводных отчётов берутся из существующего кода, не выдумываются).
- **Согласованность:** имена генераторов (`build_hierarchy_workbook`/`build_matrix_workbook`/`build_table_workbook`) и `_TABLE_FMT` едины во всех задачах; импорт в `views.py` расширяется в Task 4 и используется в 5-6.
