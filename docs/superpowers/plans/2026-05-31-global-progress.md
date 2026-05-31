# Глобальный прогресс-оверлей — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`). Реализация — Sonnet-агентами под ревью.

**Goal:** Показывать единый прогресс-оверлей с Бобром во ВСЕХ фоновых операциях (формирование отчётов, выгрузки Excel, синхронизации, ИНН-простановка), чтобы было видно, что процесс идёт.

**Architecture:** Композабл-синглтон `useProgress` (module-level reactive state, счётчик параллельных операций) + один `<ProgressOverlay>` в `app.vue`. Точки входа (генерация отчётов, экспорты, синки, ИНН) вызывают `begin()/update()/end()`. Локальные оверлеи удаляются.

**Tech Stack:** Nuxt3/Vue3 + TS. Тесты: `cd frontend && node --import tsx --test tests/progress.test.ts`. Сборка: `npx nuxt prepare`.

---

## File Structure
- Create: `frontend/app/composables/useProgress.ts`, `frontend/tests/progress.test.ts`.
- Modify: `frontend/app/app.vue`; `composables/useReportGenerator.ts`; `pages/reports/{employee,project,daily,project-task,revenue-leakage,time-discipline,focus-analysis}.client.vue`; `pages/reports/raw-data.client.vue`; `components/reports/InnBackfillPanel.vue`; `components/reports/InnAssignModal.vue`; `pages/projects/index.client.vue`.

---

## Task 1: Композабл `useProgress` (TDD)

**Files:** Create `frontend/app/composables/useProgress.ts`, `frontend/tests/progress.test.ts`

- [ ] **Step 1: Тест** (`frontend/tests/progress.test.ts`):

```ts
import { test } from 'node:test'
import assert from 'node:assert'
import { useProgress } from '../app/composables/useProgress'

test('progress: счётчик параллельных операций', () => {
  const p = useProgress()
  // сброс на всякий случай
  while (p.active.value) p.end()
  p.begin('A')
  assert.equal(p.active.value, true)
  assert.equal(p.state.title, 'A')
  p.begin('B', 10)
  assert.equal(p.state.count, 2)
  assert.equal(p.state.total, 10)
  p.update(5)
  assert.equal(p.state.done, 5)
  p.end()
  assert.equal(p.active.value, true) // одна ещё активна
  p.end()
  assert.equal(p.active.value, false)
  assert.equal(p.state.title, '')
  assert.equal(p.state.total, 0)
})
```

- [ ] **Step 2: Запустить — упадёт** (нет файла).

Run: `cd frontend && node --import tsx --test tests/progress.test.ts`
Expected: FAIL (Cannot find module).

- [ ] **Step 3: Реализация** (`frontend/app/composables/useProgress.ts`):

```ts
import { reactive, computed } from 'vue'

// Module-level singleton: общее состояние прогресса на всё приложение
const state = reactive({
  count: 0,
  title: '',
  done: 0,
  total: 0,
})

export function useProgress() {
  function begin(title = '', total = 0) {
    state.count++
    state.title = title
    state.done = 0
    state.total = total
  }
  function update(done: number, total?: number) {
    state.done = done
    if (total !== undefined) state.total = total
  }
  function end() {
    state.count = Math.max(0, state.count - 1)
    if (state.count === 0) {
      state.title = ''
      state.done = 0
      state.total = 0
    }
  }
  const active = computed(() => state.count > 0)
  return { state, active, begin, update, end }
}
```

- [ ] **Step 4: Запустить — пройдёт.** Run: та же команда. Expected: PASS.
- [ ] **Step 5: Commit** `git add frontend/app/composables/useProgress.ts frontend/tests/progress.test.ts && git commit -m "feat(progress): global progress composable + test"`

---

## Task 2: Смонтировать единый оверлей в `app.vue`

**Files:** Modify `frontend/app/app.vue`

- [ ] **Step 1:** Прочитать `frontend/app/app.vue`. Если внутри `<template>` есть корневой элемент (например `<NuxtLayout><NuxtPage/></NuxtLayout>`), добавить рядом `<ProgressOverlay>`. Если `<script setup>` отсутствует — добавить.

```vue
<script setup lang="ts">
import ProgressOverlay from '~/components/common/ProgressOverlay.vue'
import { useProgress } from '~/composables/useProgress'
const progress = useProgress()
</script>
```
В `<template>` добавить (на верхнем уровне, рядом с NuxtLayout/NuxtPage):
```vue
  <ProgressOverlay :visible="progress.active.value" :title="progress.state.title" :done="progress.state.done" :total="progress.state.total" />
```
ВАЖНО: `ProgressOverlay` использует `<Teleport to="body">`, поэтому позиция в шаблоне не важна; главное — чтобы `app.vue` всегда рендерился. Если `app.vue` тривиален и не подходит — смонтировать тот же блок в `frontend/app/layouts/default.vue` (внутри корневого `<div>`).

- [ ] **Step 2: Проверка** `cd frontend && npx nuxt prepare 2>&1 | grep -iE "error|cannot"` — пусто.
- [ ] **Step 3: Commit** `git commit -am "feat(progress): mount global ProgressOverlay in app"`

---

## Task 3: Подключить генерацию отчётов (`useReportGenerator`)

**Files:** Modify `frontend/app/composables/useReportGenerator.ts`

- [ ] **Step 1:** Прочитать файл. В функции `generateReport` обернуть выполнение в `progress.begin/end`. Добавить вверху `import { useProgress } from '~/composables/useProgress'` и внутри composable `const progress = useProgress()`. Шаблон (адаптировать под текущую структуру generateReport, сохранив существующий `setLoading`):

```ts
async function generateReport<T>(config: GenerateReportOptions<T>) {
  options.setLoading?.(true)
  progress.begin('Формирование отчёта…')
  try {
    // ... существующее тело (loader, обработка) ...
  } finally {
    options.setLoading?.(false)
    progress.end()
  }
}
```
ОБЯЗАТЕЛЬНО: `progress.end()` в `finally`, чтобы оверлей гасился при ошибке/пустом результате. Если в текущем теле уже есть try/catch — встроить begin перед try, end в finally.

- [ ] **Step 2: Проверка** `npx nuxt prepare` — пусто.
- [ ] **Step 3: Commit** `git commit -am "feat(progress): show overlay during report generation"`

---

## Task 4: Подключить выгрузки Excel (7 страниц отчётов)

**Files:** Modify `pages/reports/{employee,project,daily,project-task,revenue-leakage,time-discipline,focus-analysis}.client.vue`

- [ ] **Step 1:** В КАЖДОЙ из 7 страниц: добавить `import { useProgress } from '~/composables/useProgress'` и `const progress = useProgress()` в `<script setup>`; обернуть тело функции экспорта (`handleExport`/`handleExportExcel`) в progress:

```ts
async function handleExportExcel() {
  progress.begin('Формирование Excel…')
  try {
    // ... существующее тело (получение blob + скачивание) ...
  } catch (e) { processErrorGlobal(e) }
  finally { progress.end() }
}
```
Если в теле уже есть try/catch — добавить `progress.begin('Формирование Excel…')` перед try и `progress.end()` в finally (создать finally, если его нет). НЕ менять остальную логику.

- [ ] **Step 2: Проверка** `npx nuxt prepare` — пусто.
- [ ] **Step 3: Commit** `git commit -am "feat(progress): show overlay during report Excel export"`

---

## Task 5: Подключить синхронизации

**Files:** Modify `pages/reports/raw-data.client.vue`, `pages/projects/index.client.vue`

- [ ] **Step 1:** В `raw-data.client.vue`: в `handleSync` обернуть тело в `progress.begin('Синхронизация с Bitrix24…')` / `finally end()` (добавить import+const useProgress). В `projects/index.client.vue`: найти функцию синхронизации доски (вызов `apiStore.syncProjectCards`/`sync_project_board`) и так же обернуть `progress.begin('Синхронизация проектов…')` / `finally end()`.
- [ ] **Step 2: Проверка** `npx nuxt prepare` — пусто.
- [ ] **Step 3: Commit** `git commit -am "feat(progress): show overlay during sync operations"`

---

## Task 6: Перевести ИНН на стор + убрать локальные оверлеи

**Files:** Modify `components/reports/InnBackfillPanel.vue`, `components/reports/InnAssignModal.vue`, `pages/reports/raw-data.client.vue`

- [ ] **Step 1: InnAssignModal.vue** — заменить локальный прогресс на стор:
  - Добавить `import { useProgress } from '~/composables/useProgress'`, `const progress = useProgress()`.
  - В функции `apply()`: перед циклом чанков `progress.begin('Простановка ИНН…', items.length)`; в цикле после каждого чанка `progress.update(Math.min(i + CHUNK, items.length))`; в `finally` — `progress.end()`.
  - Удалить локальный `<ProgressOverlay ... />` из `<template>` и импорт `ProgressOverlay`, и локальную переменную `progress`/`applying`-prop оверлея, если она только для него (оставить `applying` для `:loading` кнопки).
- [ ] **Step 2: InnBackfillPanel.vue** — аналогично: в массовой простановке (`applyItems`/`applySelected`/`fillAllPossible`) обернуть `progress.begin('Простановка ИНН…', total)` + `update` по чанкам + `end()`; удалить локальный `<ProgressOverlay>` и его импорт; локальную `progress` ref (done/total) заменить вызовами стора.
- [ ] **Step 3: raw-data.client.vue** — удалить локальные `<ProgressOverlay :visible="isSyncing" .../>` и `<ProgressOverlay :visible="isExporting" .../>` (синк теперь через стор в Task 5; экспорт raw-data обернуть `progress.begin('Формирование Excel…')`/`end()` в `handleExport`). Удалить импорт `ProgressOverlay`, если больше не используется на странице.
- [ ] **Step 4: Проверка** `npx nuxt prepare 2>&1 | grep -iE "error|cannot"` — пусто; `grep -rn "ProgressOverlay" app/components/reports app/pages/reports --include='*.vue'` — не должно остаться локальных использований (только в app.vue/default-layout).
- [ ] **Step 5: Commit** `git commit -am "refactor(progress): route INN + raw-data through global overlay, drop local overlays"`

---

## Task 7: Верификация и документация

**Files:** Modify `docs/CHANGELOG.md`, `docs/RELEASES.md`, `docs/architecture/feature-map.md`

- [ ] **Step 1:** Полная проверка: `cd frontend && node --import tsx --test tests/progress.test.ts && npx nuxt prepare && npm run lint`. Всё зелёное. Подтвердить `grep -rn "ProgressOverlay" frontend/app --include='*.vue'` → только `app.vue` (или `layouts/default.vue`).
- [ ] **Step 2:** Доки: CHANGELOG (глобальный прогресс), RELEASES (пользовательский: «теперь видно, что идёт обработка во всех долгих операциях»), feature-map (useProgress + ProgressOverlay в app.vue).
- [ ] **Step 3:** e2e (вручную): «Сформировать» в отчёте → Бобёр; «Скачать Excel» → Бобёр; синк → Бобёр; ИНН-простановка → Бобёр с X/Y; локальных оверлеев не осталось.
- [ ] **Step 4: Commit** `git commit -am "docs: global progress overlay"`

---

## Self-Review (выполнено)
- **Покрытие спека:** стор → Task 1; монтаж → Task 2; генерация отчётов → Task 3; экспорты → Task 4; синки → Task 5; ИНН + удаление локальных оверлеев → Task 6; verify/docs → Task 7. ✔
- **Плейсхолдеры:** стор+тест — полный код; точки подключения — образец + явное «обернуть тело в begin/finally end», т.к. тела функций уже существуют (агент читает и оборачивает). ✔
- **Согласованность:** API стора (`begin/update/end/active/state`) единое во всех задачах; `ProgressOverlay` props (`visible/title/done/total`) совпадают с существующим компонентом. ✔
