# Sync Offload — Фаза 3 (проекты + write-through) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Проекты переходят на ту же read-model-модель, что и таймшиты в Фазе 1: доска проектов читает `project_card` из БД со своим фоновым расписанием (инкремент + существующая частая полная сверка), с гейтом свежести, маркером `last_project_synced_at` и индикатором/кнопкой «Обновить». Плюс write-through — правки таймшитов и карточек проектов сразу отражаются в локальной БД без ожидания следующего фонового синка, тем же нормализатором, что и массовый синк.

**Architecture:** Bitrix = источник истины; БД — быстрая копия. Фаза 3 продолжает Фазу 1 (см. «Контекст и допущения» ниже — что подтверждено реальным кодом, а что реконструировано для ещё не приземлившихся файлов). Для проектов: `ProjectSyncService.sync(incremental_since_minutes=…)` уже умеет инкремент — не пишем новый алгоритм синка, только (1) гейт свежести + маркер на `/api/project-board/sync` (по образцу Задачи 2 Фазы 1), (2) фоновый инкремент-луп в `start.sh` (по образцу Задачи 3 Фазы 1), (3) кнопку «Обновить» + индикатор на доске проектов (по образцу Задачи 5 Фазы 1). Write-through для таймшитов — новый лёгкий путь `upsert_one`/`remove_one` в `TimesheetSyncService`, использующий ТЕ ЖЕ `normalize_items`/`_save_batch`, что и `_sync_full`/`_sync_scoped`, чтобы строка в БД была идентична строке из массового синка. Write-through для карточек проектов — при чтении кода выяснилось, что он уже реализован (local-first: `ProjectCardService.update_project_card/update_stage/archive_project` пишут в локальную `ProjectCard` немедленно, а в Bitrix — best-effort после; см. «Контекст и допущения», пункт 3); эта фаза закрывает пробел регресс-тестами, а не дублирующим кодом. Write-through — оптимизация путей "сохранение в приложении", а не замена синка: ~10% правок происходит вручную прямо в Bitrix (без прохода через приложение) — синк (инкремент + полная сверка) остаётся единственным механизмом, который их видит, и не удаляется/не ослабляется ни в одном шаге ниже.

**Tech Stack:** Django 5 (Postgres, `managed=True` модели), b24pysdk, gunicorn (gthread, WSGI); Nuxt 4 / Vue 3 (Pinia store `api.ts`). Тесты бэка: `manage.py test --settings=test_settings`.

## Global Constraints

(скопировано дословно из плана Фазы 1 — остаётся в силе)

- Ветка: `feat/sync-offload-read-model` (от `prod_2026`; НЕ пушить в prod_2026 — авто-деплой).
- Тесты бэка запускать из `backends/python/api`: `./.venv/bin/python manage.py test main.<module> --settings=test_settings` (если `.venv` нет — `python manage.py test ... --settings=test_settings`).
- Django-миграции: `managed=True`, генерировать `makemigrations main`; в проде миграции — отдельный release-step (см. `start.sh:8-10`), не в рантайме.
- Паттерн тестов синка: `_FakeClient` с `_bitrix_token=self` и `call_method(method, params)` (см. `main/tests_sync_threshold.py`).
- Гейт свежести по умолчанию **N=3 мин**; интервал фонового инкремента **20 мин**; ночная сверка **есть**.
- Фронт: не менять публичные контракты сторов сверх описанного; сборка `NODE_OPTIONS="--max-old-space-size=4096" corepack pnpm@9.15.9 run build`, тесты `corepack pnpm@9.15.9 dlx tsx --test 'tests/**/*.test.ts'` из `frontend/`.
- Ничего не удаляем из данных: изменения только в путях синка/чтения, не в orphan-логике `_sync_full`.

Дополнительно для Фазы 3:

- Как и в Фазе 1: нет отдельного юнит-теста на Vue-компоненты/сторы в проекте (см. `tests/` — только тесты чистых функций/composables). Фронт-задачи верифицируются `build` + typecheck + регрессом существующих `tsx --test`, без новых `.test.ts`.
- `docs/incidents/2026-07-27-task-tab-slow.md` и дизайн-спека (`docs/superpowers/specs/2026-07-27-local-read-model-sync-offload-design.md`) не меняются этим планом.

## Контекст и допущения

**1. Реальное состояние ворктри `sync-offload` на момент написания плана (с учётом конкурентных изменений).** Ветка `feat/sync-offload-read-model` — общая и активно менялась другой сессией прямо во время написания этого плана (тот же эффект независимо отмечен в `phase-2-plan-report.md` для параллельной Фазы 2). Хронология по ходу работы над этим планом (три последовательных перепроверки `git log`): при первом чтении были закоммичены только Задачи 1–2 Фазы 1 (`991ed25`, `ee73deb`); к середине работы добавилась Задача 3 (`006814e`, планировщик + `--full`, ревью `task-3-report.md`); к моменту финализации добавилась ЕЩЁ и Задача 4 (`a05ea54`, «фронт не синкает таймшиты на открытии/генерации») — подтверждено грепом реальных `embedded.vue`/`useReportGenerator.ts`, совпадает с брифом дословно. На момент сдачи плана НЕ закоммичена только Задача 5 Фазы 1 (`api.ts` → `getTimesheetSyncStatus`; индикатор/кнопка в `project-report.client.vue`) — есть `task-5-brief.md`, нет `task-5-report.md`; брифы 4 и 5 идентичны исходному тексту плана Фазы 1, и Задача 4 landed ТОЧНО по брифу — это повышает уверенность, что и Задача 5 landed будет так же. Задачи 1–4 этого плана (маркер/гейт/статус/планировщик проектов, write-through backend) построены на реальном коде без реконструкции. Задачи 5 и 7 этого плана (фронт: `api.ts`/`task.vue`/`embedded.vue`/`project-report.client.vue`/`projects/index.client.vue`) частично опираются на реконструкцию ТОЛЬКО там, где затрагивается `getTimesheetSyncStatus`/индикатор Задачи 5 Фазы 1 (см. Task 5, Step 1 — формулировка «если Фаза 1 Задача 5 уже смержена» учитывает оба варианта). **Если между финализацией этого плана и его исполнением ветка снова изменится (продемонстрированная закономерность) — перед исполнением Задач 5 и 7 обязательна повторная `git log`/чтение `api.ts`/`project-report.client.vue` — так же, как было сделано здесь для Задач 3–4.**

**2. Поправка к планировщику — подтверждена реальным кодом, не догадкой.** Реальный `sync_scheduler_service.py` (после `006814e`) уже проставляет `account.last_timesheet_synced_at = timezone.now()` внутри `with account_sync_lock(account, scope="timesheet"):`, сразу после `service.sync_all(...)`, — это и есть carry-forward из ревью Задачи 2, зафиксированный в `progress.md` («scheduler должен обновлять маркер, иначе индикатор не отражает фон»), уже реализованный именно так. Задача 3 этого плана (ниже) добавляет СИММЕТРИЧНУЮ строку в project-ветку (`account.last_project_synced_at`, тот же паттерн — внутри `with account_sync_lock(..., scope="project")`, свежий `timezone.now()` в момент завершения синка ЭТОГО портала, а не общий `now` с начала функции для всех порталов) плюс параметр `incremental_minutes` — это единственные изменения в файле.

**3. Два пункта дизайн-спеки, которые при чтении реального кода оказались уже закрыты — важно не задублировать:**
   - **«Убрать синк с открытия» (§4.2, §1) для `projects/index.client.vue`.** Дизайн и входной бриф этой задачи указывают на `projects/index.client.vue:403` (`await apiStore.syncProjectCards()`) как на триггер синка при открытии. Полное чтение файла показало: `onMounted` (строки 560–581) вызывает только `loadMeta()`/`loadBoard()` — оба чистый `GET`-запрос на чтение из БД (`ProjectCardService.get_board_data()`/`get_meta()`, без обращений к Bitrix). Строка 403 — это `syncProjectCards()` внутри `syncBoard()`, которая вызывается ТОЛЬКО по клику на кнопки «Синхронизировать проекты» (строка 603) и «Синхронизировать сейчас» в пустом состоянии (строка 726) — обе явные, пользовательские, не автоматические. Открытие доски проектов уже мгновенное и уже читает из БД. **Никакого кода на «убрать синк с открытия» в этом плане нет** — раздел (А) ниже покрывает только то, чего реально не хватает: расписание инкремента + гейт/маркер/статус + кнопка «Обновить».
   - **«Write-through для карточек проектов» (§4.2, §5.1).** `ProjectCardService.update_project_card/update_stage/archive_project` (`project_board_service.py:387-488`) уже пишут в локальную `ProjectCard` (`card.save(...)`) либо ДО попытки записи в Bitrix (`update_stage`, `archive_project`), либо независимо от её результата (`update_project_card` — Bitrix-вызов в `try/except`, который только копит warning, не блокирует `card.save()`). To есть «backend там уже пишет в Bitrix — добавить upsert в project_card» из спеки уже верно в обратную сторону: backend уже пишет в БД первым, а в Bitrix — best-effort вторым. У этих трёх методов при этом НЕТ отдельного теста, фиксирующего этот инвариант. Задача 6 закрывает это регресс-тестами, а не новым кодом записи (это было бы дублирование).

## Task 1: Модель — маркер `last_project_synced_at`

**Files:**
- Modify: `backends/python/api/main/models.py` (класс `Bitrix24Account`, сразу после `last_timesheet_synced_at`, строка 41)
- Create: `backends/python/api/main/migrations/0017_bitrix24account_last_project_synced_at.py` (через `makemigrations`)
- Test: `backends/python/api/main/tests_sync_freshness.py` (дополнить — файл уже существует, Задача 1-2 Фазы 1)

**Interfaces:**
- Produces: поле `Bitrix24Account.last_project_synced_at: Optional[datetime]` (null по умолчанию), симметрично `last_timesheet_synced_at`.

- [ ] **Step 1: Написать падающий тест наличия поля**

В `tests_sync_freshness.py` (реальный текущий файл, 50 строк — см. ниже класс `LastSyncedFieldTest`, к которому это симметрично) добавить:
```python
class LastProjectSyncedFieldTest(TestCase):
    def test_field_defaults_to_none_and_persists(self):
        acc = Bitrix24Account.objects.create(
            b24_user_id=10, is_b24_user_admin=True, member_id="m10",
            is_master_account=True, domain_url="ex10.bitrix24.ru",
            status="active", application_version=1,
        )
        self.assertIsNone(acc.last_project_synced_at)
        now = timezone.now()
        acc.last_project_synced_at = now
        acc.save(update_fields=["last_project_synced_at"])
        acc.refresh_from_db()
        self.assertEqual(acc.last_project_synced_at, now)
```

- [ ] **Step 2: Прогнать — падает**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_sync_freshness.LastProjectSyncedFieldTest --settings=test_settings`
Expected: FAIL (`AttributeError`/`FieldError`: `last_project_synced_at`).

- [ ] **Step 3: Добавить поле в модель**

В `models.py`, в `Bitrix24Account` сразу после (реальная строка 41):
```python
    last_timesheet_synced_at = models.DateTimeField(null=True, blank=True)
```
добавить:
```python
    last_project_synced_at = models.DateTimeField(null=True, blank=True)
```

- [ ] **Step 4: Сгенерировать миграцию**

Run: `cd backends/python/api && ./.venv/bin/python manage.py makemigrations main --settings=test_settings`
Expected: создан `main/migrations/0017_bitrix24account_last_project_synced_at.py` (следующий номер после реального `0016_bitrix24account_last_timesheet_synced_at.py`) с `AddField(... last_project_synced_at ...)`.

- [ ] **Step 5: Прогнать — проходит**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_sync_freshness --settings=test_settings`
Expected: PASS (весь файл, включая существующие тесты Фазы 1 — регресс).

- [ ] **Step 6: Коммит**

```bash
git add backends/python/api/main/models.py backends/python/api/main/migrations/ backends/python/api/main/tests_sync_freshness.py
git commit -m "feat(sync): маркер last_project_synced_at на Bitrix24Account"
```

---

## Task 2: Гейт свежести + маркер + статус-эндпоинт для проектов

**Files:**
- Modify: `backends/python/api/main/views.py` (новый хелпер `should_skip_project_sync` перед `sync_project_board` — реальная строка 719; тело `sync_project_board` — строки 726-753; новый `project_sync_status`; `__all__` — строка 71)
- Modify: `backends/python/api/main/urls.py` (новый маршрут рядом со строкой 30)
- Test: `backends/python/api/main/tests_sync_freshness.py` (дополнить)

**Interfaces:**
- Consumes: `Bitrix24Account.last_project_synced_at` (Task 1); существующий `ProjectSyncService.sync(incremental_since_minutes)`.
- Produces: `sync_project_board` при свежести <N мин **и без `incremental_since_minutes`** возвращает `{"status":"fresh","count":<db>,"last_synced_at":<iso>}` без вызова Bitrix; инкрементальные вызовы (`?incremental_since_minutes=…`) гейт ОБХОДЯТ — быстрый путь для кнопки «Обновить» (Task 7) должен всегда доезжать до Bitrix, как в Фазе 1 scoped-таймшитах. При реальном синке (гейт пропустил или инкремент) — проставляет маркер, добавляет `last_synced_at` в ответ. Новый `GET /api/project-sync-status` → `{"last_synced_at":<iso|null>,"count":<int>}`.

- [ ] **Step 1: Падающий тест гейта (хелпер, без вьюхи — как в Фазе 1 Задаче 2)**

По прецеденту `TimesheetSyncGateHelperTest` (реальный, уже в файле — вьюха не тестируется напрямую из-за декораторов `auth_required`/`sync_lock`/`rate_limit`, гейт тестируется как чистая функция) добавить:
```python
class ProjectSyncGateHelperTest(TestCase):
    def _acc(self, last=None):
        return Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m11",
            is_master_account=True, domain_url="ex11.bitrix24.ru",
            status="active", application_version=1,
            last_project_synced_at=last,
        )

    def test_helper_skips_when_fresh(self):
        from .views import should_skip_project_sync
        acc = self._acc(last=timezone.now() - timedelta(minutes=1))
        self.assertTrue(should_skip_project_sync(acc, timezone.now()))

    def test_helper_syncs_when_stale(self):
        from .views import should_skip_project_sync
        acc = self._acc(last=timezone.now() - timedelta(minutes=10))
        self.assertFalse(should_skip_project_sync(acc, timezone.now()))

    def test_helper_syncs_when_never(self):
        from .views import should_skip_project_sync
        acc = self._acc(last=None)
        self.assertFalse(should_skip_project_sync(acc, timezone.now()))
```
(`timedelta` уже импортирован в файле — использован `FreshnessGateTest`.)

- [ ] **Step 2: Прогнать — падает**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_sync_freshness.ProjectSyncGateHelperTest --settings=test_settings`
Expected: FAIL (нет `should_skip_project_sync`).

- [ ] **Step 3: Реализовать хелпер**

В `views.py` перед `sync_project_board` (реальная строка 719, прямо перед декораторами) добавить:
```python
PROJECT_SYNC_GATE_MINUTES = 3


def should_skip_project_sync(account, now, gate_minutes=PROJECT_SYNC_GATE_MINUTES):
    """Гейт свежести для проектов — симметрично should_skip_timesheet_sync (Фаза 1, Задача 2).

    account.last_project_synced_at is None -> никогда не синкали -> False (синкать).
    """
    last = account.last_project_synced_at
    if last is None:
        return False
    return (now - last).total_seconds() < gate_minutes * 60
```

- [ ] **Step 4: Прогнать — проходит**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_sync_freshness --settings=test_settings`
Expected: PASS.

- [ ] **Step 5: Встроить гейт и маркер в `sync_project_board`**

Реальное текущее тело (строки 726-753):
```python
def sync_project_board(request: AuthorizedRequest):
    service = ProjectSyncService(request.bitrix24_account.client, request.bitrix24_account)
    incremental_raw = request.GET.get("incremental_since_minutes")
    incremental_since_minutes = None
    if incremental_raw:
        try:
            incremental_since_minutes = int(incremental_raw)
        except (TypeError, ValueError):
            return JsonResponse({"error": "incremental_since_minutes must be integer"}, status=400)
    try:
        return JsonResponse(service.sync(incremental_since_minutes=incremental_since_minutes))
    except Exception:
        logger.exception("Project board sync failed for account %s", request.bitrix24_account.pk)
        return JsonResponse(
            {
                "status": "warning",
                "sync_mode": "failed",
                "synced": 0,
                "created": 0,
                "updated": 0,
                "skipped_missing_group_link": 0,
                "skipped_conflict_linking": 0,
                "warning": (
                    "Синхронизацию проектов выполнить не удалось. "
                    "Показаны последние сохраненные данные."
                ),
            }
        )
```
Заменить на:
```python
def sync_project_board(request: AuthorizedRequest):
    incremental_raw = request.GET.get("incremental_since_minutes")
    incremental_since_minutes = None
    if incremental_raw:
        try:
            incremental_since_minutes = int(incremental_raw)
        except (TypeError, ValueError):
            return JsonResponse({"error": "incremental_since_minutes must be integer"}, status=400)

    now = timezone.now()
    # Гейт применяется только к "полному" вызову (без incremental_since_minutes) — как
    # is_scoped в timesheet_sync (Фаза 1, Задача 2): явный инкремент — дешёвый и должен
    # всегда доезжать до Bitrix (кнопка «Обновить», Task 7).
    if incremental_since_minutes is None and should_skip_project_sync(request.bitrix24_account, now):
        db_count = ProjectCard.objects.filter(**scope_to_tenant(request.bitrix24_account)).count()
        return JsonResponse({
            "status": "fresh",
            "count": db_count,
            "last_synced_at": request.bitrix24_account.last_project_synced_at.isoformat(),
        })

    service = ProjectSyncService(request.bitrix24_account.client, request.bitrix24_account)
    try:
        result = service.sync(incremental_since_minutes=incremental_since_minutes)
    except Exception:
        logger.exception("Project board sync failed for account %s", request.bitrix24_account.pk)
        return JsonResponse(
            {
                "status": "warning",
                "sync_mode": "failed",
                "synced": 0,
                "created": 0,
                "updated": 0,
                "skipped_missing_group_link": 0,
                "skipped_conflict_linking": 0,
                "warning": (
                    "Синхронизацию проектов выполнить не удалось. "
                    "Показаны последние сохраненные данные."
                ),
            }
        )

    request.bitrix24_account.last_project_synced_at = now
    request.bitrix24_account.save(update_fields=["last_project_synced_at"])
    result["last_synced_at"] = now.isoformat()
    return JsonResponse(result)
```
(`ProjectCard`, `scope_to_tenant`, `timezone` уже импортированы в `views.py` — новых импортов не требуется.)

- [ ] **Step 6: Статус-эндпоинт**

В `views.py` сразу после `sync_project_board` добавить:
```python
@xframe_options_exempt
@require_GET
@log_errors("project_sync_status")
@auth_required
def project_sync_status(request: AuthorizedRequest):
    acc = request.bitrix24_account
    count = ProjectCard.objects.filter(**scope_to_tenant(acc)).count()
    last = acc.last_project_synced_at
    return JsonResponse({
        "last_synced_at": last.isoformat() if last else None,
        "count": count,
    })
```
В `urls.py` рядом с реальной строкой 30 (`path('api/project-board/sync', ...)`):
```python
    path('api/project-sync-status', views.project_sync_status, name='project_sync_status'),
```
В `views.py` добавить `"project_sync_status"` в `__all__` рядом с `"sync_project_board"` (реальная строка 71).

- [ ] **Step 7: Прогнать все тесты синка (регресс)**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_sync_freshness main.tests_sync_threshold main.tests_sync_lock main.tests_project_fetch_keyset --settings=test_settings`
Expected: PASS (все).

- [ ] **Step 8: Коммит**

```bash
git add backends/python/api/main/views.py backends/python/api/main/urls.py backends/python/api/main/tests_sync_freshness.py
git commit -m "feat(sync): гейт свежести проектов + статус-эндпоинт + проставление маркера"
```

---

## Task 3: Планировщик — фоновый инкремент проектов + маркер из планировщика

> Baseline этой задачи — РЕАЛЬНЫЙ код, не реконструкция: Задача 3 Фазы 1 (`006814e`) была закоммичена и прошла ревью (`task-3-report.md`) во время написания этого плана (см. «Контекст и допущения», пункты 1-2); все фрагменты кода ниже — дословные цитаты фактического `sync_scheduler_service.py`/`sync_all_portals.py`/`start.sh`/`tests_scheduled_sync.py` на момент финализации плана. Единственный риск — если ветка изменится СНОВА между финализацией плана и его исполнением; в этом случае перед Step 3 быстро сверить реальный файл с блоком ниже (`git diff` покажет расхождение, если оно есть).

**Files:**
- Modify: `backends/python/api/main/sync_scheduler_service.py` (`run_scheduled_sync` — добавить `incremental_minutes` для project-ветки + маркер `last_project_synced_at`; докстринг модуля)
- Modify: `backends/python/api/main/management/commands/sync_all_portals.py` (`--incremental-minutes`; докстринг/help)
- Modify: `backends/python/api/start.sh` (новый project-инкремент-луп)
- Test: `backends/python/api/main/tests_scheduled_sync.py` (дополнить — уже есть `RunScheduledSyncProjectScopeTest` с 5 тестами)

**Interfaces:**
- Consumes: реальный `run_scheduled_sync(days, scope, full=False)` (Фаза 1, Задача 3, `006814e`) — уже проставляет `account.last_timesheet_synced_at` в timesheet-ветке.
- Produces: `run_scheduled_sync(days, scope, full=False, incremental_minutes=None)`; при `scope="project"` вызывает `ProjectSyncService.sync(incremental_since_minutes=incremental_minutes)` (`None` → полный синк, поведение по умолчанию не меняется) и при успехе проставляет `account.last_project_synced_at` — тем же паттерном (свежий `timezone.now()` внутри `with account_sync_lock(...)`), что уже применён к timesheet-ветке. Команда принимает `--incremental-minutes N`.

- [ ] **Step 1: Падающий тест — инкремент передаётся в `ProjectSyncService.sync`**

Дополнить `tests_scheduled_sync.py`, класс `RunScheduledSyncProjectScopeTest` (реальный, уже в файле):
```python
    @patch("main.sync_scheduler_service.ProjectSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_project_scope_incremental_minutes_passed_to_service(self, mock_cfg_cls, mock_proj_cls):
        """incremental_minutes=20 -> ProjectSyncService.sync(incremental_since_minutes=20)."""
        _account("m1", master=True)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg
        mock_proj = MagicMock()
        mock_proj.sync.return_value = {"synced": 3, "created": 1, "updated": 2}
        mock_proj_cls.return_value = mock_proj

        run_scheduled_sync(scope="project", incremental_minutes=20)

        _, kwargs = mock_proj.sync.call_args
        self.assertEqual(kwargs.get("incremental_since_minutes"), 20)

    @patch("main.sync_scheduler_service.ProjectSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_project_scope_full_by_default(self, mock_cfg_cls, mock_proj_cls):
        """Без incremental_minutes — поведение не меняется: полный синк (None)."""
        _account("m1", master=True)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg
        mock_proj = MagicMock()
        mock_proj.sync.return_value = {"synced": 1, "created": 0, "updated": 1}
        mock_proj_cls.return_value = mock_proj

        run_scheduled_sync(scope="project")

        _, kwargs = mock_proj.sync.call_args
        self.assertIsNone(kwargs.get("incremental_since_minutes"))

    @patch("main.sync_scheduler_service.ProjectSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_project_scope_success_sets_last_project_synced_at(self, mock_cfg_cls, mock_proj_cls):
        """Успешный плановый синк проставляет маркер — иначе индикатор (Task 7) не видит фон."""
        account = _account("m1", master=True)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {"auto_sync_enabled": True}
        mock_cfg_cls.return_value = mock_cfg
        mock_proj = MagicMock()
        mock_proj.sync.return_value = {"synced": 1, "created": 0, "updated": 1}
        mock_proj_cls.return_value = mock_proj

        run_scheduled_sync(scope="project")

        account.refresh_from_db()
        self.assertIsNotNone(account.last_project_synced_at)
```

- [ ] **Step 2: Прогнать — падает**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_scheduled_sync.RunScheduledSyncProjectScopeTest --settings=test_settings`
Expected: FAIL (`run_scheduled_sync` не принимает `incremental_minutes`; маркер не проставляется).

- [ ] **Step 3: Реализовать в `run_scheduled_sync`**

Импорт: добавить `Optional` (реальная строка 27, сейчас `from typing import List`):
```python
from typing import List, Optional
```
Сигнатура (реальная строка 57):
```python
def run_scheduled_sync(
    days: int = DEFAULT_WINDOW_DAYS,
    scope: str = "timesheet",
    full: bool = False,
    incremental_minutes: Optional[int] = None,
) -> SyncRun:
```
Реальное текущее тело project-ветки (строки 81-95) — маркер там пока не проставляется (в отличие от timesheet-ветки чуть ниже, строки 103-118, куда его уже добавила Задача 3 Фазы 1):
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
```
Заменить на (добавлен `incremental_since_minutes` и маркер — ТЕМ ЖЕ паттерном, что уже применён к timesheet-ветке: свежий `timezone.now()` внутри `with account_sync_lock(...)`, а не общий `now` с начала функции, который используется только для `date_from`/`date_to` таймшитов):
```python
            if scope == "project":
                try:
                    with account_sync_lock(account, scope="project"):
                        service = ProjectSyncService(account.client, account)
                        result = service.sync(incremental_since_minutes=incremental_minutes)
                        # Маркер «данные свежи на» для индикатора доски проектов (Task 7) —
                        # тот же паттерн, что уже применён к timesheet-ветке ниже (Фаза 1,
                        # Задача 3): без него фоновые синки не двигают индикатор.
                        account.last_project_synced_at = timezone.now()
                        account.save(update_fields=["last_project_synced_at"])
                except SyncLockBusy:
                    logger.info("Portal %s project-sync skipped: lock busy.",
                                account.member_id)
                    continue

                # ProjectSyncService.sync() возвращает dict с ключами synced/created/updated
                count = result.get("synced", 0) if isinstance(result, dict) else 0
                synced += 1
                items_total += int(count or 0)
                logger.info("Scheduled project-sync portal %s: %s items.", account.member_id, count)
```
Timesheet-ветка (реальные строки 97-122) НЕ меняется — она уже содержит маркер:
```python
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
Заодно дополнить модульный докстринг (реальные строки 1-23) — он уже точно описывает timesheet-маркер, добавить симметричную фразу для project. В абзаце «После успешного синка представительного аккаунта в ветке timesheet проставляется account.last_timesheet_synced_at…» после этого предложения добавить: «То же самое, начиная с этой фазы, происходит в ветке project (`account.last_project_synced_at`) — для индикатора доски проектов.» И в списке `scope="project"` дописать про инкремент: `- scope="project": полный синк проектов (ProjectSyncService.sync()), раз в 3 часа; с incremental_minutes=N — инкремент по updatedTime за N минут, фоновый цикл каждые 20 минут.`

- [ ] **Step 4: Прогнать — проходит**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_scheduled_sync --settings=test_settings`
Expected: PASS (весь файл — включая существующие тесты Фазы 1, регресс).

- [ ] **Step 5: Добавить `--incremental-minutes` в команду**

`sync_all_portals.py`, `add_arguments` (после реального `--full`, уже в файле):
```python
        parser.add_argument(
            "--incremental-minutes",
            type=int,
            default=None,
            help="Инкремент по updatedTime за N минут (только scope=project; без флага — полный синк).",
        )
```
`handle`:
```python
    def handle(self, *args, **options):
        days = options["days"]
        scope = options["scope"]
        run = run_scheduled_sync(
            days=days,
            scope=scope,
            full=options["full"],
            incremental_minutes=options["incremental_minutes"],
        )
        self.stdout.write(
            f"Scheduled sync done: scope={run.scope}, status={run.status}, "
            f"portals {run.portals_synced}/{run.portals_total}, "
            f"items={run.items_synced}, window={run.window_days}d."
        )
```
Реальный `help` команды (Задача 3 Фазы 1 уже обновила его корректно — таймшиты по расписанию упомянуты) дополнить упоминанием нового флага:
```python
class Command(BaseCommand):
    help = (
        "Фоновый синк по всем настроенным порталам. "
        "--scope project: синк проектов (используется встроенным планировщиком, раз в 3 ч; "
        "с --incremental-minutes N — инкремент по updatedTime, встроенный планировщик каждые 20 мин). "
        "--scope timesheet: инкрементальный синк трудозатрат (встроенный планировщик, каждые 20 мин; "
        "с --full — полная ночная сверка раз в сутки)."
    )
```
Аналогично дополнить строку `Usage` в модульном докстринге файла (реальные строки 1-20) примером `python manage.py sync_all_portals --scope project --incremental-minutes 20  # инкремент (встроенный планировщик, 20 мин)`.

- [ ] **Step 6: Добавить project-инкремент-луп в `start.sh`**

Реальный текущий фрагмент (строки 29-37 — комментарий-заголовок и три лупа, добавленные Фазой 1 Задачей 3):
```bash
# Встроенный планировщик (App Platform не имеет внешнего cron): три независимых
# фоновых цикла — отдельные дочерние процессы, переживают exec gunicorn. Сначала
# спим в каждом, чтобы не конкурировать со стартом/миграциями; advisory-lock
# (per-scope: project/timesheet) защищает от дублей при нескольких инстансах
# App Platform. Падение одной итерации (|| true) не убивает цикл.

# Проекты: полный синк раз в 3 часа.
( while true; do sleep 10800; python manage.py sync_all_portals --scope project || true; done ) &

# Таймшиты: инкремент (scoped 7д) каждые 20 минут, off-request.
( while true; do sleep 1200; python manage.py sync_all_portals --scope timesheet || true; done ) &
# Таймшиты: полная ночная сверка раз в сутки (ловит удаления/пропуски).
( while true; do sleep 86400; python manage.py sync_all_portals --scope timesheet --full || true; done ) &

exec gunicorn wsgi:application \
```
Вставить новый луп СРАЗУ после строки полного project-лупа (перед таймшит-лупами — группировка по домену: сначала оба project-лупа, потом оба timesheet):
```bash
( while true; do sleep 10800; python manage.py sync_all_portals --scope project || true; done ) &
# Проекты: инкремент по updatedTime каждые 20 минут, off-request. Полный синк выше (раз в
# 3ч) уже даёт больше "ночной сверки" по спеке (§5.3) — не понижаем его частоту, только
# добавляем быстрый инкремент между полными проходами.
( while true; do sleep 1200; python manage.py sync_all_portals --scope project --incremental-minutes 20 || true; done ) &
# Таймшиты: инкремент (scoped 7д) каждые 20 минут, off-request.
( while true; do sleep 1200; python manage.py sync_all_portals --scope timesheet || true; done ) &
# Таймшиты: полная ночная сверка раз в сутки (ловит удаления/пропуски).
( while true; do sleep 86400; python manage.py sync_all_portals --scope timesheet --full || true; done ) &

exec gunicorn wsgi:application \
```
Примечание (обоснование, что full project-луп НЕ трогаем): спека §5.3 просит «ночную полную сверку раз в сутки»; текущий full-project-луп уже бежит раз в 3 часа — это чаще и, соответственно, безопаснее (быстрее ловит удаления/переименования), чем ночная. Понижать частоту ради буквального следования формулировке — не требуется и увеличивает риск; используем существующий 3-часовой луп как основную сверку, инкремент — только дополнение для свежести между проходами.

- [ ] **Step 7: Регресс всех sync-тестов**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_scheduled_sync main.tests_sync_threshold main.tests_sync_lock main.tests_sync_integration main.tests_sync_freshness --settings=test_settings`
Expected: PASS.

- [ ] **Step 8: Коммит**

```bash
git add backends/python/api/main/sync_scheduler_service.py backends/python/api/main/management/commands/sync_all_portals.py backends/python/api/start.sh backends/python/api/main/tests_scheduled_sync.py
git commit -m "feat(sync): фоновый инкремент проектов (20м) + маркер last_project_synced_at из планировщика"
```

---

## Task 4: Backend — write-through для таймшитов (`upsert-one` / `remove-one`)

**Files:**
- Modify: `backends/python/api/main/timesheet_sync_service.py` (новые методы `upsert_one`, `remove_one`, `_extract_item`)
- Modify: `backends/python/api/main/views.py` (новые вьюхи `timesheet_upsert_one`, `timesheet_remove_one`; `__all__`)
- Modify: `backends/python/api/main/urls.py` (новые маршруты рядом со строками 54-55)
- Test: `backends/python/api/main/tests_timesheet_write_through.py` (новый файл)

**Interfaces:**
- Consumes: существующие `self.processing_service.normalize_items` и `self._save_batch` (ТЕ ЖЕ, что использует `_sync_full`/`_sync_scoped` — строка совпадает со строкой из массового синка, не ad-hoc парсинг).
- Produces: `TimesheetSyncService.upsert_one(bitrix_id: int) -> Dict[str, Any]` (тянет один элемент `crm.item.get`, нормализует, сохраняет через `_save_batch`); `TimesheetSyncService.remove_one(bitrix_id: int) -> Dict[str, Any]` (удаляет ровно эту строку локально, Bitrix не трогает — элемент там уже удалён вызывающим). `POST /api/timesheets/upsert-one {"id": <bitrix_id>}`, `POST /api/timesheets/remove-one {"id": <bitrix_id>}`.

- [ ] **Step 1: Падающие тесты `upsert_one`**

Создать `backends/python/api/main/tests_timesheet_write_through.py`:
```python
"""Тесты write-through: upsert-one / remove-one для одной записи таймшита (Фаза 3).

Паттерн _FakeClient — как в tests_sync_threshold.py / tests_sync_integration.py.

Запуск:
    cd backends/python/api
    ./.venv/bin/python manage.py test main.tests_timesheet_write_through --settings=test_settings
"""
from django.test import TestCase
from django.utils import timezone

from .models import Bitrix24Account, TimesheetItem
from .timesheet_sync_service import TimesheetSyncService


class _FakeClient:
    """Отдаёт один и тот же ответ на call_method (crm.item.get). Пишет вызовы в .calls."""

    def __init__(self, response):
        self._response = response
        self._bitrix_token = self
        self.calls = []

    def call_method(self, method, params):
        self.calls.append((method, params))
        return self._response


def _get_response(bitrix_id):
    return {
        "result": {
            "item": {
                "id": bitrix_id,
                "ufCrmTask": str(bitrix_id),
                "createdTime": "2026-01-01T09:00:00+03:00",
            }
        }
    }


class UpsertOneTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-wt-1",
            is_master_account=True, domain_url="wt1.bitrix24.ru",
            status="active", application_version=1,
        )
        self.config = {
            "sp_entity_type_id": 1,
            "fields_mapping": {"data": "createdTime", "id_zadachi": "ufCrmTask"},
        }

    def test_upsert_one_creates_local_row_from_single_bitrix_item(self):
        client = _FakeClient(_get_response(555))
        service = TimesheetSyncService(client, self.account, self.config)

        result = service.upsert_one(555)

        self.assertEqual(result["status"], "success")
        row = TimesheetItem.objects.get(bitrix24_account=self.account, bitrix_id=555)
        self.assertEqual(row.task_id, "555")
        self.assertEqual(client.calls[0][0], "crm.item.get")
        self.assertEqual(client.calls[0][1]["id"], 555)

    def test_upsert_one_updates_existing_row_not_duplicates(self):
        TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=555, task_id="555",
            employee_id="old", hours=1, date_reflection=timezone.now(),
        )
        client = _FakeClient(_get_response(555))
        service = TimesheetSyncService(client, self.account, self.config)

        service.upsert_one(555)

        self.assertEqual(
            TimesheetItem.objects.filter(bitrix24_account=self.account, bitrix_id=555).count(), 1
        )

    def test_upsert_one_not_found_returns_status_without_crash(self):
        client = _FakeClient({"result": {}})
        service = TimesheetSyncService(client, self.account, self.config)

        result = service.upsert_one(999)

        self.assertEqual(result["status"], "not_found")
        self.assertFalse(TimesheetItem.objects.filter(bitrix24_account=self.account, bitrix_id=999).exists())

    def test_upsert_one_skipped_when_entity_type_not_configured(self):
        service = TimesheetSyncService(_FakeClient({}), self.account, {})
        result = service.upsert_one(1)
        self.assertEqual(result["status"], "skipped")
```

- [ ] **Step 2: Прогнать — падает**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_timesheet_write_through.UpsertOneTest --settings=test_settings`
Expected: FAIL (`AttributeError: 'TimesheetSyncService' object has no attribute 'upsert_one'`).

- [ ] **Step 3: Реализовать `upsert_one` + `_extract_item`**

В `timesheet_sync_service.py`, добавить методы в класс `TimesheetSyncService` (например, сразу после `_sync_scoped`, перед `_fetch_all_pages_batched`):
```python
    def upsert_one(self, bitrix_id: int) -> Dict[str, Any]:
        """Write-through: подтягивает ОДИН элемент из Bitrix и сохраняет его в БД.

        Использует тот же normalize_items -> _save_batch, что и массовый синк — строка
        в БД совпадает со строкой из _sync_full/_sync_scoped. Best-effort: вызывающая
        вьюха ловит исключения и не валит сохранение в Bitrix (оно уже прошло на фронте).
        """
        if not self.entity_type_id:
            return {"status": "skipped", "reason": "not_configured"}

        response = self._call_with_retry(
            "crm.item.get",
            {"entityTypeId": self.entity_type_id, "id": bitrix_id},
        )
        item = self._extract_item(response)
        if not item:
            return {"status": "not_found"}

        normalized = self.processing_service.normalize_items([item])
        if not normalized:
            return {"status": "skipped", "reason": "normalize_dropped"}

        new_cards = self._save_batch(normalized)
        self._autofill_inn(new_cards)
        return {"status": "success"}

    @staticmethod
    def _extract_item(response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        result = response.get("result", {})
        if isinstance(result, dict):
            item = result.get("item")
            if isinstance(item, dict):
                return item
        return None
```

- [ ] **Step 4: Прогнать — проходит**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_timesheet_write_through.UpsertOneTest --settings=test_settings`
Expected: PASS.

- [ ] **Step 5: Падающие тесты `remove_one`**

Дополнить `tests_timesheet_write_through.py`:
```python
class RemoveOneTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=2, is_b24_user_admin=True, member_id="m-wt-2",
            is_master_account=True, domain_url="wt2.bitrix24.ru",
            status="active", application_version=1,
        )
        TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=777, task_id="777",
            employee_id="e1", hours=2, date_reflection=timezone.now(),
        )

    def test_remove_one_deletes_local_row_without_calling_bitrix(self):
        client = _FakeClient({})
        service = TimesheetSyncService(client, self.account, {})

        result = service.remove_one(777)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["deleted"], 1)
        self.assertFalse(TimesheetItem.objects.filter(bitrix24_account=self.account, bitrix_id=777).exists())
        self.assertEqual(client.calls, [])  # remove-one не ходит в Bitrix — элемент там уже удалён фронтом

    def test_remove_one_missing_row_is_noop(self):
        service = TimesheetSyncService(_FakeClient({}), self.account, {})
        result = service.remove_one(123456)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["deleted"], 0)

    def test_remove_one_scoped_to_account(self):
        other = Bitrix24Account.objects.create(
            b24_user_id=3, is_b24_user_admin=True, member_id="m-wt-3",
            is_master_account=True, domain_url="wt3.bitrix24.ru",
            status="active", application_version=1,
        )
        service = TimesheetSyncService(_FakeClient({}), other, {})
        service.remove_one(777)  # bitrix_id принадлежит self.account, не other
        self.assertTrue(TimesheetItem.objects.filter(bitrix24_account=self.account, bitrix_id=777).exists())
```

- [ ] **Step 6: Прогнать — падает**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_timesheet_write_through.RemoveOneTest --settings=test_settings`
Expected: FAIL (нет `remove_one`).

- [ ] **Step 7: Реализовать `remove_one`**

В `timesheet_sync_service.py`, сразу после `upsert_one`:
```python
    def remove_one(self, bitrix_id: int) -> Dict[str, Any]:
        """Write-through удаления: убирает ОДНУ запись из локальной БД.

        Элемент в Bitrix уже удалён вызывающим (фронтом) до этого вызова — Bitrix
        трогать не нужно, только локальная проекция.
        """
        deleted_count, _ = (
            TimesheetItem.objects.filter(**scope_to_tenant(self.account), bitrix_id=bitrix_id)
            .delete()
        )
        return {"status": "success", "deleted": deleted_count}
```

- [ ] **Step 8: Прогнать весь новый файл — проходит**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_timesheet_write_through --settings=test_settings`
Expected: PASS.

- [ ] **Step 9: Вьюхи + маршруты**

В `views.py` после `timesheet_sync_status` (реальная строка ~1512) добавить:
```python
@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("timesheet_upsert_one")
@auth_required
@rate_limit("write_through", 30, 60, key="account")
def timesheet_upsert_one(request: AuthorizedRequest):
    body = _load_request_json(request)
    raw_id = body.get("id")
    if not raw_id:
        return JsonResponse({"error": "id is required"}, status=400)
    try:
        bitrix_id = int(raw_id)
    except (TypeError, ValueError):
        return JsonResponse({"error": "id must be integer"}, status=400)

    config_service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    config = config_service.get_configuration_sync()
    service = TimesheetSyncService(request.bitrix24_account.client, request.bitrix24_account, config)
    try:
        result = service.upsert_one(bitrix_id)
    except Exception:
        logger.exception(
            "Write-through upsert-one failed for account %s, id %s",
            request.bitrix24_account.pk, bitrix_id,
        )
        return JsonResponse({
            "status": "warning",
            "warning": "Не удалось сохранить запись локально сразу — подхватит фоновый синк.",
        })

    invalidate_project_runtime_caches(request.bitrix24_account)
    return JsonResponse(result)


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("timesheet_remove_one")
@auth_required
@rate_limit("write_through", 30, 60, key="account")
def timesheet_remove_one(request: AuthorizedRequest):
    body = _load_request_json(request)
    raw_id = body.get("id")
    if not raw_id:
        return JsonResponse({"error": "id is required"}, status=400)
    try:
        bitrix_id = int(raw_id)
    except (TypeError, ValueError):
        return JsonResponse({"error": "id must be integer"}, status=400)

    service = TimesheetSyncService(request.bitrix24_account.client, request.bitrix24_account, {})
    result = service.remove_one(bitrix_id)
    invalidate_project_runtime_caches(request.bitrix24_account)
    return JsonResponse(result)
```
(`_load_request_json`, `ConfigurationService`, `TimesheetSyncService`, `rate_limit`, `invalidate_project_runtime_caches` уже импортированы в `views.py` — новых импортов не требуется.)

Добавить в `__all__` (рядом с `"timesheet_sync_status"`, реальная строка 98): `"timesheet_upsert_one"`, `"timesheet_remove_one"`.

В `urls.py` рядом с реальными строками 54-56 (таймшит-маршруты):
```python
    path('api/timesheets/upsert-one', views.timesheet_upsert_one, name='timesheet_upsert_one'),
    path('api/timesheets/remove-one', views.timesheet_remove_one, name='timesheet_remove_one'),
```

- [ ] **Step 10: Регресс sync-тестов**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_timesheet_write_through main.tests_sync_freshness main.tests_sync_threshold main.tests_sync_integration --settings=test_settings`
Expected: PASS.

- [ ] **Step 11: Коммит**

```bash
git add backends/python/api/main/timesheet_sync_service.py backends/python/api/main/views.py backends/python/api/main/urls.py backends/python/api/main/tests_timesheet_write_through.py
git commit -m "feat(sync): write-through для таймшитов — upsert-one/remove-one через существующий нормализатор"
```

---

## Task 5: Frontend — write-through для таймшитов (wiring)

**Files:**
- Modify: `frontend/app/stores/api.ts` (новые методы `upsertTimesheetOne`, `removeTimesheetOne`)
- Modify: `frontend/app/pages/task.vue` (`handleSaveItem`, строки 118-143)
- Modify: `frontend/app/pages/embedded.vue` (`saveCurrentItem` — обе ветки; `splitItem` — обе записи; `deleteItem`; `deleteItemDirect`)
- Modify: `frontend/app/pages/reports/project-report.client.vue` (`handleSaveMeeting`, строки 359-364 — замена тяжёлого фонового `syncTimesheets()` на лёгкий `upsertTimesheetOne`)

**Interfaces:**
- Consumes: `POST /api/timesheets/upsert-one`, `POST /api/timesheets/remove-one` (Task 4).
- Produces: `apiStore.upsertTimesheetOne(id): Promise<{status:string}>`, `apiStore.removeTimesheetOne(id): Promise<{status:string}>`. Вызовы — fire-and-forget (`.catch(...)`, не блокируют UI и не мешают уже сохранённой в Bitrix правке при сбое — инвариант дизайна §5.1).

- [ ] **Step 1: Методы в сторе**

В `api.ts` рядом с `syncTimesheets` (после реальной строки 583, перед `getTimesheetsList`; если Фаза 1 Задача 5 уже смержена — сразу после её `getTimesheetSyncStatus`) добавить:
```typescript
    const upsertTimesheetOne = async (id: string | number): Promise<{ status: string }> => {
      const result = await $api<{ status: string }>('/api/timesheets/upsert-one', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        },
        body: JSON.stringify({ id })
      })
      clearCache('project-board', 'homepage-portfolio', 'filter-projects')
      return result
    }

    const removeTimesheetOne = async (id: string | number): Promise<{ status: string }> => {
      const result = await $api<{ status: string }>('/api/timesheets/remove-one', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        },
        body: JSON.stringify({ id })
      })
      clearCache('project-board', 'homepage-portfolio', 'filter-projects')
      return result
    }
```
Добавить `upsertTimesheetOne` и `removeTimesheetOne` в возвращаемый объект стора (рядом со строкой 1067, где `syncTimesheets`).

- [ ] **Step 2: `task.vue` — write-through после `handleSaveItem`**

Добавить стор рядом с существующими composables (после реальной строки 15, `const toast = useToast()`):
```typescript
const apiStore = useApiStore()
```
Реальное текущее тело `handleSaveItem` (строки 118-143):
```typescript
async function handleSaveItem(data: EditingItem) {
    if (!config.value) return
    const { id, hours, isConsidered, description, employeeId, date } = data
    isLoading.value = true 
    
    try {
        // @ts-expect-error $b24 is guaranteed initialized in onMounted before this handler runs
        await $b24.callMethod('crm.item.update', {
            entityTypeId: config.value.DEFAULT_SMART_PROCESS_ID,
            id: id,
            fields: {
                [config.value.FIELDS.HOURS]: hours,
                [config.value.FIELDS.IS_CONSIDERED]: isConsidered ? 'Y' : 'N',
                [config.value.FIELDS.DESCRIPTION]: description,
                [config.value.FIELDS.EMPLOYEE]: employeeId,
                [config.value.FIELDS.DATE]: date
            }
        })
        if (rootTaskId.value) await loadTaskTree($b24!, rootTaskId.value)
    } catch (e: unknown) {
        toast.add({ title: "Ошибка сохранения: " + (e as { message?: string }).message, color: 'air-primary-alert' })
        isLoading.value = false
    }

    editingItem.value = null
}
```
Заменить строку `if (rootTaskId.value) await loadTaskTree($b24!, rootTaskId.value)` на:
```typescript
        // Write-through: держим локальную БД (read-model отчётов) свежей без полного
        // синка. Best-effort — сбой не мешает уже сохранённой в Bitrix правке, догонит
        // фоновый инкремент/ночная сверка. (Фаза 3 sync-offload.)
        apiStore.upsertTimesheetOne(id).catch(e => console.warn('[Task] write-through upsert failed', e))
        if (rootTaskId.value) await loadTaskTree($b24!, rootTaskId.value)
```

- [ ] **Step 3: `embedded.vue` — write-through в `saveCurrentItem`**

Реальные строки 708-712 (ветка update):
```typescript
            await ($b24 as B24Frame).callMethod('crm.item.update', {
                entityTypeId: config.value.DEFAULT_SMART_PROCESS_ID,
                id: editingItem.value.id,
                fields: fields
            })
```
Добавить сразу после:
```typescript
            apiStore.upsertTimesheetOne(editingItem.value.id).catch(e => console.warn('[Embedded] write-through upsert failed', e))
```
Реальная строка 735 (ветка create, сразу после получения `createdItemId`):
```typescript
            const createdItemId = extractCreatedItemId(createRes?.getData?.())
```
Добавить сразу после:
```typescript
            if (createdItemId) {
                apiStore.upsertTimesheetOne(createdItemId).catch(e => console.warn('[Embedded] write-through upsert failed', e))
            }
```
(`apiStore` уже объявлен в `embedded.vue`, строка 58 — новой декларации не требуется.)

- [ ] **Step 4: `embedded.vue` — write-through в `splitItem` (два write: update + add)**

Реальные строки 789-794:
```typescript
        const remainingHours = editingItem.value.hours - splitHours
        await ($b24 as B24Frame).callMethod('crm.item.update', {
            entityTypeId: config.value.DEFAULT_SMART_PROCESS_ID,
            id: editingItem.value.id,
            fields: { [config.value.FIELDS.HOURS]: remainingHours }
        })
```
Добавить сразу после:
```typescript
        apiStore.upsertTimesheetOne(editingItem.value.id).catch(e => console.warn('[Embedded] write-through upsert failed', e))
```
Реальные строки 825-828 (создание разделённой записи — сейчас результат не захватывается):
```typescript
        await ($b24 as B24Frame).callMethod('crm.item.add', {
            entityTypeId: config.value.DEFAULT_SMART_PROCESS_ID,
            fields: splitFields
        })
```
Заменить на (захватываем id новой записи, чтобы применить write-through):
```typescript
        const splitRes = await ($b24 as B24Frame).callMethod('crm.item.add', {
            entityTypeId: config.value.DEFAULT_SMART_PROCESS_ID,
            fields: splitFields
        })
        const splitItemId = extractCreatedItemId(splitRes?.getData?.())
        if (splitItemId) {
            apiStore.upsertTimesheetOne(splitItemId).catch(e => console.warn('[Embedded] write-through upsert failed', e))
        }
```

- [ ] **Step 5: `embedded.vue` — write-through в `deleteItem` / `deleteItemDirect`**

Реальные строки 856-859 (`deleteItem`):
```typescript
        await ($b24 as B24Frame).callMethod('crm.item.delete', {
            entityTypeId: config.value.DEFAULT_SMART_PROCESS_ID,
            id: editingItem.value.id
        })
```
Добавить сразу после:
```typescript
        apiStore.removeTimesheetOne(editingItem.value.id).catch(e => console.warn('[Embedded] write-through remove failed', e))
```
Реальные строки 875-878 (`deleteItemDirect`):
```typescript
        await ($b24 as B24Frame).callMethod('crm.item.delete', {
            entityTypeId: config.value.DEFAULT_SMART_PROCESS_ID,
            id: item.id
        })
```
Добавить сразу после:
```typescript
        apiStore.removeTimesheetOne(item.id).catch(e => console.warn('[Embedded] write-through remove failed', e))
```

- [ ] **Step 6: `project-report.client.vue` — заменить фоновый `syncTimesheets()` на write-through**

Реальные строки 359-364:
```typescript
        closeModal()
        await fetchData()
        
        apiStore.syncTimesheets().then(() => {
            projectCardCache.clear()
        }).catch(e => console.warn('[ProjectReport] Background sync failed', e))
    } catch (e: unknown) {
```
Заменить на:
```typescript
        closeModal()
        await fetchData()

        // Write-through вместо полного фонового синка (Фаза 1: apiStore.syncTimesheets()
        // тянул ВСЕ таймшиты за 7 дней после каждого добавления встречи — именно тот
        // паттерн, который убирает write-through). projectCardCache.clear() убран: он
        // не связан с добавлением таймшита (кэш карточки проекта — company/legal
        // entity/etc., которые здесь не меняются). (Фаза 3 sync-offload.)
        if (createdItemId) {
            apiStore.upsertTimesheetOne(createdItemId).catch(e => console.warn('[ProjectReport] write-through upsert failed', e))
        }
    } catch (e: unknown) {
```
(`createdItemId` уже вычислен выше в этой же функции, реальная строка 328 — используется без изменений.)

- [ ] **Step 7: Typecheck + сборка**

Run: `cd frontend && NODE_OPTIONS="--max-old-space-size=4096" corepack pnpm@9.15.9 run build`
Expected: `✨ Build complete!` без ошибок.

- [ ] **Step 8: Регресс фронт-тестов**

Run: `cd frontend && corepack pnpm@9.15.9 dlx tsx --test 'tests/**/*.test.ts'`
Expected: все PASS (число не уменьшилось — в проекте нет юнит-тестов на эти конкретные компоненты/стор-методы, как и в Фазе 1 Задачах 4-5; регресс покрывает существующие composable-тесты).

- [ ] **Step 9: Коммит**

```bash
git add frontend/app/stores/api.ts frontend/app/pages/task.vue frontend/app/pages/embedded.vue frontend/app/pages/reports/project-report.client.vue
git commit -m "feat(sync): фронт — write-through таймшитов вместо фоновых full/scoped синков после сохранения"
```

---

## Task 6: Регресс-тест write-through карточек проектов (уже реализовано — закрепляем)

> Эта задача НЕ добавляет новый путь записи — см. «Контекст и допущения», пункт 3. `update_project_card`/`update_stage`/`archive_project` уже пишут в локальную `ProjectCard` немедленно (local-first), у них просто не было собственных тестов. Задача фиксирует инвариант регресс-тестами, включая явную проверку best-effort-поведения при сбое Bitrix (важно — именно это гарантирует, что «write-through это оптимизация, не критично при сбое», как того требует спека §5.1, для домена проектов тоже).

**Files:**
- Test: `backends/python/api/main/tests_project_write_through.py` (новый файл)

**Interfaces:**
- Consumes: `ProjectCardService.update_project_card/update_stage/archive_project` (без изменений сигнатур/поведения).
- Produces: тестовое покрытие, фиксирующее, что все три метода сохраняют изменения в `ProjectCard` синхронно с вызовом (без отдельного синка), и что сбой записи в Bitrix не откатывает и не блокирует локальное сохранение.

- [ ] **Step 1: Написать тесты (не TDD в классическом смысле — фиксация уже существующего поведения; ожидаем сразу PASS)**

Создать `backends/python/api/main/tests_project_write_through.py`:
```python
"""Регресс-тест: `project_card` уже держится в актуальном состоянии после правки
через /api/project-board/update* — ProjectCardService пишет в локальную ProjectCard
ДО/независимо от best-effort пуша в Bitrix, а не отложенным синком (см. Self-Review
плана Фазы 3, пункт «уже реализовано»). До Фазы 3 у update_project_card/update_stage/
archive_project не было отдельного тестового покрытия — этот файл его добавляет.

Запуск:
    cd backends/python/api
    ./.venv/bin/python manage.py test main.tests_project_write_through --settings=test_settings
"""
from django.test import TestCase

from .models import Bitrix24Account, ProjectCard
from .project_board_service import ProjectCardService
from .project_board_shared import ensure_project_card_schema


class _FakeClient:
    """call_method может кидать исключение — проверяем best-effort к Bitrix:
    локальный upsert должен происходить независимо от результата."""

    def __init__(self, raises=False):
        self._bitrix_token = self
        self.raises = raises
        self.calls = []

    def call_method(self, method, params):
        self.calls.append((method, params))
        if self.raises:
            raise RuntimeError("Bitrix недоступен")
        return {"result": True}


class ProjectCardWriteThroughTest(TestCase):
    def setUp(self):
        # Форсируем переоценку схемы — LocMemCache в тестах может пережить между
        # тестами кэш PROJECT_CARD_SCHEMA_CACHE_KEY из другого TestCase.
        ensure_project_card_schema(force_refresh=True)
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-pwt-1",
            is_master_account=True, domain_url="pwt1.bitrix24.ru",
            status="active", application_version=1,
        )
        self.card = ProjectCard.objects.create(
            bitrix24_account=self.account,
            project_id="42",
            project_name="Старое имя",
            stage="Новый",
            manual_stage="Новый",
        )

    def test_update_project_card_upserts_locally_even_if_bitrix_call_fails(self):
        service = ProjectCardService(_FakeClient(raises=True), self.account)
        result = service.update_project_card("42", {"project_name": "Новое имя"})

        self.card.refresh_from_db()
        self.assertEqual(self.card.project_name, "Новое имя")
        self.assertIsNotNone(result.get("warning"))  # предупреждение есть, но сохранение не заблокировано

    def test_update_stage_upserts_locally_immediately(self):
        service = ProjectCardService(_FakeClient(), self.account)
        service.update_stage("42", "В просчете")

        self.card.refresh_from_db()
        self.assertEqual(self.card.stage, "В просчете")
        self.assertEqual(self.card.manual_stage, "В просчете")
        self.assertEqual(self.card.stage_source, "manual")

    def test_archive_project_upserts_locally_even_if_bitrix_call_fails(self):
        service = ProjectCardService(_FakeClient(raises=True), self.account)
        result = service.archive_project("42", True)

        self.card.refresh_from_db()
        self.assertTrue(self.card.is_archived)
        self.assertIsNotNone(self.card.archived_at)
        self.assertIsNotNone(result.get("warning"))
```

- [ ] **Step 2: Прогнать**

Run: `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_project_write_through --settings=test_settings`
Expected: PASS сразу (поведение уже реализовано — это регресс-лок, а не новая фича). **Если хоть один тест падает** — это значит, что реальный код `project_board_service.py` на момент исполнения отличается от того, что было прочитано при написании этого плана (см. `project_board_service.py:387-488`); в этом случае перед продолжением зафиксировать точную причину падения (systematic-debugging) и решить точечно — либо тест неверно отражает контракт (поправить тест), либо в `update_project_card`/`update_stage`/`archive_project` реально пропал local-first upsert (тогда это баг для отдельного фикса, не предусмотренный объёмом этой фазы, и должен быть explicitly вынесен, не тихо докручен внутри этой задачи).

- [ ] **Step 3: Коммит**

```bash
git add backends/python/api/main/tests_project_write_through.py
git commit -m "test(sync): регресс-лок — write-through карточек проектов (уже local-first, без теста)"
```

---

## Task 7: Frontend — кнопка «Обновить» + индикатор для проектов

**Files:**
- Modify: `frontend/app/stores/api.ts` (новый метод `getProjectSyncStatus`)
- Modify: `frontend/app/pages/projects/index.client.vue` (`<script setup>` — новые refs/функции; `<template>` — шапка с кнопками, строки 602-606)

**Interfaces:**
- Consumes: `GET /api/project-sync-status` (Task 2), `apiStore.syncProjectCards(incrementalSinceMinutes?)` (существующий метод, уже поддерживает параметр — просто раньше ничего его не передавало).
- Produces: `apiStore.getProjectSyncStatus(): Promise<{last_synced_at: string|null, count: number}>`; кнопка «Обновить» на доске проектов, дёргающая инкремент (`syncProjectCards(20)` — обходит гейт свежести, Task 2) и перечитывающая доску; индикатор «данные на ЧЧ:ММ», по образцу Задачи 5 Фазы 1 для таймшитов.

- [ ] **Step 1: Метод статуса в сторе**

В `api.ts` рядом с `syncProjectCards` (после реальной строки 751, перед `updateProjectCard`) добавить:
```typescript
    const getProjectSyncStatus = async (): Promise<{ last_synced_at: string | null; count: number }> => {
      return await $api('/api/project-sync-status', {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }
```
Добавить `getProjectSyncStatus` в возвращаемый объект стора (рядом со строкой 1077, где `syncProjectCards`).

- [ ] **Step 2: Индикатор + функция «Обновить» в `projects/index.client.vue`**

В `<script setup>`, после объявления `const statusMessage = ref<...>(null)` (реальная строка 59), добавить:
```typescript
const lastProjectSyncedAt = ref<string | null>(null)
const isRefreshingProjects = ref(false)

async function loadProjectSyncStatus() {
  try {
    lastProjectSyncedAt.value = (await apiStore.getProjectSyncStatus()).last_synced_at
  } catch {
    // индикатор не критичен — доска работает и без него
  }
}

async function refreshProjects() {
  if (isRefreshingProjects.value) {
    return
  }
  isRefreshingProjects.value = true
  try {
    await apiStore.syncProjectCards(20) // инкремент -> быстрый путь, обходит гейт свежести (Task 2)
    await loadProjectSyncStatus()
    await loadBoard(true)
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isRefreshingProjects.value = false
  }
}
```

- [ ] **Step 3: Подхватить статус в `onMounted` и после полного синка**

Реальные строки 560-581 (`onMounted`):
```typescript
onMounted(async () => {
  isLoading.value = true
  try {
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    await $b24.parent.setTitle('Управление проектами')
    isInit.value = true

    const [meta] = await Promise.all([
      loadMeta(),
      loadBoard()
    ])

    if (isMetaSparse(meta)) {
      void refreshReferenceOptions(false)
    }
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isLoading.value = false
  }
})
```
Добавить `void loadProjectSyncStatus()` сразу после `Promise.all` (не блокирует спиннер — индикатор не критичен):
```typescript
    const [meta] = await Promise.all([
      loadMeta(),
      loadBoard()
    ])
    void loadProjectSyncStatus()

    if (isMetaSparse(meta)) {
      void refreshReferenceOptions(false)
    }
```
В `syncBoard` (реальные строки 399-429), внутри `try`, сразу после существующего `await Promise.all([loadMeta(true), loadBoard(true)])`, добавить `void loadProjectSyncStatus()` — чтобы индикатор отражал и полный синк по кнопке «Синхронизировать проекты», не только инкремент:
```typescript
    const result = await apiStore.syncProjectCards()
    await Promise.all([
      loadMeta(true),
      loadBoard(true)
    ])
    void loadProjectSyncStatus()
```

- [ ] **Step 4: Индикатор + кнопка в шапке**

Реальные строки 602-606:
```html
            <div class="flex flex-wrap gap-2">
              <B24Button label="Синхронизировать проекты" color="success" :loading="isSyncing" @click="syncBoard()" />
              <B24Button label="Обновить справочники" color="default" :loading="isRefreshingMeta" @click="refreshReferenceOptions()" />
              <B24Button label="Проверить статусы" color="default" :loading="isSyncing" @click="runDailyCheck" />
            </div>
```
Заменить на:
```html
            <div class="flex flex-wrap items-center gap-2">
              <span v-if="lastProjectSyncedAt" class="text-xs text-slate-500">
                данные на {{ new Date(lastProjectSyncedAt).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) }}
              </span>
              <B24Button label="Обновить" color="default" :loading="isRefreshingProjects" @click="refreshProjects" />
              <B24Button label="Синхронизировать проекты" color="success" :loading="isSyncing" @click="syncBoard()" />
              <B24Button label="Обновить справочники" color="default" :loading="isRefreshingMeta" @click="refreshReferenceOptions()" />
              <B24Button label="Проверить статусы" color="default" :loading="isSyncing" @click="runDailyCheck" />
            </div>
```
(Используем `B24Button`, не сырой `<button>`: этот файл целиком построен на `@bitrix24/b24ui-nuxt`, в отличие от `project-report.client.vue` из Фазы 1 Задачи 5, где вся шапка — сырой Tailwind; берём образец Фазы 1 по СМЫСЛУ (индикатор + кнопка «Обновить»), а не дословно по разметке.)

- [ ] **Step 5: Typecheck + сборка**

Run: `cd frontend && NODE_OPTIONS="--max-old-space-size=4096" corepack pnpm@9.15.9 run build`
Expected: `✨ Build complete!` без ошибок.

- [ ] **Step 6: Регресс фронт-тестов**

Run: `cd frontend && corepack pnpm@9.15.9 dlx tsx --test 'tests/**/*.test.ts'`
Expected: все PASS (число не уменьшилось).

- [ ] **Step 7: Коммит**

```bash
git add frontend/app/stores/api.ts frontend/app/pages/projects/index.client.vue
git commit -m "feat(sync): индикатор «данные на ЧЧ:ММ» + кнопка «Обновить» для проектов (инкремент)"
```

---

## Self-Review (заполнить при исполнении)

- **Spec coverage (design doc §4.2, §5.1, §5.4, §6; входной бриф пункты А/Б/В):**
  - (А) Проекты: читать `project_card` из БД на открытии — уже так в реальном коде, без изменений (см. «Контекст и допущения», пункт 3, снятый пункт 1); инкремент по расписанию — Task 3 ✓; ночная/частая полная сверка — уже есть (3-часовой луп), сознательно не понижена до буквально «ночной» (обоснование в Task 3, Step 6) ✓.
  - (Б) Write-through: таймшиты (`upsert-one`/`remove-one` через существующий `normalize_items`/`_save_batch`) — Task 4 (backend) + Task 5 (frontend, все реальные call-сайты: `task.vue`, `embedded.vue` ×4, `project-report.client.vue`) ✓. Карточки проектов — уже реализовано local-first, закреплено регресс-тестами без дублирующего кода — Task 6 ✓ (см. «Контекст и допущения», пункт 3, снятый пункт 2).
  - (В) Кнопка «Обновить» + индикатор для проектов, по образцу Задачи 5 Фазы 1 — Task 7 ✓ (на доске проектов, не на `project-report.client.vue`, т.к. это страница, которую правит пункт А, и там же естественная точка для кнопки, управляющей ИМЕННО данными доски).
- **Отклонения от буквального текста дизайн-спеки/брифа — обе явно обоснованы кодом, не додуманы:** (1) нет шага «убрать синк с открытия проектов» — такого кода в реальном файле не существует (полное чтение `onMounted`, строки 560-581); (2) нет нового кода «upsert в project_card» для update*-эндпоинтов — он уже есть (`card.save()` до/независимо от Bitrix во всех трёх методах, строки 440/461/474 `project_board_service.py`), закрыт тестами вместо дублирования. Оба пункта проверяемы по указанным строкам реального файла.
- **Ветка общая и активно менялась во время написания плана — это не гипотетический риск, а подтверждённый факт, трижды пойманный перепроверкой `git log`.** Задача 3 Фазы 1 (`006814e`) и затем Задача 4 (`a05ea54`) были закоммичены другой сессией МЕЖДУ первым чтением затронутых файлов и финализацией этого плана; оба раза обнаружено повторным `git log`/`git status` перед сдачей, файлы перечитаны заново (`sync_scheduler_service.py`, `sync_all_portals.py`, `start.sh`, а для Задачи 4 — grep по `embedded.vue`/`useReportGenerator.ts` подтвердил дословное совпадение с брифом). Task 3 этого плана построен на реальном коде без реконструкции. Тот же эффект независимо зафиксирован в `phase-2-plan-report.md` для параллельной Фазы 2 — это, похоже, системное свойство текущей сессии работы над sync-offload (несколько параллельных агентов на одной ветке), а не разовая случайность. Остаточный риск дрейфа на момент сдачи плана — только Задача 5 Фазы 1 (`api.ts` → `getTimesheetSyncStatus`, индикатор в `project-report.client.vue`), которую использует Task 5/Task 7 этого плана; «Контекст и допущения», пункт 1, явно требует пересверки `git log` перед их исполнением, если ветка продолжит меняться.
- **Type/naming consistency:** `should_skip_project_sync(account, now, gate_minutes)` ↔ `should_skip_timesheet_sync` (Фаза 1); `last_project_synced_at` ↔ `last_timesheet_synced_at`; `/api/project-sync-status` ↔ `/api/timesheet-sync-status`; `getProjectSyncStatus` ↔ `getTimesheetSyncStatus`; `TimesheetSyncService.upsert_one/remove_one` ↔ `_sync_full`/`_sync_scoped` (тот же `_save_batch`); `/api/timesheets/upsert-one`/`/api/timesheets/remove-one` ↔ `/api/sync-timesheets` (тот же namespace). Согласовано между задачами 1-2 (маркер/гейт/статус), 4-5 (write-through), 7 (UI).
- **Инвариант «write-through не заменяет синк» соблюдён во всех задачах:** ни один шаг не трогает `_sync_full`, `_sync_scoped`, orphan-логику (`DELETE_SAFETY_RATIO`) или `ProjectSyncService.sync()` (кроме передачи уже существующего параметра `incremental_since_minutes`). Фоновые лупы (Task 3) и гейты (Task 2) — чистые добавления поверх существующих механизмов.
- **Placeholder scan:** нет черновых/временных тестов, которые нужно переписывать в следующем шаге (в отличие от Фазы 1 Task 2 Step 1) — все тестовые шаги в этом плане пишут финальную версию сразу.

## Definition of Done (Фаза 3)

- Все бэк-тесты зелёные: `tests_sync_freshness`, `tests_scheduled_sync`, `tests_timesheet_write_through`, `tests_project_write_through`, плюс регресс (`tests_sync_threshold`, `tests_sync_lock`, `tests_sync_integration`, `tests_project_fetch_keyset`).
- Фронт: `build` OK, `tsx --test` не уменьшил число проходящих.
- Ручная проверка после merge+деплой:
  - Открытие доски проектов не шлёт `POST /api/project-board/sync` (видно в Network) — как и раньше.
  - Фоновый инкремент проектов (20 мин) виден в логах планировщика; полный 3-часовой луп не тронут.
  - «Обновить» на доске проектов отрабатывает за секунды, индикатор показывает время; повторный клик подряд (<3 мин) для «Синхронизировать проекты» (без инкремента) возвращает `status:"fresh"` без похода в Bitrix, «Обновить» (с инкрементом) — всегда доезжает.
  - Правка/удаление записи времени в приложении (вкладка задачи и основной виджет) мгновенно видна в отчёте по проекту (`report_*` эндпоинты, читающие БД) без ожидания фонового синка — проверить, открыв отчёт сразу после сохранения.
  - Ручное удаление/правка в самом Bitrix (не через приложение) по-прежнему подхватывается фоновым инкрементом/полной сверкой — write-through не единственный путь.
