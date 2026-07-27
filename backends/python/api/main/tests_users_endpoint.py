"""GET /api/users — пагинированный список сотрудников из локальной БД."""
from unittest.mock import MagicMock, patch

from django.test import Client, TestCase, override_settings

from .models import Bitrix24Account, PortalUser
from .sync_scheduler_service import run_scheduled_sync
from .tenant_scoping import scope_to_tenant


class GetUsersEndpointTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-users-ep-1",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        self.token = self.account.create_jwt_token()

    def _get(self, query=""):
        return Client().get(f"/api/users{query}", HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def test_returns_paginated_users_from_db(self):
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="1", name="Иван", last_name="Абрамов", active=True)
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="2", name="Анна", last_name="Багрова", active=False)

        response = self._get()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual([item["id"] for item in data["items"]], ["1", "2"])  # order_by last_name
        self.assertIn("has_next", data)
        self.assertFalse(data["has_next"])

    def test_active_only_filter(self):
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="1", name="Иван", last_name="Абрамов", active=True)
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="2", name="Анна", last_name="Багрова", active=False)

        response = self._get("?active_only=1")

        data = response.json()
        self.assertEqual([item["id"] for item in data["items"]], ["1"])

    def test_pagination_limit_and_page_params(self):
        for i in range(1, 4):
            PortalUser.objects.create(bitrix24_account=self.account, bitrix_id=str(i), name=f"U{i}", last_name="L", active=True)

        response = self._get("?limit=2&page=2")
        data = response.json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["page"], 2)
        self.assertEqual(data["pages"], 2)

    def test_requires_auth(self):
        # Без Authorization заголовка auth_required уходит в OAuth-ветку и падает
        # на пустом теле запроса -> 400 (см. QueryStabilityTest для /api/configuration/,
        # тот же паттерн для GET-эндпоинтов без тела).
        response = Client().get("/api/users")
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_does_not_leak_other_tenant_users(self):
        other = Bitrix24Account.objects.create(
            b24_user_id=2, is_b24_user_admin=True, member_id="m-users-ep-2",
            is_master_account=True, domain_url="other.bitrix24.ru",
            status="active", application_version=1,
        )
        PortalUser.objects.create(bitrix24_account=other, bitrix_id="1", name="Чужой", last_name="Юзер", active=True)

        response = self._get()
        data = response.json()
        self.assertEqual(data["total"], 0)

    # --- Ревью Задачи 5, Important #1: `limit` из query string шёл прямо в
    # Paginator(queryset, page_size) без валидации -> 500 на limit=0
    # ("division by zero"), limit=-1 ("That page number is less than 1",
    # вводит в заблуждение — жалуется на page, хотя проблема в limit),
    # limit=abc ("invalid literal for int()"). Клиент не должен получать
    # 500 и сырой текст Python-исключения на банальной ошибке ввода.

    def test_limit_zero_is_clamped_to_minimum_not_500(self):
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="1", name="Иван", last_name="Абрамов", active=True)
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="2", name="Анна", last_name="Багрова", active=True)

        response = self._get("?limit=0")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["items"]), 1)  # limit=0 -> клэмп к минимуму 1
        self.assertEqual(data["pages"], 2)

    def test_limit_negative_is_clamped_to_minimum_not_500(self):
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="1", name="Иван", last_name="Абрамов", active=True)
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="2", name="Анна", last_name="Багрова", active=True)

        response = self._get("?limit=-1")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["pages"], 2)

    def test_limit_non_numeric_falls_back_to_default_not_500(self):
        for i in range(1, 4):
            PortalUser.objects.create(bitrix24_account=self.account, bitrix_id=str(i), name=f"U{i}", last_name="L", active=True)

        response = self._get("?limit=abc")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["items"]), 3)  # дефолт 50 -> все 3 влезают на одну страницу
        self.assertEqual(data["pages"], 1)

    def test_limit_above_upper_bound_is_clamped(self):
        PortalUser.objects.bulk_create([
            PortalUser(bitrix24_account=self.account, bitrix_id=str(i), name=f"U{i}", last_name="L", active=True)
            for i in range(1, 202)
        ])

        response = self._get("?limit=100000")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["items"]), 200)  # верхний предел — не весь справочник в одном ответе
        self.assertEqual(data["pages"], 2)

    # --- Ревью Задачи 5, Important #2: order_by("last_name", "name") без
    # тайбрейкера не гарантирует стабильный порядок между запросами разных
    # страниц при совпадении last_name/name -> риск дублей/пропусков при
    # постраничном обходе с фронта (Задача 6).

    def test_pagination_stable_across_pages_for_duplicate_names(self):
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="30", name="Иван", last_name="Петров", active=True)
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="10", name="Иван", last_name="Петров", active=True)
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="20", name="Иван", last_name="Петров", active=True)

        ids_in_page_order = [
            self._get(f"?limit=1&page={page}").json()["items"][0]["id"]
            for page in (1, 2, 3)
        ]

        # Тайбрейкер bitrix_id (уникален в пределах тенанта) гарантирует
        # детерминированный возрастающий порядок при равенстве last_name/name
        # -> обход постранично не теряет и не дублирует записи.
        self.assertEqual(ids_in_page_order, ["10", "20", "30"])


class SyncSchedulerUsersReadPathTest(TestCase):
    """READ-путь Дефекта 2 финального ревью Фазы 2 (тот же класс бага, что

    fixwave CRITICAL #1 у timesheet): scope="users" должен синкать КАЖДЫЙ
    аккаунт портала под USE_PORTAL_SCOPING=False, а не одного представителя
    — иначе GET /api/users отдаёт пустой список всем сотрудникам портала,
    кроме того единственного аккаунта, которого планировщик выбрал бы
    представителем. Регресс на уровне run_scheduled_sync() —
    RunScheduledSyncUsersAccountSetTest в tests_scheduled_sync.py.

    Здесь UserSyncService замокан на уровне класса (как в
    ProjectSyncService-тестах tests_scheduled_sync.py), но side_effect
    воспроизводит РЕАЛЬНУЮ запись UserSyncService._save_batch — создаёт
    PortalUser через scope_to_tenant(account, write=True) для ТОГО аккаунта,
    которому планировщик выдал сервис. Это и есть причинно-следственная
    цепочка: кого выбрал планировщик -> под чьим FK пишутся строки -> кто их
    увидит на чтении."""

    @override_settings(USE_PORTAL_SCOPING=False)
    @patch("main.sync_scheduler_service.UserSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_both_accounts_of_portal_see_users_after_scheduled_sync(self, mock_cfg_cls, mock_user_cls):
        acc1 = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-users-read-1",
            is_master_account=True, domain_url="m-users-read-1.bitrix24.ru",
            status="S", application_version=1, refresh_token="rt1",
        )
        acc2 = Bitrix24Account.objects.create(
            b24_user_id=2, is_b24_user_admin=True, member_id="m-users-read-1",
            is_master_account=False, domain_url="m-users-read-1.bitrix24.ru",
            status="S", application_version=1, refresh_token="rt2",
        )
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg

        def fake_user_sync(client, account):
            service = MagicMock()

            def _sync(*args, **kwargs):
                PortalUser.objects.create(
                    **scope_to_tenant(account, write=True),
                    bitrix_id="777", name="Иван", last_name="Тестов",
                )
                return {"synced": 1, "created": 1, "updated": 0}

            service.sync.side_effect = _sync
            return service

        mock_user_cls.side_effect = fake_user_sync

        run_scheduled_sync(scope="users")

        for account in (acc1, acc2):
            token = account.create_jwt_token()
            response = Client().get("/api/users", HTTP_AUTHORIZATION=f"Bearer {token}")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertGreater(
                data["total"], 0,
                f"аккаунт b24_user_id={account.b24_user_id} не видит сотрудников после синка",
            )
