"""Ролевая модель: матрица прав, серверные гейты, выключенная функция, перенос «Бухгалтерии».

Что закреплено и почему.

1. Портал без тарифа Pro (или с тарифом off) = поведение до ролей. Любой
   сотрудник читает реестр счетов, меняет ставку и настройки; отменяют счета
   админ портала и «Бухгалтерия»; закрывает месяц только админ портала — с
   прежними кодами отказов. Так в июне 2026 сломали отчёты, и роли сняли
   целиком: без тарифа никого запирать нельзя.
2. При Pro роли закрывают ДЕНЬГИ и необратимые операции на СЕРВЕРЕ, а отчёты
   по часам остаются открытыми.
3. Окончание Pro НЕ выключает роли: сотрудник без роли по-прежнему не видит
   ставок и сумм (feature_restrictions_active), закрывается только изменение
   ролей.
4. «Бухгалтерия» переносится из app.option в нашу БД один раз и дальше
   берётся только оттуда; недоступный портал перенос не «обнуляет».
"""

import json
from datetime import datetime, timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TestCase
from django.utils import timezone

from . import roles
from .models import (
    BillingDocument,
    Bitrix24Account,
    PortalRole,
    PortalRoleState,
    PortalSubscription,
    PortalUser,
    ProjectCard,
    TimesheetItem,
)
from .pro_plan_service import set_account_plan

MEMBER = "m-roles"


class FakeToken:
    """Портал-двойник: конфигурация приложения в app.option и пустые ответы на прочее."""

    def __init__(self, portal):
        self.portal = portal

    def call_method(self, method, params=None):
        self.portal.calls.append(method)
        if method == "app.option.get":
            if self.portal.fail_options:
                raise RuntimeError("портал недоступен")
            return {"result": {"timestamp_config": json.dumps(self.portal.config, ensure_ascii=False)}}
        if method == "app.option.set":
            self.portal.config = json.loads(params["options"]["timestamp_config"])
            return {"result": True}
        if method == "crm.item.list":
            return {"result": {"items": []}, "next": None}
        return {"result": {}}

    def call_batch(self, *args, **kwargs):
        return {"result": {"result": {}}}


class FakeClient:
    def __init__(self, portal):
        self._bitrix_token = FakeToken(portal)


class FakePortal:
    def __init__(self):
        self.config = {}
        self.fail_options = False
        self.calls = []


class RolesFixture(TestCase):
    def setUp(self):
        cache.clear()
        self.portal = FakePortal()
        patcher = patch.object(Bitrix24Account, "client", property(lambda _self: FakeClient(self.portal)))
        patcher.start()
        self.addCleanup(patcher.stop)

        self.admin = self.make_account(1, is_admin=True)
        for user_id, name, last_name in (("1", "Егор", "Цыганков"), ("21", "Анна", "Бухова"),
                                         ("31", "Пётр", "Проектов"), ("41", "Иван", "Сотрудников")):
            PortalUser.objects.create(bitrix24_account=self.admin, bitrix_id=user_id, name=name, last_name=last_name)

    def make_account(self, user_id, *, is_admin=False, member_id=MEMBER):
        return Bitrix24Account.objects.create(
            b24_user_id=user_id, is_b24_user_admin=is_admin, member_id=member_id,
            is_master_account=is_admin, domain_url=f"{member_id}.bitrix24.ru",
            status="active", application_version=1,
        )

    def pro(self, **kwargs):
        """Тариф Pro порталу: в нём и счёт, и БДДС, и ролевая модель."""
        return set_account_plan(self.admin, **kwargs)

    def set_role(self, user_id, role):
        PortalRole.objects.update_or_create(
            member_id=MEMBER, b24_user_id=str(user_id), defaults={"role": role},
        )

    def mark_imported(self):
        PortalRoleState.objects.update_or_create(
            member_id=MEMBER, defaults={"accountants_imported_at": timezone.now()},
        )

    def get(self, account, path):
        return Client().get(path, HTTP_AUTHORIZATION=f"Bearer {account.create_jwt_token()}")

    def post(self, account, path, body=None):
        return Client().post(
            path, data=json.dumps(body or {}), content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {account.create_jwt_token()}",
        )


# ---------------------------------------------------------------------------
# Матрица — чистые функции
# ---------------------------------------------------------------------------

class PermissionMatrixTest(TestCase):
    def perms(self, role, enabled, admin=False):
        return roles.compute_permissions(role, roles_enabled=enabled, is_portal_admin=admin)

    def test_portal_admin_can_everything_in_both_modes(self):
        for enabled in (True, False):
            self.assertEqual(self.perms(roles.ROLE_EMPLOYEE, enabled, admin=True), roles.ALL_PERMISSIONS)

    def test_roles_on_matrix(self):
        self.assertEqual(self.perms(roles.ROLE_ADMIN, True), roles.ALL_PERMISSIONS)
        self.assertEqual(self.perms(roles.ROLE_ACCOUNTANT, True), {
            "money_view", "rates_edit", "billing_issue", "billing_cancel",
            "operations_create", "period_close",
        })
        self.assertEqual(self.perms(roles.ROLE_PROJECT_MANAGER, True), {"money_view"})
        self.assertEqual(self.perms(roles.ROLE_EMPLOYEE, True), frozenset())

    def test_roles_off_is_the_old_behaviour(self):
        employee = self.perms(roles.ROLE_EMPLOYEE, False)
        self.assertEqual(employee, {"money_view", "rates_edit", "settings_manage"})
        accountant = self.perms(roles.ROLE_ACCOUNTANT, False)
        self.assertTrue({"billing_issue", "billing_cancel", "operations_create"} <= accountant)
        self.assertNotIn("period_close", accountant, "закрывать месяц без ролей может только админ портала")
        self.assertNotIn("roles_manage", accountant)

    def test_paid_roles_mean_nothing_without_the_feature(self):
        self.assertEqual(self.perms(roles.ROLE_ADMIN, False), self.perms(roles.ROLE_EMPLOYEE, False))
        self.assertEqual(self.perms(roles.ROLE_PROJECT_MANAGER, False), self.perms(roles.ROLE_EMPLOYEE, False))

    def test_catalog_covers_every_role_and_permission(self):
        catalog = roles.roles_catalog()
        self.assertEqual([row["code"] for row in catalog["roles"]], list(roles.ROLES))
        self.assertEqual([row["code"] for row in catalog["permissions"]], list(roles.PERMISSIONS))
        for row in catalog["roles"] + catalog["permissions"]:
            self.assertTrue(row["title"])

    def test_denial_text_names_roles_and_the_place_to_assign(self):
        text = roles.denial_text("billing_issue", roles_enabled=True)
        self.assertIn("«Администратор»", text)
        self.assertIn("«Бухгалтерия»", text)
        self.assertIn("Настройки → Роли и права", text)
        legacy = roles.denial_text("period_close", roles_enabled=False)
        self.assertEqual(legacy, "Закрывать и переоткрывать периоды может только администратор.")


# ---------------------------------------------------------------------------
# Функция «roles» выключена — всё как раньше
# ---------------------------------------------------------------------------

class RolesDisabledBehaviourTest(RolesFixture):
    """Тарифа нет — прав ровно столько, сколько было до ролей."""

    def setUp(self):
        super().setUp()
        self.mark_imported()
        self.employee = self.make_account(41)

    def test_employee_reads_billing_registry(self):
        self.assertEqual(self.get(self.employee, "/api/billing/documents").status_code, 200)
        document = BillingDocument.objects.create(
            bitrix24_account=self.admin, company_id="15", company_name="Клиент",
            period_from="2026-08-01", period_to="2026-08-31",
        )
        self.assertNotEqual(self.get(self.employee, f"/api/billing/documents/{document.pk}").status_code, 403)

    def test_employee_cannot_cancel_with_old_code(self):
        response = self.post(self.employee, "/api/billing/documents/x/cancel", {"reason": "r"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "billing_forbidden")
        self.assertFalse(response.json()["roles_enabled"])

    def test_off_plan_is_the_same_as_no_plan(self):
        self.pro(state=PortalSubscription.STATE_OFF)
        self.assertEqual(self.get(self.employee, "/api/billing/documents").status_code, 200)
        self.assertFalse(roles.resolve_access(self.employee).roles_enabled)

    def test_period_close_stays_portal_admin_only_with_old_code(self):
        self.set_role(21, roles.ROLE_ACCOUNTANT)
        accountant = self.make_account(21)
        response = self.post(accountant, "/api/periods/close", {"year": 2026, "month": 8})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "admin_required")

    def test_settings_and_rate_are_not_gated(self):
        ProjectCard.objects.create(bitrix24_account=self.employee, project_id="73", project_name="П", stage="x", hourly_rate=2000.0)
        self.assertNotEqual(self.post(self.employee, "/api/configuration/save", {"config": {}}).status_code, 403)
        self.assertNotEqual(
            self.post(self.employee, "/api/project-board/update", {"project_id": "73", "hourly_rate": 5000}).status_code,
            403,
        )

    def test_accountant_role_keeps_old_rights_without_the_plan(self):
        """«Бухгалтерия» без тарифа — прежний список: отменять счета можно."""
        self.set_role(21, roles.ROLE_ACCOUNTANT)
        accountant = self.make_account(21)
        response = self.post(accountant, "/api/billing/documents/x/cancel", {"reason": "r"})
        self.assertNotEqual(response.status_code, 403)
        self.assertTrue(roles.has_permission(accountant, roles.PERM_BILLING_ISSUE))
        self.assertTrue(roles.has_permission(accountant, roles.PERM_OPERATIONS_CREATE))

    def test_project_manager_role_is_just_an_employee_without_the_plan(self):
        self.set_role(31, roles.ROLE_PROJECT_MANAGER)
        manager = self.make_account(31)
        access = roles.resolve_access(manager)
        self.assertEqual(access.role, roles.ROLE_EMPLOYEE)
        self.assertEqual(self.post(manager, "/api/billing/documents/x/cancel", {"reason": "r"}).status_code, 403)

    def test_me_reports_disabled_mode(self):
        data = self.get(self.employee, "/api/roles/me").json()
        self.assertFalse(data["roles_enabled"])
        self.assertFalse(data["subscription_active"])
        self.assertEqual(data["assignable_roles"], [])
        self.assertEqual(data["role"], "employee")
        self.assertTrue(data["permissions"]["money_view"])
        self.assertFalse(data["permissions"]["billing_issue"])
        self.assertEqual(data["feature"]["state"], "off")


# ---------------------------------------------------------------------------
# Функция «roles» включена — гейты на сервере
# ---------------------------------------------------------------------------

class RolesEnabledGatesTest(RolesFixture):
    def setUp(self):
        super().setUp()
        self.pro()
        self.mark_imported()
        self.employee = self.make_account(41)
        self.set_role(21, roles.ROLE_ACCOUNTANT)
        self.accountant = self.make_account(21)
        self.set_role(31, roles.ROLE_PROJECT_MANAGER)
        self.manager = self.make_account(31)

    def assertDenied(self, response, code):
        self.assertEqual(response.status_code, 403, response.content)
        payload = response.json()
        self.assertEqual(payload["code"], code)
        self.assertTrue(payload["roles_enabled"])
        self.assertIn("Роли и права", payload["error"])

    # --- Сотрудник ---

    def test_employee_sees_no_money(self):
        self.assertDenied(self.get(self.employee, "/api/billing/documents"), "billing_forbidden")
        self.assertDenied(self.get(self.employee, "/api/bdds/projects"), "money_forbidden")
        self.assertDenied(self.get(self.employee, "/api/bdds/projects/73"), "money_forbidden")
        self.assertDenied(self.get(self.employee, "/api/finance-operations"), "money_forbidden")

    def test_employee_cannot_see_a_billing_card_or_its_export(self):
        document = BillingDocument.objects.create(
            bitrix24_account=self.admin, company_id="15", company_name="Клиент",
            period_from="2026-08-01", period_to="2026-08-31",
        )
        self.assertDenied(self.get(self.employee, f"/api/billing/documents/{document.pk}"), "billing_forbidden")
        self.assertDenied(self.get(self.employee, f"/api/billing/documents/{document.pk}/detail.xlsx"), "billing_forbidden")

    def test_employee_cannot_write_money(self):
        self.assertDenied(self.post(self.employee, "/api/billing/documents", {}), "billing_forbidden")
        self.assertDenied(self.post(self.employee, "/api/billing/documents/x/cancel", {"reason": "r"}), "billing_forbidden")
        self.assertDenied(self.post(self.employee, "/api/finance-operations/create", {}), "bdds_operations_forbidden")
        self.assertDenied(self.post(self.employee, "/api/periods/close", {"year": 2026, "month": 8}), "period_forbidden")
        self.assertDenied(self.post(self.employee, "/api/periods/reopen", {"year": 2026, "month": 8}), "period_forbidden")
        self.assertDenied(self.post(self.employee, "/api/configuration/save", {"config": {}}), "settings_forbidden")
        self.assertDenied(self.post(self.employee, "/api/smart-processes/create", {}), "settings_forbidden")
        self.assertDenied(self.post(self.employee, "/api/roles/assign", {"user_id": "41", "role": "admin"}), "roles_forbidden")

    def test_employee_still_works_with_hours(self):
        """Урок июня 2026: отчёты по часам под роли не попадают."""
        TimesheetItem.objects.create(
            bitrix24_account=self.employee, bitrix_id=1, task_id="1", employee_id="41", hours=1.0,
            project_id="73", date_reflection=timezone.make_aware(datetime(2026, 8, 15)),
        )
        for path in ("/api/report-employee-project", "/api/report-project-employee",
                     "/api/report-daily-workload", "/api/project-board", "/api/periods",
                     "/api/roles", "/api/roles/me"):
            with self.subTest(path=path):
                self.assertNotEqual(self.get(self.employee, path).status_code, 403)

    def test_rate_change_needs_rights_but_other_card_edits_do_not(self):
        ProjectCard.objects.create(bitrix24_account=self.employee, project_id="73", project_name="П", stage="x", hourly_rate=2000.0)

        self.assertDenied(
            self.post(self.employee, "/api/project-board/update", {"project_id": "73", "hourly_rate": 2500}),
            "rates_forbidden",
        )
        unchanged = self.post(self.employee, "/api/project-board/update", {
            "project_id": "73", "hourly_rate": "2000", "project_name": "Новое имя",
        })
        self.assertNotEqual(unchanged.status_code, 403)

    # --- Руководитель проекта ---

    def test_project_manager_sees_money_but_does_not_issue(self):
        self.assertEqual(self.get(self.manager, "/api/billing/documents").status_code, 200)
        self.assertNotEqual(self.get(self.manager, "/api/bdds/projects").status_code, 403)
        self.assertNotEqual(self.get(self.manager, "/api/finance-operations").status_code, 403)
        self.assertDenied(self.post(self.manager, "/api/billing/documents", {}), "billing_forbidden")
        self.assertDenied(self.post(self.manager, "/api/finance-operations/create", {}), "bdds_operations_forbidden")
        self.assertDenied(self.post(self.manager, "/api/periods/close", {"year": 2026, "month": 8}), "period_forbidden")

    # --- Бухгалтерия ---

    def test_accountant_does_money_and_closes_month_but_not_settings(self):
        self.assertNotEqual(self.post(self.accountant, "/api/billing/documents", {}).status_code, 403)
        self.assertNotEqual(self.post(self.accountant, "/api/finance-operations/create", {}).status_code, 403)
        self.assertNotEqual(self.post(self.accountant, "/api/periods/close", {"year": 2026, "month": 8}).status_code, 403)
        self.assertDenied(self.post(self.accountant, "/api/configuration/save", {"config": {}}), "settings_forbidden")
        self.assertDenied(self.post(self.accountant, "/api/roles/assign", {"user_id": "41", "role": "accountant"}), "roles_forbidden")

    # --- Администратор приложения (не админ портала) ---

    def test_app_admin_manages_settings_and_roles(self):
        self.set_role(41, roles.ROLE_ADMIN)
        app_admin = self.employee
        self.assertNotEqual(self.post(app_admin, "/api/configuration/save", {"config": {}}).status_code, 403)
        response = self.post(app_admin, "/api/roles/assign", {"user_id": "31", "role": "accountant"})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(PortalRole.objects.get(member_id=MEMBER, b24_user_id="31").role, "accountant")

    def test_new_role_applies_on_the_next_request(self):
        self.assertDenied(self.get(self.employee, "/api/billing/documents"), "billing_forbidden")
        self.post(self.admin, "/api/roles/assign", {"user_id": "41", "role": "project_manager"})
        self.assertEqual(self.get(self.employee, "/api/billing/documents").status_code, 200)

    def test_other_portal_roles_do_not_leak(self):
        stranger = self.make_account(41, member_id="m-other")
        set_account_plan(stranger)
        self.set_role(41, roles.ROLE_ADMIN)  # роль на НАШЕМ портале, не на чужом

        access = roles.resolve_access(stranger)

        self.assertTrue(access.roles_enabled)
        self.assertEqual(access.role, roles.ROLE_EMPLOYEE)


# ---------------------------------------------------------------------------
# Подписка закончилась — роли продолжают действовать
# ---------------------------------------------------------------------------

class ExpiredSubscriptionKeepsRolesTest(RolesFixture):
    """Окончание Pro не должно разом открыть всем ставки и деньги."""

    def setUp(self):
        super().setUp()
        self.mark_imported()
        self.pro()
        self.employee = self.make_account(41)
        self.set_role(21, roles.ROLE_ACCOUNTANT)
        self.accountant = self.make_account(21)

    def expire(self):
        """Пробный Pro, закончившийся вчера, — «только чтение»."""
        self.pro(state=PortalSubscription.STATE_TRIAL, trial_until=timezone.localdate() - timedelta(days=2))

    def test_employee_without_role_still_sees_no_rates_or_money_after_expiry(self):
        self.assertEqual(self.get(self.employee, "/api/billing/documents").status_code, 403)
        self.expire()

        for path in ("/api/billing/documents", "/api/bdds/projects", "/api/finance-operations"):
            with self.subTest(path=path):
                response = self.get(self.employee, path)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["code"], "billing_forbidden" if "billing" in path else "money_forbidden")
                self.assertTrue(response.json()["roles_enabled"])

        ProjectCard.objects.create(bitrix24_account=self.employee, project_id="73", project_name="П", stage="x", hourly_rate=2000.0)
        rate = self.post(self.employee, "/api/project-board/update", {"project_id": "73", "hourly_rate": 1})
        self.assertEqual(rate.status_code, 403)
        self.assertEqual(rate.json()["code"], "rates_forbidden")

        me = self.get(self.employee, "/api/roles/me").json()
        self.assertTrue(me["roles_enabled"])
        self.assertFalse(me["subscription_active"])
        self.assertFalse(me["permissions"]["money_view"])

    def test_explicitly_expired_plan_keeps_restrictions_too(self):
        self.pro(state=PortalSubscription.STATE_EXPIRED)
        self.assertEqual(self.get(self.employee, "/api/billing/documents").status_code, 403)

    def test_assigned_roles_keep_working_after_expiry(self):
        self.expire()
        self.assertEqual(self.get(self.accountant, "/api/billing/documents").status_code, 200)
        self.assertNotEqual(self.post(self.accountant, "/api/periods/close", {"year": 2026, "month": 8}).status_code, 403)
        self.assertNotEqual(self.get(self.employee, "/api/report-employee-project").status_code, 403)

    def test_changing_roles_is_closed_until_renewal(self):
        self.expire()

        for role in ("accountant", "employee", "project_manager"):
            with self.subTest(role=role):
                response = self.post(self.admin, "/api/roles/assign", {"user_id": "21", "role": role})
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["code"], "feature_disabled")
                self.assertEqual(response.json()["feature"], "roles")
        self.assertEqual(PortalRole.objects.get(member_id=MEMBER, b24_user_id="21").role, "accountant")

        data = self.get(self.admin, "/api/roles").json()
        self.assertEqual(data["assignable_roles"], [])
        self.assertTrue(data["roles_enabled"])

    def test_renewal_opens_changes_again(self):
        self.expire()
        self.pro()

        response = self.post(self.admin, "/api/roles/assign", {"user_id": "41", "role": "project_manager"})
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# Назначение ролей
# ---------------------------------------------------------------------------

class RoleAssignmentEndpointTest(RolesFixture):
    def setUp(self):
        super().setUp()
        self.mark_imported()
        self.pro()

    def test_without_plan_roles_do_not_change(self):
        self.pro(state=PortalSubscription.STATE_OFF)
        response = self.post(self.admin, "/api/roles/assign", {"user_id": "21", "role": "accountant"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "feature_disabled")
        self.assertEqual(response.json()["feature"], "roles")
        self.assertFalse(PortalRole.objects.filter(b24_user_id="21").exists())

    def test_admin_assigns_a_role(self):
        ok = self.post(self.admin, "/api/roles/assign", {"user_id": "21", "role": "accountant"})
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(ok.json()["role_title"], "Бухгалтерия")
        self.assertEqual(PortalRole.objects.get(member_id=MEMBER, b24_user_id="21").role, "accountant")

    def test_non_admin_cannot_assign(self):
        self.set_role(21, roles.ROLE_ACCOUNTANT)
        response = self.post(self.make_account(21), "/api/roles/assign", {"user_id": "21", "role": "admin"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "roles_forbidden")

    def test_employee_role_removes_the_row(self):
        self.set_role(21, roles.ROLE_ACCOUNTANT)
        response = self.post(self.admin, "/api/roles/assign", {"user_id": "21", "role": "employee"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PortalRole.objects.filter(member_id=MEMBER, b24_user_id="21").exists())

    def test_bad_input(self):
        self.assertEqual(self.post(self.admin, "/api/roles/assign", {"user_id": "21", "role": "boss"}).json()["code"], "unknown_role")
        self.assertEqual(self.post(self.admin, "/api/roles/assign", {"user_id": "abc", "role": "accountant"}).json()["code"], "user_required")

    def test_portal_admin_role_is_fixed(self):
        response = self.post(self.admin, "/api/roles/assign", {"user_id": "1", "role": "accountant"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "portal_admin_role_fixed")

    def test_list_shows_catalog_and_named_assignments(self):
        self.set_role(21, roles.ROLE_ACCOUNTANT)
        data = self.get(self.admin, "/api/roles").json()
        self.assertTrue(data["can_manage"])
        self.assertTrue(data["roles_enabled"])
        self.assertEqual(len(data["assignable_roles"]), 4)
        self.assertEqual(len(data["catalog"]["roles"]), 4)
        rows = {row["user_id"]: row for row in data["assignments"]}
        self.assertTrue(rows["1"]["is_portal_admin"])
        self.assertEqual(rows["21"]["role"], "accountant")
        self.assertEqual(rows["21"]["name"], "Бухова Анна")

    def test_users_search(self):
        data = self.get(self.admin, "/api/users?search=Бухова").json()
        self.assertEqual([item["id"] for item in data["items"]], ["21"])
        by_id = self.get(self.admin, "/api/users?search=31").json()
        self.assertEqual([item["id"] for item in by_id["items"]], ["31"])


# ---------------------------------------------------------------------------
# Перенос прежнего списка «Бухгалтерия»
# ---------------------------------------------------------------------------

class AccountantsImportTest(RolesFixture):
    def setUp(self):
        super().setUp()
        self.pro()
        self.portal.config = {"billing_accountants": ["21", 22, " 21 ", None, ""]}
        self.accountant = self.make_account(21)

    def test_first_permission_check_imports_the_list(self):
        self.assertNotEqual(self.post(self.accountant, "/api/billing/documents", {}).status_code, 403)

        marker = PortalRoleState.objects.get(member_id=MEMBER)
        self.assertIsNotNone(marker.accountants_imported_at)
        self.assertEqual(marker.imported_user_ids, ["21", "22"])
        rows = {row.b24_user_id: row for row in PortalRole.objects.filter(member_id=MEMBER)}
        self.assertEqual(set(rows), {"21", "22"})
        self.assertEqual(rows["21"].role, "accountant")
        self.assertEqual(rows["21"].source, "billing_accountants")

    def test_after_import_the_config_list_is_not_trusted(self):
        """Дописать себя в app.option из консоли браузера больше ничего не даёт."""
        roles.ensure_accountants_imported(self.accountant)
        self.portal.config = {"billing_accountants": ["21", "41"]}
        intruder = self.make_account(41)

        self.assertEqual(self.post(intruder, "/api/billing/documents", {}).status_code, 403)
        self.assertFalse(PortalRole.objects.filter(b24_user_id="41").exists())

    def test_unreachable_portal_does_not_wipe_accountants(self):
        self.portal.fail_options = True
        with patch("main.billing_settings.load_billing_settings",
                   side_effect=lambda account, client=None: {"accountants": ["21"]}):
            access = roles.resolve_access(self.accountant)

        self.assertEqual(access.role, roles.ROLE_ACCOUNTANT, "пока перенос не удался — прежний список")
        self.assertFalse(PortalRoleState.objects.filter(accountants_imported_at__isnull=False).exists())

        cache.clear()
        self.portal.fail_options = False
        self.assertTrue(roles.ensure_accountants_imported(self.accountant))
        self.assertTrue(PortalRole.objects.filter(b24_user_id="21", role="accountant").exists())

    def test_import_does_not_override_manual_roles(self):
        self.set_role(21, roles.ROLE_ADMIN)
        roles.ensure_accountants_imported(self.accountant)
        self.assertEqual(PortalRole.objects.get(member_id=MEMBER, b24_user_id="21").role, "admin")
        self.assertEqual(PortalRole.objects.get(member_id=MEMBER, b24_user_id="22").role, "accountant")

    def test_import_runs_once(self):
        roles.ensure_accountants_imported(self.accountant)
        calls = self.portal.calls.count("app.option.get")
        roles.ensure_accountants_imported(self.accountant)
        self.assertEqual(self.portal.calls.count("app.option.get"), calls)

    def test_roles_screen_triggers_import_for_the_portal_admin(self):
        data = self.get(self.admin, "/api/roles").json()
        self.assertTrue(data["accountants_imported"])
        self.assertEqual({row["user_id"] for row in data["assignments"] if row["role"] == "accountant"}, {"21", "22"})

    def test_first_assignment_imports_before_writing(self):
        response = self.post(self.admin, "/api/roles/assign", {"user_id": "31", "role": "accountant"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(PortalRole.objects.filter(member_id=MEMBER).values_list("b24_user_id", flat=True)),
            {"21", "22", "31"},
        )
