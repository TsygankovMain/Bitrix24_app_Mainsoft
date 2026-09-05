"""Кэш полного справочника компаний отвязан от общего сброса (31.08.2026).

Инцидент. Кнопка «Обновить» в отчётах отдавала 409 «Синхронизация уже
выполняется». Замок синка портальный, а сам синк держался минутами: на каждой
НОВОЙ карточке списания вызывался _autofill_inn -> InnBackfillService.autofill
-> _inn_maps() -> ProjectCardService.get_full_company_directory(), то есть
полный постраничный обход компаний портала (на боевом 23 252 компании: 465
страниц плюс столько же за реквизитами).

Шестичасовой кэш этот обход не спасал: ключ "admin-company-directory" стоял в
общем списке invalidate_project_runtime_caches, которую views.timesheet_sync
зовёт в конце КАЖДОГО успешного синка. Каждый синк сносил кэш, следующий синк
с новой карточкой платил за обход заново. В проде это давало бимодальные
прогоны — 4-6 секунд при попадании в кэш и 330-440 секунд при промахе.

Здесь закреплено разделение: синк таймшитов справочник компаний Битрикса не
меняет и чистить его не должен; чистит только тот путь, который может завести
новую компанию (ProjectCreationService.create -> crm.company.add).
"""

from django.core.cache import cache
from django.test import TestCase

from .models import Bitrix24Account
from .project_board_shared import (
    build_account_cache_key,
    invalidate_company_directory_cache,
    invalidate_project_runtime_caches,
)

DIRECTORY_SUFFIX = "admin-company-directory"


class CompanyDirectoryCacheInvalidationTest(TestCase):
    def setUp(self):
        cache.clear()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1,
            is_b24_user_admin=True,
            member_id="m-directory",
            is_master_account=True,
            domain_url="example.bitrix24.ru",
            status="active",
            application_version=1,
        )

    def _key(self, suffix):
        return build_account_cache_key(self.account, suffix)

    def test_runtime_invalidation_keeps_company_directory(self):
        """Главная защита: синк таймшитов не имеет права стирать справочник."""
        cache.set(self._key(DIRECTORY_SUFFIX), [{"id": "C1"}], 600)
        cache.set(self._key("project-board"), {"rows": []}, 600)

        invalidate_project_runtime_caches(self.account)

        self.assertEqual(cache.get(self._key(DIRECTORY_SUFFIX)), [{"id": "C1"}])
        # Остальные ключи по-прежнему сбрасываются — правка сузила список,
        # а не отключила инвалидацию.
        self.assertIsNone(cache.get(self._key("project-board")))

    def test_directory_invalidation_clears_it(self):
        """Путь создания компании справочник всё-таки сбрасывает."""
        cache.set(self._key(DIRECTORY_SUFFIX), [{"id": "C1"}], 600)

        invalidate_company_directory_cache(self.account)

        self.assertIsNone(cache.get(self._key(DIRECTORY_SUFFIX)))

    def test_directory_invalidation_touches_only_its_own_key(self):
        cache.set(self._key(DIRECTORY_SUFFIX), [{"id": "C1"}], 600)
        cache.set(self._key("project-board"), {"rows": []}, 600)

        invalidate_company_directory_cache(self.account)

        self.assertEqual(cache.get(self._key("project-board")), {"rows": []})
