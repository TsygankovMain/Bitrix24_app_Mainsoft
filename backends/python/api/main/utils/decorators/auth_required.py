import logging
from functools import wraps
from http import HTTPStatus
from typing import cast

import jwt

from django.http import JsonResponse, HttpRequest

from b24pysdk.bitrix_api.credentials import OAuthPlacementData
from b24pysdk.error import BitrixValidationError
from b24pysdk.utils.types import JSONDict

from ...models import Bitrix24Account
from .collect_request_data import collect_request_data

logger = logging.getLogger(__name__)


def _normalize_oauth_placement_payload(raw_payload: JSONDict) -> JSONDict:
    payload = dict(raw_payload or {})

    def pick(*keys):
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                return value
        return None

    domain_raw = pick("DOMAIN", "domain")
    if domain_raw not in (None, ""):
        domain_str = str(domain_raw).strip()
        if domain_str.startswith("https://"):
            payload["PROTOCOL"] = payload.get("PROTOCOL") or 1
            domain_str = domain_str[len("https://"):]
        elif domain_str.startswith("http://"):
            payload["PROTOCOL"] = payload.get("PROTOCOL") or 0
            domain_str = domain_str[len("http://"):]
        payload["DOMAIN"] = domain_str.rstrip("/")

    auth_id = pick("AUTH_ID", "auth_id", "access_token", "AUTH")
    if auth_id not in (None, ""):
        payload["AUTH_ID"] = auth_id

    refresh_id = pick("REFRESH_ID", "refresh_id", "refresh_token", "REFRESH_TOKEN")
    if refresh_id not in (None, ""):
        payload["REFRESH_ID"] = refresh_id

    auth_expires = pick("AUTH_EXPIRES", "auth_expires", "expires_in", "expires")
    if auth_expires not in (None, ""):
        payload["AUTH_EXPIRES"] = auth_expires

    member_id = pick("member_id", "MEMBER_ID")
    if member_id not in (None, ""):
        payload["member_id"] = member_id

    status = pick("status", "STATUS")
    if status not in (None, ""):
        payload["status"] = status

    protocol = pick("PROTOCOL", "protocol")
    if protocol not in (None, ""):
        payload["PROTOCOL"] = protocol

    lang = pick("LANG", "lang")
    if lang not in (None, ""):
        payload["LANG"] = lang

    app_sid = pick("APP_SID", "app_sid")
    if app_sid not in (None, ""):
        payload["APP_SID"] = app_sid

    return cast(JSONDict, payload)


def auth_required(view_func):
    @wraps(view_func)
    @collect_request_data
    def wrapped(request: HttpRequest, *args, **kwargs):
        auth = request.headers.get("Authorization")

        if isinstance(auth, str) and auth.lower().startswith("bearer "):
            jwt_token = auth[len("bearer "):]

            try:
                request.bitrix24_account = Bitrix24Account.get_from_jwt_token(jwt_token)

            except Bitrix24Account.DoesNotExist:
                return JsonResponse({"error": "Invalid JWT token"}, status=HTTPStatus.UNAUTHORIZED)

            except jwt.ExpiredSignatureError:
                return JsonResponse({"error": "JWT token has expired"}, status=HTTPStatus.UNAUTHORIZED)

            except jwt.InvalidTokenError:
                return JsonResponse({"error": "Invalid JWT token"}, status=HTTPStatus.UNAUTHORIZED)

            except BitrixValidationError as error:
                return JsonResponse({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)

        else:
            # Create OAuthData and pass it in the request
            try:
                oauth_payload = _normalize_oauth_placement_payload(cast(JSONDict, request.data))
                oauth_placement_data = OAuthPlacementData.from_dict(oauth_payload)
                request.bitrix24_account, _ = Bitrix24Account.update_or_create_from_oauth_placement_data(oauth_placement_data)

            except BitrixValidationError as error:
                return JsonResponse({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            except Exception:
                logger.exception("Unexpected error during OAuth authentication")
                return JsonResponse({"error": "Внутренняя ошибка сервера"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        return view_func(request, *args, **kwargs)

    return wrapped
