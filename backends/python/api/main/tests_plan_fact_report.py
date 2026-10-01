"""Отчёт «План / факт».

Два предмета проверки.

1. Доступ. Отчёт включён только для порталов из белого списка
   (PLAN_FACT_PORTALS по member_id): чужой портал получает 404 на обе ручки и
   не видит ключа в /api/features. Это требование владельца, а не удобство.
2. Арифметика. Оценка стоит и на этапе, и на подзадачах — план не должен
   удваиваться; остаток считается только по задачам с планом.
"""

import io
from datetime import datetime
from unittest.mock import patch

import openpyxl
from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from .models import Bitrix24Account, TimesheetItem
from .plan_fact_report import (
    DEFAULT_PLAN_FACT_PORTALS,
    build_plan_fact_report,
    build_plan_fact_workbook,
    fetch_plan_tasks,
    plan_fact_settings,
)

FIELD = "UF_TASKS_TASK_1"
ALLOWED = {"m-allowed": {"estimate_field": FIELD}}


def task(task_id, title, plan=0.0, parent="", group="209", responsible="1201", closed=False, in_plan_tree=None):
    return {
        "id": task_id, "title": title, "parent_id": parent, "group_id": group, "group_name": "НАВИГАТОР АО",
        "plan": plan, "responsible_id": responsible, "responsible_name": "", "closed": closed,
        "in_plan_tree": plan > 0 if in_plan_tree is None else in_plan_tree,
    }


def row(task_id, hours, *, chain=None, titles=None, employee="1199", billable=True, project="209"):
    return {
        "employee_id": employee, "project_item_id": "", "project_id": project,
        "project_title": "НАВИГАТОР АО", "hours": hours,
        "task_hierarchy_ids": chain or [task_id], "task_hierarchy_titles": titles or [f"Задача {task_id}"],
        "is_billable": billable, "description": "", "date_reflection": None, "bitrix_id": 1, "task_id": task_id,
    }


class PlanFactBuilderTest(SimpleTestCase):
    def setUp(self):
        self.plan = {
            "6063": task("6063", "6. Моделирование", plan=960.0),
            "6287": task("6287", "6.1. Баязитова", plan=200.0, parent="6063", responsible="1199"),
            "6289": task("6289", "6.2. Графова", plan=160.0, parent="6063", responsible="1747"),
        }
        self.rows = [
            row("6287", 120.0, chain=["6063", "6287"], titles=["6. Моделирование", "6.1. Баязитова"]),
            row("6287", 30.0, chain=["6063", "6287"], titles=["6. Моделирование", "6.1. Баязитова"], billable=False),
            row("6063", 6.0, employee="1217", billable=False, titles=["6. Моделирование"]),
            row("9000", 50.0, titles=["Задача без оценки"]),
        ]

    def build(self, **kwargs):
        return build_plan_fact_report(
            self.rows, self.plan,
            user_map={"1199": "Баязитова Алсу", "1217": "Ухина Дарья", "1201": "Гареева Светлана"},
            **kwargs,
        )

    def test_stage_plan_is_not_doubled_by_subtasks(self):
        project = self.build()["projects"][0]
        self.assertEqual(project["name"], "НАВИГАТОР АО")
        # 960 этапа, а не 960 + 200 + 160.
        self.assertEqual(project["plan_hours"], 960.0)
        stage = next(n for n in project["children"] if n["id"] == "6063")
        self.assertEqual(stage["own_plan_hours"], 960.0)
        self.assertEqual(stage["children_plan_hours"], 360.0)

    def test_fact_split_and_rollup(self):
        project = self.build()["projects"][0]
        self.assertEqual(project["total_hours"], 206.0)
        self.assertEqual(project["billable_hours"], 170.0)
        self.assertEqual(project["non_billable_hours"], 36.0)
        stage = next(n for n in project["children"] if n["id"] == "6063")
        self.assertEqual(stage["total_hours"], 156.0)
        self.assertEqual([e["name"] for e in stage["employees"]], ["Ухина Дарья"])
        sub = next(n for n in stage["children"] if n["id"] == "6287")
        self.assertEqual((sub["total_hours"], sub["billable_hours"], sub["non_billable_hours"]), (150.0, 120.0, 30.0))

    def test_remainder_counts_only_planned_tasks(self):
        project = self.build()["projects"][0]
        # 50 ч задачи без оценки в остаток не попадают.
        self.assertEqual(project["planned_fact_hours"], 156.0)

    def test_planned_task_without_fact_is_shown(self):
        stage = next(n for n in self.build()["projects"][0]["children"] if n["id"] == "6063")
        empty = next(n for n in stage["children"] if n["id"] == "6289")
        self.assertEqual((empty["plan_hours"], empty["total_hours"]), (160.0, 0.0))

    def test_stage_without_own_plan_sums_subtasks(self):
        self.plan["6063"]["plan"] = 0.0
        project = self.build()["projects"][0]
        self.assertEqual(project["plan_hours"], 360.0)
        # Факт этапа вне плановых подзадач (6 ч) в остаток не входит.
        self.assertEqual(project["planned_fact_hours"], 150.0)

    def test_employee_view_uses_leaf_plan_of_responsible(self):
        employees = {e["id"]: e for e in self.build()["employees"]}
        bayazitova = employees["1199"]
        self.assertEqual(bayazitova["total_hours"], 200.0)
        self.assertEqual(bayazitova["plan_hours"], 200.0)       # только 6.1, без задачи 9000
        self.assertEqual(bayazitova["planned_fact_hours"], 150.0)
        # Этап 6063 — не лист плана: его 960 ч Гареевой не приписываются.
        self.assertNotIn("1201", employees)
        # Графова: план есть, факта нет — строка всё равно присутствует.
        self.assertEqual(employees["1747"]["plan_hours"], 160.0)

    def test_employee_filter_limits_plan_to_responsible(self):
        self.rows = [r for r in self.rows if r["employee_id"] == "1199"]
        project = self.build(employee_ids=["1199"])["projects"][0]
        self.assertEqual(project["plan_hours"], 200.0)

    def test_project_filter_and_archive_cut_plan_tasks(self):
        self.plan["7000"] = task("7000", "Чужой проект", plan=40.0, group="145")
        names = [p["id"] for p in self.build()["projects"]]
        self.assertIn("145", names)
        self.assertNotIn("145", [p["id"] for p in self.build(project_group_ids=["209"])["projects"]])
        self.assertNotIn("145", [p["id"] for p in self.build(archived_group_ids=["145"])["projects"]])
        only_other = self.build(project_group_ids=["209"], project_mode="exclude")["projects"]
        self.assertEqual([p["id"] for p in only_other if p["plan_hours"]], ["145"])

    def test_parent_from_other_project_does_not_nest(self):
        self.plan["6287"]["group_id"] = "145"
        projects = {p["id"]: p for p in self.build()["projects"]}
        self.assertEqual([n["id"] for n in projects["145"]["children"]], ["6287"])

    def test_current_hierarchy_beats_snapshot_inside_plan_tree(self):
        # 9000 по снимку — в корне, но на портале сейчас лежит под этапом:
        # её часы обязаны попасть в факт по плану.
        self.plan["9000"] = task("9000", "Задача без оценки", parent="6063", in_plan_tree=True)
        project = self.build()["projects"][0]
        self.assertEqual([n["id"] for n in project["children"]], ["6063"])
        self.assertEqual(project["planned_fact_hours"], 206.0)

    def test_task_moved_out_of_plan_tree_is_detached(self):
        # По снимку 8000 — подзадача этапа, но портал среди потомков её не
        # отдал: перенесли. В факт по плану её часы не идут.
        self.rows.append(row("8000", 10.0, chain=["6063", "8000"], titles=["6. Моделирование", "Ушедшая"]))
        project = self.build()["projects"][0]
        self.assertIn("8000", [n["id"] for n in project["children"]])
        self.assertEqual(project["planned_fact_hours"], 156.0)

    def test_workbook_has_both_sheets_and_totals(self):
        book = openpyxl.load_workbook(io.BytesIO(build_plan_fact_workbook(self.build()).read()))
        self.assertEqual(book.sheetnames, ["Проекты-задачи-сотрудники", "Сотрудники"])
        total = [c.value for c in book.worksheets[0][3]]
        self.assertEqual(total[0], "ИТОГО")
        self.assertEqual((total[3], total[4], total[7]), (960.0, 206.0, 804.0))


class FakeToken:
    def __init__(self, tasks):
        self.tasks = tasks
        self.calls = []

    def call_method(self, method, params=None):
        params = params or {}
        self.calls.append((method, params))
        if method != "tasks.task.list":
            return {"result": []}
        ids = params["filter"].get("ID")
        if ids is not None:
            return {"result": {"tasks": [t for t in self.tasks if t["id"] in ids]}}
        parents = params["filter"].get("PARENT_ID")
        if parents is not None:
            return {"result": {"tasks": [t for t in self.tasks if t["parentId"] in parents]}}
        return {"result": {"tasks": [t for t in self.tasks if float(t.get("ufTasksTask1") or 0) > 0]}}


class FakeClient:
    def __init__(self, tasks):
        self._bitrix_token = FakeToken(tasks)


PORTAL_TASKS = [
    {"id": "10", "title": "Этап", "parentId": "0", "groupId": "209", "responsibleId": "1201", "status": "3",
     "ufTasksTask1": None, "group": {"id": "209", "name": "НАВИГАТОР АО"}},
    {"id": "11", "title": "Подзадача", "parentId": "10", "groupId": "209", "responsibleId": "1199", "status": "5",
     "ufTasksTask1": "200", "group": {"id": "209", "name": "НАВИГАТОР АО"},
     "responsible": {"id": "1199", "name": "Алсу Баязитова"}},
    {"id": "12", "title": "Подзадача без оценки", "parentId": "11", "groupId": "209", "responsibleId": "1199",
     "status": "3", "ufTasksTask1": None, "group": {"id": "209", "name": "НАВИГАТОР АО"}},
]


class FetchPlanTasksTest(SimpleTestCase):
    def test_reads_estimate_and_pulls_parents(self):
        client = FakeClient(PORTAL_TASKS)
        tasks = fetch_plan_tasks(client, FIELD)
        self.assertEqual(sorted(tasks), ["10", "11", "12"])
        # Плановая задача и её потомки — «полное» поддерево; родитель выше — нет.
        self.assertEqual({k: v["in_plan_tree"] for k, v in tasks.items()}, {"10": False, "11": True, "12": True})
        self.assertEqual(tasks["11"]["plan"], 200.0)
        self.assertTrue(tasks["11"]["closed"])
        self.assertEqual(tasks["11"]["parent_id"], "10")
        self.assertEqual(tasks["10"]["plan"], 0.0)
        first = client._bitrix_token.calls[0][1]
        self.assertEqual(first["filter"], {f">{FIELD}": 0})
        self.assertIn(FIELD, first["select"])


class PlanFactAccessTest(TestCase):
    def setUp(self):
        cache.clear()
        self.allowed = self.account("m-allowed", 11)
        self.other = self.account("m-other", 12)
        TimesheetItem.objects.create(
            bitrix24_account=self.allowed, bitrix_id=1, task_id="11", employee_id="1199", hours=8.0,
            is_billable=True, project_id="209", project_title="НАВИГАТОР АО",
            task_hierarchy_ids=["10", "11"], task_hierarchy_titles=["Этап", "Подзадача"],
            date_reflection=timezone.make_aware(datetime(2026, 9, 15, 0, 0)),
        )
        patcher = patch.object(Bitrix24Account, "client", property(lambda _self: FakeClient(PORTAL_TASKS)))
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def account(member_id, user_id):
        return Bitrix24Account.objects.create(
            b24_user_id=user_id, is_b24_user_admin=True, member_id=member_id, is_master_account=True,
            domain_url=f"{member_id}.bitrix24.ru", status="active", application_version=1,
        )

    @staticmethod
    def get(path, account):
        return Client().get(path, HTTP_AUTHORIZATION=f"Bearer {account.create_jwt_token()}")

    def test_default_whitelist_is_mainsoft_only(self):
        self.assertEqual(list(DEFAULT_PLAN_FACT_PORTALS), ["ac90d2405edacb6e7e65074528ce1af8"])
        self.assertIsNone(plan_fact_settings(self.allowed))   # без override — чужой портал
        self.assertIsNone(plan_fact_settings(self.other))

    def test_default_settings_close_report_for_any_other_portal(self):
        for path in ("/api/report-plan-fact", "/api/report-plan-fact-export"):
            response = self.get(path, self.allowed)
            self.assertEqual(response.status_code, 404, path)
        self.assertNotIn("plan_fact_report", self.get("/api/features", self.allowed).json())

    @override_settings(PLAN_FACT_PORTALS=ALLOWED)
    def test_other_portal_gets_404_and_no_feature_key(self):
        for path in ("/api/report-plan-fact", "/api/report-plan-fact-export"):
            response = self.get(path, self.other)
            self.assertEqual(response.status_code, 404, path)
            self.assertEqual(response.json()["code"], "plan_fact_unavailable")
        self.assertNotIn("plan_fact_report", self.get("/api/features", self.other).json())

    @override_settings(PLAN_FACT_PORTALS=ALLOWED)
    def test_allowed_portal_gets_report_feature_and_excel(self):
        features = self.get("/api/features", self.allowed).json()
        self.assertEqual(features["plan_fact_report"]["state"], "on")

        response = self.get("/api/report-plan-fact?date_from=2026-09-01&date_to=2026-09-30", self.allowed)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["plan_warning"], "")
        project = payload["projects"][0]
        self.assertEqual((project["id"], project["plan_hours"], project["total_hours"]), ("209", 200.0, 8.0))
        self.assertEqual(project["children"][0]["children"][0]["id"], "11")

        export = self.get("/api/report-plan-fact-export?date_from=2026-09-01&date_to=2026-09-30", self.allowed)
        self.assertEqual(export.status_code, 200)
        self.assertIn("spreadsheetml", export["Content-Type"])

    @override_settings(PLAN_FACT_PORTALS=ALLOWED)
    def test_portal_failure_keeps_fact_and_warns(self):
        class Broken:
            class _bitrix_token:  # noqa: N801
                @staticmethod
                def call_method(method, params=None):
                    if method == "tasks.task.list":
                        raise RuntimeError("портал не ответил")
                    return {"result": []}

        with patch.object(Bitrix24Account, "client", property(lambda _self: Broken())):
            payload = self.get("/api/report-plan-fact?date_from=2026-09-01&date_to=2026-09-30", self.allowed).json()
        self.assertTrue(payload["plan_warning"])
        self.assertEqual(payload["projects"][0]["total_hours"], 8.0)
        self.assertEqual(payload["projects"][0]["plan_hours"], 0.0)
