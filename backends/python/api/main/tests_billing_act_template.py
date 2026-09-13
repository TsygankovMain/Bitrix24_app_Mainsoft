"""Шаблоны генератора документов приходят СЛОВАРЁМ по id, а не списком.

Портал на crm.documentgenerator.template.list отвечает
{"result": {"templates": {"2": {...}}}}. Двойник портала в
tests_billing_endpoints отдаёт список, поэтому ловушка тестами не ловилась:
перебор словаря давал строковые ключи, они отбрасывались, и печать акта
падала с «шаблонов нет» при живом штатном «Акт (Россия)» (id 2 на
nfr-mainsoft, код ACT_RU).
"""

from django.test import TestCase

from main.billing_crm_service import BillingCrmService
from main.models import Bitrix24Account


class _Token:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def call_method(self, method, params):
        self.calls.append((method, params))
        return self.payload


class _Client:
    def __init__(self, payload):
        self._bitrix_token = _Token(payload)


class ActTemplateListShapeTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-act-tpl",
            is_master_account=True, domain_url="act-tpl.bitrix24.ru",
            status="active", application_version=1,
        )

    def _service(self, payload):
        return BillingCrmService(self.account, client=_Client(payload))

    def test_slovar_po_id_razbiraetsya(self):
        """Форма портала: templates — словарь по id."""
        service = self._service({"result": {"templates": {
            "2": {
                "id": "2", "name": "Акт (Россия)", "code": "ACT_RU", "isDefault": "Y",
                "region": "ru", "active": "Y", "numeratorId": "2",
                "productsTableVariant": "service",
            },
        }}})

        templates = service.list_templates()

        self.assertEqual(templates, [{
            "id": 2,
            "name": "Акт (Россия)",
            "code": "ACT_RU",
            "region": "ru",
            "active": True,
            "is_default": True,
            "numerator_id": 2,
            "products_table_variant": "service",
        }])

    def test_spisok_tozhe_razbiraetsya(self):
        """Форма двойника и части порталов: templates — список."""
        service = self._service({"result": {"templates": [
            {"id": "7", "name": "Счёт (Россия)"},
        ]}})

        templates = service.list_templates()

        self.assertEqual(len(templates), 1)
        self.assertEqual(templates[0]["id"], 7)
        self.assertEqual(templates[0]["name"], "Счёт (Россия)")
        # Флаги портала приходят строками "Y"/"N", наружу уходят булевыми:
        # строка "N" в JavaScript истинна и поставила бы галочку «по
        # умолчанию» всем шаблонам подряд.
        self.assertIs(templates[0]["active"], True)
        self.assertIs(templates[0]["is_default"], False)

    def test_akt_nahoditsya_po_nazvaniyu_v_slovare(self):
        """Запасной путь выбора шаблона акта работает и на словаре."""
        service = self._service({"result": {"templates": {
            "7": {"id": "7", "name": "Счёт (Россия)"},
            "2": {"id": "2", "name": "Акт (Россия)"},
        }}})

        self.assertEqual(service.resolve_act_template_id(), 2)

    def test_vybor_iz_nastroek_silnee_ugadyvaniya(self):
        """Явно выбранный шаблон портал не переспрашивает."""
        service = self._service({"result": {"templates": {}}})

        self.assertEqual(service.resolve_act_template_id(preferred_id=5), 5)
        self.assertEqual(service.client._bitrix_token.calls, [])
