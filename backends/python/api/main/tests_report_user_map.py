"""_get_user_map строит карту имён из локальной БД (portal_user), а не из
Bitrix user.get (Фаза 2 sync-offload: убирает 3-7с "user_map" на отчётах)."""
from django.test import RequestFactory, TestCase

from . import views
from .models import Bitrix24Account, PortalUser


class GetUserMapReadsFromPortalUserTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-map-1",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )

    def _request(self):
        request = RequestFactory().get("/api/report-employee-project")
        request.bitrix24_account = self.account
        return request

    def test_builds_map_from_local_db_without_bitrix_call(self):
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="1", name="Иван", last_name="Петров", active=True)
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="2", name="Анна", last_name="Сидорова", active=False)

        result = views._get_user_map(self._request(), {"1", "2"})

        self.assertEqual(result, {"1": "Петров Иван", "2": "Сидорова Анна"})

    def test_missing_user_id_is_simply_absent_from_map(self):
        result = views._get_user_map(self._request(), {"999"})
        self.assertEqual(result, {})  # resolve_employee_name падает на fallback "Сотрудник 999"

    def test_empty_user_ids_returns_empty_dict(self):
        self.assertEqual(views._get_user_map(self._request(), set()), {})

    def test_scoped_by_tenant_other_account_users_not_leaked(self):
        other = Bitrix24Account.objects.create(
            b24_user_id=2, is_b24_user_admin=True, member_id="m-map-2",
            is_master_account=True, domain_url="other.bitrix24.ru",
            status="active", application_version=1,
        )
        PortalUser.objects.create(bitrix24_account=other, bitrix_id="1", name="Чужой", last_name="Юзер", active=True)

        result = views._get_user_map(self._request(), {"1"})
        self.assertEqual(result, {})


class GetUserMapNormalizesNonCanonicalIdsTest(TestCase):
    """Ревью Задачи 4 (эскалировано до обязательного фикса): историчные
    TimesheetItem.employee_id могут быть неканоничными ("[12]", "12.0") —
    старый fetch_users резолвил их через numeric_to_aliases, поэтому
    _get_user_map обязан нормализовать id ПЕРЕД запросом к PortalUser (см.
    extract_bitrix_user_id — тот же конвертер, которым UserSyncService
    пишет PortalUser.bitrix_id) и отдавать канонический ключ (его же ищет
    resolve_employee_name первым делом через normalize_employee_id)."""

    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-map-3",
            is_master_account=True, domain_url="example-norm.bitrix24.ru",
            status="active", application_version=1,
        )

    def _request(self):
        request = RequestFactory().get("/api/report-employee-project")
        request.bitrix24_account = self.account
        return request

    def test_bracket_form_employee_id_resolves_to_canonical_key(self):
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="12", name="Игорь", last_name="Смирнов", active=True)

        result = views._get_user_map(self._request(), {"[12]"})

        self.assertEqual(result, {"12": "Смирнов Игорь"})

    def test_float_form_employee_id_resolves_to_canonical_key(self):
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="12", name="Игорь", last_name="Смирнов", active=True)

        result = views._get_user_map(self._request(), {"12.0"})

        self.assertEqual(result, {"12": "Смирнов Игорь"})

    def test_canonical_employee_id_still_resolves_name(self):
        """Регресс: нормализация не должна ломать уже-канонический путь."""
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="12", name="Игорь", last_name="Смирнов", active=True)

        result = views._get_user_map(self._request(), {"12"})

        self.assertEqual(result, {"12": "Смирнов Игорь"})

    def test_both_name_fields_empty_falls_back_to_bitrix_id(self):
        """Minor из ревью: пустые name/last_name -> значение падает на bitrix_id."""
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="5", name="", last_name="", active=True)

        result = views._get_user_map(self._request(), {"5"})

        self.assertEqual(result, {"5": "5"})
