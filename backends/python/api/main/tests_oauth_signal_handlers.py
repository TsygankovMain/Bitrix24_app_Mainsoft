"""Регресс на два прод-бага в обработчиках сигналов Bitrix-SDK (main/models.py).

Без фикса эти колбэки падают, когда их реально дёргает SDK при обновлении
OAuth-токена/смене домена портала:

- on_oauth_token_renewed_event: `event...expires` — datetime, а поле
  `expires` объявлено IntegerField -> TypeError: Field 'expires' expected a
  number but got datetime.datetime(...). Из-за этого обновлённый токен НЕ
  сохраняется в БД, и следующий вызов снова уходит с протухшим токеном.
- on_portal_domain_changed_event: save(update_fields=["portal_url"]) — такого
  поля в модели нет (есть domain_url) -> ValueError: ...fields do not exist
  in this model...: portal_url.

Событийные объекты — простые заглушки (SimpleNamespace), структура повторяет
реальную из b24pysdk: event.renewed_oauth_token.oauth_token.{expires,expires_in}
для OAuthTokenRenewedEvent (см. b24pysdk.bitrix_api.credentials.OAuthToken, где
expires: Optional[datetime]).
"""
from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace

from django.test import TestCase

from .models import Bitrix24Account


def _account(**overrides):
    defaults = dict(
        b24_user_id=1, is_b24_user_admin=True, member_id="m-oauth-signal",
        is_master_account=True, domain_url="old.bitrix24.ru",
        status="active", application_version=1,
    )
    defaults.update(overrides)
    return Bitrix24Account.objects.create(**defaults)


def _renewed_token_event(expires, expires_in=3600):
    """Заглушка OAuthTokenRenewedEvent с той же формой атрибутов, что и SDK."""
    oauth_token = SimpleNamespace(
        access_token="new-access-token",
        refresh_token="new-refresh-token",
        expires=expires,
        expires_in=expires_in,
    )
    renewed_oauth_token = SimpleNamespace(oauth_token=oauth_token)
    return SimpleNamespace(renewed_oauth_token=renewed_oauth_token)


class OnOAuthTokenRenewedEventTest(TestCase):
    def test_datetime_expires_is_saved_as_unix_timestamp(self):
        """Прод-кейс: SDK отдаёт expires как datetime (OAuthToken.expires)."""
        account = _account(member_id="m-oauth-dt")
        expires_dt = datetime(2026, 7, 28, 0, 52, 51, tzinfo=dt_timezone.utc)
        event = _renewed_token_event(expires=expires_dt, expires_in=3600)

        account.on_oauth_token_renewed_event(event)

        account.refresh_from_db()
        self.assertEqual(account.expires, int(expires_dt.timestamp()))
        self.assertEqual(account.expires_in, 3600)

    def test_int_expires_is_saved_as_is(self):
        """Устойчивость к случаю, когда expires уже пришёл числом."""
        account = _account(member_id="m-oauth-int")
        expires_ts = 1785285171
        event = _renewed_token_event(expires=expires_ts, expires_in=1800)

        account.on_oauth_token_renewed_event(event)

        account.refresh_from_db()
        self.assertEqual(account.expires, expires_ts)
        self.assertEqual(account.expires_in, 1800)


class OnPortalDomainChangedEventTest(TestCase):
    def test_saves_changed_domain_to_domain_url(self):
        account = _account(member_id="m-domain-signal", domain_url="old.bitrix24.ru")

        account.domain = "new.bitrix24.ru"  # сеттер SDK пишет именно в domain_url
        event = SimpleNamespace(old_domain="old.bitrix24.ru", new_domain="new.bitrix24.ru")
        account.on_portal_domain_changed_event(event)

        account.refresh_from_db()
        self.assertEqual(account.domain_url, "new.bitrix24.ru")
