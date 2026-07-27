# Sync Offload — Фаза 1 (таймшиты с критпути) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Убрать синхронный полный синк таймшитов с пути открытия/генерации; свежесть держит фоновое расписание + гейт свежести + кнопка «Обновить», всё читается из БД.

**Architecture:** Bitrix = источник истины, `timesheet_item` в Postgres = быстрая копия. Отчёты уже читают из БД; убираем блокирующий `syncTimesheets()` с фронта, переносим синк в фоновый планировщик (`start.sh`), добавляем гейт свежести и маркер `last_timesheet_synced_at`. Переиспользуем существующие `_sync_scoped` (7 дней, для расписания и «Обновить») и `_sync_full` (ночная сверка). Новый алгоритм синка в Фазе 1 не пишем.

**Tech Stack:** Django 5 (Postgres, `managed=True` модели), b24pysdk, gunicorn (gthread, WSGI); Nuxt 4 / Vue 3 (Pinia store `api.ts`). Тесты бэка: `manage.py test --settings=test_settings`.

## Global Constraints

- Ветка: `feat/sync-offload-read-model` (от `prod_2026`; НЕ пушить в prod_2026 — авто-деплой).
- Тесты бэка запускать из `backends/python/api`: `./.venv/bin/python manage.py test main.<module> --settings=test_settings` (если `.venv` нет — `python manage.py test ... --settings=test_settings`).
- Django-миграции: `managed=True`, генерировать `makemigrations main`; в проде миграции — отдельный release-step (см. `start.sh:8-10`), не в рантайме.
- Паттерн тестов синка: `_FakeClient` с `_bitrix_token=self` и `call_method(method, params)` (см. `main/tests_sync_threshold.py`).
- Гейт свежести по умолчанию **N=3 мин**; интервал фонового инкремента **20 мин**; ночная сверка **есть**.
- Фронт: не менять публичные контракты сторов сверх описанного; сборка `NODE_OPTIONS="--max-old-space-size=4096" corepack pnpm@9.15.9 run build`, тесты `corepack pnpm@9.15.9 dlx tsx --test 'tests/**/*.test.ts'` из `frontend/`.
- Ничего не удаляем из данных: изменения только в путях синка/чтения, не в orphan-логике `_sync_full`.

---

## Task 1: Модель — маркер `last_timesheet_synced_at`

**Files:**
- Modify: `backends/python/api/main/models.py` (класс `Bitrix24Account`, после строки 40)
- Create: `backends/python/api/main/migrations/00NN_bitrix24account_last_timesheet_synced_at.py` (через makemigrations)
- Test: `backends/python/api/main/tests_sync_freshness.py` (новый)

**Interfaces:**
- Produces: поле `Bitrix24Account.last_timesheet_synced_at: Optional[datetime]` (null по умолчанию).

- [ ] **Step 1: Написать падающий тест наличия поля**

Create `backends/python/api/main/tests_sync_freshness.py`:
```python
from django.test import TestCase
from django.utils import timezone
from .models import Bitrix24Account


class LastSyncedFieldTest(TestCase):
    def test_field_defaults_to_none_and_persists(self):
        acc = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m1",
            is_master_account=True, domain_url="ex.bitrix24.ru",
            status="active", application_version=1,
        )
        self.assertIsNone(acc.last_timesheet_synced_at)
        now = timezone.now()
        acc.last_timesheet_synced_at = now
        acc.save(update_fields=["last_timesheet_synced_at"])
        acc.refresh_from_db()
        self.assertEqual(acc.last_timesheet_synced_at, now)
```

- [ ] **Step 2: Прогнать — падает (нет поля)**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_sync_freshness --settings=test_settings`
Expected: FAIL (`AttributeError`/`FieldError`: `last_timesheet_synced_at`).

- [ ] **Step 3: Добавить поле в модель**

В `models.py`, в `Bitrix24Account` после `portal = models.ForeignKey(...)` (строка 40):
```python
    last_timesheet_synced_at = models.DateTimeField(null=True, blank=True)
```

- [ ] **Step 4: Сгенерировать миграцию**

Run: `cd backends/python/api && ./.venv/bin/python manage.py makemigrations main --settings=test_settings`
Expected: создан файл миграции с `AddField(... last_timesheet_synced_at ...)`.

- [ ] **Step 5: Прогнать — проходит**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_sync_freshness --settings=test_settings`
Expected: PASS.

- [ ] **Step 6: Коммит**

```bash
git add backends/python/api/main/models.py backends/python/api/main/migrations/ backends/python/api/main/tests_sync_freshness.py
git commit -m "feat(sync): маркер last_timesheet_synced_at на Bitrix24Account"
```

---

## Task 2: Гейт свежести + маркер в `timesheet_sync`, статус-эндпоинт

**Files:**
- Modify: `backends/python/api/main/views.py` (`timesheet_sync`, строки 1420-1470; + новый `timesheet_sync_status`)
- Modify: `backends/python/api/main/urls.py` (маршрут статуса)
- Test: `backends/python/api/main/tests_sync_freshness.py` (дополнить)

**Interfaces:**
- Consumes: `Bitrix24Account.last_timesheet_synced_at` (Task 1).
- Produces: `timesheet_sync` при свежести <N мин возвращает `{"status":"fresh","count":<db>,"last_synced_at":<iso>}` без вызова Bitrix; при синке проставляет маркер и возвращает `last_synced_at`. Новый `GET /api/timesheet-sync-status` → `{"last_synced_at":<iso|null>,"count":<int>}`.

- [ ] **Step 1: Падающий тест гейта (свежий → skip, без Bitrix)**

Дополнить `tests_sync_freshness.py`:
```python
import json
from unittest.mock import patch
from datetime import timedelta
from django.test import RequestFactory


class FreshnessGateTest(TestCase):
    def _acc(self, last=None):
        return Bitrix24Account.objects.create(
            b24_user_id=2, is_b24_user_admin=True, member_id="m2",
            is_master_account=True, domain_url="ex2.bitrix24.ru",
            status="active", application_version=1,
            last_timesheet_synced_at=last,
        )

    def test_fresh_skips_bitrix_sync(self):
        from . import views
        acc = self._acc(last=timezone.now() - timedelta(minutes=1))  # < 3 мин
        req = RequestFactory().post("/api/sync-timesheets", data="{}", content_type="application/json")
        req.bitrix24_account = acc
        with patch.object(views, "TimesheetSyncService") as Svc:
            resp = views.timesheet_sync.__wrapped__(req) if hasattr(views.timesheet_sync, "__wrapped__") else None
        # если декораторы мешают — тестируем выделенный хелпер (см. Step 3)
```

> Примечание исполнителю: вьюха обёрнута декораторами (`auth_required`, `sync_lock` и т.д.), напрямую звать неудобно. Поэтому логику гейта выносим в чистый хелпер `should_skip_timesheet_sync(account, now, gate_minutes)` и тестируем его (Step 3 переписывает тест на хелпер).

- [ ] **Step 2: Прогнать — падает**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_sync_freshness.FreshnessGateTest --settings=test_settings`
Expected: FAIL (нет `should_skip_timesheet_sync`).

- [ ] **Step 3: Реализовать хелпер + переписать тест на него**

В `views.py` рядом с `timesheet_sync` добавить:
```python
TIMESHEET_SYNC_GATE_MINUTES = 3

def should_skip_timesheet_sync(account, now, gate_minutes=TIMESHEET_SYNC_GATE_MINUTES):
    last = account.last_timesheet_synced_at
    if last is None:
        return False
    return (now - last).total_seconds() < gate_minutes * 60
```
Переписать тест:
```python
    def test_helper_skips_when_fresh(self):
        from .views import should_skip_timesheet_sync
        acc = self._acc(last=timezone.now() - timedelta(minutes=1))
        self.assertTrue(should_skip_timesheet_sync(acc, timezone.now()))

    def test_helper_syncs_when_stale(self):
        from .views import should_skip_timesheet_sync
        acc = self._acc(last=timezone.now() - timedelta(minutes=10))
        self.assertFalse(should_skip_timesheet_sync(acc, timezone.now()))

    def test_helper_syncs_when_never(self):
        from .views import should_skip_timesheet_sync
        acc = self._acc(last=None)
        self.assertFalse(should_skip_timesheet_sync(acc, timezone.now()))
```

- [ ] **Step 4: Прогнать — проходит**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_sync_freshness.FreshnessGateTest --settings=test_settings`
Expected: PASS.

- [ ] **Step 5: Встроить гейт и маркер во вьюху**

В `views.py` `timesheet_sync`, после чтения `date_from/date_to/is_scoped` (строка ~1440) и ДО `service = TimesheetSyncService(...)`:
```python
    from django.utils import timezone as _tz
    now = _tz.now()
    if not is_scoped and should_skip_timesheet_sync(request.bitrix24_account, now):
        from .report_queries import build_filtered_timesheet_queryset  # уже импортирован сверху — использовать существующий импорт
        db_count = TimesheetItem.objects.filter(**scope_to_tenant(request.bitrix24_account)).count()
        return JsonResponse({
            "status": "fresh",
            "count": db_count,
            "last_synced_at": request.bitrix24_account.last_timesheet_synced_at.isoformat(),
        })
```
После успешного синка, перед `response = JsonResponse(...)` (строка ~1467):
```python
    request.bitrix24_account.last_timesheet_synced_at = now
    request.bitrix24_account.save(update_fields=["last_timesheet_synced_at"])
```
И добавить `"last_synced_at": now.isoformat()` в тело успешного ответа.

- [ ] **Step 6: Статус-эндпоинт**

В `views.py` добавить:
```python
@xframe_options_exempt
@require_GET
@log_errors("timesheet_sync_status")
@auth_required
def timesheet_sync_status(request: AuthorizedRequest):
    acc = request.bitrix24_account
    count = TimesheetItem.objects.filter(**scope_to_tenant(acc)).count()
    last = acc.last_timesheet_synced_at
    return JsonResponse({
        "last_synced_at": last.isoformat() if last else None,
        "count": count,
    })
```
В `urls.py` рядом со строкой 55:
```python
    path('api/timesheet-sync-status', views.timesheet_sync_status, name='timesheet_sync_status'),
```
Добавить `"timesheet_sync_status"` в `__all__` списка вьюх (рядом со строкой 97-98).

- [ ] **Step 7: Прогнать все тесты синка (регресс)**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_sync_freshness main.tests_sync_threshold main.tests_sync_lock --settings=test_settings`
Expected: PASS (все).

- [ ] **Step 8: Коммит**

```bash
git add backends/python/api/main/views.py backends/python/api/main/urls.py backends/python/api/main/tests_sync_freshness.py
git commit -m "feat(sync): гейт свежести таймшитов + статус-эндпоинт + проставление маркера"
```

---

## Task 3: Планировщик — `--full` флаг и фоновые loop-ы таймшитов

**Files:**
- Modify: `backends/python/api/main/management/commands/sync_all_portals.py` (аргументы + вызов)
- Modify: `backends/python/api/main/sync_scheduler_service.py` (`run_scheduled_sync` поддержка full)
- Modify: `backends/python/api/start.sh` (добавить loop-ы)
- Test: `backends/python/api/main/tests_scheduled_sync.py` (дополнить — full-режим)

**Interfaces:**
- Consumes: существующий `run_scheduled_sync(days, scope)`.
- Produces: `run_scheduled_sync(days, scope, full=False)`; при `full=True` и `scope="timesheet"` вызывает `service.sync_all()` (без дат → `_sync_full`). Команда принимает `--full`.

- [ ] **Step 1: Падающий тест full-режима**

Дополнить `tests_scheduled_sync.py` (следовать существующему стилю файла — мокать `TimesheetSyncService`/аккаунты как там):
```python
def test_full_mode_calls_sync_all_without_dates(self):
    from unittest.mock import patch, MagicMock
    from . import sync_scheduler_service as sss
    with patch.object(sss, "TimesheetSyncService") as Svc, \
         patch.object(sss, "select_portal_accounts", return_value=[self.account]), \
         patch.object(sss, "ConfigurationService") as Cfg:
        Cfg.return_value.get_configuration_sync.return_value = {"sp_entity_type_id": 1, "auto_sync_enabled": True}
        inst = Svc.return_value
        inst.sync_all.return_value = 0
        sss.run_scheduled_sync(days=7, scope="timesheet", full=True)
        # full → без date_from/date_to
        _, kwargs = inst.sync_all.call_args
        self.assertIsNone(kwargs.get("date_from"))
        self.assertIsNone(kwargs.get("date_to"))
```

> Примечание: точные имена сетапа (`self.account`, фикстуры) взять из уже существующих тестов в `tests_scheduled_sync.py`; если файла/класса нет — создать по паттерну `tests_sync_threshold.py`.

- [ ] **Step 2: Прогнать — падает**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_scheduled_sync --settings=test_settings`
Expected: FAIL (`run_scheduled_sync` не принимает `full`).

- [ ] **Step 3: Реализовать full в `run_scheduled_sync`**

В `sync_scheduler_service.py`, сигнатуру и таймшит-ветку (строки 52, 92-105):
```python
def run_scheduled_sync(days: int = DEFAULT_WINDOW_DAYS, scope: str = "timesheet", full: bool = False) -> SyncRun:
```
В ветке `else:  # scope == "timesheet"` заменить вызов `service.sync_all(date_from=date_from, date_to=date_to)` на:
```python
                    if full:
                        count = service.sync_all()  # без дат → _sync_full (ночная сверка)
                    else:
                        count = service.sync_all(date_from=date_from, date_to=date_to)
```

- [ ] **Step 4: Прогнать — проходит**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_scheduled_sync --settings=test_settings`
Expected: PASS.

- [ ] **Step 5: Добавить `--full` в команду**

В `sync_all_portals.py` `add_arguments`:
```python
        parser.add_argument("--full", action="store_true", help="Полная сверка (scope=timesheet, без окна дат).")
```
В `handle`:
```python
        run = run_scheduled_sync(days=options["days"], scope=options["scope"], full=options["full"])
```

- [ ] **Step 6: Добавить loop-ы в start.sh**

В `start.sh` после строки 28 (проектный loop) добавить:
```bash
# Таймшиты: инкремент (scoped 7д) каждые 20 минут, off-request.
( while true; do sleep 1200; python manage.py sync_all_portals --scope timesheet || true; done ) &
# Таймшиты: полная ночная сверка раз в сутки (ловит удаления/пропуски).
( while true; do sleep 86400; python manage.py sync_all_portals --scope timesheet --full || true; done ) &
```

- [ ] **Step 7: Регресс всех sync-тестов**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_scheduled_sync main.tests_sync_threshold main.tests_sync_lock main.tests_sync_integration --settings=test_settings`
Expected: PASS.

- [ ] **Step 8: Коммит**

```bash
git add backends/python/api/main/management/commands/sync_all_portals.py backends/python/api/main/sync_scheduler_service.py backends/python/api/start.sh backends/python/api/main/tests_scheduled_sync.py
git commit -m "feat(sync): фоновый планировщик таймшитов (инкремент 20м + ночная полная сверка) + флаг --full"
```

---

## Task 4: Фронт — убрать авто-синк с открытия и генерации отчёта

**Files:**
- Modify: `frontend/app/pages/embedded.vue` (`reloadWorkspace`, строки 106-108)
- Modify: `frontend/app/composables/useReportGenerator.ts` (дефолт `willSync`, строка 61)

**Interfaces:**
- Consumes: `apiStore.syncTimesheets` (без изменений контракта).
- Produces: открытие/генерация не вызывают `syncTimesheets()` по умолчанию.

- [ ] **Step 1: Убрать фоновый синк в `embedded.vue`**

Заменить блок (строки 106-108):
```javascript
    apiStore.syncTimesheets().then(() => {
        projectCardCache.clear()
    }).catch(e => console.warn('[Embedded] Background sync failed', e))
```
на:
```javascript
    // Синк убран с открытия: данные читаются из БД, свежесть держит фоновый
    // планировщик + кнопка «Обновить». (Фаза 1 sync-offload.)
    projectCardCache.clear()
```

- [ ] **Step 2: Дефолт `willSync=false` в `useReportGenerator`**

В `useReportGenerator.ts` строка 61 заменить:
```javascript
      const willSync = config.syncTimesheets !== false
```
на:
```javascript
      // Синк выключен по умолчанию: отчёт формируется из БД мгновенно. Явный синк —
      // только когда вызвавший передал syncTimesheets: true. (Фаза 1 sync-offload.)
      const willSync = config.syncTimesheets === true
```

- [ ] **Step 3: Typecheck + сборка (проверка, что не сломали типы/шаблоны)**

Run: `cd frontend && NODE_OPTIONS="--max-old-space-size=4096" corepack pnpm@9.15.9 run build`
Expected: `✨ Build complete!` без ошибок.

- [ ] **Step 4: Прогнать фронт-тесты (регресс логики)**

Run: `cd frontend && corepack pnpm@9.15.9 dlx tsx --test 'tests/**/*.test.ts'`
Expected: все PASS (число не уменьшилось).

- [ ] **Step 5: Коммит**

```bash
git add frontend/app/pages/embedded.vue frontend/app/composables/useReportGenerator.ts
git commit -m "feat(sync): фронт не синкает таймшиты на открытии/генерации (читаем из БД)"
```

---

## Task 5: Фронт — индикатор «данные на ЧЧ:ММ» + кнопка «Обновить»

**Files:**
- Modify: `frontend/app/stores/api.ts` (добавить `getTimesheetSyncStatus`; «Обновить» = `syncTimesheets` с окном 30 дней)
- Modify: страница отчётов, где уместна шапка (например `frontend/app/pages/reports/project-report.client.vue` header, строки ~376-383) — индикатор + кнопка

**Interfaces:**
- Consumes: `GET /api/timesheet-sync-status` (Task 2), `apiStore.syncTimesheets(dateFrom, dateTo)`.
- Produces: `apiStore.getTimesheetSyncStatus(): Promise<{last_synced_at: string|null, count: number}>`; UI-индикатор + кнопка, дёргающая scoped-синк за последние 30 дней и перечитывающая данные.

- [ ] **Step 1: Метод статуса в сторе**

В `api.ts` рядом с `syncTimesheets` (после строки 583):
```javascript
    const getTimesheetSyncStatus = async (): Promise<{ last_synced_at: string | null; count: number }> => {
      return await $api('/api/timesheet-sync-status', {
        headers: { Authorization: `Bearer ${tokenJWT.value}` },
      })
    }
```
И добавить `getTimesheetSyncStatus` в возвращаемый объект стора (рядом со строкой 1067, где `syncTimesheets`).

- [ ] **Step 2: «Обновить» = scoped-синк за 30 дней (быстро, не полный)**

На странице отчёта добавить обработчик (пример для `project-report.client.vue`, в `<script setup>`):
```javascript
const lastSyncedAt = ref<string | null>(null)
const isRefreshing = ref(false)

async function loadSyncStatus() {
    try { lastSyncedAt.value = (await apiStore.getTimesheetSyncStatus()).last_synced_at }
    catch { /* индикатор не критичен */ }
}

async function refreshTimesheets() {
    if (isRefreshing.value) return
    isRefreshing.value = true
    try {
        const to = new Date()
        const from = new Date(); from.setDate(from.getDate() - 30)
        const iso = (d: Date) => d.toISOString().slice(0, 10)
        await apiStore.syncTimesheets(iso(from), iso(to))  // scoped → быстрый путь + гейт свежести
        await loadSyncStatus()
        await fetchData()  // существующая перезагрузка данных страницы
    } finally { isRefreshing.value = false }
}
```
Вызвать `loadSyncStatus()` в `onMounted`.

- [ ] **Step 3: Индикатор + кнопка в шапке**

В шапке (`<header>`, ~строка 376) добавить:
```html
<div class="flex items-center gap-2 text-xs text-slate-500">
    <span v-if="lastSyncedAt">данные на {{ new Date(lastSyncedAt).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) }}</span>
    <button :disabled="isRefreshing" @click="refreshTimesheets" class="px-2 py-1 border rounded hover:bg-slate-50 disabled:opacity-50">
        {{ isRefreshing ? 'Обновляю…' : 'Обновить' }}
    </button>
</div>
```

- [ ] **Step 4: Typecheck + сборка**

Run: `cd frontend && NODE_OPTIONS="--max-old-space-size=4096" corepack pnpm@9.15.9 run build`
Expected: `✨ Build complete!`.

- [ ] **Step 5: Коммит**

```bash
git add frontend/app/stores/api.ts frontend/app/pages/reports/project-report.client.vue
git commit -m "feat(sync): индикатор «данные на ЧЧ:ММ» + кнопка «Обновить» (scoped-синк)"
```

---

## Self-Review (заполнить при исполнении)

- **Spec coverage (Фаза 1 §14):** убрать авто-синк таймшитов (Task 4) ✓; инкремент/ночная сверка по расписанию (Task 3) ✓; гейт свежести (Task 2) ✓; индикатор (Task 5) ✓. Инкремент по `updatedTime` (тоньше 7-дн scoped) — сознательно в Фазу 1b (релиф даёт и scoped). Проекты/юзеры/write-through — Фазы 2–3.
- **Placeholder scan:** тест в Task 2 Step 1 намеренно черновой — Step 3 переписывает его на чистый хелпер (исполнителю следовать Step 3).
- **Type consistency:** `should_skip_timesheet_sync(account, now, gate_minutes)`, `last_timesheet_synced_at`, `/api/timesheet-sync-status`, `getTimesheetSyncStatus` — имена согласованы между Task 1/2/5.

## Definition of Done (Фаза 1)

- Все бэк-тесты (`tests_sync_freshness`, `tests_scheduled_sync`, `tests_sync_*`) зелёные.
- Фронт: `build` OK, `tsx --test` не уменьшил число проходящих.
- Ручная проверка после merge+деплой: открытие отчёта не шлёт `POST /api/sync-timesheets` (видно в Network); фоновый синк идёт из планировщика; «Обновить» отрабатывает за секунды; индикатор показывает время.
