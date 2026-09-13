"""Покупка Pro: заявка на счёт, код портала, номер счёта, отправка в CRM.

Поток (записка к макету 2026-09-12-pro-purchase-mockup.md):
кнопка -> форма -> заявка у нас -> сделка и смарт-счёт в CRM Mainsoft ->
оплата -> менеджер отмечает оплату командой `pro_requests paid` -> Pro
включается на оплаченный срок через pro_plan_service. До оплаты Pro НЕ
включается.

Три ключа сопоставления платежа с порталом:
1. номер счёта (УТ-0047) — выдаёт наш нумератор, однозначно;
2. код портала (6 цифр) — PortalBillingCode, однозначно и не меняется при
   смене домена;
3. ИНН плательщика — только подсказка (у организации бывает несколько
   порталов).

Портал заявки берётся ТОЛЬКО из авторизации (учётка из JWT), тело запроса
портал не задаёт.
"""

import logging
import secrets
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from . import pro_plan_service
from .billing_features import account_subscription_status, subscription_today
from .models import (
    Bitrix24Account,
    Portal,
    PortalBillingCode,
    PortalSubscription,
    PortalUser,
    ProInvoiceSequence,
    ProRequest,
)
from .pro_purchase_crm import CrmSettings, CrmSyncError, ProRequestCrmSync, build_transport, load_crm_settings
from .pro_purchase_pricing import (
    PurchaseSettings,
    Quote,
    add_business_days,
    build_payment_purpose,
    calculate_quote,
    load_purchase_settings,
    money_str,
    months_text,
    vat_text,
)

logger = logging.getLogger(__name__)

PORTAL_CODE_LENGTH = 6
REQUISITES_CACHE_TTL = 10 * 60
MY_COMPANIES_REQUISITES_LIMIT = 10


class PurchaseError(Exception):
    """Отказ операции покупки; текст — для человека, code — для интерфейса."""

    def __init__(self, message: str, code: str = "pro_purchase_error", status: int = 400,
                 errors: Optional[Dict[str, str]] = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.errors = errors or {}

    def as_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"error": str(self), "code": self.code}
        if self.errors:
            payload["errors"] = self.errors
        return payload


# ---------------------------------------------------------------------------
# Портал, код портала, номер счёта
# ---------------------------------------------------------------------------


def portal_for_account(account: Bitrix24Account) -> Portal:
    """Портал учётки из авторизации. Ключ — member_id, как у тарифа."""
    member_id = str(getattr(account, "member_id", "") or "").strip()
    portal = None
    if member_id:
        try:
            portal = pro_plan_service.resolve_portal(member_id=member_id)
        except pro_plan_service.PlanError:
            portal = None
    if portal is None and getattr(account, "portal_id", None):
        portal = Portal.objects.filter(pk=account.portal_id).first()
    if portal is None:
        raise PurchaseError("Портал не определён: откройте приложение из Битрикс24 заново.",
                            code="portal_unknown", status=409)
    return portal


def _generate_code() -> str:
    # Первая цифра не ноль: код не теряет ведущий ноль в Excel и выписке 1С.
    return str(secrets.randbelow(9 * 10 ** (PORTAL_CODE_LENGTH - 1)) + 10 ** (PORTAL_CODE_LENGTH - 1))


def portal_code(portal: Portal) -> str:
    """Код портала: создаётся один раз и больше не меняется."""
    existing = PortalBillingCode.objects.filter(portal=portal).values_list("code", flat=True).first()
    if existing:
        return existing
    for _attempt in range(20):
        try:
            with transaction.atomic():
                return PortalBillingCode.objects.create(portal=portal, code=_generate_code()).code
        except IntegrityError:
            # Либо совпал код (перебираем), либо код порталу уже выдал
            # соседний запрос — тогда возвращаем его.
            existing = PortalBillingCode.objects.filter(portal=portal).values_list("code", flat=True).first()
            if existing:
                return existing
    raise PurchaseError("Не удалось выдать код портала, повторите попытку.", code="portal_code_failed", status=500)


def next_invoice_number(prefix: str) -> Tuple[int, str]:
    """Следующий номер счёта. Вызывать внутри transaction.atomic()."""
    ProInvoiceSequence.objects.get_or_create(prefix=prefix)
    ProInvoiceSequence.objects.filter(prefix=prefix).update(value=F("value") + 1)
    value = ProInvoiceSequence.objects.get(prefix=prefix).value
    return value, f"{prefix}{value:04d}"


def member_id_short(member_id: str) -> str:
    value = str(member_id or "")
    return value if len(value) <= 14 else f"{value[:8]}…{value[-6:]}"


# ---------------------------------------------------------------------------
# Цена
# ---------------------------------------------------------------------------


def effective_price(portal: Portal, settings: PurchaseSettings) -> int:
    """Цена за месяц: индивидуальная цена портала побеждает общую.

    Индивидуальной считается цена тарифа, заданная командой pro_plan --price
    и отличная от значения модели по умолчанию.
    """
    subscription = PortalSubscription.objects.filter(portal=portal).first()
    if subscription and subscription.price_month_rub and \
            subscription.price_month_rub != PortalSubscription.DEFAULT_PRICE_MONTH_RUB:
        return int(subscription.price_month_rub)
    return settings.price_month_rub


def build_quotes(portal: Portal, settings: PurchaseSettings) -> List[Quote]:
    price = effective_price(portal, settings)
    return [calculate_quote(settings, term, price) for term in settings.terms]


def quote_for(portal: Portal, months: Any, settings: Optional[PurchaseSettings] = None) -> Quote:
    settings = settings or load_purchase_settings()
    term = settings.term(months)
    if term is None:
        allowed = ", ".join(str(item.months) for item in settings.terms)
        raise PurchaseError(f"Такого срока нет. Доступны: {allowed} мес.", code="term_unknown")
    return calculate_quote(settings, term, effective_price(portal, settings))


# ---------------------------------------------------------------------------
# Люди портала
# ---------------------------------------------------------------------------


def _names_by_ids(account: Bitrix24Account, ids: List[str]) -> Dict[str, str]:
    if not ids:
        return {}
    from .tenant_scoping import scope_to_tenant

    rows = PortalUser.objects.filter(**scope_to_tenant(account), bitrix_id__in=ids).values(
        "bitrix_id", "name", "last_name",
    )
    return {row["bitrix_id"]: f"{row['name']} {row['last_name']}".strip() for row in rows}


def display_name(account: Bitrix24Account) -> str:
    user_id = str(account.b24_user_id or "")
    return _names_by_ids(account, [user_id]).get(user_id, "")


#: Право «запросить счёт на Pro». Отдельного права в ролевой модели нет:
#: счёт на подписку — та же операция «выставить счёт», и её круг людей тот же —
#: администратор и «Бухгалтерия», при ролях и без них (main/roles.py).
PRO_REQUEST_PERMISSION = "billing_issue"


def can_request_pro(account: Bitrix24Account) -> bool:
    from .roles import has_permission

    return account is not None and has_permission(account, PRO_REQUEST_PERMISSION)


def pro_managers(account: Bitrix24Account) -> List[str]:
    """Кто может запросить счёт — для текста сотруднику «Pro подключает …».

    Администраторы портала, которых знает приложение, и люди с ролями,
    у которых есть право выставлять счета. При действующих ролях круг ролей
    берётся из матрицы прав портала — её можно поменять на экране «Роли и
    права».
    """
    from .roles import (
        ROLE_ACCOUNTANT,
        ensure_accountants_imported,
        permission_matrix,
        portal_admin_user_ids,
        resolve_access,
        role_queryset,
        roles_with_permission,
    )

    ensure_accountants_imported(account)
    if resolve_access(account).roles_enabled:
        allowed = roles_with_permission(PRO_REQUEST_PERMISSION, permission_matrix(account))
    else:
        allowed = [ROLE_ACCOUNTANT]
    role_ids = [str(value) for value in role_queryset(account).filter(role__in=allowed)
                .values_list("b24_user_id", flat=True)]
    ordered = list(dict.fromkeys(portal_admin_user_ids(account) + role_ids))
    names = _names_by_ids(account, ordered)
    return [names[user_id] for user_id in ordered if names.get(user_id)]


def current_user_contact(account: Bitrix24Account) -> Dict[str, str]:
    """Имя и почта текущего сотрудника с портала клиента (user.current)."""
    contact = {"name": display_name(account), "email": ""}
    try:
        response = account.client._bitrix_token.call_method("user.current", {})
        result = response.get("result") if isinstance(response, dict) else None
        if isinstance(result, dict):
            name = f"{result.get('NAME') or ''} {result.get('LAST_NAME') or ''}".strip()
            contact["name"] = name or contact["name"]
            contact["email"] = str(result.get("EMAIL") or "").strip()
    except Exception as exc:  # noqa: BLE001 — подстановка, не условие формы
        logger.info("Pro: контакт из user.current не получен: %s", type(exc).__name__)
    return contact


# ---------------------------------------------------------------------------
# Реквизиты из CRM портала клиента
# ---------------------------------------------------------------------------

REQUISITE_SELECT = [
    "ID", "ENTITY_ID", "PRESET_ID", "NAME", "RQ_INN", "RQ_KPP", "RQ_COMPANY_NAME",
    "RQ_COMPANY_FULL_NAME", "RQ_NAME", "RQ_LAST_NAME", "RQ_FIRST_NAME", "RQ_SECOND_NAME",
]
LEGAL_ADDRESS_TYPE_ID = "6"


def _call_client(account, method: str, params: Dict[str, Any]) -> Any:
    response = account.client._bitrix_token.call_method(method, params)
    return response.get("result") if isinstance(response, dict) else None


def _requisite_name(row: Dict[str, Any], is_ip: bool) -> str:
    if is_ip:
        fio = " ".join(str(row.get(key) or "").strip() for key in ("RQ_LAST_NAME", "RQ_FIRST_NAME", "RQ_SECOND_NAME"))
        fio = " ".join(fio.split())
        if fio:
            return f"Индивидуальный предприниматель {fio}"
        return str(row.get("RQ_NAME") or row.get("NAME") or "").strip()
    return str(row.get("RQ_COMPANY_FULL_NAME") or row.get("RQ_COMPANY_NAME") or row.get("NAME") or "").strip()


def _format_address(row: Dict[str, Any]) -> str:
    parts = [row.get(key) for key in ("POSTAL_CODE", "PROVINCE", "CITY", "ADDRESS_1", "ADDRESS_2")]
    return ", ".join(str(part).strip() for part in parts if str(part or "").strip())


def _requisite_address(account, requisite_id: str) -> str:
    try:
        rows = _call_client(account, "crm.address.list", {
            "filter": {"ENTITY_TYPE_ID": 8, "ENTITY_ID": requisite_id},
            "select": ["TYPE_ID", "POSTAL_CODE", "PROVINCE", "CITY", "ADDRESS_1", "ADDRESS_2"],
        })
    except Exception as exc:  # noqa: BLE001
        logger.info("Pro: адрес реквизита не получен: %s", type(exc).__name__)
        return ""
    rows = [row for row in (rows or []) if isinstance(row, dict)]
    legal = [row for row in rows if str(row.get("TYPE_ID")) == LEGAL_ADDRESS_TYPE_ID]
    for row in legal + rows:
        text = _format_address(row)
        if text:
            return text
    return ""


def _requisite_payload(account, row: Dict[str, Any], company_title: str = "") -> Optional[Dict[str, Any]]:
    inn = "".join(str(row.get("RQ_INN") or "").split())
    if not (inn.isascii() and inn.isdigit() and len(inn) in (10, 12)):
        return None
    is_ip = len(inn) == 12
    return {
        "company_id": str(row.get("ENTITY_ID") or ""),
        "company_title": company_title,
        "payer_type": "ip" if is_ip else "org",
        "inn": inn,
        "kpp": "" if is_ip else str(row.get("RQ_KPP") or "").strip(),
        "name": _requisite_name(row, is_ip),
        "address": _requisite_address(account, str(row.get("ID") or "")),
        "source": "crm",
    }


def my_company_requisites(account: Bitrix24Account) -> Dict[str, Any]:
    """«Ваши юрлица из CRM портала»: свои компании с ИНН — подсказки формы."""
    from .company_search_service import CompanySearchService

    cache_key = f"pro-my-requisites:{account.member_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    companies = CompanySearchService(account.client, account).list_my_companies()
    suggestions: List[Dict[str, Any]] = []
    failed = bool(companies.get("failed"))
    for company in (companies.get("companies") or [])[:MY_COMPANIES_REQUISITES_LIMIT]:
        try:
            rows = _call_client(account, "crm.requisite.list", {
                "filter": {"ENTITY_TYPE_ID": 4, "ENTITY_ID": company["id"]},
                "select": REQUISITE_SELECT,
            })
        except Exception as exc:  # noqa: BLE001
            logger.info("Pro: реквизиты своей компании не получены: %s", type(exc).__name__)
            failed = True
            continue
        for row in rows or []:
            if isinstance(row, dict):
                payload = _requisite_payload(account, row, company.get("name") or "")
                if payload:
                    suggestions.append(payload)
    result = {"suggestions": suggestions, "failed": failed}
    if not failed:
        cache.set(cache_key, result, REQUISITES_CACHE_TTL)
    return result


def lookup_requisites_by_inn(account: Bitrix24Account, inn: str) -> Dict[str, Any]:
    """Реквизиты по ИНН из CRM портала клиента. Внешнего справочника нет."""
    try:
        rows = _call_client(account, "crm.requisite.list", {
            "filter": {"ENTITY_TYPE_ID": 4, "RQ_INN": inn},
            "select": REQUISITE_SELECT,
        })
    except Exception as exc:  # noqa: BLE001
        logger.info("Pro: поиск реквизитов по ИНН не удался: %s", type(exc).__name__)
        return {"found": False, "failed": True, "requisite": None}
    for row in (rows or [])[:5]:
        if isinstance(row, dict):
            payload = _requisite_payload(account, row)
            if payload and payload["inn"] == inn:
                return {"found": True, "failed": False, "requisite": payload}
    return {"found": False, "failed": False, "requisite": None}


# ---------------------------------------------------------------------------
# Сериализация
# ---------------------------------------------------------------------------


def crm_state(request: ProRequest, crm_settings: Optional[CrmSettings]) -> str:
    """sent — в CRM; retry — ждёт повтора; manual — вебхук не настроен; none — не нужно.

    Сделка теперь необязательна (MAINSOFT_BILLING_DEAL_CATEGORY_ID может быть
    пуст) — «отправлено» определяется наличием смарт-счёта, а не сделки.
    """
    if request.crm_invoice_id:
        return "sent"
    if request.status in (ProRequest.STATUS_PAID, ProRequest.STATUS_CANCELLED):
        return "none"
    return "retry" if crm_settings is not None else "manual"


def serialize_request(request: ProRequest, *, full: bool = True,
                      crm_settings: Optional[CrmSettings] = None) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "id": str(request.pk),
        "invoice_number": request.invoice_number,
        "invoice_date": request.invoice_date.isoformat(),
        "due_date": request.due_date.isoformat(),
        "status": request.status,
        "months": request.months,
        "months_text": months_text(request.months),
        "total": money_str(request.total_amount),
        "requested_by_name": request.requested_by_name,
        "created_at": request.created_at.isoformat() if request.created_at else None,
        "pro_paid_until": request.pro_paid_until.isoformat() if request.pro_paid_until else None,
    }
    if not full:
        return base
    base.update({
        "amounts": {
            "price_month": money_str(request.price_month),
            "base": money_str(request.base_amount),
            "discount": money_str(request.discount_amount),
            "subtotal": money_str(request.subtotal_amount),
            "vat_mode": request.vat_mode,
            "vat_rate": format(request.vat_rate.normalize(), "f"),
            "vat": money_str(request.vat_amount),
            "total": money_str(request.total_amount),
            "vat_text": vat_text(request.vat_mode, request.vat_rate, request.vat_amount),
        },
        "payment_purpose": request.payment_purpose,
        "payment_purpose_length": len(request.payment_purpose),
        "portal": {
            "domain": request.domain_snapshot,
            "code": request.portal_code,
            "member_id_short": member_id_short(request.member_id_snapshot),
        },
        "payer": {
            "type": request.payer_type,
            "inn": request.payer_inn,
            "kpp": request.payer_kpp,
            "name": request.payer_name,
            "address": request.payer_address,
        },
        "contact": {
            "name": request.contact_name,
            "email": request.contact_email,
            "cc": request.contact_cc,
            "phone": request.contact_phone,
        },
        "crm_state": crm_state(request, crm_settings),
        "pdf_available": bool(request.crm_pdf_url),
        "paid_on": request.paid_on.isoformat() if request.paid_on else None,
        "cancelled_at": request.cancelled_at.isoformat() if request.cancelled_at else None,
        "cancel_reason": request.cancel_reason,
        "sequence_number": request.sequence_number,
    })
    return base


def current_request(portal: Portal) -> Optional[ProRequest]:
    """Открытая заявка портала, иначе последняя (оплаченная или отменённая)."""
    open_request = ProRequest.objects.filter(portal=portal, status__in=ProRequest.OPEN_STATUSES).first()
    return open_request or ProRequest.objects.filter(portal=portal).order_by("-created_at").first()


def build_offer(account: Bitrix24Account, *, can_request: bool) -> Dict[str, Any]:
    settings = load_purchase_settings()
    crm_settings = load_crm_settings()
    portal = portal_for_account(account)
    status = account_subscription_status(account)
    request = current_request(portal)
    return {
        "price_month_rub": effective_price(portal, settings),
        "vat": {"mode": settings.vat_mode, "rate": format(settings.vat_rate.normalize(), "f")},
        "terms": [quote.as_payload() for quote in build_quotes(portal, settings)],
        "default_months": settings.default_months,
        "due_business_days": settings.due_business_days,
        "contact_email": settings.contact_email,
        "offer_url": settings.offer_url,
        "portal": {
            "domain": portal.domain_url or account.domain_url or "",
            "code": portal_code(portal),
            "member_id_short": member_id_short(portal.member_id),
        },
        "contact": current_user_contact(account) if can_request else {"name": "", "email": ""},
        "subscription": {
            "status": status.status,
            "access": status.access,
            "paid_until": status.paid_until.isoformat() if status.paid_until else None,
            "trial_until": status.trial_until.isoformat() if status.trial_until else None,
            "grace_until": status.grace_until.isoformat() if status.grace_until else None,
        },
        "can_request": can_request,
        "managers": [] if can_request else pro_managers(account),
        "current_request": serialize_request(request, full=can_request, crm_settings=crm_settings) if request else None,
        "crm_mode": "auto" if crm_settings is not None else "manual",
    }


# ---------------------------------------------------------------------------
# Создание, отправка, отмена, оплата
# ---------------------------------------------------------------------------


def _apply_form(request: ProRequest, cleaned: Dict[str, Any]) -> None:
    for name in ("payer_type", "payer_inn", "payer_kpp", "payer_name", "payer_address",
                 "payer_company_id", "contact_name", "contact_email", "contact_cc", "contact_phone"):
        setattr(request, name, cleaned[name])


def _apply_quote(request: ProRequest, quote: Quote) -> None:
    request.months = quote.months
    request.price_month = quote.price_month
    request.base_amount = quote.base
    request.discount_amount = quote.discount
    request.subtotal_amount = quote.subtotal
    request.vat_mode = quote.vat_mode
    request.vat_rate = quote.vat_rate
    request.vat_amount = quote.vat
    request.total_amount = quote.total


@dataclass
class CreateResult:
    request: ProRequest
    replaced: Optional[ProRequest] = None
    updated_in_place: bool = False


def _locked_open_request(portal: Portal) -> Optional[ProRequest]:
    """Открытая заявка портала под row-level локом (или None, если её нет).

    Вынесена отдельно от create_request ради переиспользования: тем же
    запросом ищем существующую заявку и с первого захода, и повторно —
    после проигранной гонки на INSERT (см. докстринг create_request).
    """
    return (
        ProRequest.objects.select_for_update()
        .filter(portal=portal, status__in=ProRequest.OPEN_STATUSES).first()
    )


def create_request(account: Bitrix24Account, data: Dict[str, Any], *,
                   settings: Optional[PurchaseSettings] = None,
                   today: Optional[date] = None) -> CreateResult:
    """Сохранить заявку. В CRM не ходит — это dispatch().

    Открытая заявка у портала одна:
    - тот же срок и та же сумма — правим реквизиты в прежней заявке, номер
      счёта остаётся (правка реквизитов не должна плодить счетов);
    - другой срок — прежняя заявка отменяется («заменена»), выдаётся новый
      номер: оплатить оба счёта не должны.

    Гонка двух быстрых POST без открытой заявки: select_for_update().first()
    ничего не блокирует, когда блокировать ещё нечего (строки нет), поэтому
    оба запроса видят existing=None и оба пытаются вставить новую открытую
    заявку. Второй INSERT ловит частичный уникальный индекс
    pro_request_one_open_per_portal и бросает IntegrityError. Вставка
    обёрнута в собственный savepoint (вложенный transaction.atomic) именно
    ради этого случая: на PostgreSQL исключение внутри atomic без своего
    savepoint ломает всю внешнюю транзакцию, а нам после проигранной гонки
    нужно продолжить работу в ней (перечитать уже вставленную соперником
    заявку). Победившую заявку после этого разбираем так же, как разобрали
    бы existing, найденный с первого захода: тот же тариф — сливаем в неё
    реквизиты, другой — отвечаем понятным PurchaseError(409), а не давим
    вторую попытку вставки (риск той же гонки третий раз того не стоит).
    """
    from .pro_purchase_pricing import validate_purchase_form

    settings = settings or load_purchase_settings()
    cleaned, errors = validate_purchase_form(data, settings)
    if errors:
        raise PurchaseError("Проверьте поля формы.", code="validation_failed", errors=errors)

    portal = portal_for_account(account)
    code = portal_code(portal)
    quote = quote_for(portal, cleaned["months"], settings)
    today = today or subscription_today()
    requester_name = display_name(account)
    domain = portal.domain_url or account.domain_url or ""

    with transaction.atomic():
        existing = _locked_open_request(portal)
        if existing and existing.months == quote.months and existing.total_amount == quote.total:
            if existing.payer_inn != cleaned["payer_inn"]:
                existing.crm_company_id = ""
            _apply_form(existing, cleaned)
            existing.offer_accepted_at = timezone.now()
            existing.save()
            return CreateResult(request=existing, updated_in_place=True)

        replaced = None
        sequence, number = next_invoice_number(settings.invoice_prefix)
        if existing:
            existing.status = ProRequest.STATUS_CANCELLED
            existing.cancelled_at = timezone.now()
            existing.cancelled_by = requester_name or f"user:{account.b24_user_id}"
            existing.cancel_reason = f"Заменена заявкой {number}"
            existing.save()
            replaced = existing

        request = ProRequest(
            portal=portal,
            requested_by_account=account,
            requested_by_id=str(account.b24_user_id or ""),
            requested_by_name=requester_name,
            requested_by_admin=bool(account.is_b24_user_admin),
            domain_snapshot=domain,
            member_id_snapshot=portal.member_id,
            portal_code=code,
            sequence_number=sequence,
            invoice_number=number,
            invoice_date=today,
            due_date=add_business_days(today, settings.due_business_days),
            offer_accepted_at=timezone.now(),
            status=ProRequest.STATUS_DRAFT,
        )
        _apply_form(request, cleaned)
        _apply_quote(request, quote)
        request.payment_purpose = build_payment_purpose(
            invoice_number=number, invoice_date=today, months=quote.months, domain=domain,
            portal_code=code, vat_mode=quote.vat_mode, vat_rate=quote.vat_rate, vat_amount=quote.vat,
        )
        try:
            with transaction.atomic():
                request.save()
        except IntegrityError:
            winner = _locked_open_request(portal)
            if winner is None:
                # Заявка соперника пропала между проигранной вставкой и
                # перечитыванием (например, её тут же отменили) — это уже
                # не гонка «двойного клика», а что-то куда более странное.
                # Сырой 500 всё равно не отдаём.
                raise PurchaseError(
                    "Не удалось сохранить заявку, попробуйте ещё раз.",
                    code="request_conflict", status=409,
                )
            if winner.months == quote.months and winner.total_amount == quote.total:
                if winner.payer_inn != cleaned["payer_inn"]:
                    winner.crm_company_id = ""
                _apply_form(winner, cleaned)
                winner.offer_accepted_at = timezone.now()
                winner.save()
                return CreateResult(request=winner, updated_in_place=True)
            raise PurchaseError(
                "У портала уже есть открытая заявка на другой тариф — её создали параллельно. Обновите страницу.",
                code="request_conflict", status=409,
            )
        if replaced is not None:
            ProRequest.objects.filter(pk=replaced.pk).update(replaced_by=request)
    return CreateResult(request=request, replaced=replaced)


def _crm_sync(crm_settings: CrmSettings, transport=None) -> ProRequestCrmSync:
    return ProRequestCrmSync(transport or build_transport(crm_settings), crm_settings)


def dispatch(request: ProRequest, *, crm_settings: Optional[CrmSettings] = None,
             transport=None, use_env: bool = True) -> ProRequest:
    """Отправить открытую заявку в CRM Mainsoft. Ошибка портала заявку не теряет.

    Без вебхука (безопасный режим) — статус pending, в CRM ничего не уходит.
    """
    if not request.is_open:
        return request
    if crm_settings is None and use_env:
        crm_settings = load_crm_settings()
    if crm_settings is None:
        if request.status != ProRequest.STATUS_PENDING:
            request.status = ProRequest.STATUS_PENDING
            request.save(update_fields=["status", "updated_at"])
        return request

    request.crm_attempts += 1
    request.crm_last_attempt_at = timezone.now()
    request.save(update_fields=["crm_attempts", "crm_last_attempt_at", "updated_at"])
    try:
        warning = _crm_sync(crm_settings, transport).send(request)
    except CrmSyncError as exc:
        request.status = ProRequest.STATUS_PENDING
        request.crm_error = str(exc)[:1000]
        request.save(update_fields=["status", "crm_error", "updated_at"])
        logger.warning("Pro %s: отправка в CRM не удалась: %s", request.invoice_number, exc)
        return request
    request.status = ProRequest.STATUS_SENT
    request.crm_error = warning or ""
    request.crm_sent_at = request.crm_sent_at or timezone.now()
    request.save(update_fields=["status", "crm_error", "crm_sent_at", "updated_at"])
    return request


def sync_cancellation(request: ProRequest, *, crm_settings: Optional[CrmSettings] = None, transport=None) -> bool:
    """Донести отмену до CRM. True — дошла или нечего доносить.

    «Донести» может значить и сделку (если она есть), и задачу на контроль
    оплаты — сделка теперь необязательна.
    """
    if request.status != ProRequest.STATUS_CANCELLED or request.crm_cancel_synced_at:
        return True
    if not (request.crm_deal_id or request.crm_task_id):
        return True
    crm_settings = crm_settings or load_crm_settings()
    if crm_settings is None:
        return False
    try:
        _crm_sync(crm_settings, transport).cancel(request)
    except CrmSyncError as exc:
        logger.warning("Pro %s: отмена не дошла до CRM: %s", request.invoice_number, exc)
        return False
    request.crm_cancel_synced_at = timezone.now()
    request.save(update_fields=["crm_cancel_synced_at", "updated_at"])
    return True


def cancel_request(request: ProRequest, *, actor: str, reason: str = "",
                   crm_settings: Optional[CrmSettings] = None, transport=None) -> ProRequest:
    if request.status == ProRequest.STATUS_PAID:
        raise PurchaseError("Счёт уже оплачен — отменить заявку нельзя. Напишите на timesheet@mainsoft.su.",
                            code="request_paid", status=409)
    if request.status == ProRequest.STATUS_CANCELLED:
        return request
    request.status = ProRequest.STATUS_CANCELLED
    request.cancelled_at = timezone.now()
    request.cancelled_by = actor
    request.cancel_reason = (reason or "Отменена в приложении")[:1000]
    request.save(update_fields=["status", "cancelled_at", "cancelled_by", "cancel_reason", "updated_at"])
    sync_cancellation(request, crm_settings=crm_settings, transport=transport)
    return request


def mark_paid(request: ProRequest, *, actor: str, paid_on: Optional[date] = None,
              comment: str = "", today: Optional[date] = None,
              crm_settings: Optional[CrmSettings] = None, transport=None):
    """Отметить оплату и включить Pro на оплаченный срок.

    Срок продлевает pro_plan_service.extend: действующий Pro продолжается от
    paid_until (дни не пропадают), истёкший, пробный или выключенный —
    считается с сегодняшнего дня.
    """
    if request.status == ProRequest.STATUS_PAID:
        raise PurchaseError(f"Счёт {request.invoice_number} уже отмечен оплаченным.", code="already_paid", status=409)
    today = today or subscription_today()
    note = f"Оплачен счёт {request.invoice_number}" + (f": {comment}" if comment else "")
    with transaction.atomic():
        locked = ProRequest.objects.select_for_update().get(pk=request.pk)
        if locked.status == ProRequest.STATUS_PAID:
            raise PurchaseError(f"Счёт {request.invoice_number} уже отмечен оплаченным.", code="already_paid", status=409)
        try:
            change = pro_plan_service.extend(
                locked.portal, months=locked.months, price=int(locked.price_month),
                actor=actor, comment=note, today=today,
            )
        except pro_plan_service.PlanError as exc:
            raise PurchaseError(str(exc), code="plan_error", status=409) from exc
        locked.status = ProRequest.STATUS_PAID
        locked.paid_at = timezone.now()
        locked.paid_on = paid_on or today
        locked.paid_by = actor
        locked.pro_paid_until = change.after.paid_until
        locked.save()
    request.refresh_from_db()
    settings = crm_settings or load_crm_settings()
    if settings is not None and (request.crm_invoice_id or request.crm_deal_id or request.crm_task_id):
        try:
            _crm_sync(settings, transport).mark_paid(request)
        except CrmSyncError as exc:  # pragma: no cover — mark_paid сам глотает ошибки
            logger.warning("Pro %s: оплата не отмечена в CRM: %s", request.invoice_number, exc)
    return request, change


def find_request(*, invoice: str = "", code: str = "", open_only: bool = False) -> ProRequest:
    """Заявка по номеру счёта или коду портала (открытая, иначе последняя)."""
    invoice = str(invoice or "").strip()
    code = str(code or "").strip()
    if invoice:
        request = ProRequest.objects.filter(invoice_number__iexact=invoice).first()
        if request is None and invoice.isdigit():
            request = ProRequest.objects.filter(sequence_number=int(invoice)).first()
        if request is None:
            raise PurchaseError(f"Счёт «{invoice}» не найден.", code="not_found", status=404)
        return request
    if code:
        requests = ProRequest.objects.filter(portal_code=code)
        request = requests.filter(status__in=ProRequest.OPEN_STATUSES).first()
        if request is None and not open_only:
            request = requests.order_by("-created_at").first()
        if request is None:
            raise PurchaseError(f"Заявок с кодом портала {code} нет.", code="not_found", status=404)
        return request
    raise PurchaseError("Укажите --invoice или --code.", code="target_missing")
