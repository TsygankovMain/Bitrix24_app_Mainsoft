"""Эндпоинты закрытия месяца.

Главное, что здесь закрепляется: блокеры проверяются НА СЕРВЕРЕ. Экран
показывает проверку и гасит кнопку, но полагаться на это нельзя — запрос
можно отправить и мимо интерфейса, а закрыть месяц со сломанными данными
операция необратимая.

Про права. Закрытие и переоткрытие закрыты серверной проверкой роли — это
точечное исключение из решения от 11.06.2026, снявшего гейт со всех
эндпоинтов. Заказчик вернул его 31.08.2026 именно для этих двух операций:
они необратимы и влияют на то, что уходит клиенту в счёт. Остальные
эндпоинты периодов (список, проверка, опоздавшие) только читают и гейта не
имеют.
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

    # ---------- Права ----------

    def test_non_admin_cannot_close(self):
        """Точечный гейт: закрытие необратимо и меняет то, что уходит в счёт."""
        self._entry(1)
        other = Bitrix24Account.objects.create(
            b24_user_id=303, is_b24_user_admin=False, member_id="m-ep",
            is_master_account=False, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )

        response = Client().post(
            "/api/periods/close",
            data=json.dumps({"year": 2026, "month": 8}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {other.create_jwt_token()}",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "admin_required")
        self.assertFalse(ClosedPeriod.objects.exists(), "период не должен закрыться")

    def test_non_admin_cannot_reopen(self):
        self._entry(1)
        self._post("/api/periods/close", {"year": 2026, "month": 8})
        other = Bitrix24Account.objects.create(
            b24_user_id=303, is_b24_user_admin=False, member_id="m-ep",
            is_master_account=False, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )

        response = Client().post(
            "/api/periods/reopen",
            data=json.dumps({"year": 2026, "month": 8, "reason": "хочу"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {other.create_jwt_token()}",
        )

        self.assertEqual(response.status_code, 403)
        self.assertIsNone(ClosedPeriod.objects.get(year=2026, month=8).reopened_at)

    def test_non_admin_can_still_read(self):
        """Общее решение от 11.06.2026 в силе: чтение роли не требует."""
        self._entry(1)
        other = Bitrix24Account.objects.create(
            b24_user_id=303, is_b24_user_admin=False, member_id="m-ep",
            is_master_account=False, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        token = other.create_jwt_token()

        for path in ("/api/periods", "/api/periods/check?year=2026&month=8"):
            with self.subTest(path=path):
                response = Client().get(path, HTTP_AUTHORIZATION=f"Bearer {token}")
                self.assertEqual(response.status_code, 200)

    def test_endpoints_require_auth(self):
        for path in ("/api/periods", "/api/periods/check?year=2026&month=8"):
            with self.subTest(path=path):
                self.assertIn(Client().get(path).status_code, (400, 401))


class ClosingOrderTest(TestCase):
    """Периоды закрываются строго от старых к новым.

    Нельзя закрыть август, оставив июль открытым: в череде закрытых периодов
    появятся дыры, и слово «закрыт» перестанет что-либо значить.

    Найдено при первом боевом использовании 31.08.2026. Первая версия экрана
    брала первый элемент списка, а список приходит отсортированным от НОВЫХ к
    старым — кнопка оказывалась у самого свежего месяца, ровно наоборот. У
    пользователя из десяти периодов кликабельным был только сентябрь, а
    остальные девять показывали подсказку «сначала закройте предыдущий»,
    указывавшую в никуда.

    Проверка живёт на СЕРВЕРЕ, а не только в интерфейсе: экран прячет кнопку,
    но запрос можно отправить мимо него, а закрытие необратимо.
    """

    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-order",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        self.token = self.account.create_jwt_token()
        # Три месяца с часами: июнь, июль, август.
        for month, bid in ((6, 1), (7, 2), (8, 3)):
            TimesheetItem.objects.create(
                bitrix24_account=self.account, bitrix_id=bid, task_id="1",
                employee_id="11", hours=1, project_id="73", project_title="Мейнсофт",
                task_hierarchy_ids=["1"], task_hierarchy_titles=["Задача"],
                date_reflection=timezone.make_aware(datetime(2026, month, 15, 0, 0)),
            )

    def _close(self, year, month):
        return Client().post(
            "/api/periods/close",
            data=json.dumps({"year": year, "month": month}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )

    def test_newest_month_cannot_be_closed_first(self):
        """Ровно тот случай, что был у пользователя."""
        response = self._close(2026, 8)

        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual(body["code"], "out_of_order")
        self.assertEqual(body["earliest_open"], {"year": 2026, "month": 6})
        self.assertIn("Июнь 2026", body["error"])
        self.assertFalse(ClosedPeriod.objects.exists())

    def test_oldest_month_closes(self):
        self.assertEqual(self._close(2026, 6).status_code, 200)

    def test_order_advances_after_each_closing(self):
        """Закрыли июнь — очередь дошла до июля, но не до августа."""
        self._close(2026, 6)

        self.assertEqual(self._close(2026, 8).status_code, 409)
        self.assertEqual(self._close(2026, 7).status_code, 200)
        self.assertEqual(self._close(2026, 8).status_code, 200)

    def test_reopening_returns_the_queue(self):
        """Переоткрытый период снова становится самым старым открытым."""
        self._close(2026, 6)
        self._close(2026, 7)
        Client().post(
            "/api/periods/reopen",
            data=json.dumps({"year": 2026, "month": 6, "reason": "поправить"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )

        response = self._close(2026, 8)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["earliest_open"], {"year": 2026, "month": 6})

    def test_empty_months_are_skipped(self):
        """Месяц без часов закрывать незачем, и требовать этого — тоже.

        Между июнем и августом нет мая, но если бы был пустой месяц, очередь
        не должна на нём застревать.
        """
        self._close(2026, 6)
        self._close(2026, 7)

        self.assertEqual(self._close(2026, 8).status_code, 200)
