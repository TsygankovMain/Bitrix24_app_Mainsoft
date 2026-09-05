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


class SyncMissingTasksTest(TestCase):
    """Кнопка «Обновить» дотягивает задачи, которых нет в справочнике.

    Боевая проверка 31.08.2026: пользователь списал час на задачу 8365,
    перенёс её в другой проект и нажал «Обновить» — ничего не изменилось.
    Причина: синк обновлял только списания, а справочник ждал своего цикла, и
    задача, доехавшая на минуту позже прогона, оставалась неизвестной. Отчёт
    при этом честно откатывался на снимок, показывая прежний проект.
    """

    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-missing",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )

    def _service(self, referenced, fetched):
        service = TaskSyncService(client=None, account=self.account)
        service.collect_referenced_task_ids = lambda: referenced
        service._fetch_tasks = lambda ids: [t for t in fetched if str(t.get("id")) in set(ids)]
        return service

    def test_missing_task_is_pulled(self):
        service = self._service(
            referenced=["8365"],
            fetched=[{"id": "8365", "title": "подготовить рассылку", "groupId": "73"}],
        )

        result = service.sync_missing_task_ids()

        self.assertEqual(result["created"], 1)
        self.assertEqual(PortalTask.objects.get(bitrix_id="8365").group_id, "73")

    def test_nothing_missing_costs_no_bitrix_calls(self):
        """Обычный случай: всё на месте — кнопка не платит ни одного вызова."""
        PortalTask.objects.create(
            bitrix24_account=self.account, bitrix_id="8365",
            title="подготовить рассылку", group_id="73",
        )
        service = TaskSyncService(client=None, account=self.account)
        service.collect_referenced_task_ids = lambda: ["8365"]

        def _must_not_be_called(ids):
            raise AssertionError("Битрикс не должен вызываться, когда дотягивать нечего")

        service._fetch_tasks = _must_not_be_called

        self.assertEqual(service.sync_missing_task_ids()["synced"], 0)

    def test_limit_caps_one_run(self):
        """После долгого простоя кнопка не превращается в полный обход."""
        referenced = [str(i) for i in range(1, 51)]
        fetched = [{"id": str(i), "title": f"Задача {i}", "groupId": "1"} for i in referenced]
        service = self._service(referenced=referenced, fetched=fetched)

        service.sync_missing_task_ids(limit=10)

        self.assertEqual(PortalTask.objects.count(), 10)


class SyncChangedSinceTest(TestCase):
    """Перенос УЖЕ известной задачи виден сразу, а не через фоновый цикл.

    Боевая проверка 31.08.2026: пользователь перенёс задачу 8365 в другой
    проект в 14:51:52, нажал «Обновить» — и ничего не изменилось. Причина:
    sync_missing_task_ids по своей природе тянет только ОТСУТСТВУЮЩИЕ задачи,
    а 8365 в справочнике была. Перенос известной задачи ждал десятиминутного
    цикла, и кнопка не показывала реального положения.

    Полный обход ради кнопки не годится (1 592 задачи ≈ 17 секунд), поэтому
    спрашиваем у Битрикса только изменившиеся — фильтр >CHANGED_DATE.
    """

    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-changed",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        PortalTask.objects.create(
            bitrix24_account=self.account, bitrix_id="8365",
            title="подготовить рассылку", group_id="459",
        )

    def _service(self, changed):
        service = TaskSyncService(client=None, account=self.account)
        service.calls = []

        def _fetch(since):
            service.calls.append(since)
            return changed

        service._fetch_changed_tasks = _fetch
        return service

    def test_move_of_known_task_is_applied(self):
        service = self._service(
            [{"id": "8365", "title": "подготовить рассылку", "groupId": "73"}]
        )

        result = service.sync_changed_since()

        self.assertEqual(result["updated"], 1)
        self.assertEqual(PortalTask.objects.get(bitrix_id="8365").group_id, "73")

    def test_marker_uses_overlap(self):
        """Правка, случившаяся в ту же секунду, что и наша запись, не теряется."""
        from datetime import timedelta

        service = self._service([])
        service.sync_changed_since(overlap=timedelta(minutes=5))

        marker = PortalTask.objects.get(bitrix_id="8365").updated_at
        self.assertEqual(service.calls[0], marker - timedelta(minutes=5))

    def test_empty_directory_is_left_to_background(self):
        """Наполнять пустой справочник целиком должен фоновый прогон, не кнопка."""
        PortalTask.objects.all().delete()
        service = self._service([{"id": "1", "title": "x", "groupId": "1"}])

        self.assertEqual(service.sync_changed_since()["synced"], 0)
        self.assertEqual(service.calls, [], "Битрикс не должен вызываться")

    def test_no_changes_costs_nothing(self):
        service = self._service([])

        self.assertEqual(service.sync_changed_since()["synced"], 0)
