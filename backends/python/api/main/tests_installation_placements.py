"""Тесты привязки вкладок при установке (InstallationService._install_placements_sync).

Вкладка в карточке сделки (CRM_DEAL_DETAIL_TAB) не привязывается: её экран — заглушка
«в разработке». До 06.10.2026 установка привязывала её, и на портале появлялась пустая
вкладка «Финансы проекта». Отвязка при этом должна остаться — она снимает вкладку
с порталов, где её привязали прежние версии.
"""
from django.test import SimpleTestCase

from .installation_service import InstallationService


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
