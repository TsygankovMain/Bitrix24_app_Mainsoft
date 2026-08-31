"""Гейт свежести не должен съедать обновление справочника задач.

Боевая проверка 31.08.2026. Пользователь назначил задаче новый проект, нажал
«Обновить» — сработало. Через пятнадцать секунд поменял проект снова, нажал
«Обновить» — и кнопка не сделала НИЧЕГО.

Причина: в timesheet_sync стоит трёхминутный гейт свежести, который выходит из
обработчика с ответом "fresh", не выполняя остального. Обновление справочника
задач стояло ПОСЛЕ гейта, поэтому при повторном нажатии до него не доходило.
В логе это видно буквально: один ответ "success" за 1805 мс и следом четыре
"fresh" по ~120 мс.

Гейт защищает от лишних обходов Битрикса за списаниями — операции дорогой.
Справочник задач это отдельный и дешёвый источник (SELECT плюс, при наличии
изменений, один вызов), и на него гейт распространяться не должен: кнопка
обязана показывать реальное положение задач при КАЖДОМ нажатии.
"""

import json
from unittest import mock

from django.test import Client, TestCase
from django.utils import timezone

from .models import Bitrix24Account


class RefreshRunsBeforeFreshnessGateTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-gate",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
            # Синк был только что -> гейт свежести сработает.
            last_timesheet_synced_at=timezone.now(),
        )
        self.token = self.account.create_jwt_token()

    def _sync(self):
        return Client().post(
            "/api/sync-timesheets",
            data=json.dumps({}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )

    @mock.patch("main.views._refresh_task_directory")
    @mock.patch("main.views.ConfigurationService.get_configuration_sync",
                return_value={"sp_entity_type_id": 1, "fields_mapping": {}})
    def test_directory_refreshed_even_when_response_is_fresh(self, _cfg, m_refresh):
        """Ядро правки: гейт вернул "fresh", но справочник обновлён."""
        response = self._sync()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "fresh")
        m_refresh.assert_called_once_with(self.account)

    @mock.patch("main.views._refresh_task_directory")
    @mock.patch("main.views.ConfigurationService.get_configuration_sync",
                return_value={"sp_entity_type_id": 1, "fields_mapping": {}})
    def test_directory_refreshed_on_repeated_presses(self, _cfg, m_refresh):
        """Повторные нажатия подряд — тот самый сценарий из проверки."""
        for _ in range(4):
            self.assertEqual(self._sync().json()["status"], "fresh")

        self.assertEqual(m_refresh.call_count, 4)


class RefreshFailureDoesNotBreakSyncTest(TestCase):
    """Сбой справочника не должен превращать успешный синк в ошибку."""

    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-gate2",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
            last_timesheet_synced_at=timezone.now(),
        )
        self.token = self.account.create_jwt_token()

    @mock.patch("main.views.TaskSyncService")
    @mock.patch("main.views.ConfigurationService.get_configuration_sync",
                return_value={"sp_entity_type_id": 1, "fields_mapping": {}})
    def test_sync_survives_directory_failure(self, _cfg, m_service):
        m_service.side_effect = RuntimeError("Битрикс недоступен")

        response = Client().post(
            "/api/sync-timesheets",
            data=json.dumps({}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "fresh")
