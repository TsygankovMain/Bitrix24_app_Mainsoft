"""
save_configuration: оптимистическая блокировка по ревизии (Баг 6).

Конфигурация лежит одним блобом в app.option — сервер раньше перезаписывал
её тем, что пришло, без всякой версии. Две вкладки, правящие разные части
экрана настроек, могли сохраниться один за другим, и второе сохранение
молча стирало то, что записало первое.

Тесты используют портал-мок, который ДЕЙСТВИТЕЛЬНО хранит состояние между
вызовами app.option.get/app.option.set (в отличие от статичного мока в
tests_config_save_finance_scope.py) — иначе конфликт ревизий, возникающий
между двумя последовательными запросами, не смоделировать.
"""
import json
from http import HTTPStatus
from unittest.mock import MagicMock, PropertyMock, patch

from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from .models import Bitrix24Account

LOCMEM_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "config-save-optimistic-lock-tests"}}

STORED_CONFIG = {
    "sp_entity_type_id": 1100,
    "fields_mapping": {"id_zadachi": "ufCrm5TaskId", "kolichestvo_chasov": "ufCrm5Hours"},
    "project_sp_entity_type_id": 0,
    "project_fields_mapping": {},
    "finance_sp_entity_type_id": 0,
    "finance_fields_mapping": {},
    "hourly_rate": 1500,
    "billing_accountants": ["7"],
}


def _make_account() -> Bitrix24Account:
    return Bitrix24Account.objects.create(
        b24_user_id=502,
        member_id="member_optimistic_lock",
        domain_url="portal-optimistic-lock.bitrix24.ru",
        status="active",
        application_version=1,
        is_b24_user_admin=True,
        is_master_account=False,
    )


def _stateful_portal(stored=None):
    """Портал, который реально запоминает то, что в него записали.

    В отличие от статичного мока соседнего файла тестов, здесь app.option.get
    после app.option.set видит уже новое значение — иначе не проверить, что
    второй (устаревший) запрос действительно наткнётся на изменившуюся
    ревизию.
    """
    state = {"config": dict(stored or {})}
    saved = []

    def call_method(method, params=None):
        if method == "app.option.get":
            return {"result": {"timestamp_config": json.dumps(state["config"])}}
        if method == "app.option.set":
            new_config = json.loads(params["options"]["timestamp_config"])
            state["config"] = new_config
            saved.append(new_config)
        return {"result": True}

    client = MagicMock()
    client._bitrix_token.call_method.side_effect = call_method
    return client, saved, state


@override_settings(CACHES=LOCMEM_CACHE)
class SaveConfigurationOptimisticLockTest(TestCase):
    def setUp(self):
        cache.clear()
        self.http = Client()
        self.account = _make_account()

    def _post(self, config, base_revision=None, scope=None):
        body = {"config": config}
        if base_revision is not None:
            body["base_revision"] = base_revision
        if scope is not None:
            body["scope"] = scope
        return self.http.post(
            "/api/configuration/save",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.account.create_jwt_token()}",
        )

    def test_matching_revision_saves_and_increments(self):
        portal, saved, state = _stateful_portal(STORED_CONFIG)

        with patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=portal):
            response = self._post(
                dict(STORED_CONFIG, hourly_rate=2000), base_revision=0,
            )

        self.assertEqual(response.status_code, HTTPStatus.OK, response.content)
        self.assertEqual(response.json(), {"status": "success", "config_revision": 1})
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["hourly_rate"], 2000)
        self.assertEqual(state["config"]["config_revision"], 1)

    def test_stale_revision_is_rejected_and_nothing_is_written(self):
        portal, saved, state = _stateful_portal(STORED_CONFIG)

        with patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=portal):
            # Вкладка A читает ревизию 0 и сохраняет первой.
            first = self._post(dict(STORED_CONFIG, hourly_rate=2000), base_revision=0)
            self.assertEqual(first.status_code, HTTPStatus.OK, first.content)
            self.assertEqual(first.json()["config_revision"], 1)

            # Вкладка B открыла экран раньше (тоже с ревизией 0) и правит
            # billing_accountants — но пытается сохранить уже после A.
            second = self._post(
                dict(STORED_CONFIG, billing_accountants=["9"]), base_revision=0,
            )

        self.assertEqual(second.status_code, HTTPStatus.CONFLICT)
        payload = second.json()
        self.assertEqual(payload["code"], "config_conflict")
        self.assertIn("обновите страницу", payload["error"])
        self.assertEqual(payload["current_revision"], 1)

        # Второе сохранение ничего не записало: правка вкладки A цела.
        self.assertEqual(len(saved), 1)
        self.assertEqual(state["config"]["hourly_rate"], 2000)
        self.assertEqual(state["config"]["billing_accountants"], ["7"])

    def test_missing_base_revision_saves_as_before(self):
        """Старый клиент / внутренний вызов без ревизии — без проверки."""
        portal, saved, state = _stateful_portal(STORED_CONFIG)

        with patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=portal):
            first = self._post(dict(STORED_CONFIG, hourly_rate=1800))
            second = self._post(dict(STORED_CONFIG, hourly_rate=1900))

        self.assertEqual(first.status_code, HTTPStatus.OK, first.content)
        self.assertEqual(second.status_code, HTTPStatus.OK, second.content)
        self.assertEqual(len(saved), 2)
        self.assertEqual(state["config"]["hourly_rate"], 1900)
        # Ревизия всё равно продвигается — не проверяется, но не откатывается.
        self.assertEqual(state["config"]["config_revision"], 2)

    def test_finance_scope_checks_revision_the_same_way(self):
        """scope=finance (быстрая ветка без синхронизации проектов) —
        та же проверка ревизии, что и в общем пути."""
        stored_with_project = dict(
            STORED_CONFIG,
            project_sp_entity_type_id=1102,
            project_fields_mapping={"title": "TITLE", "stage_id": "STAGE_ID"},
        )
        portal, saved, state = _stateful_portal(stored_with_project)
        finance_config = dict(
            stored_with_project,
            finance_sp_entity_type_id=1104,
            finance_fields_mapping={"amount": "ufCrm9Amount"},
        )

        with patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=portal), \
             patch("main.views._build_project_spa_validation_payload") as validation, \
             patch("main.views.ProjectSyncService.sync") as sync:
            stale = self._post(finance_config, base_revision=5, scope="finance")

        self.assertEqual(stale.status_code, HTTPStatus.CONFLICT)
        self.assertEqual(stale.json()["code"], "config_conflict")
        self.assertEqual(saved, [])
        validation.assert_not_called()
        sync.assert_not_called()

        with patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=portal), \
             patch("main.views._build_project_spa_validation_payload") as validation2, \
             patch("main.views.ProjectSyncService.sync") as sync2:
            ok = self._post(finance_config, base_revision=0, scope="finance")

        self.assertEqual(ok.status_code, HTTPStatus.OK, ok.content)
        self.assertEqual(ok.json(), {"status": "success", "scope": "finance", "config_revision": 1})
        self.assertEqual(len(saved), 1)
        # Быстрая ветка scope=finance по-прежнему не зовёт проверку/синк проектов.
        validation2.assert_not_called()
        sync2.assert_not_called()
