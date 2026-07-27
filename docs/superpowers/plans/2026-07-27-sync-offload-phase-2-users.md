# Sync Offload — Фаза 2 (кэш пользователей) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Убрать синхронный `user.get` (и его Django LocMemCache с холодными промахами по 8 воркерам, 3–7 с на отчёт) из пути построения `user_map` в отчётах; завести локальную копию пользователей портала (`portal_user`), синкать её фоном по расписанию, отдавать наружу через пагинированный `/api/users`, и починить на фронте баг «только 50 сотрудников / User <id>» в дереве задачи.

**Architecture:** Bitrix24 остаётся источником истины для пользователей; `portal_user` в Postgres — локальная копия (та же схема, что `timesheet_item`/`project_card`: FK на `Bitrix24Account` + nullable FK на `Portal`, `scope_to_tenant`). Новый `UserSyncService.sync()` тянет `user.get` постранично (ВСЕХ пользователей, включая неактивных — иначе исторические отчёты по уволенным сотрудникам регрессируют) и upsert'ит в `portal_user`; удалений нет (Global Constraint «ничего не удаляем из данных»). Фоновый планировщик получает третий scope `"users"` рядом с `"timesheet"`/`"project"`, с часовым циклом в `start.sh` (без отдельной «ночной полной» — синк юзеров и так всегда полный, см. Self-Review). `views._get_user_map` — единая точка, которую уже используют ВСЕ 14 отчётных эндпоинтов, — переключается на чтение `portal_user` вместо `BitrixDataService.fetch_users`; эффект применяется сразу ко всем отчётам без правки каждого по отдельности. Новый `GET /api/users` отдаёт пагинированный список из БД (паттерн — как у существующего `timesheet_list`). На фронте `useTaskTreeLoader.loadConfigAndUsers` вместо одного непагинированного `user.get` (только первые 50) постранично вычитывает `/api/users`.

**Tech Stack:** Django 4.2/py3.9 локально (sqlite, тест-раннер), прод — Django 5/py3.11 (Postgres), `managed=True` модели, b24pysdk, gunicorn (gthread); Nuxt 4 / Vue 3 (Pinia store `api.ts`). Тесты бэка: `manage.py test --settings=test_settings`. Тесты фронта: `node:test` через `tsx`.

## Global Constraints

- Ветка: `feat/sync-offload-read-model` (от `prod_2026`; НЕ пушить в prod_2026 — авто-деплой).
- Тесты бэка запускать из `backends/python/api`: `./.venv/bin/python manage.py test main.<module> --settings=test_settings` (если `.venv` нет — `python manage.py test ... --settings=test_settings`).
- Django-миграции: `managed=True`, генерировать `makemigrations main`; в проде миграции — отдельный release-step (см. `start.sh:8-10`), не в рантайме.
- Паттерн тестов синка: `_FakeClient` с `_bitrix_token=self` и `call_method(method, params)` (см. `main/tests_sync_threshold.py`).
- Гейт свежести по умолчанию N=3 мин; интервал фонового инкремента 20 мин; ночная сверка есть.
- Фронт: не менять публичные контракты сторов сверх описанного; сборка `NODE_OPTIONS="--max-old-space-size=4096" corepack pnpm@9.15.9 run build`, тесты `corepack pnpm@9.15.9 dlx tsx --test 'tests/**/*.test.ts'` из `frontend/`.
- Ничего не удаляем из данных: изменения только в путях синка/чтения, не в orphan-логике `_sync_full`.

### Фаза 2 — дополнительно (уточнения к общим constraints)

- **Точка старта.** Ветка `feat/sync-offload-read-model` активно живёт (несколько параллельных сессий); состояние фиксировалось дважды за время подготовки этого плана. На момент ФИНАЛИЗАЦИИ плана реально применены (закоммичены, но не обязательно смержены в `prod_2026`) задачи 1–3 Фазы 1: поле `last_timesheet_synced_at` (`991ed25`), гейт/статус-эндпоинт `timesheet_sync_status` (`ee73deb`), и планировщик таймшитов с флагом `--full` + два фоновых timesheet-цикла в `start.sh` (`006814e`). Задачи 4–5 Фазы 1 (фронт: убрать авто-синк с открытия в `embedded.vue`, дефолт `willSync=false` в `useReportGenerator.ts`) — ЕЩЁ НЕ применены на момент финализации. Задача 3 НИЖЕ (диспетчеризация по `scope` в `run_scheduled_sync`) написана и построчно сверена против АКТУАЛЬНОГО состояния файлов после коммита `006814e` (включая ветку `full=True/False` и простановку `last_timesheet_synced_at` внутри диспетчера). Задачи 4 и 6 этого плана трогают файлы (`views.py`, `urls.py`, `useTaskTreeLoader.ts`, `stores/api.ts`), которые Фаза 1 не касается вообще (нет пересечения ни с Task 1-3, ни с ожидаемыми Task 4-5) — они не зависят от того, в каком порядке домержается Фаза 1.
- **Миграции.** Последняя применённая на момент грунтовки — `0016_bitrix24account_last_timesheet_synced_at.py`. Новая миграция этой фазы ожидается как `0017_portal_user.py` — перед `makemigrations` свериться командой `ls backends/python/api/main/migrations/`; если номер окажется другим (параллельная работа добавила миграции) — не страшно, `makemigrations` сам возьмёт следующий свободный номер, само имя не является публичным контрактом.
- **Мульти-портал.** `select_portal_accounts()` (один представитель на `member_id`) переиспользуется БЕЗ изменений для `scope="users"`. `scope_to_tenant(account)` — обязательный паттерн для каждого чтения/записи `PortalUser` (Задачи 1, 2, 4, 5); `PortalUser.bitrix_id` уникален только В ПРЕДЕЛАХ аккаунта (`unique_together`), НЕ глобально — один и тот же Bitrix-пользователь на двух порталах допустим (это два разных портала с независимыми `user.get`).
- **Всегда-полный синк юзеров.** В отличие от таймшитов, у пользователей нет инкремента по `updatedTime` (Bitrix `user.get` не отдаёт это поле стабильно, а пользователей на портале — десятки-сотни, не тысячи) — КАЖДЫЙ запуск `UserSyncService.sync()` полный. Поэтому отдельная «ночная полная сверка» для scope=users не нужна — часовой цикл УЖЕ является полной сверкой каждый час (см. обоснование в Self-Review).
- **Неактивные сотрудники не выпадают.** `portal_user` хранит и активных, и уволенных/деактивированных (`active=False`, запись не удаляется и не пропускается синком) — иначе имена в исторических отчётах по уволенным сотрудникам регрессируют на fallback-заглушку вместо резолва (текущий `BitrixDataService.fetch_users` тоже не фильтрует по ACTIVE, так что это сохранение, а не улучшение поведения).

---

## Task 1: Модель `PortalUser` + миграция

**Files:**
- Modify: `backends/python/api/main/models.py` (новый класс `PortalUser` после `class ProjectCard` — Meta закрывается на строке 266, `class RequestLog` начинается на строке 269; вставить между ними)
- Create: `backends/python/api/main/migrations/0017_portal_user.py` (через `makemigrations`)
- Test: `backends/python/api/main/tests_portal_user_model.py` (новый)

**Interfaces:**
- Produces: модель `PortalUser` с полями `bitrix24_account (FK Bitrix24Account)`, `portal (FK Portal, nullable)`, `bitrix_id (str, max 50)`, `name (str)`, `last_name (str)`, `active (bool, default True)`, `created_at`, `updated_at`; `Meta.unique_together = ("bitrix24_account", "bitrix_id")`; `db_table = "portal_user"`.

- [ ] **Step 1: Написать падающий тест модели**

Create `backends/python/api/main/tests_portal_user_model.py`:
```python
"""Тесты модели PortalUser (Фаза 2 sync-offload: кэш пользователей)."""
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Bitrix24Account, PortalUser


def _account(member_id="m-pu-1", **kwargs):
    defaults = dict(
        b24_user_id=1, is_b24_user_admin=True, is_master_account=True,
        domain_url=f"{member_id}.bitrix24.ru", status="active", application_version=1,
    )
    defaults.update(kwargs)
    return Bitrix24Account.objects.create(member_id=member_id, **defaults)


class PortalUserModelTest(TestCase):
    def test_create_with_required_fields_and_defaults(self):
        account = _account()
        user = PortalUser.objects.create(
            bitrix24_account=account,
            bitrix_id="167",
            name="Иван",
            last_name="Петров",
        )
        self.assertTrue(user.active)  # default True
        self.assertIsNotNone(user.created_at)
        self.assertIsNotNone(user.updated_at)
        self.assertIsNone(user.portal_id)  # nullable до backfill/portal-скоупинга

    def test_unique_together_account_and_bitrix_id(self):
        account = _account("m-pu-uniq")
        PortalUser.objects.create(bitrix24_account=account, bitrix_id="1", name="A", last_name="B")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PortalUser.objects.create(bitrix24_account=account, bitrix_id="1", name="C", last_name="D")

    def test_same_bitrix_id_allowed_across_different_accounts(self):
        acc1 = _account("m-pu-2", b24_user_id=1)
        acc2 = _account("m-pu-3", b24_user_id=2)
        PortalUser.objects.create(bitrix24_account=acc1, bitrix_id="1", name="A", last_name="B")
        # тот же bitrix_id, другой портал — не конфликт (мульти-портал)
        PortalUser.objects.create(bitrix24_account=acc2, bitrix_id="1", name="X", last_name="Y")
        self.assertEqual(PortalUser.objects.filter(bitrix_id="1").count(), 2)

    def test_inactive_user_is_stored_not_dropped(self):
        account = _account("m-pu-4")
        user = PortalUser.objects.create(
            bitrix24_account=account, bitrix_id="2", name="Уволен", last_name="Сотрудников", active=False,
        )
        user.refresh_from_db()
        self.assertFalse(user.active)
```

- [ ] **Step 2: Прогнать — падает**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_portal_user_model --settings=test_settings`
Expected: FAIL (`ImportError: cannot import name 'PortalUser' from 'main.models'`).

- [ ] **Step 3: Добавить модель**

В `models.py`, между `class ProjectCard` (заканчивается строкой 266) и `class RequestLog` (строка 269):
```python
class PortalUser(models.Model):
    """Локальная копия справочника пользователей Bitrix24 (Фаза 2 sync-offload).

    Кэш для user_map отчётов и /api/users вместо per-request user.get с
    LocMemCache (см. BitrixDataService.fetch_users). Хранит И активных, И
    неактивных сотрудников: user_map отчётов должен резолвить имя и по
    уволенным (историчные списания) — см. report_services.resolve_employee_name.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bitrix24_account = models.ForeignKey(Bitrix24Account, on_delete=models.CASCADE, related_name="portal_users")
    portal = models.ForeignKey(
        "Portal", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="portal_users", db_index=True,
    )
    bitrix_id = models.CharField(max_length=50, db_index=True)
    name = models.CharField(max_length=255, blank=True, default="")
    last_name = models.CharField(max_length=255, blank=True, default="")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = "portal_user"
        unique_together = ("bitrix24_account", "bitrix_id")
        indexes = [
            models.Index(fields=["bitrix24_account", "active"], name="portal_user_acc_active_idx"),
        ]
```

- [ ] **Step 4: Сгенерировать миграцию**

Run: `cd backends/python/api && ./.venv/bin/python manage.py makemigrations main --settings=test_settings`
Expected: создан `migrations/0017_portal_user.py` с `CreateModel(name='PortalUser', ...)`.

- [ ] **Step 5: Прогнать — проходит**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_portal_user_model --settings=test_settings`
Expected: PASS (4/4).

- [ ] **Step 6: Коммит**

```bash
git add backends/python/api/main/models.py backends/python/api/main/migrations/ backends/python/api/main/tests_portal_user_model.py
git commit -m "feat(sync): модель PortalUser + миграция (кэш пользователей, Фаза 2)"
```

---

## Task 2: `UserSyncService` — полный синк пользователей (upsert, без удалений)

**Files:**
- Create: `backends/python/api/main/user_sync_service.py`
- Test: `backends/python/api/main/tests_user_sync_service.py` (новый)

**Interfaces:**
- Consumes: `PortalUser` (Task 1), `employee_ids.extract_bitrix_user_id`, `tenant_scoping.scope_to_tenant`.
- Produces: `UserSyncService(client, account).sync() -> Dict[str, int]` с ключами `{"synced": int, "created": int, "updated": int}` (та же форма возврата, что у `ProjectSyncService.sync()` — для единообразной обработки в планировщике, см. Задачу 3).

- [ ] **Step 1: Написать падающий тест**

Create `backends/python/api/main/tests_user_sync_service.py`:
```python
"""Тесты UserSyncService: полный постраничный синк user.get -> upsert PortalUser.

Паттерн _FakeClient — как в tests_sync_threshold.py.
"""
from django.test import TestCase

from .models import Bitrix24Account, PortalUser
from .user_sync_service import UserSyncService


class _FakeClient:
    """Минимальный двойник Client: возвращает заранее заданные страницы по порядку."""

    def __init__(self, pages):
        self._pages = list(pages)
        self._calls = 0
        self._bitrix_token = self

    def call_method(self, method, params):
        if self._calls < len(self._pages):
            resp = self._pages[self._calls]
        else:
            resp = {"result": []}
        self._calls += 1
        return resp


class UserSyncServiceTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-usersync-1",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )

    def test_sync_creates_new_users_including_inactive(self):
        pages = [
            {
                "result": [
                    {"ID": "1", "NAME": "Иван", "LAST_NAME": "Петров", "ACTIVE": "Y"},
                    {"ID": "2", "NAME": "Анна", "LAST_NAME": "Сидорова", "ACTIVE": "N"},
                ],
            },
        ]
        service = UserSyncService(_FakeClient(pages), self.account)
        result = service.sync()

        self.assertEqual(result, {"synced": 2, "created": 2, "updated": 0})
        rows = {row.bitrix_id: row for row in PortalUser.objects.filter(bitrix24_account=self.account)}
        self.assertEqual(rows["1"].name, "Иван")
        self.assertTrue(rows["1"].active)
        self.assertFalse(rows["2"].active)  # неактивный тоже сохранён (для истории отчётов)

    def test_sync_updates_existing_user_on_name_change(self):
        PortalUser.objects.create(
            bitrix24_account=self.account, bitrix_id="1", name="Old", last_name="Name", active=True,
        )
        pages = [{"result": [{"ID": "1", "NAME": "New", "LAST_NAME": "Name", "ACTIVE": "Y"}]}]
        service = UserSyncService(_FakeClient(pages), self.account)
        result = service.sync()

        self.assertEqual(result, {"synced": 1, "created": 0, "updated": 1})
        row = PortalUser.objects.get(bitrix24_account=self.account, bitrix_id="1")
        self.assertEqual(row.name, "New")

    def test_sync_paginates_using_next_cursor(self):
        page1_users = [
            {"ID": str(i), "NAME": f"U{i}", "LAST_NAME": "L", "ACTIVE": "Y"} for i in range(1, 51)
        ]
        pages = [
            {"result": page1_users, "next": 50, "total": 51},
            {"result": [{"ID": "51", "NAME": "U51", "LAST_NAME": "L", "ACTIVE": "Y"}], "total": 51},
        ]
        service = UserSyncService(_FakeClient(pages), self.account)
        result = service.sync()
        self.assertEqual(result["synced"], 51)
        self.assertTrue(PortalUser.objects.filter(bitrix24_account=self.account, bitrix_id="51").exists())

    def test_sync_does_not_delete_users_missing_from_response(self):
        PortalUser.objects.create(
            bitrix24_account=self.account, bitrix_id="99", name="Stale", last_name="User", active=True,
        )
        pages = [{"result": [{"ID": "1", "NAME": "Иван", "LAST_NAME": "Петров", "ACTIVE": "Y"}]}]
        service = UserSyncService(_FakeClient(pages), self.account)
        service.sync()
        # upsert-only: юзер, не вернувшийся в этом ответе, НЕ удаляется (Global Constraint).
        self.assertTrue(PortalUser.objects.filter(bitrix24_account=self.account, bitrix_id="99").exists())

    def test_sync_scoped_to_account_does_not_touch_other_portal(self):
        other = Bitrix24Account.objects.create(
            b24_user_id=2, is_b24_user_admin=True, member_id="m-usersync-2",
            is_master_account=True, domain_url="other.bitrix24.ru",
            status="active", application_version=1,
        )
        PortalUser.objects.create(bitrix24_account=other, bitrix_id="1", name="Чужой", last_name="Юзер", active=True)

        pages = [{"result": [{"ID": "1", "NAME": "Свой", "LAST_NAME": "Юзер", "ACTIVE": "Y"}]}]
        service = UserSyncService(_FakeClient(pages), self.account)
        service.sync()

        other_row = PortalUser.objects.get(bitrix24_account=other, bitrix_id="1")
        self.assertEqual(other_row.name, "Чужой")  # не тронут синком другого аккаунта
```

- [ ] **Step 2: Прогнать — падает**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_user_sync_service --settings=test_settings`
Expected: FAIL (`ModuleNotFoundError: No module named 'main.user_sync_service'`).

- [ ] **Step 3: Реализовать `UserSyncService`**

Create `backends/python/api/main/user_sync_service.py`:
```python
import logging
from typing import Any, Dict, List

from b24pysdk import Client
from django.db import transaction
from django.utils import timezone

from .employee_ids import extract_bitrix_user_id
from .models import Bitrix24Account, PortalUser
from .tenant_scoping import scope_to_tenant

logger = logging.getLogger(__name__)


class UserSyncService:
    """Полный постраничный синк справочника пользователей Bitrix24 -> PortalUser.

    В отличие от TimesheetSyncService, здесь НЕТ инкремента и НЕТ удаления
    "осиротевших" записей: пользователей на портале мало (десятки-сотни),
    полный обход дешёвый, а удаление запрещено Global Constraint ("ничего не
    удаляем из данных"). Пользователь, пропавший из ответа Bitrix, просто
    сохраняет последнее известное состояние до следующего успешного синка.
    """

    PAGE_SIZE = 50
    MAX_PAGES = 1000  # защита от зацикливания фонового джоба; 1000*50 = 50000 юзеров с запасом
    BULK_BATCH_SIZE = 200
    UPSERT_FIELDS = ["name", "last_name", "active", "updated_at"]

    def __init__(self, client: Client, account: Bitrix24Account):
        self.client = client
        self.account = account

    def sync(self) -> Dict[str, int]:
        raw_users = self._fetch_all_users()
        return self._save_batch(raw_users)

    def _fetch_all_users(self) -> List[Dict[str, Any]]:
        """Все пользователи портала, БЕЗ фильтра ACTIVE (нужны и уволенные —
        см. Global Constraints). Пагинация: тот же курсор next/total/len<PAGE_SIZE,
        что в BitrixDataService.fetch_active_users."""
        result: List[Dict[str, Any]] = []
        seen_ids = set()
        start = 0
        pages = 0

        while pages < self.MAX_PAGES:
            response = self.client._bitrix_token.call_method(
                "user.get",
                {"sort": "ID", "order": "ASC", "start": start},
            )
            users = response.get("result", [])
            if not users:
                break

            for user in users:
                user_id = extract_bitrix_user_id(user.get("ID"))
                if not user_id or user_id in seen_ids:
                    continue
                seen_ids.add(user_id)
                result.append(user)

            pages += 1
            next_value = response.get("next")
            if next_value not in (None, "", False):
                next_start = int(next_value)
                if next_start <= start:
                    break
                start = next_start
                continue

            total = response.get("total")
            if total is not None:
                next_start = start + len(users)
                if next_start >= int(total):
                    break
                start = next_start
                continue

            if len(users) < self.PAGE_SIZE:
                break
            start += len(users)

        return result

    @transaction.atomic
    def _save_batch(self, raw_users: List[Dict[str, Any]]) -> Dict[str, int]:
        prepared: List[tuple] = []
        for user in raw_users:
            bitrix_id = extract_bitrix_user_id(user.get("ID"))
            if not bitrix_id:
                continue
            prepared.append((
                bitrix_id,
                {
                    "name": user.get("NAME") or "",
                    "last_name": user.get("LAST_NAME") or "",
                    "active": str(user.get("ACTIVE", "Y")).upper() == "Y",
                },
            ))

        if not prepared:
            return {"synced": 0, "created": 0, "updated": 0}

        now = timezone.now()
        bitrix_ids = [bid for bid, _ in prepared]
        existing = {
            row.bitrix_id: row
            for row in PortalUser.objects.filter(
                **scope_to_tenant(self.account),
                bitrix_id__in=bitrix_ids,
            )
        }

        to_create: List[PortalUser] = []
        to_update: List[PortalUser] = []

        for bitrix_id, defaults in prepared:
            existing_row = existing.get(bitrix_id)
            if existing_row is None:
                to_create.append(
                    PortalUser(
                        **scope_to_tenant(self.account, write=True),
                        bitrix_id=bitrix_id,
                        created_at=now,
                        updated_at=now,
                        **defaults,
                    )
                )
                continue

            has_changes = False
            for field_name, field_value in defaults.items():
                if getattr(existing_row, field_name) != field_value:
                    setattr(existing_row, field_name, field_value)
                    has_changes = True
            if has_changes:
                existing_row.updated_at = now
                to_update.append(existing_row)

        if to_create:
            PortalUser.objects.bulk_create(to_create, batch_size=self.BULK_BATCH_SIZE)
        if to_update:
            PortalUser.objects.bulk_update(to_update, self.UPSERT_FIELDS, batch_size=self.BULK_BATCH_SIZE)

        return {"synced": len(prepared), "created": len(to_create), "updated": len(to_update)}
```

- [ ] **Step 4: Прогнать — проходит**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_user_sync_service --settings=test_settings`
Expected: PASS (5/5).

- [ ] **Step 5: Коммит**

```bash
git add backends/python/api/main/user_sync_service.py backends/python/api/main/tests_user_sync_service.py
git commit -m "feat(sync): UserSyncService — полный синк user.get -> upsert PortalUser, без удалений"
```

---

## Task 3: Планировщик — `scope="users"` (SCOPE_BITS, run_scheduled_sync, sync_all_portals, start.sh)

**Files:**
- Modify: `backends/python/api/main/utils/decorators/sync_lock.py` (`SCOPE_BITS`, строка 30)
- Modify: `backends/python/api/main/sync_scheduler_service.py` (импорт после строки 34; диспетчеризация по `scope`, строки 81-122 — актуально после коммита `006814e`, см. Global Constraints)
- Modify: `backends/python/api/main/management/commands/sync_all_portals.py` (`--scope` choices + docstring)
- Modify: `backends/python/api/start.sh` (часовой фоновый цикл `--scope users`)
- Test: `backends/python/api/main/tests_sync_lock.py` (дополнить), `backends/python/api/main/tests_scheduled_sync.py` (дополнить)

**Interfaces:**
- Consumes: `UserSyncService` (Task 2).
- Produces: `account_sync_lock(account, scope="users")` работает (не бросает `ValueError`); `run_scheduled_sync(scope="users")` вызывает `UserSyncService(account.client, account).sync()` под локом `scope="users"`, пишет `SyncRun(scope="users", items_synced=result["synced"], ...)`; `sync_all_portals --scope users` — новый выбор команды.

- [ ] **Step 1: Написать падающие тесты (lock scope + scheduler dispatch)**

В `tests_sync_lock.py`, в класс `AdvisoryKeyTest` добавить:
```python
    def test_users_scope_produces_distinct_key(self):
        k_ts = _advisory_key(account_pk=10, scope="timesheet")
        k_pr = _advisory_key(account_pk=10, scope="project")
        k_us = _advisory_key(account_pk=10, scope="users")
        self.assertNotEqual(k_us, k_ts)
        self.assertNotEqual(k_us, k_pr)
```

В `tests_scheduled_sync.py` добавить новый класс (после `RunScheduledSyncProjectScopeTest`):
```python
class RunScheduledSyncUsersScopeTest(TestCase):
    """Тесты scope="users": синк пользователей без timesheet/project."""

    @patch("main.sync_scheduler_service.UserSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_users_scope_calls_user_sync_service(self, mock_cfg_cls, mock_user_cls):
        _account("m1", master=True)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg
        mock_user_svc = MagicMock()
        mock_user_svc.sync.return_value = {"synced": 42, "created": 10, "updated": 32}
        mock_user_cls.return_value = mock_user_svc

        run = run_scheduled_sync(scope="users")

        self.assertIsInstance(run, SyncRun)
        self.assertEqual(run.scope, "users")
        self.assertEqual(run.status, "success")
        self.assertEqual(run.portals_total, 1)
        self.assertEqual(run.portals_synced, 1)
        self.assertEqual(run.items_synced, 42)
        mock_user_svc.sync.assert_called_once()

    @patch("main.sync_scheduler_service.UserSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_users_scope_lock_uses_users_scope(self, mock_cfg_cls, mock_user_cls):
        _account("m1", master=True)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg
        mock_user_cls.return_value.sync.return_value = {"synced": 1, "created": 1, "updated": 0}

        with patch("main.sync_scheduler_service.account_sync_lock") as mock_lock:
            mock_lock.return_value.__enter__ = MagicMock(return_value=None)
            mock_lock.return_value.__exit__ = MagicMock(return_value=False)
            run_scheduled_sync(scope="users")

        mock_lock.assert_called_once()
        _, kwargs = mock_lock.call_args
        self.assertEqual(kwargs.get("scope"), "users")

    @patch("main.sync_scheduler_service.UserSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_users_scope_auto_sync_disabled_skips_portal(self, mock_cfg_cls, mock_user_cls):
        _account("m1", master=True)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": False}
        mock_cfg_cls.return_value = mock_cfg
        mock_user_cls.return_value = MagicMock()

        run = run_scheduled_sync(scope="users")
        self.assertEqual(run.portals_synced, 0)
        mock_user_cls.return_value.sync.assert_not_called()

    @patch("main.sync_scheduler_service.UserSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_users_scope_one_portal_failure_does_not_abort_run(self, mock_cfg_cls, mock_user_cls):
        _account("m1", master=True, b24_user_id=1)
        _account("m2", master=True, b24_user_id=3)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg
        mock_user_svc = MagicMock()
        mock_user_svc.sync.side_effect = [RuntimeError("users_boom"), {"synced": 7, "created": 2, "updated": 5}]
        mock_user_cls.return_value = mock_user_svc

        run = run_scheduled_sync(scope="users")
        self.assertEqual(run.portals_total, 2)
        self.assertEqual(run.portals_synced, 1)
        self.assertEqual(run.status, "partial")
        self.assertIn("users_boom", run.error_summary or "")

    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ProjectSyncService")
    @patch("main.sync_scheduler_service.UserSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_users_scope_does_not_call_other_services(self, mock_cfg_cls, mock_user_cls, mock_proj_cls, mock_ts_cls):
        _account("m1", master=True)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg
        mock_user_cls.return_value.sync.return_value = {"synced": 1, "created": 1, "updated": 0}

        run_scheduled_sync(scope="users")

        mock_proj_cls.assert_not_called()
        mock_ts_cls.assert_not_called()
```

- [ ] **Step 2: Прогнать — падает**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_sync_lock main.tests_scheduled_sync --settings=test_settings`
Expected: FAIL — `tests_sync_lock`: `ValueError: sync_lock: unknown scope 'users'`; `tests_scheduled_sync`: `AttributeError: <module 'main.sync_scheduler_service'> does not have the attribute 'UserSyncService'` (patch не может найти атрибут для мока).

- [ ] **Step 3: Добавить `"users"` в `SCOPE_BITS`**

В `utils/decorators/sync_lock.py`, строка 30, заменить:
```python
SCOPE_BITS = {"timesheet": 1, "project": 2}
```
на:
```python
SCOPE_BITS = {"timesheet": 1, "project": 2, "users": 3}
```

- [ ] **Step 4: Добавить импорт и ветку `scope="users"` в `run_scheduled_sync`**

> Важно: Фаза 1 Задача 3 (флаг `--full` + маркер `last_timesheet_synced_at` внутри диспетчера) уже смержена в эту ветку коммитом `006814e` на момент этой задачи. Ниже — точная сверка с АКТУАЛЬНЫМ содержимым файла (не с черновиком из плана Фазы 1).

В `sync_scheduler_service.py`, после строки `from .timesheet_sync_service import TimesheetSyncService` (строка 34) добавить:
```python
from .user_sync_service import UserSyncService
```

Текущее содержимое диспетчеризации (строки 81-122) выглядит так:
```python
            if scope == "project":
                try:
                    with account_sync_lock(account, scope="project"):
                        service = ProjectSyncService(account.client, account)
                        result = service.sync()
                except SyncLockBusy:
                    logger.info("Portal %s project-sync skipped: lock busy.",
                                account.member_id)
                    continue

                # ProjectSyncService.sync() возвращает dict с ключами synced/created/updated
                count = result.get("synced", 0) if isinstance(result, dict) else 0
                synced += 1
                items_total += int(count or 0)
                logger.info("Scheduled project-sync portal %s: %s items.", account.member_id, count)

            else:  # scope == "timesheet"
                if not config.get("sp_entity_type_id"):
                    logger.info("Portal %s not configured (no sp_entity_type_id); skip.",
                                account.member_id)
                    continue

                try:
                    with account_sync_lock(account, scope="timesheet"):
                        service = TimesheetSyncService(account.client, account, config)
                        if full:
                            count = service.sync_all()  # без дат → _sync_full (ночная сверка)
                        else:
                            count = service.sync_all(date_from=date_from, date_to=date_to)
                        # Маркер «данные свежи на» для индикатора отчёта (гейт в timesheet_sync,
                        # задача 2.2) — иначе фоновые синки его не двигают, и виджет всегда
                        # показывал бы устаревшее время, пока пользователь не откроет отчёт сам.
                        account.last_timesheet_synced_at = timezone.now()
                        account.save(update_fields=["last_timesheet_synced_at"])
                except SyncLockBusy:
                    logger.info("Portal %s sync skipped: lock busy (manual sync running).",
                                account.member_id)
                    continue

                synced += 1
                items_total += int(count or 0)
                logger.info("Scheduled sync portal %s: %s items.", account.member_id, count)
```

Вставить новую ветку `elif scope == "users":` МЕЖДУ веткой `project` (заканчивается строкой с `logger.info("Scheduled project-sync ...")`) и `else:  # scope == "timesheet"` — то есть заменить строку
```python
            else:  # scope == "timesheet"
```
на:
```python
            elif scope == "users":
                try:
                    with account_sync_lock(account, scope="users"):
                        service = UserSyncService(account.client, account)
                        result = service.sync()
                except SyncLockBusy:
                    logger.info("Portal %s user-sync skipped: lock busy.",
                                account.member_id)
                    continue

                # UserSyncService.sync() возвращает dict с ключами synced/created/updated
                count = result.get("synced", 0) if isinstance(result, dict) else 0
                synced += 1
                items_total += int(count or 0)
                logger.info("Scheduled user-sync portal %s: %s users.", account.member_id, count)

            else:  # scope == "timesheet"
```
(тело ветки `timesheet`, включая простановку `full`/`last_timesheet_synced_at` — без изменений; трогаем только точку вставки новой `elif`).

- [ ] **Step 5: Прогнать — проходит**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_sync_lock main.tests_scheduled_sync --settings=test_settings`
Expected: PASS.

- [ ] **Step 6: Добавить `--scope users` в команду**

В `management/commands/sync_all_portals.py`, модульный докстринг (строки 6-10) сейчас:
```python
По расписанию используются оба scope (встроенные фоновые циклы в start.sh):
  - project:   полный синк проектов, раз в 3 часа;
  - timesheet: инкрементальный синк (окно days), каждые 20 минут;
  - timesheet --full: полная ночная сверка (без окна дат), раз в сутки —
    ловит удаления/пропуски, которые инкремент не видит.
```
заменить на:
```python
По расписанию используются все три scope (встроенные фоновые циклы в start.sh):
  - project:   полный синк проектов, раз в 3 часа;
  - timesheet: инкрементальный синк (окно days), каждые 20 минут;
  - timesheet --full: полная ночная сверка (без окна дат), раз в сутки —
    ловит удаления/пропуски, которые инкремент не видит;
  - users:     полный синк пользователей (всегда полный, инкремента нет), раз в час.
```

Класс `Command.help` (строки 27-32) сейчас:
```python
    help = (
        "Фоновый синк по всем настроенным порталам. "
        "--scope project: синк проектов (используется встроенным планировщиком, раз в 3 ч). "
        "--scope timesheet: инкрементальный синк трудозатрат (встроенный планировщик, каждые 20 мин; "
        "с --full — полная ночная сверка раз в сутки)."
    )
```
заменить на:
```python
    help = (
        "Фоновый синк по всем настроенным порталам. "
        "--scope project: синк проектов (используется встроенным планировщиком, раз в 3 ч). "
        "--scope timesheet: инкрементальный синк трудозатрат (встроенный планировщик, каждые 20 мин; "
        "с --full — полная ночная сверка раз в сутки). "
        "--scope users: синк пользователей (всегда полный, встроенный планировщик, раз в час)."
    )
```

`add_arguments` (строки 41-48, БЕЗ изменений от Фазы 1 Задачи 3), заменить:
```python
        parser.add_argument(
            "--scope",
            type=str,
            default="timesheet",
            choices=["timesheet", "project"],
            help="Что синхронизировать: timesheet (трудозатраты) или project (проекты). "
                 "По умолчанию timesheet (обратная совместимость).",
        )
```
на:
```python
        parser.add_argument(
            "--scope",
            type=str,
            default="timesheet",
            choices=["timesheet", "project", "users"],
            help="Что синхронизировать: timesheet (трудозатраты), project (проекты) или "
                 "users (пользователи, раз в ~1 ч). По умолчанию timesheet (обратная совместимость).",
        )
```

- [ ] **Step 7: Добавить часовой фоновый цикл в `start.sh`**

На момент этой задачи в `start.sh` (после Фазы 1 Задачи 3) уже есть три фоновых цикла (project раз в 3ч — строка 30; timesheet-инкремент раз в 20 мин — строка 33; timesheet --full раз в сутки — строка 35), затем `exec gunicorn` (строка 37). Добавить четвёртый цикл сразу после timesheet-циклов (после строки 35), перед пустой строкой и `exec gunicorn`:
```bash
# Пользователи: полный синк раз в час (юзеров мало, меняются редко; полный
# синк дешёвый — отдельная "ночная" сверка не нужна, часовой цикл её заменяет,
# см. Global Constraints / Self-Review).
( while true; do sleep 3600; python manage.py sync_all_portals --scope users || true; done ) &
```

- [ ] **Step 8: Регресс всех sync-тестов**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_sync_lock main.tests_scheduled_sync main.tests_sync_threshold main.tests_sync_freshness main.tests_sync_integration --settings=test_settings`
Expected: PASS (все, включая уже существующие project/timesheet тесты — регресс).

- [ ] **Step 9: Коммит**

```bash
git add backends/python/api/main/utils/decorators/sync_lock.py backends/python/api/main/sync_scheduler_service.py backends/python/api/main/management/commands/sync_all_portals.py backends/python/api/start.sh backends/python/api/main/tests_sync_lock.py backends/python/api/main/tests_scheduled_sync.py
git commit -m "feat(sync): планировщик — scope=users (часовой фоновый синк пользователей)"
```

---

## Task 4: `user_map` в отчётах — читать из `portal_user`, а не `fetch_users`

**Files:**
- Modify: `backends/python/api/main/views.py` (импорт строка 14; `_get_user_map`, строки 133-140)
- Test: `backends/python/api/main/tests_report_user_map.py` (новый)

**Interfaces:**
- Consumes: `PortalUser` (Task 1).
- Produces: `views._get_user_map(request, user_ids) -> Dict[str, str]` — СИГНАТУРА не меняется (используется всеми 14 отчётными эндпоинтами через единую точку вызова), меняется только тело: без обращения к Bitrix, читает `PortalUser` по `scope_to_tenant(request.bitrix24_account)`.

- [ ] **Step 1: Написать падающий тест**

Create `backends/python/api/main/tests_report_user_map.py`:
```python
"""_get_user_map строит карту имён из локальной БД (portal_user), а не из
Bitrix user.get (Фаза 2 sync-offload: убирает 3-7с "user_map" на отчётах)."""
from django.test import RequestFactory, TestCase

from . import views
from .models import Bitrix24Account, PortalUser


class GetUserMapReadsFromPortalUserTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-map-1",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )

    def _request(self):
        request = RequestFactory().get("/api/report-employee-project")
        request.bitrix24_account = self.account
        return request

    def test_builds_map_from_local_db_without_bitrix_call(self):
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="1", name="Иван", last_name="Петров", active=True)
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="2", name="Анна", last_name="Сидорова", active=False)

        result = views._get_user_map(self._request(), {"1", "2"})

        self.assertEqual(result, {"1": "Петров Иван", "2": "Сидорова Анна"})

    def test_missing_user_id_is_simply_absent_from_map(self):
        result = views._get_user_map(self._request(), {"999"})
        self.assertEqual(result, {})  # resolve_employee_name падает на fallback "Сотрудник 999"

    def test_empty_user_ids_returns_empty_dict(self):
        self.assertEqual(views._get_user_map(self._request(), set()), {})

    def test_scoped_by_tenant_other_account_users_not_leaked(self):
        other = Bitrix24Account.objects.create(
            b24_user_id=2, is_b24_user_admin=True, member_id="m-map-2",
            is_master_account=True, domain_url="other.bitrix24.ru",
            status="active", application_version=1,
        )
        PortalUser.objects.create(bitrix24_account=other, bitrix_id="1", name="Чужой", last_name="Юзер", active=True)

        result = views._get_user_map(self._request(), {"1"})
        self.assertEqual(result, {})
```

- [ ] **Step 2: Прогнать — падает**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_report_user_map --settings=test_settings`
Expected: FAIL (`AssertionError: {} != {'1': 'Петров Иван', '2': 'Сидорова Анна'}`) — текущая реализация уходит в `BitrixDataService.fetch_users` через `request.bitrix24_account.client` с фиктивными кредами; в тестовом окружении без сети быстро ловит исключение (`except Exception: return {}` внутри `fetch_users`/`get_configuration_sync`) и возвращает пустую карту.

- [ ] **Step 3: Переключить `_get_user_map` на `PortalUser`**

В `views.py`, строка 14, добавить `PortalUser` в импорт моделей:
```python
from .models import ApplicationInstallation, TimesheetItem, RequestLog, SystemLog, ProjectCard, PortalUser
```

Заменить тело функции (строки 133-140):
```python
def _get_user_map(request: AuthorizedRequest, user_ids):
    if not user_ids:
        return {}

    config_service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    config = config_service.get_configuration_sync()
    data_service = BitrixDataService(request.bitrix24_account.client, config, request.bitrix24_account)
    return data_service.fetch_users(list(user_ids))
```
на:
```python
def _get_user_map(request: AuthorizedRequest, user_ids):
    """Строит {employee_id: "Фамилия Имя"} из локальной БД (portal_user),
    а не через Bitrix user.get. Убирает 3-7с "user_map" на отчётах (был
    холодный промах per-воркер Django LocMemCache) — см. Фаза 2 sync-offload.
    """
    if not user_ids:
        return {}

    rows = PortalUser.objects.filter(
        **scope_to_tenant(request.bitrix24_account),
        bitrix_id__in=list(user_ids),
    ).values("bitrix_id", "name", "last_name")

    return {
        row["bitrix_id"]: (f"{row['last_name']} {row['name']}".strip() or row["bitrix_id"])
        for row in rows
    }
```
(`scope_to_tenant` уже импортирован в `views.py` — строка 34; `BitrixDataService`/`ConfigurationService` остаются импортированными и используются другими функциями файла — не удалять эти импорты).

- [ ] **Step 4: Прогнать — проходит**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_report_user_map --settings=test_settings`
Expected: PASS (4/4).

- [ ] **Step 5: Регресс отчётных тестов**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_reports main.tests_report_perf main.tests_user_cache --settings=test_settings`
Expected: PASS. `tests_user_cache.py` (контракт `BitrixDataService.fetch_users`/LocMemCache) остаётся зелёным без изменений — `fetch_users` НЕ удаляется, им по-прежнему пользуются `inn_backfill_service.py`, `project_board_service.py` и `project_sync_service.py` (имена куратора/владельца проекта) — это осознанно вне объёма Фазы 2 (см. Self-Review).

- [ ] **Step 6: Коммит**

```bash
git add backends/python/api/main/views.py backends/python/api/main/tests_report_user_map.py
git commit -m "perf(reports): user_map из portal_user вместо fetch_users — убирает 3-7с на отчётах"
```

---

## Task 5: `GET /api/users` — пагинированный список пользователей из БД

**Files:**
- Modify: `backends/python/api/main/views.py` (новая вьюха `get_users` — после `timesheet_list`, строка ~1556; `__all__`, строка 99)
- Modify: `backends/python/api/main/urls.py` (маршрут, после строки 56)
- Test: `backends/python/api/main/tests_users_endpoint.py` (новый)

**Interfaces:**
- Consumes: `PortalUser` (Task 1).
- Produces: `GET /api/users?page=&limit=&active_only=` (JWT `Authorization: Bearer`, `@auth_required`) → `{"items": [{"id": str, "name": str, "last_name": str, "active": bool, "updated_at": str}], "total": int, "page": int, "pages": int, "has_next": bool, "has_previous": bool}` (та же форма ответа, что у `GET /api/timesheets`).

- [ ] **Step 1: Написать падающий тест**

Create `backends/python/api/main/tests_users_endpoint.py`:
```python
"""GET /api/users — пагинированный список сотрудников из локальной БД."""
from django.test import Client, TestCase

from .models import Bitrix24Account, PortalUser


class GetUsersEndpointTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-users-ep-1",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        self.token = self.account.create_jwt_token()

    def _get(self, query=""):
        return Client().get(f"/api/users{query}", HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def test_returns_paginated_users_from_db(self):
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="1", name="Иван", last_name="Абрамов", active=True)
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="2", name="Анна", last_name="Багрова", active=False)

        response = self._get()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual([item["id"] for item in data["items"]], ["1", "2"])  # order_by last_name
        self.assertIn("has_next", data)
        self.assertFalse(data["has_next"])

    def test_active_only_filter(self):
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="1", name="Иван", last_name="Абрамов", active=True)
        PortalUser.objects.create(bitrix24_account=self.account, bitrix_id="2", name="Анна", last_name="Багрова", active=False)

        response = self._get("?active_only=1")

        data = response.json()
        self.assertEqual([item["id"] for item in data["items"]], ["1"])

    def test_pagination_limit_and_page_params(self):
        for i in range(1, 4):
            PortalUser.objects.create(bitrix24_account=self.account, bitrix_id=str(i), name=f"U{i}", last_name="L", active=True)

        response = self._get("?limit=2&page=2")
        data = response.json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["page"], 2)
        self.assertEqual(data["pages"], 2)

    def test_requires_auth(self):
        # Без Authorization заголовка auth_required уходит в OAuth-ветку и падает
        # на пустом теле запроса -> 400 (см. QueryStabilityTest для /api/configuration/,
        # тот же паттерн для GET-эндпоинтов без тела).
        response = Client().get("/api/users")
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_does_not_leak_other_tenant_users(self):
        other = Bitrix24Account.objects.create(
            b24_user_id=2, is_b24_user_admin=True, member_id="m-users-ep-2",
            is_master_account=True, domain_url="other.bitrix24.ru",
            status="active", application_version=1,
        )
        PortalUser.objects.create(bitrix24_account=other, bitrix_id="1", name="Чужой", last_name="Юзер", active=True)

        response = self._get()
        data = response.json()
        self.assertEqual(data["total"], 0)
```

- [ ] **Step 2: Прогнать — падает**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_users_endpoint --settings=test_settings`
Expected: FAIL (404 — маршрут `/api/users` не существует, попадает в SPA catch-all `serve_spa`, `response.json()` бросает `JSONDecodeError` на HTML-ответе).

- [ ] **Step 3: Добавить вьюху `get_users`**

В `views.py`, добавить в `__all__` (после `"timesheet_list"`, строка 99):
```python
    "get_users",
```

Добавить саму вьюху после `timesheet_list` (после строки 1555, перед `get_configuration`):
```python
@xframe_options_exempt
@require_GET
@log_errors("get_users")
@auth_required
def get_users(request: AuthorizedRequest):
    queryset = PortalUser.objects.filter(**scope_to_tenant(request.bitrix24_account)).order_by("last_name", "name")

    active_only = str(request.GET.get("active_only", "")).strip().lower() in {"1", "true", "y", "yes"}
    if active_only:
        queryset = queryset.filter(active=True)

    page_number = request.GET.get("page", 1)
    page_size = request.GET.get("limit", 50)

    paginator = Paginator(queryset, page_size)
    page_obj = paginator.get_page(page_number)

    items = [
        {
            "id": item.bitrix_id,
            "name": item.name,
            "last_name": item.last_name,
            "active": item.active,
            "updated_at": item.updated_at.isoformat(),
        }
        for item in page_obj
    ]

    return JsonResponse({
        "items": items,
        "total": paginator.count,
        "page": page_obj.number,
        "pages": paginator.num_pages,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
    })
```

- [ ] **Step 4: Добавить маршрут**

В `urls.py`, после строки 56 (`path('api/timesheets', ...)`), перед `path('api/export-raw-data', ...)`:
```python
    path('api/users', views.get_users, name='get_users'),
```

- [ ] **Step 5: Прогнать — проходит**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_users_endpoint --settings=test_settings`
Expected: PASS (5/5).

- [ ] **Step 6: Регресс (маршрутизация не сломана)**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_reports.QueryStabilityTest main.tests_users_endpoint main.tests_report_user_map --settings=test_settings`
Expected: PASS.

- [ ] **Step 7: Коммит**

```bash
git add backends/python/api/main/views.py backends/python/api/main/urls.py backends/python/api/main/tests_users_endpoint.py
git commit -m "feat(api): GET /api/users — пагинированный список сотрудников из БД"
```

---

## Task 6: Фронт — `apiStore.getUsers` + `useTaskTreeLoader` без каппа на 50

**Files:**
- Modify: `frontend/app/stores/api.ts` (новый метод `getUsers`, после `getTimesheetsList` строка 597; добавить в `return`, рядом со строкой 1087-1088)
- Modify: `frontend/app/composables/useTaskTreeLoader.ts` (`loadConfigAndUsers`, строки 65-101)
- Test: `frontend/tests/taskTreeLoader.test.ts` (дополнить)

**Interfaces:**
- Consumes: `GET /api/users` (Task 5).
- Produces: `apiStore.getUsers(page = 1, limit = 50, activeOnly = false): Promise<{items: Array<{id: string; name: string; last_name: string; active: boolean; updated_at: string}>; total: number; page: number; pages: number; has_next: boolean; has_previous: boolean}>`. `loadConfigAndUsers` — публичная сигнатура не меняется, `usersMap`/`usersList` теперь содержат ВСЕХ активных сотрудников (не только первые 50).

- [ ] **Step 1: Написать падающий тест**

В `frontend/tests/taskTreeLoader.test.ts`, в блоке стабов (строки 18-24) добавить стаб `useApiStore`:
```typescript
type Global = Record<string, unknown>

let fieldConfigStub: Record<string, unknown>
let apiStoreStub: Record<string, unknown>

;(globalThis as unknown as Global).ref = ref
;(globalThis as unknown as Global).computed = computed
;(globalThis as unknown as Global).useFieldConfigStore = () => fieldConfigStub
;(globalThis as unknown as Global).useApiStore = () => apiStoreStub
```
(заменяет старый блок строк 18-24 — добавлены строки `let apiStoreStub` и `useApiStore`).

В конец файла (после последнего `test(...)`, строка 94) добавить:
```typescript
test('loadConfigAndUsers: подгружает больше 50 сотрудников постранично из /api/users', async () => {
  fieldConfigStub = makeConfigStub(87)

  const page1 = Array.from({ length: 200 }, (_, i) => ({
    id: String(i + 1), name: `Имя${i + 1}`, last_name: 'Фамилия', active: true, updated_at: '2026-07-27T00:00:00Z'
  }))
  const page2 = [{ id: '201', name: 'Имя201', last_name: 'Фамилия', active: true, updated_at: '2026-07-27T00:00:00Z' }]

  let callCount = 0
  apiStoreStub = {
    getUsers: async (page: number) => {
      callCount += 1
      if (page === 1) {
        return { items: page1, total: 201, page: 1, pages: 2, has_next: true, has_previous: false }
      }
      return { items: page2, total: 201, page: 2, pages: 2, has_next: false, has_previous: true }
    }
  }

  const loader = useTaskTreeLoader()
  await loader.loadConfigAndUsers({} as never, {})

  assert.equal(loader.usersList.value.length, 201, 'все 201 сотрудник должны загрузиться, а не первые 50')
  assert.equal(callCount, 2, 'должно быть ровно две страницы запроса')
  const lastUser = loader.usersMap.value['201'] as { NAME?: string } | undefined
  assert.equal(lastUser?.NAME, 'Имя201', 'сотрудник со второй страницы должен резолвиться')
})
```

- [ ] **Step 2: Прогнать — падает**

Run: `cd frontend && corepack pnpm@9.15.9 dlx tsx --test tests/taskTreeLoader.test.ts`
Expected: FAIL — текущая реализация `loadConfigAndUsers` безусловно вызывает `client.callBatch(batch)` (для ключа `users`), а стаб `$b24 = {}` не имеет `callBatch` → `TypeError: client.callBatch is not a function`.

- [ ] **Step 3: Добавить `getUsers` в `api.ts`**

В `frontend/app/stores/api.ts`, после `getTimesheetsList` (после строки 597, перед `getProjectBoard`):
```typescript
    const getUsers = async (
      page: number = 1,
      limit: number = 50,
      activeOnly: boolean = false
    ): Promise<{ items: Array<{ id: string, name: string, last_name: string, active: boolean, updated_at: string }>, total: number, page: number, pages: number, has_next: boolean, has_previous: boolean }> => {
      const params = new URLSearchParams()
      params.append('page', page.toString())
      params.append('limit', limit.toString())
      if (activeOnly) params.append('active_only', '1')

      return await $api(`/api/users?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }
```

В `return { ... }` объекта стора (рядом со строкой 1087-1088, где `getFilterEmployees`/`getFilterProjects`), добавить:
```typescript
      getUsers,
```

- [ ] **Step 4: Переписать `loadConfigAndUsers` в `useTaskTreeLoader.ts`**

Заменить тело функции (строки 65-101):
```typescript
  async function loadConfigAndUsers($b24: B24Frame, options: LoadTaskTreeOptions = {}) {
    const batch: Record<string, { method: string; params?: Record<string, unknown> }> = {
      users: { method: 'user.get', params: { FILTER: { ACTIVE: 'Y' }, sort: 'LAST_NAME', order: 'ASC' } }
    }

    if (options.includeProfile) {
      batch.profile = { method: 'profile' }
    }

    const client = $b24 as unknown as B24BatchClient
    const result = await client.callBatch(batch)
    const data = result.getData()

    const usersResponse = data.users as RawRecord | undefined
    if (usersResponse && !usersResponse.error) {
      const users = extractResult(usersResponse)
      const map: Record<string, TaskWorkspaceUser> = {}
      if (Array.isArray(users)) {
        for (const user of users) {
          map[String(user.ID)] = user
        }
      }
      usersMap.value = map
    }

    if (options.includeProfile) {
      const profile = extractResult(data.profile) as RawRecord | null
      if (profile?.ID) {
        currentUserId.value = String(profile.ID)
      }
    }

    await fieldConfigStore.loadFromB24($b24)
    if (!fieldConfigStore.isConfigured) {
      error.value = fieldConfigStore.loadError || 'Конфигурация не найдена. Зайдите в Настройки → Настройка полей и настройте поля.'
    }
  }
```
на:
```typescript
  async function loadConfigAndUsers($b24: B24Frame, options: LoadTaskTreeOptions = {}) {
    const apiStore = useApiStore()
    const client = $b24 as unknown as B24BatchClient

    // Сотрудники — из локальной БД через /api/users (пагинированно), а не прямым
    // user.get у Bitrix: user.get без курсора отдавал только первые 50 (баг «только
    // 50 сотрудников» / «User <id>» в дереве задачи). БД держит полную актуальную
    // копию (Фаза 2 sync-offload).
    const map: Record<string, TaskWorkspaceUser> = {}
    const USERS_PAGE_LIMIT = 200
    const USERS_MAX_PAGES = 25 // защита от зацикливания; 25*200 = 5000 сотрудников с запасом
    let page = 1
    while (page <= USERS_MAX_PAGES) {
      const response = await apiStore.getUsers(page, USERS_PAGE_LIMIT, true)
      for (const item of response.items) {
        map[String(item.id)] = { ID: item.id, NAME: item.name, LAST_NAME: item.last_name }
      }
      if (!response.has_next) {
        break
      }
      page += 1
    }
    usersMap.value = map

    if (options.includeProfile) {
      const batch: Record<string, { method: string; params?: Record<string, unknown> }> = {
        profile: { method: 'profile' }
      }
      const result = await client.callBatch(batch)
      const data = result.getData()
      const profile = extractResult(data.profile) as RawRecord | null
      if (profile?.ID) {
        currentUserId.value = String(profile.ID)
      }
    }

    await fieldConfigStore.loadFromB24($b24)
    if (!fieldConfigStore.isConfigured) {
      error.value = fieldConfigStore.loadError || 'Конфигурация не найдена. Зайдите в Настройки → Настройка полей и настройте поля.'
    }
  }
```

- [ ] **Step 5: Прогнать — проходит**

Run: `cd frontend && corepack pnpm@9.15.9 dlx tsx --test tests/taskTreeLoader.test.ts`
Expected: PASS (4/4 — 3 существующих + новый).

- [ ] **Step 6: Typecheck + сборка**

Run: `cd frontend && NODE_OPTIONS="--max-old-space-size=4096" corepack pnpm@9.15.9 run build`
Expected: `✨ Build complete!` без ошибок типов (`TaskWorkspaceUser` совместим с `{ID, NAME, LAST_NAME}`, `useApiStore`/`getUsers` резолвятся автоимпортом).

- [ ] **Step 7: Полный регресс фронт-тестов**

Run: `cd frontend && corepack pnpm@9.15.9 dlx tsx --test 'tests/**/*.test.ts'`
Expected: все PASS, число проходящих тестов не уменьшилось (выросло на 1 — новый тест Step 1).

- [ ] **Step 8: Коммит**

```bash
git add frontend/app/stores/api.ts frontend/app/composables/useTaskTreeLoader.ts frontend/tests/taskTreeLoader.test.ts
git commit -m "fix(task-tree): имена сотрудников из /api/users — убирает капп на 50 и User <id>"
```

---

## Self-Review

**1. Spec coverage (design §4.3, «Меняем»):**
- «Новая модель `portal_user` (bitrix_id, name, last_name, active, скоуп account/portal, updated_at) + миграция» — Task 1 ✓ (все перечисленные поля присутствуют дословно; `unique_together` на уровне аккаунта, а не глобально — обязательно для мульти-портала).
- «Синк юзеров: `user.get` постранично (все) → upsert в `portal_user`. По расписанию реже (раз в 1–3 ч) + ночью» — Task 2 (сервис, постранично, ВСЕ включая неактивных) ✓ + Task 3 (часовой фоновый цикл) ✓. Отдельная «ночная» ветка сознательно НЕ добавлена — обоснование ниже (п. 4).
- «`user_map` в отчётах строится из `portal_user` (мгновенно, шаред между воркерами, переживает рестарт)» — Task 4 ✓; единая точка `_get_user_map` покрывает все 14 отчётных эндпоинтов одним изменением (проверено grep'ом по `views.py` перед написанием плана).
- «Фронт: имена сотрудников из БД-эндпоинта `/api/users` (с пагинацией) → уходит баг «только 50 / User <id>»» — Task 5 (эндпоинт, пагинация page/limit + active_only) ✓ + Task 6 (`useTaskTreeLoader` вычитывает ВСЕ страницы, а не только первую) ✓.
- Design §5.2 (маркер `last_<domain>_synced_at`) и §5.4/§5.5 (кнопка «Обновить», гейт свежести) — сознательно НЕ реализованы для домена users: после Фазы 2 отчёты вообще не дёргают Bitrix на чтении юзеров (это не on-request путь, как таймшиты в Фазе 1), поэтому нет пользовательского действия, которое нужно было бы гейтить или которому нужен индикатор. Наблюдаемость даёт существующий `SyncRun(scope="users")` (создаётся в Task 3 через тот же `run_scheduled_sync`, без нового поля-маркера на `Bitrix24Account`). Явный список задач в постановке (5 пунктов) тоже не просил гейт/кнопку для users — только: модель, синк+расписание, user_map из БД, эндпоинт, фронт.

**2. Placeholder scan:** пройден по всему файлу — каждый шаг содержит реальный код (тест + реализация), нет `TODO`/«добавить обработку»/«аналогично Task N» без кода. Единственное намеренное «неидеальное» место — Task 4 Step 2 явно объясняет МЕХАНИЗМ падения теста (сеть недоступна → `fetch_users` ловит исключение → `{}`), а не декларирует голое «должно упасть».

**3. Type consistency (сквозная проверка имён/сигнатур между задачами):**
- `PortalUser.bitrix_id` — `CharField` (Task 1) ↔ `UserSyncService._save_batch` пишет туда `extract_bitrix_user_id(...)` (строка, Task 2) ↔ `_get_user_map` фильтрует `bitrix_id__in=list(user_ids)` где `user_ids` — уже нормализованные строки из `TimesheetItem.employee_id` (Task 4) ↔ `get_users` сериализует `item.bitrix_id` как `"id"` (строка, Task 5) ↔ фронт `String(item.id)` (Task 6). Везде строка — согласовано.
- `UserSyncService.sync() -> {"synced", "created", "updated"}` (Task 2) ↔ `run_scheduled_sync`'s `elif scope == "users"` читает `result.get("synced", 0)` (Task 3) — та же форма, что уже используется для `ProjectSyncService.sync()` в соседней ветке `project` — единообразно, не изобретён новый контракт.
- `account_sync_lock(account, scope="users")` (Task 3, Step 4) ↔ `SCOPE_BITS["users"] = 3` (Task 3, Step 3) — добавлены В ОДНОЙ задаче, до первого использования.
- `GET /api/users` ответ `{items:[{id,name,last_name,active,updated_at}], total,page,pages,has_next,has_previous}` (Task 5) ↔ `apiStore.getUsers` объявляет ТОТ ЖЕ shape как `Promise<...>` (Task 6) ↔ `useTaskTreeLoader` читает `response.items`, `item.id`, `item.name`, `item.last_name`, `response.has_next` — поля совпадают буква в букву.
- `apiStore.getUsers(page, limit, activeOnly)` (Task 6, Step 3) ↔ вызов `apiStore.getUsers(page, USERS_PAGE_LIMIT, true)` (Task 6, Step 4) — 3 позиционных аргумента, порядок совпадает.
- `views._get_user_map(request, user_ids)` — сигнатура idempotent между Task 4 (единственное место изменения) и всеми существующими 14 вызовами в `views.py` (не тронуты, т.к. вызывают функцию по имени, а не дублируют её тело).

**4. Обоснование «без отдельной ночной ветки для users» (Global Constraints, design §7/§11):** design говорит «синк юзеров реже (~1 ч) + ночью», по аналогии с таймшитами (инкремент 20 мин + ночная ПОЛНАЯ сверка, потому что инкремент по `updatedTime` не ловит удаления). У пользователей НЕТ инкрементального режима вообще — `UserSyncService.sync()` всегда полный обход. Значит часовой цикл — это и есть «сверка» каждый час; отдельный ночной `--full`-проход для users был бы дублирующим вызовом той же функции с той же логикой. План использует ОДИН часовой фоновый цикл вместо двух (часовой + ночной) — осознанное упрощение, которое сохраняет свойство «раз в сутки гарантированно полная сверка» (даёт его 24 раза в сутки, а не 1).

**5. Открытый вопрос (не задача, для отчёта пользователю):** design §13 «Пустая БД нового портала: до первого синка отчёт пуст → показать «идёт первичная загрузка»; первичный полный синк — по установке/первой плановой сверке» — этот план НЕ добавляет синхронный вызов `UserSyncService.sync()` в `views.install`/`get_token` (эндпоинт установки явно не входил в 5 пунктов постановки, и трогать auth-critical path без явного запроса — лишний риск). Между установкой приложения и первым часовым тиком планировщика (до 1 ч) `portal_user` пуст → `_get_user_map` вернёт `{}` для всех — отчёты покажут фоллбэк-имена («Сотрудник <id>»/«User <id>» для `generate_daily_workload`), НЕ пустой отчёт (сами цифры/структура отчёта не зависят от user_map). Это узкое, самоисправляющееся окно (максимум ~1 ч после установки нового портала), но стоит явно решить отдельно, нужно ли форсировать `UserSyncService.sync()` синхронно в `install`/`getToken`.

## Definition of Done (Фаза 2)

- Все бэк-тесты зелёные: `tests_portal_user_model`, `tests_user_sync_service`, `tests_sync_lock`, `tests_scheduled_sync`, `tests_report_user_map`, `tests_users_endpoint`, плюс регресс (`tests_reports`, `tests_report_perf`, `tests_user_cache`, `tests_sync_threshold`, `tests_sync_freshness`, `tests_sync_integration`).
- Фронт: `build` OK, `tsx --test 'tests/**/*.test.ts'` — все PASS, число проходящих не уменьшилось.
- Ручная проверка после merge+деплой: `[REPORT_PERF] report_* user_map=...ms` в логах падает с 3000-7000 мс до единиц мс на ХОЛОДНОМ воркере (не только на прогретом кэше); вкладка задачи в карточке показывает более 50 сотрудников в выпадающих списках, если их больше 50 на портале; фамилии сотрудников в дереве задачи и в отчётах не показывают «User <id>»/«Сотрудник <id>» для реально существующих (в т.ч. уволенных) сотрудников; `GET /api/users` отдаёт JSON с пагинацией; фоновый лог показывает часовые `sync_all_portals --scope users` без ошибок.
