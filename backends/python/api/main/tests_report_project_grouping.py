"""Проект в отчёте — один узел на проект, а не на каждое написание имени.

Жалоба (31.08.2026): «если пользователь поменяет название задачи и поменяет у
неё проект, у нас не происходит замена в приложении, и метки времени
дубляются».

Разбор показал две разные причины, и здесь закреплены обе.

1. Дерево отчёта ключевало узел проекта ПО ИМЕНИ:
   emp_node["children"][proj_name]. Любое расхождение текста давало вторую
   строку того же проекта. А расхождения берутся из того, что project_title в
   записи — снимок на момент списания: он не обновляется при переименовании и
   спокойно расходится с текущим именем карточки (на проде 415 таких строк).

2. normalize_items при пустом поле проекта подставлял в project_title
   title_hierarchy[0] — то есть НАЗВАНИЕ ЗАДАЧИ. Так в отчётах появлялись
   «проекты», которых в Битриксе нет. На проде: задача 8033, project_id=415,
   записи и с «Сопровождение ПВД», и с «Разработка модуля/расширения для
   1С:Бухгалтерии» (её собственное имя).

Что НЕ чинится здесь и почему. Если задачу реально перенесли в другой проект,
её старые записи остаются в старом проекте — это не дефект, а решение:
коммерческие факты фиксируются на момент списания, ровно как уже сделано с
hourly_rate_snapshot. Такие записи и должны показываться двумя строками.
"""

from django.test import SimpleTestCase

from .report_queries import build_tree_report_items, resolve_project_key_for_row
from .report_services import DataProcessingService, ReportService


def _row(**overrides):
    row = {
        "employee_id": "1",
        "project_item_id": "",
        "project_id": "415",
        "project_title": "Сопровождение ПВД",
        "hours": 1.0,
        "task_hierarchy_ids": ["8033"],
        "task_hierarchy_titles": ["Разработка модуля"],
        "is_billable": True,
        "description": "",
        "date_reflection": None,
        "bitrix_id": 1,
        "task_id": "8033",
    }
    row.update(overrides)
    return row


class ProjectKeyTest(SimpleTestCase):
    def test_item_id_wins_over_group_and_name(self):
        key = resolve_project_key_for_row(_row(project_item_id="241"))
        self.assertEqual(key, "item:241")

    def test_group_id_used_when_no_item_id(self):
        self.assertEqual(resolve_project_key_for_row(_row()), "group:415")

    def test_same_group_different_titles_share_key(self):
        """Ядро дефекта: разные снимки имени — один и тот же проект."""
        left = resolve_project_key_for_row(_row(project_title="Сопровождение ПВД"))
        right = resolve_project_key_for_row(
            _row(project_title="Разработка модуля/расширения для 1С:Бухгалтерии")
        )
        self.assertEqual(left, right)

    def test_name_is_last_resort(self):
        key = resolve_project_key_for_row(_row(project_id="", project_title="Без опоры"))
        self.assertEqual(key, "name:Без опоры")

    def test_different_groups_stay_separate(self):
        """Реальный перенос задачи между проектами схлопывать нельзя."""
        self.assertNotEqual(
            resolve_project_key_for_row(_row(project_id="25")),
            resolve_project_key_for_row(_row(project_id="425")),
        )


class ProjectNodeMergingTest(SimpleTestCase):
    """Сквозная проверка: от строк БД до дерева отчёта."""

    def _tree(self, rows):
        items = build_tree_report_items(rows, project_name_by_group={"415": "ПВД сопровождение"})
        return ReportService().generate_employee_projects(items, {})

    def test_same_project_two_title_snapshots_give_one_node(self):
        report = self._tree([
            _row(bitrix_id=1, project_title="Сопровождение ПВД", hours=10.5),
            _row(bitrix_id=2, project_title="Разработка модуля/расширения", hours=22.0),
        ])

        employee = report[0]
        self.assertEqual(len(employee["children"]), 1, "проект должен быть один")
        project = employee["children"][0]
        self.assertEqual(project["total_hours"], 32.5)
        # Имя берём актуальное — из карточки проекта, а не из снимка записи.
        self.assertEqual(project["name"], "ПВД сопровождение")

    def test_genuine_move_between_projects_stays_two_nodes(self):
        report = self._tree([
            _row(bitrix_id=1, project_id="25", project_title="ИТ-ЛАБ", hours=3.0),
            _row(bitrix_id=2, project_id="425", project_title="ООО «ВСС»", hours=43.0),
        ])

        employee = report[0]
        self.assertEqual(len(employee["children"]), 2)
        self.assertEqual({p["total_hours"] for p in employee["children"]}, {3.0, 43.0})

    def test_renamed_task_merges_into_one_task_node(self):
        """Переименование задачи не должно плодить узлы задач."""
        report = self._tree([
            _row(bitrix_id=1, task_hierarchy_titles=["Тестирование системы Клеверенс."], hours=237.0),
            _row(bitrix_id=2, task_hierarchy_titles=["ЗАДАЧИ ПО ООО ЭЛР"], hours=23.0),
        ])

        project = report[0]["children"][0]
        self.assertEqual(len(project["children"]), 1, "задача должна быть одна")
        self.assertEqual(project["children"][0]["total_hours"], 260.0)


class ProjectNameFallbackTest(SimpleTestCase):
    """Пустое поле проекта больше не подменяется названием задачи."""

    def _normalize(self, raw):
        service = DataProcessingService({
            "id_zadachi": "UF_TASK_ID",
            "project_title": "UF_PROJECT",
            "title_zadach_ierarhiya": "UF_TITLES",
            "kolichestvo_chasov": "UF_HOURS",
            "data": "UF_DATE",
        })
        return service.normalize_items(raw)

    def test_empty_project_is_not_replaced_by_task_title(self):
        normalized = self._normalize([{
            "id": "1",
            "UF_TASK_ID": "8033",
            "UF_PROJECT": "",
            "UF_TITLES": '["Разработка модуля/расширения для 1С:Бухгалтерии"]',
            "UF_HOURS": "2",
            "UF_DATE": "2026-08-01",
        }])

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["project_name"], "Не определён")
        # Название задачи при этом на месте — потеряли только подмену.
        self.assertEqual(
            normalized[0]["title_zadach_ierarhiya"],
            ["Разработка модуля/расширения для 1С:Бухгалтерии"],
        )

    def test_umbrella_task_still_becomes_project_name(self):
        """Исходный замысел сохранён: если НАД задачей есть зонтичная задача,
        её название по-прежнему играет роль проекта. Сломан был только
        вырожденный случай — задача без родителя, где корень это она сама."""
        normalized = self._normalize([{
            "id": "1",
            "UF_TASK_ID": "10",
            "UF_PROJECT": "",
            "UF_TITLES": '["Зонтичная задача", "Подзадача"]',
            "UF_HOURS": "2",
            "UF_DATE": "2026-08-01",
        }])

        self.assertEqual(normalized[0]["project_name"], "Зонтичная задача")

    def test_real_project_name_is_kept(self):
        normalized = self._normalize([{
            "id": "1",
            "UF_TASK_ID": "8033",
            "UF_PROJECT": "Сопровождение ПВД",
            "UF_TITLES": '["Разработка модуля"]',
            "UF_HOURS": "2",
            "UF_DATE": "2026-08-01",
        }])

        self.assertEqual(normalized[0]["project_name"], "Сопровождение ПВД")
