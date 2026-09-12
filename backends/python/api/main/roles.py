"""Ролевая модель приложения: роли, права и серверная проверка.

ИСТОРИЯ, БЕЗ КОТОРОЙ ЭТОТ ФАЙЛ ЧИТАЕТСЯ НЕПРАВИЛЬНО.
В спринте 1 на 26 эндпоинтов повесили @admin_required — включая отчёты по
часам. Не-администраторы получили 403 на отчётах, которыми пользуются каждый
день, и 11.06.2026 владелец продукта снял серверные проверки ролей целиком.
Отсюда два правила, по которым сделана эта модель:

1. Роли закрывают ДЕНЬГИ и НЕОБРАТИМЫЕ операции, а не работу с часами.
   Отчёты по часам, доска проектов, списание времени, проверка данных и ИНН —
   открыты всем, как и сейчас. Под ролями: суммы (реестр счетов, БДДС,
   начисления и списания), смена ставки проекта, выставление и отмена счетов,
   добавление операций, закрытие месяца, настройки и назначение ролей.
2. Ролевая модель — функция ``roles`` тарифа Pro. На портале без тарифа (или с
   тарифом, выключенным командой off) права ровно те, что были до ролей
   (LEGACY_PERMISSIONS): администратор портала может всё, «Бухгалтерия»
   выставляет счета и заводит операции, закрывает месяц только
   администратор портала, остальное открыто всем.
3. Окончание Pro роли НЕ выключает: пока тариф в «только чтении»,
   billing_features.feature_restrictions_active отвечает True, и права по
   назначенным ролям проверяются как прежде — иначе в день окончания все
   сотрудники разом увидели бы ставки и суммы. Закрывается только ИЗМЕНЕНИЕ
   ролей и их прав — назначение, правка и матрица прав
   (@feature_required(FEATURE_ROLES) на /api/roles/assign и /api/roles/matrix).

Где хранятся роли и почему это нельзя подделать. В нашей БД (PortalRole),
по member_id портала. Прежний список «Бухгалтерия» лежал в app.option портала,
а app.option пишется токеном приложения, который есть у фронта: сотрудник мог
дописать себя в бухгалтерию из консоли браузера. Здесь роль пишет только
сервер по запросу человека с правом ``roles_manage``. Признак «администратор
портала» — is_b24_user_admin, его сервер сам спрашивает у портала методом
user.admin (views._refresh_admin_flag), клиент его не передаёт. Тариф —
PortalSubscription на нашем сервере (billing_features), по REST не пишется.

Права ролей редактируются (экран «Роли и права»). Матрица по умолчанию —
ROLE_PERMISSIONS ниже; портал хранит только отличия от неё
(PortalPermissionMatrix, по member_id, пишет только сервер). Редактор не
может нарушить три правила, и они закреплены здесь, а не в интерфейсе:
  - у «Администратора» всегда есть settings_manage и roles_manage, а
    roles_manage есть ТОЛЬКО у него (LOCKED_CELLS): иначе портал запер бы сам
    себя, или любая роль с правом назначать роли назначила бы себе всё;
  - работа с часами правами не описывается вовсе — в PERMISSIONS её нет, и
    сохранить неизвестное право нельзя (урок июня 2026);
  - зависимые права без базового не сохраняются (PERMISSION_REQUIRES): счета,
    ставка и операции без «видеть суммы» не работают.
Редактирование закрыто, как и назначение ролей, при окончании Pro
(@feature_required(FEATURE_ROLES)); сохранённая матрица при этом действует.

Перенос «Бухгалтерии». Список billing_accountants при первой проверке прав на
портале переносится в роль «Бухгалтерия» (ensure_accountants_imported) и
дальше не читается. Если конфигурацию прочитать не удалось, отметка переноса
не ставится, а права считаются по прежнему списку — иначе недоступный портал
молча лишил бы бухгалтеров прав.
"""

import logging
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Tuple

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone

from .billing_features import (
    ACCESS_FULL,
    FEATURE_ROLES,
    account_subscription_status,
    feature_access_from_status,
    get_feature_state,
    restrictions_active_from_access,
)
from .models import PortalPermissionChange, PortalPermissionMatrix, PortalRole, PortalRoleState

logger = logging.getLogger(__name__)

ROLE_ADMIN = PortalRole.ROLE_ADMIN
ROLE_ACCOUNTANT = PortalRole.ROLE_ACCOUNTANT
ROLE_PROJECT_MANAGER = PortalRole.ROLE_PROJECT_MANAGER
ROLE_EMPLOYEE = PortalRole.ROLE_EMPLOYEE
ROLES = PortalRole.ROLES

# ---------------------------------------------------------------------------
# Права
# ---------------------------------------------------------------------------

PERM_MONEY_VIEW = "money_view"
PERM_RATES_EDIT = "rates_edit"
PERM_BILLING_ISSUE = "billing_issue"
PERM_BILLING_CANCEL = "billing_cancel"
PERM_OPERATIONS_CREATE = "operations_create"
PERM_PERIOD_CLOSE = "period_close"
PERM_SETTINGS_MANAGE = "settings_manage"
PERM_ROLES_MANAGE = "roles_manage"

#: Порядок — порядок строк таблицы «роль → что может» на экране.
PERMISSIONS = (
    PERM_MONEY_VIEW,
    PERM_RATES_EDIT,
    PERM_BILLING_ISSUE,
    PERM_BILLING_CANCEL,
    PERM_OPERATIONS_CREATE,
    PERM_PERIOD_CLOSE,
    PERM_SETTINGS_MANAGE,
    PERM_ROLES_MANAGE,
)

ALL_PERMISSIONS: FrozenSet[str] = frozenset(PERMISSIONS)

ROLE_TITLES = {
    ROLE_ADMIN: "Администратор",
    ROLE_ACCOUNTANT: "Бухгалтерия",
    ROLE_PROJECT_MANAGER: "Руководитель проекта",
    ROLE_EMPLOYEE: "Сотрудник",
}

#: Для кого роль. Что она может, показывает таблица прав: её можно поменять,
#: поэтому здесь нет перечня прав, который разошёлся бы с таблицей.
ROLE_DESCRIPTIONS = {
    ROLE_ADMIN: "Управляет приложением: настройки, роли и права. "
                "Администраторы портала получают эту роль автоматически.",
    ROLE_ACCOUNTANT: "Для тех, кто работает с деньгами: счета и акты, начисления и списания, закрытие месяца.",
    ROLE_PROJECT_MANAGER: "Для руководителей проектов: следить за бюджетами и счетами своих проектов.",
    ROLE_EMPLOYEE: "Роль по умолчанию для всех, кому роль не назначена. "
                   "Списание времени и отчёты по часам открыты всем ролям.",
}

PERMISSION_TITLES = {
    PERM_MONEY_VIEW: "Видеть суммы: счета и акты, БДДС, начисления и списания",
    PERM_RATES_EDIT: "Менять ставку проекта",
    PERM_BILLING_ISSUE: "Выставлять счета, печатать счета и акты",
    PERM_BILLING_CANCEL: "Отменять счета",
    PERM_OPERATIONS_CREATE: "Добавлять начисления и списания",
    PERM_PERIOD_CLOSE: "Закрывать и переоткрывать месяц, исправлять находки проверки",
    PERM_SETTINGS_MANAGE: "Менять настройки приложения и сопоставление полей",
    PERM_ROLES_MANAGE: "Назначать роли",
}

#: Что даёт право — словами, для экрана «Роли и права».
PERMISSION_DESCRIPTIONS = {
    PERM_MONEY_VIEW: "Открывает реестр счетов и актов, бюджеты проектов (БДДС), начисления и списания. "
                     "Без него эти разделы закрыты, суммы не видны.",
    PERM_RATES_EDIT: "Позволяет поменять часовую ставку в карточке проекта. Остальные поля карточки "
                     "правит любой сотрудник.",
    PERM_BILLING_ISSUE: "Позволяет выставить счёт в CRM и напечатать счёт и акт.",
    PERM_BILLING_CANCEL: "Позволяет отменить выставленный счёт — списания снова становятся свободными.",
    PERM_OPERATIONS_CREATE: "Позволяет завести начисление или списание по проекту.",
    PERM_PERIOD_CLOSE: "Позволяет закрыть месяц (после этого часы за него не меняются), открыть его снова "
                       "и исправлять находки проверки данных. Смотреть проверку может любой.",
    PERM_SETTINGS_MANAGE: "Позволяет менять настройки приложения, сопоставление полей и смарт-процессов.",
    PERM_ROLES_MANAGE: "Позволяет назначать роли сотрудникам и менять права ролей в этой таблице.",
}

#: Группы строк таблицы — в порядке PERMISSIONS.
PERMISSION_GROUPS: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("money", "Суммы и ставки", (PERM_MONEY_VIEW, PERM_RATES_EDIT)),
    ("billing", "Счета и акты", (PERM_BILLING_ISSUE, PERM_BILLING_CANCEL)),
    ("operations", "Начисления и списания", (PERM_OPERATIONS_CREATE,)),
    ("period", "Закрытие месяца", (PERM_PERIOD_CLOSE,)),
    ("admin", "Управление приложением", (PERM_SETTINGS_MANAGE, PERM_ROLES_MANAGE)),
)

#: Зависимости: право -> базовые права, без которых оно не работает.
#: Экран при включении зависимого включает базовое, при выключении базового
#: выключает зависимые; сервер матрицу с нарушением не сохраняет.
PERMISSION_REQUIRES: Dict[str, Tuple[str, ...]] = {
    PERM_RATES_EDIT: (PERM_MONEY_VIEW,),
    PERM_BILLING_ISSUE: (PERM_MONEY_VIEW,),
    PERM_BILLING_CANCEL: (PERM_MONEY_VIEW,),
    PERM_OPERATIONS_CREATE: (PERM_MONEY_VIEW,),
}

#: Почему зависимое право не работает без базового.
PERMISSION_REQUIRE_REASONS = {
    PERM_RATES_EDIT: "ставка — это деньги: менять её, не видя сумм, нельзя",
    PERM_BILLING_ISSUE: "счета выставляются из реестра, а он закрыт без права видеть суммы",
    PERM_BILLING_CANCEL: "счёт отменяют в реестре, а он закрыт без права видеть суммы",
    PERM_OPERATIONS_CREATE: "начисления и списания заводятся в разделе БДДС, а он закрыт без права видеть суммы",
}

#: Ячейки, которые редактор не меняет: (роль, право) -> (значение, почему).
LOCKED_CELLS: Dict[Tuple[str, str], Tuple[bool, str]] = {
    (ROLE_ADMIN, PERM_SETTINGS_MANAGE): (
        True,
        "У «Администратора» право менять настройки не снимается: иначе на портале не останется "
        "никого, кто может их поправить.",
    ),
    (ROLE_ADMIN, PERM_ROLES_MANAGE): (
        True,
        "У «Администратора» право назначать роли не снимается: иначе портал запер бы сам себя — "
        "вернуть права было бы некому.",
    ),
    **{
        (role, PERM_ROLES_MANAGE): (
            False,
            "Назначать роли и менять права может только «Администратор»: с этим правом любая роль "
            "назначила бы себе «Администратора» и получила бы всё.",
        )
        for role in (ROLE_ACCOUNTANT, ROLE_PROJECT_MANAGER, ROLE_EMPLOYEE)
    },
}

#: Что открыто всем и в таблицу прав не попадает никогда (урок июня 2026).
ALWAYS_OPEN_WORK = (
    "Списание времени в задачах",
    "Отчёты по часам",
    "Доска проектов",
    "Проверка данных (просмотр)",
)

#: Что может каждая роль ПО УМОЛЧАНИЮ, когда ограничения ролей действуют (Pro
#: или «только чтение» после него). Портал может её поменять — действующая
#: матрица портала: permission_matrix(account).
ROLE_PERMISSIONS: Dict[str, FrozenSet[str]] = {
    ROLE_ADMIN: ALL_PERMISSIONS,
    ROLE_ACCOUNTANT: frozenset({
        PERM_MONEY_VIEW,
        PERM_RATES_EDIT,
        PERM_BILLING_ISSUE,
        PERM_BILLING_CANCEL,
        PERM_OPERATIONS_CREATE,
        PERM_PERIOD_CLOSE,
    }),
    ROLE_PROJECT_MANAGER: frozenset({PERM_MONEY_VIEW}),
    ROLE_EMPLOYEE: frozenset(),
}

#: Права при ВЫКЛЮЧЕННОЙ функции — ровно то, что приложение делало до ролей.
#: Суммы, ставки и настройки сервер тогда не закрывал никому (решение от
#: 11.06.2026), счета и операции — админ портала и «Бухгалтерия», закрытие
#: месяца — только админ портала (@admin_required от 31.08.2026).
_LEGACY_COMMON = frozenset({PERM_MONEY_VIEW, PERM_RATES_EDIT, PERM_SETTINGS_MANAGE})
LEGACY_PERMISSIONS: Dict[str, FrozenSet[str]] = {
    ROLE_ADMIN: ALL_PERMISSIONS,
    ROLE_ACCOUNTANT: _LEGACY_COMMON | {PERM_BILLING_ISSUE, PERM_BILLING_CANCEL, PERM_OPERATIONS_CREATE},
    ROLE_EMPLOYEE: _LEGACY_COMMON,
}


#: Прежние тексты отказов — без действующих ролей человек видит то же, что
#: видел раньше, только с новым адресом настройки.
LEGACY_DENIAL_TEXTS = {
    PERM_BILLING_ISSUE: "Выставлять и отменять счета может администратор портала "
                        "или сотрудник с ролью «Бухгалтерия» (Настройки → Роли и права).",
    PERM_BILLING_CANCEL: "Выставлять и отменять счета может администратор портала "
                         "или сотрудник с ролью «Бухгалтерия» (Настройки → Роли и права).",
    PERM_OPERATIONS_CREATE: "Заводить операции по проектам может администратор портала "
                            "или сотрудник с ролью «Бухгалтерия» (Настройки → Роли и права).",
    PERM_PERIOD_CLOSE: "Закрывать и переоткрывать периоды может только администратор.",
    PERM_ROLES_MANAGE: "Назначать роли может администратор портала.",
}

IMPORT_FAILURE_CACHE_SECONDS = 300
MATRIX_CACHE_SECONDS = 300
MATRIX_LOG_LIMIT = 30
IMPORT_SOURCE = "billing_accountants"


# ---------------------------------------------------------------------------
# Каталог — для экрана настроек
# ---------------------------------------------------------------------------

def _group_of(permission: str) -> str:
    for code, _title, members in PERMISSION_GROUPS:
        if permission in members:
            return code
    return ""


def _matrix_payload(matrix: Mapping[str, FrozenSet[str]]) -> Dict[str, List[str]]:
    """Матрица в JSON: права роли в порядке строк таблицы."""
    return {role: [perm for perm in PERMISSIONS if perm in matrix.get(role, ())] for role in ROLES}


def roles_catalog(account=None) -> Dict[str, Any]:
    """Роли, права и матрица одним ответом. Экран рисует таблицу из него.

    С учёткой — действующая матрица её портала, без — матрица по умолчанию.
    """
    state = matrix_state(account) if account is not None else None
    matrix = state["matrix"] if state else ROLE_PERMISSIONS
    return {
        "roles": [
            {
                "code": code,
                "title": ROLE_TITLES[code],
                "description": ROLE_DESCRIPTIONS[code],
                "customized": matrix.get(code, frozenset()) != ROLE_PERMISSIONS[code],
            }
            for code in ROLES
        ],
        "permissions": [
            {
                "code": code,
                "title": PERMISSION_TITLES[code],
                "description": PERMISSION_DESCRIPTIONS[code],
                "group": _group_of(code),
                "requires": list(PERMISSION_REQUIRES.get(code, ())),
                "requires_reason": PERMISSION_REQUIRE_REASONS.get(code, ""),
            }
            for code in PERMISSIONS
        ],
        "groups": [
            {"code": code, "title": title, "permissions": list(members)}
            for code, title, members in PERMISSION_GROUPS
        ],
        "locks": [
            {"role": role, "permission": perm, "value": value, "reason": reason}
            for (role, perm), (value, reason) in LOCKED_CELLS.items()
        ],
        "always_open": list(ALWAYS_OPEN_WORK),
        "matrix": _matrix_payload(matrix),
        "default_matrix": _matrix_payload(ROLE_PERMISSIONS),
        "legacy_matrix": {code: sorted(perms) for code, perms in LEGACY_PERMISSIONS.items()},
        "revision": state["revision"] if state else 0,
        "updated_at": state["updated_at"] if state else None,
        "updated_by_name": state["updated_by_name"] if state else "",
    }


def roles_with_permission(permission: str, matrix: Optional[Mapping[str, FrozenSet[str]]] = None) -> List[str]:
    source = ROLE_PERMISSIONS if matrix is None else matrix
    return [code for code in ROLES if permission in source.get(code, ())]


def normalize_role(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    return text if text in ROLES else None


def normalize_user_id(value: Any) -> str:
    """Идентификатор пользователя Битрикс24: только цифры, иначе пусто."""
    text = str(value if value is not None else "").strip()
    return text if text.isdigit() and text != "0" else ""


# ---------------------------------------------------------------------------
# Хранение
# ---------------------------------------------------------------------------

def portal_key(account) -> str:
    """Ключ портала. Пустой member_id не должен склеить разные порталы в один."""
    member_id = str(getattr(account, "member_id", "") or "").strip()
    return member_id or f"account:{getattr(account, 'pk', '')}"


def role_queryset(account):
    return PortalRole.objects.filter(member_id=portal_key(account))


def _read_accountants_from_portal(account, client=None) -> List[str]:
    """Прежний список «Бухгалтерия» прямо из app.option. Исключение = не прочитали.

    ConfigurationService.get_configuration_sync здесь не годится: на сбой он
    отвечает конфигурацией по умолчанию, то есть пустым списком, и перенос
    принял бы недоступный портал за «бухгалтеров нет».
    """
    import json

    from .configuration_service import ConfigurationService

    source = client or account.client
    response = source._bitrix_token.call_method("app.option.get", {})
    result = response.get("result", {}) if isinstance(response, dict) else {}
    if not isinstance(result, dict):
        raise ValueError("app.option.get вернул не объект")
    raw = result.get("timestamp_config")
    if not raw:
        return []
    config = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(config, dict):
        return []
    return ConfigurationService._normalize_id_list(config.get("billing_accountants"))


def _legacy_accountants(account, client=None) -> List[str]:
    """Прежний список через настройки счёта — запасной путь, пока перенос не удался."""
    from . import billing_settings

    try:
        return list(billing_settings.load_billing_settings(account, client).get("accountants") or [])
    except Exception:  # noqa: BLE001
        return []


def ensure_accountants_imported(account, client=None) -> bool:
    """Перенести список «Бухгалтерия» в роли. True — перенос есть (сейчас или раньше).

    Уже назначенные роли не перезаписываются: если человеку дали роль на
    экране, прежний список ему её не поменяет.
    """
    key = portal_key(account)
    if PortalRoleState.objects.filter(member_id=key, accountants_imported_at__isnull=False).exists():
        return True

    failure_key = f"roles-import-failed:{key}"
    if cache.get(failure_key):
        return False

    try:
        user_ids = _read_accountants_from_portal(account, client)
    except Exception as exc:  # noqa: BLE001
        logger.warning("roles: список «Бухгалтерия» портала %s не прочитан: %s", key, exc)
        cache.set(failure_key, 1, IMPORT_FAILURE_CACHE_SECONDS)
        return False

    portal = getattr(account, "portal", None)
    try:
        with transaction.atomic():
            state, _created = PortalRoleState.objects.select_for_update().get_or_create(member_id=key)
            if state.accountants_imported_at is not None:
                return True
            for user_id in user_ids:
                if not normalize_user_id(user_id):
                    continue
                PortalRole.objects.get_or_create(
                    member_id=key,
                    b24_user_id=user_id,
                    defaults={
                        "portal": portal,
                        "role": ROLE_ACCOUNTANT,
                        "source": IMPORT_SOURCE,
                    },
                )
            state.accountants_imported_at = timezone.now()
            state.imported_user_ids = user_ids
            state.save(update_fields=["accountants_imported_at", "imported_user_ids", "updated_at"])
    except IntegrityError:
        # Параллельный запрос перенёс раньше нас — результат тот же.
        return PortalRoleState.objects.filter(member_id=key, accountants_imported_at__isnull=False).exists()

    logger.info("roles: портал %s — «Бухгалтерия» перенесена в роли: %s", key, user_ids)
    return True


def stored_role(account, client=None) -> str:
    """Роль из БД (после переноса) либо по прежнему списку, если перенос не удался."""
    user_id = normalize_user_id(getattr(account, "b24_user_id", ""))
    if not user_id:
        return ROLE_EMPLOYEE

    imported = ensure_accountants_imported(account, client)
    row = role_queryset(account).filter(b24_user_id=user_id).first()
    if row is not None and row.role in ROLES:
        return row.role
    if not imported and user_id in _legacy_accountants(account, client):
        return ROLE_ACCOUNTANT
    return ROLE_EMPLOYEE


# ---------------------------------------------------------------------------
# Матрица прав портала
# ---------------------------------------------------------------------------

class PermissionMatrixError(Exception):
    """Матрицу нельзя сохранить: нарушено ограничение, зависимость или версия."""

    def __init__(self, message: str, code: str, status: int = 400, **details: Any):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.details = details

    def as_payload(self) -> Dict[str, Any]:
        return {"error": self.message, "code": self.code, **self.details}


def default_matrix() -> Dict[str, FrozenSet[str]]:
    return {role: frozenset(ROLE_PERMISSIONS[role]) for role in ROLES}


def enforce_matrix_rules(matrix: Mapping[str, Any]) -> Dict[str, FrozenSet[str]]:
    """Привести матрицу к правилам: неизменяемые ячейки и зависимости.

    Для ЧТЕНИЯ сохранённого, а не для сохранения присланного: присланное с
    нарушением отклоняется (validate_permission_matrix), а сохранённое могло
    разойтись с правилами, только если правила поменялись в коде, — тогда
    зависимое право без базового снимается (в сторону «меньше прав»).
    """
    result: Dict[str, set] = {
        role: {perm for perm in (matrix.get(role) or ()) if perm in ALL_PERMISSIONS} for role in ROLES
    }
    for (role, perm), (value, _reason) in LOCKED_CELLS.items():
        if value:
            result[role].add(perm)
        else:
            result[role].discard(perm)
    changed = True
    while changed:
        changed = False
        for role in ROLES:
            for perm in list(result[role]):
                if any(base not in result[role] for base in PERMISSION_REQUIRES.get(perm, ())):
                    if LOCKED_CELLS.get((role, perm), (False, ""))[0]:
                        continue
                    result[role].discard(perm)
                    changed = True
    return {role: frozenset(perms) for role, perms in result.items()}


def apply_overrides(overrides: Any) -> Dict[str, FrozenSet[str]]:
    """Матрица по умолчанию + отличия портала. Мусор в отличиях игнорируется."""
    result = {role: set(ROLE_PERMISSIONS[role]) for role in ROLES}
    if isinstance(overrides, dict):
        for role, cells in overrides.items():
            if role not in result or not isinstance(cells, dict):
                continue
            for perm, granted in cells.items():
                if perm not in ALL_PERMISSIONS or not isinstance(granted, bool):
                    continue
                if granted:
                    result[role].add(perm)
                else:
                    result[role].discard(perm)
    return enforce_matrix_rules(result)


def overrides_from_matrix(matrix: Mapping[str, FrozenSet[str]]) -> Dict[str, Dict[str, bool]]:
    """Отличия матрицы от матрицы по умолчанию — то, что хранится в БД."""
    result: Dict[str, Dict[str, bool]] = {}
    for role in ROLES:
        cells = {}
        for perm in PERMISSIONS:
            granted = perm in matrix.get(role, ())
            if granted != (perm in ROLE_PERMISSIONS[role]):
                cells[perm] = granted
        if cells:
            result[role] = cells
    return result


def matrix_changes(before: Mapping[str, FrozenSet[str]], after: Mapping[str, FrozenSet[str]]) -> List[Dict[str, Any]]:
    """Ячейки, которые поменялись, — в порядке ролей и строк таблицы."""
    changes = []
    for role in ROLES:
        for perm in PERMISSIONS:
            was = perm in before.get(role, ())
            now = perm in after.get(role, ())
            if was != now:
                changes.append({"role": role, "permission": perm, "granted": now})
    return changes


def validate_permission_matrix(raw: Any) -> Dict[str, FrozenSet[str]]:
    """Присланная экраном матрица -> проверенная. Нарушение -> PermissionMatrixError.

    Ничего не «чинит» молча: неизвестное право, снятое у «Администратора»
    право или зависимое право без базового — отказ с объяснением. Экран сам
    включает базовые и выключает зависимые права, так что отказ здесь значит
    запрос мимо экрана или его ошибку.
    """
    if not isinstance(raw, dict):
        raise PermissionMatrixError("Не передана таблица прав.", "matrix_required")

    unknown_roles = sorted(str(role) for role in raw if role not in ROLES)
    if unknown_roles:
        raise PermissionMatrixError(
            f"Такой роли нет: {', '.join(unknown_roles)}.", "unknown_role", roles=unknown_roles,
        )
    missing = [role for role in ROLES if role not in raw]
    if missing:
        raise PermissionMatrixError(
            "В таблице прав должны быть все роли: " + ", ".join(f"«{ROLE_TITLES[r]}»" for r in missing) + ".",
            "matrix_incomplete",
        )

    matrix: Dict[str, FrozenSet[str]] = {}
    for role in ROLES:
        values = raw[role]
        if not isinstance(values, (list, tuple)):
            raise PermissionMatrixError("Права роли передаются списком.", "matrix_invalid", role=role)
        perms = {str(value) for value in values}
        unknown = sorted(perms - ALL_PERMISSIONS)
        if unknown:
            raise PermissionMatrixError(
                f"Права {', '.join(unknown)} нет. Настраиваются только права из таблицы: работа с "
                "часами — списание времени, отчёты, доска проектов, проверка данных — открыта всем "
                "и правами не закрывается.",
                "unknown_permission", role=role, permissions=unknown,
            )
        matrix[role] = frozenset(perms)

    for (role, perm), (value, reason) in LOCKED_CELLS.items():
        if (perm in matrix[role]) != value:
            raise PermissionMatrixError(reason, "permission_locked", role=role, permission=perm)

    for role in ROLES:
        for perm in PERMISSIONS:
            if perm not in matrix[role]:
                continue
            for base in PERMISSION_REQUIRES.get(perm, ()):
                if base not in matrix[role]:
                    raise PermissionMatrixError(
                        f"«{ROLE_TITLES[role]}»: право «{PERMISSION_TITLES[perm]}» не работает без "
                        f"«{PERMISSION_TITLES[base]}» — {PERMISSION_REQUIRE_REASONS.get(perm, '')}.",
                        "permission_dependency", role=role, permission=perm, requires=base,
                    )
    return matrix


def matrix_cache_key(account) -> str:
    return f"roles-permission-matrix:{portal_key(account)}"


def forget_matrix(account) -> None:
    cache.delete(matrix_cache_key(account))
    forget_access(account)


def matrix_state(account) -> Dict[str, Any]:
    """Действующая матрица портала с версией. Кэш сбрасывается при сохранении."""
    key = matrix_cache_key(account)
    cached = cache.get(key)
    if isinstance(cached, dict) and isinstance(cached.get("matrix"), dict):
        return {**cached, "matrix": {role: frozenset(perms) for role, perms in cached["matrix"].items()}}

    row = PortalPermissionMatrix.objects.filter(member_id=portal_key(account)).first()
    matrix = apply_overrides(row.overrides if row else None)
    state = {
        "matrix": matrix,
        "revision": row.revision if row else 0,
        "updated_at": row.updated_at.isoformat() if row and row.revision else None,
        "updated_by_name": row.updated_by_name if row else "",
    }
    cache.set(key, {**state, "matrix": _matrix_payload(matrix)}, MATRIX_CACHE_SECONDS)
    return state


def permission_matrix(account) -> Dict[str, FrozenSet[str]]:
    """Действующая матрица прав портала (при действующих ограничениях ролей)."""
    if account is None:
        return default_matrix()
    return matrix_state(account)["matrix"]


def save_permission_matrix(account, raw_matrix: Any, *, base_revision: Any = None,
                           by_id: str = "", by_name: str = "") -> Dict[str, Any]:
    """Сохранить матрицу портала. Права и тариф проверяет вызывающий.

    ``base_revision`` — версия, которую человек видел на экране. Разошлась —
    отказ matrix_conflict: кто-то сохранил раньше, и молча затирать его правку
    нельзя. Без изменений ничего не пишется и журнал не растёт.
    """
    proposed = validate_permission_matrix(raw_matrix)
    key = portal_key(account)
    try:
        with transaction.atomic():
            row, _created = PortalPermissionMatrix.objects.select_for_update().get_or_create(member_id=key)
            if base_revision not in (None, "") and str(base_revision) != str(row.revision):
                raise PermissionMatrixError(
                    "Права ролей уже поменял другой человек. Обновите страницу и повторите изменения.",
                    "matrix_conflict", status=409, revision=row.revision,
                )
            before = apply_overrides(row.overrides)
            changes = matrix_changes(before, proposed)
            if not changes:
                return {"status": "unchanged", "revision": row.revision, "changes": []}

            row.overrides = overrides_from_matrix(proposed)
            row.revision += 1
            row.updated_by_id = str(by_id or "")
            row.updated_by_name = str(by_name or "")[:255]
            row.save()
            PortalPermissionChange.objects.create(
                member_id=key,
                revision=row.revision,
                changes=changes,
                matrix=_matrix_payload(proposed),
                changed_by_id=row.updated_by_id,
                changed_by_name=row.updated_by_name,
            )
    except IntegrityError:
        raise PermissionMatrixError(
            "Права ролей сохраняет кто-то ещё. Обновите страницу и повторите изменения.",
            "matrix_conflict", status=409,
        )
    finally:
        forget_matrix(account)

    logger.info("roles: портал %s — права ролей изменены, ячеек: %s, ревизия %s", key, len(changes), row.revision)
    return {"status": "ok", "revision": row.revision, "changes": changes}


def matrix_log(account, limit: int = MATRIX_LOG_LIMIT) -> List[Dict[str, Any]]:
    """Журнал изменений прав ролей портала, новые сверху."""
    rows = PortalPermissionChange.objects.filter(member_id=portal_key(account)).order_by("-created_at", "-revision")
    defaults = _matrix_payload(ROLE_PERMISSIONS)
    result = []
    for row in rows[:limit]:
        result.append({
            "revision": row.revision,
            "changed_at": row.created_at.isoformat() if row.created_at else None,
            "changed_by_name": row.changed_by_name,
            "reset_to_default": row.matrix == defaults,
            "changes": [
                {
                    **change,
                    "role_title": ROLE_TITLES.get(change.get("role"), change.get("role")),
                    "permission_title": PERMISSION_TITLES.get(change.get("permission"), change.get("permission")),
                }
                for change in (row.changes or []) if isinstance(change, dict)
            ],
        })
    return result


def roles_mode(account) -> Dict[str, bool]:
    """Режим ролевой модели портала — одним чтением тарифа.

    ``enforced`` — ограничения ролей действуют: Pro живой ИЛИ закончился и
    перешёл в «только чтение» (billing_features.feature_restrictions_active).
    ``subscription_active`` — Pro позволяет ПИСАТЬ, то есть менять роли.
    """
    access = feature_access_from_status(account_subscription_status(account), FEATURE_ROLES)
    return {
        "subscription_active": access == ACCESS_FULL,
        "enforced": restrictions_active_from_access(access),
    }


# ---------------------------------------------------------------------------
# Эффективные права
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Access:
    #: Права считаются по ролям (модель действует — оплачена сейчас или была).
    roles_enabled: bool
    role: str
    is_portal_admin: bool
    permissions: FrozenSet[str] = field(default_factory=frozenset)
    #: Подписка на ролевую модель действует прямо сейчас.
    subscription_active: bool = False

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def as_payload(self) -> Dict[str, Any]:
        return {
            "roles_enabled": self.roles_enabled,
            "role": self.role,
            "role_title": ROLE_TITLES.get(self.role, self.role),
            "is_portal_admin": self.is_portal_admin,
            "subscription_active": self.subscription_active,
            "assignable_roles": assignable_roles(self),
            "permissions": {code: code in self.permissions for code in PERMISSIONS},
        }


def assignable_roles(access: "Access") -> List[str]:
    """Какие роли сейчас можно назначать на портале (при праве roles_manage).

    Только при живом Pro — любые. Без тарифа и после его окончания — никакие:
    назначение закрыто @feature_required(FEATURE_ROLES). Интерфейсу это нужно,
    чтобы погасить выпадающие списки, а не показывать отказ после выбора.
    """
    return list(ROLES) if access.subscription_active else []


def compute_permissions(role: str, *, roles_enabled: bool, is_portal_admin: bool,
                        matrix: Optional[Mapping[str, FrozenSet[str]]] = None) -> FrozenSet[str]:
    """Чистая функция матрицы — её и проверяют тесты.

    ``matrix`` — действующая матрица портала (permission_matrix); без неё —
    матрица по умолчанию. Администратор портала при действующих ролях получает
    права роли «Администратор» этой матрицы (настройки и роли у неё не
    снимаются), без ролей — всё, как до ролей.
    """
    if roles_enabled:
        source = ROLE_PERMISSIONS if matrix is None else matrix
        effective_role = ROLE_ADMIN if is_portal_admin else role
        return frozenset(source.get(effective_role, frozenset()))
    if is_portal_admin:
        return ALL_PERMISSIONS
    legacy_role = ROLE_ACCOUNTANT if role == ROLE_ACCOUNTANT else ROLE_EMPLOYEE
    return LEGACY_PERMISSIONS[legacy_role]


def resolve_access(account, client=None) -> Access:
    """Права человека на этот запрос. Запоминается на объекте учётки.

    Учётка поднимается заново на каждый запрос (auth_required), так что
    запомненное не переживает запрос и не устаревает после смены роли.
    """
    if account is None:
        return Access(roles_enabled=False, role=ROLE_EMPLOYEE, is_portal_admin=False)

    cached = getattr(account, "_roles_access", None)
    if isinstance(cached, Access):
        return cached

    mode = roles_mode(account)
    roles_enabled = mode["enforced"]
    is_portal_admin = bool(getattr(account, "is_b24_user_admin", False))
    if is_portal_admin:
        # Администратору портала не нужен ни перенос, ни чтение ролей: он
        # может всё в обоих режимах, а это самая частая проверка.
        role = ROLE_ADMIN
    else:
        role = stored_role(account, client)

    if not roles_enabled and not is_portal_admin:
        # Пока модель на портале не включалась, ролей «Руководитель проекта» и
        # «Администратор» не существует: права те же, что у любого сотрудника.
        role = ROLE_ACCOUNTANT if role == ROLE_ACCOUNTANT else ROLE_EMPLOYEE

    access = Access(
        roles_enabled=roles_enabled,
        role=role,
        is_portal_admin=is_portal_admin,
        permissions=compute_permissions(
            role, roles_enabled=roles_enabled, is_portal_admin=is_portal_admin,
            matrix=permission_matrix(account) if roles_enabled else None,
        ),
        subscription_active=mode["subscription_active"],
    )
    try:
        account._roles_access = access
    except Exception:  # noqa: BLE001
        pass
    return access


def has_permission(account, permission: str, client=None) -> bool:
    return resolve_access(account, client).has(permission)


def forget_access(account) -> None:
    if account is not None and hasattr(account, "_roles_access"):
        try:
            delattr(account, "_roles_access")
        except AttributeError:
            pass


def denial_text(permission: str, *, roles_enabled: bool, action: str = "",
                matrix: Optional[Mapping[str, FrozenSet[str]]] = None) -> str:
    """Текст отказа: что нельзя, какие роли могут и где их назначают."""
    if not roles_enabled:
        return LEGACY_DENIAL_TEXTS.get(
            permission, "Недостаточно прав для этого действия."
        )
    titles = [f"«{ROLE_TITLES[code]}»" for code in roles_with_permission(permission, matrix)]
    what = action or PERMISSION_TITLES.get(permission, "Это действие")
    if not titles:
        return (
            f"{what} — сейчас это право не дано ни одной роли. Права ролей настраивает "
            "администратор приложения: Настройки → Роли и права."
        )
    who = f"роль {titles[0]}" if len(titles) == 1 else "одна из ролей: " + ", ".join(titles)
    return (
        f"{what} — нужна {who}. Роли назначает администратор приложения: "
        "Настройки → Роли и права."
    )


def denial_response(account, permission: str, *, code: str = "", legacy_code: str = "",
                    action: str = "") -> JsonResponse:
    access = resolve_access(account)
    resolved_code = (code if access.roles_enabled else (legacy_code or code)) or "permission_denied"
    matrix = permission_matrix(account) if access.roles_enabled and account is not None else None
    return JsonResponse(
        {
            "error": denial_text(permission, roles_enabled=access.roles_enabled, action=action, matrix=matrix),
            "code": resolved_code,
            "permission": permission,
            "roles_enabled": access.roles_enabled,
            "allowed_roles": roles_with_permission(permission, matrix),
        },
        status=403,
    )


def permission_required(permission: str, *, code: str = "", legacy_code: str = "", action: str = ""):
    """Серверный гейт по праву. Применять ПОСЛЕ @auth_required и @feature_required.

    ``legacy_code`` — код отказа, пока ограничения ролей не действуют: у прежних
    гейтов свои коды (billing_forbidden, admin_required…), и интерфейс, уже
    разбирающий их, без тарифа не должен заметить разницы.
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            account = getattr(request, "bitrix24_account", None)
            if account is None or not has_permission(account, permission):
                return denial_response(
                    account, permission, code=code, legacy_code=legacy_code, action=action,
                )
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


# ---------------------------------------------------------------------------
# Назначение ролей
# ---------------------------------------------------------------------------

class RoleAssignmentError(Exception):
    def __init__(self, message: str, code: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status

    def as_payload(self) -> Dict[str, Any]:
        return {"error": self.message, "code": self.code}


def portal_admin_user_ids(account) -> List[str]:
    """Администраторы портала, которых знает приложение (открывали его хотя бы раз)."""
    from .models import Bitrix24Account

    key = portal_key(account)
    if key.startswith("account:"):
        rows = [account] if getattr(account, "is_b24_user_admin", False) else []
    else:
        rows = Bitrix24Account.objects.filter(member_id=key, is_b24_user_admin=True)
    result: List[str] = []
    for row in rows:
        user_id = normalize_user_id(getattr(row, "b24_user_id", ""))
        if user_id and user_id not in result:
            result.append(user_id)
    return result


def list_assignments(account) -> List[Dict[str, Any]]:
    from .models import PortalUser
    from .tenant_scoping import scope_to_tenant

    rows = list(role_queryset(account).order_by("role", "b24_user_id"))
    admin_ids = portal_admin_user_ids(account)
    ids = {row.b24_user_id for row in rows} | set(admin_ids)
    names = {
        user.bitrix_id: " ".join(part for part in (user.last_name, user.name) if part).strip()
        for user in PortalUser.objects.filter(**scope_to_tenant(account), bitrix_id__in=ids)
    }

    result = []
    for user_id in admin_ids:
        result.append({
            "user_id": user_id,
            "name": names.get(user_id, ""),
            "role": ROLE_ADMIN,
            "role_title": ROLE_TITLES[ROLE_ADMIN],
            "is_portal_admin": True,
            "source": "portal_admin",
            "assigned_by_name": "",
            "updated_at": None,
        })
    for row in rows:
        if row.b24_user_id in admin_ids:
            continue
        result.append({
            "user_id": row.b24_user_id,
            "name": names.get(row.b24_user_id, ""),
            "role": row.role,
            "role_title": ROLE_TITLES.get(row.role, row.role),
            "is_portal_admin": False,
            "source": row.source,
            "assigned_by_name": row.assigned_by_name,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        })
    return result


def assign_role(account, user_id: Any, role: Any, *, by_id: str = "", by_name: str = "") -> Dict[str, Any]:
    """Назначить роль. «Сотрудник» = удалить строку. Права проверяет вызывающий."""
    normalized_user = normalize_user_id(user_id)
    if not normalized_user:
        raise RoleAssignmentError("Не указан сотрудник.", "user_required")
    normalized_role = normalize_role(role)
    if normalized_role is None:
        raise RoleAssignmentError("Такой роли нет.", "unknown_role")
    if normalized_user in portal_admin_user_ids(account):
        raise RoleAssignmentError(
            "Это администратор портала: у него всегда роль «Администратор», и поменять её "
            "в приложении нельзя.",
            "portal_admin_role_fixed",
        )

    # Перенос прежнего списка ДО записи: иначе первое же назначение на
    # портале, где переноса ещё не было, поставило бы строку раньше, чем
    # «Бухгалтерия» перенесётся, и перенос потом пропустил бы этого человека.
    ensure_accountants_imported(account)

    key = portal_key(account)
    if normalized_role == ROLE_EMPLOYEE:
        PortalRole.objects.filter(member_id=key, b24_user_id=normalized_user).delete()
    else:
        PortalRole.objects.update_or_create(
            member_id=key,
            b24_user_id=normalized_user,
            defaults={
                "portal": getattr(account, "portal", None),
                "role": normalized_role,
                "assigned_by_id": str(by_id or ""),
                "assigned_by_name": str(by_name or "")[:255],
                "source": "manual",
            },
        )
    forget_access(account)
    return {"user_id": normalized_user, "role": normalized_role, "role_title": ROLE_TITLES[normalized_role]}


def roles_feature_state(account) -> Dict[str, Any]:
    return get_feature_state(account, FEATURE_ROLES)
