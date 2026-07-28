"""Тесты форс-рефреша доски проектов и главного экрана (Блокер 2 финального

ревью кнопки «Создать проект», .superpowers/sdd/2026-07-28-create-project-button/):
кэш доски и главного экрана — LocMemCache, свой у каждого воркера gunicorn,
общего хранилища нет. invalidate_project_runtime_caches (project_board_shared.py),
которую create() зовёт после записи нового проекта, чистит кэш ТОЛЬКО того
воркера, который обработал запрос на создание. Следующий GET
.../project-board или .../homepage/portfolio может попасть на ДРУГОЙ воркер
и получить кэш, прогретый ДО создания проекта, — тот же симптом «создал и не
увидел», что и в task-9-cache-fix-report.md, только на межпроцессном окне, а
не внутрипроцессном (то поведение уже закрыто и покрыто
CreateCacheInvalidationTest в tests_project_creation_service.py).

Решение — по образцу уже отревьюженного get_project_board_meta?refresh=1
(ProjectCardService.get_meta, views.py:_get_project_board_meta_refresh):
эндпоинт принимает признак принудительного обновления в адресе и передаёт
его в сервис как bypass_cache=True — тот пропускает ЧТЕНИЕ (не запись) кэша
и честно пересчитывает ответ. Кэш всё равно прогревается свежим значением в
конце (тот же приём) — так что воркер, который обработал форс-рефреш, сам
становится «тёплым» для следующих обычных запросов.

В отличие от get_meta, здесь форс-рефреш НЕ обязан бить в Битрикс живьём:
get_board_data/get_homepage_snapshot пересчитывают ответ из локальной базы
(ProjectCard/TimesheetItem) — тот же путь, что уже происходит на каждый
органический холодный кэш (PROJECT_BOARD_CACHE_TTL/HOMEPAGE_CACHE_TTL — 2
минуты, project_board_shared.py) без всякого force-параметра. Поэтому
рейт-лимит здесь не заведён — см. докстринги get_project_board/
get_homepage_portfolio в views.py.
"""
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TestCase

from .models import Bitrix24Account, ProjectCard
from .project_board_service import ProjectCardService


class _FakeClient:
    def __init__(self, responses=None):
        self._responses = dict(responses or {})
        self.calls = []
        self._bitrix_token = self

    def call_method(self, method, params=None):
        self.calls.append((method, params or {}))
        value = self._responses.get(method, {"result": []})
        if isinstance(value, Exception):
            raise value
        return value

    def methods_called(self):
        return [m for m, _ in self.calls]


def _create_card(account, project_id, name):
    ProjectCard.objects.create(
        bitrix24_account=account,
        project_id=project_id,
        project_name=name,
        stage="Новый",
        manual_stage="Новый",
    )


class BoardDataCacheBypassTest(TestCase):
    def setUp(self):
        cache.clear()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-board-bypass-1",
            is_master_account=True, domain_url="board-bypass.bitrix24.ru",
            status="active", application_version=1,
        )

    def test_default_call_keeps_serving_stale_cache_from_another_worker(self):
        """Документирует сам баг перед его обходом: без bypass_cache доска

        честно отдаёт то, что уже лежит в кэше ЭТОГО процесса, — даже если
        локальная таблица успела измениться (ровно то, что происходит, когда
        create() отработал на ДРУГОМ воркере и почистил только его кэш)."""
        service = ProjectCardService(_FakeClient(), self.account)

        warm = service.get_board_data()
        self.assertEqual(warm["cards"], [])

        # Проект появился в локальной таблице — как будто его создал другой
        # воркер и сбросил кэш только у себя.
        _create_card(self.account, "44", "Портал АО Ромашка")

        stale = service.get_board_data()
        self.assertEqual(
            stale["cards"], [],
            "Без bypass_cache должен отдаваться именно кэш этого воркера — тест ловит будущую регрессию поведения.",
        )

    def test_bypass_cache_ignores_stale_cache_and_shows_fresh_local_data(self):
        service = ProjectCardService(_FakeClient(), self.account)

        service.get_board_data()  # прогрев кэша пустой доской
        _create_card(self.account, "44", "Портал АО Ромашка")

        fresh = service.get_board_data(bypass_cache=True)
        project_ids = [card["project_id"] for card in fresh["cards"]]
        self.assertIn(
            "44", project_ids,
            "bypass_cache=True обязан игнорировать протухший кэш и честно перечитать локальную таблицу.",
        )

    def test_bypass_cache_rewarms_cache_for_subsequent_plain_calls(self):
        service = ProjectCardService(_FakeClient(), self.account)

        service.get_board_data()  # прогрев кэша пустой доской
        _create_card(self.account, "44", "Портал АО Ромашка")
        service.get_board_data(bypass_cache=True)

        # Следующий ОБЫЧНЫЙ вызов (как на следующей загрузке доски этим же
        # воркером) обязан увидеть уже свежее значение, а не пересчитывать
        # заново и не откатываться к прежнему кэшу.
        again = service.get_board_data()
        project_ids = [card["project_id"] for card in again["cards"]]
        self.assertIn("44", project_ids)


class HomepageSnapshotCacheBypassTest(TestCase):
    def setUp(self):
        cache.clear()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=2, is_b24_user_admin=True, member_id="m-homepage-bypass-1",
            is_master_account=True, domain_url="homepage-bypass.bitrix24.ru",
            status="active", application_version=1,
        )

    def test_bypass_cache_ignores_stale_outer_and_nested_board_cache(self):
        """get_homepage_snapshot кэшируется ОТДЕЛЬНЫМ ключом

        ("project-board-homepage") и внутри читает get_board_data() —
        значит bypass_cache обязан пробить ОБА кэша, а не только внешний,
        иначе свежая доска всё равно подставит вложенные протухшие данные
        (тот же урок, что и get_meta -> get_legal_entities(bypass_cache=...),
        project_board_service.py)."""
        service = ProjectCardService(_FakeClient(), self.account)

        # Прогреваем ОБА кэша пустыми данными — как будто оба уже читал
        # другой воркер до создания проекта.
        service.get_board_data()
        service.get_homepage_snapshot()

        _create_card(self.account, "55", "Портал ООО Новый")

        stale = service.get_homepage_snapshot()
        self.assertNotIn("55", [c["project_id"] for c in stale["cards"]])

        fresh = service.get_homepage_snapshot(bypass_cache=True)
        self.assertIn(
            "55", [c["project_id"] for c in fresh["cards"]],
            "bypass_cache=True на главном экране обязан пробить и вложенный кэш доски, не только свой собственный.",
        )

        # Оба кэша прогреты свежим значением форс-рефрешем.
        again_homepage = service.get_homepage_snapshot()
        self.assertIn("55", [c["project_id"] for c in again_homepage["cards"]])
        again_board = service.get_board_data()
        self.assertIn("55", [c["project_id"] for c in again_board["cards"]])


class ProjectBoardViewRefreshParamTest(TestCase):
    """View get_project_board: ?refresh=... транслируется в bypass_cache

    сервиса — тот же приём и тот же устойчивый к любому мусору разбор, что и
    у get_project_board_meta (см. GetProjectBoardMetaViewRefreshParamTest,
    tests_project_references.py). Разбор не должен бросать исключений ни при
    каком значении параметра — план уже дважды ловил падения именно на
    парсинге входных значений вне try/except."""

    def setUp(self):
        cache.clear()
        self.http = Client()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-board-view-refresh-1",
            is_master_account=True, domain_url="board-view-refresh.bitrix24.ru",
            status="active", application_version=1,
        )
        self.auth_header = f"Bearer {self.account.create_jwt_token()}"

    def _get(self, query_suffix=""):
        url = "/api/project-board"
        if query_suffix:
            url = f"{url}?{query_suffix}"
        return self.http.get(url, HTTP_AUTHORIZATION=self.auth_header)

    def test_no_param_passes_bypass_cache_false(self):
        with patch.object(ProjectCardService, "get_board_data", return_value={"cards": []}) as mocked:
            resp = self._get()

        self.assertEqual(resp.status_code, 200)
        mocked.assert_called_once_with(bypass_cache=False)

    def test_refresh_1_passes_bypass_cache_true(self):
        with patch.object(ProjectCardService, "get_board_data", return_value={"cards": []}) as mocked:
            resp = self._get("refresh=1")

        self.assertEqual(resp.status_code, 200)
        mocked.assert_called_once_with(bypass_cache=True)

    def test_garbage_refresh_value_does_not_crash_endpoint(self):
        garbage_values = ("", "мусор", "0", "null", "NaN", "%%%", "false", "[]")
        for garbage in garbage_values:
            with patch.object(ProjectCardService, "get_board_data", return_value={"cards": []}):
                resp = self._get(f"refresh={garbage}")

            self.assertEqual(
                resp.status_code, 200,
                f"refresh={garbage!r} не должен ронять эндпоинт, получили {resp.status_code}",
            )


class HomepagePortfolioViewRefreshParamTest(TestCase):
    """View get_homepage_portfolio: тот же приём ?refresh=..., что и у доски

    и у get_project_board_meta."""

    def setUp(self):
        cache.clear()
        self.http = Client()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-homepage-view-refresh-1",
            is_master_account=True, domain_url="homepage-view-refresh.bitrix24.ru",
            status="active", application_version=1,
        )
        self.auth_header = f"Bearer {self.account.create_jwt_token()}"

    def _get(self, query_suffix=""):
        url = "/api/homepage/portfolio"
        if query_suffix:
            url = f"{url}?{query_suffix}"
        return self.http.get(url, HTTP_AUTHORIZATION=self.auth_header)

    def test_no_param_passes_bypass_cache_false(self):
        with patch.object(ProjectCardService, "get_homepage_snapshot", return_value={"cards": []}) as mocked:
            resp = self._get()

        self.assertEqual(resp.status_code, 200)
        mocked.assert_called_once_with(bypass_cache=False)

    def test_refresh_yes_passes_bypass_cache_true(self):
        with patch.object(ProjectCardService, "get_homepage_snapshot", return_value={"cards": []}) as mocked:
            resp = self._get("refresh=yes")

        self.assertEqual(resp.status_code, 200)
        mocked.assert_called_once_with(bypass_cache=True)

    def test_garbage_refresh_value_does_not_crash_endpoint(self):
        garbage_values = ("", "мусор", "0", "null", "NaN", "%%%", "false", "[]")
        for garbage in garbage_values:
            with patch.object(ProjectCardService, "get_homepage_snapshot", return_value={"cards": []}):
                resp = self._get(f"refresh={garbage}")

            self.assertEqual(
                resp.status_code, 200,
                f"refresh={garbage!r} не должен ронять эндпоинт, получили {resp.status_code}",
            )
