"""Тариф Pro портала: правило срока, портальность, перенос старых строк, команда.

Что закрепляется:
- тариф висит на ПОРТАЛЕ (member_id), а не на учётке: сотрудник, впервые
  открывший приложение после включения, получает функции без команды;
- неоплата гасится сама: paid_until + 7 дней грейса, затем «только чтение»;
- пробный период после срока — сразу «только чтение», без грейса;
- /api/features отвечает прежней формой (state/trial_until/enabled по коду);
- команда pro_plan: enable, extend, trial, expire, off, list, show;
- миграция сворачивает прежние PortalFeature в тариф по member_id.
"""

import json
from datetime import date, datetime, timedelta, timezone as dt_timezone
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, TransactionTestCase

from . import pro_plan_service as service
from .billing_features import (
    ACCESS_FULL,
    ACCESS_NONE,
    ACCESS_READ_ONLY,
    GRACE_DAYS,
    KNOWN_FEATURES,
    feature_access,
    feature_enabled,
    feature_required,
    feature_restrictions_active,
    feature_states,
    resolve_subscription,
    subscription_today,
)
from .models import Bitrix24Account, Portal, PortalSubscription, PortalSubscriptionEvent
from .pro_plan_migration import merge_legacy_rows

TODAY = date(2026, 9, 12)


def plan(state, paid_until=None, trial_until=None):
    return PortalSubscription(state=state, paid_until=paid_until, trial_until=trial_until)


def make_account(member_id="m-pro", domain="pro.bitrix24.ru", user_id=11, **extra):
    defaults = dict(is_b24_user_admin=True, is_master_account=True, status="active", application_version=1)
    defaults.update(extra)
    return Bitrix24Account.objects.create(
        b24_user_id=user_id, member_id=member_id, domain_url=domain, **defaults,
    )


class SubscriptionRuleTest(SimpleTestCase):
    """Чистое правило на границах дат."""

    def test_no_subscription_is_off(self):
        status = resolve_subscription(None, TODAY)
        self.assertEqual((status.status, status.access), ("off", ACCESS_NONE))

    def test_active_until_paid_date_inclusive(self):
        status = resolve_subscription(plan("active", paid_until=TODAY), TODAY)
        self.assertEqual((status.status, status.access), ("active", ACCESS_FULL))
        self.assertEqual(status.grace_until, TODAY + timedelta(days=GRACE_DAYS))

    def test_grace_keeps_everything_working_for_seven_days(self):
        self.assertEqual(GRACE_DAYS, 7)
        paid = TODAY - timedelta(days=1)
        for day in (TODAY, paid + timedelta(days=7)):
            with self.subTest(day=day):
                status = resolve_subscription(plan("active", paid_until=paid), day)
                self.assertEqual((status.status, status.access), ("grace", ACCESS_FULL))

    def test_after_grace_only_reading_remains(self):
        paid = TODAY - timedelta(days=8)
        status = resolve_subscription(plan("active", paid_until=paid), TODAY)
        self.assertEqual((status.status, status.access), ("expired", ACCESS_READ_ONLY))
        self.assertTrue(status.can_read)
        self.assertFalse(status.can_write)

    def test_active_without_date_is_unlimited(self):
        status = resolve_subscription(plan("active"), date(2099, 1, 1))
        self.assertEqual(status.access, ACCESS_FULL)

    def test_trial_has_no_grace(self):
        self.assertEqual(resolve_subscription(plan("trial", trial_until=TODAY), TODAY).access, ACCESS_FULL)
        after = resolve_subscription(plan("trial", trial_until=TODAY), TODAY + timedelta(days=1))
        self.assertEqual((after.status, after.access), ("expired", ACCESS_READ_ONLY))

    def test_open_trial_is_unlimited(self):
        self.assertEqual(resolve_subscription(plan("trial"), TODAY).status, "trial")

    def test_manual_expire_and_off(self):
        self.assertEqual(resolve_subscription(plan("expired", paid_until=TODAY + timedelta(days=30)), TODAY).access,
                         ACCESS_READ_ONLY)
        self.assertEqual(resolve_subscription(plan("off", paid_until=TODAY + timedelta(days=30)), TODAY).access,
                         ACCESS_NONE)

    def test_unknown_state_is_strict(self):
        self.assertEqual(resolve_subscription(plan("magic"), TODAY).access, ACCESS_NONE)

    def test_day_is_counted_in_moscow(self):
        # 22:30 UTC 12.09 — в Москве уже 13.09.
        self.assertEqual(subscription_today(datetime(2026, 9, 12, 22, 30, tzinfo=dt_timezone.utc)), date(2026, 9, 13))

    def test_add_months_keeps_month_end(self):
        self.assertEqual(service.add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(service.add_months(date(2026, 11, 30), 1), date(2026, 12, 31))
        self.assertEqual(service.add_months(date(2026, 9, 12), 12), date(2027, 9, 12))


class PortalWideSubscriptionTest(TestCase):
    def test_colleague_created_after_enabling_gets_the_plan(self):
        admin = make_account()
        service.enable(service.resolve_portal(member_id="m-pro"), months=1, actor="t", today=subscription_today())

        newcomer = make_account(user_id=77, is_b24_user_admin=False, is_master_account=False)

        for code in KNOWN_FEATURES:
            with self.subTest(code=code):
                self.assertEqual(feature_access(admin, code), ACCESS_FULL)
                self.assertEqual(feature_access(newcomer, code), ACCESS_FULL)

    def test_other_portal_is_untouched(self):
        make_account()
        stranger = make_account(member_id="m-other", domain="other.bitrix24.ru", user_id=1)
        service.enable(service.resolve_portal(member_id="m-pro"), months=1, actor="t")

        self.assertEqual(feature_access(stranger, "bdds"), ACCESS_NONE)

    def test_domain_change_does_not_lose_the_plan(self):
        account = make_account()
        service.enable(service.resolve_portal(domain="pro.bitrix24.ru"), months=1, actor="t")
        Bitrix24Account.objects.filter(pk=account.pk).update(domain_url="renamed.bitrix24.ru")
        account.refresh_from_db()

        self.assertEqual(feature_access(account, "billing"), ACCESS_FULL)
        self.assertEqual(service.resolve_portal(domain="renamed.bitrix24.ru").member_id, "m-pro")

    def test_features_payload_keeps_the_old_shape(self):
        account = make_account()
        today = subscription_today()
        service.trial(service.resolve_portal(member_id="m-pro"), days=14, actor="t", today=today)

        states = feature_states(account)

        self.assertEqual(set(states), {"bdds", "billing", "roles"})
        for code, payload in states.items():
            with self.subTest(code=code):
                self.assertEqual(payload["state"], "trial")
                self.assertEqual(payload["trial_until"], (today + timedelta(days=13)).isoformat())
                self.assertTrue(payload["enabled"])
                self.assertEqual(payload["access"], "full")
                self.assertEqual(payload["plan"], "pro")
                self.assertEqual(payload["price_month_rub"], 3000)

    def test_features_payload_for_expired_plan(self):
        account = make_account()
        subscription = service.set_account_plan(account, paid_until=subscription_today() - timedelta(days=30))

        payload = feature_states(account)["billing"]

        self.assertEqual(payload["state"], "off")
        self.assertFalse(payload["enabled"])
        self.assertEqual(payload["status"], "expired")
        self.assertEqual(payload["access"], "read_only")
        self.assertTrue(payload["can_read"])
        self.assertFalse(payload["can_write"])
        self.assertEqual(payload["paid_until"], subscription.paid_until.isoformat())

    def test_features_payload_without_plan(self):
        payload = feature_states(make_account())["roles"]

        self.assertEqual((payload["state"], payload["access"], payload["enabled"]), ("off", "none", False))


class FeatureRequiredDecoratorTest(TestCase):
    """Декоратор для соседних задач: код roles, чтение и запись по методу."""

    def setUp(self):
        self.account = make_account()
        self.factory = RequestFactory()

        @feature_required("roles")
        def view(request):
            return HttpResponse("ok")

        @feature_required("roles", write=False)
        def post_read(request):
            return HttpResponse("ok")

        self.view = view
        self.post_read = post_read

    def call(self, view, method="get"):
        request = getattr(self.factory, method)("/x")
        request.bitrix24_account = self.account
        return view(request)

    def test_roles_is_closed_without_plan(self):
        response = self.call(self.view)
        self.assertEqual(response.status_code, 403)
        self.assertIn("Ролевая модель", json.loads(response.content)["error"])

    def test_roles_opens_with_pro(self):
        service.set_account_plan(self.account)
        self.assertEqual(self.call(self.view, "post").status_code, 200)

    def test_expired_plan_reads_but_does_not_write(self):
        service.set_account_plan(self.account, state=PortalSubscription.STATE_EXPIRED)
        self.assertEqual(self.call(self.view).status_code, 200)
        self.assertEqual(self.call(self.view, "post").status_code, 403)
        self.assertEqual(self.call(self.view, "delete").status_code, 403)
        self.assertEqual(self.call(self.post_read, "post").status_code, 200)

    def test_expired_roles_close_role_changes_but_keep_restrictions(self):
        """Окончание Pro не снимает ограничения ролей: иначе все увидят ставки и деньги."""
        service.set_account_plan(self.account, paid_until=subscription_today() - timedelta(days=30))

        change = self.call(self.view, "post")
        self.assertEqual(change.status_code, 403)
        payload = json.loads(change.content)
        self.assertEqual(payload["reason"], "expired")
        self.assertIn("назначать и менять роли нельзя", payload["error"])
        self.assertIn("ограничения продолжают действовать", payload["error"])
        self.assertEqual(self.call(self.view).status_code, 200)

        self.assertFalse(feature_enabled(self.account, "roles"))
        self.assertTrue(feature_restrictions_active(self.account))
        roles = feature_states(self.account)["roles"]
        self.assertTrue(roles["restrictions_active"])
        self.assertFalse(roles["can_write"])
        self.assertNotIn("restrictions_active", feature_states(self.account)["bdds"])

    def test_roles_restrictions_follow_plan_state(self):
        self.assertFalse(feature_restrictions_active(self.account))
        subscription = service.set_account_plan(self.account)
        self.assertTrue(feature_restrictions_active(self.account))
        subscription.state = PortalSubscription.STATE_EXPIRED
        subscription.save(update_fields=["state"])
        self.assertTrue(feature_restrictions_active(self.account))
        subscription.state = PortalSubscription.STATE_OFF
        subscription.save(update_fields=["state"])
        self.assertFalse(feature_restrictions_active(self.account))

    def test_missing_account_is_refused(self):
        request = self.factory.get("/x")
        self.assertEqual(self.view(request).status_code, 403)


class ProPlanCommandTest(TestCase):
    def setUp(self):
        self.admin = make_account()
        self.colleague = make_account(user_id=12, is_b24_user_admin=False, is_master_account=False)
        self.stranger = make_account(member_id="m-other", domain="other.bitrix24.ru", user_id=1)
        self.today = subscription_today()

    def run_command(self, *args):
        out = StringIO()
        call_command("pro_plan", *args, stdout=out)
        return out.getvalue()

    def subscription(self, member_id="m-pro"):
        return PortalSubscription.objects.get(portal__member_id=member_id)

    def test_enable_until_date_by_member_id(self):
        until = self.today + timedelta(days=100)
        output = self.run_command("enable", "--member-id", "m-pro", "--until", until.isoformat(),
                                  "--comment", "счёт 15", "--by", "egor")

        subscription = self.subscription()
        self.assertEqual((subscription.state, subscription.paid_until), ("active", until))
        self.assertEqual(subscription.price_month_rub, 3000)
        self.assertEqual(subscription.updated_by, "console:egor")
        self.assertEqual(subscription.comment, "счёт 15")
        self.assertEqual(PortalSubscription.objects.count(), 1)
        self.assertEqual(feature_access(self.colleague, "bdds"), ACCESS_FULL)
        self.assertEqual(feature_access(self.stranger, "bdds"), ACCESS_NONE)
        self.assertIn("стало: Pro: действует", output)
        self.assertIn(f"оплачен по {until:%d.%m.%Y}", output)

    def test_enable_months_by_domain_creates_portal_row(self):
        Portal.objects.all().delete()

        self.run_command("enable", "--domain", "https://PRO.bitrix24.ru/", "--months", "12", "--price", "2500")

        subscription = self.subscription()
        self.assertEqual(subscription.paid_until, service.add_months(self.today, 12) - timedelta(days=1))
        self.assertEqual(subscription.price_month_rub, 2500)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.portal_id, subscription.portal_id)

    def test_enable_needs_exactly_one_term(self):
        with self.assertRaises(CommandError):
            self.run_command("enable", "--member-id", "m-pro")
        with self.assertRaises(CommandError):
            self.run_command("enable", "--member-id", "m-pro", "--months", "1", "--until", "2030-01-01")
        with self.assertRaises(CommandError):
            self.run_command("enable", "--member-id", "m-pro", "--until", "31.12.2026")

    def test_extend_continues_from_paid_until_even_in_grace(self):
        paid = self.today - timedelta(days=3)
        service.set_account_plan(self.admin, paid_until=paid)

        self.run_command("extend", "--domain", "pro.bitrix24.ru", "--months", "1")

        expected = service.add_months(paid + timedelta(days=1), 1) - timedelta(days=1)
        self.assertEqual(self.subscription().paid_until, expected)

    def test_extend_after_expiry_counts_from_today(self):
        service.set_account_plan(self.admin, paid_until=self.today - timedelta(days=60))

        output = self.run_command("extend", "--member-id", "m-pro", "--months", "2")

        self.assertEqual(self.subscription().paid_until, service.add_months(self.today, 2) - timedelta(days=1))
        self.assertIn("было:  Pro: истёк", output)

    def test_extend_of_unlimited_plan_is_refused(self):
        service.set_account_plan(self.admin)
        with self.assertRaises(CommandError):
            self.run_command("extend", "--member-id", "m-pro", "--months", "1")

    def test_trial_defaults_to_fourteen_days(self):
        output = self.run_command("trial", "--member-id", "m-pro")

        subscription = self.subscription()
        self.assertEqual((subscription.state, subscription.trial_until),
                         ("trial", self.today + timedelta(days=13)))
        self.assertIn("пробный", output)

    def test_trial_does_not_silently_replace_paid_plan(self):
        service.set_account_plan(self.admin, paid_until=self.today + timedelta(days=30))

        with self.assertRaises(CommandError):
            self.run_command("trial", "--member-id", "m-pro", "--days", "7")

        self.run_command("trial", "--member-id", "m-pro", "--days", "7", "--force")
        self.assertEqual(self.subscription().state, "trial")

    def test_expire_leaves_reading(self):
        service.set_account_plan(self.admin, paid_until=self.today + timedelta(days=30))

        output = self.run_command("expire", "--member-id", "m-pro", "--comment", "не оплатили")

        self.assertEqual(feature_access(self.colleague, "billing"), ACCESS_READ_ONLY)
        self.assertIn("назначенные ограничения ролей продолжают действовать", output)

    def test_off_closes_everything_and_is_journaled(self):
        self.run_command("enable", "--member-id", "m-pro", "--months", "1", "--by", "egor")
        output = self.run_command("off", "--member-id", "m-pro", "--comment", "отказались", "--by", "egor")
        self.assertIn("используйте expire", output)

        self.assertEqual(feature_access(self.admin, "bdds"), ACCESS_NONE)
        events = list(PortalSubscriptionEvent.objects.order_by("created_at").values_list("action", "changes"))
        self.assertEqual([action for action, _ in events], ["enable", "off"])
        self.assertEqual(events[1][1]["state"], ["active", "off"])

    def test_list_shows_status_and_dates(self):
        self.run_command("enable", "--member-id", "m-pro", "--until", "2030-12-31")

        output = self.run_command("list")

        self.assertIn("pro.bitrix24.ru", output)
        self.assertIn("действует", output)
        self.assertIn("31.12.2030", output)
        self.assertIn("other.bitrix24.ru", output)
        self.assertIn("нет тарифа", output)
        self.assertNotIn("other.bitrix24.ru", self.run_command("list", "--with-plan"))
        self.assertNotIn("pro.bitrix24.ru", self.run_command("list", "--status", "expired"))

    def test_show_prints_journal(self):
        self.run_command("enable", "--member-id", "m-pro", "--until", "2030-12-31", "--comment", "договор 7")

        output = self.run_command("show", "--domain", "pro.bitrix24.ru")

        self.assertIn("member_id m-pro", output)
        self.assertIn("договор 7", output)
        self.assertIn("enable", output)

    def test_unknown_portal_and_ambiguous_domain_are_errors(self):
        with self.assertRaises(CommandError):
            self.run_command("enable", "--domain", "нет-такого.bitrix24.ru", "--months", "1")
        make_account(member_id="m-twin", domain="pro.bitrix24.ru", user_id=99)
        with self.assertRaises(CommandError):
            self.run_command("enable", "--domain", "pro.bitrix24.ru", "--months", "1")
        with self.assertRaises(CommandError):
            self.run_command("enable", "--member-id", "m-pro", "--domain", "other.bitrix24.ru", "--months", "1")

    def test_target_is_required(self):
        with self.assertRaises(CommandError):
            self.run_command("off")


class LegacyRowsMergeTest(SimpleTestCase):
    def row(self, member_id, code, state, trial_until=None, domain="p.bitrix24.ru"):
        return {"member_id": member_id, "code": code, "state": state, "trial_until": trial_until, "domain": domain}

    def test_best_enabled_state_wins_per_portal(self):
        late = datetime(2026, 10, 1, 21, 30, tzinfo=dt_timezone.utc)   # 02.10 по Москве
        merged = merge_legacy_rows([
            self.row("m1", "billing", "on"), self.row("m1", "bdds", "off"),
            self.row("m2", "billing", "trial", datetime(2026, 9, 20, tzinfo=dt_timezone.utc)),
            self.row("m2", "bdds", "trial", late),
            self.row("m3", "billing", "trial", None), self.row("m3", "bdds", "trial", late),
            self.row("m4", "billing", "off"),
            self.row("", "billing", "on"),
        ])

        self.assertEqual(merged["m1"]["state"], "active")
        self.assertIn("billing=on", merged["m1"]["comment"])
        self.assertEqual((merged["m2"]["state"], merged["m2"]["trial_until"]), ("trial", date(2026, 10, 2)))
        self.assertEqual((merged["m3"]["state"], merged["m3"]["trial_until"]), ("trial", None))
        self.assertEqual(merged["m4"]["state"], "off")
        self.assertNotIn("", merged)


class PortalFeatureDataMigrationTest(TransactionTestCase):
    """Настоящая миграция 0024 на строках старой модели (не на двойнике)."""

    before = [("main", "0023_billing_invoice_print")]
    after = [("main", "0025_delete_portalfeature")]

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_rows_per_account_become_one_plan_per_portal(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        apps = executor.loader.project_state(self.before).apps
        Account = apps.get_model("main", "Bitrix24Account")
        Feature = apps.get_model("main", "PortalFeature")
        OldPortal = apps.get_model("main", "Portal")

        def account(user_id, member_id, domain):
            return Account.objects.create(
                b24_user_id=user_id, member_id=member_id, domain_url=domain, status="active",
                application_version=1, is_b24_user_admin=False,
            )

        paid_a = account(1, "m-paid", "paid.bitrix24.ru")
        paid_b = account(2, "m-paid", "paid.bitrix24.ru")
        trial = account(3, "m-trial", "trial.bitrix24.ru")
        off = account(4, "m-off", "off.bitrix24.ru")
        OldPortal.objects.create(member_id="m-paid", domain_url="paid.bitrix24.ru")
        Feature.objects.create(bitrix24_account=paid_a, code="billing", state="on")
        Feature.objects.create(bitrix24_account=paid_b, code="billing", state="on")
        Feature.objects.create(bitrix24_account=paid_b, code="bdds", state="off")
        Feature.objects.create(bitrix24_account=trial, code="bdds", state="trial",
                               trial_until=datetime(2030, 1, 10, 12, 0, tzinfo=dt_timezone.utc))
        Feature.objects.create(bitrix24_account=off, code="billing", state="off")

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.after)
        apps = executor.loader.project_state(self.after).apps
        Subscription = apps.get_model("main", "PortalSubscription")
        Event = apps.get_model("main", "PortalSubscriptionEvent")

        rows = {row.portal.member_id: row for row in Subscription.objects.select_related("portal")}
        self.assertEqual(set(rows), {"m-paid", "m-trial", "m-off"})
        self.assertEqual((rows["m-paid"].state, rows["m-paid"].paid_until), ("active", None))
        self.assertEqual((rows["m-trial"].state, rows["m-trial"].trial_until), ("trial", date(2030, 1, 10)))
        self.assertEqual(rows["m-off"].state, "off")
        self.assertEqual(rows["m-paid"].plan, "pro")
        self.assertEqual(Event.objects.filter(action="migrate").count(), 3)
        # Портал для member_id без строки Portal заведён, учётки к нему привязаны.
        self.assertEqual(apps.get_model("main", "Portal").objects.filter(member_id="m-trial").count(), 1)
        self.assertIsNotNone(apps.get_model("main", "Bitrix24Account").objects.get(b24_user_id=3).portal_id)
        self.assertNotIn("portal_feature", connection.introspection.table_names())
