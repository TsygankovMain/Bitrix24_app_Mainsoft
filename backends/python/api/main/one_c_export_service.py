"""Сервис отправки часов в 1С.

Собирает пакет за период, отдаёт его приёмнику коннектора и сохраняет
построчный результат. Ошибка транспорта здесь не превращается в 500:
1С может быть недоступна, и это нормальное состояние обмена — запись
получает статус «не принято», повтор безопасен (идемпотентность на стороне 1С
построчная, по идентификатору списания).
"""
import json
import logging
import uuid
from datetime import date
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from django.conf import settings

from .inn_backfill_service import build_project_lookup
from .models import OneCExportRun, PortalUser, ProjectCard, TimesheetItem
from .one_c_export import build_batch, parse_response

logger = logging.getLogger(__name__)


class HttpTransport:
    """Транспорт по умолчанию: POST в точку приёма коннектора.

    Токен уходит в строке запроса, а не в заголовке: так же принимает вызовы
    штатный робот Битрикс24, и приёмник коннектора рассчитан именно на это.
    """

    def __init__(self, url: str, token: str, timeout: int = 120):
        self.url = url
        self.token = token
        self.timeout = timeout

    def __call__(self, payload: Dict[str, Any]) -> Any:
        import requests  # локально: без отправки в 1С модуль не нужен

        if not self.url:
            raise RuntimeError(
                "Не задан адрес приёмника 1С (ONE_C_INBOX_URL): отправлять некуда")

        url = self.url
        if self.token:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}token={self.token}"

        response = requests.post(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=self.timeout,
        )
        try:
            return response.json()
        except ValueError:
            return {"ok": False, "сообщение": f"1С ответила не JSON (HTTP {response.status_code})"}


class OneCExportService:
    def __init__(
        self,
        account,
        transport: Optional[Callable[[Dict[str, Any]], Any]] = None,
        inn_maps: Optional[Tuple[Mapping[str, str], Mapping[str, str]]] = None,
        employee_names: Optional[Mapping[str, str]] = None,
        config: Optional[Dict[str, Any]] = None,
        client=None,
    ):
        self.account = account
        self.client = client
        self.config = config or {}
        self._inn_maps = inn_maps
        self._employee_names = employee_names
        self.transport = transport or HttpTransport(
            url=getattr(settings, "ONE_C_INBOX_URL", "") or "",
            token=getattr(settings, "ONE_C_TOKEN", "") or "",
        )

    # --- источники данных ---

    def _items(self, period_from: date, period_to: date):
        return list(
            TimesheetItem.objects.filter(
                bitrix24_account=self.account,
                date_reflection__date__gte=period_from,
                date_reflection__date__lte=period_to,
            ).order_by("date_reflection", "bitrix_id")
        )

    def _projects(self):
        cards = ProjectCard.objects.filter(bitrix24_account=self.account)
        by_item, _ = build_project_lookup(cards)
        return by_item

    def _names(self) -> Mapping[str, str]:
        if self._employee_names is not None:
            return self._employee_names
        names = {}
        for user in PortalUser.objects.filter(bitrix24_account=self.account):
            full = " ".join(p for p in (user.last_name, user.name) if p).strip()
            names[str(user.bitrix_id)] = full
        return names

    def _inn(self) -> Tuple[Mapping[str, str], Mapping[str, str]]:
        """ИНН клиентов и наших юрлиц. Берётся из Битрикса тем же механизмом,
        которым приложение дозаполняет ИНН в карточках списаний."""
        if self._inn_maps is not None:
            return self._inn_maps
        try:
            from .inn_backfill_service import InnBackfillService
            service = InnBackfillService(self.client or self.account.client, self.account, self.config)
            return service._inn_maps()  # noqa: SLF001 — единственная точка резолва ИНН в проекте
        except Exception:
            logger.warning("Не удалось получить ИНН из Битрикса, строки уедут без ИНН",
                           exc_info=True)
            return {}, {}

    # --- отправка ---

    def run(self, period_from: date, period_to: date, started_by: str = "") -> OneCExportRun:
        items = self._items(period_from, period_to)
        companies_inn, legal_inn = self._inn()
        sending_id = uuid.uuid4().hex[:16]

        batch = build_batch(
            items=items,
            projects_by_item=self._projects(),
            companies_inn=companies_inn,
            legal_inn=legal_inn,
            employee_names=self._names(),
            period_from=period_from,
            period_to=period_to,
            sending_id=sending_id,
        )

        run = OneCExportRun(
            bitrix24_account=self.account,
            period_from=period_from,
            period_to=period_to,
            sending_id=sending_id,
            sent_rows=len(batch["строки"]),
            started_by=started_by,
        )

        try:
            answer = self.transport(batch)
        except Exception as error:  # транспорт чужой системы: падать нельзя
            run.status = OneCExportRun.STATUS_FAILED
            run.message = f"1С недоступна: {error}"
            run.save()
            logger.warning("Отправка %s в 1С не доставлена: %s", sending_id, error)
            return run

        parsed = parse_response(answer)
        run.accepted = parsed["accepted"]
        run.rejected = parsed["rejected"]
        run.documents = parsed["documents"]
        run.rows = parsed["rows"]
        run.message = parsed["message"]

        if not parsed["ok"]:
            run.status = OneCExportRun.STATUS_FAILED
        elif parsed["rejected"]:
            run.status = OneCExportRun.STATUS_PARTIAL
        else:
            run.status = OneCExportRun.STATUS_OK

        run.save()
        logger.info("Отправка %s в 1С: %s", sending_id, run.status)
        return run
