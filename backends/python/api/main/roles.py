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
   ролей — назначение и правка (@feature_required(FEATURE_ROLES) на
   /api/roles/assign).

Где хранятся роли и почему это нельзя подделать. В нашей БД (PortalRole),
по member_id портала. Прежний список «Бухгалтерия» лежал в app.option портала,
а app.option пишется токеном приложения, который есть у фронта: сотрудник мог
дописать себя в бухгалтерию из консоли браузера. Здесь роль пишет только
сервер по запросу человека с правом ``roles_manage``. Признак «администратор
портала» — is_b24_user_admin, его сервер сам спрашивает у портала методом
user.admin (views._refresh_admin_flag), клиент его не передаёт. Тариф —
PortalSubscription на нашем сервере (billing_features), по REST не пишется.

Перенос «Бухгалтерии». Список billing_accountants при первой проверке прав на
портале переносится в роль «Бухгалтерия» (ensure_accountants_imported) и
дальше не читается. Если конфигурацию прочитать не удалось, отметка переноса
не ставится, а права считаются по прежнему списку — иначе недоступный портал
молча лишил бы бухгалтеров прав.
"""

import logging
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Dict, FrozenSet, List, Optional

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
from .models import PortalRole, PortalRoleState

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

ROLE_DESCRIPTIONS = {
    ROLE_ADMIN: "Всё, включая настройки приложения и назначение ролей. "
                "Администраторы портала получают эту роль автоматически.",
    ROLE_ACCOUNTANT: "Деньги: счета и акты, начисления и списания, ставки, закрытие месяца.",
    ROLE_PROJECT_MANAGER: "Видит суммы по проектам — бюджеты, операции, счета, — но ничего не выставляет.",
    ROLE_EMPLOYEE: "Списывает время, смотрит отчёты по часам и доску проектов. Сумм не видит. "
                   "Роль по умолчанию для всех, кому роль не назначена.",
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

#: Что может каждая роль, когда ограничения ролей действуют (Pro или «только чтение» после него).
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
IMPORT_SOURCE = "billing_accountants"


# ---------------------------------------------------------------------------
# Каталог — для экрана настроек
# ---------------------------------------------------------------------------

def roles_catalog() -> Dict[str, Any]:
    """Роли, права и матрица одним ответом. Экран рисует таблицу из него."""
    return {
        "roles": [
            {"code": code, "title": ROLE_TITLES[code], "description": ROLE_DESCRIPTIONS[code]}
            for code in ROLES
        ],
        "permissions": [
            {"code": code, "title": PERMISSION_TITLES[code]} for code in PERMISSIONS
        ],
        "matrix": {code: sorted(ROLE_PERMISSIONS[code]) for code in ROLES},
        "legacy_matrix": {code: sorted(perms) for code, perms in LEGACY_PERMISSIONS.items()},
    }


def roles_with_permission(permission: str) -> List[str]:
    return [code for code in ROLES if permission in ROLE_PERMISSIONS[code]]


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


def compute_permissions(role: str, *, roles_enabled: bool, is_portal_admin: bool) -> FrozenSet[str]:
    """Чистая функция матрицы — её и проверяют тесты."""
    if is_portal_admin:
        return ALL_PERMISSIONS
    if roles_enabled:
        return ROLE_PERMISSIONS.get(role, frozenset())
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
        permissions=compute_permissions(role, roles_enabled=roles_enabled, is_portal_admin=is_portal_admin),
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


def denial_text(permission: str, *, roles_enabled: bool, action: str = "") -> str:
    """Текст отказа: что нельзя, какие роли могут и где их назначают."""
    if not roles_enabled:
        return LEGACY_DENIAL_TEXTS.get(
            permission, "Недостаточно прав для этого действия."
        )
    titles = [f"«{ROLE_TITLES[code]}»" for code in roles_with_permission(permission)]
    what = action or PERMISSION_TITLES.get(permission, "Это действие")
    who = f"роль {titles[0]}" if len(titles) == 1 else "одна из ролей: " + ", ".join(titles)
    return (
        f"{what} — нужна {who}. Роли назначает администратор приложения: "
        "Настройки → Роли и права."
    )


def denial_response(account, permission: str, *, code: str = "", legacy_code: str = "",
                    action: str = "") -> JsonResponse:
    access = resolve_access(account)
    resolved_code = (code if access.roles_enabled else (legacy_code or code)) or "permission_denied"
    return JsonResponse(
        {
            "error": denial_text(permission, roles_enabled=access.roles_enabled, action=action),
            "code": resolved_code,
            "permission": permission,
            "roles_enabled": access.roles_enabled,
            "allowed_roles": roles_with_permission(permission),
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
