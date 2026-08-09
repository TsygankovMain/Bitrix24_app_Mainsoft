"""Сверка флага администратора идёт по TTL, а не на каждый /api/getToken.

Раньше _refresh_admin_flag ходил в Bitrix (user.admin) при каждой выдаче токена,
а initApp() стоит в onMounted каждой страницы — то есть на одно открытие вкладки
задачи приходилось два блокирующих REST-вызова, занимавших слоты gunicorn.
"""
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from .models import Bitrix24Account
from .views import ADMIN_FLAG_TTL, _refresh_admin_flag


def _make_account(**overrides) -> Bitrix24Account:
    defaults = dict(
        b24_user_id=1,
        member_id="member-ttl",
        domain_url="ttl.bitrix24.ru",
        status="L",
        application_version=1,
        is_b24_user_admin=False,
    )
    defaults.update(overrides)
    return Bitrix24Account.objects.create(**defaults)


class AdminFlagTtlTest(TestCase):
    def setUp(self):
        self.account = _make_account()

    def _patched_client(self, is_admin=True):
        """Подменяет account.client так, чтобы user.admin вернул заданный ответ."""
        call_method = MagicMock(return_value={"result": is_admin})
        client = MagicMock()
        client._bitrix_token.call_method = call_method
        return patch.object(Bitrix24Account, "client", property(lambda _self: client)), call_method

    def test_first_call_hits_bitrix_and_stamps_time(self):
        patcher, call_method = self._patched_client(is_admin=True)
        with patcher:
            _refresh_admin_flag(self.account)

        call_method.assert_called_once_with("user.admin", {})
        self.account.refresh_from_db()
        self.assertTrue(self.account.is_b24_user_admin)
        self.assertIsNotNone(self.account.admin_flag_checked_at)

    def test_second_call_within_ttl_does_not_hit_bitrix(self):
        self.account.admin_flag_checked_at = timezone.now()
        self.account.save(update_fields=["admin_flag_checked_at"])

        patcher, call_method = self._patched_client()
        with patcher:
            _refresh_admin_flag(self.account)

        call_method.assert_not_called()

    def test_call_after_ttl_expiry_hits_bitrix_again(self):
        self.account.admin_flag_checked_at = timezone.now() - ADMIN_FLAG_TTL - timedelta(minutes=1)
        self.account.save(update_fields=["admin_flag_checked_at"])

        patcher, call_method = self._patched_client()
        with patcher:
            _refresh_admin_flag(self.account)

        call_method.assert_called_once_with("user.admin", {})

    def test_force_bypasses_ttl(self):
        """Установка приложения сверяет флаг всегда."""
        self.account.admin_flag_checked_at = timezone.now()
        self.account.save(update_fields=["admin_flag_checked_at"])

        patcher, call_method = self._patched_client()
        with patcher:
            _refresh_admin_flag(self.account, force=True)

        call_method.assert_called_once_with("user.admin", {})

    def test_flag_change_is_persisted(self):
        patcher, _ = self._patched_client(is_admin=True)
        with patcher:
            _refresh_admin_flag(self.account)

        self.account.refresh_from_db()
        self.assertTrue(self.account.is_b24_user_admin)

    def test_bitrix_failure_keeps_previous_value_and_does_not_stamp(self):
        """Неудачная сверка не должна «залипать» на весь TTL."""
        self.account.is_b24_user_admin = True
        self.account.save(update_fields=["is_b24_user_admin"])

        client = MagicMock()
        client._bitrix_token.call_method.side_effect = RuntimeError("bitrix down")
        with patch.object(Bitrix24Account, "client", property(lambda _self: client)):
            _refresh_admin_flag(self.account)

        self.account.refresh_from_db()
        self.assertTrue(self.account.is_b24_user_admin, "прежнее значение сохраняется")
        self.assertIsNone(
            self.account.admin_flag_checked_at,
            "отметка не ставится, иначе следующая сверка отложится на весь TTL",
        )

    def test_failure_does_not_block_next_attempt(self):
        client = MagicMock()
        client._bitrix_token.call_method.side_effect = RuntimeError("bitrix down")
        with patch.object(Bitrix24Account, "client", property(lambda _self: client)):
            _refresh_admin_flag(self.account)

        patcher, call_method = self._patched_client(is_admin=True)
        with patcher:
            _refresh_admin_flag(self.account)

        call_method.assert_called_once_with("user.admin", {})
