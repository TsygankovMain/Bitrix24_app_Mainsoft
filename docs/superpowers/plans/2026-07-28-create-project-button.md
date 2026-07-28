# Кнопка «Создать проект» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Одна кнопка в приложении создаёт связку «компания в CRM + проект/группа в Задачах + карточка смарт-процесса проекта», чтобы сотрудники перестали забывать это делать вручную.

**Architecture:** Оркестратор на бэкенде (`ProjectCreationService`) выполняет три идемпотентных шага строго по порядку — компания, группа, карточка, — потому что карточка ссылается на первые две. Каждый шаг сначала ищет, потом создаёт; при более чем одном совпадении шаг останавливается и возвращает варианты (`ambiguous`), не угадывая. Значения полей карточки считает отдельный чистый модуль `project_creation_defaults` — он не знает про Битрикс и тестируется без сети. Фронт — модальное окно с предзаполненной формой, показывающее статус по каждому шагу и умеющее повторить запрос (повтор досоздаёт только недостающее).

**Tech Stack:** Django 5.2 (Python 3.11) на бэкенде, b24pysdk для REST-вызовов Битрикса; Nuxt 4 / Vue 3 + `@bitrix24/b24ui-nuxt` на фронте; тесты — `django.test.TestCase` на бэкенде и `node:test` через `tsx` на фронте.

**Спека:** `docs/superpowers/specs/2026-07-28-create-project-button-design.md`

## §11 спеки закрыт кодом — портал дёргать не нужно

Спека оставляла три вопроса «проверить до реализации». Все три отвечает существующий код, живых вызовов к боевому порталу не требуется:

1. **Признак «моя компания»** — `ProjectCardService.get_legal_entities()` (`project_board_service.py:572`) уже возвращает только свои компании: под капотом `_fetch_companies_live(only_my_company=True)` читает `IS_MY_COMPANY` / `isMyCompany` через `crm.company.list` и `crm.item.list`. Ничего нового писать не надо, только вызвать.
2. **Ставка по умолчанию** — ключ `hourly_rate` в конфигурации портала (`ConfigurationService._get_default_configuration`, дефолт `0`). Ноль означает «не задана» → поле обязательно для ввода.
3. **Начальная стадия** — `ProjectCardService.get_project_stage_options(config)` (`project_board_service.py:709`) отдаёт стадии воронки по порядку; берём первую.

## Global Constraints

- **Все вызовы Битрикса — под токеном текущего сотрудника** (`request.bitrix24_account.client`). Своей системы прав не заводим, права проверяет Битрикс.
- **Запись в БД — только через `scope_to_tenant`**, как во всём остальном коде (`from .tenant_scoping import scope_to_tenant`).
- **Ничего никогда не удаляется, откатов нет.** Частичный результат сохраняется и возвращается.
- **Имена полей карточки берутся из `project_fields_mapping`** (`ConfigurationService.get_configuration_sync()`), а не зашиваются в код: на разных порталах поля называются по-разному. Механизм уже существует — `ProjectCardService._assign_mapped_spa_field`.
- **Неоднозначность не разрешается автоматически:** если поиск компании или группы вернул больше одного совпадения, шаг не выполняется, возвращается `status: "ambiguous"` и список кандидатов.
- **Пустых полей не остаётся.** У каждого поля `ProjectCard` есть источник значения — автоматика или пользователь. Единственные осознанные исключения: `project_hours_budget` и производная от неё `planned_budget_amount`.
- **Дата окончания = дата начала + 1 год.**
- **Владелец группы — создатель**, то есть текущий сотрудник. Отдельно владельца не назначаем и участников не добавляем.
- **Прод — Python 3.11.15 / Django 5.2.16**, локальный venv 3.9/4.2 для проверки не годится. Финальная сверка — в Docker (см. «Как гонять тесты»).

## Как гонять тесты

**Бэкенд, django-модули** (4 файла `tests_inn_apply_batch`, `tests_project_fetch_keyset`, `tests_fetch_paginated_batch`, `tests_sync_scoped` подменяют `django` в `sys.modules` и ломают общий раннер — их исключаем):

```bash
cd backends/python/api && python manage.py test main.tests_project_creation_defaults main.tests_project_creation_service --settings=test_settings -v 2
```

**Финальная сверка на прод-стеке** (обязательна перед мержем):

```bash
cd backends/python && docker run --rm -v "$PWD":/app -w /app python:3.11-slim bash -c 'pip install -q -r api/requirements.txt && cd api && python manage.py test main.tests_project_creation_defaults main.tests_project_creation_service --settings=test_settings -v 2'
```

**Фронтенд** (`tsx` не объявлен в `package.json`, поэтому через `dlx`):

```bash
cd frontend && corepack pnpm@9.15.9 dlx tsx --test 'tests/**/*.test.ts'
```

**Сборка фронта** (Nuxt 4 + Vite требует >1.7 ГБ heap):

```bash
cd frontend && NODE_OPTIONS="--max-old-space-size=4096" corepack pnpm@9.15.9 run build
```

## Структура файлов

| Файл | Ответственность |
|---|---|
| `backends/python/api/main/project_creation_defaults.py` (создать) | Чистый расчёт значений полей по правилам §5 спеки. Не знает про Битрикс и про Django ORM. |
| `backends/python/api/main/project_creation_service.py` (создать) | Оркестратор: три идемпотентных шага + сборка ответа + write-through в `ProjectCard`. |
| `backends/python/api/main/tests_project_creation_defaults.py` (создать) | Тесты чистого расчёта. |
| `backends/python/api/main/tests_project_creation_service.py` (создать) | Тесты оркестратора на фейковом клиенте. |
| `backends/python/api/main/views.py` (изменить) | HTTP-эндпоинт `create_project_board`. |
| `backends/python/api/main/urls.py` (изменить) | Маршрут `api/project-board/create`. |
| `frontend/app/types/project-creation.ts` (создать) | Типы запроса/ответа. |
| `frontend/app/stores/api.ts` (изменить) | Метод `createProject`. |
| `frontend/app/components/projects/CreateProjectModal.vue` (создать) | Форма, статусы шагов, повтор. |
| `frontend/app/pages/projects/index.client.vue` (изменить) | Кнопка на доске проектов. |
| `frontend/app/pages/index.client.vue` (изменить) | Кнопка на главном экране. |
| `frontend/tests/projectCreation.test.ts` (создать) | Тесты расчёта дефолтов на фронте и обработки ответа. |

Расчёт дефолтов вынесен в отдельный модуль намеренно: это единственная часть правил §5, которая должна совпадать на бэкенде и на фронте (фронт показывает предзаполненные значения, бэкенд им доверять не может и считает заново). Держать её в оркестраторе — значит тестировать арифметику через моки Битрикса.

---

### Task 1: Чистый расчёт значений полей

**Files:**
- Create: `backends/python/api/main/project_creation_defaults.py`
- Test: `backends/python/api/main/tests_project_creation_defaults.py`

**Interfaces:**
- Consumes: ничего (первая задача, зависимостей нет).
- Produces:
  - `add_one_year(value: date) -> date`
  - `@dataclass ResolvedProjectFields` с полями: `project_name: str`, `company_id: Optional[str]`, `company_name: str`, `our_legal_entity_id: Optional[str]`, `our_legal_entity_name: str`, `curator_user_id: str`, `curator_name: str`, `project_start_date: date`, `project_end_date: date`, `project_hours_budget: Optional[float]`, `hourly_rate: float`, `planned_budget_amount: Optional[float]`, `project_type: str`, `budget_mode: str`, `is_support: bool`, `stage: str`
  - `resolve_project_fields(form: Dict[str, Any], *, config: Dict[str, Any], current_user_id: str, current_user_name: str, today: date, legal_entities: List[Dict[str, Any]], stage_options: List[Dict[str, Any]]) -> Tuple[ResolvedProjectFields, List[str]]` — возвращает заполненные поля и список ключей обязательных полей, которых не хватило.
  - Константы `DEFAULT_PROJECT_TYPE = "delivery"`, `DEFAULT_BUDGET_MODE = "hours_and_amount"`

- [ ] **Step 1: Написать падающий тест**

Создать `backends/python/api/main/tests_project_creation_defaults.py`:

```python
"""Тесты чистого расчёта полей карточки проекта (§5 спеки: пустых полей не остаётся)."""
from datetime import date
from django.test import SimpleTestCase

from .project_creation_defaults import (
    DEFAULT_BUDGET_MODE,
    DEFAULT_PROJECT_TYPE,
    add_one_year,
    resolve_project_fields,
)


def _config(hourly_rate=1500):
    return {"hourly_rate": hourly_rate, "project_fields_mapping": {}, "project_sp_entity_type_id": 180}


def _stages():
    return [{"id": "DT180_7:NEW", "title": "Новый"}, {"id": "DT180_7:WON", "title": "Завершён"}]


def _resolve(form, **overrides):
    kwargs = {
        "config": _config(),
        "current_user_id": "42",
        "current_user_name": "Петров Иван",
        "today": date(2026, 7, 28),
        "legal_entities": [{"id": "7", "name": "ООО Мейнсофт"}],
        "stage_options": _stages(),
    }
    kwargs.update(overrides)
    return resolve_project_fields(form, **kwargs)


class AddOneYearTest(SimpleTestCase):
    def test_adds_one_year(self):
        self.assertEqual(add_one_year(date(2026, 7, 28)), date(2027, 7, 28))

    def test_leap_day_falls_back_to_28_february(self):
        self.assertEqual(add_one_year(date(2028, 2, 29)), date(2029, 2, 28))


class ResolveProjectFieldsTest(SimpleTestCase):
    def test_fills_every_field_from_defaults(self):
        fields, missing = _resolve({"project_name": "Портал АО Ромашка", "company_id": "15"})

        self.assertEqual(missing, [])
        self.assertEqual(fields.project_name, "Портал АО Ромашка")
        self.assertEqual(fields.curator_user_id, "42")
        self.assertEqual(fields.curator_name, "Петров Иван")
        self.assertEqual(fields.project_start_date, date(2026, 7, 28))
        self.assertEqual(fields.project_end_date, date(2027, 7, 28))
        self.assertEqual(fields.hourly_rate, 1500.0)
        self.assertEqual(fields.project_type, DEFAULT_PROJECT_TYPE)
        self.assertEqual(fields.budget_mode, DEFAULT_BUDGET_MODE)
        self.assertFalse(fields.is_support)
        self.assertEqual(fields.stage, "DT180_7:NEW")
        # Единственное разрешённое исключение из «пустых полей не остаётся»:
        self.assertIsNone(fields.project_hours_budget)
        self.assertIsNone(fields.planned_budget_amount)

    def test_single_legal_entity_is_auto_selected(self):
        fields, missing = _resolve({"project_name": "П", "company_id": "15"})
        self.assertEqual(fields.our_legal_entity_id, "7")
        self.assertEqual(fields.our_legal_entity_name, "ООО Мейнсофт")
        self.assertEqual(missing, [])

    def test_several_legal_entities_make_the_field_required(self):
        entities = [{"id": "7", "name": "ООО Мейнсофт"}, {"id": "9", "name": "ИП Цыганков"}]
        fields, missing = _resolve({"project_name": "П", "company_id": "15"}, legal_entities=entities)
        self.assertIn("our_legal_entity_id", missing)
        self.assertIsNone(fields.our_legal_entity_id)

    def test_several_legal_entities_satisfied_by_user_choice(self):
        entities = [{"id": "7", "name": "ООО Мейнсофт"}, {"id": "9", "name": "ИП Цыганков"}]
        fields, missing = _resolve(
            {"project_name": "П", "company_id": "15", "our_legal_entity_id": "9"},
            legal_entities=entities,
        )
        self.assertEqual(missing, [])
        self.assertEqual(fields.our_legal_entity_id, "9")
        self.assertEqual(fields.our_legal_entity_name, "ИП Цыганков")

    def test_rate_missing_in_config_makes_the_field_required(self):
        fields, missing = _resolve({"project_name": "П", "company_id": "15"}, config=_config(hourly_rate=0))
        self.assertIn("hourly_rate", missing)

    def test_rate_from_form_beats_config(self):
        fields, missing = _resolve({"project_name": "П", "company_id": "15", "hourly_rate": "2000"})
        self.assertEqual(fields.hourly_rate, 2000.0)
        self.assertEqual(missing, [])

    def test_planned_amount_is_hours_times_rate(self):
        fields, _ = _resolve({"project_name": "П", "company_id": "15", "project_hours_budget": "10"})
        self.assertEqual(fields.project_hours_budget, 10.0)
        self.assertEqual(fields.planned_budget_amount, 15000.0)

    def test_end_date_follows_explicit_start_date(self):
        fields, _ = _resolve(
            {"project_name": "П", "company_id": "15", "project_start_date": "2026-01-15"}
        )
        self.assertEqual(fields.project_start_date, date(2026, 1, 15))
        self.assertEqual(fields.project_end_date, date(2027, 1, 15))

    def test_explicit_end_date_is_not_overwritten(self):
        fields, _ = _resolve(
            {"project_name": "П", "company_id": "15", "project_end_date": "2026-12-31"}
        )
        self.assertEqual(fields.project_end_date, date(2026, 12, 31))

    def test_name_and_company_are_required(self):
        _, missing = _resolve({})
        self.assertIn("project_name", missing)
        self.assertIn("company", missing)

    def test_company_name_alone_satisfies_company_requirement(self):
        _, missing = _resolve({"project_name": "П", "company_name": "АО Ромашка"})
        self.assertNotIn("company", missing)

    def test_empty_stage_options_leave_stage_blank_without_crashing(self):
        fields, missing = _resolve({"project_name": "П", "company_id": "15"}, stage_options=[])
        self.assertEqual(fields.stage, "")
        self.assertEqual(missing, [])
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
cd backends/python/api && python manage.py test main.tests_project_creation_defaults --settings=test_settings -v 2
```

Ожидаемо: `ModuleNotFoundError: No module named 'main.project_creation_defaults'`.

- [ ] **Step 3: Написать минимальную реализацию**

Создать `backends/python/api/main/project_creation_defaults.py`:

```python
"""Чистый расчёт значений полей карточки проекта при создании через кнопку
«Создать проект».

Правило заказчика (§5 спеки 2026-07-28): пустых полей не остаётся — у каждого
поля есть источник значения, автоматика или пользователь. Осознанные
исключения — project_hours_budget и производная от неё planned_budget_amount:
на момент заведения проекта объём часто неизвестен, а выдуманное число попало
бы в отчёты как факт.

Модуль намеренно не знает ни про Битрикс, ни про Django ORM: те же правила
дублирует форма на фронте, и арифметику надо проверять без моков сети.
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_PROJECT_TYPE = "delivery"
DEFAULT_BUDGET_MODE = "hours_and_amount"


def add_one_year(value: date) -> date:
    """Дата + 1 год. 29 февраля переносится на 28-е: в невисокосном году
    такой даты нет, а падать на календарном крае нельзя."""
    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        return value.replace(year=value.year + 1, day=28)


@dataclass
class ResolvedProjectFields:
    project_name: str
    company_id: Optional[str]
    company_name: str
    our_legal_entity_id: Optional[str]
    our_legal_entity_name: str
    curator_user_id: str
    curator_name: str
    project_start_date: date
    project_end_date: date
    project_hours_budget: Optional[float]
    hourly_rate: float
    planned_budget_amount: Optional[float]
    project_type: str
    budget_mode: str
    is_support: bool
    stage: str


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_float(value: Any) -> Optional[float]:
    text = _clean_str(value).replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any, fallback: date) -> date:
    text = _clean_str(value)
    if not text:
        return fallback
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return fallback


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _clean_str(value).upper() in {"Y", "YES", "TRUE", "1"}


def resolve_project_fields(
    form: Dict[str, Any],
    *,
    config: Dict[str, Any],
    current_user_id: str,
    current_user_name: str,
    today: date,
    legal_entities: List[Dict[str, Any]],
    stage_options: List[Dict[str, Any]],
) -> Tuple[ResolvedProjectFields, List[str]]:
    """Считает итоговые значения полей и список недостающих обязательных.

    Ключи в списке missing: "project_name", "company", "our_legal_entity_id",
    "hourly_rate" — их фронт подсвечивает в форме.
    """
    form = form or {}
    missing: List[str] = []

    project_name = _clean_str(form.get("project_name"))
    if not project_name:
        missing.append("project_name")

    company_id = _clean_str(form.get("company_id")) or None
    company_name = _clean_str(form.get("company_name"))
    if not company_id and not company_name:
        missing.append("company")

    legal_entity_id = _clean_str(form.get("our_legal_entity_id")) or None
    legal_entity_name = _clean_str(form.get("our_legal_entity_name"))
    if legal_entity_id:
        for entity in legal_entities or []:
            if _clean_str(entity.get("id")) == legal_entity_id:
                legal_entity_name = legal_entity_name or _clean_str(entity.get("name"))
                break
    elif len(legal_entities or []) == 1:
        only = legal_entities[0]
        legal_entity_id = _clean_str(only.get("id")) or None
        legal_entity_name = _clean_str(only.get("name"))
    elif legal_entities:
        missing.append("our_legal_entity_id")

    curator_user_id = _clean_str(form.get("curator_user_id")) or _clean_str(current_user_id)
    curator_name = _clean_str(form.get("curator_name")) or _clean_str(current_user_name)

    start_date = _parse_date(form.get("project_start_date"), today)
    end_date = _parse_date(form.get("project_end_date"), add_one_year(start_date))

    hours_budget = _parse_float(form.get("project_hours_budget"))

    hourly_rate = _parse_float(form.get("hourly_rate"))
    if hourly_rate is None:
        hourly_rate = _parse_float((config or {}).get("hourly_rate"))
    if not hourly_rate:
        missing.append("hourly_rate")
        hourly_rate = 0.0

    planned_amount = None
    if hours_budget is not None:
        planned_amount = round(hours_budget * hourly_rate, 2)

    stage = _clean_str(form.get("stage"))
    if not stage and stage_options:
        stage = _clean_str(stage_options[0].get("id"))

    fields = ResolvedProjectFields(
        project_name=project_name,
        company_id=company_id,
        company_name=company_name,
        our_legal_entity_id=legal_entity_id,
        our_legal_entity_name=legal_entity_name,
        curator_user_id=curator_user_id,
        curator_name=curator_name,
        project_start_date=start_date,
        project_end_date=end_date,
        project_hours_budget=hours_budget,
        hourly_rate=hourly_rate,
        planned_budget_amount=planned_amount,
        project_type=_clean_str(form.get("project_type")) or DEFAULT_PROJECT_TYPE,
        budget_mode=_clean_str(form.get("budget_mode")) or DEFAULT_BUDGET_MODE,
        is_support=_parse_bool(form.get("is_support")),
        stage=stage,
    )
    return fields, missing
```

- [ ] **Step 4: Убедиться, что тесты проходят**

```bash
cd backends/python/api && python manage.py test main.tests_project_creation_defaults --settings=test_settings -v 2
```

Ожидаемо: 14 тестов PASS.

- [ ] **Step 5: Коммит**

```bash
git add backends/python/api/main/project_creation_defaults.py backends/python/api/main/tests_project_creation_defaults.py
git commit -m "feat(create-project): чистый расчёт полей карточки — пустых не остаётся"
```

---

### Task 2: Шаг «компания» — найти или создать

**Files:**
- Create: `backends/python/api/main/project_creation_service.py`
- Test: `backends/python/api/main/tests_project_creation_service.py`

**Interfaces:**
- Consumes: ничего из Task 1 (шаг компании работает до расчёта полей).
- Produces:
  - `@dataclass StepResult` с полями `status: str`, `id: Optional[str]`, `name: str`, `candidates: List[Dict[str, str]]`, `error: Optional[str]`; метод `as_dict() -> Dict[str, Any]`.
  - `class ProjectCreationService` с `__init__(self, client, account)` и методом `ensure_company(self, company_id: Optional[str], company_name: str) -> StepResult`.

Статусы шага: `"found"` (передан id или найдено ровно одно совпадение), `"created"`, `"ambiguous"` (больше одного совпадения), `"error"`.

- [ ] **Step 1: Написать падающий тест**

Создать `backends/python/api/main/tests_project_creation_service.py`:

```python
"""Тесты оркестратора создания связки «компания + группа + карточка».

Паттерн _FakeClient — как в tests_user_sync_service.py: подменяем call_method и
записываем вызовы, чтобы проверять идемпотентность без сети.
"""
from django.test import TestCase

from .models import Bitrix24Account
from .project_creation_service import ProjectCreationService


class _FakeClient:
    """Двойник Client: отдаёт ответы по имени метода, пишет журнал вызовов.

    responses — {метод: ответ} либо {метод: [ответ1, ответ2, ...]} когда метод
    вызывается несколько раз и ответы должны отличаться.
    """

    def __init__(self, responses=None):
        self._responses = dict(responses or {})
        self.calls = []
        self._bitrix_token = self

    def call_method(self, method, params=None):
        self.calls.append((method, params or {}))
        value = self._responses.get(method, {"result": []})
        if isinstance(value, list):
            if not value:
                return {"result": []}
            return value.pop(0) if len(value) > 1 else value[0]
        if isinstance(value, Exception):
            raise value
        return value

    def methods_called(self):
        return [method for method, _ in self.calls]


class _ServiceTestCase(TestCase):
    def setUp(self):
        # ProjectCardService кэширует справочники (компании, юрлица, стадии) в
        # LocMemCache по ключу аккаунта. Ключ строится из member_id, который у
        # всех тестов здесь одинаковый, — без сброса результаты первого теста
        # протекут в остальные и тесты станут зависеть от порядка запуска.
        from django.core.cache import cache
        cache.clear()

        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-create-1",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )

    def service(self, client):
        return ProjectCreationService(client, self.account)


class EnsureCompanyTest(_ServiceTestCase):
    def test_explicit_id_is_used_without_search(self):
        client = _FakeClient()
        result = self.service(client).ensure_company("15", "АО Ромашка")

        self.assertEqual(result.status, "found")
        self.assertEqual(result.id, "15")
        self.assertEqual(client.methods_called(), [])

    def test_single_match_is_reused_not_recreated(self):
        client = _FakeClient({
            "crm.company.list": {"result": [{"ID": "15", "TITLE": "АО Ромашка"}]},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка")

        self.assertEqual(result.status, "found")
        self.assertEqual(result.id, "15")
        self.assertNotIn("crm.company.add", client.methods_called())

    def test_no_match_creates_company(self):
        client = _FakeClient({
            "crm.company.list": {"result": []},
            "crm.company.add": {"result": 77},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка")

        self.assertEqual(result.status, "created")
        self.assertEqual(result.id, "77")
        method, params = client.calls[-1]
        self.assertEqual(method, "crm.company.add")
        self.assertEqual(params["fields"]["TITLE"], "АО Ромашка")

    def test_two_matches_return_ambiguous_and_create_nothing(self):
        client = _FakeClient({
            "crm.company.list": {"result": [
                {"ID": "15", "TITLE": "АО Ромашка"},
                {"ID": "16", "TITLE": "АО Ромашка"},
            ]},
        })
        result = self.service(client).ensure_company(None, "АО Ромашка")

        self.assertEqual(result.status, "ambiguous")
        self.assertIsNone(result.id)
        self.assertEqual(
            sorted(c["id"] for c in result.candidates), ["15", "16"]
        )
        self.assertNotIn("crm.company.add", client.methods_called())

    def test_bitrix_failure_becomes_error_status_not_exception(self):
        client = _FakeClient({"crm.company.list": RuntimeError("портал недоступен")})
        result = self.service(client).ensure_company(None, "АО Ромашка")

        self.assertEqual(result.status, "error")
        self.assertIn("портал недоступен", result.error)

    def test_blank_input_is_an_error(self):
        client = _FakeClient()
        result = self.service(client).ensure_company(None, "")

        self.assertEqual(result.status, "error")
        self.assertEqual(client.methods_called(), [])
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
cd backends/python/api && python manage.py test main.tests_project_creation_service --settings=test_settings -v 2
```

Ожидаемо: `ModuleNotFoundError: No module named 'main.project_creation_service'`.

- [ ] **Step 3: Написать минимальную реализацию**

Создать `backends/python/api/main/project_creation_service.py`:

```python
"""Оркестратор кнопки «Создать проект»: компания -> группа в Задачах ->
карточка смарт-процесса.

Шаги идут строго по порядку, потому что карточка ссылается на первые две
сущности. Каждый шаг идемпотентен: сначала ищет, потом создаёт, — чтобы
повторное нажатие не плодило дубли. Больше одного совпадения по названию не
разрешается автоматически: возвращается ambiguous со списком кандидатов, иначе
можно молча привязаться к чужому одноимённому проекту.
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from b24pysdk import Client

from .models import Bitrix24Account

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    status: str
    id: Optional[str] = None
    name: str = ""
    candidates: List[Dict[str, str]] = field(default_factory=list)
    error: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "id": self.id,
            "name": self.name,
            "candidates": self.candidates,
            "error": self.error,
        }


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


class ProjectCreationService:
    def __init__(self, client: Optional[Client], account: Bitrix24Account):
        self.client = client or account.client
        self.account = account

    def _call(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return self.client._bitrix_token.call_method(method, params)

    def ensure_company(self, company_id: Optional[str], company_name: str) -> StepResult:
        """Шаг 1: компания. Передан id — используем как есть, поиска не делаем."""
        company_id = _clean_str(company_id)
        company_name = _clean_str(company_name)

        if company_id:
            return StepResult(status="found", id=company_id, name=company_name)

        if not company_name:
            return StepResult(status="error", error="Не указана компания.")

        try:
            response = self._call(
                "crm.company.list",
                {"filter": {"=TITLE": company_name}, "select": ["ID", "TITLE"]},
            )
        except Exception as exc:
            logger.warning("ensure_company: crm.company.list failed: %s", exc)
            return StepResult(status="error", error=f"Не удалось найти компанию: {exc}")

        matches = [
            {"id": _clean_str(row.get("ID")), "name": _clean_str(row.get("TITLE"))}
            for row in (response.get("result") or [])
            if _clean_str(row.get("ID"))
        ]

        if len(matches) == 1:
            return StepResult(status="found", id=matches[0]["id"], name=matches[0]["name"])
        if len(matches) > 1:
            return StepResult(status="ambiguous", candidates=matches)

        try:
            created = self._call("crm.company.add", {"fields": {"TITLE": company_name}})
        except Exception as exc:
            logger.warning("ensure_company: crm.company.add failed: %s", exc)
            return StepResult(status="error", error=f"Не удалось создать компанию: {exc}")

        created_id = _clean_str(created.get("result"))
        if not created_id:
            return StepResult(status="error", error="Битрикс не вернул идентификатор компании.")

        return StepResult(status="created", id=created_id, name=company_name)
```

- [ ] **Step 4: Убедиться, что тесты проходят**

```bash
cd backends/python/api && python manage.py test main.tests_project_creation_service --settings=test_settings -v 2
```

Ожидаемо: 6 тестов PASS.

- [ ] **Step 5: Коммит**

```bash
git add backends/python/api/main/project_creation_service.py backends/python/api/main/tests_project_creation_service.py
git commit -m "feat(create-project): идемпотентный шаг создания компании"
```

---

### Task 3: Шаг «группа в Задачах» — найти или создать

**Files:**
- Modify: `backends/python/api/main/project_creation_service.py`
- Test: `backends/python/api/main/tests_project_creation_service.py`

**Interfaces:**
- Consumes: `StepResult`, `ProjectCreationService._call`, `_clean_str` из Task 2.
- Produces: `ProjectCreationService.ensure_group(self, group_name: str) -> StepResult`.

Группа создаётся под токеном текущего сотрудника — он и становится владельцем. Отдельно владельца не назначаем (см. §4 спеки).

- [ ] **Step 1: Написать падающий тест**

Дописать в `backends/python/api/main/tests_project_creation_service.py`:

```python
class EnsureGroupTest(_ServiceTestCase):
    def test_single_match_is_reused(self):
        client = _FakeClient({
            "sonet_group.get": {"result": [{"ID": "31", "NAME": "Портал АО Ромашка"}]},
        })
        result = self.service(client).ensure_group("Портал АО Ромашка")

        self.assertEqual(result.status, "found")
        self.assertEqual(result.id, "31")
        self.assertNotIn("sonet_group.create", client.methods_called())

    def test_no_match_creates_project_group(self):
        client = _FakeClient({
            "sonet_group.get": {"result": []},
            "sonet_group.create": {"result": 44},
        })
        result = self.service(client).ensure_group("Портал АО Ромашка")

        self.assertEqual(result.status, "created")
        self.assertEqual(result.id, "44")
        method, params = client.calls[-1]
        self.assertEqual(method, "sonet_group.create")
        self.assertEqual(params["NAME"], "Портал АО Ромашка")
        self.assertEqual(params["PROJECT"], "Y")
        # Владельца не назначаем: им становится создатель — текущий сотрудник.
        self.assertNotIn("OWNER_ID", params)

    def test_two_matches_return_ambiguous_and_create_nothing(self):
        client = _FakeClient({
            "sonet_group.get": {"result": [
                {"ID": "31", "NAME": "Портал АО Ромашка"},
                {"ID": "32", "NAME": "Портал АО Ромашка"},
            ]},
        })
        result = self.service(client).ensure_group("Портал АО Ромашка")

        self.assertEqual(result.status, "ambiguous")
        self.assertIsNone(result.id)
        self.assertEqual(sorted(c["id"] for c in result.candidates), ["31", "32"])
        self.assertNotIn("sonet_group.create", client.methods_called())

    def test_search_matches_by_exact_name_only(self):
        """sonet_group.get фильтрует по подстроке — одноимённый префикс не должен
        считаться совпадением, иначе привяжемся к чужому проекту."""
        client = _FakeClient({
            "sonet_group.get": {"result": [{"ID": "31", "NAME": "Портал АО Ромашка 2"}]},
            "sonet_group.create": {"result": 44},
        })
        result = self.service(client).ensure_group("Портал АО Ромашка")

        self.assertEqual(result.status, "created")
        self.assertEqual(result.id, "44")

    def test_bitrix_failure_becomes_error_status(self):
        client = _FakeClient({"sonet_group.get": RuntimeError("нет прав")})
        result = self.service(client).ensure_group("Портал АО Ромашка")

        self.assertEqual(result.status, "error")
        self.assertIn("нет прав", result.error)

    def test_blank_name_is_an_error(self):
        client = _FakeClient()
        result = self.service(client).ensure_group("  ")

        self.assertEqual(result.status, "error")
        self.assertEqual(client.methods_called(), [])
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
cd backends/python/api && python manage.py test main.tests_project_creation_service.EnsureGroupTest --settings=test_settings -v 2
```

Ожидаемо: `AttributeError: 'ProjectCreationService' object has no attribute 'ensure_group'`.

- [ ] **Step 3: Написать минимальную реализацию**

Дописать метод в класс `ProjectCreationService` в `backends/python/api/main/project_creation_service.py`:

```python
    def ensure_group(self, group_name: str) -> StepResult:
        """Шаг 2: проект/группа в Задачах.

        sonet_group.get фильтрует по подстроке, поэтому совпадением считаем
        только точное равенство имени — иначе «Портал Ромашка» подцепит
        «Портал Ромашка 2» и списания уедут в чужой проект.

        Группа создаётся под токеном текущего сотрудника, он же становится
        владельцем; отдельно владельца не назначаем и участников не добавляем.
        """
        group_name = _clean_str(group_name)
        if not group_name:
            return StepResult(status="error", error="Не указано название проекта.")

        try:
            response = self._call(
                "sonet_group.get",
                {"FILTER": {"NAME": group_name}, "SELECT": ["ID", "NAME"]},
            )
        except Exception as exc:
            logger.warning("ensure_group: sonet_group.get failed: %s", exc)
            return StepResult(status="error", error=f"Не удалось найти проект: {exc}")

        matches = [
            {"id": _clean_str(row.get("ID")), "name": _clean_str(row.get("NAME"))}
            for row in (response.get("result") or [])
            if _clean_str(row.get("ID")) and _clean_str(row.get("NAME")) == group_name
        ]

        if len(matches) == 1:
            return StepResult(status="found", id=matches[0]["id"], name=matches[0]["name"])
        if len(matches) > 1:
            return StepResult(status="ambiguous", candidates=matches)

        try:
            created = self._call(
                "sonet_group.create",
                {"NAME": group_name, "PROJECT": "Y", "VISIBLE": "Y", "OPENED": "N"},
            )
        except Exception as exc:
            logger.warning("ensure_group: sonet_group.create failed: %s", exc)
            return StepResult(status="error", error=f"Не удалось создать проект: {exc}")

        created_id = _clean_str(created.get("result"))
        if not created_id:
            return StepResult(status="error", error="Битрикс не вернул идентификатор проекта.")

        return StepResult(status="created", id=created_id, name=group_name)
```

- [ ] **Step 4: Убедиться, что тесты проходят**

```bash
cd backends/python/api && python manage.py test main.tests_project_creation_service --settings=test_settings -v 2
```

Ожидаемо: 12 тестов PASS.

- [ ] **Step 5: Коммит**

```bash
git add backends/python/api/main/project_creation_service.py backends/python/api/main/tests_project_creation_service.py
git commit -m "feat(create-project): идемпотентный шаг создания группы в Задачах"
```

---

### Task 4: Шаг «карточка смарт-процесса» + запись в локальную таблицу

**Files:**
- Modify: `backends/python/api/main/project_creation_service.py`
- Test: `backends/python/api/main/tests_project_creation_service.py`

**Interfaces:**
- Consumes: `StepResult`, `_call`, `_clean_str` (Task 2); `ResolvedProjectFields` (Task 1).
- Produces:
  - `ProjectCreationService.ensure_card(self, fields: ResolvedProjectFields, group_id: str, *, entity_type_id: int, mapping: Dict[str, Any]) -> StepResult`
  - `ProjectCreationService.write_through(self, fields: ResolvedProjectFields, group_id: str, item_id: Optional[str]) -> None`
  - `ProjectCreationService.build_card_fields(self, fields: ResolvedProjectFields, group_id: str, mapping: Dict[str, Any]) -> Dict[str, Any]`

Имена полей — только из `mapping` (ключи те же, что в `ProjectCardService._build_project_spa_update_fields`: `title`, `bitrix_group_id`, `stage_id`, `is_support`, `project_hours_budget`, `hourly_rate`, `curator_id`, `company_id`, `our_legal_entity_id`, `start_date`, `finish_date`). Незамапленные ключи молча пропускаются — портал мог их не настроить.

Write-through нужен, чтобы проект появился на доске сразу, а не через фоновый синк: иначе сотрудник решит, что не сработало, и нажмёт повторно (§7 спеки).

- [ ] **Step 1: Написать падающий тест**

Дописать в `backends/python/api/main/tests_project_creation_service.py` (импорты в начало файла: `from datetime import date`, `from .models import ProjectCard`, `from .project_creation_defaults import resolve_project_fields`):

```python
def _resolved_fields(**overrides):
    form = {
        "project_name": "Портал АО Ромашка",
        "company_id": "15",
        "company_name": "АО Ромашка",
        "project_hours_budget": "10",
    }
    form.update(overrides)
    fields, _ = resolve_project_fields(
        form,
        config={"hourly_rate": 1500},
        current_user_id="42",
        current_user_name="Петров Иван",
        today=date(2026, 7, 28),
        legal_entities=[{"id": "7", "name": "ООО Мейнсофт"}],
        stage_options=[{"id": "DT180_7:NEW", "title": "Новый"}],
    )
    return fields


_MAPPING = {
    "title": "title",
    "bitrix_group_id": "ufCrm7Group",
    "stage_id": "stageId",
    "company_id": "ufCrm7Company",
    "our_legal_entity_id": "ufCrm7Legal",
    "curator_id": "ufCrm7Curator",
    "hourly_rate": "ufCrm7Rate",
    "project_hours_budget": "ufCrm7Hours",
    "start_date": "ufCrm7Start",
    "finish_date": "ufCrm7Finish",
    "is_support": "ufCrm7Support",
}


class BuildCardFieldsTest(_ServiceTestCase):
    def test_maps_every_configured_field(self):
        service = self.service(_FakeClient())
        built = service.build_card_fields(_resolved_fields(), "44", _MAPPING)

        self.assertEqual(built["title"], "Портал АО Ромашка")
        self.assertEqual(built["ufCrm7Group"], 44)
        self.assertEqual(built["stageId"], "DT180_7:NEW")
        self.assertEqual(built["ufCrm7Company"], 15)
        self.assertEqual(built["ufCrm7Legal"], 7)
        self.assertEqual(built["ufCrm7Curator"], 42)
        self.assertEqual(built["ufCrm7Rate"], 1500.0)
        self.assertEqual(built["ufCrm7Hours"], 10.0)
        self.assertEqual(built["ufCrm7Start"], "2026-07-28")
        self.assertEqual(built["ufCrm7Finish"], "2027-07-28")
        self.assertEqual(built["ufCrm7Support"], "N")

    def test_unmapped_keys_are_skipped_not_guessed(self):
        service = self.service(_FakeClient())
        built = service.build_card_fields(_resolved_fields(), "44", {"title": "title"})

        self.assertEqual(list(built.keys()), ["title"])

    def test_empty_hours_budget_is_not_written_as_zero(self):
        service = self.service(_FakeClient())
        fields = _resolved_fields(project_hours_budget="")
        built = service.build_card_fields(fields, "44", _MAPPING)

        self.assertNotIn("ufCrm7Hours", built)


class EnsureCardTest(_ServiceTestCase):
    def test_existing_card_for_group_is_reused(self):
        client = _FakeClient({"crm.item.list": {"result": {"items": [{"id": 900}]}}})
        result = self.service(client).ensure_card(
            _resolved_fields(), "44", entity_type_id=180, mapping=_MAPPING
        )

        self.assertEqual(result.status, "found")
        self.assertEqual(result.id, "900")
        self.assertNotIn("crm.item.add", client.methods_called())

    def test_no_card_creates_one(self):
        client = _FakeClient({
            "crm.item.list": {"result": {"items": []}},
            "crm.item.add": {"result": {"item": {"id": 901}}},
        })
        result = self.service(client).ensure_card(
            _resolved_fields(), "44", entity_type_id=180, mapping=_MAPPING
        )

        self.assertEqual(result.status, "created")
        self.assertEqual(result.id, "901")

    def test_unconfigured_smart_process_is_skipped_not_crashed(self):
        client = _FakeClient()
        result = self.service(client).ensure_card(
            _resolved_fields(), "44", entity_type_id=0, mapping=_MAPPING
        )

        self.assertEqual(result.status, "skipped")
        self.assertEqual(client.methods_called(), [])

    def test_bitrix_failure_becomes_error_status(self):
        client = _FakeClient({
            "crm.item.list": {"result": {"items": []}},
            "crm.item.add": RuntimeError("поле не найдено"),
        })
        result = self.service(client).ensure_card(
            _resolved_fields(), "44", entity_type_id=180, mapping=_MAPPING
        )

        self.assertEqual(result.status, "error")
        self.assertIn("поле не найдено", result.error)


class WriteThroughTest(_ServiceTestCase):
    def test_creates_local_row_so_board_shows_project_immediately(self):
        service = self.service(_FakeClient())
        service.write_through(_resolved_fields(), "44", "901")

        card = ProjectCard.objects.get(bitrix24_account=self.account, project_id="44")
        self.assertEqual(card.project_name, "Портал АО Ромашка")
        self.assertEqual(card.project_item_id, "901")
        self.assertEqual(card.company_id, "15")
        self.assertEqual(card.our_legal_entity_id, "7")
        self.assertEqual(card.curator_user_id, "42")
        self.assertEqual(card.hourly_rate, 1500.0)
        self.assertEqual(card.project_hours_budget, 10.0)
        self.assertEqual(card.planned_budget_amount, 15000.0)
        self.assertEqual(card.project_start_date, date(2026, 7, 28))
        self.assertEqual(card.project_end_date, date(2027, 7, 28))
        self.assertEqual(card.stage, "DT180_7:NEW")
        self.assertFalse(card.is_archived)

    def test_second_call_updates_instead_of_duplicating(self):
        service = self.service(_FakeClient())
        service.write_through(_resolved_fields(), "44", "901")
        service.write_through(_resolved_fields(project_name="Переименован"), "44", "901")

        cards = ProjectCard.objects.filter(bitrix24_account=self.account, project_id="44")
        self.assertEqual(cards.count(), 1)
        self.assertEqual(cards.first().project_name, "Переименован")

    def test_other_portal_does_not_see_the_row(self):
        """Изоляция между порталами (§9 спеки): чужой аккаунт не должен видеть
        созданный проект ни при account-, ни при portal-скоупинге."""
        from .tenant_scoping import scope_to_tenant

        other = Bitrix24Account.objects.create(
            b24_user_id=2, is_b24_user_admin=True, member_id="m-create-2",
            is_master_account=True, domain_url="other.bitrix24.ru",
            status="active", application_version=1,
        )
        self.service(_FakeClient()).write_through(_resolved_fields(), "44", "901")

        visible_here = ProjectCard.objects.filter(**scope_to_tenant(self.account), project_id="44")
        visible_there = ProjectCard.objects.filter(**scope_to_tenant(other), project_id="44")
        self.assertEqual(visible_here.count(), 1)
        self.assertEqual(visible_there.count(), 0)
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
cd backends/python/api && python manage.py test main.tests_project_creation_service.EnsureCardTest --settings=test_settings -v 2
```

Ожидаемо: `AttributeError: 'ProjectCreationService' object has no attribute 'ensure_card'`.

- [ ] **Step 3: Написать минимальную реализацию**

В `backends/python/api/main/project_creation_service.py` дописать импорты в начало файла:

```python
from .models import Bitrix24Account, ProjectCard
from .project_creation_defaults import ResolvedProjectFields
from .tenant_scoping import scope_to_tenant
```

и добавить методы в класс `ProjectCreationService`:

```python
    @staticmethod
    def _to_bitrix_id(value: Any) -> Any:
        """Битрикс ждёт числовые id числами; нечисловое отдаём как есть."""
        text = _clean_str(value)
        return int(text) if text.isdigit() else (text or None)

    def build_card_fields(
        self, fields: ResolvedProjectFields, group_id: str, mapping: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Собирает поля crm.item.add по маппингу портала.

        Ключи те же, что у ProjectCardService._build_project_spa_update_fields —
        маппинг общий. Незамапленное и пустое не пишем: на разных порталах набор
        настроенных полей разный, а пустое значение затрёт то, что уже есть.
        """
        values = {
            "title": fields.project_name,
            "bitrix_group_id": self._to_bitrix_id(group_id),
            "stage_id": fields.stage,
            "company_id": self._to_bitrix_id(fields.company_id),
            "our_legal_entity_id": self._to_bitrix_id(fields.our_legal_entity_id),
            "curator_id": self._to_bitrix_id(fields.curator_user_id),
            "hourly_rate": fields.hourly_rate,
            "project_hours_budget": fields.project_hours_budget,
            "start_date": fields.project_start_date.isoformat() if fields.project_start_date else None,
            "finish_date": fields.project_end_date.isoformat() if fields.project_end_date else None,
            "is_support": "Y" if fields.is_support else "N",
        }

        built: Dict[str, Any] = {}
        for mapping_key, value in values.items():
            field_code = _clean_str((mapping or {}).get(mapping_key))
            if not field_code or value in (None, ""):
                continue
            built[field_code] = value
        return built

    def ensure_card(
        self,
        fields: ResolvedProjectFields,
        group_id: str,
        *,
        entity_type_id: int,
        mapping: Dict[str, Any],
    ) -> StepResult:
        """Шаг 3: карточка смарт-процесса, связанная с группой."""
        if not entity_type_id or not mapping:
            return StepResult(
                status="skipped",
                error="Смарт-процесс проектов не настроен — карточка не создана.",
            )

        group_field = _clean_str((mapping or {}).get("bitrix_group_id"))
        if group_field:
            try:
                response = self._call(
                    "crm.item.list",
                    {
                        "entityTypeId": entity_type_id,
                        "filter": {group_field: self._to_bitrix_id(group_id)},
                        "select": ["id"],
                    },
                )
            except Exception as exc:
                logger.warning("ensure_card: crm.item.list failed: %s", exc)
                return StepResult(status="error", error=f"Не удалось найти карточку: {exc}")

            existing = self._extract_items(response)
            if existing:
                return StepResult(
                    status="found",
                    id=_clean_str(existing[0].get("id") or existing[0].get("ID")),
                    name=fields.project_name,
                )

        try:
            created = self._call(
                "crm.item.add",
                {
                    "entityTypeId": entity_type_id,
                    "fields": self.build_card_fields(fields, group_id, mapping),
                },
            )
        except Exception as exc:
            logger.warning("ensure_card: crm.item.add failed: %s", exc)
            return StepResult(status="error", error=f"Не удалось создать карточку: {exc}")

        result = created.get("result") or {}
        item = result.get("item") if isinstance(result, dict) else None
        created_id = _clean_str((item or {}).get("id") if isinstance(item, dict) else result)
        if not created_id:
            return StepResult(status="error", error="Битрикс не вернул идентификатор карточки.")

        return StepResult(status="created", id=created_id, name=fields.project_name)

    @staticmethod
    def _extract_items(response: Dict[str, Any]) -> List[Dict[str, Any]]:
        result = response.get("result") or {}
        if isinstance(result, dict):
            items = result.get("items") or result.get("item") or []
        else:
            items = result
        if isinstance(items, dict):
            items = [items]
        return [row for row in items if isinstance(row, dict)]

    def write_through(
        self, fields: ResolvedProjectFields, group_id: str, item_id: Optional[str]
    ) -> None:
        """Пишет карточку в локальную таблицу сразу после создания в Битриксе,
        чтобы проект появился на доске немедленно, а не через фоновый синк:
        иначе сотрудник решит, что не сработало, и нажмёт повторно."""
        defaults = {
            "project_name": fields.project_name,
            "stage": fields.stage,
            "project_item_id": _clean_str(item_id) or None,
            "project_hours_budget": fields.project_hours_budget,
            "hourly_rate": fields.hourly_rate,
            "planned_budget_amount": fields.planned_budget_amount,
            "is_support": fields.is_support,
            "project_type": fields.project_type,
            "budget_mode": fields.budget_mode,
            "curator_user_id": fields.curator_user_id,
            "curator_name": fields.curator_name,
            "project_start_date": fields.project_start_date,
            "project_end_date": fields.project_end_date,
            "company_id": fields.company_id,
            "company_name": fields.company_name,
            "our_legal_entity_id": fields.our_legal_entity_id,
            "our_legal_entity_name": fields.our_legal_entity_name,
            "is_archived": False,
            "stage_source": "manual",
        }
        ProjectCard.objects.update_or_create(
            **scope_to_tenant(self.account, write=True),
            project_id=_clean_str(group_id),
            defaults=defaults,
        )
```

`scope_to_tenant` возвращает **kwargs для фильтра/создания**, а не вызываемый объект: при `write=True` и включённом `USE_PORTAL_SCOPING` (на проде он включён) это `{"portal": ..., "bitrix24_account": ...}`. Двойная запись обязательна — без `portal` строка не попадёт в скоуп компании и доска её не покажет.

- [ ] **Step 4: Убедиться, что тесты проходят**

```bash
cd backends/python/api && python manage.py test main.tests_project_creation_service --settings=test_settings -v 2
```

Ожидаемо: 22 теста PASS.

- [ ] **Step 5: Коммит**

```bash
git add backends/python/api/main/project_creation_service.py backends/python/api/main/tests_project_creation_service.py
git commit -m "feat(create-project): карточка смарт-процесса + write-through в project_card"
```

---

### Task 5: Оркестратор — три шага и сборка ответа

**Files:**
- Modify: `backends/python/api/main/project_creation_service.py`
- Test: `backends/python/api/main/tests_project_creation_service.py`

**Interfaces:**
- Consumes: `ensure_company`, `ensure_group`, `ensure_card`, `write_through`, `build_card_fields` (Tasks 2-4); `resolve_project_fields` (Task 1).
- Produces: `ProjectCreationService.create(self, form: Dict[str, Any], *, current_user_id: str, current_user_name: str, today: Optional[date] = None) -> Dict[str, Any]`

Формат ответа (§4 спеки):

```json
{
  "company": {"status": "created|found|ambiguous|error", "id": "123", "name": "", "candidates": [], "error": null},
  "group":   {"status": "created|found|ambiguous|error", "id": "45",  "name": "", "candidates": [], "error": null},
  "card":    {"status": "created|found|skipped|error",   "id": "678", "name": "", "candidates": [], "error": null},
  "done": false,
  "missing_fields": []
}
```

`done` — истина, когда компания и группа получили id, а карточка не в `error`. `skipped` у карточки означает, что предыдущий шаг не дал нужного идентификатора либо смарт-процесс не настроен.

- [ ] **Step 1: Написать падающий тест**

Дописать в `backends/python/api/main/tests_project_creation_service.py`:

```python
class CreateOrchestrationTest(_ServiceTestCase):
    def _client(self, **overrides):
        responses = {
            "app.option.get": {"result": {"timestamp_config": (
                '{"hourly_rate": 1500, "project_sp_entity_type_id": 180,'
                ' "project_fields_mapping": {"title": "title",'
                ' "bitrix_group_id": "ufCrm7Group", "stage_id": "stageId"}}'
            )}},
            "crm.company.list": {"result": []},
            "crm.company.add": {"result": 77},
            "sonet_group.get": {"result": []},
            "sonet_group.create": {"result": 44},
            "crm.item.list": {"result": {"items": []}},
            "crm.item.add": {"result": {"item": {"id": 901}}},
        }
        responses.update(overrides)
        return _FakeClient(responses)

    def _form(self, **overrides):
        form = {"project_name": "Портал АО Ромашка", "company_name": "АО Ромашка"}
        form.update(overrides)
        return form

    def _create(self, client, form=None):
        return self.service(client).create(
            form or self._form(), current_user_id="42", current_user_name="Петров Иван",
            today=date(2026, 7, 28),
        )

    def test_happy_path_creates_all_three(self):
        result = self._create(self._client())

        self.assertEqual(result["company"]["status"], "created")
        self.assertEqual(result["group"]["status"], "created")
        self.assertEqual(result["card"]["status"], "created")
        self.assertTrue(result["done"])
        self.assertEqual(ProjectCard.objects.filter(project_id="44").count(), 1)

    def test_repeat_call_does_not_create_second_entities(self):
        client = self._client(
            **{
                "crm.company.list": {"result": [{"ID": "77", "TITLE": "АО Ромашка"}]},
                "sonet_group.get": {"result": [{"ID": "44", "NAME": "Портал АО Ромашка"}]},
                "crm.item.list": {"result": {"items": [{"id": 901}]}},
            }
        )
        result = self._create(client)

        self.assertEqual(result["company"]["status"], "found")
        self.assertEqual(result["group"]["status"], "found")
        self.assertEqual(result["card"]["status"], "found")
        self.assertTrue(result["done"])
        for method in ("crm.company.add", "sonet_group.create", "crm.item.add"):
            self.assertNotIn(method, client.methods_called())

    def test_group_failure_keeps_company_and_skips_card(self):
        client = self._client(**{"sonet_group.create": RuntimeError("нет прав на создание групп")})
        result = self._create(client)

        self.assertEqual(result["company"]["status"], "created")
        self.assertEqual(result["group"]["status"], "error")
        self.assertEqual(result["card"]["status"], "skipped")
        self.assertFalse(result["done"])
        self.assertNotIn("crm.item.add", client.methods_called())

    def test_ambiguous_company_stops_before_group(self):
        client = self._client(
            **{"crm.company.list": {"result": [
                {"ID": "77", "TITLE": "АО Ромашка"},
                {"ID": "78", "TITLE": "АО Ромашка"},
            ]}}
        )
        result = self._create(client)

        self.assertEqual(result["company"]["status"], "ambiguous")
        self.assertEqual(result["group"]["status"], "skipped")
        self.assertEqual(result["card"]["status"], "skipped")
        self.assertFalse(result["done"])
        self.assertNotIn("sonet_group.create", client.methods_called())

    def test_missing_required_fields_stop_before_any_bitrix_call(self):
        client = self._client()
        result = self._create(client, form={"company_name": "АО Ромашка"})

        self.assertIn("project_name", result["missing_fields"])
        self.assertFalse(result["done"])
        self.assertNotIn("crm.company.add", client.methods_called())

    def test_card_error_still_reports_created_company_and_group(self):
        client = self._client(**{"crm.item.add": RuntimeError("поле не найдено")})
        result = self._create(client)

        self.assertEqual(result["company"]["status"], "created")
        self.assertEqual(result["group"]["status"], "created")
        self.assertEqual(result["card"]["status"], "error")
        self.assertFalse(result["done"])
        # Группа создана — локальную строку всё равно пишем, иначе доска её не покажет.
        self.assertEqual(ProjectCard.objects.filter(project_id="44").count(), 1)
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
cd backends/python/api && python manage.py test main.tests_project_creation_service.CreateOrchestrationTest --settings=test_settings -v 2
```

Ожидаемо: `AttributeError: 'ProjectCreationService' object has no attribute 'create'`.

- [ ] **Step 3: Написать минимальную реализацию**

Дописать импорты в `backends/python/api/main/project_creation_service.py`:

```python
from datetime import date

from django.utils import timezone

from .configuration_service import ConfigurationService
from .project_board_service import ProjectCardService
from .project_creation_defaults import resolve_project_fields
```

и добавить метод в класс:

```python
    def create(
        self,
        form: Dict[str, Any],
        *,
        current_user_id: str,
        current_user_name: str,
        today: Optional[date] = None,
    ) -> Dict[str, Any]:
        """Три шага строго по порядку: карточка ссылается на компанию и группу.

        Сбой шага не откатывает уже созданное — возвращаем частичный результат,
        повторный вызов досоздаёт недостающее (каждый шаг идемпотентен).
        """
        today = today or timezone.localdate()
        config_service = ConfigurationService(self.client, self.account)
        config = config_service.get_configuration_sync()

        card_service = ProjectCardService(self.client, self.account)
        try:
            legal_entities = card_service.get_legal_entities(config)
        except Exception as exc:
            logger.warning("create: get_legal_entities failed: %s", exc)
            legal_entities = []
        try:
            stage_options = card_service.get_project_stage_options(config)
        except Exception as exc:
            logger.warning("create: get_project_stage_options failed: %s", exc)
            stage_options = []

        fields, missing = resolve_project_fields(
            form,
            config=config,
            current_user_id=current_user_id,
            current_user_name=current_user_name,
            today=today,
            legal_entities=legal_entities,
            stage_options=stage_options,
        )

        skipped = StepResult(status="skipped")
        if missing:
            return {
                "company": skipped.as_dict(),
                "group": skipped.as_dict(),
                "card": skipped.as_dict(),
                "done": False,
                "missing_fields": missing,
            }

        company = self.ensure_company(fields.company_id, fields.company_name)
        if not company.id:
            return {
                "company": company.as_dict(),
                "group": skipped.as_dict(),
                "card": skipped.as_dict(),
                "done": False,
                "missing_fields": [],
            }
        fields.company_id = company.id
        fields.company_name = fields.company_name or company.name

        group = self.ensure_group(fields.project_name)
        if not group.id:
            return {
                "company": company.as_dict(),
                "group": group.as_dict(),
                "card": skipped.as_dict(),
                "done": False,
                "missing_fields": [],
            }

        try:
            entity_type_id = int(config.get("project_sp_entity_type_id") or 0)
        except (TypeError, ValueError):
            entity_type_id = 0
        mapping = config.get("project_fields_mapping") or {}

        card = self.ensure_card(
            fields, group.id, entity_type_id=entity_type_id, mapping=mapping
        )

        try:
            self.write_through(fields, group.id, card.id)
        except Exception as exc:
            logger.warning("create: write_through failed for group %s: %s", group.id, exc)

        return {
            "company": company.as_dict(),
            "group": group.as_dict(),
            "card": card.as_dict(),
            "done": card.status != "error",
            "missing_fields": [],
        }
```

- [ ] **Step 4: Убедиться, что тесты проходят**

```bash
cd backends/python/api && python manage.py test main.tests_project_creation_service main.tests_project_creation_defaults --settings=test_settings -v 2
```

Ожидаемо: 42 теста PASS (28 в оркестраторе + 14 в расчёте полей).

- [ ] **Step 5: Коммит**

```bash
git add backends/python/api/main/project_creation_service.py backends/python/api/main/tests_project_creation_service.py
git commit -m "feat(create-project): оркестратор трёх шагов с частичным результатом"
```

---

### Task 6: HTTP-эндпоинт

**Files:**
- Modify: `backends/python/api/main/views.py`
- Modify: `backends/python/api/main/urls.py`
- Test: `backends/python/api/main/tests_project_creation_service.py`

**Interfaces:**
- Consumes: `ProjectCreationService.create` (Task 5).
- Produces: `POST /api/project-board/create` → JSON из Task 5.

Эндпоинт повторяет паттерн соседей (`update_project_board`): декораторы `@xframe_options_exempt`, `@csrf_exempt`, `@require_POST`, `@log_errors(...)`, `@auth_required`, тело через `_load_request_json`. Добавляется `@rate_limit("create-project", 10, 60, key="account")` — создание сущностей на портале дороже чтения.

- [ ] **Step 1: Написать падающий тест**

Дописать в `backends/python/api/main/tests_project_creation_service.py`:

```python
class CreateEndpointRoutingTest(_ServiceTestCase):
    def test_route_is_registered(self):
        from django.urls import reverse
        self.assertEqual(reverse("create_project_board"), "/api/project-board/create")

    def test_view_rejects_get(self):
        from django.test import Client as HttpClient
        response = HttpClient().get("/api/project-board/create")
        self.assertEqual(response.status_code, 405)
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
cd backends/python/api && python manage.py test main.tests_project_creation_service.CreateEndpointRoutingTest --settings=test_settings -v 2
```

Ожидаемо: `NoReverseMatch: Reverse for 'create_project_board' not found`.

- [ ] **Step 3: Написать минимальную реализацию**

В `backends/python/api/main/views.py` рядом с `update_project_board` добавить импорт `from .project_creation_service import ProjectCreationService` (в блок импортов сервисов) и view:

```python
@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("create_project_board")
@auth_required
@rate_limit("create-project", 10, 60, key="account")
def create_project_board(request: AuthorizedRequest):
    """Создаёт связку «компания + группа в Задачах + карточка смарт-процесса».

    Шаги идемпотентны, поэтому повтор того же запроса досоздаёт только
    недостающее — фронт этим и пользуется в кнопке «Повторить».
    """
    payload = _load_request_json(request)
    account = request.bitrix24_account

    service = ProjectCreationService(account.client, account)
    result = service.create(
        payload,
        current_user_id=str(account.b24_user_id or ""),
        current_user_name=_current_user_display_name(request),
    )
    return JsonResponse(result)
```

и вспомогательную функцию рядом с `_get_user_map`:

```python
def _current_user_display_name(request: AuthorizedRequest) -> str:
    """Имя текущего сотрудника для поля «куратор». Берём из локального
    справочника (PortalUser) — он же питает user_map отчётов; если сотрудника
    там ещё нет, куратор останется с пустым именем, но с корректным id."""
    account = request.bitrix24_account
    row = PortalUser.objects.filter(
        **scope_to_tenant(account),
        bitrix_id=str(account.b24_user_id or ""),
    ).values("name", "last_name").first()
    if not row:
        return ""
    return f"{row['last_name']} {row['name']}".strip()
```

В `backends/python/api/main/urls.py` добавить маршрут рядом с `api/project-board/update`:

```python
    path('api/project-board/create', views.create_project_board, name='create_project_board'),
```

- [ ] **Step 4: Убедиться, что тесты проходят**

```bash
cd backends/python/api && python manage.py test main.tests_project_creation_service main.tests_project_creation_defaults --settings=test_settings -v 2
```

Ожидаемо: 44 теста PASS (30 в оркестраторе + 14 в расчёте полей).

- [ ] **Step 5: Коммит**

```bash
git add backends/python/api/main/views.py backends/python/api/main/urls.py backends/python/api/main/tests_project_creation_service.py
git commit -m "feat(create-project): эндпоинт POST /api/project-board/create"
```

---

### Task 7: Фронт — типы и метод стора

**Files:**
- Create: `frontend/app/types/project-creation.ts`
- Modify: `frontend/app/stores/api.ts`
- Test: `frontend/tests/projectCreation.test.ts`

**Interfaces:**
- Consumes: формат ответа из Task 5.
- Produces:
  - `interface ProjectCreationStep { status: 'created' | 'found' | 'ambiguous' | 'skipped' | 'error'; id: string | null; name: string; candidates: Array<{ id: string; name: string }>; error: string | null }`
  - `interface ProjectCreationResult { company: ProjectCreationStep; group: ProjectCreationStep; card: ProjectCreationStep; done: boolean; missing_fields: string[] }`
  - `interface ProjectCreationForm { project_name: string; company_id: string | null; company_name: string; our_legal_entity_id: string | null; project_start_date: string; project_end_date: string; project_hours_budget: string; hourly_rate: string; project_type: string; is_support: boolean }`
  - `useApiStore().createProject(form: ProjectCreationForm): Promise<ProjectCreationResult>`
  - `addOneYear(iso: string): string` (экспорт из `frontend/app/types/project-creation.ts`) — тот же календарный край, что на бэкенде.

- [ ] **Step 1: Написать падающий тест**

Создать `frontend/tests/projectCreation.test.ts`:

```typescript
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { addOneYear, plannedAmount } from '../app/types/project-creation'

test('addOneYear: обычная дата', () => {
  assert.equal(addOneYear('2026-07-28'), '2027-07-28')
})

test('addOneYear: 29 февраля переносится на 28-е', () => {
  assert.equal(addOneYear('2028-02-29'), '2029-02-28')
})

test('addOneYear: пустая строка не ломается', () => {
  assert.equal(addOneYear(''), '')
})

test('plannedAmount: часы × ставка', () => {
  assert.equal(plannedAmount('10', '1500'), 15000)
})

test('plannedAmount: без часов — null, а не ноль', () => {
  assert.equal(plannedAmount('', '1500'), null)
})

test('plannedAmount: запятая как десятичный разделитель', () => {
  assert.equal(plannedAmount('1,5', '1000'), 1500)
})
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
cd frontend && corepack pnpm@9.15.9 dlx tsx --test 'tests/projectCreation.test.ts'
```

Ожидаемо: `Cannot find module '../app/types/project-creation'`.

- [ ] **Step 3: Написать минимальную реализацию**

Создать `frontend/app/types/project-creation.ts`:

```typescript
export interface ProjectCreationStep {
  status: 'created' | 'found' | 'ambiguous' | 'skipped' | 'error'
  id: string | null
  name: string
  candidates: Array<{ id: string; name: string }>
  error: string | null
}

export interface ProjectCreationResult {
  company: ProjectCreationStep
  group: ProjectCreationStep
  card: ProjectCreationStep
  done: boolean
  missing_fields: string[]
}

export interface ProjectCreationForm {
  project_name: string
  company_id: string | null
  company_name: string
  our_legal_entity_id: string | null
  project_start_date: string
  project_end_date: string
  project_hours_budget: string
  hourly_rate: string
  project_type: string
  is_support: boolean
}

/**
 * Дата + 1 год. 29 февраля переносится на 28-е — в невисокосном году такой
 * даты нет. Те же правила считает бэкенд (project_creation_defaults.add_one_year):
 * форма лишь показывает результат заранее, доверять ей нельзя.
 */
export function addOneYear(iso: string): string {
  if (!iso) return ''
  const [year, month, day] = iso.slice(0, 10).split('-').map(Number)
  if (!year || !month || !day) return ''
  const nextYear = year + 1
  const daysInMonth = new Date(Date.UTC(nextYear, month, 0)).getUTCDate()
  const safeDay = Math.min(day, daysInMonth)
  return `${nextYear}-${String(month).padStart(2, '0')}-${String(safeDay).padStart(2, '0')}`
}

/** Плановая сумма = часы × ставка. Без часов — null, а не ноль: пустой бюджет
 * это «неизвестно», и ноль в отчёте прочитали бы как факт. */
export function plannedAmount(hours: string, rate: string): number | null {
  const parsedHours = parseFloat(String(hours ?? '').replace(',', '.'))
  const parsedRate = parseFloat(String(rate ?? '').replace(',', '.'))
  if (!Number.isFinite(parsedHours)) return null
  if (!Number.isFinite(parsedRate)) return null
  return Math.round(parsedHours * parsedRate * 100) / 100
}
```

В `frontend/app/stores/api.ts` добавить импорт типов рядом с существующим импортом `~/types/project-board`:

```typescript
import type { ProjectCreationForm, ProjectCreationResult } from '~/types/project-creation'
```

и метод рядом с `updateProjectBoard` (сохраняя стиль соседей — сброс кэша после записи):

```typescript
    async createProject(form: ProjectCreationForm): Promise<ProjectCreationResult> {
      const result = await $api<ProjectCreationResult>('/api/project-board/create', {
        method: 'POST',
        body: form
      })
      clearCache('project-board', 'project-board-meta', 'homepage-portfolio', 'filter-projects')
      return result
    },
```

- [ ] **Step 4: Убедиться, что тесты проходят**

```bash
cd frontend && corepack pnpm@9.15.9 dlx tsx --test 'tests/projectCreation.test.ts'
```

Ожидаемо: 6 тестов PASS.

- [ ] **Step 5: Коммит**

```bash
git add frontend/app/types/project-creation.ts frontend/app/stores/api.ts frontend/tests/projectCreation.test.ts
git commit -m "feat(create-project): типы и метод стора createProject"
```

---

### Task 8: Фронт — модальное окно с формой

**Files:**
- Create: `frontend/app/components/projects/CreateProjectModal.vue`
- Test: `frontend/tests/projectCreation.test.ts` (дополнить)

**Interfaces:**
- Consumes: `useApiStore().createProject`, `addOneYear`, `plannedAmount`, типы (Task 7); `getProjectBoardMeta()` для списков компаний, юрлиц и ставки.
- Produces:
  - компонент `<CreateProjectModal v-model:open="..." @created="(result: ProjectCreationResult) => void" />`
  - `frontend/app/utils/projectCreationLabels.ts` → `export function stepLabel(step: ProjectCreationStep): string`

Состав формы — §5 спеки. Обязательны: название, компания и (только если своих юрлиц несколько) юрлицо. Остальное предзаполнено и видно сотруднику.

`stepLabel` живёт в `utils`, а не в SFC: `node:test` через `tsx` не резолвит `.vue`, да и чистой функции в компоненте не место.

- [ ] **Step 1: Написать падающий тест**

Дописать в `frontend/tests/projectCreation.test.ts`:

```typescript
import { stepLabel } from '../app/utils/projectCreationLabels'

test('stepLabel: каждый статус имеет человеческий текст', () => {
  const make = (status: string) => ({ status, id: null, name: '', candidates: [], error: null }) as never
  assert.equal(stepLabel(make('created')), '✓ создано')
  assert.equal(stepLabel(make('found')), '✓ найдено')
  assert.equal(stepLabel(make('skipped')), '— пропущено')
  assert.equal(stepLabel(make('ambiguous')), '⚠ уточните')
  assert.equal(stepLabel(make('error')), '✗ ошибка')
})

test('stepLabel: неизвестный статус не роняет интерфейс', () => {
  assert.equal(stepLabel({ status: 'xxx' } as never), '— пропущено')
})
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
cd frontend && corepack pnpm@9.15.9 dlx tsx --test 'tests/projectCreation.test.ts'
```

Ожидаемо: ошибка резолва модуля.

- [ ] **Step 3: Написать минимальную реализацию**

Создать `frontend/app/utils/projectCreationLabels.ts`:

```typescript
import type { ProjectCreationStep } from '~/types/project-creation'

const LABELS: Record<ProjectCreationStep['status'], string> = {
  created: '✓ создано',
  found: '✓ найдено',
  skipped: '— пропущено',
  ambiguous: '⚠ уточните',
  error: '✗ ошибка'
}

export function stepLabel(step: ProjectCreationStep): string {
  return LABELS[step?.status] ?? '— пропущено'
}
```

Создать `frontend/app/components/projects/CreateProjectModal.vue`.

`<script setup lang="ts">` — вся логика формы:

```typescript
import { computed, ref, watch } from 'vue'
import { useApiStore } from '~/stores/api'
import { stepLabel } from '~/utils/projectCreationLabels'
import { addOneYear, plannedAmount } from '~/types/project-creation'
import type { ProjectCreationForm, ProjectCreationResult } from '~/types/project-creation'
import type { ProjectBoardDirectoryOption } from '~/types/project-board'

const open = defineModel<boolean>('open', { required: true })
const emit = defineEmits<{ created: [result: ProjectCreationResult] }>()

const apiStore = useApiStore()

const companies = ref<ProjectBoardDirectoryOption[]>([])
const legalEntities = ref<ProjectBoardDirectoryOption[]>([])
const submitting = ref(false)
const result = ref<ProjectCreationResult | null>(null)
const loadError = ref('')

const today = new Date().toISOString().slice(0, 10)
const form = ref<ProjectCreationForm>({
  project_name: '',
  company_id: null,
  company_name: '',
  our_legal_entity_id: null,
  project_start_date: today,
  project_end_date: addOneYear(today),
  project_hours_budget: '',
  hourly_rate: '',
  project_type: 'delivery',
  is_support: false
})

// Ручная правка даты окончания не должна затираться пересчётом от даты начала.
const endDateTouched = ref(false)
watch(() => form.value.project_start_date, (start) => {
  if (!endDateTouched.value) form.value.project_end_date = addOneYear(start)
})

const amount = computed(() => plannedAmount(form.value.project_hours_budget, form.value.hourly_rate))

// Юрлицо спрашиваем, только когда своих компаний в CRM больше одной;
// единственную подставляем молча (§5 спеки).
const needsLegalEntityChoice = computed(() => legalEntities.value.length > 1)

const missing = computed(() => result.value?.missing_fields ?? [])
const canSubmit = computed(() =>
  Boolean(form.value.project_name.trim())
  && Boolean(form.value.company_id || form.value.company_name.trim())
  && (!needsLegalEntityChoice.value || Boolean(form.value.our_legal_entity_id))
  && Boolean(form.value.hourly_rate.trim())
)

async function loadReferences() {
  loadError.value = ''
  try {
    const meta = await apiStore.getProjectBoardMeta()
    companies.value = meta.directories?.companies ?? meta.companies ?? meta.filters?.companies ?? []
    legalEntities.value = meta.directories?.legal_entities ?? meta.legal_entities ?? meta.filters?.legal_entities ?? []
    if (legalEntities.value.length === 1) {
      form.value.our_legal_entity_id = String(legalEntities.value[0]!.id)
    }
    const config = await apiStore.getConfiguration()
    const rate = Number(config?.hourly_rate ?? 0)
    if (rate > 0) form.value.hourly_rate = String(rate)
  } catch (error) {
    // Справочники не догрузились — форму всё равно показываем: названия
    // компании и проекта можно ввести руками, бэкенд их найдёт или создаст.
    loadError.value = 'Не удалось загрузить справочники. Заполните поля вручную.'
    console.error('CreateProjectModal: failed to load references', error)
  }
}

watch(open, (isOpen) => { if (isOpen) loadReferences() }, { immediate: true })

async function submit() {
  submitting.value = true
  loadError.value = ''
  try {
    result.value = await apiStore.createProject(form.value)
    if (result.value.done) emit('created', result.value)
  } catch (error) {
    // Экран не роняем — тот же принцип, что у /api/users в useTaskTreeLoader.
    loadError.value = error instanceof Error ? error.message : 'Не удалось создать проект.'
    console.error('CreateProjectModal: create failed', error)
  } finally {
    submitting.value = false
  }
}

/** Повтор отправляет ту же форму: шаги идемпотентны, досоздаётся недостающее. */
function retry() { return submit() }

function chooseCandidate(step: 'company', id: string) {
  if (step === 'company') form.value.company_id = id
  return submit()
}
</script>
```

Требования к разметке (используй компоненты `@bitrix24/b24ui-nuxt` с префиксом `B24`, как в соседних файлах `frontend/app/components/projects/`):

- `B24Modal` с заголовком «Создать проект».
- Поля в порядке §5: название (обязательное), компания (`B24Select` из `meta.companies` + возможность ввести новое название), наше юрлицо (показывать `B24Select` только когда в `meta.legal_entities` больше одного, иначе скрытое предзаполненное значение), куратор (предзаполнен текущим сотрудником), дата начала (по умолчанию сегодня), дата окончания (по умолчанию `addOneYear(project_start_date)`, пересчитывается при смене начала, но не затирает ручную правку — держи флаг `endDateTouched`), бюджет часов (необязательное), ставка (предзаполнена из `meta.hourly_rate`, обязательна только если та пустая), плановая сумма (только для чтения, `plannedAmount(hours, rate)`), тип проекта (`B24Select`, по умолчанию «Поставка»), признак поддержки (`B24Switch`, выключен).
- Кнопка «Создать» отключена, пока не заполнены обязательные поля.
- После отправки — три строки статуса вида «Компания ✓ создано · Проект ✓ создано · Карточка ✗ ошибка» через `stepLabel`, тексты ошибок показываются под строкой.
- При `status === 'ambiguous'` — `B24Select` из `candidates` и кнопка «Повторить», отправляющая ту же форму с выбранным `company_id`.
- При любой ошибке — кнопка «Повторить», отправляющая тот же запрос без изменений.
- `missing_fields` из ответа подсвечивают соответствующие поля.
- Ошибка запроса ловится `try/catch` и показывается текстом в модалке; экран не роняем (как `/api/users` в `useTaskTreeLoader`).
- При `done === true` — `emit('created', result)` и ссылки на созданные сущности.

- [ ] **Step 4: Убедиться, что тесты проходят и сборка цела**

```bash
cd frontend && corepack pnpm@9.15.9 dlx tsx --test 'tests/**/*.test.ts' && NODE_OPTIONS="--max-old-space-size=4096" corepack pnpm@9.15.9 run build
```

Ожидаемо: все тесты PASS, сборка завершается «Build complete!».

- [ ] **Step 5: Коммит**

```bash
git add frontend/app/components/projects/CreateProjectModal.vue frontend/app/utils/projectCreationLabels.ts frontend/tests/projectCreation.test.ts
git commit -m "feat(create-project): модальное окно создания проекта"
```

---

### Task 9: Кнопки на доске проектов и на главном экране

**Files:**
- Modify: `frontend/app/pages/projects/index.client.vue`
- Modify: `frontend/app/pages/index.client.vue`

**Interfaces:**
- Consumes: `<CreateProjectModal>` (Task 8).
- Produces: ничего для последующих задач — это последняя.

Компонент один и тот же на обоих экранах (§3 спеки: «Доска проектов и главный экран, форма общая»).

- [ ] **Step 1: Добавить кнопку на доску проектов**

В `frontend/app/pages/projects/index.client.vue` в панель действий рядом с существующими кнопками добавить:

```vue
<B24Button color="primary" @click="createProjectOpen = true">
  Создать проект
</B24Button>
<CreateProjectModal v-model:open="createProjectOpen" @created="onProjectCreated" />
```

и в `<script setup>`:

```ts
const createProjectOpen = ref(false)

async function onProjectCreated() {
  // Локальная строка уже записана write-through'ом на бэкенде,
  // поэтому доске достаточно перечитать себя — фоновый синк ждать не нужно.
  await loadBoard(true)
}
```

`loadBoard(forceRefresh = false)` уже определена в этом файле (`frontend/app/pages/projects/index.client.vue:344`); `true` нужен, чтобы обойти браузерный кэш доски, который `createProject` сбрасывает только на своей стороне.

- [ ] **Step 2: Проверить, что доска собирается и кнопка на месте**

```bash
cd frontend && NODE_OPTIONS="--max-old-space-size=4096" corepack pnpm@9.15.9 run build
```

Ожидаемо: «Build complete!» без ошибок компиляции шаблона.

- [ ] **Step 3: Добавить кнопку на главный экран**

В `frontend/app/pages/index.client.vue` добавить ту же пару (`B24Button` + `CreateProjectModal`) в блок быстрых действий. Обработчик перечитывает портфель:

```ts
const createProjectOpen = ref(false)

async function onProjectCreated() {
  await loadPortfolio(true)
}
```

`loadPortfolio(forceRefresh = false)` уже определена в этом файле (`frontend/app/pages/index.client.vue:290`).

- [ ] **Step 4: Прогнать всё целиком**

```bash
cd frontend && corepack pnpm@9.15.9 dlx tsx --test 'tests/**/*.test.ts' && NODE_OPTIONS="--max-old-space-size=4096" corepack pnpm@9.15.9 run build
```

и бэкенд на прод-стеке:

```bash
cd backends/python && docker run --rm -v "$PWD":/app -w /app python:3.11-slim bash -c 'pip install -q -r api/requirements.txt && cd api && python manage.py test main.tests_project_creation_defaults main.tests_project_creation_service --settings=test_settings -v 2'
```

Ожидаемо: фронт — все тесты PASS и «Build complete!»; бэкенд — 44 теста PASS на Python 3.11 / Django 5.2.

- [ ] **Step 5: Коммит**

```bash
git add frontend/app/pages/projects/index.client.vue frontend/app/pages/index.client.vue
git commit -m "feat(create-project): кнопка на доске проектов и на главном экране"
```

---

## Проверка перед мержем

Прогнать весь бэкенд, а не только новые модули, — новый view трогает общий `views.py`:

```bash
cd backends/python && docker run --rm -v "$PWD":/app -w /app python:3.11-slim bash -c 'pip install -q -r api/requirements.txt && cd api && python manage.py test $(cd main && ls tests_*.py | sed "s/\.py$//" | grep -vE "^(tests_inn_apply_batch|tests_project_fetch_keyset|tests_fetch_paginated_batch|tests_sync_scoped)$" | sed "s/^/main./" | tr "\n" " ") --settings=test_settings'
```

Ожидаемо: ~334 теста PASS (290 существующих + 44 новых), миграций не появилось (`ProjectCard` не менялся).
