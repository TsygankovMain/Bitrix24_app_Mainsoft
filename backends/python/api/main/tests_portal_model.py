"""Тесты модели Portal и seed-миграции (задача 4.0)."""
from django.test import TestCase

from .models import Bitrix24Account, Portal


def _account(member_id, *, master=False, b24_user_id=1, domain=None, status="active"):
    return Bitrix24Account.objects.create(
        b24_user_id=b24_user_id,
        is_b24_user_admin=True,
        member_id=member_id,
        is_master_account=master,
        domain_url=domain or f"{member_id}.bitrix24.ru",
        status=status,
        application_version=1,
    )


class PortalModelTest(TestCase):
    def test_member_id_is_unique(self):
        Portal.objects.create(member_id="m1", domain_url="m1.bitrix24.ru", status="active")
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Portal.objects.create(member_id="m1", domain_url="dup.bitrix24.ru", status="active")

    def test_account_has_nullable_portal_fk_default_none(self):
        acc = _account("m2")
        # На этапе 0 FK ещё не заполнен напрямую при создании аккаунта.
        self.assertIsNone(acc.portal_id)

    def test_timesheet_and_card_have_nullable_portal_fk(self):
        # Поле существует и nullable: создаём запись БЕЗ portal — не падает.
        from .models import TimesheetItem, ProjectCard
        from django.utils import timezone
        acc = _account("m3")
        ts = TimesheetItem.objects.create(
            bitrix24_account=acc, bitrix_id=1, task_id="1", employee_id="1",
            hours=1.0, date_reflection=timezone.now(),
        )
        card = ProjectCard.objects.create(
            bitrix24_account=acc, project_id="100", project_name="P", stage="new",
        )
        self.assertIsNone(ts.portal_id)
        self.assertIsNone(card.portal_id)


class SeedPortalsMigrationTest(TestCase):
    """Проверяем эффект data-migration 0015 на «живых» данных.

    Тест-раннер применяет все миграции к sqlite, включая 0015, но 0015 видит
    пустую БД (фикстур ещё нет). Поэтому здесь воспроизводим её ЛОГИКУ через
    публичную функцию seed_portals_from_accounts (вынесена в migrations-helper
    и переиспользуется), чтобы протестировать дедуп по member_id и проставление
    Bitrix24Account.portal.
    """

    def test_one_portal_per_member_id_and_account_linked(self):
        from .portal_seed import seed_portals_from_accounts
        # Две учётки одной компании m1 + одна m2.
        a1 = _account("m1", master=True, b24_user_id=1, domain="m1.bitrix24.ru")
        a2 = _account("m1", master=False, b24_user_id=2, domain="m1.bitrix24.ru")
        a3 = _account("m2", master=True, b24_user_id=3, domain="m2.bitrix24.ru")

        created = seed_portals_from_accounts(Portal, Bitrix24Account)

        self.assertEqual(Portal.objects.count(), 2)  # по одному на member_id
        self.assertEqual(created, 2)
        # Повторный прогон идемпотентен — новых Portal нет.
        created_again = seed_portals_from_accounts(Portal, Bitrix24Account)
        self.assertEqual(created_again, 0)
        self.assertEqual(Portal.objects.count(), 2)

        for acc in (a1, a2, a3):
            acc.refresh_from_db()
            self.assertIsNotNone(acc.portal_id)
        a1.refresh_from_db()
        a2.refresh_from_db()
        self.assertEqual(a1.portal_id, a2.portal_id)  # обе учётки m1 -> один Portal
        # Домен Portal m1 взят у мастер-аккаунта.
        p1 = Portal.objects.get(member_id="m1")
        self.assertEqual(p1.domain_url, "m1.bitrix24.ru")
