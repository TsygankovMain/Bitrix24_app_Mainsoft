"""Тесты справочников 1С для экрана сопоставления."""
from django.test import TestCase

from .one_c_directory_service import (
    OneCDirectoryError, OneCDirectoryService, directory_url)


class DirectoryUrlTests(TestCase):
    """Отдельного адреса для справочников нет — он считается из приёмника."""

    def test_url_is_derived_from_inbox(self):
        self.assertEqual(
            directory_url("http://1c.local/Demo_BUH/hs/msbx24/v1/inbox/timesheet"),
            "http://1c.local/Demo_BUH/hs/itlab/v1/list/all")

    def test_https_and_port_survive(self):
        self.assertEqual(
            directory_url("https://1c.local:8443/Buh/hs/msbx24/v1/inbox/timesheet"),
            "https://1c.local:8443/Buh/hs/itlab/v1/list/all")

    def test_empty_inbox_gives_empty_url(self):
        self.assertEqual(directory_url(""), "")


class FetchTests(TestCase):
    def test_answer_is_normalised(self):
        service = OneCDirectoryService(transport=lambda: {
            "ok": True,
            "физлица": [{"ид": "u-1", "наименование": "Абрамов Геннадий", "инн": "77"}],
            "организации": [{"ид": "o-1", "наименование": "Конфетпром ООО",
                             "наименованиеПолное": "ООО «Конфетпром»", "инн": "7799555550"}],
            "контрагенты": [{"ид": "c-1", "наименование": "Автотрейд", "инн": ""}],
        })

        data = service.fetch()

        self.assertEqual(data["people"][0]["name"], "Абрамов Геннадий")
        self.assertEqual(data["organizations"][0]["inn"], "7799555550")
        self.assertEqual(data["counterparties"][0]["inn"], "")

    def test_rows_without_name_are_dropped(self):
        """Безымянная строка в списке выбора бесполезна и только мешает."""
        service = OneCDirectoryService(transport=lambda: {
            "физлица": [{"ид": "u-1", "наименование": ""}, "мусор",
                        {"ид": "u-2", "наименование": "Белкина Анна"}],
        })

        self.assertEqual([r["name"] for r in service.fetch()["people"]], ["Белкина Анна"])

    def test_error_from_1c_is_readable(self):
        service = OneCDirectoryService(transport=lambda: {"ошибка": "Неверный токен подключения"})

        with self.assertRaises(OneCDirectoryError) as caught:
            service.fetch()

        self.assertIn("токен", str(caught.exception))

    def test_missing_address_explains_itself(self):
        """Без адреса подключения идти некуда — и человек должен понять, куда."""
        with self.settings(ONE_C_INBOX_URL="", ONE_C_TOKEN="", ONE_C_USER="", ONE_C_PASSWORD=""):
            with self.assertRaises(OneCDirectoryError) as caught:
                OneCDirectoryService(config={}).fetch()

        self.assertIn("адрес подключения", str(caught.exception).lower())

    def test_network_failure_is_wrapped(self):
        def boom():
            raise OSError("connection refused")

        with self.assertRaises(OneCDirectoryError) as caught:
            OneCDirectoryService(transport=boom).fetch()

        self.assertIn("connection refused", str(caught.exception))
