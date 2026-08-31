"""Эндпоинты закрытия месяца.

Главное, что здесь закрепляется: блокеры проверяются НА СЕРВЕРЕ. Экран
показывает проверку и гасит кнопку, но полагаться на это нельзя — запрос
можно отправить и мимо интерфейса, а закрыть месяц со сломанными данными
операция необратимая.

Про права. Серверного гейта по роли здесь нет — это следование решению
владельца продукта от 11.06.2026, снявшему @admin_required со всех
эндпоинтов (см. tests_security_roles). Флаг администратора используется
фронтом, чтобы прятать экран настроек. Вопрос, нужно ли для закрытия месяца
сделать исключение, вынесен заказчику отдельно.
"""

import json
from datetime import datetime

from django.test import Client, TestCase
from django.utils import timezone

from .models import Bitrix24Account, ClosedPeriod, PortalTask, TimesheetItem
from .period_service import PeriodService


class PeriodEndpointsTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-ep",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        self.token = self.account.create_jwt_token()

    def _entry(self, bitrix_id, *, project_id="73", task_id="8365", month=8, hours=1.0):
        TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=bitrix_id, task_id=task_id,
            employee_id="11", hours=hours, project_id=project_id,
            project_title="Мейнсофт", task_hierarchy_ids=[task_id],
            task_hierarchy_titles=["Задача"],
            date_reflection=timezone.make_aware(datetime(2026, month, 15, 0, 0)),
        )

    def _get(self, path):
        return Client().get(path, HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def _post(self, path, body):
        return Client().post(
            path, data=json.dumps(body), content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )

    # ---------- Список ----------

    def test_periods_are_built_from_entries(self):
        """Календарь не заводим: периоды без часов закрывать незачем."""
        self._entry(1, month=8)
        self._entry(2, month=7)

        data = self._get("/api/periods").json()

        self.assertEqual([(p["year"], p["month"]) for p in data["periods"]],
                         [(2026, 8), (2026, 7)])
        self.assertFalse(data["periods"][0]["closed"])

    def test_closed_period_shows_journal(self):
        self._entry(1, month=8)
        PeriodService(self.account).close(2026, 8, stats={}, by_id="11",
                                          by_name="Егор Цыганков")

        item = self._get("/api/periods").json()["periods"][0]

        self.assertTrue(item["closed"])
        self.assertEqual(item["closed_by_name"], "Егор Цыганков")

    # ---------- Проверка ----------

    def test_check_reports_clean_month(self):
        self._entry(1)

        data = self._get("/api/periods/check?year=2026&month=8").json()

        self.assertTrue(data["can_close"])
        self.assertEqual(data["stats"]["entries"], 1)

    def test_check_reports_blockers(self):
        self._entry(1, project_id="")

        data = self._get("/api/periods/check?year=2026&month=8").json()

        self.assertFalse(data["can_close"])
        self.assertIn("no_project", [b["code"] for b in data["blockers"]])

    def test_check_details_lists_entries(self):
        self._entry(1, project_id="")
        self._entry(2, project_id="73")

        data = self._get("/api/periods/check?year=2026&month=8&code=no_project").json()

        self.assertEqual([i["bitrix_id"] for i in data["items"]], [1])

    def test_bad_period_is_rejected(self):
        for query in ("", "?year=2026", "?year=2026&month=13", "?year=abc&month=8"):
            with self.subTest(query=query):
                self.assertEqual(self._get(f"/api/periods/check{query}").status_code, 400)

    # ---------- Закрытие ----------

    def test_close_freezes_period(self):
        self._entry(1)

        response = self._post("/api/periods/close", {"year": 2026, "month": 8})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "closed")
        self.assertTrue(ClosedPeriod.objects.filter(year=2026, month=8).exists())

    def test_close_is_refused_when_blockers_present(self):
        """Ядро: сервер не полагается на то, что кнопка была неактивна."""
        self._entry(1, project_id="")

        response = self._post("/api/periods/close", {"year": 2026, "month": 8})

        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual(body["code"], "blockers_present")
        self.assertIn("no_project", [b["code"] for b in body["check"]["blockers"]])
        self.assertFalse(ClosedPeriod.objects.exists(), "период не должен закрыться")

    def test_close_stores_stats_snapshot(self):
        """Снимок объёма нужен для сверки «столько мы заморозили».
        Пересчитывать его потом бессмысленно: данные могли измениться."""
        self._entry(1, hours=4.0)
        self._entry(2, hours=2.5)

        self._post("/api/periods/close", {"year": 2026, "month": 8})

        stats = ClosedPeriod.objects.get(year=2026, month=8).stats
        self.assertEqual(stats["hours"], 6.5)
        self.assertEqual(stats["entries"], 2)

    # ---------- Переоткрытие ----------

    def test_reopen_requires_reason(self):
        self._entry(1)
        self._post("/api/periods/close", {"year": 2026, "month": 8})

        response = self._post("/api/periods/reopen", {"year": 2026, "month": 8})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "reason_required")

    def test_reopen_with_reason_works(self):
        self._entry(1)
        self._post("/api/periods/close", {"year": 2026, "month": 8})

        response = self._post("/api/periods/reopen", {
            "year": 2026, "month": 8, "reason": "Учесть 3 записи после закрытия",
        })

        self.assertEqual(response.status_code, 200)
        row = ClosedPeriod.objects.get(year=2026, month=8)
        self.assertEqual(row.reopen_reason, "Учесть 3 записи после закрытия")

    def test_reopen_of_unknown_period_is_404(self):
        response = self._post("/api/periods/reopen", {
            "year": 2026, "month": 8, "reason": "х",
        })
        self.assertEqual(response.status_code, 404)

    # ---------- Опоздавшие ----------

    def test_late_arrivals_listed(self):
        self._entry(1)
        self._post("/api/periods/close", {"year": 2026, "month": 8})
        period = ClosedPeriod.objects.get(year=2026, month=8)

        TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=99, task_id="1",
            employee_id="11", hours=4, project_id="73", project_title="Мейнсофт",
            task_hierarchy_ids=["1"], task_hierarchy_titles=["Задача"],
            date_reflection=timezone.make_aware(datetime(2026, 8, 28, 0, 0)),
            source_created_at=period.closed_at + timezone.timedelta(days=1),
        )

        data = self._get("/api/periods/late?year=2026&month=8").json()

        self.assertEqual([i["bitrix_id"] for i in data["items"]], [99])

    def test_late_arrivals_of_open_period_is_empty(self):
        self._entry(1)
        self.assertEqual(self._get("/api/periods/late?year=2026&month=8").json()["items"], [])

    # ---------- Авторизация ----------

    def test_endpoints_require_auth(self):
        for path in ("/api/periods", "/api/periods/check?year=2026&month=8"):
            with self.subTest(path=path):
                self.assertIn(Client().get(path).status_code, (400, 401))
