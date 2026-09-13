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
- ``act_generation_failed`` — шаблон есть, документ не собрался;
- ``billing_template_not_found`` — выбранного в настройках шаблона на портале
  больше нет (его удалили);
- ``invoice_template_missing`` — шаблон печатной формы счёта не выбран;
- ``invoice_generation_failed`` — печатная форма счёта не собралась.

Что портал реально отдаёт в списке шаблонов — проверено на nfr-mainsoft
12.09.2026 и описано в докстринге list_templates: словарь по id, без поля
entityTypeId, а фильтр по entityTypeId обнуляет выборку.

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


def _is_template_missing(exc: Exception) -> bool:
    """«Шаблон не найден» — ответ портала на удалённый или чужой id.

    Проверено живьём: crm.documentgenerator.template.get на несуществующий id
    отвечает {"error": "0", "error_description": "Шаблон не найден"} — код
    ошибки "0", то есть по коду отличить нельзя, только по тексту.
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(
        marker in text
        for marker in ("шаблон не найден", "template not found", "not_found_template")
    )


def _matches_invoice_entity(row: Dict[str, Any]) -> bool:
    """Привязан ли шаблон к смарт-счёту — когда портал вообще это сказал.

    Формат привязки у портала — строки "<entityTypeId>_<categoryId>"
    ("31_2"), поэтому сравнение идёт и на точное равенство, и на префикс.
    Отсутствие поля (а в ответе template.list его нет вовсе) читается как
    «портал не сказал» и шаблон НЕ отбрасывается: пустой список шаблонов на
    портале, где они есть, хуже лишней строки в выпадающем списке.
    """
    entity_types = row.get("entityTypeId") or row.get("ENTITY_TYPE_ID")
    if isinstance(entity_types, dict):
        entity_types = list(entity_types.values())
    if isinstance(entity_types, (list, tuple, set)):
        codes = {_clean(value) for value in entity_types}
    else:
        codes = {_clean(entity_types)} if entity_types not in (None, "") else set()
    codes.discard("")
    if not codes:
        return True
    return any(
        code == str(INVOICE_ENTITY_TYPE_ID) or code.startswith(f"{INVOICE_ENTITY_TYPE_ID}_")
        for code in codes
    )


def _serialize_template(row: Dict[str, Any]) -> Dict[str, Any]:
    """Шаблон в вид, который уходит и в интерфейс, и в подбор по названию.

    Поля взяты из живого ответа портала (nfr-mainsoft, 12.09.2026). Флаги
    приходят строками "Y"/"N" — наружу отдаются булевыми: строка "N" в
    JavaScript истинна, и признак «по умолчанию» показал бы галочку у всех.

    isDefault портала — НЕ «шаблон по умолчанию для счёта»: на стенде он
    стоит у 17 шаблонов из 21 (это признак штатного шаблона своего вида,
    ACT_RU и INVOICE_RU одновременно «по умолчанию»). Поэтому наружу он
    уходит как справочный признак, а выбор шаблона по нему не делается.
    """
    return {
        "id": _to_int(row.get("id") or row.get("ID")),
        "name": _clean(row.get("name") or row.get("NAME")),
        "code": _clean(row.get("code") or row.get("CODE")),
        "region": _clean(row.get("region") or row.get("REGION")),
        "active": _clean(row.get("active") or row.get("ACTIVE")).upper() != "N",
        "is_default": _clean(row.get("isDefault") or row.get("IS_DEFAULT")).upper() == "Y",
        "numerator_id": _to_int(row.get("numeratorId") or row.get("NUMERATOR_ID")) or 0,
        "products_table_variant": _clean(row.get("productsTableVariant")),
    }


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
        """Шаблоны генератора документов портала.

        Фильтр по entityTypeId НЕ передаётся, и это проверено живьём на
        nfr-mainsoft 12.09.2026: ``filter: {entityTypeId: 31}`` отдаёт
        ``{"templates": []}`` и ``total: 0`` — как и любое другое значение
        (31, "31", [31], 2). Без фильтра тот же портал отдаёт 21 шаблон,
        включая штатный «Акт (Россия)» (id 2, код ACT_RU) и «Счет (Россия)»
        (id 4, код BILL_RU), оба привязанные к смарт-счёту. То есть фильтр не
        сужал выборку, а обнулял её: печать акта падала с «шаблонов нет» при
        живом штатном шаблоне.

        Привязки к сущности в ответе list ТОЖЕ нет — поля entityTypeId там
        просто не существует (union полей: active, code, createTime,
        createdBy, download, downloadMachine, id, isDefault, isDeleted,
        moduleId, name, numeratorId, productsTableVariant, region, sort,
        updateTime, updatedBy, withStamps). Привязку отдаёт только
        template.get, списком строк вида ["2_category_0", "31_2"] — см.
        get_template. Поэтому локальное просеивание оставлено, но работает
        только когда портал всё-таки прислал entityTypeId: отбрасывать
        шаблоны за отсутствие поля значило бы вернуть пустой список на
        портале, где шаблоны есть.

        Удалённые шаблоны (isDeleted = Y) отбрасываются всегда: выбрать
        удалённый шаблон в настройках — это отложенная ошибка печати.
        """
        try:
            response = self._call("crm.documentgenerator.template.list", {})
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
            container = result.get("templates") or result.get("items") or []
            # Портал отдаёт шаблоны СЛОВАРЁМ по id: {"2": {...}}. Перебор dict
            # даёт строковые ключи, они не проходят isinstance(row, dict) ниже,
            # и все шаблоны молча отбрасывались — печать акта падала с
            # «шаблонов нет» при живом штатном «Акт (Россия)» (id 2).
            raw = list(container.values()) if isinstance(container, dict) else container
        elif isinstance(result, list):
            raw = result
        else:
            raw = []

        templates: List[Dict[str, Any]] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            if _clean(row.get("isDeleted") or row.get("IS_DELETED")).upper() == "Y":
                continue
            if not _matches_invoice_entity(row):
                continue
            templates.append(_serialize_template(row))
        return [row for row in templates if row["id"]]

    def get_template(self, template_id: int) -> Dict[str, Any]:
        """Один шаблон по id — этим проверяется, что выбранный ещё жив.

        Метод list для проверки не годится: он не отдаёт entityTypeId и на
        большом портале это лишняя страница данных ради одного id. А главное
        — template.get честно отвечает «Шаблон не найден» на удалённый
        шаблон, и это единственный способ отличить «настройка устарела» от
        «портал недоступен».

        Проверено живьём (nfr-mainsoft, 12.09.2026): ответ приходит как
        {"result": {"template": {...}}} и, в отличие от list, содержит
        entityTypeId — список строк ["2_category_0", "16documentrealization",
        "31_2"], где "31_2" и есть привязка к смарт-счёту (31) в воронке 2.
        На несуществующий id портал отвечает
        {"error": "0", "error_description": "Шаблон не найден"}.
        """
        template_id = int(template_id or 0)
        if not template_id:
            raise BillingError("Шаблон не выбран.", "billing_template_not_found")
        try:
            response = self._call(
                "crm.documentgenerator.template.get", {"id": template_id}
            )
        except Exception as exc:  # noqa: BLE001
            if _is_template_missing(exc):
                raise BillingError(
                    f"Шаблон {template_id} на портале не найден — его удалили или он "
                    "принадлежал другому порталу. Выберите шаблон заново.",
                    "billing_template_not_found",
                ) from exc
            if _is_method_unavailable(exc):
                raise BillingError(
                    "Портал не отдаёт шаблоны генератора документов "
                    f"(crm.documentgenerator): модуль недоступен или у приложения нет прав ({exc}).",
                    "documentgenerator_unavailable",
                    status=502,
                ) from exc
            raise BillingError(
                f"Не удалось проверить шаблон {template_id} на портале: {exc}",
                "documentgenerator_unavailable",
                status=502,
            ) from exc

        result = response.get("result") if isinstance(response, dict) else None
        row = _first_dict(
            result.get("template") if isinstance(result, dict) else None,
            result if isinstance(result, dict) else None,
        )
        if not row or not _to_int(row.get("id") or row.get("ID")):
            raise BillingError(
                f"Шаблон {template_id} на портале не найден — выберите шаблон заново.",
                "billing_template_not_found",
            )
        return _serialize_template(row)

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

        printed = self._generate_document(
            document, template_id=template_id, values=values,
            subject="акт", fail_code="act_generation_failed",
        )

        # Номер акта: свой номер документа генератора, если он есть, иначе —
        # номер счёта (контракт: номер акта равен номеру счёта).
        document.act_document_id = printed["id"]
        document.act_number = (printed["number"] or number)[:100]
        document.act_download_url = printed["download_url"]
        document.act_public_url = printed["public_url"]
        # pdfUrl собирается асинхронно и в первом ответе обычно пуст —
        # это не ошибка, ссылка появится при повторном чтении документа.
        document.act_pdf_url = printed["pdf_url"]
        document.act_error = ""
        document.save(update_fields=[
            "act_document_id", "act_number", "act_download_url", "act_public_url",
            "act_pdf_url", "act_error", "updated_at",
        ])

        audit.info(
            "Billing act printed: document=%s, act=%s, number=%s",
            document.pk, document.act_document_id, document.act_number,
        )
        return {
            "act_document_id": document.act_document_id,
            "act_number": document.act_number,
            "act_download_url": document.act_download_url,
            "act_public_url": document.act_public_url,
            "act_pdf_url": document.act_pdf_url,
        }

    # ------------------------------------------------------------------
    # Печатная форма счёта
    # ------------------------------------------------------------------

    def _generate_document(
        self,
        document: BillingDocument,
        *,
        template_id: int,
        values: Dict[str, Any],
        subject: str,
        fail_code: str,
    ) -> Dict[str, Any]:
        """Один вызов генератора документов и разбор его ответа.

        Общий и для акта, и для печатной формы счёта: различаются они только
        шаблоном, подстановками и кодом отказа. Разбор ответа проверен живьём
        (nfr-mainsoft, 12.09.2026): портал отвечает
        {"result": {"document": {...}}}, в ответе есть id, number, title,
        downloadUrl, а publicUrl и pdfUrl в первом ответе приходят null —
        PDF собирается асинхронно, и пустая ссылка тут не ошибка.
        """
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
            code = "documentgenerator_unavailable" if _is_method_unavailable(exc) else fail_code
            raise BillingError(
                f"Не удалось напечатать {subject}: {exc}", code, status=502
            ) from exc

        item = _first_dict(
            (response.get("result") or {}).get("document") if isinstance(response, dict) else None,
            _extract_item(response),
        )
        printed_id = _to_int(item.get("id"))
        if not printed_id:
            raise BillingError(
                f"Генератор документов не вернул идентификатор документа ({subject}).",
                fail_code,
                status=502,
            )
        return {
            "id": str(printed_id),
            "number": _clean(item.get("number")),
            "download_url": _clean(item.get("downloadUrl")),
            "public_url": _clean(item.get("publicUrl")),
            "pdf_url": _clean(item.get("pdfUrl")),
        }

    def print_invoice_document(self, document: BillingDocument, *, template_id: int = 0) -> Dict[str, Any]:
        """Печатная форма самого счёта по шаблону из настроек.

        Зачем это приложению, если счёт и так лежит в CRM и печатается
        кнопкой карточки: бухгалтер отправляет клиенту пару «счёт + акт», а
        собирает документ в приложении. Ходить за одной из двух половин на
        портал — лишний переход, на котором теряется связь «вот этот счёт
        приложения и вот этот файл».

        Шаблон ЗДЕСЬ не угадывается по названию, в отличие от акта. Угадывать
        было бы опасно: под «счёт» на портале подходят и «Счет (Россия)», и
        «Счет-фактура (Россия)», и «Универсальный передаточный документ» —
        последние два клиенту вместо счёта отправлять нельзя. Нет настройки —
        честный отказ с кодом invoice_template_missing.
        """
        if not document.is_issued:
            raise BillingError(
                "Печатная форма счёта делается только по действующему счёту.",
                "document_cancelled",
                status=409,
            )
        if not document.crm_entity_id:
            raise BillingError(
                "У документа нет счёта в CRM — печатать нечего.",
                "crm_invoice_missing",
            )

        template_id = int(template_id or 0) or int(self.service.settings.get("invoice_template_id") or 0)
        if not template_id:
            raise BillingError(
                "Шаблон счёта не выбран в настройках приложения. Выберите шаблон печатной "
                "формы счёта в настройках «Счёта и акта» — угадывать его приложение не будет: "
                "под «счёт» на портале подходят и счёт-фактура, и УПД.",
                "invoice_template_missing",
            )

        number = document.crm_account_number or ""
        issued_on = timezone.localdate().strftime("%d.%m.%Y")
        printed = self._generate_document(
            document,
            template_id=template_id,
            # Те же подстановки, что у акта: номер и дата печатной формы
            # обязаны совпадать с номером счёта, иначе у клиента окажется
            # счёт с одним номером и акт с другим.
            values={
                "DocumentNumber": number,
                "DocumentDate": issued_on,
                "TotalHours": document.total_hours,
            },
            subject="счёт",
            fail_code="invoice_generation_failed",
        )

        document.invoice_document_id = printed["id"]
        document.invoice_document_number = (printed["number"] or number)[:100]
        document.invoice_download_url = printed["download_url"]
        document.invoice_public_url = printed["public_url"]
        document.invoice_pdf_url = printed["pdf_url"]
        document.invoice_print_error = ""
        document.save(update_fields=[
            "invoice_document_id", "invoice_document_number", "invoice_download_url",
            "invoice_public_url", "invoice_pdf_url", "invoice_print_error", "updated_at",
        ])

        audit.info(
            "Billing invoice form printed: document=%s, printed=%s, number=%s",
            document.pk, printed["id"], document.invoice_document_number,
        )
        return {
            "invoice_document_id": document.invoice_document_id,
            "invoice_document_number": document.invoice_document_number,
            "invoice_download_url": document.invoice_download_url,
            "invoice_public_url": document.invoice_public_url,
            "invoice_pdf_url": document.invoice_pdf_url,
        }
