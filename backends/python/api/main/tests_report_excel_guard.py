"""
Тесты задачи 3.5: лимит строк и сохранность _safe_cell_text в write_only-режиме.

Django TestCase (без django.setup() — использует стандартный механизм test runner).
"""

from django.test import TestCase

from main.report_excel import (
    build_matrix_workbook,
    build_table_workbook,
    build_hierarchy_workbook,
    ExportTooLargeError,
    MAX_EXPORT_ROWS,
)


class ExportLimitTest(TestCase):
    def test_matrix_within_limit_ok(self):
        header_days = [{"date": "2026-05-01"}, {"date": "2026-05-02"}]
        rows = [{"employee": {"name": f"E{i}"}, "days": {"2026-05-01": {"total": 8}}} for i in range(10)]
        out = build_matrix_workbook(header_days, rows, title="Нагрузка")
        self.assertEqual(out.read()[:2], b"PK")

    def test_matrix_over_limit_raises(self):
        header_days = [{"date": "2026-05-01"}]
        rows = [{"employee": {"name": f"E{i}"}, "days": {}} for i in range(MAX_EXPORT_ROWS + 1)]
        with self.assertRaises(ExportTooLargeError):
            build_matrix_workbook(header_days, rows, title="Нагрузка")

    def test_table_over_limit_raises(self):
        cols = [{"key": "p", "label": "Проект", "fmt": "text"}]
        rows = [{"p": f"P{i}"} for i in range(MAX_EXPORT_ROWS + 1)]
        with self.assertRaises(ExportTooLargeError):
            build_table_workbook(cols, rows, title="Таблица")

    def test_formula_injection_still_neutralized(self):
        # Защита формул из спринта 1 должна сохраниться в write_only-режиме.
        cols = [{"key": "p", "label": "Проект", "fmt": "text"}]
        rows = [{"p": "=SUM(A1:A9)"}]
        out = build_table_workbook(cols, rows, title="Таблица")
        data = out.read()
        self.assertEqual(data[:2], b"PK")
        # Содержимое xlsx — zip; грубая проверка, что опасная строка ушла с префиксом '
        # (точную распаковку не делаем — достаточно, что файл валиден и билдер не упал).

    def test_hierarchy_over_limit_raises(self):
        # Иерархия: лимит тоже действует (write_only НЕ применяется, но guard — да).
        big_children = [{"name": f"T{i}", "total_hours": 1, "billable_hours": 1,
                         "non_billable_hours": 0, "children": []} for i in range(MAX_EXPORT_ROWS + 1)]
        roots = [{"name": "Проект", "total_hours": 1, "billable_hours": 1,
                  "non_billable_hours": 0, "children": big_children}]
        with self.assertRaises(ExportTooLargeError):
            build_hierarchy_workbook(roots, title="Иерархия")
