"""Редактируемые права ролей: матрица портала, ограничения, зависимости, тариф, журнал.

Что закреплено и почему.

1. Портал, который права не трогал, живёт по прежней матрице из кода — после
   миграции у действующих порталов не меняется ничего.
2. Изменённое право реально открывает и закрывает ручки на сервере, и сразу:
   кэш матрицы сбрасывается при сохранении.
3. У «Администратора» не снимаются «менять настройки» и «назначать роли», а
   «назначать роли» нельзя дать другой роли: иначе портал запер бы сам себя или
   любая роль назначила бы себе всё.
4. Зависимое право без базового не сохраняется, а сохранённое по старым
   правилам — снимается при чтении.
5. Работа с часами правами не закрывается никаким набором прав (урок июня 2026).
6. Менять матрицу можно только при живом Pro; сохранённая матрица действует и
   после его окончания.
7. Каждое изменение — строка журнала: кто, когда, какие ячейки.
"""

from datetime import datetime, timedelta

from django.core.cache import cache
from django.utils import timezone

from . import roles
from .models import PortalPermissionChange, PortalPermissionMatrix, PortalSubscription, TimesheetItem
from .tests_roles import MEMBER, RolesFixture

#: Матрица до того, как права стали редактируемыми (PR #40). Копия, а не
#: ссылка на roles.ROLE_PERMISSIONS: тест должен упасть, если её поменяют.
PREVIOUS_MATRIX = {
    "admin": {
        "money_view", "rates_edit", "billing_issue", "billing_cancel",
        "operations_create", "period_close", "settings_manage", "roles_manage",
    },
    "accountant": {
        "money_view", "rates_edit", "billing_issue", "billing_cancel",
        "operations_create", "period_close",
    },
    "project_manager": {"money_view"},
    "employee": set(),
}

HOURS_PATHS = (
    "/api/report-employee-project",
    "/api/report-project-employee",
    "/api/report-daily-workload",
    "/api/project-board",
    "/api/periods",
    "/api/roles",
    "/api/roles/me",
)


def as_payload(matrix):
    return {role: sorted(perms) for role, perms in matrix.items()}


def minimal_matrix():
    """Наименьший допустимый набор прав: только неизменяемые ячейки."""
    return {
        "admin": ["settings_manage", "roles_manage"],
        "accountant": [],
        "project_manager": [],
        "employee": [],
    }


class MatrixFixture(RolesFixture):
    def setUp(self):
        super().setUp()
        # Матрица кэшируется по member_id, а LocMemCache переживает откат БД
        # между тестами: без чистки после теста чужая матрица «протекла» бы.
        self.addCleanup(cache.clear)
        self.mark_imported()
        self.pro()
        self.employee = self.make_account(41)
        self.set_role(21, roles.ROLE_ACCOUNTANT)
        self.accountant = self.make_account(21)
        self.set_role(31, roles.ROLE_PROJECT_MANAGER)
        self.manager = self.make_account(31)

    def matrix_with(self, **changes):
        matrix = as_payload(roles.default_matrix())
        for role, perms in changes.items():
            matrix[role] = sorted(perms)
        return matrix

    def save(self, account, matrix, revision=None):
        body = {"matrix": matrix}
        if revision is not None:
            body["revision"] = revision
        return self.post(account, "/api/roles/matrix", body)

    def revision(self):
        return self.get(self.admin, "/api/roles").json()["catalog"]["revision"]


# ---------------------------------------------------------------------------
# По умолчанию — прежняя матрица
# ---------------------------------------------------------------------------

class DefaultMatrixTest(MatrixFixture):
    def test_default_matrix_is_the_previous_one(self):
        self.assertEqual({role: set(perms) for role, perms in roles.default_matrix().items()}, PREVIOUS_MATRIX)
        self.assertEqual({role: set(perms) for role, perms in roles.apply_overrides(None).items()}, PREVIOUS_MATRIX)

    def test_default_matrix_already_satisfies_the_rules(self):
        roles.validate_permission_matrix(as_payload(roles.default_matrix()))
        self.assertEqual(roles.enforce_matrix_rules(roles.ROLE_PERMISSIONS), roles.default_matrix())

    def test_portal_without_saved_matrix_uses_defaults(self):
        self.assertFalse(PortalPermissionMatrix.objects.exists())
        self.assertEqual(roles.permission_matrix(self.employee), roles.default_matrix())
        catalog = self.get(self.admin, "/api/roles").json()["catalog"]
        self.assertEqual({role: set(perms) for role, perms in catalog["matrix"].items()}, PREVIOUS_MATRIX)
        self.assertEqual(catalog["matrix"], catalog["default_matrix"])
        self.assertEqual(catalog["revision"], 0)
        self.assertFalse(any(role["customized"] for role in catalog["roles"]))

    def test_catalog_describes_every_permission_and_groups(self):
        catalog = roles.roles_catalog()
        grouped = [perm for group in catalog["groups"] for perm in group["permissions"]]
        self.assertEqual(grouped, list(roles.PERMISSIONS))
        for row in catalog["permissions"]:
            self.assertTrue(row["description"], row["code"])
            self.assertTrue(row["group"], row["code"])
        self.assertEqual(
            {(lock["role"], lock["permission"]) for lock in catalog["locks"]},
            set(roles.LOCKED_CELLS),
        )

    def test_effective_rights_did_not_change(self):
        self.assertEqual(roles.resolve_access(self.accountant).permissions, PREVIOUS_MATRIX["accountant"])
        self.assertEqual(roles.resolve_access(self.manager).permissions, PREVIOUS_MATRIX["project_manager"])
        self.assertEqual(roles.resolve_access(self.employee).permissions, frozenset())
        self.assertEqual(roles.resolve_access(self.admin).permissions, roles.ALL_PERMISSIONS)


# ---------------------------------------------------------------------------
# Изменённое право открывает и закрывает ручки
# ---------------------------------------------------------------------------

class MatrixAppliesOnServerTest(MatrixFixture):
    def test_granting_money_view_opens_money_for_employees(self):
        self.assertEqual(self.get(self.employee, "/api/billing/documents").status_code, 403)

        response = self.save(self.admin, self.matrix_with(employee={"money_view"}), revision=0)
        self.assertEqual(response.status_code, 200, response.content)

        self.assertEqual(self.get(self.employee, "/api/billing/documents").status_code, 200)
        self.assertNotEqual(self.get(self.employee, "/api/finance-operations").status_code, 403)
        self.assertEqual(self.post(self.employee, "/api/billing/documents", {}).status_code, 403)

    def test_revoking_period_close_closes_it_for_accountants(self):
        self.assertNotEqual(self.post(self.accountant, "/api/periods/close", {"year": 2026, "month": 8}).status_code, 403)

        accountant = PREVIOUS_MATRIX["accountant"] - {"period_close"}
        self.assertEqual(self.save(self.admin, self.matrix_with(accountant=accountant)).status_code, 200)

        response = self.post(self.accountant, "/api/periods/close", {"year": 2026, "month": 8})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "period_forbidden")
        self.assertEqual(response.json()["allowed_roles"], ["admin"])
        self.assertNotIn("«Бухгалтерия»", response.json()["error"])

    def test_project_manager_can_be_allowed_to_issue_invoices(self):
        self.assertEqual(self.post(self.manager, "/api/billing/documents", {}).status_code, 403)
        matrix = self.matrix_with(project_manager={"money_view", "billing_issue"})
        self.assertEqual(self.save(self.admin, matrix).status_code, 200)
        self.assertNotEqual(self.post(self.manager, "/api/billing/documents", {}).status_code, 403)

    def test_settings_can_be_given_to_accountants(self):
        self.assertEqual(self.post(self.accountant, "/api/configuration/save", {"config": {}}).status_code, 403)
        matrix = self.matrix_with(accountant=PREVIOUS_MATRIX["accountant"] | {"settings_manage"})
        self.assertEqual(self.save(self.admin, matrix).status_code, 200)
        self.assertNotEqual(self.post(self.accountant, "/api/configuration/save", {"config": {}}).status_code, 403)

    def test_rate_change_follows_the_matrix(self):
        from .models import ProjectCard

        ProjectCard.objects.create(bitrix24_account=self.employee, project_id="73", project_name="П", stage="x", hourly_rate=2000.0)
        body = {"project_id": "73", "hourly_rate": 2500}
        self.assertEqual(self.post(self.employee, "/api/project-board/update", body).status_code, 403)
        self.save(self.admin, self.matrix_with(employee={"money_view", "rates_edit"}))
        self.assertNotEqual(self.post(self.employee, "/api/project-board/update", body).status_code, 403)

    def test_cache_is_dropped_on_save(self):
        """Матрица прочитана и закэширована — сохранение действует на следующий же запрос."""
        roles.permission_matrix(self.employee)
        self.assertIsNotNone(cache.get(roles.matrix_cache_key(self.employee)))
        self.assertEqual(self.get(self.manager, "/api/billing/documents").status_code, 200)

        self.save(self.admin, self.matrix_with(project_manager=set()))

        self.assertEqual(self.get(self.manager, "/api/billing/documents").status_code, 403)
        self.assertEqual(roles.permission_matrix(self.manager)["project_manager"], frozenset())

    def test_portal_admin_gets_the_admin_column(self):
        admin = PREVIOUS_MATRIX["admin"] - {"money_view", "rates_edit", "billing_issue", "billing_cancel", "operations_create"}
        self.assertEqual(self.save(self.admin, self.matrix_with(admin=admin)).status_code, 200)

        roles.forget_access(self.admin)
        access = roles.resolve_access(self.admin)
        self.assertEqual(access.role, roles.ROLE_ADMIN)
        self.assertEqual(access.permissions, admin)
        self.assertEqual(self.get(self.admin, "/api/billing/documents").status_code, 403)
        # Настройки и роли у него остались — он может вернуть права.
        self.assertTrue(access.has("settings_manage") and access.has("roles_manage"))

    def test_other_portal_matrix_does_not_leak(self):
        self.save(self.admin, self.matrix_with(employee={"money_view"}))
        stranger = self.make_account(41, member_id="m-other")
        from .pro_plan_service import set_account_plan

        set_account_plan(stranger)
        self.assertEqual(roles.permission_matrix(stranger), roles.default_matrix())
        self.assertFalse(roles.resolve_access(stranger).has("money_view"))

    def test_matrix_is_ignored_without_the_plan(self):
        """Без Pro — прежние права, что бы ни было сохранено."""
        self.save(self.admin, self.matrix_with(employee=set(), accountant=set()))
        self.pro(state=PortalSubscription.STATE_OFF)
        self.assertEqual(self.get(self.employee, "/api/billing/documents").status_code, 200)
        self.assertTrue(roles.has_permission(self.accountant, "billing_issue"))


# ---------------------------------------------------------------------------
# Неизменяемые ограничения
# ---------------------------------------------------------------------------

class LockedCellsTest(MatrixFixture):
    def assertRejected(self, matrix, code):
        response = self.save(self.admin, matrix)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["code"], code)
        self.assertFalse(PortalPermissionMatrix.objects.filter(revision__gt=0).exists())
        self.assertFalse(PortalPermissionChange.objects.exists())
        return response.json()

    def test_admin_keeps_settings(self):
        data = self.assertRejected(self.matrix_with(admin=PREVIOUS_MATRIX["admin"] - {"settings_manage"}), "permission_locked")
        self.assertEqual(data["permission"], "settings_manage")
        self.assertIn("Администратор", data["error"])

    def test_admin_keeps_roles(self):
        data = self.assertRejected(self.matrix_with(admin=PREVIOUS_MATRIX["admin"] - {"roles_manage"}), "permission_locked")
        self.assertEqual(data["permission"], "roles_manage")

    def test_roles_manage_only_for_admin(self):
        for role in ("accountant", "project_manager", "employee"):
            with self.subTest(role=role):
                matrix = self.matrix_with(**{role: set(self.matrix_with()[role]) | {"roles_manage"}})
                self.assertRejected(matrix, "permission_locked")

    def test_validator_rejects_locks_directly(self):
        matrix = minimal_matrix()
        matrix["admin"] = []
        with self.assertRaises(roles.PermissionMatrixError) as caught:
            roles.validate_permission_matrix(matrix)
        self.assertEqual(caught.exception.code, "permission_locked")

    def test_stored_garbage_cannot_strip_the_admin(self):
        """Даже если в БД окажется снятое право — при чтении оно возвращается."""
        PortalPermissionMatrix.objects.create(
            member_id=MEMBER, revision=1,
            overrides={"admin": {"settings_manage": False, "roles_manage": False}, "employee": {"roles_manage": True}},
        )
        matrix = roles.permission_matrix(self.employee)
        self.assertIn("settings_manage", matrix["admin"])
        self.assertIn("roles_manage", matrix["admin"])
        self.assertNotIn("roles_manage", matrix["employee"])

    def test_portal_admin_role_is_still_fixed(self):
        response = self.post(self.admin, "/api/roles/assign", {"user_id": "1", "role": "employee"})
        self.assertEqual(response.json()["code"], "portal_admin_role_fixed")

    def test_minimal_matrix_is_allowed(self):
        response = self.save(self.admin, minimal_matrix())
        self.assertEqual(response.status_code, 200, response.content)
        roles.forget_access(self.admin)
        self.assertEqual(
            roles.resolve_access(self.admin).permissions,
            {"settings_manage", "roles_manage"},
        )

    def test_bad_payloads(self):
        self.assertRejected({"admin": ["settings_manage", "roles_manage"]}, "matrix_incomplete")
        self.assertRejected({**minimal_matrix(), "boss": []}, "unknown_role")
        self.assertRejected({**minimal_matrix(), "employee": "money_view"}, "matrix_invalid")
        self.assertEqual(self.post(self.admin, "/api/roles/matrix", {}).json()["code"], "matrix_required")


# ---------------------------------------------------------------------------
# Зависимости прав
# ---------------------------------------------------------------------------

class PermissionDependenciesTest(MatrixFixture):
    def test_dependent_rights_need_money_view(self):
        for perm in ("billing_issue", "billing_cancel", "operations_create", "rates_edit"):
            with self.subTest(permission=perm):
                response = self.save(self.admin, self.matrix_with(employee={perm}))
                self.assertEqual(response.status_code, 400, response.content)
                data = response.json()
                self.assertEqual(data["code"], "permission_dependency")
                self.assertEqual(data["requires"], "money_view")
                self.assertIn("Видеть суммы", data["error"])
        self.assertFalse(PortalPermissionChange.objects.exists())

    def test_revoking_money_view_with_dependents_left_is_rejected(self):
        accountant = PREVIOUS_MATRIX["accountant"] - {"money_view"}
        response = self.save(self.admin, self.matrix_with(accountant=accountant))
        self.assertEqual(response.json()["code"], "permission_dependency")

    def test_dependencies_are_declared_for_the_screen(self):
        catalog = {row["code"]: row for row in roles.roles_catalog()["permissions"]}
        self.assertEqual(catalog["billing_issue"]["requires"], ["money_view"])
        self.assertEqual(catalog["billing_cancel"]["requires"], ["money_view"])
        self.assertTrue(catalog["billing_cancel"]["requires_reason"])
        self.assertEqual(catalog["money_view"]["requires"], [])

    def test_stored_dependent_without_base_is_dropped_on_read(self):
        PortalPermissionMatrix.objects.create(
            member_id=MEMBER, revision=1,
            overrides={"accountant": {"money_view": False}},
        )
        matrix = roles.permission_matrix(self.accountant)
        self.assertEqual(matrix["accountant"], {"period_close"})
        self.assertEqual(self.post(self.accountant, "/api/billing/documents", {}).status_code, 403)


# ---------------------------------------------------------------------------
# Работа с часами — вне прав
# ---------------------------------------------------------------------------

class HoursStayOpenTest(MatrixFixture):
    def test_permissions_do_not_describe_hours(self):
        self.assertEqual(set(roles.PERMISSIONS), set(PREVIOUS_MATRIX["admin"]))
        self.assertTrue(roles.ALWAYS_OPEN_WORK)

    def test_unknown_hours_permission_cannot_be_saved(self):
        matrix = minimal_matrix()
        matrix["employee"] = ["reports_view"]
        response = self.save(self.admin, matrix)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "unknown_permission")
        self.assertIn("часами", response.json()["error"])

    def test_no_set_of_rights_closes_hours(self):
        TimesheetItem.objects.create(
            bitrix24_account=self.employee, bitrix_id=1, task_id="1", employee_id="41", hours=1.0,
            project_id="73", date_reflection=timezone.make_aware(datetime(2026, 8, 15)),
        )
        full = {role: sorted(roles.ALL_PERMISSIONS - ({"roles_manage"} if role != "admin" else set()))
                for role in roles.ROLES}
        for label, matrix in (("минимальный", minimal_matrix()), ("полный", full)):
            self.assertEqual(self.save(self.admin, matrix).status_code, 200, label)
            for account in (self.employee, self.accountant, self.manager, self.admin):
                for path in HOURS_PATHS:
                    with self.subTest(matrix=label, user=account.b24_user_id, path=path):
                        self.assertNotEqual(self.get(account, path).status_code, 403)


# ---------------------------------------------------------------------------
# Кто и когда может менять
# ---------------------------------------------------------------------------

class MatrixEditAccessTest(MatrixFixture):
    def expire(self):
        self.pro(state=PortalSubscription.STATE_TRIAL, trial_until=timezone.localdate() - timedelta(days=2))

    def test_only_roles_manage_edits(self):
        for account in (self.accountant, self.manager, self.employee):
            with self.subTest(user=account.b24_user_id):
                response = self.save(account, self.matrix_with(employee={"money_view"}))
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["code"], "roles_forbidden")
        self.assertFalse(PortalPermissionChange.objects.exists())

    def test_app_admin_who_is_not_portal_admin_edits(self):
        self.set_role(41, roles.ROLE_ADMIN)
        response = self.save(self.employee, self.matrix_with(project_manager=set()))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(PortalPermissionChange.objects.get().changed_by_id, "41")

    def test_editing_is_closed_after_expiry_but_matrix_keeps_working(self):
        self.save(self.admin, self.matrix_with(employee={"money_view"}))
        self.expire()

        response = self.save(self.admin, self.matrix_with(employee=set()))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "feature_disabled")
        self.assertEqual(response.json()["feature"], "roles")

        self.assertEqual(self.get(self.employee, "/api/billing/documents").status_code, 200)
        self.assertEqual(self.get(self.manager, "/api/billing/documents").status_code, 200)
        data = self.get(self.admin, "/api/roles").json()
        self.assertFalse(data["can_edit_matrix"])
        self.assertTrue(data["can_manage"])
        self.assertEqual(data["catalog"]["matrix"]["employee"], ["money_view"])

    def test_editing_is_closed_without_the_plan(self):
        self.pro(state=PortalSubscription.STATE_OFF)
        response = self.save(self.admin, self.matrix_with(employee={"money_view"}))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "feature_disabled")
        self.assertFalse(PortalPermissionMatrix.objects.exists())

    def test_renewal_opens_editing_again(self):
        self.expire()
        self.pro()
        self.assertEqual(self.save(self.admin, self.matrix_with(employee={"money_view"})).status_code, 200)
        self.assertTrue(self.get(self.admin, "/api/roles").json()["can_edit_matrix"])

    def test_stale_revision_is_a_conflict(self):
        self.assertEqual(self.save(self.admin, self.matrix_with(employee={"money_view"}), revision=0).status_code, 200)
        response = self.save(self.admin, self.matrix_with(project_manager=set()), revision=0)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "matrix_conflict")
        self.assertEqual(response.json()["revision"], 1)
        self.assertEqual(roles.permission_matrix(self.manager)["project_manager"], {"money_view"})


# ---------------------------------------------------------------------------
# Журнал
# ---------------------------------------------------------------------------

class MatrixLogTest(MatrixFixture):
    def test_save_writes_who_when_and_what(self):
        response = self.save(self.admin, self.matrix_with(employee={"money_view"}), revision=0)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["revision"], 1)
        self.assertEqual(data["changes"], [{"role": "employee", "permission": "money_view", "granted": True}])

        entry = PortalPermissionChange.objects.get()
        self.assertEqual(entry.member_id, MEMBER)
        self.assertEqual(entry.changed_by_id, "1")
        self.assertEqual(entry.changed_by_name, "Цыганков Егор")
        self.assertEqual(entry.matrix["employee"], ["money_view"])
        self.assertIsNotNone(entry.created_at)

        stored = PortalPermissionMatrix.objects.get(member_id=MEMBER)
        self.assertEqual(stored.overrides, {"employee": {"money_view": True}})
        self.assertEqual(stored.updated_by_name, "Цыганков Егор")

    def test_log_is_returned_newest_first_with_titles(self):
        self.save(self.admin, self.matrix_with(employee={"money_view"}), revision=0)
        self.save(self.admin, self.matrix_with(employee={"money_view"}, project_manager=set()), revision=1)

        data = self.get(self.admin, "/api/roles").json()
        log = data["matrix_log"]
        self.assertEqual([row["revision"] for row in log], [2, 1])
        self.assertEqual(log[0]["changed_by_name"], "Цыганков Егор")
        self.assertEqual(log[0]["changes"][0]["role_title"], "Руководитель проекта")
        self.assertFalse(log[0]["changes"][0]["granted"])
        self.assertTrue(log[0]["changes"][0]["permission_title"].startswith("Видеть суммы"))
        self.assertTrue(data["catalog"]["roles"][2]["customized"])
        self.assertEqual(data["catalog"]["updated_by_name"], "Цыганков Егор")

    def test_unchanged_save_writes_nothing(self):
        response = self.save(self.admin, as_payload(roles.default_matrix()))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "unchanged")
        self.assertFalse(PortalPermissionChange.objects.exists())

    def test_reset_to_defaults_is_logged_and_clears_overrides(self):
        self.save(self.admin, self.matrix_with(employee={"money_view"}, accountant={"money_view"}))
        response = self.save(self.admin, as_payload(roles.default_matrix()))
        self.assertEqual(response.json()["status"], "ok")

        self.assertEqual(PortalPermissionMatrix.objects.get(member_id=MEMBER).overrides, {})
        latest = self.get(self.admin, "/api/roles").json()["matrix_log"][0]
        self.assertTrue(latest["reset_to_default"])
        self.assertEqual(roles.permission_matrix(self.employee), roles.default_matrix())

    def test_rejected_save_is_not_logged(self):
        self.save(self.admin, self.matrix_with(employee={"billing_issue"}))
        self.save(self.accountant, self.matrix_with(employee={"money_view"}))
        self.assertFalse(PortalPermissionChange.objects.exists())
