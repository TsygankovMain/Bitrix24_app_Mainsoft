# Инкремент таймшитов по `updatedTime` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить механизм инкрементального синка таймшитов: вместо окна в 7 дней по дате отражения плюс подпорки по `createdTime` — выборка по `>=updatedTime` от маркера с перекрытием. Это делает инкремент дешёвым настолько, чтобы держать его в пути отчёта, и снимает целый класс багов с границами суток.

**Spec:** [2026-07-31 — инкремент таймшитов по updatedTime](../specs/2026-07-31-timesheet-incremental-updatedtime-design.md). Родительская спека: [2026-07-27](../specs/2026-07-27-local-read-model-sync-offload-design.md), §4.1 и §5.2.

**Architecture:** `TimesheetSyncService` получает третий режим `_sync_incremental` рядом с существующими `_sync_scoped` и `_sync_full`. Выбор режима и расчёт границы выносятся в чистые функции — они и накрываются тестами. Маркер `Bitrix24Account.last_timesheet_synced_at` уже существует (миграция 0016), новых миграций не нужно.

**Tech Stack:** Django (в `requirements.txt` не запинен; локально ставится 4.2.30) на Postgres, b24pysdk, gunicorn; Nuxt 4 / Vue 3 (Pinia store `api.ts`).

## Global Constraints

- Ветка: `feat/timesheet-incremental-updatedtime` от `prod_2026`. **НЕ пушить в `prod_2026`** — там авто-деплой на Timeweb.
- Тесты бэка из `backends/python/api`: `python3 manage.py test main.<модуль> --settings=test_settings`. Отдельного venv в проекте больше нет, системный `python3` идёт с Django 4.2.30.
- `manage.py test main` целиком **не работает никогда** — четыре модуля подменяют `sys.modules["django"]` и ломают discovery. Запускать строго по модулям; четыре standalone-скрипта (`tests_sync_scoped`, `tests_project_fetch_keyset`, `tests_inn_apply_batch`, `tests_fetch_paginated_batch`) — своими командами со своим cwd.
- Паттерн тестов синка: `_FakeClient` с `_bitrix_token=self` и `call_method(method, params)` — см. `main/tests_sync_threshold.py`.
- `_sync_scoped` и `_sync_full` **не трогаем**: они остаются для ручных задач и ночной сверки, их тесты должны остаться зелёными без правок.
- Никаких удалений данных в новом коде. См. §4.5 спеки.
- `OVERLAP = 5 минут`, гейт свежести 3 минуты, интервал фонового инкремента 20 минут.

---

## Task 1: Чистые функции — выбор режима и расчёт границы

Логика должна быть проверяемой без сети, БД и Django-настроек.

- [ ] **Step 1: Падающие тесты в новом `main/tests_sync_incremental.py`**
  - `resolve_sync_mode(marker=None, date_from=None, date_to=None, full=False)` → `"full"`
  - маркер есть, дат нет, `full=False` → `"incremental"`
  - `full=True` при наличии маркера → `"full"`
  - заданы обе даты → `"scoped"` (даты приоритетнее маркера)
  - задана только одна дата → `"incremental"` при наличии маркера, иначе `"full"`
  - `build_incremental_filter(since)` → ровно один ключ `">=updatedTime"`
  - значение — полный ISO с таймзоной, длиной больше 10 символов (регресс на `2fcd176`)
  - в фильтре нет ни одного ключа, начинающегося с `<`
  - `incremental_since(marker, overlap)` → `marker - overlap`

- [ ] **Step 2: Прогнать — падает (функций нет)**
  - `python3 manage.py test main.tests_sync_incremental --settings=test_settings`

- [ ] **Step 3: Реализовать функции в `timesheet_sync_service.py`**
  - модульного уровня, без обращения к `self`

- [ ] **Step 4: Прогнать — проходит**

- [ ] **Step 5: Коммит** — `feat(sync): чистые функции выбора режима и границы инкремента`

---

## Task 2: `_sync_incremental`

- [ ] **Step 1: Падающие тесты (дописать в `tests_sync_incremental.py`)**
  - выдача Битрикса из двух страниц собирается целиком и уходит в `_save_batch`
  - фильтр каждой страницы содержит `">=updatedTime"` и `">id"` (keyset), `start=-1`
  - **`_sync_incremental` не вызывает `_delete_scoped_orphans` ни разу** — в том числе при пустой выдаче Битрикса
  - пустая выдача → 0 записей, никаких исключений, никаких удалений
  - исключение на второй странице пробрасывается наружу (маркер двигает вызывающий, не сервис)

- [ ] **Step 2: Прогнать — падает**

- [ ] **Step 3: Реализовать `_sync_incremental(since)`**
  - keyset по `id`, `start=-1`, нормализация и сохранение существующим конвейером
  - никаких удалений

- [ ] **Step 4: Встроить выбор режима в `sync_all`**
  - вызов без дат и с маркером больше не уходит в `_sync_full`

- [ ] **Step 5: Прогнать регресс всех модулей синка**
  - `tests_sync_incremental`, `tests_scheduled_sync`, `tests_sync_integration`, `tests_sync_threshold`, `tests_sync_lock`, `tests_sync_honest_errors`, `tests_reports`
  - standalone: `python3 backends/python/api/main/tests_sync_scoped.py` из корня репозитория

- [ ] **Step 6: Коммит** — `feat(sync): инкрементальный режим синка таймшитов по updatedTime`

---

## Task 3: Продвижение маркера

- [ ] **Step 1: Падающие тесты**
  - маркер сдвигается на `started_at`, зафиксированное ДО обхода, а не на время окончания
  - при исключении в обходе маркер остаётся прежним
  - при успехе с нулём записей маркер всё равно сдвигается (нечего забирать — тоже успех)

- [ ] **Step 2: Прогнать — падает**

- [ ] **Step 3: Реализовать в `sync_scheduler_service.run_scheduled_sync` и `views.timesheet_sync`**
  - обе точки продвигают маркер по одному правилу

- [ ] **Step 4: Прогнать — проходит, плюс регресс `tests_scheduled_sync`**

- [ ] **Step 5: Коммит** — `feat(sync): маркер свежести двигается только по успеху обхода`

---

## Task 4: Перевод фонового цикла на инкремент

- [ ] **Step 1: Падающий тест в `tests_scheduled_sync`**
  - `run_scheduled_sync(scope="timesheet", full=False)` при наличии маркера вызывает `sync_all` **без** `date_from`/`date_to`
  - `full=True` по-прежнему уходит в полный обход

- [ ] **Step 2: Прогнать — падает**

- [ ] **Step 3: Убрать вычисление `date_from`/`date_to` из инкрементальной ветки `run_scheduled_sync`**
  - `DEFAULT_WINDOW_DAYS` остаётся только для явного scoped-вызова из команды

- [ ] **Step 4: Прогнать — проходит + полный регресс бэка по модулям**

- [ ] **Step 5: Коммит** — `feat(sync): фоновый цикл таймшитов перешёл на инкремент по updatedTime`

- [ ] **Step 6: Наблюдение сутки на одном портале перед продолжением**
  - в логах: `Scheduled sync portal <member_id>: <N> items.` должно идти три раза в час
  - ночная полная сверка не должна находить существенных расхождений; если находит — предположение из §10 спеки неверно, остановиться и вернуться к дизайну

---

## Task 5: Индикатор и кнопка «Обновить» на всех отчётах

Сейчас есть только на `project-report.client.vue`. Образец брать оттуда.

- [ ] **Step 1: Вынести индикатор и кнопку в общий компонент**
  - логика возраста данных (форматирование «данные на ЧЧ:ММ») — в `app/utils`, а не в `.vue`: тесты не резолвят `.vue`, логика внутри шаблона остаётся непокрытой

- [ ] **Step 2: Тесты на форматирование возраста данных**
  - `null` → «данные не синхронизировались»
  - сегодня → «данные на ЧЧ:ММ»
  - вчера и раньше → с датой

- [ ] **Step 3: Подключить компонент на девяти оставшихся страницах**
  - `daily`, `employee`, `focus-analysis`, `project`, `project-task`, `raw-data`, `revenue-leakage`, `time-discipline`, `debug`

- [ ] **Step 4: Typecheck и сборка**
  - `NODE_OPTIONS="--max-old-space-size=4096" corepack pnpm@9.15.9 run build` из `frontend/`

- [ ] **Step 5: Фронт-тесты**
  - `corepack pnpm@9.15.9 dlx tsx --test 'tests/**/*.test.ts'` из `frontend/`

- [ ] **Step 6: Коммит** — `feat(reports): возраст данных и кнопка обновления на всех отчётах`

---

## Task 6: Досинк перед отчётом — ГЕЙТ

**Не начинать, пока не разобран шторм справочника компаний** (§9 спеки, задача про `_offset_loop_fallback` в `project_board_service.py`). На портале, где фоновый синк голодает, включение досинка даст не свежие данные, а постоянное предупреждение «не удалось обновить».

- [ ] **Step 1: Убедиться, что шторм справочника устранён**
  - фоновый синк отрабатывает штатно три раза в час на проблемном портале

- [ ] **Step 2: Включить `syncTimesheets: true` на страницах отчётов**
  - без периода — инкремент глобален
  - `allowSyncFallback: true` уже стоит, проверить на каждой странице

- [ ] **Step 3: Проверить поведение гейта свежести**
  - два перестроения отчёта подряд → второй получает `status: "fresh"` без обращения к Битриксу

- [ ] **Step 4: Typecheck, сборка, фронт-тесты**

- [ ] **Step 5: Коммит** — `feat(reports): отчёт досинхронизирует изменения перед построением`
