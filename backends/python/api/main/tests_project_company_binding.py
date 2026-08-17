"""Чтение полей «Компания» и «Наше юрлицо» (тип `crm`) при синхронизации проектов.

Поля имеют тип «привязка к элементам CRM». Битрикс отдаёт такое значение с
префиксом сущности (`CO_15` — компания), когда в поле разрешено больше одного
типа. Приложение создаёт поле с единственным разрешённым типом, где значение
приходит голым ID, но на порталах эти поля часто заведены руками через интерфейс
и с несколькими галочками.

Ниже по коду ID сравнивается со списком компаний портала и по нему тянутся
реквизиты для ИНН в 1С — префикс ломает и то, и другое молча: компания просто не
находится, а в карточке проекта вместо названия остаётся «CO_15».
"""
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from .project_sync_service import ProjectSyncService


class StripCrmEntityPrefixTest(SimpleTestCase):
    def test_strips_company_prefix(self):
        self.assertEqual(ProjectSyncService._strip_crm_entity_prefix("CO_15"), "15")

    def test_strips_other_crm_prefixes(self):
        self.assertEqual(ProjectSyncService._strip_crm_entity_prefix("C_7"), "7")
        self.assertEqual(ProjectSyncService._strip_crm_entity_prefix("D_3"), "3")
        self.assertEqual(ProjectSyncService._strip_crm_entity_prefix("L_9"), "9")

    def test_plain_id_untouched(self):
        self.assertEqual(ProjectSyncService._strip_crm_entity_prefix("15"), "15")

    def test_empty_values_untouched(self):
        self.assertIsNone(ProjectSyncService._strip_crm_entity_prefix(None))
        self.assertEqual(ProjectSyncService._strip_crm_entity_prefix(""), "")

    def test_prefix_like_text_untouched(self):
        """Срезаем только «префикс + цифры», а не всё, что начинается на C_.

        Иначе поле, в которое подобрали обычную строку, поехало бы: «CO_ГОЛОВНОЙ»
        превратилось бы в «ГОЛОВНОЙ» без всякой на то причины.
        """
        self.assertEqual(
            ProjectSyncService._strip_crm_entity_prefix("CO_ГОЛОВНОЙ"), "CO_ГОЛОВНОЙ"
        )
        self.assertEqual(ProjectSyncService._strip_crm_entity_prefix("CO_"), "CO_")


class NormalizeProjectItemCompanyTest(SimpleTestCase):
    """Проверка, что срезание префикса действительно подключено к разбору карточки."""

    def _service(self):
        # __new__ вместо конструктора: он поднимает ProjectCardService, которому
        # нужны портал и БД, а здесь проверяется только разбор словаря.
        service = ProjectSyncService.__new__(ProjectSyncService)
        card_service = MagicMock()
        card_service._resolve_company_reference.side_effect = lambda cid, name=None: (cid, name)
        card_service._resolve_legal_entity_reference.side_effect = lambda eid, name=None: (eid, name)
        card_service.resolve_project_stage_title.side_effect = lambda stage, lookup=None: stage
        service.card_service = card_service
        return service

    def test_prefixed_company_becomes_plain_id(self):
        service = self._service()

        normalized = service.normalize_project_item(
            {
                "id": "44",
                "ufCrm5CompanyId": "CO_15",
                "ufCrm5OurLegalEntityId": "CO_7",
            },
            {
                "company_id": "ufCrm5CompanyId",
                "our_legal_entity_id": "ufCrm5OurLegalEntityId",
            },
            {},
            {},
            {},
        )

        self.assertEqual(normalized["company_id"], "15")
        self.assertEqual(normalized["our_legal_entity_id"], "7")

    def test_plain_company_id_still_works(self):
        """Контроль на регресс: порталы, отдающие голый ID, не должны пострадать."""
        service = self._service()

        normalized = service.normalize_project_item(
            {"id": "44", "ufCrm5CompanyId": "15"},
            {"company_id": "ufCrm5CompanyId"},
            {},
            {},
            {},
        )

        self.assertEqual(normalized["company_id"], "15")
