"""
Хотфикс 2026-07-28: тело запроса, успешно разобравшееся в НЕ-объект (список,
число, строка, true), давало 500 на всех эндпоинтах, которые читают payload
через `_load_request_json` и сразу зовут у результата метод словаря (.get(...)).

Причина: `_load_request_json` пропускала дальше любое успешно разобранное
JSON-значение как есть. Пустой список и null не падали только потому, что
где-то ниже по стеку (resolve_project_fields: `form = form or {}`) их гасила
чужая, случайная для остальных вызывающих конструкция `x or {}` — она же не
трогает список/число/строку/true, потому что они истинны. Первый же
payload.get(...) на таком значении падал с "'list'/'int'/'str'/'bool' object
has no attribute 'get'".

Воспроизведено ревью реальным HTTP-запросом POST /api/project-board/create:
тела [1, 2, 3] / 42 / "hello" / true -> 500; тела "" / "{}" / "[]" / null /
{...поля неверных типов} -> 200 штатно. Тот же незащищённый паттерн — у
каждого вызывающего _load_request_json (update_project_board и другие).

Фикс — централизованно в `_load_request_json`: любое успешно разобранное
значение, которое не dict, приводится к {}, как сейчас уже (случайно)
приводятся null и [].

Три класса тестов:
  * LoadRequestJsonHelperTest — юнит-тесты самого хелпера на всех формах входа.
  * CreateProjectBoardMalformedBodyTest — регресс через реальный HTTP-клиент
    на новом эндпоинте create_project_board (эндпоинт из отчёта ревью).
  * UpdateProjectBoardMalformedBodyTest — тот же регресс на соседе
    update_project_board (ревьюер называл его как пример того же паттерна).
"""
import json
from unittest.mock import PropertyMock, patch

from django.test import Client, RequestFactory, TestCase

from .models import Bitrix24Account

# Ровно те четыре тела, которыми ревьюер воспроизвёл 500 через реальный HTTP.
BODIES_THAT_REPRODUCED_THE_500 = {
    "list": [1, 2, 3],
    "number": 42,
    "string": "hello",
    "bool_true": True,
}


def _make_account(domain_url: str, *, b24_user_id: int = 1) -> Bitrix24Account:
    return Bitrix24Account.objects.create(
        b24_user_id=b24_user_id,
        member_id=f"member_{b24_user_id}_{domain_url}",
        domain_url=domain_url,
        status="active",
        application_version=1,
        is_b24_user_admin=True,
        is_master_account=False,
    )


def _auth_header(account: Bitrix24Account) -> str:
    return f"Bearer {account.create_jwt_token()}"


# ---------------------------------------------------------------------------
# Юнит-тесты хелпера
# ---------------------------------------------------------------------------

class LoadRequestJsonHelperTest(TestCase):
    """`_load_request_json` обязана всегда возвращать dict — все вызывающие
    (create_project_board, update_project_board, update_project_board_stage,
    archive_project_board) обращаются к результату как к словарю без
    дополнительной проверки типа."""

    def _request(self, raw_body):
        factory = RequestFactory()
        return factory.post("/x", data=raw_body, content_type="application/json")

    def _load(self, raw_body):
        from .views import _load_request_json
        return _load_request_json(self._request(raw_body))

    def test_valid_object_passes_through_unchanged(self):
        result = self._load(json.dumps({"a": 1, "b": [1, 2, 3], "c": None}))
        self.assertEqual(result, {"a": 1, "b": [1, 2, 3], "c": None})

    def test_empty_object(self):
        self.assertEqual(self._load(json.dumps({})), {})

    def test_empty_body(self):
        self.assertEqual(self._load(b""), {})

    def test_non_json_garbage_text(self):
        self.assertEqual(self._load(b"not-json-at-all!!!"), {})

    def test_all_non_object_json_values_collapse_to_empty_dict(self):
        """Все формы входа, которые парсятся как валидный JSON, но не объект:
        null, [], непустой список, 0, число, "", строка, true, false."""
        cases = {
            "null": None,
            "empty_list": [],
            "non_empty_list": [1, 2, 3],
            "zero": 0,
            "positive_number": 42,
            "float": 3.14,
            "empty_string": "",
            "non_empty_string": "hello",
            "true": True,
            "false": False,
        }
        for label, value in cases.items():
            with self.subTest(label=label):
                self.assertEqual(self._load(json.dumps(value)), {})

    def test_the_four_bodies_that_reproduced_the_500(self):
        """Прямая проверка на теле отчёта ревью: [1, 2, 3] / 42 / "hello" / true."""
        for label, value in BODIES_THAT_REPRODUCED_THE_500.items():
            with self.subTest(label=label):
                self.assertEqual(self._load(json.dumps(value)), {})


# ---------------------------------------------------------------------------
# Регресс через реальный HTTP-клиент: create_project_board
# ---------------------------------------------------------------------------

class _FakeClient:
    """Минимальный двойник Bitrix-клиента — тот же приём и тот же валидный
    app.option.get, что и в tests_project_creation_service.py
    (CreateOrchestrationTest._client()): create() читает конфигурацию через
    get_configuration_sync(), которая НЕ обёрнута в try/except на уровне
    create() — без валидного ответа он падал бы раньше, чем дойдёт до
    resolve_project_fields (именно там раньше падало на payload-не-словаре).
    Всё остальное — пустой список; get_legal_entities/get_project_stage_options
    в create() сами обёрнуты в try/except и переживают пустой/неожиданный ответ."""

    _CONFIG_RESPONSE = {"result": {"timestamp_config": (
        '{"hourly_rate": 1500, "project_sp_entity_type_id": 180,'
        ' "project_fields_mapping": {"title": "title",'
        ' "bitrix_group_id": "ufCrm7Group", "stage_id": "stageId"}}'
    )}}

    def __init__(self):
        self._bitrix_token = self

    def call_method(self, method, params=None):
        if method == "app.option.get":
            return self._CONFIG_RESPONSE
        return {"result": []}


class CreateProjectBoardMalformedBodyTest(TestCase):
    """POST /api/project-board/create с телом, которое разбирается в
    не-словарь. До фикса: 500 "'...' object has no attribute 'get'" из
    resolve_project_fields. После фикса: payload нормализуется в {} ещё в
    _load_request_json и эндпоинт ведёт себя так же, как при пустом объекте
    — 200 с missing_fields (project_name/company не заполнены)."""

    def _post(self, account, raw_body_text):
        with patch.object(Bitrix24Account, "client", new_callable=PropertyMock, return_value=_FakeClient()):
            return Client().post(
                "/api/project-board/create",
                data=raw_body_text,
                content_type="application/json",
                HTTP_AUTHORIZATION=_auth_header(account),
            )

    def test_malformed_bodies_no_longer_500(self):
        for label, value in BODIES_THAT_REPRODUCED_THE_500.items():
            with self.subTest(label=label):
                # Свежий аккаунт на каждое тело: create_project_board стоит за
                # rate_limit("project_create", 5, 60, key="account") — общий
                # аккаунт на все 4 тела рисковал бы случайно упереться в 429
                # и исказить результат теста, не имеющий отношения к этой проверке.
                account = _make_account(f"portal-create-malformed-{label}.bitrix24.ru")
                resp = self._post(account, json.dumps(value))
                self.assertEqual(
                    resp.status_code,
                    200,
                    f"body={value!r} must be treated like an empty payload (200 + "
                    f"missing_fields), got {resp.status_code}: {resp.content!r}",
                )
                body = resp.json()
                self.assertIn("missing_fields", body)
                self.assertIn("project_name", body["missing_fields"])
                self.assertIn("company", body["missing_fields"])
                self.assertFalse(body["done"])

    def test_control_empty_object_gives_the_same_missing_fields_shape(self):
        """Контроль: подтверждаем, что {} (заведомо корректный вид тела, уже
        и раньше отдававший 200) даёт ТОТ ЖЕ ответ, что и четвёрка выше после
        фикса, — значит, для них не завели особый путь, а просто перестали
        ронять то, что и так должно было бы вести себя как пустой payload."""
        account = _make_account("portal-create-malformed-control.bitrix24.ru")
        resp = self._post(account, json.dumps({}))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("project_name", body["missing_fields"])
        self.assertIn("company", body["missing_fields"])
        self.assertFalse(body["done"])


# ---------------------------------------------------------------------------
# Регресс через реальный HTTP-клиент: update_project_board (сосед из отчёта)
# ---------------------------------------------------------------------------

class UpdateProjectBoardMalformedBodyTest(TestCase):
    """POST /api/project-board/update с тем же набором тел. До фикса: 500
    "'...' object has no attribute 'get'" прямо на payload.get("project_id")
    — это первая строка вьюхи после _load_request_json, без какой-либо
    защиты вида `x or {}`. После фикса: payload -> {}, project_id
    отсутствует -> штатные 400 "project_id is required", как при {}.
    Bitrix здесь не мокаем: код не идёт дальше этого раннего return —
    ни ProjectCardService, ни Bitrix ещё не тронуты."""

    def setUp(self):
        self.account = _make_account("portal-update-malformed.bitrix24.ru")
        self.client = Client()

    def _post(self, raw_body_text):
        return self.client.post(
            "/api/project-board/update",
            data=raw_body_text,
            content_type="application/json",
            HTTP_AUTHORIZATION=_auth_header(self.account),
        )

    def test_malformed_bodies_no_longer_500(self):
        for label, value in BODIES_THAT_REPRODUCED_THE_500.items():
            with self.subTest(label=label):
                resp = self._post(json.dumps(value))
                self.assertEqual(
                    resp.status_code,
                    400,
                    f"body={value!r} must degrade to the same 'project_id is required' "
                    f"400 as an empty object, got {resp.status_code}: {resp.content!r}",
                )
                self.assertEqual(resp.json(), {"error": "project_id is required"})

    def test_control_empty_object_gives_the_same_400(self):
        resp = self._post(json.dumps({}))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"error": "project_id is required"})
