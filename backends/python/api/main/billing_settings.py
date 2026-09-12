"""Настройки счёта и акта и серверная проверка прав «выставлять».

Настройки лежат в ОБЩЕЙ конфигурации приложения (app.option портала,
ConfigurationService) — параллельный механизм не заводим. Сюда попадают:

- ``billing_allow_open_period`` — разрешить выставление за незакрытый месяц;
- ``billing_accountants`` — список id пользователей «Бухгалтерия»;
- ``billing_act_template_id`` — выбранный шаблон АКТА генератора документов;
- ``billing_invoice_template_id`` — выбранный шаблон печатной формы СЧЁТА;
- ``billing_our_company_id`` / ``billing_our_company_name`` — наше юрлицо, от
  которого выставляются все счета;
- ``billing_line_variant`` — вариант наполнения счёта, который мастер
  подставляет при открытии: ``task`` | ``project`` | ``employee`` | ``single``;
- ``billing_line_template`` и ``billing_line_template_{project,employee,single}``
  — формулировка строки, СВОЯ У КАЖДОГО варианта. Один общий шаблон не годится:
  «{задача}, {месяц}» в счёте на одну строку читается как «Услуги по договору,
  август 2026»;
- ``billing_service_name`` — текст услуги для подстановки ``{услуга}``
  («Разработка»);
- ``billing_line_task_level`` — уровень задачи в строке: сама задача или её
  родитель верхнего уровня.

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

from .billing_line_template import (
    DEFAULT_LINE_TEMPLATE,
    DEFAULT_LINE_VARIANT,
    DEFAULT_SERVICE_NAME,
    LINE_TEMPLATE_SETTING_KEYS,
    LINE_VARIANTS,
    TASK_LEVEL_TASK,
    TASK_LEVELS,
    default_line_template,
    normalize_line_template,
    normalize_line_variant,
    normalize_service_name,
)
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
        "invoice_template_id": 0,
        "our_company_id": "",
        "our_company_name": "",
        # Формулировка и уровень задачи — сторона НЕ строгая: при недоступной
        # конфигурации счёт всё равно должен собираться, просто по значениям
        # по умолчанию. Пустой шаблон оставил бы строки счёта без названия,
        # а это хуже, чем «как по умолчанию».
        "line_variant": DEFAULT_LINE_VARIANT,
        "line_template": DEFAULT_LINE_TEMPLATE,
        "line_templates": {
            variant: default_line_template(variant) for variant in LINE_VARIANTS
        },
        "service_name": DEFAULT_SERVICE_NAME,
        "task_level": TASK_LEVEL_TASK,
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

    try:
        invoice_template_id = int(config.get("billing_invoice_template_id") or 0)
    except (TypeError, ValueError):
        invoice_template_id = 0

    our_company_id = _text(config.get("billing_our_company_id"))

    task_level = _text(config.get("billing_line_task_level")).lower()
    if task_level not in TASK_LEVELS:
        task_level = TASK_LEVEL_TASK

    return {
        "allow_open_period": bool(config.get("billing_allow_open_period")),
        "accountants": accountants,
        "act_template_id": template_id,
        # Ноль — «шаблон не выбран», и это рабочее состояние: печатную форму
        # счёта приложение НЕ угадывает по названию (под «счёт» подходят и
        # счёт-фактура, и УПД), поэтому без настройки кнопка печати честно
        # отказывает, а не печатает случайный документ.
        "invoice_template_id": invoice_template_id,
        "our_company_id": our_company_id,
        # Название без идентификатора бессмысленно: выставлять счёт по одному
        # названию нельзя, а показывать «настройка задана» при пустом id —
        # врать. Поэтому имя читается только вместе с id.
        "our_company_name": _text(config.get("billing_our_company_name")) if our_company_id else "",
        "line_variant": normalize_line_variant(config.get("billing_line_variant")),
        # Одиночный ключ остаётся формулировкой варианта «по задачам»: под
        # ним она уже лежит в конфигурации порталов, и новый ключ с суффиксом
        # «_task» стёр бы настроенный текст.
        "line_template": normalize_line_template(
            config.get("billing_line_template"), "task",
        ),
        "line_templates": {
            variant: normalize_line_template(config.get(key), variant)
            for variant, key in LINE_TEMPLATE_SETTING_KEYS.items()
        },
        "service_name": normalize_service_name(config.get("billing_service_name")),
        "task_level": task_level,
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


# Ключи настроек с шаблонами генератора документов: значение — как называть
# шаблон в тексте ошибки. Порядок важен только для предсказуемости сообщения.
TEMPLATE_SETTING_KEYS = (
    ("billing_act_template_id", "акта"),
    ("billing_invoice_template_id", "счёта"),
)


def has_selected_templates(config: Any) -> bool:
    """Есть ли в конфигурации хоть один выбранный шаблон.

    Нужна ровно для одного: не читать прежнюю конфигурацию с портала
    (app.option.get — живой REST-вызов), когда сохраняют что-то, не имеющее
    к шаблонам отношения. Сохранение сопоставления полей смарт-процесса не
    должно платить за проверку настройки, которой в нём нет.
    """
    if not isinstance(config, dict):
        return False
    for key, _title in TEMPLATE_SETTING_KEYS:
        try:
            if int(config.get(key) or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def changed_template_ids(new_config: Any, old_config: Any) -> Dict[str, int]:
    """Шаблоны, которые в сохраняемой конфигурации ИЗМЕНИЛИСЬ (и не нулевые).

    Проверять живьём надо только их. Иначе каждое сохранение любой настройки
    приложения — сопоставления полей смарт-процесса, например — платило бы
    двумя REST-вызовами к порталу за проверку того, что и так не менялось.
    Снятый шаблон (0) тоже не проверяется: «не выбран» проверять не в чем.
    """
    def read(source: Any, key: str) -> int:
        if not isinstance(source, dict):
            return 0
        try:
            return int(source.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    changed: Dict[str, int] = {}
    for key, _title in TEMPLATE_SETTING_KEYS:
        value = read(new_config, key)
        if value and value != read(old_config, key):
            changed[key] = value
    return changed


def validate_template_settings(account, new_config: Any, old_config: Any, client: Optional[Any] = None):
    """Живая проверка выбранных шаблонов. Возвращает BillingError или None.

    Зачем вообще проверять. Список шаблонов приезжает с портала в момент
    открытия настроек, а сохраняют их позже — шаблон могли за это время
    удалить. Сохранённый мёртвый id ведёт себя хуже пустого: печать
    отказывает уже в момент, когда счёт клиенту нужен, и по коду
    act_generation_failed непонятно, что дело в настройке.

    Ошибку НЕ поднимаем исключением: вызывающая вьюха сама решает, вернуть
    400 или проглотить. Недоступный портал (documentgenerator_unavailable)
    сохранению не мешает — это ответ про портал, а не про настройку, и
    запирать настройки приложения из-за отключённого генератора документов
    нельзя.
    """
    from .billing_crm_service import BillingCrmService

    changed = changed_template_ids(new_config, old_config)
    if not changed:
        return None

    service = BillingCrmService(account, client=client)
    for key, title in TEMPLATE_SETTING_KEYS:
        template_id = changed.get(key)
        if not template_id:
            continue
        try:
            service.get_template(template_id)
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", "")
            if code == "billing_template_not_found":
                from .billing_service import BillingError

                return BillingError(
                    f"Шаблон {title} (id {template_id}) на портале не найден — его удалили "
                    "или он принадлежал другому порталу. Выберите другой шаблон и сохраните "
                    "настройки снова.",
                    "billing_template_not_found",
                    extra={"setting": key, "template_id": template_id},
                )
            # Портал недоступен — настройки всё равно сохраняем. Логируем, чтобы
            # причина не потерялась: «сохранили непроверенным» должно быть видно.
            logger.warning(
                "validate_template_settings: шаблон %s=%s не проверен: %s", key, template_id, exc
            )
    return None
