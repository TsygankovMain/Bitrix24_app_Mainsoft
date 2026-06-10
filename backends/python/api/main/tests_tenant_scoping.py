"""Тесты помощника scope_to_tenant и флага USE_PORTAL_SCOPING (задача 4.3)."""
from django.test import TestCase, override_settings

from .models import Bitrix24Account, Portal
from .tenant_scoping import scope_to_tenant


def _account(member_id="m1", *, with_portal=True):
    portal = None
    if with_portal:
        portal = Portal.objects.create(member_id=member_id, domain_url=f"{member_id}.b24.ru", status="active")
    return Bitrix24Account.objects.create(
        b24_user_id=1, is_b24_user_admin=True, member_id=member_id, is_master_account=True,
        domain_url=f"{member_id}.b24.ru", status="active", application_version=1, portal=portal,
    ), portal


class ScopeToTenantTest(TestCase):
    @override_settings(USE_PORTAL_SCOPING=False)
    def test_flag_off_returns_account_kwargs(self):
        acc, _ = _account()
        self.assertEqual(scope_to_tenant(acc), {"bitrix24_account": acc})
        # write=True при выключенном флаге — тоже account.
        self.assertEqual(scope_to_tenant(acc, write=True), {"bitrix24_account": acc})

    @override_settings(USE_PORTAL_SCOPING=True)
    def test_flag_on_with_portal_reads_by_portal(self):
        acc, portal = _account()
        self.assertEqual(scope_to_tenant(acc), {"portal": portal})

    @override_settings(USE_PORTAL_SCOPING=True)
    def test_flag_on_write_sets_both_portal_and_account(self):
        acc, portal = _account()
        result = scope_to_tenant(acc, write=True)
        self.assertEqual(result, {"portal": portal, "bitrix24_account": acc})

    @override_settings(USE_PORTAL_SCOPING=True)
    def test_flag_on_but_portal_empty_falls_back_to_account(self):
        acc, _ = _account(with_portal=False)
        self.assertIsNone(acc.portal_id)
        self.assertEqual(scope_to_tenant(acc), {"bitrix24_account": acc})
        self.assertEqual(scope_to_tenant(acc, write=True), {"bitrix24_account": acc})
