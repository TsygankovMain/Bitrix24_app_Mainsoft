"""Тесты создания полей смарт-процесса (installation_service).

Инцидент 17.08.2026: клиент нажал «создать поле» для `company_id` в SPA проектов
и получил 400 с текстом «Поле company_id не удалось создать или определить в
Smart Process». Настоящая причина — ответ Битрикса на `userfieldconfig.add` —
оседала в списке `warnings`, который на ветке ошибки никуда не отдавался:
`create_single_field` бросал исключение до возврата warnings, а `SystemLog`
пишется только для необработанных исключений (`utils/decorators/log_errors.py`).
В итоге причину можно было достать лишь из stdout контейнера.

Модуль до этого инцидента не имел тестов вообще.
"""
import json

from django.test import SimpleTestCase

from .installation_service import InstallationError, InstallationService


class _FakeToken:
    """Двойник bitrix_token: отдаёт ответы по имени метода, пишет журнал вызовов.

    Значение-исключение в `handlers` бросается — так воспроизводится отказ
    Битрикса на конкретном методе.
    """

    def __init__(self, handlers):
        self.handlers = handlers
        self.calls = []

    def call_method(self, method, params=None):
        self.calls.append((method, params))
        handler = self.handlers.get(method)
        if isinstance(handler, Exception):
            raise handler
        if callable(handler):
            return handler(params)
        return handler if handler is not None else {"result": {}}


class _FakeClient:
    def __init__(self, handlers):
        self._bitrix_token = _FakeToken(handlers)


def _base_handlers(**overrides):
    """Портал с созданным SPA проектов: entityTypeId 1038, внутренний id 5."""
    handlers = {
        "app.option.get": {
            "result": {
                "timestamp_config": json.dumps(
                    {
                        "project_sp_entity_type_id": 1038,
                        "project_fields_mapping": {},
                    }
                )
            }
        },
        "app.option.set": {"result": True},
        "crm.type.list": {
            "result": {
                "types": [{"id": 5, "entityTypeId": 1038, "title": "Проекты (App)"}]
            }
        },
        "crm.item.fields": {"result": {"fields": {}}},
    }
    handlers.update(overrides)
    return handlers


class CreateSingleFieldErrorTest(SimpleTestCase):
    def _service(self, handlers):
        return InstallationService(_FakeClient(handlers), None)

    def test_error_text_carries_bitrix_reason(self):
        """Отказ `userfieldconfig.add` доезжает до вызывающего, а не теряется.

        Без этого клиент видит только «не удалось создать или определить»,
        и причину приходится искать в логах контейнера.
        """
        bitrix_error = "Указан неверный тип пользовательского поля"
        service = self._service(
            _base_handlers(**{"userfieldconfig.add": Exception(bitrix_error)})
        )

        with self.assertRaises(InstallationError) as caught:
            service.create_single_field(1038, "company_id", "project")

        self.assertIn(bitrix_error, str(caught.exception))
        self.assertTrue(
            any(bitrix_error in warning for warning in caught.exception.warnings)
        )

    def test_error_names_field_missing_after_create(self):
        """Поле создалось, но не видно в `crm.item.fields` — сообщаем какое именно.

        Вторая ветка того же 400: `userfieldconfig.add` отработал, а сверка с
        `crm.item.fields` не нашла ожидаемый идентификатор. Без имени поля
        отличить эту ветку от отказа создания по тексту ошибки невозможно.
        """
        service = self._service(
            _base_handlers(
                **{
                    "userfieldconfig.add": {
                        "result": {"field": {"fieldName": "UF_CRM_5_COMPANY_ID"}}
                    }
                }
            )
        )

        with self.assertRaises(InstallationError) as caught:
            service.create_single_field(1038, "company_id", "project")

        self.assertIn("ufCrm5CompanyId", str(caught.exception))
        self.assertIn("crm.item.fields", str(caught.exception))

    def test_company_field_is_created_as_crm_binding(self):
        """Корень инцидента: тип поля должен существовать в Битриксе.

        `crm_company` в `crm.userfield.types` не значится — `userfieldconfig.add`
        отбивал создание, и «Компания» с «Наше юрлицо» не создавались ни на одном
        портале. Привязка к CRM — это тип `crm`, сущность задаётся через settings.
        """
        service = self._service(
            _base_handlers(
                **{
                    "userfieldconfig.add": {
                        "result": {"field": {"fieldName": "UF_CRM_5_COMPANY_ID"}}
                    },
                    "crm.item.fields": {
                        "result": {"fields": {"ufCrm5CompanyId": {"type": "crm"}}}
                    },
                }
            )
        )

        service.create_single_field(1038, "company_id", "project")

        sent = [
            params
            for method, params in service.client._bitrix_token.calls
            if method == "userfieldconfig.add"
        ]
        self.assertEqual(len(sent), 1)
        field = sent[0]["field"]
        self.assertEqual(field["userTypeId"], "crm")
        self.assertEqual(field["settings"]["COMPANY"], "Y")
        self.assertEqual(field["settings"]["CONTACT"], "N")
        self.assertEqual(field["settings"]["DEAL"], "N")
        self.assertEqual(field["settings"]["LEAD"], "N")

    def test_legal_entity_field_is_created_as_crm_binding(self):
        """«Наше юрлицо» страдало от того же несуществующего типа."""
        service = self._service(
            _base_handlers(
                **{
                    "userfieldconfig.add": {
                        "result": {
                            "field": {"fieldName": "UF_CRM_5_OUR_LEGAL_ENTITY_ID"}
                        }
                    },
                    "crm.item.fields": {
                        "result": {
                            "fields": {"ufCrm5OurLegalEntityId": {"type": "crm"}}
                        }
                    },
                }
            )
        )

        service.create_single_field(1038, "our_legal_entity_id", "project")

        field = [
            params
            for method, params in service.client._bitrix_token.calls
            if method == "userfieldconfig.add"
        ][0]["field"]
        self.assertEqual(field["userTypeId"], "crm")
        self.assertEqual(field["settings"]["COMPANY"], "Y")

    def test_plain_field_carries_no_settings(self):
        """settings уходит только там, где он объявлен, — не во всех полях подряд."""
        service = self._service(
            _base_handlers(
                **{
                    "userfieldconfig.add": {
                        "result": {"field": {"fieldName": "UF_CRM_5_HOURLY_RATE"}}
                    },
                    "crm.item.fields": {
                        "result": {"fields": {"ufCrm5HourlyRate": {"type": "double"}}}
                    },
                }
            )
        )

        service.create_single_field(1038, "hourly_rate", "project")

        field = [
            params
            for method, params in service.client._bitrix_token.calls
            if method == "userfieldconfig.add"
        ][0]["field"]
        self.assertEqual(field["userTypeId"], "double")
        self.assertNotIn("settings", field)

    def test_success_path_returns_mapping(self):
        """Контроль на ложную тревогу: при живом Битриксе поле мапится как раньше."""
        service = self._service(
            _base_handlers(
                **{
                    "userfieldconfig.add": {
                        "result": {"field": {"fieldName": "UF_CRM_5_COMPANY_ID"}}
                    },
                    "crm.item.fields": {
                        "result": {"fields": {"ufCrm5CompanyId": {"type": "crm"}}}
                    },
                }
            )
        )

        result = service.create_single_field(1038, "company_id", "project")

        self.assertEqual(result["field_id"], "ufCrm5CompanyId")
        self.assertEqual(result["field_key"], "company_id")
