"""Rate limiting decorator using Django's cache framework.

Algorithm: fixed window.
  - cache.add(key, 0, timeout=window) — атомарно создаёт счётчик, если его нет
    (ключ отсутствует или истёк), возвращает True при успехе.
  - cache.incr(key) — атомарно увеличивает счётчик.

Ограничение LocMemCache: счётчик хранится в памяти процесса.
При запуске нескольких воркеров (gunicorn с >1 worker) у каждого своя копия,
и фактический предел будет ×N_workers.  Это приемлемый первый барьер.
При переходе на Redis (django-redis) поведение станет точным — код менять не нужно.

Ключи:
  key="account"    — используется ПОСЛЕ @auth_required;
                     ключ кэша: rl:<scope>:acct:<account_pk>
  key="ip_domain"  — используется ДО/БЕЗ @auth_required (get_token);
                     IP берётся из X-Forwarded-For (первый элемент) или REMOTE_ADDR;
                     domain — из тела запроса:
                       1) request.data["DOMAIN"/"domain"] — если @collect_request_data уже отработал;
                       2) json.loads(request.body)["DOMAIN"/"domain"] — фолбэк, когда rate_limit
                          стоит ВЫШЕ @auth_required и request.data ещё не заполнен;
                       3) request.POST["DOMAIN"/"domain"] — для form-encoded;
                       4) пустая строка — если тело кривое/отсутствует; тогда ключ деградирует
                          до IP-only, что для защиты от перебора достаточно.
                     ключ кэша: rl:<scope>:ip:<ip>:<domain>
"""

import json
from functools import wraps

from django.core.cache import cache
from django.http import JsonResponse, HttpRequest


def rate_limit(scope: str, max_requests: int, window_seconds: int, key: str):
    """Декоратор ограничения частоты запросов.

    Параметры:
        scope         — логическая группа (например "get_token", "sync", "export").
        max_requests  — максимальное количество запросов в окно.
        window_seconds — длительность окна в секундах.
        key           — стратегия формирования ключа:
                        "account"   — по account.pk (нужен request.bitrix24_account).
                        "ip_domain" — по IP + domain из тела запроса.

    Применение (пример):
        @auth_required
        @rate_limit("sync", 6, 60, key="account")
        def my_view(request): ...
    """
    if key not in ("account", "ip_domain"):
        raise ValueError(f"rate_limit: unknown key strategy {key!r}. Use 'account' or 'ip_domain'.")

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request: HttpRequest, *args, **kwargs):
            cache_key = _build_cache_key(scope, key, request)

            # cache.add returns True when the key was newly created (didn't exist).
            # If False — key already existed; incr won't reset the TTL (fixed window).
            cache.add(cache_key, 0, timeout=window_seconds)
            count = cache.incr(cache_key)

            if count > max_requests:
                return JsonResponse(
                    {"error": "Слишком много запросов, повторите через минуту"},
                    status=429,
                )

            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


def _build_cache_key(scope: str, key: str, request: HttpRequest) -> str:
    if key == "account":
        account = getattr(request, "bitrix24_account", None)
        account_pk = account.pk if account is not None else "anon"
        return f"rl:{scope}:acct:{account_pk}"

    # key == "ip_domain"
    ip = _get_client_ip(request)
    domain = _get_domain_from_request(request)
    return f"rl:{scope}:ip:{ip}:{domain}"


def _get_client_ip(request: HttpRequest) -> str:
    """Возвращает IP клиента: первый адрес из X-Forwarded-For или REMOTE_ADDR."""
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _get_domain_from_request(request: HttpRequest) -> str:
    """Извлекает domain из тела запроса.

    Порядок попыток:
    1. request.data — если @collect_request_data уже отработал (rate_limit стоит НИЖЕ auth_required).
    2. json.loads(request.body) — фолбэк для случая, когда rate_limit стоит ВЫШЕ auth_required
       и request.data ещё не заполнен (именно так работает get_token после исправления).
    3. request.POST — для form-encoded запросов.
    4. Пустая строка — при любой ошибке разбора; ключ деградирует до IP-only,
       что для защиты от перебора достаточно и не позволяет обойти лимит сменой domain.
    """
    # 1. request.data (populated by @collect_request_data)
    data = getattr(request, "data", None)
    if data and isinstance(data, dict):
        domain = data.get("DOMAIN") or data.get("domain") or ""
        if domain:
            return str(domain).strip()

    # 2. Fallback: parse request.body as JSON directly
    try:
        body = request.body
        if body:
            parsed = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
            if isinstance(parsed, dict):
                domain = parsed.get("DOMAIN") or parsed.get("domain") or ""
                if domain:
                    return str(domain).strip()
    except Exception:  # noqa: BLE001 — malformed body → fall through to empty string
        pass

    # 3. Fallback to POST for form-encoded requests
    domain = request.POST.get("DOMAIN") or request.POST.get("domain") or ""
    return str(domain).strip()
