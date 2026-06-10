from functools import wraps
from http import HTTPStatus

from django.http import JsonResponse, HttpRequest


def admin_required(view_func):
    """Restrict a view to Bitrix24 portal administrators.

    Must be applied *after* ``@auth_required`` (i.e. closer to the function) so
    that ``request.bitrix24_account`` is already populated. The role is read from
    the account's ``is_b24_user_admin`` flag, which ``get_token`` keeps in sync
    with the Bitrix ``user.admin`` method.
    """

    @wraps(view_func)
    def wrapped(request: HttpRequest, *args, **kwargs):
        account = getattr(request, "bitrix24_account", None)

        if account is None or not getattr(account, "is_b24_user_admin", False):
            return JsonResponse({"error": "Недостаточно прав"}, status=HTTPStatus.FORBIDDEN)

        return view_func(request, *args, **kwargs)

    return wrapped
