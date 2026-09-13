"""Настройки «Счёта и акта» в общей конфигурации приложения.

Перенесены из tests_billing_feature_command.py, когда команда billing_feature
уступила место pro_plan (тариф портала): к подписке эти проверки отношения
не имеют.
"""

from django.test import SimpleTestCase

from .configuration_service import ConfigurationService


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
