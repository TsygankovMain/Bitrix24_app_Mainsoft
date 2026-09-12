"""Управление подпиской: команда billing_feature и настройки счёта.

Ключевое требование контракта, которое здесь и закрепляется: состояние
платной функции меняется ТОЛЬКО командой, и меняется порталу целиком, а не
одной учётке. Учётка в этом приложении — запись на сотрудника, поэтому
включение «одному аккаунту» означало бы, что функция есть у администратора
и нет у бухгалтера.
"""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from .billing_features import feature_enabled, feature_states
from .configuration_service import ConfigurationService
from .models import Bitrix24Account, PortalFeature


class BillingFeatureCommandTest(TestCase):
    def setUp(self):
        self.admin = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-cmd",
            is_master_account=True, domain_url="cmd.bitrix24.ru",
            status="active", application_version=1,
        )
        self.colleague = Bitrix24Account.objects.create(
            b24_user_id=12, is_b24_user_admin=False, member_id="m-cmd",
            is_master_account=False, domain_url="cmd.bitrix24.ru",
            status="active", application_version=1,
        )
        self.stranger = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-other",
            is_master_account=True, domain_url="other.bitrix24.ru",
            status="active", application_version=1,
        )

    def run_command(self, *args, **kwargs):
        out = StringIO()
        call_command("billing_feature", *args, stdout=out, **kwargs)
        return out.getvalue()

    def test_enabling_covers_every_account_of_the_portal(self):
        self.run_command("--domain", "cmd.bitrix24.ru", "--state", "on")

        self.assertEqual(PortalFeature.objects.filter(code="billing").count(), 2)
        self.assertTrue(feature_enabled(self.admin, "billing"))
        self.assertTrue(feature_enabled(self.colleague, "billing"))

    def test_other_portals_are_untouched(self):
        self.run_command("--domain", "cmd.bitrix24.ru", "--state", "on")

        self.assertFalse(feature_enabled(self.stranger, "billing"))

    def test_disabling_works(self):
        self.run_command("--member-id", "m-cmd", "--state", "on")
        self.run_command("--member-id", "m-cmd", "--state", "off", "--comment", "не продлили")

        self.assertFalse(feature_enabled(self.admin, "billing"))
        self.assertEqual(PortalFeature.objects.filter(state="off").count(), 2)

    def test_trial_days_set_the_deadline(self):
        self.run_command("--member-id", "m-cmd", "--state", "trial", "--trial-days", "14")

        row = PortalFeature.objects.filter(bitrix24_account=self.admin).get()
        self.assertEqual(row.state, "trial")
        self.assertIsNotNone(row.trial_until)
        self.assertTrue(feature_enabled(self.admin, "billing"))

    def test_expired_trial_is_off(self):
        self.run_command("--member-id", "m-cmd", "--state", "trial", "--trial-days", "1")
        PortalFeature.objects.update(trial_until=timezone.now() - timezone.timedelta(hours=1))

        self.assertFalse(feature_enabled(self.admin, "billing"))

    def test_unknown_portal_is_an_error(self):
        with self.assertRaises(CommandError):
            self.run_command("--domain", "нет-такого.bitrix24.ru", "--state", "on")

    def test_state_is_required(self):
        with self.assertRaises(CommandError):
            self.run_command("--domain", "cmd.bitrix24.ru")

    def test_unknown_code_is_an_error(self):
        with self.assertRaises(CommandError):
            self.run_command("--domain", "cmd.bitrix24.ru", "--state", "on", "--code", "magic")

    def test_target_is_required(self):
        with self.assertRaises(CommandError):
            self.run_command("--state", "on")

    def test_list_shows_current_states(self):
        self.run_command("--member-id", "m-cmd", "--state", "on")

        output = self.run_command("--list")

        self.assertIn("cmd.bitrix24.ru", output)
        self.assertIn("billing=on", output)

    def test_features_payload_lists_every_known_code(self):
        states = feature_states(self.admin)

        self.assertEqual(set(states), {"billing", "bdds"})
        self.assertEqual(states["bdds"]["state"], "off")


class BillingConfigurationTest(SimpleTestCase):
    """Настройки счёта живут в общей конфигурации приложения, не в своей."""

    def normalize(self, config):
        return ConfigurationService(client=None).normalize_configuration_sync(config)

    def test_defaults_are_conservative(self):
        config = self.normalize({})

        self.assertFalse(config["billing_allow_open_period"])
        self.assertEqual(config["billing_accountants"], [])
        self.assertEqual(config["billing_act_template_id"], 0)

    def test_string_false_does_not_enable_open_period(self):
        """app.option отдаёт всё строками, а bool('false') в Python истинно."""
        for raw in ("false", "0", "", "no"):
            with self.subTest(raw=raw):
                self.assertFalse(self.normalize({"billing_allow_open_period": raw})["billing_allow_open_period"])

    def test_string_true_enables_open_period(self):
        for raw in ("true", "1", "Y", True):
            with self.subTest(raw=raw):
                self.assertTrue(self.normalize({"billing_allow_open_period": raw})["billing_allow_open_period"])

    def test_accountants_are_strings_without_duplicates(self):
        config = self.normalize({"billing_accountants": [11, "11", " 12 ", "", None]})

        self.assertEqual(config["billing_accountants"], ["11", "12"])

    def test_broken_accountants_value_degrades_to_empty(self):
        self.assertEqual(self.normalize({"billing_accountants": {"a": 1}})["billing_accountants"], [])

    def test_template_id_is_an_int(self):
        self.assertEqual(self.normalize({"billing_act_template_id": "6"})["billing_act_template_id"], 6)
        self.assertEqual(self.normalize({"billing_act_template_id": "нет"})["billing_act_template_id"], 0)
