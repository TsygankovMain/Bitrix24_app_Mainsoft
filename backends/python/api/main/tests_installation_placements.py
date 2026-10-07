"""Тесты привязки вкладок при установке (InstallationService._install_placements_sync).

Вкладка в карточке сделки (CRM_DEAL_DETAIL_TAB) не привязывается: её экран — заглушка
«в разработке». До 06.10.2026 установка привязывала её, и на портале появлялась пустая
вкладка «Финансы проекта». Отвязка при этом должна остаться — она снимает вкладку
с порталов, где её привязали прежние версии.
"""
from unittest import mock

from django.test import SimpleTestCase, TestCase

from .installation_service import InstallationService
from .models import Bitrix24Account, Portal


class _Token:
    def __init__(self):
        self.calls = []

    def call_method(self, method, params=None):
        self.calls.append((method, params or {}))
        return {"result": True}


class _Client:
    def __init__(self):
        self._bitrix_token = _Token()


class InstallPlacementsTest(SimpleTestCase):
    def setUp(self):
        self.client_double = _Client()
        InstallationService(self.client_double, None)._install_placements_sync()
        self.calls = self.client_double._bitrix_token.calls

    def _placements(self, method):
        return [params.get("PLACEMENT") for name, params in self.calls if name == method]

    def test_task_and_group_tabs_are_bound(self):
        self.assertEqual(sorted(self._placements("placement.bind")), ["SONET_GROUP_DETAIL_TAB", "TASK_VIEW_TAB"])

    def test_deal_tab_is_not_bound(self):
        self.assertNotIn("CRM_DEAL_DETAIL_TAB", self._placements("placement.bind"))

    def test_deal_tab_left_by_older_versions_is_unbound(self):
        self.assertIn("CRM_DEAL_DETAIL_TAB", self._placements("placement.unbind"))

    def test_unbind_removes_handlers_of_any_address(self):
        """Отвязка идёт без HANDLER: иначе вкладка со старым адресом остаётся на портале."""
        for name, params in self.calls:
            if name == "placement.unbind":
                self.assertNotIn("HANDLER", params)

    def test_tabs_are_unbound_before_bind(self):
        methods = [name for name, _ in self.calls]
        last_unbind = max(i for i, name in enumerate(methods) if name == "placement.unbind")
        first_bind = methods.index("placement.bind")
        self.assertLess(last_unbind, first_bind)


class _FailingBindToken(_Token):
    def call_method(self, method, params=None):
        self.calls.append((method, params or {}))
        if method == "placement.bind":
            raise RuntimeError("ACCESS_DENIED")
        return {"result": True}


NEW_URL = "https://timesheet.example.test"


@mock.patch("main.installation_service.config.app_base_url", NEW_URL)
class EnsurePlacementsCurrentTest(TestCase):
    """Самолечение после смены домена (инцидент 07.10.2026).

    После переезда на новый сервер на портале осталась вкладка «Учет трудозатрат»
    со старым адресом — она не открывалась, рядом висела рабочая «Учет времени».
    """

    def setUp(self):
        self.portal = Portal.objects.create(member_id="m1", domain_url="p.bitrix24.ru")
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, member_id="m1", domain_url="p.bitrix24.ru", status="active",
            application_version=1, is_b24_user_admin=True, is_master_account=False,
            portal=self.portal,
        )
        self.client_double = _Client()

    def _ensure(self):
        return InstallationService(self.client_double, self.account).ensure_placements_current_sync()

    def _stored(self):
        return Portal.objects.get(pk=self.portal.pk).placements_handler_url

    def test_rebinds_when_address_changed(self):
        Portal.objects.filter(pk=self.portal.pk).update(placements_handler_url="https://old.example.test")
        self.assertTrue(self._ensure())
        binds = [p for name, p in self.client_double._bitrix_token.calls if name == "placement.bind"]
        self.assertEqual({p["HANDLER"] for p in binds}, {NEW_URL})
        self.assertEqual(self._stored(), NEW_URL)

    def test_rebinds_portal_installed_before_the_mark_existed(self):
        self.assertIsNone(self._stored())
        self.assertTrue(self._ensure())
        self.assertEqual(self._stored(), NEW_URL)

    def test_second_call_does_nothing(self):
        self._ensure()
        self.client_double._bitrix_token.calls.clear()
        self.assertFalse(self._ensure())
        self.assertEqual(self.client_double._bitrix_token.calls, [])

    def test_failed_bind_is_retried_next_time(self):
        self.client_double._bitrix_token = _FailingBindToken()
        self.assertFalse(self._ensure())
        self.assertIsNone(self._stored())

    def test_nothing_without_app_address(self):
        with mock.patch("main.installation_service.config.app_base_url", ""):
            self.assertFalse(self._ensure())
        self.assertEqual(self.client_double._bitrix_token.calls, [])
