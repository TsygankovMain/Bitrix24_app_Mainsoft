"""Тесты живого поставщика стадий проекта: ProjectCardService._fetch_project_stage_options.

Блокер 3 (дожим ревью кнопки «Создать проект»): фильтр по признаку "kind"
(_is_automatic_stage_option / _first_manual_stage_id в
project_creation_defaults.py) написан правильно и здесь не трогается — но он
целиком зависит от того, честно ли поставщик стадий проставляет "kind"
живым записям. _build_legacy_stage_options (синтетический фолбэк) считает
kind по PROJECT_AUTO_STAGES. Живой _fetch_project_stage_options — тот, что
реально уходит в бой через crm.status.list, — до фикса ставил kind="manual"
БЕЗУСЛОВНО каждой живой записи, вообще не сверяясь с PROJECT_AUTO_STAGES:
метка "auto" появлялась только у синтетических заглушек, дописываемых ПОСЛЕ
основного цикла для стадий, которых Битрикс не вернул.

Из-за этого на портале, где реальная автостадия (например "Нет списаний 1
месяц") пришла от crm.status.list как обычная живая запись — а не как
заглушка, — она получала kind="manual" и can_drop=True и могла быть выбрана
резолвером как начальная стадия нового проекта. Сценарий воспроизводится,
когда среди живых статусов нет НИ ОДНОЙ ранней ручной стадии: выбрана не та
категория многокатегорийной воронки, либо администратор портала
переименовал/удалил ранние стадии (оба варианта доступны обычному
администратору без злого умысла).

Существующие тесты (tests_project_creation_defaults.py,
tests_project_creation_service.py) этот дефект не ловили: они гоняют
resolve_project_fields/build_card_fields на вручную собранных
stage_options — синтетическая ветка, которую этот баг не задевает вовсе.
Здесь — прогон через настоящий _fetch_project_stage_options с поддельным
клиентом Битрикса, живая УСПЕШНАЯ ветка (crm.status.list отвечает без
исключений и без сетевого сбоя).
"""
from datetime import date

from django.core.cache import cache
from django.test import TestCase

from .models import Bitrix24Account
from .project_board_service import ProjectCardService
from .project_creation_defaults import resolve_project_fields


class _FakeClient:
    """Двойник Client — по образцу tests_project_references.py."""

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
        return [method for method, _ in self.calls]


def _config():
    return {"project_sp_entity_type_id": 180}


class FetchProjectStageOptionsLiveTest(TestCase):
    """Живая успешная ветка: crm.category.list и crm.status.list оба

    отвечают без исключений (в отличие от tests_project_creation_defaults.py,
    где до этой правки единственный способ увидеть kind="auto" был через
    деградировавший список — полный сбой живого запроса).
    """

    def setUp(self):
        cache.clear()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-stage-live-1",
            is_master_account=True, domain_url="example-stage.bitrix24.ru",
            status="active", application_version=1,
        )

    def _client_missing_early_manual_stages(self):
        """Точное репро находки: категория без ранних ручных стадий.

        crm.category.list отдаёт пустой список категорий (обычный ответ для
        портала без явно настроенных категорий multi-category воронки) ->
        сервис уходит в category_id="0". crm.status.list для этой категории
        возвращает только ДВЕ живые записи: позднюю автостадию (её реальный
        Bitrix STATUS_ID НЕ совпадает по написанию с литералом
        PROJECT_AUTO_STAGES — совпадает только title) и ручную терминальную
        "Успех". Ни "Новый", ни "В просчете", ни "В работе" среди живых
        записей нет вовсе — как и требует репро.
        """
        return _FakeClient({
            "crm.category.list": {"result": []},
            "crm.status.list": {"result": [
                {
                    "STATUS_ID": "DT180_7:UC_NOWRITE30",
                    "NAME": "Нет списаний 1 месяц",
                    "SEMANTICS": None,
                    "SORT": "10",
                },
                {
                    "STATUS_ID": "DT180_7:SUCCESS",
                    "NAME": "Успех",
                    "SEMANTICS": "S",
                    "SORT": "20",
                },
            ]},
        })

    def test_live_status_matching_auto_stage_title_is_tagged_auto(self):
        client = self._client_missing_early_manual_stages()
        service = ProjectCardService(client, self.account)

        options = service._fetch_project_stage_options(_config())
        by_id = {opt["id"]: opt for opt in options}

        self.assertIn("DT180_7:UC_NOWRITE30", by_id, options)
        # Живая запись с настоящим Bitrix STATUS_ID, чей title совпадает с
        # PROJECT_AUTO_STAGES, обязана нести kind="auto" — ровно как и
        # синтетическая заглушка второй недостающей автостадии ниже.
        self.assertEqual(by_id["DT180_7:UC_NOWRITE30"]["kind"], "auto")

        # Настоящая ручная терминальная стадия — соседняя живая запись — не
        # должна была пострадать от фикса.
        self.assertEqual(by_id["DT180_7:SUCCESS"]["kind"], "manual")

        # Синтетическая заглушка второй недостающей автостадии по-прежнему
        # на месте и по-прежнему auto (де-дуп цикл её не публикует дважды).
        self.assertIn("Нет списаний 3 месяца", by_id)
        self.assertEqual(by_id["Нет списаний 3 месяца"]["kind"], "auto")

    def test_recognized_auto_stage_cannot_be_selected_as_initial_stage(self):
        """Полная цепочка: живые stage_options -> resolve_project_fields.

        Точное репро находки ревью: до фикса resolve_project_fields на этих
        живых stage_options выдавал fields.stage='DT180_7:UC_NOWRITE30' —
        автостадию — и missing=[], то есть ничего не сигнализировало о
        проблеме. Автостадия в поле карточки роняла бы её в автоколонку
        воронки, откуда её не вытащить мышью (см. докстринг
        _first_manual_stage_id в project_creation_defaults.py).
        """
        client = self._client_missing_early_manual_stages()
        service = ProjectCardService(client, self.account)
        stage_options = service._fetch_project_stage_options(_config())

        fields, missing = resolve_project_fields(
            {"project_name": "Портал АО Ромашка", "company_id": "15"},
            config={"hourly_rate": 1500},
            current_user_id="42",
            current_user_name="Петров Иван",
            today=date(2026, 7, 28),
            legal_entities=[],
            stage_options=stage_options,
        )

        self.assertEqual(missing, [])
        self.assertNotEqual(fields.stage, "DT180_7:UC_NOWRITE30")
        # Единственная оставшаяся живая РУЧНАЯ стадия в этом деградировавшем
        # наборе — терминальная "Успех": резолвер обязан пропустить
        # распознанную автостадию и подставить её.
        self.assertEqual(fields.stage, "DT180_7:SUCCESS")

    def test_recognized_auto_stage_cannot_be_dropped_onto_on_the_board(self):
        """can_drop тоже обязан отражать распознанный kind="auto".

        Единственный реальный потребитель can_drop — ProjectBoardColumn.vue
        на фронте (frontend/app/components/projects/ProjectBoardColumn.vue):
        canDrop=false одновременно (а) запрещает drag-and-drop на колонку
        (handleDragOver/handleDrop — ранний return) и (б) переключает
        подпись колонки на «Статус назначается автоматически». Это ТА ЖЕ
        бизнес-гарантия, что и у выбора начальной стадии: в автоматическую
        стадию нельзя писать вручную. Если can_drop остаётся True (как было
        до фикса, потому что для живых записей его считали по
        semantics not in {"S","F"}, не зная, что стадия вообще auto), доска
        разрешит перетащить карточку в стадию, которую расписание перезапишет
        сама, — тот же дефект, что и в форме создания, просто на другом
        экране.
        """
        client = self._client_missing_early_manual_stages()
        service = ProjectCardService(client, self.account)

        options = service._fetch_project_stage_options(_config())
        by_id = {opt["id"]: opt for opt in options}

        self.assertEqual(by_id["DT180_7:UC_NOWRITE30"]["can_drop"], False)
        # Ручная терминальная стадия ("Успех", semantics="S") — её can_drop
        # не в скоупе этого фикса: семантика Bitrix (won-стадии нельзя
        # перетаскивать руками) должна остаться нетронутой.
        self.assertEqual(by_id["DT180_7:SUCCESS"]["can_drop"], False)
