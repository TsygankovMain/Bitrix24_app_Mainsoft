"""Покупка Pro: цена, НДС, сроки, назначение платежа и проверка формы.

Чистый модуль — без Django и без сети, как inn_validation.py: расчёт суммы
и лимит назначения платежа должны проверяться тестами без базы и без
портала. Тот же расчёт на фронте только показывается (frontend/app/utils/
proPurchase.ts): сумму для счёта считает ТОЛЬКО сервер.

Всё, что может поменяться решением бухгалтерии, — настройка окружения, а не
константа (записка к макету 2026-09-12-pro-purchase-mockup.md, открытые
вопросы 1 и 2):

    PRO_PRICE_MONTH_RUB            цена за месяц, ₽ (3000)
    PRO_VAT_MODE                   none | included | on_top (none — Mainsoft работает без НДС)
    PRO_VAT_RATE                   ставка, % (22)
    PRO_TERMS                      JSON-список сроков, см. DEFAULT_TERMS
    PRO_DEFAULT_MONTHS             срок, выбранный в форме (12)
    PRO_INVOICE_PREFIX             префикс номера счёта («УТ-»)
    PRO_INVOICE_DUE_BUSINESS_DAYS  срок оплаты, рабочих дней (5)
    PRO_CONTACT_EMAIL              адрес для оплаты картой и вопросов
    PRO_OFFER_URL                  ссылка на текст оферты (пусто — без ссылки)

Кривое значение не роняет приложение: берётся значение по умолчанию, а
причина пишется в лог — форма покупки не должна пропадать из-за опечатки в
переменной.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .inn_validation import normalize_inn, validate_inn

logger = logging.getLogger(__name__)

VAT_NONE = "none"
VAT_INCLUDED = "included"
VAT_ON_TOP = "on_top"
VAT_MODES = (VAT_NONE, VAT_INCLUDED, VAT_ON_TOP)

DEFAULT_PRICE_MONTH_RUB = 3000
#: Mainsoft работает без НДС (счёт-фактуры не выставляет). Ставка PRO_VAT_RATE
#: остаётся настройкой на случай, если PRO_VAT_MODE переключат обратно.
DEFAULT_VAT_MODE = VAT_NONE
DEFAULT_VAT_RATE = Decimal("22")
#: 1 и 3 месяца без скидки, 6 месяцев −5 %, 12 месяцев по цене 10 (записка,
#: вопрос 2, рекомендация «б»).
DEFAULT_TERMS: Tuple[Dict[str, Any], ...] = (
    {"months": 1},
    {"months": 3},
    {"months": 6, "discount_percent": 5},
    {"months": 12, "paid_months": 10},
)
DEFAULT_MONTHS = 12
DEFAULT_INVOICE_PREFIX = "УТ-"
DEFAULT_DUE_BUSINESS_DAYS = 5
DEFAULT_CONTACT_EMAIL = "timesheet@mainsoft.su"

#: Лимит поля «Назначение платежа» в платёжном поручении.
PAYMENT_PURPOSE_LIMIT = 210
PRODUCT_TITLE = "Учёт трудозатрат"

_KOPECK = Decimal("0.01")
_RUBLE = Decimal("1")


@dataclass(frozen=True)
class PurchaseTerm:
    months: int
    discount_percent: Decimal = Decimal("0")
    #: «12 по цене 10»: сколько месяцев оплачивается. Перекрывает процент.
    paid_months: Optional[int] = None

    @property
    def label(self) -> str:
        if self.paid_months is not None and self.paid_months < self.months:
            return f"{self.months} по цене {self.paid_months}"
        if self.discount_percent > 0:
            return f"−{_plain_number(self.discount_percent)}%"
        return ""


@dataclass(frozen=True)
class PurchaseSettings:
    price_month_rub: int = DEFAULT_PRICE_MONTH_RUB
    vat_mode: str = DEFAULT_VAT_MODE
    vat_rate: Decimal = DEFAULT_VAT_RATE
    terms: Tuple[PurchaseTerm, ...] = field(default_factory=lambda: _parse_terms(DEFAULT_TERMS))
    default_months: int = DEFAULT_MONTHS
    invoice_prefix: str = DEFAULT_INVOICE_PREFIX
    due_business_days: int = DEFAULT_DUE_BUSINESS_DAYS
    contact_email: str = DEFAULT_CONTACT_EMAIL
    offer_url: str = ""

    def term(self, months: Any) -> Optional[PurchaseTerm]:
        try:
            value = int(months)
        except (TypeError, ValueError):
            return None
        return next((term for term in self.terms if term.months == value), None)


@dataclass(frozen=True)
class Quote:
    months: int
    label: str
    price_month: Decimal
    base: Decimal
    discount: Decimal
    subtotal: Decimal
    vat_mode: str
    vat_rate: Decimal
    vat: Decimal
    total: Decimal

    @property
    def per_month(self) -> Decimal:
        return (self.total / self.months).quantize(_KOPECK, ROUND_HALF_UP)

    def as_payload(self) -> Dict[str, Any]:
        return {
            "months": self.months,
            "label": self.label,
            "price_month": money_str(self.price_month),
            "base": money_str(self.base),
            "discount": money_str(self.discount),
            "subtotal": money_str(self.subtotal),
            "vat_mode": self.vat_mode,
            "vat_rate": _plain_number(self.vat_rate),
            "vat": money_str(self.vat),
            "total": money_str(self.total),
            "per_month": money_str(self.per_month),
            "vat_text": vat_text(self.vat_mode, self.vat_rate, self.vat),
        }


def _plain_number(value: Decimal) -> str:
    text = format(Decimal(value).normalize(), "f")
    return text


def money_str(value: Decimal) -> str:
    """Сумма строкой с копейками через точку: JSON без потери точности."""
    return format(Decimal(value).quantize(_KOPECK, ROUND_HALF_UP), "f")


def money_human(value: Decimal) -> str:
    """«3 000» или «5 409,84» — для текстов людям: пробел-разделитель тысяч,
    копейки только если они есть. Обычный пробел, не NBSP: текст уходит в
    задачи и уведомления Битрикс24, где NBSP ломает поиск."""
    amount = Decimal(value).quantize(_KOPECK, ROUND_HALF_UP)
    rubles, _, kopecks = format(amount, "f").partition(".")
    sign = "-" if rubles.startswith("-") else ""
    rubles = rubles.lstrip("-")
    grouped = " ".join(rubles[max(0, i - 3):i] for i in range(len(rubles), 0, -3)[::-1])
    return f"{sign}{grouped}" + (f",{kopecks}" if kopecks and kopecks != "00" else "")


def money_ru(value: Decimal) -> str:
    """«5409,84» — как в платёжке: запятая, без пробелов-разделителей."""
    return money_str(value).replace(".", ",")


# ---------------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------------


def _parse_terms(raw: Any) -> Tuple[PurchaseTerm, ...]:
    terms: List[PurchaseTerm] = []
    seen = set()
    for item in raw or ():
        if not isinstance(item, Mapping):
            raise ValueError("срок должен быть объектом")
        months = int(item.get("months"))
        if months <= 0 or months > 60 or months in seen:
            raise ValueError(f"недопустимый срок {months}")
        percent = Decimal(str(item.get("discount_percent") or 0))
        if percent < 0 or percent >= 100:
            raise ValueError(f"недопустимая скидка {percent}")
        paid_raw = item.get("paid_months")
        paid = int(paid_raw) if paid_raw not in (None, "") else None
        if paid is not None and not (0 < paid <= months):
            raise ValueError(f"недопустимое paid_months {paid}")
        seen.add(months)
        terms.append(PurchaseTerm(months=months, discount_percent=percent, paid_months=paid))
    if not terms:
        raise ValueError("список сроков пуст")
    return tuple(sorted(terms, key=lambda term: term.months))


def _env_int(env: Mapping[str, str], name: str, default: int, *, minimum: int = 0) -> int:
    raw = str(env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s: ожидается целое число, взято значение по умолчанию %s", name, default)
        return default
    if value < minimum:
        logger.warning("%s: значение меньше %s, взято значение по умолчанию %s", name, minimum, default)
        return default
    return value


def load_purchase_settings(env: Optional[Mapping[str, str]] = None) -> PurchaseSettings:
    """Настройки покупки из окружения (по умолчанию os.environ)."""
    env = os.environ if env is None else env

    price = _env_int(env, "PRO_PRICE_MONTH_RUB", DEFAULT_PRICE_MONTH_RUB, minimum=1)

    vat_mode = str(env.get("PRO_VAT_MODE") or "").strip().lower() or DEFAULT_VAT_MODE
    if vat_mode not in VAT_MODES:
        logger.warning("PRO_VAT_MODE: неизвестный режим, взят %s", DEFAULT_VAT_MODE)
        vat_mode = DEFAULT_VAT_MODE

    vat_rate = DEFAULT_VAT_RATE
    raw_rate = str(env.get("PRO_VAT_RATE") or "").strip().replace(",", ".")
    if raw_rate:
        try:
            parsed = Decimal(raw_rate)
            if not (Decimal("0") <= parsed < Decimal("100")):
                raise ValueError
            vat_rate = parsed
        except Exception:  # noqa: BLE001 — InvalidOperation и ValueError
            logger.warning("PRO_VAT_RATE: недопустимая ставка, взята %s", DEFAULT_VAT_RATE)

    terms = _parse_terms(DEFAULT_TERMS)
    raw_terms = str(env.get("PRO_TERMS") or "").strip()
    if raw_terms:
        try:
            terms = _parse_terms(json.loads(raw_terms))
        except Exception as exc:  # noqa: BLE001
            logger.warning("PRO_TERMS: не разобран (%s), взяты сроки по умолчанию", exc)

    default_months = _env_int(env, "PRO_DEFAULT_MONTHS", DEFAULT_MONTHS, minimum=1)
    if default_months not in {term.months for term in terms}:
        default_months = terms[-1].months

    prefix = str(env.get("PRO_INVOICE_PREFIX") or "").strip() or DEFAULT_INVOICE_PREFIX
    if len(prefix) > 10:
        prefix = DEFAULT_INVOICE_PREFIX

    return PurchaseSettings(
        price_month_rub=price,
        vat_mode=vat_mode,
        vat_rate=vat_rate,
        terms=terms,
        default_months=default_months,
        invoice_prefix=prefix,
        due_business_days=_env_int(env, "PRO_INVOICE_DUE_BUSINESS_DAYS", DEFAULT_DUE_BUSINESS_DAYS, minimum=1),
        contact_email=str(env.get("PRO_CONTACT_EMAIL") or "").strip() or DEFAULT_CONTACT_EMAIL,
        offer_url=_offer_url(env.get("PRO_OFFER_URL")),
    )


def _offer_url(raw) -> str:
    value = str(raw or "").strip()
    return value if value.startswith("https://") and len(value) <= 500 else ""


# ---------------------------------------------------------------------------
# Расчёт
# ---------------------------------------------------------------------------


def calculate_quote(settings: PurchaseSettings, term: PurchaseTerm,
                    price_month_rub: Optional[int] = None) -> Quote:
    """Сумма за срок: база, скидка, НДС, итог.

    Скидка — в целых рублях (процент от базы) либо «N по цене M». НДС:
    - none     — не облагается, итог = цена со скидкой;
    - included — цена уже содержит НДС, выделяется rate/(100+rate);
    - on_top   — НДС начисляется сверху, итог больше цены.
    """
    price = Decimal(price_month_rub or settings.price_month_rub)
    months = term.months
    base = price * months
    if term.paid_months is not None:
        discount = price * (months - term.paid_months)
    else:
        discount = (base * term.discount_percent / Decimal(100)).quantize(_RUBLE, ROUND_HALF_UP)
    subtotal = base - discount
    rate = settings.vat_rate
    if settings.vat_mode == VAT_INCLUDED and rate > 0:
        vat = (subtotal * rate / (Decimal(100) + rate)).quantize(_KOPECK, ROUND_HALF_UP)
        total = subtotal
    elif settings.vat_mode == VAT_ON_TOP and rate > 0:
        vat = (subtotal * rate / Decimal(100)).quantize(_KOPECK, ROUND_HALF_UP)
        total = subtotal + vat
    else:
        vat = Decimal("0")
        total = subtotal
    return Quote(
        months=months,
        label=term.label,
        price_month=price.quantize(_KOPECK),
        base=base.quantize(_KOPECK),
        discount=discount.quantize(_KOPECK),
        subtotal=subtotal.quantize(_KOPECK),
        vat_mode=settings.vat_mode if rate > 0 else VAT_NONE,
        vat_rate=rate,
        vat=vat,
        total=total.quantize(_KOPECK),
    )


def vat_text(vat_mode: str, vat_rate: Decimal, vat_amount: Decimal) -> str:
    """Строка НДС для назначения платежа: платёж всегда содержит НДС целиком."""
    if vat_mode == VAT_NONE or Decimal(vat_rate) <= 0:
        return "Без НДС"
    return f"В т.ч. НДС {_plain_number(Decimal(vat_rate))}% {money_ru(vat_amount)} руб."


def add_business_days(start: date, days: int) -> date:
    """Дата через N рабочих дней (без праздничного календаря)."""
    current = start
    left = max(0, int(days))
    while left > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            left -= 1
    return current


def months_text(months: int) -> str:
    value = abs(int(months))
    if 11 <= value % 100 <= 14:
        word = "месяцев"
    elif value % 10 == 1:
        word = "месяц"
    elif 2 <= value % 10 <= 4:
        word = "месяца"
    else:
        word = "месяцев"
    return f"{months} {word}"


def build_payment_purpose(*, invoice_number: str, invoice_date: date, months: int, domain: str,
                          portal_code: str, vat_mode: str, vat_rate: Decimal, vat_amount: Decimal,
                          limit: int = PAYMENT_PURPOSE_LIMIT) -> str:
    """Назначение платежа по шаблону записки, не длиннее limit символов.

    Шаблон: «Оплата по счёту № УТ-0047 от 12.09.2026. Подписка Pro «Учёт
    трудозатрат» на 12 мес., портал kvarc-int.bitrix24.ru, код 482137. Без
    НДС». Если не влезает — сокращаем по шагам, но номер счёта и код портала
    остаются всегда: это два независимых ключа сопоставления платежа.
    """
    day = f"{invoice_date:%d.%m.%Y}"
    vat = vat_text(vat_mode, vat_rate, vat_amount)
    domain = str(domain or "").strip()
    variants = [
        f"Оплата по счёту № {invoice_number} от {day}. Подписка Pro «{PRODUCT_TITLE}» на {months} мес., "
        f"портал {domain}, код {portal_code}. {vat}",
        f"Оплата по сч. № {invoice_number} от {day}. Pro на {months} мес., портал {domain}, "
        f"код {portal_code}. {vat}",
    ]
    for text in variants:
        if domain and len(text) <= limit:
            return text

    head = f"Оплата по сч. № {invoice_number} от {day}. Pro на {months} мес."
    tail = f", код {portal_code}. {vat}"
    if domain:
        # Домен не влез целиком — обрезаем его, а не ключи.
        room = limit - len(head) - len(", портал ") - len(tail)
        if room >= 12:
            clipped = domain if len(domain) <= room else domain[: room - 1] + "…"
            return f"{head}, портал {clipped}{tail}"
    without_domain = f"{head}{tail}"
    if len(without_domain) <= limit:
        return without_domain
    # Последний рубеж: только ключи. Номер и код короче лимита всегда.
    return f"Оплата по сч. № {invoice_number}, код {portal_code}. {vat}"[:limit]


# ---------------------------------------------------------------------------
# Проверка формы
# ---------------------------------------------------------------------------

PAYER_ORG = "org"
PAYER_IP = "ip"

KPP_RE = re.compile(r"^\d{4}[0-9A-Z]{2}\d{3}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")

FIELD_LIMITS = {
    "contact_name": 255,
    "contact_email": 254,
    "contact_cc": 254,
    "contact_phone": 32,
    "payer_name": 500,
    "payer_address": 500,
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def payer_type_for_inn(inn: str) -> str:
    return PAYER_IP if len(inn) == 12 else PAYER_ORG


def validate_purchase_form(data: Mapping[str, Any], settings: PurchaseSettings) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Те же правила, что во фронтовой форме. Возвращает (очищенное, ошибки).

    Контрольная сумма ИНН НЕ проверяется — ровно как в inn_validation.py:
    фронт о ней только предупреждает.
    """
    errors: Dict[str, str] = {}
    inn = re.sub(r"\s+", "", normalize_inn(data.get("payer_inn")))
    inn_error = validate_inn(inn)
    if inn_error:
        errors["payer_inn"] = inn_error
    payer_type = payer_type_for_inn(inn)

    kpp = re.sub(r"\s+", "", str(data.get("payer_kpp") or "")).upper()
    if payer_type == PAYER_IP:
        kpp = ""
    elif not kpp:
        errors["payer_kpp"] = "Укажите КПП — у организации он обязателен."
    elif not KPP_RE.match(kpp):
        errors["payer_kpp"] = "КПП — 9 знаков: 4 цифры, 2 цифры или заглавные латинские буквы, 3 цифры."

    name = _text(data.get("payer_name"))
    if len(name) < 3:
        errors["payer_name"] = (
            "Укажите ФИО предпринимателя." if payer_type == PAYER_IP
            else "Укажите полное наименование организации."
        )

    address = _text(data.get("payer_address"))
    if len(address) < 10:
        errors["payer_address"] = "Укажите юридический адрес."

    email = _text(data.get("contact_email"))
    if not email:
        errors["contact_email"] = "Укажите почту, на которую отправить счёт."
    elif not EMAIL_RE.match(email):
        errors["contact_email"] = "Почта выглядит неполной: нужен вид name@company.ru."

    cc = _text(data.get("contact_cc"))
    if cc and not EMAIL_RE.match(cc):
        errors["contact_cc"] = "Проверьте адрес копии или оставьте поле пустым."

    phone = _text(data.get("contact_phone"))
    if phone:
        digits = re.sub(r"\D", "", phone)
        if not 10 <= len(digits) <= 11:
            errors["contact_phone"] = "Телефон: 10–11 цифр, например +7 842 250-14-80."

    contact = _text(data.get("contact_name"))
    if len(contact) < 2:
        errors["contact_name"] = "Укажите, кому писать по счёту."

    term = settings.term(data.get("months"))
    if term is None:
        allowed = ", ".join(str(item.months) for item in settings.terms)
        errors["months"] = f"Выберите срок подписки: {allowed} мес."

    if data.get("offer_accepted") is not True:
        errors["offer_accepted"] = "Отметьте согласие с условиями оферты."

    cleaned = {
        "payer_type": payer_type,
        "payer_inn": inn,
        "payer_kpp": kpp,
        "payer_name": name,
        "payer_address": address,
        "contact_name": contact,
        "contact_email": email,
        "contact_cc": cc,
        "contact_phone": phone,
        "months": term.months if term else None,
        "payer_company_id": _text(data.get("payer_company_id"))[:50],
    }
    for key, limit in FIELD_LIMITS.items():
        if len(cleaned[key]) > limit:
            errors.setdefault(key, f"Слишком длинное значение: не больше {limit} символов.")
    return cleaned, errors
