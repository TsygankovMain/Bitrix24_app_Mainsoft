"""Справочники 1С для экрана сопоставления.

Сопоставление раньше набиралось руками: ФИО физлица и ИНН. Опечатка в них
не видна на экране — она всплывает отказом строки при отправке часов, когда
период уже закрыт. Поэтому списки берутся из самой 1С, а человек выбирает
из готового.

Адрес считается из адреса приёмника: обе точки живут в одной публикации базы,
и отдельной настройки для этого заводить незачем.
"""
import logging
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings

logger = logging.getLogger(__name__)

# Путь точки справочников внутри публикации базы.
DIRECTORY_PATH = "/hs/itlab/v1/list/all"


class OneCDirectoryError(RuntimeError):
    """Справочники получить не удалось. Сообщение показывается человеку."""


def directory_url(inbox_url: str) -> str:
    """Из адреса приёмника получает адрес точки справочников.

    ``…/Demo_BUH/hs/msbx24/v1/inbox/timesheet`` → ``…/Demo_BUH/hs/itlab/v1/list/all``.
    Разрез идёт по ``/hs/`` — границе между публикацией базы и её HTTP-сервисами.
    """
    if not inbox_url:
        return ""

    parts = urlsplit(inbox_url.strip())
    path = parts.path
    marker = path.lower().find("/hs/")
    base = path[:marker] if marker >= 0 else path.rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, base + DIRECTORY_PATH, "", ""))


class HttpDirectoryTransport:
    """GET в точку справочников. Токен — тот же, что у приёма часов."""

    def __init__(self, url: str, token: str, user: str = "", password: str = "",
                 timeout: int = 60):
        self.url = url
        self.token = token
        self.user = user
        self.password = password
        self.timeout = timeout

    def __call__(self) -> Any:
        import requests  # локально: без похода в 1С модуль не нужен

        response = requests.get(
            self.url,
            params={"token": self.token} if self.token else None,
            auth=(self.user, self.password) if self.user else None,
            timeout=self.timeout,
        )
        if response.status_code == 404:
            raise OneCDirectoryError(
                "1С не знает точку справочников: в базе не установлено "
                "расширение IT_Lab или нужна свежая его версия")
        if response.status_code == 401:
            raise OneCDirectoryError(
                "1С не приняла авторизацию: проверьте пользователя, пароль и токен")
        try:
            return response.json()
        except ValueError:
            raise OneCDirectoryError(
                f"1С ответила не JSON (HTTP {response.status_code})")


class OneCDirectoryService:
    """Отдаёт списки физлиц, организаций и контрагентов из 1С."""

    def __init__(self, config: Optional[Dict[str, Any]] = None,
                 transport: Optional[Callable[[], Any]] = None):
        self.config = config or {}
        self._transport = transport

    def _settings(self) -> Dict[str, str]:
        one_c = (self.config or {}).get("one_c") or {}

        def value(key: str, env_name: str) -> str:
            return str(one_c.get(key) or getattr(settings, env_name, "") or "").strip()

        return {
            "inbox_url": value("inbox_url", "ONE_C_INBOX_URL"),
            "token": value("token", "ONE_C_TOKEN"),
            "user": value("user", "ONE_C_USER"),
            "password": value("password", "ONE_C_PASSWORD"),
        }

    def fetch(self) -> Dict[str, List[Dict[str, str]]]:
        conf = self._settings()
        transport = self._transport
        if transport is None:
            url = directory_url(conf["inbox_url"])
            if not url:
                raise OneCDirectoryError(
                    "Не задан адрес подключения к 1С: заполните его выше и сохраните")
            transport = HttpDirectoryTransport(
                url, conf["token"], conf["user"], conf["password"])

        try:
            answer = transport()
        except OneCDirectoryError:
            raise
        except Exception as error:  # сеть, таймаут, DNS — показываем как есть
            logger.warning("Справочники 1С не получены", exc_info=True)
            raise OneCDirectoryError(f"1С недоступна: {error}")

        if not isinstance(answer, dict):
            raise OneCDirectoryError("1С вернула неожиданный ответ")
        if answer.get("ошибка"):
            raise OneCDirectoryError(str(answer["ошибка"]))

        return {
            "people": _rows(answer.get("физлица")),
            "organizations": _rows(answer.get("организации")),
            "counterparties": _rows(answer.get("контрагенты")),
        }


def _rows(raw: Any) -> List[Dict[str, str]]:
    """Приводит ответ 1С к тому, что нужно экрану: имя, ИНН, идентификатор."""
    if not isinstance(raw, list):
        return []

    rows = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("наименование") or "").strip()
        if not name:
            continue
        rows.append({
            "id": str(item.get("ид") or ""),
            "name": name,
            "full_name": str(item.get("наименованиеПолное") or "").strip(),
            "inn": str(item.get("инн") or "").strip(),
        })
    return rows
