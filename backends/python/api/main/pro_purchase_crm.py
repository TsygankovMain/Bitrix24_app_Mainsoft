"""Отправка заявки на Pro в CRM портала Mainsoft через входящий вебхук.

Портал Mainsoft — не портал клиента: запись идёт не токеном приложения, а
отдельным вебхуком с узкими правами (crm, task, im, documentgenerator).
Адрес вебхука — секрет, он живёт ТОЛЬКО в окружении сервера:

    MAINSOFT_BILLING_WEBHOOK   https://<портал>/rest/<user>/<token>/

Без этой переменной — безопасный режим: заявка сохраняется у нас со статусом
«ожидает отправки», в CRM ничего не уходит, интерфейс честно пишет, что счёт
готовится вручную. Адрес вебхука не пишется ни в лог, ни в ответ API, ни в
текст ошибки: всё, что уходит наружу, проходит через _scrub.

Поток при заданном вебхуке — компания -> (сделка, если настроена воронка) ->
смарт-счёт -> PDF -> задача на контроль оплаты -> лента и уведомление:

    Сделка необязательна. MAINSOFT_BILLING_DEAL_CATEGORY_ID пуст — сделка не
    создаётся вовсе, смарт-счёт выставляется напрямую на компанию клиента
    (`companyId`) от нашего юрлица (`mycompanyId`), без `parentId2`. Категория
    задана — сделка создаётся, как раньше, и счёт привязывается к ней.

    Смарт-счёт требует продавца: без MAINSOFT_BILLING_MY_COMPANY_ID отправка
    падает с понятной ошибкой (заявка остаётся «ожидает отправки») — без
    юрлица Mainsoft счёт выставить нельзя.

    Задача tasks.task.add создаётся один раз после смарт-счёта — «проконтро-
    лировать оплату», с дедлайном по сроку оплаты счёта и привязкой к CRM
    через UF_CRM_TASK (коды владельца из crm.enum.ownertype: SI — смарт-счёт,
    D — сделка, CO — компания). Сбой создания задачи не откатывает счёт:
    предупреждение сохраняется в заявке, следующий `pro_requests sync`
    досоздаёт только задачу (счёт и компания уже на месте — идемпотентно).

Остальная настройка — тоже окружение (всё необязательно, кроме
MAINSOFT_BILLING_MY_COMPANY_ID; пусто — шаг пропускается или данные уходят в
комментарий):

    MAINSOFT_BILLING_PORTAL_URL           https://mainsoft.bitrix24.ru (ссылки в консоли)
    MAINSOFT_BILLING_MY_COMPANY_ID        наше юрлицо в смарт-счёте (обязательно)
    MAINSOFT_BILLING_DEAL_CATEGORY_ID     воронка «Подписки Pro» — пусто, сделки нет
    MAINSOFT_BILLING_STAGE_NEW            стадия новой сделки («Заявка из приложения»)
    MAINSOFT_BILLING_STAGE_INVOICED       стадия сделки после счёта («Счёт выставлен»)
    MAINSOFT_BILLING_STAGE_PAID           стадия сделки после оплаты («Pro включён»)
    MAINSOFT_BILLING_STAGE_LOST           стадия сделки при отмене («Не оплачен»)
    MAINSOFT_BILLING_INVOICE_STAGE_PAID   стадия смарт-счёта после оплаты (пример: DT31_3:P)
    MAINSOFT_BILLING_INVOICE_STAGE_LOST   стадия смарт-счёта при отмене (пример: DT31_3:D)
    MAINSOFT_BILLING_RESPONSIBLE_ID       ответственный за сделку и счёт
    MAINSOFT_BILLING_INVOICE_TEMPLATE_ID  шаблон «Счёт Pro» генератора документов
    MAINSOFT_BILLING_NOTIFY_USER_ID       кому im.notify о новой заявке
    MAINSOFT_BILLING_TASK_RESPONSIBLE_ID  ответственный за задачу (иначе RESPONSIBLE_ID, иначе NOTIFY_USER_ID)
    MAINSOFT_BILLING_TASK_GROUP_ID        группа задачи (необязательно)
    MAINSOFT_BILLING_TASK_AUDITORS        наблюдатели задачи, id через запятую (необязательно)
    MAINSOFT_BILLING_PRESET_ORG_ID        пресет реквизита организации (1)
    MAINSOFT_BILLING_PRESET_IP_ID         пресет реквизита ИП (2 по умолчанию; на портале
                                          Mainsoft фактический пресет — 3, задайте явно)
    MAINSOFT_BILLING_FIELD_DOMAIN         UF-поля сделки: домен портала,
    MAINSOFT_BILLING_FIELD_MEMBER_ID        member_id,
    MAINSOFT_BILLING_FIELD_PORTAL_CODE      код портала,
    MAINSOFT_BILLING_FIELD_REQUEST          номер счёта/заявки,
    MAINSOFT_BILLING_FIELD_MONTHS           срок в месяцах,
    MAINSOFT_BILLING_FIELD_PAID_UNTIL       «Pro оплачено до»,
    MAINSOFT_BILLING_FIELD_SOURCE           источник

Идемпотентность. Каждый созданный объект (компания, сделка, счёт, задача)
сразу запоминается в заявке и сохраняется в БД — повторная отправка обновляет
его, а не создаёт второй. Если процесс упал между созданием сделки и
сохранением её id, сделку находит поиск по номеру счёта (UF-поле заявки или
заголовок); то же для счёта — поиск по названию.

Ответам REST Битрикс24 на слово не верим: сделка и счёт перечитываются, сумма
счёта сверяется с заявкой.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal
from typing import Any, Callable, Dict, Mapping, Optional, Tuple
from urllib.parse import urlsplit

from .pro_purchase_pricing import VAT_NONE, VAT_ON_TOP, money_human, money_str, months_text, vat_text

logger = logging.getLogger(__name__)

WEBHOOK_ENV = "MAINSOFT_BILLING_WEBHOOK"
SMART_INVOICE_ENTITY_TYPE_ID = 31
DEAL_SOURCE_TEXT = "Кнопка «Купить Pro» в приложении «Учёт трудозатрат»"
#: Дедлайн задачи — момент, к которому просим проконтролировать оплату.
_MSK = dt_timezone(timedelta(hours=3))


class CrmSyncError(Exception):
    """Отправка в CRM не удалась. Текст без адреса вебхука — можно показывать."""

    def __init__(self, message: str, *, method: str = ""):
        super().__init__(message)
        self.method = method


@dataclass(frozen=True)
class CrmSettings:
    webhook: str
    portal_url: str = ""
    deal_category_id: str = ""
    stage_new: str = ""
    stage_invoiced: str = ""
    stage_paid: str = ""
    stage_lost: str = ""
    invoice_stage_paid: str = ""
    invoice_stage_lost: str = ""
    responsible_id: str = ""
    my_company_id: str = ""
    invoice_template_id: str = ""
    notify_user_id: str = ""
    task_responsible_id: str = ""
    task_group_id: str = ""
    task_auditors: Tuple[str, ...] = ()
    preset_org_id: str = "1"
    preset_ip_id: str = "2"
    fields: Dict[str, str] = field(default_factory=dict)

    def deal_link(self, deal_id: str) -> str:
        return f"{self.portal_url}/crm/deal/details/{deal_id}/" if self.portal_url and deal_id else ""

    def invoice_link(self, invoice_id: str) -> str:
        if not (self.portal_url and invoice_id):
            return ""
        return f"{self.portal_url}/crm/type/{SMART_INVOICE_ENTITY_TYPE_ID}/details/{invoice_id}/"

    def task_link(self, task_id: str) -> str:
        if not (self.portal_url and task_id):
            return ""
        return f"{self.portal_url}/company/personal/user/0/tasks/task/view/{task_id}/"


FIELD_ENV = {
    "domain": "MAINSOFT_BILLING_FIELD_DOMAIN",
    "member_id": "MAINSOFT_BILLING_FIELD_MEMBER_ID",
    "portal_code": "MAINSOFT_BILLING_FIELD_PORTAL_CODE",
    "request": "MAINSOFT_BILLING_FIELD_REQUEST",
    "months": "MAINSOFT_BILLING_FIELD_MONTHS",
    "paid_until": "MAINSOFT_BILLING_FIELD_PAID_UNTIL",
    "source": "MAINSOFT_BILLING_FIELD_SOURCE",
}


def load_crm_settings(env: Optional[Mapping[str, str]] = None) -> Optional[CrmSettings]:
    """Настройки отправки. None — вебхук не задан, работаем в безопасном режиме."""
    env = os.environ if env is None else env

    def read(name: str, default: str = "") -> str:
        return str(env.get(name) or "").strip() or default

    webhook = read(WEBHOOK_ENV)
    if not webhook:
        return None
    parts = urlsplit(webhook)
    if parts.scheme != "https" or not parts.netloc:
        logger.error("%s задан, но это не https-адрес — отправка в CRM выключена", WEBHOOK_ENV)
        return None
    portal_url = read("MAINSOFT_BILLING_PORTAL_URL", f"https://{parts.netloc}").rstrip("/")
    auditors_raw = read("MAINSOFT_BILLING_TASK_AUDITORS")
    return CrmSettings(
        webhook=webhook.rstrip("/") + "/",
        portal_url=portal_url,
        deal_category_id=read("MAINSOFT_BILLING_DEAL_CATEGORY_ID"),
        stage_new=read("MAINSOFT_BILLING_STAGE_NEW"),
        stage_invoiced=read("MAINSOFT_BILLING_STAGE_INVOICED"),
        stage_paid=read("MAINSOFT_BILLING_STAGE_PAID"),
        stage_lost=read("MAINSOFT_BILLING_STAGE_LOST"),
        invoice_stage_paid=read("MAINSOFT_BILLING_INVOICE_STAGE_PAID"),
        invoice_stage_lost=read("MAINSOFT_BILLING_INVOICE_STAGE_LOST"),
        responsible_id=read("MAINSOFT_BILLING_RESPONSIBLE_ID"),
        my_company_id=read("MAINSOFT_BILLING_MY_COMPANY_ID"),
        invoice_template_id=read("MAINSOFT_BILLING_INVOICE_TEMPLATE_ID"),
        notify_user_id=read("MAINSOFT_BILLING_NOTIFY_USER_ID"),
        task_responsible_id=read("MAINSOFT_BILLING_TASK_RESPONSIBLE_ID"),
        task_group_id=read("MAINSOFT_BILLING_TASK_GROUP_ID"),
        task_auditors=tuple(part.strip() for part in auditors_raw.split(",") if part.strip()),
        preset_org_id=read("MAINSOFT_BILLING_PRESET_ORG_ID", "1"),
        preset_ip_id=read("MAINSOFT_BILLING_PRESET_IP_ID", "2"),
        fields={key: read(name) for key, name in FIELD_ENV.items() if read(name)},
    )


def crm_configured() -> bool:
    return load_crm_settings() is not None


class WebhookTransport:
    """POST JSON на <вебхук>/<метод>.json. Секрет не попадает в исключения."""

    def __init__(self, webhook: str, timeout: float = 15.0):
        self._webhook = webhook
        self._timeout = timeout

    def _scrub(self, text: Any) -> str:
        value = str(text or "")
        if self._webhook:
            value = value.replace(self._webhook, "<webhook>").replace(self._webhook.rstrip("/"), "<webhook>")
        return value[:500]

    def call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        body = json.dumps(params or {}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self._webhook}{method}.json", data=body, method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310 — https из настройки
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read() if hasattr(exc, "read") else b""
            payload = _json_or_empty(raw)
            description = payload.get("error_description") or payload.get("error") or f"HTTP {exc.code}"
            raise CrmSyncError(f"{method}: {self._scrub(description)}", method=method) from None
        except Exception as exc:  # noqa: BLE001 — сеть, таймаут, TLS
            raise CrmSyncError(f"{method}: портал Mainsoft не ответил ({type(exc).__name__})", method=method) from None
        payload = _json_or_empty(raw)
        if "error" in payload:
            description = payload.get("error_description") or payload.get("error")
            raise CrmSyncError(f"{method}: {self._scrub(description)}", method=method)
        return payload

    def call_bytes(self, method: str, params: Optional[Dict[str, Any]] = None,
                   limit: int = 20 * 1024 * 1024) -> bytes:
        """Метод REST, который отдаёт файл, а не JSON.

        Так скачивается PDF счёта: crm.documentgenerator.document.getpdf по
        вебхуку возвращает сам application/pdf. Ссылки pdfUrl/downloadUrl из
        ответа генератора ведут на /bitrix/services/main/ajax.php и требуют
        браузерной сессии портала — сервер получает там 403 (проверено
        14.09.2026 на портале Mainsoft). Ошибку метод отдаёт JSON-ом.
        """
        body = json.dumps(params or {}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self._webhook}{method}", data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout * 2) as response:  # noqa: S310 — https из настройки
                content_type = str(response.headers.get("Content-Type") or "")
                data = response.read(limit + 1)
        except urllib.error.HTTPError as exc:
            payload = _json_or_empty(exc.read() if hasattr(exc, "read") else b"")
            description = payload.get("error_description") or payload.get("error") or f"HTTP {exc.code}"
            raise CrmSyncError(f"{method}: {self._scrub(description)}", method=method) from None
        except Exception as exc:  # noqa: BLE001 — сеть, таймаут, TLS
            raise CrmSyncError(f"{method}: портал Mainsoft не ответил ({type(exc).__name__})", method=method) from None
        if len(data) > limit:
            raise CrmSyncError("Файл больше допустимого размера", method=method)
        if "json" in content_type.lower():
            payload = _json_or_empty(data)
            description = payload.get("error_description") or payload.get("error") or "портал вернул не файл"
            raise CrmSyncError(f"{method}: {self._scrub(description)}", method=method)
        return data

    def fetch_bytes(self, url: str, limit: int = 20 * 1024 * 1024) -> bytes:
        """Скачать файл генератора документов (ссылка может содержать токен)."""
        try:
            with urllib.request.urlopen(url, timeout=self._timeout * 2) as response:  # noqa: S310
                data = response.read(limit + 1)
        except Exception as exc:  # noqa: BLE001
            raise CrmSyncError(f"PDF не скачан ({type(exc).__name__})") from None
        if len(data) > limit:
            raise CrmSyncError("PDF больше допустимого размера")
        return data


def _json_or_empty(raw: bytes) -> Dict[str, Any]:
    try:
        value = json.loads((raw or b"{}").decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return value if isinstance(value, dict) else {}


def build_transport(settings: CrmSettings) -> WebhookTransport:
    return WebhookTransport(settings.webhook)


def _id(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("id") or value.get("ID")
    text = str(value if value is not None else "").strip()
    return text if text.isdigit() and text != "0" else ""


def _rows(result: Any) -> list:
    if isinstance(result, dict):
        for key in ("items", "item"):
            if isinstance(result.get(key), list):
                return result[key]
        return []
    return result if isinstance(result, list) else []


class ProRequestCrmSync:
    """Шаги записи заявки на портал Mainsoft. Сохраняет прогресс в заявке.

    save — колбэк сохранения заявки после каждого созданного объекта (в
    тестах и в сервисе это request.save(update_fields=...)).
    """

    def __init__(self, transport, settings: CrmSettings,
                 save: Optional[Callable[[Any, list], None]] = None):
        self.transport = transport
        self.settings = settings
        self._save = save or (lambda request, fields: request.save(update_fields=fields + ["updated_at"]))

    # -- общие куски -------------------------------------------------------

    def _call(self, method: str, params: Dict[str, Any]) -> Any:
        payload = self.transport.call(method, params)
        return payload.get("result") if isinstance(payload, dict) else None

    def _remember(self, request, **values):
        for name, value in values.items():
            setattr(request, name, value)
        self._save(request, list(values))

    def _deal_title(self, request) -> str:
        return f"Pro · {request.domain_snapshot} · {months_text(request.months)} · {request.invoice_number}"

    def _summary(self, request) -> str:
        lines = [
            f"Заявка из «Учёта трудозатрат», счёт {request.invoice_number} от {request.invoice_date:%d.%m.%Y}.",
            f"Портал: {request.domain_snapshot}",
            f"Код портала: {request.portal_code}",
            f"member_id: {request.member_id_snapshot}",
            f"Плательщик: {request.payer_name}, ИНН {request.payer_inn}"
            + (f", КПП {request.payer_kpp}" if request.payer_kpp else ""),
            f"Адрес: {request.payer_address}",
            f"Контакт: {request.contact_name}, {request.contact_email}"
            + (f", копия {request.contact_cc}" if request.contact_cc else "")
            + (f", тел. {request.contact_phone}" if request.contact_phone else ""),
            f"Запросил: {request.requested_by_name or request.requested_by_id}"
            + (" (администратор портала)" if request.requested_by_admin else ""),
            f"Срок: {months_text(request.months)}. К оплате: {money_human(request.total_amount)} ₽ до {request.due_date:%d.%m.%Y}.",
            f"Назначение платежа: {request.payment_purpose}",
        ]
        return "\n".join(lines)

    # -- компания ----------------------------------------------------------

    def _ensure_company(self, request) -> str:
        if request.crm_company_id:
            return request.crm_company_id
        found = _rows(self._call("crm.requisite.list", {
            "filter": {"RQ_INN": request.payer_inn, "ENTITY_TYPE_ID": 4},
            "select": ["ID", "ENTITY_ID", "RQ_KPP"],
        }))
        company_id = ""
        for row in found:
            if not isinstance(row, dict):
                continue
            candidate = _id(row.get("ENTITY_ID"))
            if not candidate:
                continue
            # У филиалов один ИНН и разные КПП: предпочитаем точное совпадение.
            if not request.payer_kpp or str(row.get("RQ_KPP") or "") == request.payer_kpp:
                company_id = candidate
                break
            company_id = company_id or candidate
        if company_id:
            self._remember(request, crm_company_id=company_id)
            return company_id

        fields: Dict[str, Any] = {
            "TITLE": request.payer_name[:255],
            "COMPANY_TYPE": "CUSTOMER",
            "COMMENTS": f"Создана заявкой на Pro {request.invoice_number}",
        }
        if request.contact_email:
            fields["EMAIL"] = [{"VALUE": request.contact_email, "VALUE_TYPE": "WORK"}]
        if request.contact_phone:
            fields["PHONE"] = [{"VALUE": request.contact_phone, "VALUE_TYPE": "WORK"}]
        if self.settings.responsible_id:
            fields["ASSIGNED_BY_ID"] = self.settings.responsible_id
        company_id = _id(self._call("crm.company.add", {"fields": fields}))
        if not company_id:
            raise CrmSyncError("crm.company.add: портал не вернул id компании", method="crm.company.add")
        self._remember(request, crm_company_id=company_id)

        is_ip = request.payer_type == "ip"
        requisite = {
            "ENTITY_TYPE_ID": 4,
            "ENTITY_ID": company_id,
            "PRESET_ID": self.settings.preset_ip_id if is_ip else self.settings.preset_org_id,
            "NAME": request.payer_name[:255],
            "RQ_INN": request.payer_inn,
        }
        if is_ip:
            requisite["RQ_NAME"] = request.payer_name[:255]
        else:
            requisite["RQ_COMPANY_FULL_NAME"] = request.payer_name[:500]
            requisite["RQ_KPP"] = request.payer_kpp
        try:
            requisite_id = _id(self._call("crm.requisite.add", {"fields": requisite}))
            if requisite_id and request.payer_address:
                self._call("crm.address.add", {"fields": {
                    "TYPE_ID": 6, "ENTITY_TYPE_ID": 8, "ENTITY_ID": requisite_id,
                    "ADDRESS_1": request.payer_address[:255],
                }})
        except CrmSyncError as exc:
            # Реквизит — удобство менеджера, а не условие счёта: все данные
            # есть в комментарии сделки. Счёт из-за него не останавливаем.
            logger.warning("Pro %s: реквизит компании не записан: %s", request.invoice_number, exc)
        return company_id

    # -- сделка (необязательна: только если задан MAINSOFT_BILLING_DEAL_CATEGORY_ID) --

    def _deal_fields(self, request, company_id: str) -> Dict[str, Any]:
        fields: Dict[str, Any] = {
            "TITLE": self._deal_title(request),
            "OPPORTUNITY": money_str(request.total_amount),
            "CURRENCY_ID": "RUB",
            "COMPANY_ID": company_id,
            "SOURCE_DESCRIPTION": DEAL_SOURCE_TEXT,
            "COMMENTS": self._summary(request),
        }
        if self.settings.deal_category_id:
            fields["CATEGORY_ID"] = self.settings.deal_category_id
        if self.settings.responsible_id:
            fields["ASSIGNED_BY_ID"] = self.settings.responsible_id
        values = {
            "domain": request.domain_snapshot,
            "member_id": request.member_id_snapshot,
            "portal_code": request.portal_code,
            "request": request.invoice_number,
            "months": request.months,
            "source": DEAL_SOURCE_TEXT,
        }
        for key, value in values.items():
            code = self.settings.fields.get(key)
            if code:
                fields[code] = value
        return fields

    def _find_deal(self, request) -> str:
        code = self.settings.fields.get("request")
        flt: Dict[str, Any] = {code: request.invoice_number} if code else {"%TITLE": request.invoice_number}
        if self.settings.deal_category_id:
            flt["CATEGORY_ID"] = self.settings.deal_category_id
        for row in _rows(self._call("crm.deal.list", {"filter": flt, "select": ["ID", "TITLE"]})):
            if isinstance(row, dict) and (code or request.invoice_number in str(row.get("TITLE") or "")):
                deal_id = _id(row.get("ID"))
                if deal_id:
                    return deal_id
        return ""

    def _ensure_deal(self, request, company_id: str) -> str:
        fields = self._deal_fields(request, company_id)
        deal_id = request.crm_deal_id or self._find_deal(request)
        if deal_id:
            fields.pop("CATEGORY_ID", None)  # воронку у существующей сделки не трогаем
            self._call("crm.deal.update", {"id": deal_id, "fields": fields})
        else:
            if self.settings.stage_new:
                fields["STAGE_ID"] = self.settings.stage_new
            deal_id = _id(self._call("crm.deal.add", {"fields": fields}))
            if not deal_id:
                raise CrmSyncError("crm.deal.add: портал не вернул id сделки", method="crm.deal.add")
        if deal_id != request.crm_deal_id:
            self._remember(request, crm_deal_id=deal_id)
        check = self._call("crm.deal.get", {"id": deal_id})
        if not isinstance(check, dict) or _id(check.get("ID")) != deal_id:
            raise CrmSyncError(f"crm.deal.get: сделка {deal_id} не перечитывается", method="crm.deal.get")
        return deal_id

    # -- смарт-счёт ----------------------------------------------------------

    def _invoice_title(self, request) -> str:
        return f"Счёт {request.invoice_number} · Pro «Учёт трудозатрат»"

    def _find_invoice(self, request, deal_id: str) -> str:
        flt: Dict[str, Any] = {"%title": request.invoice_number}
        if deal_id:
            flt["parentId2"] = int(deal_id)
        result = self._call("crm.item.list", {
            "entityTypeId": SMART_INVOICE_ENTITY_TYPE_ID,
            "filter": flt,
            "select": ["id", "title"],
        })
        for row in _rows(result):
            if isinstance(row, dict) and request.invoice_number in str(row.get("title") or ""):
                invoice_id = _id(row.get("id"))
                if invoice_id:
                    return invoice_id
        return ""

    def _create_or_update_invoice(self, request, deal_id: str, company_id: str) -> str:
        fields: Dict[str, Any] = {
            "title": self._invoice_title(request),
            "companyId": int(company_id),
            "currencyId": "RUB",
            "opportunity": float(request.total_amount),
            "begindate": request.invoice_date.isoformat(),
            "closedate": request.due_date.isoformat(),
            "comments": request.payment_purpose,
        }
        if deal_id:
            fields["parentId2"] = int(deal_id)
        if self.settings.my_company_id:
            fields["mycompanyId"] = int(self.settings.my_company_id)
        if self.settings.responsible_id:
            fields["assignedById"] = int(self.settings.responsible_id)

        invoice_id = request.crm_invoice_id or self._find_invoice(request, deal_id)
        if invoice_id:
            self._call("crm.item.update", {
                "entityTypeId": SMART_INVOICE_ENTITY_TYPE_ID, "id": int(invoice_id), "fields": fields,
            })
        else:
            result = self._call("crm.item.add", {"entityTypeId": SMART_INVOICE_ENTITY_TYPE_ID, "fields": fields})
            invoice_id = _id((result or {}).get("item") if isinstance(result, dict) else None)
            if not invoice_id:
                raise CrmSyncError("crm.item.add: портал не вернул id счёта", method="crm.item.add")
        if invoice_id != request.crm_invoice_id:
            self._remember(request, crm_invoice_id=invoice_id)

        row: Dict[str, Any] = {
            "productName": (
                f"Право использования Pro-функций приложения «Учёт трудозатрат» для портала "
                f"{request.domain_snapshot} (код {request.portal_code}), {months_text(request.months)}"
            )[:255],
            "price": float(request.subtotal_amount),
            "quantity": 1,
        }
        if request.vat_mode != VAT_NONE and Decimal(request.vat_rate) > 0:
            row["taxRate"] = float(request.vat_rate)
            row["taxIncluded"] = "N" if request.vat_mode == VAT_ON_TOP else "Y"
        self._call("crm.item.productrow.set", {
            "ownerType": "SI", "ownerId": int(invoice_id), "productRows": [row],
        })

        check = self._call("crm.item.get", {"entityTypeId": SMART_INVOICE_ENTITY_TYPE_ID, "id": int(invoice_id)})
        item = (check or {}).get("item") if isinstance(check, dict) else None
        if not isinstance(item, dict):
            raise CrmSyncError(f"crm.item.get: счёт {invoice_id} не перечитывается", method="crm.item.get")
        try:
            opportunity = Decimal(str(item.get("opportunity")))
        except Exception:  # noqa: BLE001
            opportunity = None
        if opportunity is None or abs(opportunity - Decimal(request.total_amount)) > Decimal("0.01"):
            raise CrmSyncError(
                f"Сумма счёта в CRM ({item.get('opportunity')}) не совпала с заявкой "
                f"({money_str(request.total_amount)}) — счёт требует проверки менеджером",
                method="crm.item.get",
            )
        return invoice_id

    # -- документ ------------------------------------------------------------

    def _ensure_document(self, request, invoice_id: str) -> Optional[str]:
        """PDF по шаблону «Счёт Pro». Не критично: ошибка не останавливает счёт."""
        if request.crm_document_id or not self.settings.invoice_template_id:
            return None
        try:
            result = self._call("crm.documentgenerator.document.add", {
                "templateId": int(self.settings.invoice_template_id),
                "entityTypeId": SMART_INVOICE_ENTITY_TYPE_ID,
                "entityId": int(invoice_id),
                "values": {},
            })
        except CrmSyncError as exc:
            return f"PDF не сформирован: {exc}"
        document = (result or {}).get("document") if isinstance(result, dict) else None
        document_id = _id(document)
        if not document_id:
            return "PDF не сформирован: генератор документов не вернул документ"
        url = str(document.get("pdfUrl") or document.get("downloadUrl") or "")
        self._remember(request, crm_document_id=document_id, crm_pdf_url=url)
        return None

    # -- задача на контроль оплаты --------------------------------------------

    def _task_title(self, request) -> str:
        return (
            f"Проконтролировать оплату счёта Pro {request.invoice_number}: {request.domain_snapshot}, "
            f"{months_text(request.months)}, {money_human(request.total_amount)} ₽"
        )[:250]

    def _task_description(self, request, invoice_id: str) -> str:
        invoice_link = self.settings.invoice_link(invoice_id)
        lines = [
            "Смарт-счёт создан в CRM Mainsoft — нужно проконтролировать оплату.",
            f"Портал: {request.domain_snapshot}",
            f"member_id: {request.member_id_snapshot}",
            f"Код портала: {request.portal_code}",
            f"Срок: {months_text(request.months)}. К оплате: {money_human(request.total_amount)} ₽ до "
            f"{request.due_date:%d.%m.%Y}. {vat_text(request.vat_mode, request.vat_rate, request.vat_amount)}.",
            f"Назначение платежа: {request.payment_purpose}",
            f"Плательщик: {request.payer_name}, ИНН {request.payer_inn}"
            + (f", КПП {request.payer_kpp}" if request.payer_kpp else "") + ".",
            f"Адрес: {request.payer_address}",
            f"Контакт: {request.contact_name}, {request.contact_email}"
            + (f", копия {request.contact_cc}" if request.contact_cc else "")
            + (f", тел. {request.contact_phone}" if request.contact_phone else "") + ".",
            f"Счёт в CRM: {invoice_link}" if invoice_link else f"Счёт в CRM: id {invoice_id}",
            "",
            "Что сделать:",
            "1. Убедиться, что счёт отправлен клиенту (по e-mail или из CRM).",
            f"2. После оплаты выполнить: python manage.py pro_requests paid --invoice {request.invoice_number}",
        ]
        return "\n".join(lines)

    def _task_deadline(self, request) -> str:
        return datetime.combine(request.due_date, time(18, 0), tzinfo=_MSK).isoformat()

    def _ensure_task(self, request, *, invoice_id: str, company_id: str, deal_id: str) -> Optional[str]:
        if request.crm_task_id:
            return None
        responsible = (self.settings.task_responsible_id or self.settings.responsible_id
                       or self.settings.notify_user_id)
        if not responsible:
            message = (
                "Задача не создана: не задан ответственный — заполните "
                "MAINSOFT_BILLING_TASK_RESPONSIBLE_ID, MAINSOFT_BILLING_RESPONSIBLE_ID "
                "или MAINSOFT_BILLING_NOTIFY_USER_ID."
            )
            logger.warning("Pro %s: %s", request.invoice_number, message)
            return message

        uf_crm_task = [f"SI_{invoice_id}"]
        if company_id:
            uf_crm_task.append(f"CO_{company_id}")
        if deal_id:
            uf_crm_task.append(f"D_{deal_id}")
        fields: Dict[str, Any] = {
            "TITLE": self._task_title(request),
            "DESCRIPTION": self._task_description(request, invoice_id),
            "RESPONSIBLE_ID": responsible,
            "DEADLINE": self._task_deadline(request),
            "UF_CRM_TASK": uf_crm_task,
        }
        if self.settings.task_group_id:
            fields["GROUP_ID"] = self.settings.task_group_id
        if self.settings.task_auditors:
            fields["AUDITORS"] = list(self.settings.task_auditors)
        try:
            result = self._call("tasks.task.add", {"fields": fields})
        except CrmSyncError as exc:
            logger.warning("Pro %s: задача не создана: %s", request.invoice_number, exc)
            return f"Задача не создана: {exc}"
        task = (result or {}).get("task") if isinstance(result, dict) else None
        task_id = _id(task)
        if not task_id:
            return "Задача не создана: tasks.task.add не вернул id"
        self._remember(request, crm_task_id=task_id)
        return None

    def _notify(self, request, *, invoice_id: str, task_id: str) -> None:
        if not self.settings.notify_user_id:
            return
        invoice_link = self.settings.invoice_link(invoice_id)
        message = (
            f"Новая заявка на Pro: {request.domain_snapshot}, {months_text(request.months)}, "
            f"{money_human(request.total_amount)} ₽. Счёт {request.invoice_number}"
            + (f": {invoice_link}" if invoice_link else "") + "."
        )
        if task_id:
            task_link = self.settings.task_link(task_id)
            message += f" Задача: {task_link}" if task_link else f" Задача: {task_id}."
        self._best_effort(request, "im.notify.system.add", {
            "USER_ID": int(self.settings.notify_user_id), "MESSAGE": message.strip(),
        })

    def _best_effort(self, request, method: str, params: Dict[str, Any]) -> None:
        try:
            self._call(method, params)
        except CrmSyncError as exc:
            logger.warning("Pro %s: %s пропущен: %s", request.invoice_number, method, exc)

    # -- публичные операции --------------------------------------------------

    def send(self, request) -> Optional[str]:
        """Компания -> (сделка) -> смарт-счёт -> PDF -> задача -> лента и уведомление.

        Возвращает текст нефатального предупреждения (например, PDF или
        задача не созданы) либо None. Фатальная ошибка — CrmSyncError, заявка
        остаётся «ожидает отправки».
        """
        first_time = not request.crm_sent_at
        if not self.settings.my_company_id:
            raise CrmSyncError(
                "Без MAINSOFT_BILLING_MY_COMPANY_ID выставить счёт от Mainsoft нельзя — "
                "заполните переменную окружения.",
                method="crm.item.add",
            )
        company_id = self._ensure_company(request)
        deal_id = request.crm_deal_id
        if self.settings.deal_category_id:
            deal_id = self._ensure_deal(request, company_id)
        invoice_id = self._create_or_update_invoice(request, deal_id, company_id)
        if deal_id and self.settings.stage_invoiced:
            self._best_effort(request, "crm.deal.update", {
                "id": deal_id, "fields": {"STAGE_ID": self.settings.stage_invoiced},
            })
        warning = self._ensure_document(request, invoice_id)
        if first_time:
            entity_type = "deal" if deal_id else "SI"
            entity_id = deal_id or invoice_id
            self._best_effort(request, "crm.timeline.comment.add", {"fields": {
                "ENTITY_ID": int(entity_id), "ENTITY_TYPE": entity_type, "COMMENT": self._summary(request),
            }})
        task_warning = self._ensure_task(request, invoice_id=invoice_id, company_id=company_id, deal_id=deal_id)
        if task_warning:
            warning = f"{warning}; {task_warning}" if warning else task_warning
        if first_time:
            self._notify(request, invoice_id=invoice_id, task_id=request.crm_task_id)
        return warning

    def cancel(self, request) -> None:
        if request.crm_invoice_id and self.settings.invoice_stage_lost:
            self._best_effort(request, "crm.item.update", {
                "entityTypeId": SMART_INVOICE_ENTITY_TYPE_ID, "id": int(request.crm_invoice_id),
                "fields": {"stageId": self.settings.invoice_stage_lost},
            })
        if request.crm_deal_id:
            fields: Dict[str, Any] = {}
            if self.settings.stage_lost:
                fields["STAGE_ID"] = self.settings.stage_lost
            if fields:
                self._call("crm.deal.update", {"id": request.crm_deal_id, "fields": fields})
            self._best_effort(request, "crm.timeline.comment.add", {"fields": {
                "ENTITY_ID": int(request.crm_deal_id), "ENTITY_TYPE": "deal",
                "COMMENT": f"Заявка {request.invoice_number} отменена: {request.cancel_reason or 'без причины'}"
                           f" ({request.cancelled_by or 'приложение'}).",
            }})
        if request.crm_task_id:
            self._best_effort(request, "task.commentitem.add", {
                "TASKID": int(request.crm_task_id),
                "FIELDS": {"POST_MESSAGE": f"Заявка отменена: {request.cancel_reason or 'без причины'}"
                                           f" ({request.cancelled_by or 'приложение'})."},
            })

    def mark_paid(self, request) -> None:
        if request.crm_invoice_id and self.settings.invoice_stage_paid:
            self._best_effort(request, "crm.item.update", {
                "entityTypeId": SMART_INVOICE_ENTITY_TYPE_ID, "id": int(request.crm_invoice_id),
                "fields": {"stageId": self.settings.invoice_stage_paid},
            })
        until = f" до {request.pro_paid_until:%d.%m.%Y}" if request.pro_paid_until else ""
        if request.crm_deal_id:
            fields: Dict[str, Any] = {}
            if self.settings.stage_paid:
                fields["STAGE_ID"] = self.settings.stage_paid
            code = self.settings.fields.get("paid_until")
            if code and request.pro_paid_until:
                fields[code] = request.pro_paid_until.isoformat()
            if fields:
                self._best_effort(request, "crm.deal.update", {"id": request.crm_deal_id, "fields": fields})
            self._best_effort(request, "crm.timeline.comment.add", {"fields": {
                "ENTITY_ID": int(request.crm_deal_id), "ENTITY_TYPE": "deal",
                "COMMENT": f"Оплата по счёту {request.invoice_number} подтверждена ({request.paid_by}), "
                           f"Pro включён{until}.",
            }})
        if request.crm_task_id:
            self._best_effort(request, "task.commentitem.add", {
                "TASKID": int(request.crm_task_id),
                "FIELDS": {"POST_MESSAGE": f"Оплата отмечена, Pro включён{until}."},
            })
            self._best_effort(request, "tasks.task.complete", {"taskId": int(request.crm_task_id)})
