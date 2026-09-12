"""
save_configuration: отдельное сохранение «Доходов-расходов» (scope=finance).

Экран сопоставления сохраняет шаг «Доходы-расходы» своей кнопкой. Без
отдельной ветки такое сохранение при подключённом смарт-процессе проектов
шло бы через _save_configuration_with_project_sync: живую проверку проектов,
полную синхронизацию, лимит 6/60 — и 400, если сопоставление проектов на
портале поломано. Тесты фиксируют три вещи:

1. scope=finance при неизменной проектной части не зовёт ни проверку, ни
   синхронизацию и сохраняет конфигурацию целиком;
2. этим признаком НЕЛЬЗЯ обойти проверку проектов: изменённая проектная
   часть или несчитанная сохранённая конфигурация — обычный путь;
3. без признака всё как раньше.
"""
import json
from http import HTTPStatus
from unittest.mock import MagicMock, PropertyMock, patch

from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from .models import Bitrix24Account
from .project_sync_service import ProjectSyncService

LOCMEM_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "config-save-finance-tests"}}

STORED_CONFIG = {
    "sp_entity_type_id": 1100,
    "fields_mapping": {"id_zadachi": "ufCrm5TaskId", "kolichestvo_chasov": "ufCrm5Hours"},
    "project_sp_entity_type_id": 1102,
    "project_fields_mapping": {
        "title": "TITLE",
        "stage_id": "STAGE_ID",
        "bitrix_group_id": "ufCrm6BitrixGroupId",
    },
    "finance_sp_entity_type_id": 0,
    "finance_fields_mapping": {},
    "hourly_rate": 1500,
    "billing_accountants": ["7"],
}

FINANCE_MAPPING = {
    "project_item_id": "ufCrm9ProjectItemId",
    "operation_type": "ufCrm9OperationType",
    "amount": "ufCrm9Amount",
    "operation_date": "ufCrm9OperationDate",
    "source": "ufCrm9Source",
}


def _make_account() -> Bitrix24Account:
    return Bitrix24Account.objects.create(
        b24_user_id=501,
        member_id="member_finance_scope",
        domain_url="portal-finance-scope.bitrix24.ru",
        status="active",
        application_version=1,
        is_b24_user_admin=True,
        is_master_account=False,
    )


def _portal(stored=None, *, read_fails=False):
    """Портал с сохранённой конфигурацией; копит вызовы app.option.set."""
    saved = []

    def call_method(method, params=None):
        if method == "app.option.get":
            if read_fails:
                raise RuntimeError("portal unavailable")
            return {"result": {"timestamp_config": json.dumps(stored or {})}}
        if method == "app.option.set":
            saved.append(json.loads(params["options"]["timestamp_config"]))
        return {"result": True}

    client = MagicMock()
    client._bitrix_token.call_method.side_effect = call_method
    return client, saved


@override_settings(CACHES=LOCMEM_CACHE)
class SaveConfigurationFinanceScopeTest(TestCase):
    def setUp(self):
        cache.clear()
        self.http = Client()
        self.account = _make_account()

    def _post(self, config, scope=None):
        body = {"config": config}
        if scope is not None:
            body["scope"] = scope
        return self.http.post(
            "/api/configuration/save",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.account.create_jwt_token()}",
        )

    def _incoming(self, **changes):
        config = json.loads(json.dumps(STORED_CONFIG))
        config.update({"finance_sp_entity_type_id": 1104, "finance_fields_mapping": dict(FINANCE_MAPPING)})
        config.update(changes)
        return config

    def test_finance_scope_skips_project_validation_and_sync(self):
        portal, saved = _portal(STORED_CONFIG)
        validation = MagicMock(return_value={"is_valid": False})

        with patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=portal), \
             patch("main.views._build_project_spa_validation_payload", validation), \
             patch.object(ProjectSyncService, "sync") as sync:
            response = self._post(self._incoming(), scope="finance")

        self.assertEqual(response.status_code, HTTPStatus.OK, response.content)
        self.assertEqual(response.json(), {"status": "success", "scope": "finance"})
        validation.assert_not_called()
        sync.assert_not_called()

        self.assertEqual(len(saved), 1)
        written = saved[0]
        self.assertEqual(written["finance_sp_entity_type_id"], 1104)
        self.assertEqual(written["finance_fields_mapping"], FINANCE_MAPPING)
        # Остальная конфигурация не затёрта.
        self.assertEqual(written["sp_entity_type_id"], 1100)
        self.assertEqual(written["fields_mapping"], STORED_CONFIG["fields_mapping"])
        self.assertEqual(written["project_sp_entity_type_id"], 1102)
        self.assertEqual(written["project_fields_mapping"]["bitrix_group_id"], "ufCrm6BitrixGroupId")
        self.assertEqual(written["hourly_rate"], 1500)
        self.assertEqual(written["billing_accountants"], ["7"])

    def test_finance_scope_is_not_rate_limited_by_project_sync_bucket(self):
        portal, saved = _portal(STORED_CONFIG)

        with patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=portal), \
             patch("main.views._build_project_spa_validation_payload", return_value={"is_valid": True}), \
             patch.object(ProjectSyncService, "sync", return_value={"status": "success"}):
            statuses = [self._post(self._incoming(), scope="finance").status_code for _ in range(8)]

        self.assertEqual(statuses, [HTTPStatus.OK] * 8)
        self.assertEqual(len(saved), 8)

    def test_finance_scope_with_changed_project_part_goes_through_validation(self):
        portal, saved = _portal(STORED_CONFIG)
        validation = MagicMock(return_value={"is_valid": False, "missing_mapping_keys": ["curator_id"]})
        changed_project = dict(STORED_CONFIG["project_fields_mapping"], bitrix_group_id="ufCrm6Other")

        with patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=portal), \
             patch("main.views._build_project_spa_validation_payload", validation), \
             patch.object(ProjectSyncService, "sync") as sync:
            response = self._post(self._incoming(project_fields_mapping=changed_project), scope="finance")

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        validation.assert_called_once()
        sync.assert_not_called()
        self.assertEqual(saved, [])

    def test_finance_scope_with_other_project_process_goes_through_validation(self):
        portal, saved = _portal(STORED_CONFIG)
        validation = MagicMock(return_value={"is_valid": False})

        with patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=portal), \
             patch("main.views._build_project_spa_validation_payload", validation):
            response = self._post(self._incoming(project_sp_entity_type_id=2000), scope="finance")

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        validation.assert_called_once()
        self.assertEqual(saved, [])

    def test_unreadable_stored_config_makes_finance_scope_strict(self):
        """Сбой чтения даёт конфигурацию по умолчанию -> проектная часть «изменилась»."""
        portal, saved = _portal(read_fails=True)
        validation = MagicMock(return_value={"is_valid": False})

        with patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=portal), \
             patch("main.views._build_project_spa_validation_payload", validation):
            response = self._post(self._incoming(), scope="finance")

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        validation.assert_called_once()
        self.assertEqual(saved, [])

    def test_without_scope_project_validation_runs_as_before(self):
        portal, saved = _portal(STORED_CONFIG)
        validation = MagicMock(return_value={"is_valid": False})

        with patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=portal), \
             patch("main.views._build_project_spa_validation_payload", validation):
            response = self._post(self._incoming())

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        validation.assert_called_once()
        self.assertEqual(saved, [])

    def test_unknown_scope_is_ignored(self):
        portal, saved = _portal(STORED_CONFIG)
        validation = MagicMock(return_value={"is_valid": False})

        with patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=portal), \
             patch("main.views._build_project_spa_validation_payload", validation):
            response = self._post(self._incoming(), scope="project")

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        validation.assert_called_once()
        self.assertEqual(saved, [])
