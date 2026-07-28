# Вариант Б: справочники из локальной базы — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Убрать обход всего справочника компаний портала (23 252 записи, 465 последовательных страниц) со всех путей, которыми ходят пользователи. Экран проектов, главный экран и карточка проекта перестают ждать Битрикс за справочниками.

**Architecture:** Компании для выпадающих списков берутся из локальной базы — из тех, что уже указаны в карточках проектов. Компании, которых там ещё нет, ищутся отдельным эндпоинтом по мере ввода: один запрос к Битриксу с фильтром вместо постраничного обхода. Свои юрлица запрашиваются серверным фильтром. Сотрудники читаются из таблицы `portal_user`, заведённой в Фазе 2. Полный обход остаётся ровно в одном месте — в дозаполнении ИНН, это админское действие вне горячего пути.

**Tech Stack:** Django 5.2 / Python 3.11, b24pysdk; Nuxt 4 / Vue 3 на фронте; тесты — `django.test.TestCase` и `node:test` через `tsx`.

**Спека:** `docs/superpowers/specs/2026-07-28-project-references-performance-design.md`

## Зачем: доказательства с боевого портала

Логи и HAR от 2026-07-28, после выката хотфикса карточки:

```
[_fetch_paginated] batch-offset pages=465 total=23252 method=crm.company.list
[_fetch_paginated] batch-offset pages=327 total=16382 method=crm.requisite.list
[_fetch_paginated] batched fetch failed for crm.item.list
                   (Read timed out, read timeout=10); falling back to offset loop.

Request logging failed: connection to server at "192.168.0.6", port 5432 failed: timeout expired

09:52:16   5,03с   ждали сервер 5,02   GET /_nuxt/_JgdvnmC.js   (статический файл на 10 КБ)
```

Процессор при этом на 15%, память в норме. Причина не в мощности: обработчиков восемь (2 воркера × 4 потока), один обход справочника занимает поток на минуты, ожидая сеть. Процессор простаивает, очередь растёт, и статический файл ждёт пять секунд за чужим обходом. Плюс кончаются соединения с Postgres (их 25).

Битрикс при этом сам отваливается по таймауту на `crm.item.list` — 23 тысячи компаний тяжелы и для портала.

## Global Constraints

- **Ни один пользовательский путь не выполняет постраничный обход справочника.** Единственное разрешённое исключение — дозаполнение ИНН (Task 6), это админское действие.
- **Чтение из базы — только через `scope_to_tenant(account)`**; запись — `scope_to_tenant(account, write=True)`. Это kwargs, а не вызываемый объект.
- **Форма ответов эндпоинтов не меняется**, кроме объёма содержимого: `/api/project-board/meta` сохраняет ключи `filters` и `directories`, иначе сломаются проверки формы на бэкенде и во фронтовом сторе.
- **Сбой Битрикса не роняет экран.** Пустой список и пометка о недоступности — да; исключение наружу — нет.
- **Ничего не удаляем.** Ни одна задача этого плана не трогает данные.
- Прод — Python 3.11.15 / Django 5.2.16. Локальный venv 3.9/4.2 не годится, сверка — в Docker.

## Как гонять тесты

Бэкенд, отдельные модули:

```bash
cd backends/python/api && python manage.py test main.tests_company_search --settings=test_settings -v 2
```

Полный прогон на прод-стеке (обязателен перед сдачей каждой задачи — все правки идут в файл, который трогают десятки существующих тестов):

```bash
cd backends/python && docker run --rm -v "$PWD":/app -w /app python:3.11-slim bash -c 'pip install -q -r api/requirements.txt && cd api && python manage.py test $(cd main && ls tests_*.py | sed "s/\.py$//" | grep -vE "^(tests_inn_apply_batch|tests_project_fetch_keyset|tests_fetch_paginated_batch|tests_sync_scoped)$" | sed "s/^/main./" | tr "\n" " ") --settings=test_settings'
```

Четыре исключённых файла подменяют `django` в `sys.modules` и ломают общий раннер — их гонять отдельно:

```bash
cd backends/python && docker run --rm -e PYTHONPATH=/app -v "$PWD":/app -w /app python:3.11-slim bash -c 'pip install -q -r api/requirements.txt && for s in tests_inn_apply_batch tests_project_fetch_keyset tests_fetch_paginated_batch tests_sync_scoped; do python "api/main/$s.py"; done'
```

Фронт:

```bash
cd frontend && corepack pnpm@9.15.9 dlx tsx --test 'tests/**/*.test.ts'
```

## Структура файлов

| Файл | Ответственность |
|---|---|
| `backends/python/api/main/company_search_service.py` (создать) | Поиск компаний по подстроке и ИНН; список своих юрлиц серверным фильтром. |
| `backends/python/api/main/tests_company_search.py` (создать) | Тесты обоих методов. |
| `backends/python/api/main/project_board_service.py` (изменить) | `get_companies` и `get_legal_entities` перестают обходить портал; полный обход выделяется в отдельный метод для админского пути. |
| `backends/python/api/main/tests_project_references.py` (создать) | Тесты источников справочников и отсутствия обхода. |
| `backends/python/api/main/views.py`, `urls.py` (изменить) | Два новых эндпоинта. |
| `backends/python/api/main/inn_backfill_service.py` (изменить) | Явный вызов полного обхода вместо `get_companies()`. |
| `frontend/app/components/common/SearchableSelect.vue` (изменить) | Режим серверного поиска. |
| `frontend/app/stores/api.ts` (изменить) | `searchCompanies`, `getMyCompanies`. |
| `frontend/app/types/project-board.ts` (изменить) | Типы результата поиска. |
| `frontend/tests/companySearch.test.ts` (создать) | Тесты задержки ввода и обработки ответа. |

---

### Task 1: Сервис поиска компаний и своих юрлиц

**Files:**
- Create: `backends/python/api/main/company_search_service.py`
- Test: `backends/python/api/main/tests_company_search.py`

**Interfaces:**
- Consumes: ничего.
- Produces:
  - `class CompanySearchService` с `__init__(self, client, account)`
  - `search(self, query: str, limit: int = 50) -> Dict[str, Any]` → `{"companies": [{"id", "name", "inn"}], "truncated": bool, "failed": bool}`
  - `list_my_companies(self) -> Dict[str, Any]` → `{"companies": [{"id", "name"}], "failed": bool}`
  - константы `MIN_QUERY_LENGTH = 2`, `DEFAULT_LIMIT = 50`, `MAX_LIMIT = 100`, `SEARCH_CACHE_TTL = 60 * 5`, `MY_COMPANIES_CACHE_TTL = 60 * 60 * 6`

Полный код теста и реализации — в плане кнопки «Создать проект», задача 6, шаги 6–13 (`docs/superpowers/plans/2026-07-28-create-project-button.md`). **Возьми его оттуда дословно.** Он там уже написан, потому что форма создания проекта нуждается в тех же двух методах; вариант Б просто забирает их себе и выкатывается первым.

После того как этот файл появится здесь, в плане кнопки задача 6 должна ссылаться на него, а не дублировать. Это сделаю я, тебе трогать план кнопки не нужно.

- [ ] **Step 1: Написать падающий тест**

Скопируй тесты из шагов 6 и 11 задачи 6 плана кнопки: классы `CompanySearchTest` (8 тестов) и `MyCompaniesTest` (3 теста). Ничего не меняй.

- [ ] **Step 2: Убедиться, что тест падает**

```bash
cd backends/python/api && python manage.py test main.tests_company_search --settings=test_settings -v 2
```

Ожидаемо: `ModuleNotFoundError: No module named 'main.company_search_service'`.

- [ ] **Step 3: Написать реализацию**

Скопируй код из шагов 8 и 12 задачи 6 плана кнопки: модуль `company_search_service.py` целиком плюс метод `list_my_companies`.

- [ ] **Step 4: Прогон**

```bash
cd backends/python/api && python manage.py test main.tests_company_search --settings=test_settings -v 2
```

Ожидаемо: 11 тестов PASS.

- [ ] **Step 5: Коммит**

```bash
git add backends/python/api/main/company_search_service.py backends/python/api/main/tests_company_search.py
git commit -m "perf(references): сервис поиска компаний и своих юрлиц серверными фильтрами"
```

---

### Task 2: Свои юрлица без обхода портала

**Files:**
- Modify: `backends/python/api/main/project_board_service.py`
- Test: `backends/python/api/main/tests_project_references.py`

**Interfaces:**
- Consumes: `CompanySearchService.list_my_companies` (Task 1).
- Produces: `ProjectCardService.get_legal_entities(config=None)` больше не вызывает `_fetch_companies_live`.

Сейчас `get_legal_entities` (`project_board_service.py:586`) зовёт `_fetch_companies_live(only_my_company=True)` — тот выкачивает все 23 252 компании и отбирает «мои» уже в Python. Битрикс умеет отфильтровать сам.

- [ ] **Step 1: Написать падающий тест**

Создать `backends/python/api/main/tests_project_references.py`:

```python
"""Тесты источников справочников: пользовательские пути не обходят портал."""
from django.core.cache import cache
from django.test import TestCase

from .models import Bitrix24Account
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


class LegalEntitiesTest(TestCase):
    def setUp(self):
        cache.clear()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-refs-1",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )

    def test_uses_server_side_filter_not_full_scan(self):
        client = _FakeClient({
            "crm.company.list": {"result": [{"ID": "7", "TITLE": "ООО Мейнсофт"}]},
        })
        entities = ProjectCardService(client, self.account).get_legal_entities()

        self.assertEqual([e["id"] for e in entities], ["7"])
        # Ровно один вызов, без постраничного обхода и без crm.requisite.list.
        self.assertEqual(client.methods_called(), ["crm.company.list"])
        _, params = client.calls[0]
        self.assertEqual(params["filter"]["IS_MY_COMPANY"], "Y")

    def test_bitrix_failure_falls_back_to_project_cards(self):
        client = _FakeClient({"crm.company.list": RuntimeError("нет прав")})
        entities = ProjectCardService(client, self.account).get_legal_entities()

        self.assertEqual(entities, [])
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
cd backends/python/api && python manage.py test main.tests_project_references --settings=test_settings -v 2
```

Ожидаемо: падает на `assertEqual(client.methods_called(), ["crm.company.list"])` — текущая реализация зовёт ещё `crm.item.list` и `crm.requisite.list`.

- [ ] **Step 3: Написать реализацию**

Переписать `get_legal_entities` так, чтобы источником был `CompanySearchService.list_my_companies()`, а не `_fetch_companies_live(only_my_company=True)`. Кэш и фолбэк на компании из карточек проектов (`_get_project_card_fallback_options("our_legal_entity_id", "our_legal_entity_name")`) сохранить — они и сегодня там есть.

В докстринге объясни, почему нельзя вернуть обратно на `_fetch_companies_live`: это 465 страниц ради нескольких записей, и именно такие обходы держали обработчики и тормозили статику (см. раздел «Зачем» этого плана).

- [ ] **Step 4: Прогон**

Модуль плюс полный прогон бэкенда на прод-стеке — командой из раздела «Как гонять тесты». Существующие тесты должны остаться зелёными.

- [ ] **Step 5: Коммит**

```bash
git add backends/python/api/main/project_board_service.py backends/python/api/main/tests_project_references.py
git commit -m "perf(references): свои юрлица серверным фильтром вместо обхода портала"
```

---

### Task 3: Компании для выпадающих списков — из локальной базы

**Files:**
- Modify: `backends/python/api/main/project_board_service.py`
- Test: `backends/python/api/main/tests_project_references.py`

**Interfaces:**
- Consumes: `_get_project_card_fallback_options` (существует, `project_board_service.py:669`).
- Produces:
  - `ProjectCardService.get_companies()` читает локальную базу и не ходит в Битрикс.
  - `ProjectCardService.get_full_company_directory()` — прежнее поведение с постраничным обходом, вынесено отдельно и предназначено **только** для админского дозаполнения ИНН.

Это главная задача плана. `get_companies()` сейчас зовут пять мест: `get_board_data` (:154), `get_meta` (:309), `_resolve_company_reference` (:1023), `_resolve_legal_entity_reference` (:1035) и view `/api/project-board/companies` (`views.py:786`). Все они пользовательские, и все обходят портал.

Механизм уже написан: `_get_project_card_fallback_options("company_id", "company_name")` собирает компании из карточек проектов в локальной базе. Сегодня он используется как запасной вариант при сбое Битрикса — становится основным.

- [ ] **Step 1: Написать падающий тест**

Дописать в `backends/python/api/main/tests_project_references.py`:

```python
from datetime import date

from .models import ProjectCard
from .tenant_scoping import scope_to_tenant


class CompaniesFromDbTest(TestCase):
    def setUp(self):
        cache.clear()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-refs-2",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        ProjectCard.objects.create(
            **scope_to_tenant(self.account, write=True),
            project_id="44", project_name="Портал АО Ромашка", stage="NEW",
            company_id="15", company_name="АО Ромашка",
        )

    def test_companies_come_from_project_cards_without_touching_bitrix(self):
        client = _FakeClient()
        companies = ProjectCardService(client, self.account).get_companies()

        self.assertEqual([c["id"] for c in companies], ["15"])
        self.assertEqual([c["name"] for c in companies], ["АО Ромашка"])
        self.assertEqual(client.methods_called(), [])

    def test_no_project_cards_gives_empty_list_not_full_scan(self):
        ProjectCard.objects.all().delete()
        client = _FakeClient()
        companies = ProjectCardService(client, self.account).get_companies()

        self.assertEqual(companies, [])
        self.assertEqual(client.methods_called(), [])

    def test_other_portal_companies_are_not_visible(self):
        other = Bitrix24Account.objects.create(
            b24_user_id=2, is_b24_user_admin=True, member_id="m-refs-3",
            is_master_account=True, domain_url="other.bitrix24.ru",
            status="active", application_version=1,
        )
        companies = ProjectCardService(_FakeClient(), other).get_companies()

        self.assertEqual(companies, [])

    def test_board_data_does_not_scan_the_portal(self):
        client = _FakeClient()
        ProjectCardService(client, self.account).get_board_data()

        for method in ("crm.company.list", "crm.item.list", "crm.requisite.list"):
            self.assertNotIn(method, client.methods_called())

    def test_full_directory_is_still_available_for_admin_path(self):
        """Полный обход не удалён — он нужен дозаполнению ИНН, но вызывается
        только явно и никогда с пользовательского пути."""
        client = _FakeClient({
            "crm.company.list": {"result": [{"ID": "15", "TITLE": "АО Ромашка"}]},
        })
        directory = ProjectCardService(client, self.account).get_full_company_directory()

        self.assertEqual([c["id"] for c in directory], ["15"])
```

- [ ] **Step 2: Убедиться, что тесты падают**

```bash
cd backends/python/api && python manage.py test main.tests_project_references --settings=test_settings -v 2
```

Ожидаемо: падают на обращениях к Битриксу и на отсутствии `get_full_company_directory`.

- [ ] **Step 3: Написать реализацию**

- Переименовать текущее тело `get_companies` в `get_full_company_directory()`, оставив постраничный обход как есть. В докстринге написать прямо: метод медленный (465 страниц на боевом портале), предназначен только для админского дозаполнения ИНН, звать его с пользовательского пути нельзя.
- Новый `get_companies()` возвращает `_get_project_card_fallback_options("company_id", "company_name")` — компании, уже указанные в карточках проектов. В Битрикс не ходит.
- В докстринге `get_companies` объяснить: компании, которых нет в проектах, ищутся через `/api/project-board/companies/search`; сюда они попадают после первого же сохранения карточки.
- `_resolve_company_reference` и `_resolve_legal_entity_reference` автоматически станут дешёвыми — они зовут те же методы. Проверь, что они не сломались.

- [ ] **Step 4: Прогон**

Модуль плюс полный прогон на прод-стеке. Отдельно убедись, что тесты доски, главного экрана и `meta` остались зелёными: их содержимое изменится по составу, но форма должна сохраниться.

- [ ] **Step 5: Коммит**

```bash
git add backends/python/api/main/project_board_service.py backends/python/api/main/tests_project_references.py
git commit -m "perf(references): компании для списков — из карточек проектов, а не обходом портала"
```

---

### Task 4: Сотрудники в meta — из таблицы portal_user

**Files:**
- Modify: `backends/python/api/main/project_board_service.py`
- Test: `backends/python/api/main/tests_project_references.py`

**Interfaces:**
- Consumes: модель `PortalUser` (Фаза 2), `scope_to_tenant`.
- Produces: `get_meta()` не вызывает `BitrixDataService.fetch_active_users()`.

`get_meta` (`project_board_service.py:305`) строит список сотрудников через `fetch_active_users()`, который постранично обходит `user.get`. Таблица `portal_user` уже наполняется фоновым синком раз в час и уже питает имена в отчётах (`_get_user_map` в `views.py`).

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests_project_references.py` тест: создать две записи `PortalUser` (одну активную, одну нет), вызвать `get_meta()`, проверить что `directories["employees"]` содержит активного, что `user.get` не вызывался, и что чужой портал своих сотрудников здесь не видит.

Уволенных в выпадающий список кураторов не включаем — назначать куратором уволенного нельзя. Это отличается от `_get_user_map` отчётов, где уволенные обязаны резолвиться: там историчные списания.

- [ ] **Step 2: Убедиться, что тест падает**

Ожидаемо: в журнале вызовов фейкового клиента присутствует `user.get`.

- [ ] **Step 3: Написать реализацию**

Заменить источник сотрудников в `get_meta` на выборку из `PortalUser` с `active=True` через `scope_to_tenant(self.account)`, отсортированную по фамилии. Формат элемента прежний: `{"id", "name"}`, где имя — «Фамилия Имя». Фолбэк на `_get_project_card_fallback_options("curator_user_id", "curator_name")` сохранить.

- [ ] **Step 4: Прогон**

Модуль плюс полный прогон на прод-стеке.

- [ ] **Step 5: Коммит**

```bash
git add backends/python/api/main/project_board_service.py backends/python/api/main/tests_project_references.py
git commit -m "perf(references): сотрудники в meta — из portal_user, без обхода user.get"
```

---

### Task 5: Эндпоинты поиска и своих юрлиц

**Files:**
- Modify: `backends/python/api/main/views.py`
- Modify: `backends/python/api/main/urls.py`
- Test: `backends/python/api/main/tests_company_search.py`

**Interfaces:**
- Consumes: `CompanySearchService` (Task 1).
- Produces:
  - `GET /api/project-board/companies/search?q=<строка>&limit=50`
  - `GET /api/project-board/my-companies`

Код view и маршрутов — в задаче 6 плана кнопки, шаги 8 и 12. Возьми оттуда дословно.

- [ ] **Step 1: Написать падающий тест**

Тесты на маршруты: `reverse("search_project_board_companies")` даёт `/api/project-board/companies/search`, `reverse("list_my_companies")` даёт `/api/project-board/my-companies`, оба отклоняют POST кодом 405.

- [ ] **Step 2: Убедиться, что тест падает**

Ожидаемо: `NoReverseMatch`.

- [ ] **Step 3: Написать реализацию**

Views и маршруты из плана кнопки. Импорт `CompanySearchService` в блок импортов сервисов `views.py`.

- [ ] **Step 4: Прогон**

Модуль плюс полный прогон на прод-стеке.

- [ ] **Step 5: Коммит**

```bash
git add backends/python/api/main/views.py backends/python/api/main/urls.py backends/python/api/main/tests_company_search.py
git commit -m "perf(references): эндпоинты поиска компаний и своих юрлиц"
```

---

### Task 6: Дозаполнение ИНН — явный вызов полного обхода

**Files:**
- Modify: `backends/python/api/main/inn_backfill_service.py`
- Test: `backends/python/api/main/tests_project_references.py`

**Interfaces:**
- Consumes: `ProjectCardService.get_full_company_directory` (Task 3).
- Produces: ничего для последующих задач.

`inn_backfill_service.py:152-153` зовёт `get_companies()` и `get_legal_entities()` ради карты ИНН. После задачи 3 эти методы читают локальную базу и ИНН в них нет — дозаполнение перестанет работать, если не перевести его на явный полный обход.

Это единственное место, которому полный обход действительно нужен: оно проставляет ИНН во всех карточках сразу. Действие админское, вызывается вручную с экрана настроек, а не при открытии приложения.

- [ ] **Step 1: Написать падающий тест**

Тест: сервис дозаполнения получает карту ИНН через `get_full_company_directory`, а не через `get_companies`. Проверять по журналу вызовов фейкового клиента, что постраничный обход произошёл — здесь он ожидаем, в отличие от всех остальных задач плана.

- [ ] **Step 2: Убедиться, что тест падает**

- [ ] **Step 3: Написать реализацию**

Заменить `board.get_companies()` на `board.get_full_company_directory()` и `board.get_legal_entities()` на выборку своих юрлиц из того же полного справочника (по признаку `is_my_company`), чтобы ИНН были доступны. В комментарии написать, почему здесь обход допустим.

- [ ] **Step 4: Прогон**

Модуль плюс полный прогон на прод-стеке, **включая четыре standalone-скрипта** — среди них `tests_inn_apply_batch`, он про этот же сервис.

- [ ] **Step 5: Коммит**

```bash
git add backends/python/api/main/inn_backfill_service.py backends/python/api/main/tests_project_references.py
git commit -m "perf(references): дозаполнение ИНН — явный полный обход вместо общего метода"
```

---

### Task 7: Фронт — поиск компаний по мере ввода

**Files:**
- Modify: `frontend/app/components/common/SearchableSelect.vue`
- Modify: `frontend/app/stores/api.ts`
- Modify: `frontend/app/types/project-board.ts`
- Create: `frontend/tests/companySearch.test.ts`

**Interfaces:**
- Consumes: эндпоинты из Task 5.
- Produces: `useApiStore().searchCompanies`, `useApiStore().getMyCompanies`; необязательный режим серверного поиска в `SearchableSelect`.

`SearchableSelect.vue` сегодня фильтрует переданный список локально и показывает ИНН (`option.inn`, `option.search_text`). Локальный режим должен остаться нетронутым — компонент используется и для сотрудников, и для юрлиц, и для стадий.

- [ ] **Step 1: Написать падающий тест**

Создать `frontend/tests/companySearch.test.ts` с чистыми функциями, которые вынесешь из компонента в `frontend/app/utils/companySearch.ts`: нормализация запроса и решение «идти ли на сервер». Тесты: запрос короче двух символов не идёт на сервер; запрос из пробелов не идёт; из 10 цифр идёт; повторный тот же запрос в пределах задержки не порождает второй вызов.

`node:test` через `tsx` не резолвит `.vue`, поэтому логика решения должна жить в `utils`, а не в SFC.

- [ ] **Step 2: Убедиться, что тест падает**

```bash
cd frontend && corepack pnpm@9.15.9 dlx tsx --test 'tests/companySearch.test.ts'
```

- [ ] **Step 3: Написать реализацию**

- `frontend/app/utils/companySearch.ts` — чистые функции решения.
- Методы стора `searchCompanies(query, limit)` и `getMyCompanies()` — код в задаче 7 плана кнопки, возьми оттуда.
- `SearchableSelect.vue`: необязательный проп с функцией поиска, задержка ввода 300 мс, состояние «идёт поиск», подсказка «начните вводить название или ИНН» при пустом запросе, пометка «показаны первые 50, уточните запрос» при `truncated`. Без этого пропа компонент работает ровно как сейчас.
- Экраны проектов и главный: передать функцию поиска в выпадающие списки компаний. Списки сотрудников, юрлиц и стадий не трогать.

- [ ] **Step 4: Прогон и сборка**

```bash
cd frontend && corepack pnpm@9.15.9 dlx tsx --test 'tests/**/*.test.ts' && NODE_OPTIONS="--max-old-space-size=4096" corepack pnpm@9.15.9 run build
```

- [ ] **Step 5: Коммит**

```bash
git add frontend/app/utils/companySearch.ts frontend/app/components/common/SearchableSelect.vue frontend/app/stores/api.ts frontend/app/types/project-board.ts frontend/tests/companySearch.test.ts
git commit -m "perf(references): поиск компаний по мере ввода вместо локальной фильтрации справочника"
```

---

## Проверка перед мержем

Полный бэкенд плюс четыре standalone-скрипта плюс фронт и сборка — командами из раздела «Как гонять тесты». Миграций появиться не должно: ни одна задача не меняет модели.

Отдельно глазами: `grep -rn "_fetch_companies_live\|get_full_company_directory" backends/python/api/main/ | grep -v tests_` — вызывающих должно остаться ровно два, оба в `project_board_service.py` (сам метод и его определение) плюс один в `inn_backfill_service.py`. Любой другой вызывающий — это пользовательский путь, который снова обходит портал.
