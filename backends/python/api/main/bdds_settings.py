"""Настройки функции «БДДС по проектам»: пороги статуса и уведомления.

Живут в ОБЩЕЙ конфигурации приложения (app.option портала,
ConfigurationService) — параллельный механизм не заводим, ровно как у
«Счёта и акта» (см. billing_settings).

Почему ключи НЕ добавлены в ConfigurationService._get_default_configuration.
``_merge_with_defaults`` кладёт defaults и накрывает их сохранённым
значением (``merged.update(config)``), поэтому незнакомые ключи проходят
через нормализацию нетронутыми и сохраняются как есть. Значит для новых
настроек достаточно СВОЕГО нормализатора — этого, — и экран настроек с
сервером уже совместим. Это осознанный выбор: configuration_service.py
правится сейчас и под «Счёт и акт», и лишняя правка общего файла — лишний
конфликт без выигрыша. Если БДДС когда-нибудь понадобится значение по
умолчанию НА СЕРВЕРЕ раньше первого сохранения — оно и так здесь.

Выключатель ПОДПИСКИ здесь не живёт принципиально: он на нашем сервере
(модель PortalFeature), потому что app.option портала пишется токеном
приложения, то есть из консоли браузера.

Про пороги. Сегодня 80 % и 100 % зашиты константами в
ProjectBudgetService. Порог — это управленческое решение клиента («риск с
восьмидесяти» у всех разный), поэтому он обязан быть настройкой. Но
трактовка «непонятное значение = значение по умолчанию» здесь строгая:
порог 0 % сделал бы «Перерасходом» каждый проект, и разбираться в этом
человек стал бы уже после рассылки уведомлений.
"""

import logging
from typing import Any, Dict, List, Optional

from .configuration_service import ConfigurationService

logger = logging.getLogger(__name__)

#: Порог «Риск»: процент освоения, с которого проект попадает в жёлтую зону.
DEFAULT_RISK_THRESHOLD_PERCENT = 80.0
#: Порог «Перерасход»: процент освоения, выше которого зона красная.
DEFAULT_OVERRUN_THRESHOLD_PERCENT = 100.0
#: Порог поддержки: убыток меньше этого — «Граница», больше — «Минус», ₽.
DEFAULT_SUPPORT_BOUNDARY_AMOUNT = 100000.0

#: Пауза между двумя одинаковыми уведомлениями по одному проекту, часов.
DEFAULT_NOTIFY_COOLDOWN_HOURS = 12

BDDS_SETTINGS_DEFAULTS: Dict[str, Any] = {
    "notifications_enabled": True,
    "risk_threshold_percent": DEFAULT_RISK_THRESHOLD_PERCENT,
    "overrun_threshold_percent": DEFAULT_OVERRUN_THRESHOLD_PERCENT,
    "support_boundary_amount": DEFAULT_SUPPORT_BOUNDARY_AMOUNT,
    "notify_cooldown_hours": DEFAULT_NOTIFY_COOLDOWN_HOURS,
    "notify_user_ids": [],
}

#: Ключи в app.option портала. Префикс bdds_ — чтобы не пересечься с billing_.
CONFIG_KEYS = {
    "notifications_enabled": "bdds_notifications_enabled",
    "risk_threshold_percent": "bdds_risk_threshold_percent",
    "overrun_threshold_percent": "bdds_overrun_threshold_percent",
    "support_boundary_amount": "bdds_support_boundary_amount",
    "notify_cooldown_hours": "bdds_notify_cooldown_hours",
    "notify_user_ids": "bdds_notify_user_ids",
}


def _bool(value: Any, default: bool) -> bool:
    """app.option отдаёт всё строками: bool('false') истинно, поэтому разбор свой."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _positive_float(value: Any, default: float) -> float:
    """Число больше нуля либо значение по умолчанию. Мусор порогом не становится."""
    try:
        parsed = float(str(value).strip().replace(",", ".")) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed or parsed <= 0:  # NaN тоже сюда
        return default
    return round(parsed, 2)


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _id_list(value: Any) -> List[str]:
    """Идентификаторы пользователей: строками, без пустых, 'None' и дублей."""
    if value is None:
        return []
    if isinstance(value, (str, int)):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    result: List[str] = []
    for item in value:
        if item is None:
            continue
        text = str(item).strip()
        if not text or text.lower() in {"none", "null", "undefined"} or text in result:
            continue
        result.append(text)
    return result


def _pick(config: Dict[str, Any], key: str) -> Any:
    """Значение настройки по каноническому имени ИЛИ по ключу app.option.

    Нормализация обязана быть ИДЕМПОТЕНТНОЙ. Через неё проходят два вида
    словарей: сырая конфигурация портала (ключи ``bdds_*``) и уже
    нормализованные настройки, которые передают друг другу сервисы
    (``BddsService`` -> ``ProjectBudgetService``, вьюха -> нотификатор). Пока
    читались только ключи ``bdds_*``, второй прогон молча возвращал значения
    по умолчанию: настройки портала доходили до сервиса и терялись на
    следующем шаге — самый неприятный класс дефекта, потому что всё
    «работает», просто цифры не те.
    """
    if key in config:
        return config.get(key)
    return config.get(CONFIG_KEYS[key])


def normalize_bdds_settings(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Конфигурация приложения -> настройки БДДС со здравыми значениями.

    На входе и сырая конфигурация портала, и уже нормализованные настройки
    (см. ``_pick``): функция идемпотентна.

    Инвариант, который держится здесь, а не в вызывающем коде: порог риска
    НЕ БОЛЬШЕ порога перерасхода. Настройка «риск 120 %, перерасход 100 %»
    не сломала бы код, но сделала бы зону «Риск» недостижимой: статус
    считается сверху вниз, и всё, что выше перерасхода, стало бы
    «Перерасходом». Такую пару чиним, а не отвергаем: человек почти всегда
    перепутал поля местами, и запрет со сообщением он увидит позже, чем
    ошибку в отчёте.
    """
    config = raw if isinstance(raw, dict) else {}
    overrun = _positive_float(
        _pick(config, "overrun_threshold_percent"),
        DEFAULT_OVERRUN_THRESHOLD_PERCENT,
    )
    risk = _positive_float(
        _pick(config, "risk_threshold_percent"),
        DEFAULT_RISK_THRESHOLD_PERCENT,
    )
    if risk > overrun:
        risk, overrun = overrun, risk

    return {
        "notifications_enabled": _bool(
            _pick(config, "notifications_enabled"),
            BDDS_SETTINGS_DEFAULTS["notifications_enabled"],
        ),
        "risk_threshold_percent": risk,
        "overrun_threshold_percent": overrun,
        "support_boundary_amount": _positive_float(
            _pick(config, "support_boundary_amount"),
            DEFAULT_SUPPORT_BOUNDARY_AMOUNT,
        ),
        "notify_cooldown_hours": _positive_int(
            _pick(config, "notify_cooldown_hours"),
            DEFAULT_NOTIFY_COOLDOWN_HOURS,
        ),
        "notify_user_ids": _id_list(_pick(config, "notify_user_ids")),
    }


def load_bdds_settings(account, client: Optional[Any] = None) -> Dict[str, Any]:
    """Настройки БДДС портала. Сбой чтения конфигурации НЕ роняет запрос.

    Значения по умолчанию здесь — не «строгая сторона», а ЕДИНСТВЕННАЯ
    осмысленная: без порогов метрики бюджета не посчитать вовсе, а показать
    вместо цифр ошибку портала на экране, где всё остальное считается из
    нашей БД, — хуже, чем показать цифры по 80/100.
    """
    try:
        service = ConfigurationService(client or account.client, account)
        config = service.get_configuration_sync()
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_bdds_settings: не удалось прочитать конфигурацию: %s", exc)
        return normalize_bdds_settings(None)
    return normalize_bdds_settings(config)
