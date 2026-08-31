"""Отчёт следует за задачей: актуальные название и проект, а не снимок.

Требование пользователя (31.08.2026): «приоритет должен быть на актуальные
показатели, соответствие должно быть от них… до закрытия должна быть полная
возможность менять проекты и отчёт должен быть актуальным».

Заморозки закрытых периодов здесь намеренно НЕТ: закрытие сделано правами
Битрикса и распространяется и на задачи, и на проекты, поэтому перенести
что-либо в закрытом периоде нельзя в принципе — защищать нечего.

Снимок в timesheet_item при этом не переписывается: резолв идёт на чтении.
Поэтому история становится актуальной сразу, без миграции, а след «под чем
списывалось» сохраняется.
"""

from django.test import SimpleTestCase, TestCase

from .models import Bitrix24Account, PortalTask
from .report_queries import (
    build_task_lookup,
    build_tree_report_items,
    resolve_current_group_for_row,
    resolve_task_titles_for_row,
)
from .report_services import ReportService
from .task_sync_service import TaskSyncService


def _row(**overrides):
    row = {
        "employee_id": "1",
        "project_item_id": "",
        "project_id": "25",
        "project_title": "ИТ-ЛАБ",
        "hours": 3.0,
        "task_hierarchy_ids": ["6823"],
        "task_hierarchy_titles": ["Оценить доработки в 1С ЗУП 3.1"],
        "is_billable": True,
        "description": "",
        "date_reflection": None,
        "bitrix_id": 1,
        "task_id": "6823",
    }
    row.update(overrides)
    return row


# Задача 6823 переехала из группы 25 (ИТ-ЛАБ) в 425 (ВСС) — реальный случай с прода.
LOOKUP = {"6823": {"title": "Оценить доработки в 1С ЗУП 3.1 (актуальное)", "group_id": "425"}}


class ResolveFromDirectoryTest(SimpleTestCase):
    def test_current_group_replaces_snapshot(self):
        self.assertEqual(resolve_current_group_for_row(_row(), LOOKUP), "425")

    def test_missing_task_falls_back_to_snapshot(self):
        """Задача ещё не попала в справочник — деградация мягкая."""
        self.assertEqual(resolve_current_group_for_row(_row(), {}), "")

    def test_titles_resolved_elementwise(self):
        titles = resolve_task_titles_for_row(
            _row(task_hierarchy_ids=["100", "6823"],
                 task_hierarchy_titles=["Зонтичная", "Старое имя"]),
            LOOKUP,
        )
        # 100 в справочнике нет -> снимок; 6823 есть -> актуальное.
        self.assertEqual(titles, ["Зонтичная", "Оценить доработки в 1С ЗУП 3.1 (актуальное)"])

    def test_hierarchy_length_preserved(self):
        """По цепочке строится дерево — длину и порядок ломать нельзя."""
        row = _row(task_hierarchy_ids=["1", "2", "6823"],
                   task_hierarchy_titles=["A", "B", "C"])
        self.assertEqual(len(resolve_task_titles_for_row(row, LOOKUP)), 3)

    def test_empty_title_in_directory_keeps_snapshot(self):
        titles = resolve_task_titles_for_row(_row(), {"6823": {"title": "", "group_id": "425"}})
        self.assertEqual(titles, ["Оценить доработки в 1С ЗУП 3.1"])


class ReportFollowsTaskTest(SimpleTestCase):
    """Сквозная проверка: перенос задачи меняет отчёт."""

    def _report(self, rows, lookup):
        items = build_tree_report_items(
            rows,
            project_name_by_group={"25": "ИТ-ЛАБ", "425": "ВСС"},
            task_lookup=lookup,
        )
        return ReportService().generate_employee_projects(items, {})

    def test_moved_task_collapses_into_current_project(self):
        """Главное требование: старые и новые часы сходятся в текущем проекте."""
        rows = [
            _row(bitrix_id=1, project_id="25", project_title="ИТ-ЛАБ", hours=3.0),
            _row(bitrix_id=2, project_id="425", project_title="ООО «ВСС»", hours=43.0),
        ]

        report = self._report(rows, LOOKUP)

        projects = report[0]["children"]
        self.assertEqual(len(projects), 1, "часы перенесённой задачи должны быть в одном проекте")
        self.assertEqual(projects[0]["name"], "ВСС")
        self.assertEqual(projects[0]["total_hours"], 46.0)

    def test_without_directory_behaviour_is_unchanged(self):
        """Справочник ещё не наполнен — работаем по снимку, как раньше."""
        rows = [
            _row(bitrix_id=1, project_id="25", project_title="ИТ-ЛАБ", hours=3.0),
            _row(bitrix_id=2, project_id="425", project_title="ООО «ВСС»", hours=43.0),
        ]

        report = self._report(rows, {})

        self.assertEqual(len(report[0]["children"]), 2)

    def test_renamed_task_shows_current_title(self):
        report = self._report([_row(hours=5.0)], LOOKUP)

        task = report[0]["children"][0]["children"][0]
        self.assertEqual(task["name"], "Оценить доработки в 1С ЗУП 3.1 (актуальное)")


class TaskSyncServiceTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-tasks",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )

    def _service(self, responses):
        service = TaskSyncService(client=None, account=self.account)
        service._fetch_tasks = lambda ids: responses
        return service

    def test_upsert_creates_then_updates(self):
        service = self._service([{"id": "6823", "title": "Старое имя", "groupId": "25"}])
        created = service._save_batch([{"id": "6823", "title": "Старое имя", "groupId": "25"}])
        self.assertEqual(created["created"], 1)

        updated = service._save_batch([{"id": "6823", "title": "Новое имя", "groupId": "425"}])
        self.assertEqual(updated["updated"], 1)

        row = PortalTask.objects.get(bitrix_id="6823")
        self.assertEqual(row.title, "Новое имя")
        self.assertEqual(row.group_id, "425")

    def test_snake_case_keys_are_accepted(self):
        """Битрикс исторически неоднороден в написании ключей."""
        service = self._service([])
        service._save_batch([{"ID": "10", "TITLE": "Задача", "GROUP_ID": "7"}])

        row = PortalTask.objects.get(bitrix_id="10")
        self.assertEqual(row.title, "Задача")
        self.assertEqual(row.group_id, "7")

    def test_response_shapes_are_tolerated(self):
        extract = TaskSyncService._extract_tasks
        self.assertEqual(extract({"result": {"tasks": [{"id": "1"}]}}), [{"id": "1"}])
        self.assertEqual(extract({"result": [{"id": "2"}]}), [{"id": "2"}])
        self.assertEqual(extract({"result": {}}), [])
        self.assertEqual(extract(None), [])

    def test_long_title_is_truncated_to_column(self):
        service = self._service([])
        service._save_batch([{"id": "11", "title": "д" * 900, "groupId": "1"}])

        self.assertEqual(len(PortalTask.objects.get(bitrix_id="11").title), 500)

    def test_lookup_round_trip(self):
        service = self._service([])
        service._save_batch([{"id": "6823", "title": "Актуальное", "groupId": "425"}])

        lookup = build_task_lookup(self.account)
        self.assertEqual(lookup["6823"], {"title": "Актуальное", "group_id": "425"})
