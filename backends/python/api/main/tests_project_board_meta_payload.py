"""Тесты гигиены ответа ProjectCardService.get_meta() (хотфикс perf/project-references).

Контекст: боевые логи 2026-07-28 — на портале с 23 252 компаниями ответ
GET /api/project-board/meta весил 37.9 МБ. Причина — meta клала одни и те же
три справочника (employees/companies/legal_entities) трижды: в filters,
в directories и в корне. ~25 МБ из 37.9 МБ было чистым дублированием.

Фронт везде читает directories первым (filters/корень — только запасные
варианты), поэтому данные оставлены только в directories, а filters — пустой
словарь (нужен как словарь для _meta_has_required_shape и формы фронта).

Двойник клиента — по образцу tests_user_sync_service.py (_FakeClient с
call_method и _bitrix_token = self). get_meta() дёргает ConfigurationService,
get_companies/get_legal_entities — они замоканы на уровне методов сервиса, а
не через фейковый REST.

Сотрудники — отдельно (Task 4 плана "справочники из локальной базы"):
get_meta() с этой задачи читает их из локальной таблицы portal_user
(PortalUser, active=True), а не через BitrixDataService.fetch_active_users —
поэтому здесь заводится настоящая строка PortalUser, а не мок метода.
"""
import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from .models import Bitrix24Account, PortalUser
from .project_board_service import ProjectCardService


class _FakeClient:
    """Минимальный двойник Client — как в tests_user_sync_service.py."""

    def __init__(self):
        self._bitrix_token = self

    def call_method(self, method, params):
        return {"result": []}


class GetMetaPayloadHygieneTest(TestCase):
    UNIQUE_COMPANY_NAME = "ООО Уникальная Тестовая Компания Гигиена Мета"

    def setUp(self):
        # Справочники кэшируются по ключу аккаунта -> без очистки тесты
        # зависят от порядка запуска (см. брифом отмеченную ловушку).
        cache.clear()
        self.addCleanup(cache.clear)

        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-meta-hygiene-1",
            is_master_account=True, domain_url="meta-hygiene.bitrix24.ru",
            status="active", application_version=1,
        )
        self.service = ProjectCardService(_FakeClient(), self.account)

        PortalUser.objects.create(
            bitrix24_account=self.account, bitrix_id="1",
            name="Иван", last_name="Петров", active=True,
        )
        self.companies = [
            {
                "id": "100",
                "name": self.UNIQUE_COMPANY_NAME,
                "inn": "7700000001",
                "is_my_company": False,
            }
        ]
        self.legal_entities = [
            {
                "id": "200",
                "name": "ООО Наше Юрлицо Гигиена Мета",
                "inn": "7700000002",
                "is_my_company": True,
            }
        ]

        self._patch(ProjectCardService, "_load_config", return_value={})
        self._patch(ProjectCardService, "get_companies", return_value=self.companies)
        self._patch(ProjectCardService, "get_legal_entities", return_value=self.legal_entities)

    def _patch(self, target, attribute=None, **kwargs):
        if attribute is None:
            patcher = patch(target, **kwargs)
        else:
            patcher = patch.object(target, attribute, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def test_get_meta_has_no_root_level_directory_keys(self):
        meta = self.service.get_meta()

        self.assertNotIn("employees", meta)
        self.assertNotIn("companies", meta)
        self.assertNotIn("legal_entities", meta)

    def test_get_meta_directories_contain_all_three_lists(self):
        meta = self.service.get_meta()

        directories = meta["directories"]
        self.assertEqual([item["id"] for item in directories["employees"]], ["1"])
        self.assertEqual([item["id"] for item in directories["companies"]], ["100"])
        self.assertEqual([item["id"] for item in directories["legal_entities"]], ["200"])

    def test_filters_present_and_is_dict(self):
        meta = self.service.get_meta()

        self.assertIn("filters", meta)
        self.assertIsInstance(meta["filters"], dict)

    def test_meta_has_required_shape_true_for_new_response(self):
        meta = self.service.get_meta()

        self.assertTrue(ProjectCardService._meta_has_required_shape(meta))

    def test_meta_has_options_true_when_directories_companies_nonempty(self):
        meta = self.service.get_meta()

        self.assertTrue(self.service._meta_has_options(meta))

    def test_company_list_appears_exactly_once_in_serialized_json(self):
        """Суть задачи: раньше один и тот же список компаний попадал в JSON
        трижды (filters.companies, directories.companies, корневой companies).
        Ищем JSON-пару "name": "<уникальное имя тестовой компании>" — именно
        она обозначает отдельное вхождение записи справочника в ответе.
        (Просто искать голое имя нельзя: _merge_reference_options переносит
        name и внутрь search_text того же самого элемента, так что голая
        подстрока с именем закономерно встречается дважды даже в одной копии
        списка — это не имеет отношения к тройному дублированию, которое
        чинит эта задача.)
        """
        meta = self.service.get_meta()
        serialized = json.dumps(meta, ensure_ascii=False)

        marker = f'"name": "{self.UNIQUE_COMPANY_NAME}"'
        self.assertEqual(serialized.count(marker), 1)
