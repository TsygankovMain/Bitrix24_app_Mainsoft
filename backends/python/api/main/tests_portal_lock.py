"""Тест выбора субъекта advisory-замка (задача 4.3-lock; фикс-раунд задачи 5
«Кнопка Создать проект»: scope="project_create" не должен молча зависеть от
USE_PORTAL_SCOPING — см. ProjectCreateLockSubjectTest ниже)."""
from django.test import TestCase, override_settings

from .models import Bitrix24Account, Portal
from .utils.decorators.sync_lock import _lock_subject_pk


def _account(member_id="m1", with_portal=True, b24_user_id=1):
    portal = Portal.objects.create(member_id=member_id, domain_url=f"{member_id}.b24.ru", status="active") if with_portal else None
    return Bitrix24Account.objects.create(
        b24_user_id=b24_user_id, is_b24_user_admin=True, member_id=member_id, is_master_account=True,
        domain_url=f"{member_id}.b24.ru", status="active", application_version=1, portal=portal,
    ), portal


class LockSubjectTest(TestCase):
    """scope="project" здесь представляет три унаследованных scope
    (timesheet/project/users): поведение БИТ-в-БИТ, менять нельзя — на нём
    завязана сериализация фонового синка и другие тесты."""

    @override_settings(USE_PORTAL_SCOPING=False)
    def test_flag_off_subject_is_account_pk(self):
        acc, _ = _account()
        self.assertEqual(_lock_subject_pk(acc, "project"), acc.pk)

    @override_settings(USE_PORTAL_SCOPING=True)
    def test_flag_on_subject_is_portal_pk(self):
        acc, portal = _account()
        self.assertEqual(_lock_subject_pk(acc, "project"), portal.pk)

    @override_settings(USE_PORTAL_SCOPING=True)
    def test_flag_on_no_portal_falls_back_to_account_pk(self):
        acc, _ = _account(with_portal=False)
        self.assertEqual(_lock_subject_pk(acc, "project"), acc.pk)


class ProjectCreateLockSubjectTest(TestCase):
    """scope="project_create" (кнопка «Создать проект»): Bitrix24Account в
    этом приложении — запись НА СОТРУДНИКА (unique_together = b24_user_id +
    domain_url, свои токены), а не на компанию. Два разных сотрудника одного
    портала обязаны получать ОДИН И ТОТ ЖЕ субъект замка НЕЗАВИСИМО от
    USE_PORTAL_SCOPING — иначе оба проходят account_sync_lock параллельно,
    оба не находят компанию/группу по имени и оба создают дубли прямо в
    Битриксе. Локальная дедупликация строк ProjectCard тут не спасает: до неё
    дело не доходит, расходятся сами вызовы crm.company.add/sonet_group.create.

    Регрессия ревью фикс-раунда задачи 5: до фикса при выключенном
    USE_PORTAL_SCOPING (боевое значение флага задаётся переменной окружения
    вне репозитория и нигде не закреплено тестом) _lock_subject_pk возвращал
    account.pk, и два теста ниже('...flag_off...' и '...flag_on...')
    расходились бы для одного и того же портала."""

    def _two_accounts_same_portal(self):
        portal = Portal.objects.create(
            member_id="m-pc-lock", domain_url="m-pc-lock.b24.ru", status="active",
        )
        acc_a = Bitrix24Account.objects.create(
            b24_user_id=101, is_b24_user_admin=True, member_id="m-pc-lock",
            is_master_account=True, domain_url="m-pc-lock.b24.ru",
            status="active", application_version=1, portal=portal,
        )
        acc_b = Bitrix24Account.objects.create(
            b24_user_id=102, is_b24_user_admin=False, member_id="m-pc-lock",
            is_master_account=False, domain_url="m-pc-lock.b24.ru",
            status="active", application_version=1, portal=portal,
        )
        return acc_a, acc_b, portal

    @override_settings(USE_PORTAL_SCOPING=False)
    def test_flag_off_two_accounts_same_portal_share_subject(self):
        acc_a, acc_b, portal = self._two_accounts_same_portal()
        subject_a = _lock_subject_pk(acc_a, "project_create")
        subject_b = _lock_subject_pk(acc_b, "project_create")
        self.assertEqual(subject_a, subject_b)
        self.assertEqual(subject_a, portal.pk)

    @override_settings(USE_PORTAL_SCOPING=True)
    def test_flag_on_two_accounts_same_portal_share_subject(self):
        acc_a, acc_b, portal = self._two_accounts_same_portal()
        subject_a = _lock_subject_pk(acc_a, "project_create")
        subject_b = _lock_subject_pk(acc_b, "project_create")
        self.assertEqual(subject_a, subject_b)
        self.assertEqual(subject_a, portal.pk)

    def test_no_portal_falls_back_to_account_pk_regardless_of_flag(self):
        """Без portal (переходный период/легаси-запись) сериализовать не по
        чему — деградация к account.pk, как и у унаследованных scope, под
        обоими состояниями флага."""
        acc, _ = _account(with_portal=False)
        with override_settings(USE_PORTAL_SCOPING=False):
            self.assertEqual(_lock_subject_pk(acc, "project_create"), acc.pk)
        with override_settings(USE_PORTAL_SCOPING=True):
            self.assertEqual(_lock_subject_pk(acc, "project_create"), acc.pk)
