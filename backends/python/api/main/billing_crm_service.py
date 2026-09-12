"""Канал CRM: смарт-счёт (entityTypeId 31), товарные строки и печать акта.

Здесь и только здесь приложение разговаривает с порталом про счёт. Правило,
которое определяет весь модуль: **ответам REST Битрикс24 верить нельзя**.
Успешный ответ на crm.item.add не доказывает, что счёт создан с теми
суммами, которые мы отправили, а ошибка не доказывает, что он не создан.
Поэтому после записи счёт и его строки ПЕРЕЧИТЫВАЮТСЯ и суммы сверяются, а
расхождение — отказ выставления с понятным текстом, не «вроде получилось».

Про акт. Печать акта по смарт-счёту генератором документов портала живьём
НЕ проверялась (эксперимент на nfr-mainsoft не состоялся, доступа на запись
нет). Поэтому весь путь акта построен так, чтобы отсутствие метода, scope,
шаблона или самого модуля давало понятный код ошибки в act_error, а не 500:

- ``documentgenerator_unavailable`` — портал не отвечает методом
  crm.documentgenerator.* (нет модуля, нет прав, метод не найден);
- ``act_template_missing`` — метод есть, подходящего шаблона акта нет;
- ``act_generation_failed`` — шаблон есть, документ не собрался.

Свой шаблон (crm.documentgenerator.template.add) предусмотрен, но НЕ
обязателен: он создаётся только по явному указанию — параметром запроса или
настройкой с DOCX в base64.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from django.utils import timezone

from .billing_service import BillingError, BillingService, clean_str as _clean, money as _money, num as _num
from .models import BillingDocument

logger = logging.getLogger(__name__)
audit = logging.getLogger("main.audit")

# Смарт-счёт: тип сущности CRM и его код владельца товарных строк.
INVOICE_ENTITY_TYPE_ID = 31
INVOICE_OWNER_TYPE = "SI"

# Единица измерения товарной строки — час, код ОКЕИ 356. Не проверено на
# живом портале: если портал код не примет, строка уйдёт без единицы
# измерения (crm.item.productrow.set не требует measureCode), количество и
# сумма от этого не меняются.
MEASURE_CODE_HOUR = 356

# Допуск сверки сумм. Итог документа — сумма округлённых до копейки строк,
# поэтому побайтового равенства с opportunity счёта ждать нельзя: копейка на
# строку накапливается. Копейка на строку и берётся допуском, но не меньше
# рубля — иначе документ из тысячи строк не сверился бы никогда.
AMOUNT_TOLERANCE_PER_LINE = 0.01
AMOUNT_TOLERANCE_MIN = 1.0


def _first_dict(*candidates: Any) -> Dict[str, Any]:
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return {}


def _to_int(value: Any) -> Optional[int]:
    text = _clean(value)
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _extract_item(response: Any) -> Dict[str, Any]:
    """Элемент из ответа crm.item.* — разбор устойчив к форме ответа.

    Битрикс отдаёт то {"result": {"item": {...}}}, то {"result": {...}}.
    Неразобранный ответ возвращается пустым словарём: вызывающий код
    трактует это как «сверить не удалось», а не как успех.
    """
    if not isinstance(response, dict):
        return {}
    result = response.get("result")
    if not isinstance(result, dict):
        return {}
    item = result.get("item")
    if isinstance(item, dict):
        return item
    return result


def _extract_product_rows(response: Any) -> Tuple[List[Dict[str, Any]], bool]:
    """(строки, разобрано ли). Пустой список при parsed_ok=True — честный ноль."""
    if not isinstance(response, dict):
        return [], False
    result = response.get("result")
    if isinstance(result, list):
        rows = result
    elif isinstance(result, dict):
        rows = result.get("productRows")
        if rows is None:
            rows = result.get("productrows")
        if rows is None:
            rows = result.get("items")
    else:
        return [], False
    if rows is None or not isinstance(rows, list):
        return [], False
    valid = [row for row in rows if isinstance(row, dict)]
    if len(valid) != len(rows):
        return [], False
    return valid, True


def _extract_created_id(response: Any) -> Optional[int]:
    """id созданной записи из ответа *.add — форма ответа у Битрикса разная.

    {"result": 77}, {"result": {"id": 77}}, {"result": {"item": {"id": 77}}},
    {"result": {"template": {"id": 77}}} — всё это встречается у разных
    методов. None означает «идентификатора в ответе нет», и вызывающий код
    превращает это в отказ, а не в молчаливый успех.
    """
    if not isinstance(response, dict):
        return None
    result = response.get("result")
    if isinstance(result, (int, str)):
        return _to_int(result)
    if not isinstance(result, dict):
        return None
    if "id" in result:
        return _to_int(result["id"])
    for value in result.values():
        if isinstance(value, dict) and "id" in value:
            return _to_int(value["id"])
    return None


def _is_method_unavailable(exc: Exception) -> bool:
    """Отличает «метода/модуля нет» от «метод есть, но вызов не удался».

    Разбор по тексту, а не по типу: b24pysdk поднимает одну и ту же
    BitrixAPIError и на отсутствующий метод, и на прикладную ошибку, а нам
    нужно развести «портал не умеет печатать акты» (пусть настройщик знает,
    что дело в портале) от «шаблон не тот».
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    markers = (
        "method not found",
        "error_method_not_found",
        "method_not_found",
        "insufficient scope",
        "invalid_scope",
        "access denied",
        "документооборот",
        "documentgenerator is not installed",
        "module not installed",
    )
    return any(marker in text for marker in markers)


class BillingCrmService:
    """Обёртка REST-вызовов счёта. Держит и сверку, и печать акта."""

    def __init__(self, account, client: Any = None, service: Optional[BillingService] = None):
        self.account = account
        self._client = client
        self.service = service or BillingService(account, client)

    @property
    def client(self):
        if self._client is None:
            self._client = self.account.client
        return self._client

    def _call(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return self.client._bitrix_token.call_method(method, params)

    # ------------------------------------------------------------------
    # Счёт
    # ------------------------------------------------------------------

    def build_invoice_fields(self, document: BillingDocument) -> Dict[str, Any]:
        period = ""
        if document.period_from and document.period_to:
            period = f"{document.period_from.strftime('%d.%m.%Y')}—{document.period_to.strftime('%d.%m.%Y')}"
        title = f"Услуги за {period}" if period else "Услуги по договору"
        if document.company_name:
            title = f"{title} ({document.company_name})"

        fields: Dict[str, Any] = {
            "title": title[:255],
            "currencyId": document.currency or "RUB",
            # opportunity + isManualOpportunity: сумму считает приложение, а
            # не портал по строкам. Иначе портал пересчитал бы её по своим
            # правилам НДС и итог разошёлся бы с детализацией акта.
            "opportunity": _money(document.total_amount),
            "isManualOpportunity": "Y",
            "begindate": timezone.localdate().isoformat(),
        }
        company_id = _to_int(document.company_id)
        if company_id:
            fields["companyId"] = company_id
        our_company_id = _to_int(document.our_company_id)
        if our_company_id:
            fields["mycompanyId"] = our_company_id
        if document.period_to:
            fields["closedate"] = document.period_to.isoformat()
        fields["comments"] = (
            f"Счёт по трудозатратам: {document.total_hours} ч. "
            f"Документ приложения «Учёт трудозатрат» {document.pk}."
        )
        return fields

    def build_product_rows(self, document: BillingDocument) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        vat_included = document.vat_mode == BillingDocument.VAT_INCLUDED
        for line in document.lines.all():
            row: Dict[str, Any] = {
                "productName": (line.title or line.project_name or "Услуги")[:255],
                "price": _money(line.rate),
                "quantity": round(_num(line.hours), 2),
                "measureCode": MEASURE_CODE_HOUR,
            }
            if vat_included and _num(document.vat_rate) > 0:
                row["taxRate"] = _num(document.vat_rate)
                row["taxIncluded"] = "Y"
            else:
                row["taxRate"] = None
                row["taxIncluded"] = "N"
            rows.append(row)
        return rows

    def create_invoice(self, document: BillingDocument) -> str:
        try:
            response = self._call(
                "crm.item.add",
                {
                    "entityTypeId": INVOICE_ENTITY_TYPE_ID,
                    "fields": self.build_invoice_fields(document),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("create_invoice: crm.item.add упал: %s", exc)
            raise BillingError(
                f"Не удалось создать счёт в CRM: {exc}", "crm_invoice_failed", status=502
            ) from exc

        invoice_id = _extract_created_id(response)
        if not invoice_id:
            raise BillingError(
                "Битрикс не вернул идентификатор созданного счёта.",
                "crm_invoice_failed",
                status=502,
            )
        return str(invoice_id)

    def set_product_rows(self, document: BillingDocument, invoice_id: str) -> None:
        rows = self.build_product_rows(document)
        if not rows:
            return
        try:
            self._call(
                "crm.item.productrow.set",
                {
                    "ownerType": INVOICE_OWNER_TYPE,
                    "ownerId": _to_int(invoice_id),
                    "productRows": rows,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("set_product_rows: crm.item.productrow.set упал: %s", exc)
            raise BillingError(
                f"Счёт создан, но строки не записались: {exc}",
                "crm_productrows_failed",
                status=502,
            ) from exc

    def verify_invoice(self, document: BillingDocument, invoice_id: str) -> Dict[str, Any]:
        """Перечитывание счёта и сверка сумм. Возвращает данные счёта.

        Сверяются ДВЕ вещи: итог самого счёта (opportunity) и сумма его
        товарных строк. Сверять только одну бессмысленно: строки могли
        записаться мимо, а итог — остаться нашим (isManualOpportunity), и
        наоборот.
        """
        try:
            response = self._call(
                "crm.item.get",
                {"entityTypeId": INVOICE_ENTITY_TYPE_ID, "id": _to_int(invoice_id)},
            )
        except Exception as exc:  # noqa: BLE001
            raise BillingError(
                f"Счёт создан, но перечитать его не удалось: {exc}",
                "crm_verify_failed",
                status=502,
            ) from exc

        item = _extract_item(response)
        if not item:
            raise BillingError(
                "Счёт создан, но Битрикс вернул его в неожиданном виде — сверить суммы нельзя.",
                "crm_verify_failed",
                status=502,
            )

        expected = _money(document.total_amount)
        tolerance = max(AMOUNT_TOLERANCE_MIN, AMOUNT_TOLERANCE_PER_LINE * max(1, document.lines.count()))

        actual = _num(item.get("opportunity"))
        if abs(actual - expected) > tolerance:
            raise BillingError(
                f"Суммы не сошлись: приложение посчитало {expected}, в счёте {actual}. "
                "Счёт остался в CRM, документ не выставлен — проверьте счёт вручную.",
                "crm_amount_mismatch",
                status=502,
                extra={"expected": expected, "actual": actual, "crm_entity_id": str(invoice_id)},
            )

        try:
            rows_response = self._call(
                "crm.item.productrow.list",
                {"filter": {"=ownerType": INVOICE_OWNER_TYPE, "=ownerId": _to_int(invoice_id)}},
            )
        except Exception as exc:  # noqa: BLE001
            raise BillingError(
                f"Счёт создан, но перечитать его строки не удалось: {exc}",
                "crm_verify_failed",
                status=502,
            ) from exc

        rows, parsed_ok = _extract_product_rows(rows_response)
        if not parsed_ok:
            raise BillingError(
                "Счёт создан, но строки вернулись в неожиданном виде — сверить суммы нельзя.",
                "crm_verify_failed",
                status=502,
            )

        rows_total = _money(sum(_num(row.get("price")) * _num(row.get("quantity")) for row in rows))
        if abs(rows_total - expected) > tolerance:
            raise BillingError(
                f"Строки счёта не сошлись с документом: в приложении {expected}, в счёте {rows_total}. "
                "Счёт остался в CRM, документ не выставлен — проверьте счёт вручную.",
                "crm_amount_mismatch",
                status=502,
                extra={"expected": expected, "actual": rows_total, "crm_entity_id": str(invoice_id)},
            )

        return item

    def issue(self, document: BillingDocument) -> BillingDocument:
        """Счёт в CRM для уже записанного документа.

        Документ к этому моменту создан (см. докстринг billing_service, п. 3):
        конфликт частичного индекса обязан всплыть раньше, чем на портале
        появится счёт, который мы не сможем удалить.
        """
        invoice_id = self.create_invoice(document)
        document.crm_entity_id = str(invoice_id)
        document.save(update_fields=["crm_entity_id", "updated_at"])

        self.set_product_rows(document, invoice_id)
        item = self.verify_invoice(document, invoice_id)

        document.crm_account_number = _clean(
            item.get("accountNumber") or item.get("ACCOUNT_NUMBER") or item.get("number")
        )[:100]
        document.save(update_fields=["crm_account_number", "updated_at"])

        audit.info(
            "Billing invoice created in CRM: document=%s, invoice=%s, number=%s, amount=%s",
            document.pk, invoice_id, document.crm_account_number, document.total_amount,
        )
        return document

    # ------------------------------------------------------------------
    # Акт
    # ------------------------------------------------------------------

    def list_templates(self) -> List[Dict[str, Any]]:
        """Шаблоны генератора документов, пригодные для смарт-счёта.

        Фильтр по entityTypeId передаётся, но результат ещё и просеивается
        локально: на каких порталах фильтр работает, а на каких отдаёт всё
        подряд, не проверено, а подобрать шаблон чужой сущности хуже, чем не
        найти никакого.
        """
        try:
            response = self._call(
                "crm.documentgenerator.template.list",
                {"filter": {"entityTypeId": INVOICE_ENTITY_TYPE_ID}},
            )
        except Exception as exc:  # noqa: BLE001
            if _is_method_unavailable(exc):
                raise BillingError(
                    "Портал не отдаёт шаблоны генератора документов (crm.documentgenerator): "
                    f"модуль недоступен или у приложения нет прав ({exc}).",
                    "documentgenerator_unavailable",
                    status=502,
                ) from exc
            raise BillingError(
                f"Не удалось получить список шаблонов генератора документов: {exc}",
                "documentgenerator_unavailable",
                status=502,
            ) from exc

        result = response.get("result") if isinstance(response, dict) else None
        raw: List[Any]
        if isinstance(result, dict):
            raw = result.get("templates") or result.get("items") or []
        elif isinstance(result, list):
            raw = result
        else:
            raw = []

        templates: List[Dict[str, Any]] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            entity_types = row.get("entityTypeId") or row.get("ENTITY_TYPE_ID")
            if isinstance(entity_types, (list, tuple)):
                codes = {_clean(value) for value in entity_types}
            else:
                codes = {_clean(entity_types)} if entity_types not in (None, "") else set()
            if codes and not any(
                code == str(INVOICE_ENTITY_TYPE_ID) or code.startswith(f"{INVOICE_ENTITY_TYPE_ID}_")
                for code in codes
            ):
                continue
            templates.append({
                "id": _to_int(row.get("id") or row.get("ID")),
                "name": _clean(row.get("name") or row.get("NAME")),
            })
        return [row for row in templates if row["id"]]

    def resolve_act_template_id(self, *, preferred_id: int = 0) -> int:
        """Шаблон акта: сначала выбранный в настройках, затем — по названию.

        По названию, потому что по REST шаблон не помечен «это акт»:
        различить счёт и акт можно только текстом имени. Поэтому явный выбор
        в настройках (billing_act_template_id) всегда в приоритете, а
        угадывание — запасной путь.
        """
        if preferred_id:
            return int(preferred_id)
        templates = self.list_templates()
        if not templates:
            raise BillingError(
                "На портале нет шаблонов генератора документов для счёта — "
                "добавьте шаблон акта в CRM или укажите его в настройках приложения.",
                "act_template_missing",
            )
        for row in templates:
            if "акт" in row["name"].lower() or "act" in row["name"].lower():
                return int(row["id"])
        raise BillingError(
            "Среди шаблонов генератора документов не нашлось акта. "
            "Укажите шаблон вручную в настройках приложения.",
            "act_template_missing",
            extra={"templates": templates},
        )

    def create_act_template(self, name: str, docx_base64: str, *, numerator_id: int = 0) -> int:
        """Свой шаблон акта из DOCX в base64.

        Путь предусмотрен контрактом, но НЕ обязателен для первой версии:
        вызывается только когда DOCX передан явно. Сам файл приложение не
        придумывает — его даёт настройщик.
        """
        payload: Dict[str, Any] = {
            "fields": {
                "name": name[:255],
                "entityTypeId": [str(INVOICE_ENTITY_TYPE_ID)],
                "file": docx_base64,
                "region": "ru",
                "active": "Y",
            }
        }
        if numerator_id:
            payload["fields"]["numeratorId"] = int(numerator_id)
        try:
            response = self._call("crm.documentgenerator.template.add", payload)
        except Exception as exc:  # noqa: BLE001
            code = "documentgenerator_unavailable" if _is_method_unavailable(exc) else "act_template_failed"
            raise BillingError(
                f"Не удалось создать шаблон акта: {exc}", code, status=502
            ) from exc
        template_id = _extract_created_id(response)
        if not template_id:
            raise BillingError(
                "Битрикс не вернул идентификатор созданного шаблона акта.",
                "act_template_failed",
                status=502,
            )
        return template_id

    def print_act(
        self,
        document: BillingDocument,
        *,
        template_id: int = 0,
        template_docx_base64: str = "",
    ) -> Dict[str, Any]:
        """Печать акта по счёту. Любой отказ — код, а не 500.

        Номер и дата акта равны номеру и дате счёта (контракт, п. 6): они
        уходят в шаблон через values. Имена полей шаблона порталом не
        стандартизованы, поэтому передаются несколько привычных написаний —
        лишние генератор игнорирует.
        """
        if not document.is_issued:
            raise BillingError("Акт печатается только по действующему счёту.", "document_cancelled", status=409)
        if not document.crm_entity_id:
            raise BillingError(
                "У документа нет счёта в CRM — печатать акт не по чему.",
                "crm_invoice_missing",
            )

        if not template_id and template_docx_base64:
            template_id = self.create_act_template(
                f"Акт (Учёт трудозатрат) {document.our_company_name}".strip(),
                template_docx_base64,
            )
        if not template_id:
            template_id = self.resolve_act_template_id(
                preferred_id=int(self.service.settings.get("act_template_id") or 0)
            )

        number = document.crm_account_number or ""
        issued_on = timezone.localdate().strftime("%d.%m.%Y")
        values = {
            "DocumentNumber": number,
            "DocumentDate": issued_on,
            "ActNumber": number,
            "ActDate": issued_on,
            "TotalHours": document.total_hours,
        }

        try:
            response = self._call(
                "crm.documentgenerator.document.add",
                {
                    "templateId": int(template_id),
                    "entityTypeId": INVOICE_ENTITY_TYPE_ID,
                    "entityId": _to_int(document.crm_entity_id),
                    "values": values,
                },
            )
        except Exception as exc:  # noqa: BLE001
            code = "documentgenerator_unavailable" if _is_method_unavailable(exc) else "act_generation_failed"
            raise BillingError(
                f"Не удалось напечатать акт: {exc}", code, status=502
            ) from exc

        item = _first_dict(
            (response.get("result") or {}).get("document") if isinstance(response, dict) else None,
            _extract_item(response),
        )
        act_id = _to_int(item.get("id"))
        if not act_id:
            raise BillingError(
                "Генератор документов не вернул идентификатор акта.",
                "act_generation_failed",
                status=502,
            )

        # Номер акта: свой номер документа генератора, если он есть, иначе —
        # номер счёта (контракт: номер акта равен номеру счёта).
        document.act_document_id = str(act_id)
        document.act_number = _clean(item.get("number") or number)[:100]
        document.act_download_url = _clean(item.get("downloadUrl"))
        document.act_public_url = _clean(item.get("publicUrl"))
        # pdfUrl собирается асинхронно и в первом ответе обычно пуст —
        # это не ошибка, ссылка появится при повторном чтении документа.
        document.act_pdf_url = _clean(item.get("pdfUrl"))
        document.act_error = ""
        document.save(update_fields=[
            "act_document_id", "act_number", "act_download_url", "act_public_url",
            "act_pdf_url", "act_error", "updated_at",
        ])

        audit.info(
            "Billing act printed: document=%s, act=%s, number=%s",
            document.pk, act_id, document.act_number,
        )
        return {
            "act_document_id": document.act_document_id,
            "act_number": document.act_number,
            "act_download_url": document.act_download_url,
            "act_public_url": document.act_public_url,
            "act_pdf_url": document.act_pdf_url,
        }
