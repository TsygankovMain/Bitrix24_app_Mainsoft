"""Тест выбора субъекта advisory-замка под portal-скоупингом (задача 4.3-lock)."""
from django.test import TestCase, override_settings

from .models import Bitrix24Account, Portal
from .utils.decorators.sync_lock import _lock_subject_pk


def _account(member_id="m1", with_portal=True):
    portal = Portal.objects.create(member_id=member_id, domain_url="m1.b24.ru", status="active") if with_portal else None
    return Bitrix24Account.objects.create(
        b24_user_id=1, is_b24_user_admin=True, member_id=member_id, is_master_account=True,
        domain_url="m1.b24.ru", status="active", application_version=1, portal=portal,
    ), portal


class LockSubjectTest(TestCase):
    @override_settings(USE_PORTAL_SCOPING=False)
    def test_flag_off_subject_is_account_pk(self):
        acc, _ = _account()
        self.assertEqual(_lock_subject_pk(acc), acc.pk)

    @override_settings(USE_PORTAL_SCOPING=True)
    def test_flag_on_subject_is_portal_pk(self):
        acc, portal = _account()
        self.assertEqual(_lock_subject_pk(acc), portal.pk)

    @override_settings(USE_PORTAL_SCOPING=True)
    def test_flag_on_no_portal_falls_back_to_account_pk(self):
        acc, _ = _account(with_portal=False)
        self.assertEqual(_lock_subject_pk(acc), acc.pk)
