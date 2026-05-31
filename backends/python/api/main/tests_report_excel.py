import os
import unittest

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
django.setup()

from main.report_excel import (  # noqa: E402
    build_hierarchy_workbook,
    build_matrix_workbook,
    build_table_workbook,
)


class HierarchyWB(unittest.TestCase):
    def test_valid_xlsx_with_totals(self):
        roots = [{"name": "Проект", "total_hours": 10, "billable_hours": 8, "non_billable_hours": 2,
                  "children": [{"name": "Сотрудник", "total_hours": 10, "billable_hours": 8,
                                "non_billable_hours": 2, "children": []}]}]
        out = build_hierarchy_workbook(roots, title="Отчёт по проектам", date_from="2026-05-01", date_to="2026-05-31")
        data = out.read()
        self.assertEqual(data[:2], b"PK")
        self.assertGreater(len(data), 0)


class MatrixWB(unittest.TestCase):
    def test_valid(self):
        header_days = [{"date": "2026-05-01"}, {"date": "2026-05-02"}]
        rows = [{"employee": {"name": "Иванов"}, "days": {"2026-05-01": {"total": 8}, "2026-05-02": {"total": 7}}}]
        out = build_matrix_workbook(header_days, rows, title="Ежедневная нагрузка", date_from="2026-05-01", date_to="2026-05-02")
        self.assertEqual(out.read()[:2], b"PK")


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


if __name__ == "__main__":
    unittest.main()
