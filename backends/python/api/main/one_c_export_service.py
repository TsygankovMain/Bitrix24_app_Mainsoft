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

    def __init__(self, url: str, token: str, timeout: int = 120,
                 user: str = "", password: str = ""):
        self.url = url
        self.token = token
        self.timeout = timeout
        # Публикация 1С закрыта basic-авторизацией пользователя информационной
        # базы: без неё веб-сервер отдаёт 401 ещё до того, как запрос дойдёт
        # до точки приёма.
        self.user = user
        self.password = password

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
            auth=(self.user, self.password) if self.user else None,
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
        self.transport = transport or HttpTransport(**self._connection())

    def _connection(self) -> Dict[str, str]:
        """Реквизиты приёмника: сначала настройки портала, потом окружение.

        Настройки портала важнее: адрес 1С у каждого клиента свой, и менять
        его должен администратор на экране настроек, а не мы в .env на сервере.
        Переменные окружения остаются запасным путём для стенда.
        """
        one_c = (self.config or {}).get("one_c") or {}

        def value(key: str, env_name: str) -> str:
            return str(one_c.get(key) or getattr(settings, env_name, "") or "").strip()

        return {
            "url": value("inbox_url", "ONE_C_INBOX_URL"),
            "token": value("token", "ONE_C_TOKEN"),
            "user": value("user", "ONE_C_USER"),
            "password": value("password", "ONE_C_PASSWORD"),
        }

    # --- источники данных ---

    def _items(self, period_from: date, period_to: date):
        return list(
            TimesheetItem.objects.filter(
                bitrix24_account=self.account,
                date_reflection__date__gte=period_from,
                date_reflection__date__lte=period_to,
            ).order_by("date_reflection", "bitrix_id")
        )

    def _project_cards(self):
        return list(ProjectCard.objects.filter(bitrix24_account=self.account))

    def _projects(self, cards):
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

    def _inn(self, cards) -> Tuple[Mapping[str, str], Mapping[str, str]]:
        """ИНН клиентов и наших юрлиц — по компаниям, которые реально встретились
        в проектах периода.

        Берём _inn_maps_for_cards, а не _inn_maps: первый читает реквизиты
        адресно (crm.requisite.list по нужным id), второй строит карту из
        полного обхода справочника компаний, где ИНН попросту нет — на стенде
        это давало пустые ИНН во всех 796 строках пакета.
        """
        if self._inn_maps is not None:
            return self._inn_maps
        try:
            from .inn_backfill_service import InnBackfillService
            service = InnBackfillService(self.client or self.account.client, self.account, self.config)
            return service._inn_maps_for_cards(list(cards))  # noqa: SLF001
        except Exception:
            logger.warning("Не удалось получить ИНН из Битрикса, строки уедут без ИНН",
                           exc_info=True)
            return {}, {}

    # --- отправка ---

    def _company_titles(self, cards) -> Dict[str, str]:
        """Имена компаний из CRM для карточек, где вместо имени стоит id.

        Имя уезжает в 1С рядом с ИНН: по нему приёмник находит клиента, когда
        реквизиты в CRM не заполнены, и им же называет заведённого контрагента.
        Без CRM здесь пусто — отправка от этого не падает, просто теряет
        запасной ключ сопоставления.
        """
        if not self.client:
            return {}

        titles: Dict[str, str] = {}
        try:
            from .project_board_service import ProjectCardService
            board = ProjectCardService(self.client, self.account)
            for card in cards:
                company_id = str(getattr(card, "company_id", "") or "").strip()
                stored = str(getattr(card, "company_name", "") or "").strip()
                if not company_id or company_id in titles:
                    continue
                if stored and stored != company_id:
                    titles[company_id] = stored
                    continue
                titles[company_id] = str(
                    board._fetch_single_reference_name(company_id) or "").strip()
        except Exception:  # noqa: BLE001
            logger.warning("Имена компаний из Битрикса не получены", exc_info=True)

        return {k: v for k, v in titles.items() if v}

    def run(self, period_from: date, period_to: date, started_by: str = "") -> OneCExportRun:
        items = self._items(period_from, period_to)
        cards = self._project_cards()
        companies_inn, legal_inn = self._inn(cards)
        sending_id = uuid.uuid4().hex[:16]

        batch = build_batch(
            items=items,
            projects_by_item=self._projects(cards),
            companies_inn=companies_inn,
            legal_inn=legal_inn,
            employee_names=self._names(),
            period_from=period_from,
            period_to=period_to,
            sending_id=sending_id,
            overrides={**((self.config or {}).get("one_c") or {}),
                       "company_titles": self._company_titles(cards)},
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
