"""Тесты модели PortalUser (Фаза 2 sync-offload: кэш пользователей)."""
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Bitrix24Account, PortalUser


def _account(member_id="m-pu-1", **kwargs):
    defaults = dict(
        b24_user_id=1, is_b24_user_admin=True, is_master_account=True,
        domain_url=f"{member_id}.bitrix24.ru", status="active", application_version=1,
    )
    defaults.update(kwargs)
    return Bitrix24Account.objects.create(member_id=member_id, **defaults)


class PortalUserModelTest(TestCase):
    def test_create_with_required_fields_and_defaults(self):
        account = _account()
        user = PortalUser.objects.create(
            bitrix24_account=account,
            bitrix_id="167",
            name="Иван",
            last_name="Петров",
        )
        self.assertTrue(user.active)  # default True
        self.assertIsNotNone(user.created_at)
        self.assertIsNotNone(user.updated_at)
        self.assertIsNone(user.portal_id)  # nullable до backfill/portal-скоупинга

    def test_unique_together_account_and_bitrix_id(self):
        account = _account("m-pu-uniq")
        PortalUser.objects.create(bitrix24_account=account, bitrix_id="1", name="A", last_name="B")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PortalUser.objects.create(bitrix24_account=account, bitrix_id="1", name="C", last_name="D")

    def test_same_bitrix_id_allowed_across_different_accounts(self):
        acc1 = _account("m-pu-2", b24_user_id=1)
        acc2 = _account("m-pu-3", b24_user_id=2)
        PortalUser.objects.create(bitrix24_account=acc1, bitrix_id="1", name="A", last_name="B")
        # тот же bitrix_id, другой портал — не конфликт (мульти-портал)
        PortalUser.objects.create(bitrix24_account=acc2, bitrix_id="1", name="X", last_name="Y")
        self.assertEqual(PortalUser.objects.filter(bitrix_id="1").count(), 2)

    def test_inactive_user_is_stored_not_dropped(self):
        account = _account("m-pu-4")
        user = PortalUser.objects.create(
            bitrix24_account=account, bitrix_id="2", name="Уволен", last_name="Сотрудников", active=False,
        )
        user.refresh_from_db()
        self.assertFalse(user.active)
