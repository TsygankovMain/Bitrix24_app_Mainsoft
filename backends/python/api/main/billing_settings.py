"""Настройки счёта и акта и серверная проверка прав «выставлять».

Настройки лежат в ОБЩЕЙ конфигурации приложения (app.option портала,
ConfigurationService) — параллельный механизм не заводим. Сюда попадают:

- ``billing_allow_open_period`` — разрешить выставление за незакрытый месяц;
- ``billing_accountants`` — список id пользователей «Бухгалтерия»;
- ``billing_act_template_id`` — заранее выбранный шаблон акта генератора;
- ``billing_our_company_id`` / ``billing_our_company_name`` — наше юрлицо, от
  которого выставляются все счета.

Про «наше юрлицо». До настройки оно бралось из карточки проекта
(``ProjectCard.our_legal_entity_id``), а карточки приходят с портала
синхронизацией: поправить их в нашей БД нельзя — следующий обмен вернёт
прежние значения. На боевом портале там встречаются идентификаторы компаний,
которые своими юрлицами вообще не являются. Поэтому настройка приложения
ПЕРЕКРЫВАЕТ карточку, а не дополняет её.

Выключатель ПОДПИСКИ здесь не живёт принципиально: он на нашем сервере
(PortalFeature), потому что app.option портала пишется токеном приложения,
то есть из консоли браузера.

Права. Общего серверного гейта по ролям в приложении нет (решение владельца
продукта от 11.06.2026), точечные исключения — закрытие месяца
(@admin_required) и теперь выставление: это операции того же класса, они
превращаются в деньги клиента. Проверка: администратор портала ИЛИ
пользователь из списка «Бухгалтерия».

Администратор проходит БЕЗ обращения к порталу — флаг is_b24_user_admin уже
в нашей БД. Живой app.option.get нужен только для не-администратора, иначе
самая частая проверка платила бы за REST-вызов на каждый запрос.
"""

import logging
from functools import wraps
from typing import Any, Dict, List, Optional

from django.http import JsonResponse

from .configuration_service import ConfigurationService

logger = logging.getLogger(__name__)


def _text(value: Optional[Any]) -> str:
    """Строка настройки: None и строковое 'None' — это пусто.

    str(None) == 'None', и такой «идентификатор» выглядел бы как заданная
    настройка, уводя счёт к юрлицу, которого нет.
    """
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"none", "null", "undefined"} else text


def load_billing_settings(account, client: Optional[Any] = None) -> Dict[str, Any]:
    """Разбор настроек счёта из конфигурации приложения.

    Сбой чтения конфигурации НЕ роняет запрос: возвращаются значения по
    умолчанию — «открытый период нельзя, бухгалтеров нет». Это строгая
    сторона: недоступный портал не должен молча разрешать то, что запрещено.
    """
    defaults = {
        "allow_open_period": False,
        "accountants": [],
        "act_template_id": 0,
        "our_company_id": "",
        "our_company_name": "",
    }
    try:
        service = ConfigurationService(client or account.client, account)
        config = service.get_configuration_sync()
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_billing_settings: не удалось прочитать конфигурацию: %s", exc)
        return defaults

    if not isinstance(config, dict):
        return defaults

    accountants: List[str] = []
    for item in config.get("billing_accountants") or []:
        if item is None:
            continue
        text = str(item).strip()
        if text and text not in accountants:
            accountants.append(text)

    try:
        template_id = int(config.get("billing_act_template_id") or 0)
    except (TypeError, ValueError):
        template_id = 0

    our_company_id = _text(config.get("billing_our_company_id"))

    return {
        "allow_open_period": bool(config.get("billing_allow_open_period")),
        "accountants": accountants,
        "act_template_id": template_id,
        "our_company_id": our_company_id,
        # Название без идентификатора бессмысленно: выставлять счёт по одному
        # названию нельзя, а показывать «настройка задана» при пустом id —
        # врать. Поэтому имя читается только вместе с id.
        "our_company_name": _text(config.get("billing_our_company_name")) if our_company_id else "",
    }


def can_manage_billing(account, client: Optional[Any] = None) -> bool:
    if account is None:
        return False
    if getattr(account, "is_b24_user_admin", False):
        return True
    user_id = str(getattr(account, "b24_user_id", "") or "").strip()
    if not user_id:
        return False
    return user_id in load_billing_settings(account, client).get("accountants", [])


def billing_manager_required(view_func):
    """Серверный гейт «выставлять и отменять». Применять ПОСЛЕ @auth_required."""

    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        account = getattr(request, "bitrix24_account", None)
        if not can_manage_billing(account):
            return JsonResponse(
                {
                    "error": (
                        "Выставлять и отменять счета может администратор портала "
                        "или сотрудник из списка «Бухгалтерия» в настройках приложения."
                    ),
                    "code": "billing_forbidden",
                },
                status=403,
            )
        return view_func(request, *args, **kwargs)

    return wrapped
