# Спринт 3 «Интерфейс сотрудника + свежие данные» — план исполнения

> Исполнение: волны параллельных агентов; файлы внутри одной волны не пересекаются. Фиксации (commit) делает оркестратор после проверки каждой задачи. Ветка: `sprint-3-ui-freshness` (от `prod_2026`, спринты 1-2 безопасности/надёжности влиты). **КОД В РАМКАХ НАПИСАНИЯ ПЛАНА НЕ МЕНЯЕТСЯ** — это документ для последующего исполнения. Тёмная тема осознанно отложена — её НЕ трогаем; везде работаем на светлой теме.

## Цель

Сделать так, чтобы самый массовый экран приложения (ввод времени в карточке задачи) выглядел и вёл себя как родной Битрикс24 (фирменные компоненты вместо чужих лаймовых кнопок и форм без подписей, работа с клавиатуры), фильтры отчётов перестали сбрасываться при переключении между 7 отчётами, на «Проверке данных» крутился ровно один индикатор загрузки вместо двух, отчётные таблицы открывались уже раскрытыми и управлялись с клавиатуры, Excel-выгрузки перестали грозить падением сервера на больших объёмах, а данные обновлялись сами по расписанию (фоновый инкрементальный синк) без нажатия кнопки. Дополнительно закрываем долг ревизии спринта 2 (панель `syncWarning` на 6 отчётах) и готовим проектный документ перестройки хранения «одна компания — одно хранилище» (без кода — решение за заказчиком).

## Подход (3 предложения)

UI-задачи 3.1–3.4 берём строго поведенчески-эквивалентными: переводим только слой представления на уже используемые в проекте B24-компоненты (`B24Button`, `B24Modal`, `B24Switch`, `B24Select`, `B24Input`, `B24InputNumber`, `B24FormField`) и существующий `UiDatePickerInput`/`useProgress`, **не трогая** вызовы стора/Bitrix и логику записи времени, а реальный набор и пропсы компонентов берём из уже мигрированных страниц (`pages/slider/app-options.client.vue`, `components/reports/InnAssignModal.vue`, `components/projects/ProjectBoardDrawer.vue`), а не выдумываем. Excel-задачу 3.5 решаем через `write_only`-режим openpyxl там, где он совместим со стилями/группировкой/закреплением (matrix и table — да; иерархические с `outline_level`/`merge_cells` — оставляем в обычном режиме, обосновано в карточке), плюс мягкий лимит строк с понятным сообщением, сохраняя защиту формул `_safe_cell_text` и существующие `tests_report_excel`. Автосинхронизацию 3.6 реализуем как **management-команду `sync_all_portals` + внешний cron платформы Timeweb** (вариант «а» — обоснование в карточке: gunicorn идёт в 2 воркера × 4 потока, поэтому APScheduler в процессе дублировался бы), с журналом запусков (модель `SyncRun`), переиспользованием advisory-lock из 2.2, флагом отключения на портал и инкрементальными окнами; всё бэкенд-тестируем на sqlite с моком Bitrix.

## Волны и непересечение файлов

Спринт 3 имеет сильное пересечение по фронту (общие компоненты `DateRangeFilter.vue`, `RecursiveTableRow.vue`, страница `raw-data.client.vue`, 6 отчётных страниц). Чтобы в одной волне не было двух задач, пишущих в один файл, разводим так. Бэкенд-задачи (3.5 Excel, 3.6 автосинк, 3.7 только документ) трогают свои файлы и параллелятся с фронтом.

| Волна | Задачи (параллельно) | Файлы записи (Create/Modify) |
|---|---|---|
| 1 | **3.1а** task.vue → B24; **3.2** фильтры запоминаются + панель syncWarning на 6 страниц; **3.5** Excel write_only+лимит; **3.6** автосинк по расписанию | 3.1а: `frontend/app/pages/task.vue` · 3.2: `frontend/app/composables/useReportFilters.ts`, `frontend/app/pages/reports/{employee,project,project-task,focus-analysis,revenue-leakage,time-discipline}.client.vue` (6 шт.) · 3.5: `backends/python/api/main/report_excel.py`, `main/tests_report_excel_guard.py` (new) · 3.6: `main/models.py`, `main/migrations/0013_syncrun.py` (new), `main/management/commands/sync_all_portals.py` (new), `main/sync_scheduler_service.py` (new), `main/tests_scheduled_sync.py` (new) |
| 2 | **3.1б** TaskGroupComponent/TaskNode/TaskItemRow → B24; **3.3** один индикатор на «Проверке данных»; **3.4** таблицы+календарь | 3.1б: `frontend/app/components/TaskGroupComponent.vue`, `frontend/app/components/TaskNode.vue`, `frontend/app/components/TaskItemRow.vue` · 3.3: `frontend/app/pages/reports/raw-data.client.vue`, `frontend/app/components/common/ProgressOverlay.vue`, `frontend/app/composables/useProgress.ts` · 3.4: `frontend/app/components/reports/RecursiveTableRow.vue`, `frontend/app/components/common/DateRangeFilter.vue` |
| 3 | **3.7** проектный документ перестройки мультитенантности (только текст внутри этого плана) | без правок кода — раздел плана |
| 4 | **3.8** Ревизия | без правок (чтение + полный прогон) |

**Доказательство непересечения по волнам:**
- **Волна 1:** 3.1а пишет только `pages/task.vue`; 3.2 пишет `composables/useReportFilters.ts` + 6 файлов `pages/reports/*.client.vue` (employee, project, project-task, focus-analysis, revenue-leakage, time-discipline); 3.5 пишет `main/report_excel.py` + новый тест; 3.6 пишет `main/models.py`, новую миграцию, новую команду, новый сервис, новый тест. Пересечений нет: фронт-файлы 3.1а и 3.2 различны (`task.vue` ∉ списка 6 отчётов), бэкенд-файлы 3.5 и 3.6 различны (`report_excel.py` ∉ {models, команда, сервис}).
- **Волна 2:** 3.1б пишет `TaskGroupComponent.vue`/`TaskNode.vue`/`TaskItemRow.vue`; 3.3 пишет `raw-data.client.vue`/`ProgressOverlay.vue`/`useProgress.ts`; 3.4 пишет `RecursiveTableRow.vue`/`DateRangeFilter.vue`. Три непересекающихся набора файлов.
- **Волна 3 (одна задача):** 3.7 — только текст в этом документе, кода нет.
- **Волна 4:** 3.8 — без правок.

**Критические зависимости между волнами (сознательная сериализация, не пересечение в волне):**
1. **`DateRangeFilter.vue` — общий между 3.2 и 3.4.** Все 6 отчётных страниц 3.2 рендерят `DateRangeFilter` (импортируют его), а 3.4 этот компонент **переписывает** (меняет внутренности на `UiDatePickerInput`). Они НЕ пишут в один файл (3.2 правит страницы, 3.4 правит сам компонент), но 3.4 идёт в **волне 2 — после** волны 1, чтобы новый `DateRangeFilter` уже был стабилен, когда страницы 3.2 (волна 1) с ним работают. 3.2 НЕ меняет API `DateRangeFilter` (пропсы `dateFrom`/`dateTo` + события `update:dateFrom`/`update:dateTo` сохраняются 3.4), поэтому страницы продолжают работать.
2. **`raw-data.client.vue` — общий между 3.3 и 3.4.** В `raw-data` используется `UiDatePickerInput` (стр. 338-384) и `RecursiveTableRow` НЕ используется (там своя таблица), а `DateRangeFilter` НЕ используется. 3.3 правит `raw-data` (индикатор), 3.4 правит `RecursiveTableRow`+`DateRangeFilter`. Оба в волне 2, но в разные файлы — `raw-data` пишет только 3.3. Пересечения нет.
3. **`useReportGenerator.ts` НЕ трогается в спринте 3** — он был источником `syncWarning` в 2.3 и уже корректно его выставляет; 3.2 лишь добавляет рендер панели на страницах, движок не правит.

## Как запускать тесты / проверки (обязательно к прочтению исполнителями)

- **Django-тесты (sqlite):** `cd backends/python/api && ./.venv/bin/python manage.py test main.<модуль> --settings=test_settings`. Python и Django в `backends/python/api/.venv` (Python 3.9.6, Django 4.2.29). Новые тест-модули спринта 3 (`tests_report_excel_guard`, `tests_scheduled_sync`) пишем как Django-`TestCase` **без** `sys.modules`-заглушек и **без** `django.setup()` на верхнем уровне — тогда они запускаются через `manage.py test`.
- **ВАЖНО про `tests_report_excel` (существующий):** этот модуль написан в **standalone-стиле** — на верхнем уровне делает `os.environ.setdefault("DJANGO_SETTINGS_MODULE","settings"); django.setup()` и использует `unittest`, НЕ Django-`TestCase`. Он **не падает** под `manage.py test`, но его «родной» прогон — `cd backends/python && api/.venv/bin/python -m unittest api.main.tests_report_excel`. Задача 3.5 правит `report_excel.py`, поэтому **прогонять `tests_report_excel` ОБА способа** (через `manage.py test main.tests_report_excel --settings=test_settings` и standalone) и убедиться, что зелёные. Новый тест 3.5 (`tests_report_excel_guard`) пишем как чистый Django-`TestCase` без `django.setup()`.
- **Автономные тесты (подменяют `sys.modules`!):** запускать ТОЛЬКО через `cd backends/python && api/.venv/bin/python -m unittest api.main.<модуль>`. Семейство: `tests_fetch_paginated_batch`, `tests_project_fetch_keyset`, `tests_sync_scoped`, `tests_inn_apply_batch`, `tests_sync_integration` (последний добавлен в спринте 2 и содержит `sys.modules`). Эти модули **никогда не запускать через `manage.py test`**. Перед добавлением любого нового тест-модуля проверить `grep -L "sys.modules" main/tests_*.py`.
- **База регресса:** `main.tests_reports` — **41 тест, 2 ИЗВЕСТНЫЕ ошибки** в `FinanceOperationServiceTest` (finance отключён флагом; существовали до спринта 3 — НЕ чинить, новых ошибок не добавлять). Контракты, которые НЕЛЬЗЯ ломать: `test_sync_endpoint_returns_warning_instead_of_500`, `test_project_board_sync_endpoint_returns_warning_instead_of_500`, `test_timesheet_filters_use_date_range_and_exclude_archived_projects`, `test_timesheet_sync_save_batch_updates_and_creates_records`.
- **БД тестов:** sqlite (`test_settings.py`: `ENGINE django.db.backends.sqlite3`, `NAME BASE_DIR/test.sqlite3`). На sqlite `account_sync_lock` из 2.2 — **no-op** (gate `connection.vendor != "postgresql"`), это важно для тестов 3.6 (конкуренция на sqlite не воспроизводится — логику замка не тестируем заново, она покрыта в 2.2; в 3.6 проверяем журнал, флаг, инкрементальность, идемпотентность с моком Bitrix).
- **Миграции:** последняя — `0012_requestlog_bitrix24_account_and_more`. Новая миграция 3.6 — `0013_syncrun`. На проде миграции применяются ОТДЕЛЬНЫМ release-шагом (`python manage.py migrate --noinput`), `start.sh` миграции НЕ запускает — это учтено в карточке 3.6.
- **Фронт:** тест-раннера для компонентов нет. **`npm run lint` покрывает ТОЛЬКО `app/utils` и `app/composables`** (см. `package.json`: `"lint": "eslint app/utils app/composables --max-warnings=0"`), то есть ESLint **НЕ** проверяет `.client.vue`-страницы и `components/*.vue`. Значит: (1) задачи 3.1/3.3/3.4 (компоненты/страницы) НЕ ловятся линтером — проверка только ручная + сверка с образцами; (2) задача 3.2 правит `composables/useReportFilters.ts` — он **попадает** под линт, его `npm run lint` обязан остаться 0 ошибок. Пакетный менеджер — **pnpm** (`pnpm-lock.yaml`), но команда `npm run lint` тоже сработает (это просто запуск скрипта). **VueUse в проекте НЕТ** (`@vueuse/core` отсутствует в `package.json`) — 3.2 использует **сырой** `localStorage`/`sessionStorage`, не `useLocalStorage`.
- **Docker НЕ запущен.** PostgreSQL в тест-окружение НЕ вводить. Путь проекта содержит пробелы и кириллицу — экранировать кавычками.

**Инвентарь реальных B24-компонентов (проверено грепом по `pages`+`components`, для задачи 3.1 — НЕ выдумывать API):**
- `B24Button` (90 употреблений): пропсы `label`, `color` (`primary`/`success`/`default`/`link`), `size` (`sm`/`lg`), `:loading`, `:disabled`, событие `@click`. Образец: везде.
- `B24Modal` (2 употр.): `:open` (boolean) + `@update:open="(v)=>{...}"`, слоты `#header`/`#body`/`#footer`. Образец: `components/reports/InnAssignModal.vue:63-93`.
- `B24Switch` (2 употр.): `v-model` (boolean), `size`. Образец: `components/projects/ProjectBoardDrawer.vue:261`, `pages/slider/app-options.client.vue:222`.
- `B24Select` (1 употр.): `v-model`, `:items` (массив), `size`, `class`. Образец: `pages/slider/app-options.client.vue:201-206`.
- `B24Input` (1 употр.): `v-model`, `size`, `class`. Образец: `pages/slider/app-options.client.vue:212-216`.
- `B24InputNumber` (1 употр.): `v-model`, образец: `pages/handler/uf.demo.client.vue:126`.
- `B24FormField` (5 употр.): обёртка с `:label` и/или `:description`, внутрь кладётся контрол. Образец: `pages/slider/app-options.client.vue:197-226`, `pages/handler/uf.demo.client.vue:119-131`.
- **`B24Textarea` в проекте НЕ используется НИГДЕ** (проверено: 0 совпадений). См. **открытый вопрос 1**: для поля «Описание» в модале 3.1 либо проверить наличие `B24Textarea` в `@bitrix24/b24ui-nuxt` (если есть — использовать), либо оставить нативный `<textarea>` со стилем B24Input (border/rounded/focus-ring как у образца), завернув в `B24FormField`.
- **ВАЖНАЯ ОГОВОРКА:** в уже мигрированных экранах принят **смешанный** паттерн — `B24Card`/`B24Button`/`B24Switch` соседствуют с нативными `<select>`/`<input>` внутри `B24Card` (см. `pages/settings/mapping.client.vue:553-572`, `components/projects/ProjectBoardDrawer.vue:223-305` — там нативные input/select/SearchableSelect). Поэтому «фирменность» = убрать чужие лаймовые цвета и формы без подписей, привести к виду настроек; полная замена каждого `<input>` на `B24Input` НЕ обязательна, но для нового кода 3.1 предпочитаем B24-контролы там, где их API подтверждён образцом.

---

## Задача 3.1а — Экран ввода времени (страница) → фирменные компоненты [соннет, заход 1]

**Файлы:** Modify `frontend/app/pages/task.vue` (кнопки шапки ≈250-258; модал редактирования ≈298-344; модал переноса ≈346-367; блок `<style scoped>` ≈372-448).

**Дыра (проверено чтением `pages/task.vue` целиком).**
1. Кастомные кнопки `.task-primary-btn`/`.task-secondary-btn`/`.task-group-create-btn` с `background:#0075ff` и `:hover{background:#c7f04f}` (лаймовый отголосок старой тёмной темы; см. стр. 386-394 — заметна даже логическая ошибка: `color:#0f172a` тёмный текст на синем фоне). Кнопки «Excel (CSV)», «В отчет Bitrix24» (стр. 250-257), «Отмена»/«Сохранить» в модалах (стр. 339-340, 359-363).
2. Модал редактирования записи (стр. 298-344) сделан на самописном `.ms-modal-overlay`/`.ms-modal-panel` через `<Teleport>`; внутри — нативные `<select>` (стр. 314), `<input type=number>` (стр. 321), `<input type=checkbox>` (стр. 325), `<input type=date>` (стр. 330), `<textarea>` (стр. 334). Подписи есть (`.task-field-label`), но фокус не захватывается (нет focus-trap), Esc не закрывает, нет ARIA.
3. Модал подтверждения переноса (стр. 346-367) — тоже самописный overlay.

**Решение (поведение записи времени НЕ меняем — только UI-слой).**
- Кнопки шапки и кнопки в модалах → `B24Button` с `color="success"` (главное действие: «Сохранить», «В отчет», «Подтвердить»), `color="default"`/`color="link"` (вторичное: «Excel (CSV)», «Отмена»), по образцу `InnAssignModal`/`ProjectBoardDrawer`. Иконки `material-symbols-outlined` можно сохранить внутри слота кнопки (B24Button принимает дефолтный слот контента наряду с `label`) ИЛИ оставить `label` — выбрать `label`, иконку убрать, если она ломает вид (сверить с настройками, где кнопки без иконок).
- Оба самописных модала (`editingItem`, `isReportModalOpen`) → `B24Modal` с `:open` + `@update:open` + слотами `#header`/`#body`/`#footer` (точно как `InnAssignModal.vue:63-93`). Это даёт штатный focus-trap/Esc/overlay от B24 — закрывает дыру «фокус не захватывается». Убрать `<Teleport>` и `.ms-modal-*` (B24Modal телепортируется сам).
  - **Тонкость с `useIframeResizeOnToggle`:** на стр. 50-51 ресайз айфрейма завязан на `isReportModalOpen` и `computed(()=>Boolean(editingItem.value))`. Эти зависимости СОХРАНИТЬ как есть — они следят за ref-флагами, а не за DOM, поэтому при переходе на `B24Modal` (управляется тем же `editingItem`/`isReportModalOpen`) продолжат работать. НЕ удалять эти строки.
- Поля в модале редактирования (внутри `#body`):
  - «Сотрудник» → `B24Select` `v-model="editingItem.employeeId"` `:items="..."` в `B24FormField label="Сотрудник"`. Список строится из `usersMap` — сейчас `<option v-for="u in usersMap" :value="u.ID">{{u.NAME}} {{u.LAST_NAME}}</option>`. `B24Select :items` ожидает массив; собрать `computed` `employeeSelectItems` вида `[{ label: '${NAME} ${LAST_NAME}', value: ID }, ...]` из `usersMap`. **Тип значения сохранить** (`employeeId: string | number`) — `crm.item.update` (стр. 122) шлёт `[config.FIELDS.EMPLOYEE]: employeeId`, формат не менять.
  - «Часы» → `B24InputNumber` `v-model="editingItem.hours"` (или `B24Input type=number`), `B24FormField label="Часы"`. `step=0.5` если поддерживается; иначе оставить нативный number в `B24FormField`.
  - «Учитывать в аналитике» → `B24Switch v-model="editingItem.isConsidered"` (boolean) в `B24FormField label="Учитывать в аналитике"`. Сейчас checkbox; `isConsidered` уже boolean (стр. 38, и при сохранении `isConsidered ? 'Y':'N'` стр. 120 — логику НЕ менять).
  - «Дата» → `UiDatePickerInput v-model="editingItem.date"` (тот же компонент, что в `raw-data`/3.4; формат `YYYY-MM-DD`, совпадает с тем, что шлёт `crm.item.update`). `B24FormField label="Дата"`.
  - «Описание» → см. открытый вопрос 1: `B24Textarea` если есть, иначе нативный `<textarea>` со стилем B24 в `B24FormField label="Описание"`.
- Убрать из `<style scoped>` правила `.task-primary-btn`, `.task-secondary-btn`, `.task-field-*`, `.task-toggle`, `.ms-modal-*` (если они локальные; `ms-modal-*`/`ms-surface` могут быть глобальными в `app/assets/css/main.css` — **проверить грепом** перед удалением, глобальные НЕ удалять, удалять только локальные дубли). Лаймовые `#c7f04f`/`#84cc16`/`rgba(190,242,100,*)` из `task.vue` устранить полностью.

**Приёмка (ручная):** визуально совпадает со страницами настроек (кнопки, модал, переключатель); модал редактирования закрывается по Esc и держит фокус внутри (даёт B24Modal); по Tab можно дойти до всех полей и кнопок; сохранение записи работает как раньше (тот же вызов `handleSaveItem` → `crm.item.update`). Поведение `handleExportExcel`/`handleTransferToReport` НЕ меняется.

**Шаг 1. Падающий тест.** Тест-раннера компонентов нет; ESLint `task.vue` НЕ покрывает. «Падающий тест» здесь — **визуально-функциональный чек-лист** (ниже, в ручной проверке). Перед правкой исполнитель ОБЯЗАН прочитать `InnAssignModal.vue` и `app-options.client.vue` целиком, чтобы скопировать реальный синтаксис B24Modal/B24Select/B24FormField, и проверить грепом наличие `B24Textarea` в `node_modules/@bitrix24/b24ui-nuxt` (`grep -rl "B24Textarea\|Textarea" frontend/node_modules/@bitrix24/b24ui-nuxt/dist 2>/dev/null` — если пусто, использовать нативный textarea).

**Шаг 2. Реализация.** Применить замены выше в `pages/task.vue`. Полный шаблон модала редактирования (`#body`) — ориентир (адаптировать под подтверждённый API):
```vue
<B24Modal :open="!!editingItem" @update:open="(v) => { if (!v) editingItem = null }">
  <template #header>
    <div>
      <div class="text-sm font-semibold text-slate-900">Редактирование записи</div>
      <div class="mt-1 text-xs text-slate-500">Измените сотрудника, часы, дату и описание.</div>
    </div>
  </template>
  <template #body>
    <div v-if="editingItem" class="space-y-4">
      <B24FormField label="Сотрудник">
        <B24Select v-model="editingItem.employeeId" :items="employeeSelectItems" class="w-full" />
      </B24FormField>
      <div class="grid gap-4 md:grid-cols-2">
        <B24FormField label="Часы">
          <B24InputNumber v-model="editingItem.hours" :step="0.5" class="w-full" />
        </B24FormField>
        <B24FormField label="Учитывать в аналитике">
          <B24Switch v-model="editingItem.isConsidered" />
        </B24FormField>
      </div>
      <B24FormField label="Дата">
        <UiDatePickerInput v-model="editingItem.date" placeholder="Выберите дату" />
      </B24FormField>
      <B24FormField label="Описание">
        <!-- B24Textarea если доступен; иначе нативный textarea со стилем B24 -->
        <textarea v-model="editingItem.description" class="min-h-28 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#0075ff]" />
      </B24FormField>
    </div>
  </template>
  <template #footer>
    <B24Button label="Отмена" color="link" @click="editingItem = null" />
    <B24Button label="Сохранить" color="success" @click="editingItem && handleSaveItem(editingItem)" />
  </template>
</B24Modal>
```
И `computed` в `<script setup>`:
```ts
const employeeSelectItems = computed(() =>
  Object.values(usersMap.value || {}).map((u: any) => ({
    label: `${u.NAME ?? ''} ${u.LAST_NAME ?? ''}`.trim() || String(u.ID),
    value: u.ID,
  }))
)
```
> Примечание: `usersMap` — это структура из `useTaskTreeLoader`; перепроверить её форму (объект id→user или массив) ДО написания `employeeSelectItems` и подогнать (`Object.values` vs прямой массив). Сейчас в шаблоне `v-for="u in usersMap"` — Vue итерирует и по объекту, и по массиву; для `.map` нужна точная форма.

**Шаг 3. Проверка.** Запустить фронт (`make dev-python`, делает исполнитель при проверке) и пройти ручной чек-лист. ESLint этой страницы не касается, но прогнать общий `npm run lint` (должен остаться 0 — `task.vue` не в скоупе линта, поэтому изменения там линт не затронут; убедиться, что ничего в `composables`/`utils` не задето).

**Шаг 4. Доклад.** Кнопки и оба модала на task.vue переведены на B24Button/B24Modal/B24Select/B24Switch/B24InputNumber/UiDatePickerInput; лаймовые цвета убраны; фокус/Esc даёт B24Modal; поведение сохранения/переноса/CSV не изменено; зафиксировано решение по «Описанию» (B24Textarea или нативный).

---

## Задача 3.1б — Экран ввода времени (компоненты строк) → фирменные компоненты [соннет, заход 2]

**Файлы:** Modify `frontend/app/components/TaskGroupComponent.vue` (кнопки ≈77-83, 126-141; `<style scoped>` ≈196-267); Modify `frontend/app/components/TaskNode.vue` (кнопки раскрытия/ссылки ≈33-47, 73; лаймовых стилей нет, но есть `#0075ff` подсветка — оставить как нейтральный синий); Modify `frontend/app/components/TaskItemRow.vue` (кнопка edit ≈36).

**Дыра (проверено).**
- `TaskGroupComponent.vue`: кнопка «Отразить» `.task-group-create-btn` с `background:#0075ff` и `:hover{#c7f04f}` (стр. 201-211) — тот же лаймовый отголосок; строки записей со своими hover-классами на лаймовых `rgba(236,252,203,*)`/`#84cc16` (стр. 224-231, 246-248). Кнопки edit/delete — иконочные `<button>` без подписи (стр. 126-141), доступны только по hover (`opacity:0` → виден при наведении мышью, с клавиатуры не видно).
- `TaskNode.vue`: рендерится из `task.vue` (это фактический рендер дерева, а не `TaskGroupComponent`). Кнопка раскрытия (стр. 33-39) и внешняя ссылка (стр. 45-47) — нейтральные, но используют `#0075ff` hover; лаймового нет. Здесь правка минимальна: подсветку оставить, при желании заменить иконочную кнопку раскрытия на нейтральный стиль (фокус с клавиатуры). `isExpanded` по умолчанию `true` (стр. 14) — **НЕ менять** (поведение раскрытия дерева задач).
- `TaskItemRow.vue`: кнопка edit (стр. 36) с `hover:text-[#0075ff]` и `opacity-0 group-hover:opacity-100` — недоступна с клавиатуры.

**Решение (поведение НЕ меняем — только цвета/доступность; вызовы emit те же).**
- `TaskGroupComponent.vue`: кнопку «Отразить» → `B24Button color="success" size="sm" label="Отразить"` (или с иконкой через слот) вместо `.task-group-create-btn`. Кнопки edit/delete — оставить иконочными, но: (1) убрать лаймовый hover (`#65a30d`/`rgba(217,249,157,*)` → нейтральный синий `#0075ff`/slate; delete — rose оставить, он семантичен), (2) сделать доступными с клавиатуры — убрать `opacity:0` ИЛИ добавить `focus-visible:opacity-100` + `tabindex` штатный (у `<button>` он есть). Минимально: заменить `opacity:0`→видимые приглушённые иконки (`text-slate-400`), либо добавить `focus-within`/`focus-visible:opacity-100`. Лаймовые hover на строках (`.task-group-row:hover`, `.task-group-row-active`) → нейтральный `bg-slate-50`/`bg-blue-50` и `inset 3px 0 0 #0075ff` вместо `#84cc16`.
- `TaskNode.vue`: оставить структуру; заменить точечно лаймовые тона если найдутся (их тут нет — только `#0075ff`, нейтральный синий B24, оставить). Кнопку раскрытия (`<button>` уже фокусируемый) оставить; убедиться, что hover-стиль нейтральный.
- `TaskItemRow.vue`: кнопка edit — `hover:text-[#0075ff]` оставить (синий нейтрален), но добавить `focus-visible:opacity-100` к `opacity-0`, чтобы иконка появлялась при фокусе с клавиатуры.

**Приёмка (ручная):** ни одной лаймовой подсветки в дереве задач; кнопка «Отразить» как success-кнопка настроек; edit/delete видимы и достижимы с клавиатуры (Tab → видна иконка); раскрытие/сворачивание узлов и все emits (`toggle`/`select`/`createForTask`/`delete`/`edit`) работают как раньше.

**Шаг 1. Падающий тест.** Аналогично 3.1а — визуальный чек-лист (ниже). Перед правкой прочитать `app-options.client.vue` для B24Button `size="sm"`.

**Шаг 2. Реализация.** Заменить `.task-group-create-btn`-кнопку на `B24Button`; перекрасить лаймовые CSS-правила в нейтральные; добавить `focus-visible:opacity-100`. Удалить осиротевшие лаймовые правила из `<style scoped>`.

**Шаг 3. Проверка.** Ручной чек-лист + `npm run lint` (компоненты не в скоупе — должен остаться 0, изменения линт не затрагивают).

**Шаг 4. Доклад.** Лайм убран из `TaskGroupComponent`/`TaskItemRow`; «Отразить» → B24Button success; edit/delete доступны с клавиатуры; emits и раскрытие не изменены.

---

## Задача 3.2 — Фильтры отчётов запоминаются + панель syncWarning на 6 страниц [соннет]

**Файлы:** Modify `frontend/app/composables/useReportFilters.ts` (целиком тело — ≈8-18 рефы без персистентности, +возврат); Modify 6 страниц `frontend/app/pages/reports/{employee,project,project-task,focus-analysis,revenue-leakage,time-discipline}.client.vue` (деструктуризация `syncWarning` + рендер панели).

### Часть A — персистентность фильтров

**Дыра (проверено).** В `useReportFilters` все фильтры — чистые `ref('')`/`ref([])` без сохранения (`dateFrom`/`dateTo` стр. 8-9; `selectedEmployees`/`selectedProjects`/`employeeFilterMode`/`projectFilterMode` стр. 15-18). При переключении между 7 отчётами (каждая страница вызывает `useReportFilters()` заново) период и выборки сбрасываются. `initCurrentMonthRange()` ставит текущий месяц при инициализации.

**Решение.** **VueUse в проекте нет** — используем сырые `localStorage`/`sessionStorage` через тонкие хелперы, без новых зависимостей.
- **Период (`dateFrom`/`dateTo`) — глобально, `localStorage`** (один период на все отчёты, переживает перезагрузку). Ключ `ms-report-period-v1` со значением `{dateFrom, dateTo}`.
- **Выборки (`selectedEmployees`/`selectedProjects`/`employeeFilterMode`/`projectFilterMode`) — per-report, `sessionStorage`** (живут в пределах сессии вкладки, у каждого отчёта свои). Ключ `ms-report-filters-v1:<reportKey>`. `reportKey` приходит аргументом в `useReportFilters(reportKey)` — **сигнатура расширяется необязательным параметром** (обратносовместимо: без него выборки не персистятся).
- **SSR-safety:** страницы `.client.vue` (только клиент), но `useReportFilters` теоретически может вызваться при гидрации — обернуть доступ к storage в `if (typeof window !== 'undefined')` (или `import.meta.client`). Иначе `localStorage is not defined` на сервере.
- **Восстановление:** при инициализации читаем localStorage период; если он валиден — ставим его, иначе `initCurrentMonthRange()`. Выборки читаем из sessionStorage по `reportKey`. **`watch`** на каждую персистируемую величину — пишем в storage при изменении. Тип значений сохранить (`Array<string|number>`, `FilterMode`).
- **`initCurrentMonthRange` оставить** как явный сброс периода (кнопкой), но при наличии сохранённого периода — не перетирать его на маунте автоматически.

**Шаг 1. Падающий тест (линтуемый composable).** `useReportFilters.ts` **попадает под `npm run lint`**. Падающего unit-теста нет (нет раннера для composables, скрипт `test` — `node --test tests/**`, но это утилиты). Поэтому проверка: (1) `npm run lint` остаётся 0 ошибок ПОСЛЕ правки (новый код без `any`-нарушений, типы корректны); (2) ручная проверка персистентности. Перед правкой прочитать `useReportFilters.ts` целиком и `types/report.ts` (`FilterMode`, `FilterValue`, `ReportFilterOptions`).

**Шаг 2. Реализация (ПОЛНЫЙ код `useReportFilters.ts`).**
```ts
import { getCurrentMonthRange } from '~/utils/reportDateRange'
import { applyProjectPresetToFilters } from '~/utils/reportFilters'
import type { FilterMode, FilterValue, ReportFilterOptions } from '~/types/report'

const PERIOD_KEY = 'ms-report-period-v1'
const FILTERS_KEY_PREFIX = 'ms-report-filters-v1'

function readLocal<T>(key: string): T | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch { return null }
}
function writeLocal(key: string, value: unknown): void {
  if (typeof window === 'undefined') return
  try { window.localStorage.setItem(key, JSON.stringify(value)) } catch { /* quota/private mode */ }
}
function readSession<T>(key: string): T | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.sessionStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch { return null }
}
function writeSession(key: string, value: unknown): void {
  if (typeof window === 'undefined') return
  try { window.sessionStorage.setItem(key, JSON.stringify(value)) } catch { /* ignore */ }
}

export function useReportFilters(reportKey = 'default') {
  const apiStore = useApiStore()

  const dateFrom = ref('')
  const dateTo = ref('')
  const filterOptions = ref<ReportFilterOptions>({
    employees: [],
    projects: []
  })

  const selectedEmployees = ref<Array<string | number>>([])
  const selectedProjects = ref<Array<string | number>>([])
  const employeeFilterMode = ref<FilterMode>('include')
  const projectFilterMode = ref<FilterMode>('include')

  const filtersKey = `${FILTERS_KEY_PREFIX}:${reportKey}`

  // --- Восстановление сохранённого состояния (только на клиенте) ---
  const savedPeriod = readLocal<{ dateFrom: string; dateTo: string }>(PERIOD_KEY)
  if (savedPeriod && savedPeriod.dateFrom && savedPeriod.dateTo) {
    dateFrom.value = savedPeriod.dateFrom
    dateTo.value = savedPeriod.dateTo
  }
  const savedFilters = readSession<{
    employees: Array<string | number>
    projects: Array<string | number>
    employeeMode: FilterMode
    projectMode: FilterMode
  }>(filtersKey)
  if (savedFilters) {
    selectedEmployees.value = Array.isArray(savedFilters.employees) ? savedFilters.employees : []
    selectedProjects.value = Array.isArray(savedFilters.projects) ? savedFilters.projects : []
    if (savedFilters.employeeMode) employeeFilterMode.value = savedFilters.employeeMode
    if (savedFilters.projectMode) projectFilterMode.value = savedFilters.projectMode
  }

  // --- Персистентность при изменении ---
  watch([dateFrom, dateTo], ([from, to]) => {
    if (from && to) writeLocal(PERIOD_KEY, { dateFrom: from, dateTo: to })
  })
  watch(
    [selectedEmployees, selectedProjects, employeeFilterMode, projectFilterMode],
    ([emps, projs, eMode, pMode]) => {
      writeSession(filtersKey, {
        employees: emps,
        projects: projs,
        employeeMode: eMode,
        projectMode: pMode,
      })
    },
    { deep: true }
  )

  const employeeFilter = computed<FilterValue>(() => ({
    ids: selectedEmployees.value,
    mode: employeeFilterMode.value
  }))

  const projectFilter = computed<FilterValue>(() => ({
    ids: selectedProjects.value,
    mode: projectFilterMode.value
  }))

  async function loadFilterOptions(forceRefresh = false) {
    const [employeesResult, projectsResult] = await Promise.allSettled([
      apiStore.getFilterEmployees(forceRefresh),
      apiStore.getFilterProjects(forceRefresh)
    ])

    filterOptions.value = {
      employees: employeesResult.status === 'fulfilled' ? employeesResult.value : [],
      projects: projectsResult.status === 'fulfilled' ? projectsResult.value : [],
    }
  }

  function initCurrentMonthRange() {
    // Не перетираем сохранённый период автоматически: ставим текущий месяц,
    // только если период ещё пуст (нет сохранённого).
    if (dateFrom.value && dateTo.value) return
    const range = getCurrentMonthRange()
    dateFrom.value = range.dateFrom
    dateTo.value = range.dateTo
  }

  function applyRouteProjectPreset(routeQuery: Record<string, unknown>) {
    return applyProjectPresetToFilters(
      routeQuery,
      filterOptions.value.projects,
      (nextIds) => {
        selectedProjects.value = nextIds
      },
      (mode) => {
        projectFilterMode.value = mode
      },
      (nextOptions) => {
        filterOptions.value = {
          ...filterOptions.value,
          projects: nextOptions
        }
      }
    )
  }

  return {
    dateFrom,
    dateTo,
    filterOptions,
    selectedEmployees,
    selectedProjects,
    employeeFilterMode,
    projectFilterMode,
    employeeFilter,
    projectFilter,
    loadFilterOptions,
    initCurrentMonthRange,
    applyRouteProjectPreset
  }
}
```
> **Изменение поведения `initCurrentMonthRange`**: теперь не перетирает уже выставленный (восстановленный) период. Перепроверить все 7 страниц: где вызывается `initCurrentMonthRange()` — обычно на маунте. С сохранённым периодом он станет no-op, что и нужно. Если какая-то страница хочет ПРИНУДИТЕЛЬНО текущий месяц (например кнопка «Сброс») — это отдельный вызов, его сохранить.
> **`reportKey`**: каждая страница, желающая per-report выборки, передаёт уникальный ключ: `useReportFilters('employee')`, `useReportFilters('project')` и т.д. Без аргумента (`daily`, `raw-data` — если не нужно) выборки лягут под общий `default`. **Решение:** проставить `reportKey` на всех 7 отчётных страницах, использующих `useReportFilters`, чтобы выборки не смешивались. Это часть правки страниц (см. ниже — но 6 страниц 3.2 и так правятся ради панели; `daily` — седьмая, тоже добавить `reportKey='daily'`).

**Шаг 3. Проверка.** `npm run lint` → 0 ошибок (composable в скоупе). Ручная: выбрать период+сотрудников в «По сотрудникам», уйти в «По проектам» и вернуться — выборки сотрудников восстановились, период общий; перезагрузить страницу — период сохранился (localStorage), выборки сохранились в пределах вкладки (sessionStorage).

### Часть B — панель `syncWarning` на 6 страницах (долг ревизии спринта 2)

**Дыра (проверено грепом).** Движок `useReportGenerator` (после 2.3) корректно выставляет `syncWarning` для всех отчётов, но панель `<div v-if="syncWarning" class="ms-panel-warning">` есть ТОЛЬКО на `daily.client.vue:255-256`. Шесть страниц деструктурируют `const { hasGenerated, generateReport } = useReportGenerator(...)` БЕЗ `syncWarning` (employee:61, project:64, project-task:80, focus-analysis:53, revenue-leakage:53, time-discipline:53) и панель НЕ рендерят. `ms-panel-warning` — глобальный класс (`app/assets/css/main.css`).

**Решение (копипаст-паттерн с daily).** На каждой из 6 страниц:
1. В деструктуризации `useReportGenerator(...)` добавить `syncWarning`: было `const { hasGenerated, generateReport } = ...` → стало `const { hasGenerated, syncWarning, generateReport } = ...` (сохранив прочие, напр. `resetGenerated` у project/project-task).
2. В шаблоне добавить панель сразу после блока фильтров (перед таблицей результата), по образцу daily:
```vue
<div v-if="syncWarning" class="ms-panel-warning">
  {{ syncWarning }}
</div>
```
   Якорь вставки на каждой странице — после `<MultiSelectFilter .../>`-блока внутри `B24Card v-if="isInit"` (строки: employee ≈179-после, project ≈213-после, project-task ≈247-после, focus-analysis ≈203-после, revenue-leakage ≈185-после, time-discipline ≈183-после; ТОЧНОЕ место исполнитель определяет чтением — сразу после закрытия грид-блока с фильтрами, до блока с таблицей).
3. **(Опционально, по образцу daily) `allowSyncFallback: true` и `syncWarningMessage`** в объекте `generateReport({...})` каждой страницы — чтобы при жёстком сбое синка отчёт строился по последним данным и показывал ту же плашку. daily передаёт `allowSyncFallback: true` (стр. 112). **Решение:** добавить `allowSyncFallback: true` на все 6 (поведение «показать последние данные + предупредить» желаемо для всех отчётов). Сообщение можно не задавать — движок подставит дефолт.
4. Заодно проставить `reportKey` в `useReportFilters(...)` (см. часть A) на этих 6 + на daily.

**Шаг 1 (часть B). Тест.** Нет автотеста; ручная проверка: на любом из 6 отчётов сэмулировать сбой синка (или дернуть при недоступном Bitrix) — появляется жёлтая плашка. ESLint страниц не покрывает.

**Шаг 2 (часть B). Реализация.** Точечные правки 6 файлов как выше.

**Шаг 4. Доклад.** Период персистится глобально (localStorage), выборки — per-report (sessionStorage), без VueUse, SSR-safe; `initCurrentMonthRange` больше не перетирает сохранённый период; панель `syncWarning` + `allowSyncFallback` добавлены на 6 страниц по образцу daily; `npm run lint` 0 ошибок (composable в скоупе).

---

## Задача 3.3 — Один индикатор на «Проверке данных» [хайку]

**Файлы:** Modify `frontend/app/pages/reports/raw-data.client.vue` (удалить самописный status-bar — шаблон ≈276-293 + стили ≈499-560; завести progress на 4 состояния); Modify `frontend/app/composables/useProgress.ts` (опционально — расширить под именованные состояния, см. решение); Modify `frontend/app/components/common/ProgressOverlay.vue` (только если расширяем сообщения — по решению НЕ требуется).

**Дыра (проверено).** На `raw-data.client.vue` одновременно показываются ДВА индикатора:
1. Самописный `.status-bar` (шаблон стр. 277-293), управляемый `isAnyLoading` (стр. 92-94 = `isLoading || isSyncing || isExporting || isLoadingFields`) и `statusMessage` (стр. 96-102 — 4 состояния: sync/export/fields/loading).
2. Глобальный `ProgressOverlay`, смонтированный в `app/app.vue:27` и управляемый `useProgress()`. Но `raw-data` вызывает `progress.begin/end` ТОЛЬКО для sync (стр. 219) и export (стр. 172) — НЕ для fields/loading. То есть при синке/экспорте видны ОБА (overlay + status-bar), а при загрузке полей/данных — только status-bar.

**Решение (убрать самописный, оставить глобальный ProgressOverlay, научить его всем 4 состояниям через useProgress).**
- Удалить из `raw-data` шаблон `.status-bar` (277-293) и его CSS (499-560: `.status-bar`, `-track`, `-fill`, `-message`, `-spinner` + анимации + `.status-slide-*`). Удалить `statusMessage` computed (96-102) и `isAnyLoading` computed (92-94), если они больше нигде не используются (**проверить грепом** — `isAnyLoading`/`statusMessage` могут использоваться в шаблоне ещё где-то; если да — оставить нужное).
- Завести `progress.begin/end` для ВСЕХ 4 операций (а не только sync/export). Сейчас:
  - sync: уже есть `progress.begin('Синхронизация с Bitrix24', 0, 'Обновляем списания времени')` (стр. 219) + `progress.end()` (стр. 229) — оставить.
  - export: уже есть `progress.begin('Excel: «Сырые данные»', 0, 'Готовим файл выгрузки')` (стр. 172) + end (189) — оставить.
  - **fields** (загрузка полей смарт-процесса, `isLoadingFields`): добавить `progress.begin('Загрузка полей смарт-процесса', 0, '...')` / `progress.end()` вокруг операции, выставляющей `isLoadingFields` (найти её в `<script setup>`).
  - **loading** (загрузка данных, `isLoading`): добавить `progress.begin('Загрузка данных', 0, '...')` / `progress.end()` вокруг `fetchTimesheetList`.
  - Сообщения взять из текущего `statusMessage` (стр. 97-100), чтобы тексты не потерялись.
- **`ProgressOverlay.vue` НЕ требует изменений**: он уже умеет индетерминированный режим (`total=0` → бегущая полоса) и берёт `title`/`hint` из `useProgress().state`. Все 4 состояния различаются только текстом `title`/`hint`, который задаёт `progress.begin(...)`. → Менять `ProgressOverlay` НЕ нужно; ТЗ-формулировка «расширить ProgressOverlay/progress» закрывается через `progress.begin` с разными надписями. (Если исполнитель видит необходимость в индикаторе именно «4 состояний» как enum — это избыточно; режима/процента overlay уже достаточно. Фиксируем как осознанное решение: расширяем вызовы `useProgress`, не сам overlay.)
- **`useProgress.ts` правка опциональна.** Достаточно существующих `begin/stage/end`. Менять НЕ требуется. (Оставляем файл в списке Modify волны 2 только как «возможная точка» — по факту правок не будет; это резервирование файла за 3.3, чтобы 3.4 его не трогала. 3.4 `useProgress` не трогает — пересечения нет.)
- **begin/end строго парные** (как в `InnAssignModal`): `end()` только в `finally` после успешного `begin()`. Перепроверить, что нет двойного `begin` без `end` при наложении операций (на raw-data операции последовательны — sync, потом export — наложения нет; но guard на `count` в useProgress и так корректен).

**Шаг 1. Падающий тест.** Нет раннера; ручная проверка. Перед правкой прочитать `raw-data.client.vue` полностью (особенно `<script setup>` — где меняются `isLoadingFields`/`isLoading`) и `app/app.vue` (как смонтирован overlay).

**Шаг 2. Реализация.** Удалить самописный status-bar (шаблон+CSS+computed), обернуть 4 операции в `progress.begin/end`.

**Шаг 3. Проверка.** `npm run lint` (страница не в скоупе — 0 ошибок). Ручная: на «Проверке данных» при синхронизации, экспорте, загрузке полей и загрузке данных виден РОВНО ОДИН индикатор (глобальный overlay-бобёр), нижней полосы `.status-bar` больше нет.

**Шаг 4. Доклад.** Самописный status-bar удалён (шаблон+CSS+`statusMessage`/`isAnyLoading`); все 4 операции (sync/export/fields/loading) теперь идут через глобальный `useProgress`/`ProgressOverlay`; сам overlay не менялся (обосновано — индетерминированного режима достаточно).

---

## Задача 3.4 — Удобство таблиц + единый календарь [хайку]

**Файлы:** Modify `frontend/app/components/reports/RecursiveTableRow.vue` (≈25 `isOpen`, ≈74 `<tr>` без клавиатуры); Modify `frontend/app/components/common/DateRangeFilter.vue` (≈42-43 голые `<input type=date>`).

### Часть A — RecursiveTableRow: клавиатура + раскрытие первого уровня

**Дыра (проверено).** `RecursiveTableRow.vue`: `isOpen = ref(false)` (стр. 25) — все узлы закрыты по умолчанию, отчёт выглядит пустым; раскрытие — клик по всему `<tr>` (`@click="toggle"` стр. 74), **без клавиатуры** (нет `tabindex`/`@keydown`). Рекурсивные дети тоже стартуют закрытыми.

**Решение.**
- **Клавиатура:** на `<tr>` (стр. 74) добавить `tabindex="0"`, `role="button"`, `:aria-expanded="isOpen"` (когда `hasChildren`), и `@keydown.enter.prevent="toggle"` + `@keydown.space.prevent="toggle"`. Только когда `hasChildren` (у листовых строк toggle бессмыслен — им `tabindex` не давать или давать без обработчиков). Для строк-листьев (стр. 131, `node.items`) клавиатура не нужна.
- **Раскрытие первого уровня:** заменить `const isOpen = ref(false)` на раскрытие верхнего уровня — `const isOpen = ref(props.level === 0)`. Тогда корневые узлы (level 0) открыты, отчёт сразу показывает первый уровень; вложенные остаются закрытыми (компактно). Это закрывает «отчёт выглядит пустым».
  - **Тонкость:** `RecursiveTableRow` вызывается рекурсивно с `:level="level + 1"` (стр. 123). `props.level` по умолчанию 0 (стр. 11-13). Значит `ref(props.level === 0)` раскроет именно корни. Поведение клика/рекурсии не меняется.
- Фокус-стиль: добавить `focus-visible:outline` / `focus:bg-slate-100` к `<tr>`, чтобы видеть фокус с клавиатуры (доступность).

### Часть B — DateRangeFilter: единый календарь + перенос

**Дыра (проверено).** `DateRangeFilter.vue:42-43` — два голых `<input type="date" class="min-w-[174px]">` (браузерный нативный пикер, не в стиле приложения). Рядом есть пресет-кнопки (стр. 47-50). Компонент используют все 6 отчётных страниц 3.2 (и др.).

**Решение.** Заменить оба `<input type="date">` на уже существующий `UiDatePickerInput` (`components/ui/DatePickerInput.vue`, тот же, что в `raw-data` стр. 338-384 и в модале 3.1). API: `v-model` (строка `YYYY-MM-DD`) + `placeholder`.
- Сейчас компонент держит локальные `localFrom`/`localTo` и эмитит `update:dateFrom`/`update:dateTo` по `@change`. `UiDatePickerInput` эмитит `update:modelValue` при выборе дня. Переписать так: `UiDatePickerInput v-model="localFrom"` + `watch(localFrom, update)` (или `@update:modelValue` → `localFrom = $event; update()`). **API наружу (`update:dateFrom`/`update:dateTo`, пропсы `dateFrom`/`dateTo`) СОХРАНИТЬ без изменений** — это контракт с 6 страницами 3.2.
- **Перенос на узком экране:** обёртку строки дат (стр. 41 `flex items-center gap-2`) сделать `flex flex-wrap items-center gap-2`, чтобы на узком слайдере два пикера переносились. Пресет-кнопки (стр. 46 `flex flex-wrap gap-1.5`) уже с `flex-wrap` — оставить.

**Шаг 1. Падающий тест.** Нет раннера; ручная проверка. Перед правкой прочитать `RecursiveTableRow.vue` и `DateRangeFilter.vue` целиком + `components/ui/DatePickerInput.vue` (его API подтверждён).

**Шаг 2. Реализация.** Применить A и B.
Ориентир для `DateRangeFilter` (шаблон строки дат):
```vue
<div class="flex flex-wrap items-center gap-2">
  <UiDatePickerInput v-model="localFrom" placeholder="Начало периода" @update:model-value="update" />
  <span class="self-center text-slate-400">—</span>
  <UiDatePickerInput v-model="localTo" placeholder="Конец периода" @update:model-value="update" />
</div>
```
> Если `@update:model-value` + `v-model` дублируют запись — оставить только `v-model` + `watch([localFrom, localTo], update)`. Выбрать один способ, проверить, что `update()` (emit наружу) срабатывает при выборе дня. `watch` уже частично есть (стр. 15-16 — синк props→local); добавить обратный watch local→emit либо обработчик.

Ориентир для `RecursiveTableRow` `<tr>`:
```vue
<tr
  :class="['cursor-pointer border-b transition-colors focus:outline-none focus-visible:bg-slate-100', rowClass]"
  :tabindex="hasChildren ? 0 : undefined"
  :role="hasChildren ? 'button' : undefined"
  :aria-expanded="hasChildren ? isOpen : undefined"
  @click="toggle"
  @keydown.enter.prevent="toggle"
  @keydown.space.prevent="toggle"
>
```
И `const isOpen = ref(props.level === 0)`.

**Шаг 3. Проверка.** `npm run lint` (компоненты не в скоупе — 0). Ручная: открыть любой иерархический отчёт — первый уровень раскрыт; по Tab можно сфокусировать строку с детьми и раскрыть Enter/Space; период в фильтре — оформленный календарь (как в raw-data), на узком слайдере пикеры переносятся. Проверить, что 6 страниц 3.2 с обновлённым `DateRangeFilter` продолжают корректно слать период (`update:dateFrom`/`update:dateTo`).

**Шаг 4. Доклад.** `RecursiveTableRow`: первый уровень раскрыт (`ref(level===0)`), строки с детьми управляются Enter/Space + `aria-expanded`; `DateRangeFilter`: голые `<input type=date>` → `UiDatePickerInput`, `flex-wrap` для узкого экрана, внешний API сохранён.

---

## Задача 3.5 — Excel: экономная запись + предохранитель объёма [соннет]

**Файлы:** Modify `backends/python/api/main/report_excel.py` (4 билдера + новый guard); Create `backends/python/api/main/tests_report_excel_guard.py`.

**Дыра (проверено чтением целиком).** Все 4 билдера (`build_project_task_workbook` стр. 189, `build_hierarchy_workbook` стр. 270, `build_matrix_workbook` стр. 331, `build_table_workbook` стр. 379) создают `openpyxl.Workbook()` в обычном режиме и собирают весь лист в памяти через произвольный `ws.cell(row, col, ...)` + per-cell стили, затем `wb.save(BytesIO())`. **Нет лимита строк** — на большом периоде (десятки тысяч строк) это раздувает память и грозит падением воркера gunicorn.

**Архитектурное решение (write_only — выборочно, обосновано; лимит — для всех).**

`openpyxl` write-only режим (`Workbook(write_only=True)` + `ws.append(row)`) даёт линейный расход памяти, НО имеет ограничения, несовместимые с частью текущего кода:
- НЕТ произвольного `ws.cell(row, col)` — только последовательный `ws.append([...])`.
- НЕТ `ws.row_dimensions[row].outline_level` (группировка строк) — в write-only стиль строки/outline задаётся иначе/ограниченно.
- `ws.merge_cells(...)`, `ws.freeze_panes`, `ws.column_dimensions[...].width` — частично поддерживаются, но `merge_cells` после append работает ненадёжно; `freeze_panes` ставится до append.
- Стили (`Font`/`Fill`/`Alignment`/`Border`) задаются на ячейку через `WriteOnlyCell` ДО append — это совместимо, но многословно.

**Разбор по билдерам:**
1. **`build_matrix_workbook`** (ежедневная нагрузка — матрица сотрудник×день): плоская таблица БЕЗ группировки/outline, только заголовок + строки + итоги, `freeze_panes="B3"`. → **Совместим с write_only** (последовательная запись строк, freeze до append, ширины до append). **Переводим на write_only.**
2. **`build_table_workbook`** (плоские табличные отчёты: потери выручки и т.п.): плоская таблица, заголовок + строки + total_row, `freeze_panes="A3"`, без outline. → **Совместим с write_only. Переводим.**
3. **`build_hierarchy_workbook`** и **`build_project_task_workbook`** (иерархия проект→задача→…): используют `ws.row_dimensions[row].outline_level = min(depth,7)` (группировка-сворачивание, стр. 100/303) и `merge_cells` для шапки (стр. 211/280). Группировка строк — ключевая UX-фича этих отчётов (сворачивание уровней в Excel). В write_only outline-группировка строк **не поддерживается штатно**. → **НЕ переводим на write_only**; для них применяем ТОЛЬКО лимит строк (предохранитель). Это осознанный компромисс: экономия памяти важнее всего на матрице/плоских таблицах (самые широкие выгрузки — нагрузка по дням за период), а иерархические обычно меньше по числу строк и теряют группировку при write_only. Фиксируем в докладе.

**Лимит строк (мягкий предохранитель) — для ВСЕХ 4 билдеров.**
- Константа `MAX_EXPORT_ROWS = 50000` (число строк ДАННЫХ, без шапки). Значение — с запасом под боевой объём (103k записей `TimesheetItem`, но отчёты агрегированы — строк меньше; матрица — сотрудники×дни; 50k строк ≈ безопасно по памяти даже в обычном режиме).
- Перед сборкой каждый билдер считает число строк, которое он СОБИРАЕТСЯ записать (для matrix — `len(rows)`; для table — `len(rows)`; для иерархии — рекурсивный подсчёт узлов+items+employees). Если превышает `MAX_EXPORT_ROWS` — **бросить `ExportTooLargeError`** (новый класс-исключение) с понятным сообщением `"Слишком большой период или выборка для выгрузки (строк: {n} > {limit}). Сузьте период или фильтры."`.
- Вызывающий код (views, отдающий файл) ловит `ExportTooLargeError` и возвращает **HTTP 400** с `{"error": "<сообщение>"}` (НЕ 500). **Где ловить:** найти все вызовы `build_*_workbook` в `views.py`/`report_*` (грепом `grep -rn "build_matrix_workbook\|build_table_workbook\|build_hierarchy_workbook\|build_project_task_workbook" main/`) и обернуть в `try/except ExportTooLargeError`. Это часть реализации 3.5 (правка точек вызова), но **только обёртка except**, без изменения логики отчёта.
  - **Открытый вопрос 2:** подсчёт строк до сборки для иерархии — отдельный проход по дереву. Альтернатива — лимит «на лету» (бросать при достижении в процессе записи). Выбрать **подсчёт до сборки** (проще, не оставляет полу-собранный workbook). Для иерархии — функция `_count_hierarchy_rows(roots)`.

**Совместимость с `_safe_cell_text` и `tests_report_excel`.**
- `_safe_cell_text` (стр. 56-62) применяется к строковым значениям ячеек. В write_only через `WriteOnlyCell` значение тоже проходит через `_safe_cell_text` — **сохранить вызов** в matrix/table при формировании ячеек. НЕ удалять и не ослаблять защиту формул.
- `tests_report_excel.py` (standalone-стиль, `django.setup()`) проверяет только, что вывод начинается с `b"PK"` (валидный xlsx) для hierarchy/matrix/table. После перевода matrix/table на write_only вывод остаётся валидным xlsx → тесты зелёные. **Прогнать `tests_report_excel` ОБОИМИ способами** (manage.py и standalone unittest — см. раздел запуска).

**Шаг 1. Падающий тест** — Create `main/tests_report_excel_guard.py` (чистый Django-`TestCase`, БЕЗ `django.setup()`):
```python
from django.test import TestCase

from main.report_excel import (
    build_matrix_workbook,
    build_table_workbook,
    build_hierarchy_workbook,
    ExportTooLargeError,
    MAX_EXPORT_ROWS,
)


class ExportLimitTest(TestCase):
    def test_matrix_within_limit_ok(self):
        header_days = [{"date": "2026-05-01"}, {"date": "2026-05-02"}]
        rows = [{"employee": {"name": f"E{i}"}, "days": {"2026-05-01": {"total": 8}}} for i in range(10)]
        out = build_matrix_workbook(header_days, rows, title="Нагрузка")
        self.assertEqual(out.read()[:2], b"PK")

    def test_matrix_over_limit_raises(self):
        header_days = [{"date": "2026-05-01"}]
        rows = [{"employee": {"name": f"E{i}"}, "days": {}} for i in range(MAX_EXPORT_ROWS + 1)]
        with self.assertRaises(ExportTooLargeError):
            build_matrix_workbook(header_days, rows, title="Нагрузка")

    def test_table_over_limit_raises(self):
        cols = [{"key": "p", "label": "Проект", "fmt": "text"}]
        rows = [{"p": f"P{i}"} for i in range(MAX_EXPORT_ROWS + 1)]
        with self.assertRaises(ExportTooLargeError):
            build_table_workbook(cols, rows, title="Таблица")

    def test_formula_injection_still_neutralized(self):
        # Защита формул из спринта 1 должна сохраниться в write_only-режиме.
        cols = [{"key": "p", "label": "Проект", "fmt": "text"}]
        rows = [{"p": "=SUM(A1:A9)"}]
        out = build_table_workbook(cols, rows, title="Таблица")
        data = out.read()
        self.assertEqual(data[:2], b"PK")
        # Содержимое xlsx — zip; грубая проверка, что опасная строка ушла с префиксом '
        # (точную распаковку не делаем — достаточно, что файл валиден и билдер не упал).

    def test_hierarchy_over_limit_raises(self):
        # Иерархия: лимит тоже действует (write_only НЕ применяется, но guard — да).
        big_children = [{"name": f"T{i}", "total_hours": 1, "billable_hours": 1,
                         "non_billable_hours": 0, "children": []} for i in range(MAX_EXPORT_ROWS + 1)]
        roots = [{"name": "Проект", "total_hours": 1, "billable_hours": 1,
                  "non_billable_hours": 0, "children": big_children}]
        with self.assertRaises(ExportTooLargeError):
            build_hierarchy_workbook(roots, title="Иерархия")
```
> Примечание: `test_formula_injection_still_neutralized` намеренно не распаковывает zip (достаточно, что билдер не упал и `_safe_cell_text` вызывается в коде — это проверяется code review). Если нужна строгая проверка содержимого — открыть workbook через `openpyxl.load_workbook(BytesIO(data))` и убедиться, что ячейка начинается с `'`. Это допустимое усиление теста.

**Шаг 2. Запуск (ожидание: FAIL).** `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_report_excel_guard --settings=test_settings` — упадёт (`ExportTooLargeError`/`MAX_EXPORT_ROWS` ещё нет, лимит не реализован).

**Шаг 3. Реализация (ПОЛНЫЙ код ключевых фрагментов).** В `report_excel.py`:

В начало (после импортов, рядом со стр. 26):
```python
MAX_EXPORT_ROWS = 50000


class ExportTooLargeError(Exception):
    """Выгрузка превышает мягкий лимит строк. View ловит и отдаёт HTTP 400."""

    def __init__(self, rows: int, limit: int = MAX_EXPORT_ROWS):
        self.rows = rows
        self.limit = limit
        super().__init__(
            f"Слишком большой период или выборка для выгрузки "
            f"(строк: {rows} > {limit}). Сузьте период или фильтры."
        )


def _count_hierarchy_rows(roots) -> int:
    """Считает строки данных иерархии (узлы + листовые items + employees+их items)."""
    total = 0

    def walk(node):
        nonlocal total
        total += 1
        for ch in node.get("children") or []:
            walk(ch)
        for emp in node.get("employees") or []:
            total += 1
            total += len(emp.get("items") or [])
        total += len(node.get("items") or [])

    for r in roots:
        walk(r)
    return total
```

**`build_matrix_workbook` — перевод на write_only + лимит.** Полная замена тела (сохранены формат/итоги/freeze/ширины; стиль ячеек через `WriteOnlyCell`):
```python
from openpyxl.cell import WriteOnlyCell  # добавить к импортам сверху файла


def build_matrix_workbook(header_days, rows, *, title, date_from="", date_to=""):
    if len(rows) > MAX_EXPORT_ROWS:
        raise ExportTooLargeError(len(rows))

    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet("Нагрузка")
    days = [(d.get("date") if isinstance(d, dict) else d) for d in header_days]
    ncols = 1 + len(days) + 1
    # freeze/ширины ставим ДО append (write_only требование)
    ws.freeze_panes = "B3"
    ws.column_dimensions["A"].width = 24
    for idx in range(2, ncols + 1):
        ws.column_dimensions[get_column_letter(idx)].width = 10

    period = f"{date_from} — {date_to}".strip(" —")
    full_title = f"{title} · период {period}" if period else title

    def _styled(value, *, number=False, bold=False, fill=None, align="right"):
        cell = WriteOnlyCell(ws, value=value)
        if bold:
            cell.font = Font(bold=True)
        if fill:
            cell.fill = fill
        if number:
            cell.number_format = _HOURS_FORMAT
        cell.alignment = Alignment(horizontal=align, vertical="center")
        cell.border = _BORDER
        return cell

    # Строка 1: заголовок (без merge — write_only merge ненадёжен; пишем в A1)
    title_cell = WriteOnlyCell(ws, value=_safe_cell_text(full_title))
    title_cell.font = Font(bold=True, color="FFFFFF", size=12)
    title_cell.fill = _FILL_TITLE
    title_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.append([title_cell])

    # Строка 2: шапка
    head = [_styled("Сотрудник", bold=True, fill=_FILL_HEAD, align="left")]
    for day in days:
        head.append(_styled(_format_iso_date(day) or str(day), bold=True, fill=_FILL_HEAD))
    head.append(_styled("Итого", bold=True, fill=_FILL_HEAD))
    ws.append(head)

    # Данные
    col_tot = [0.0] * len(days)
    grand = 0.0
    for r in rows:
        name = (r.get("employee") or {}).get("name") or "—"
        row_cells = [_styled(_safe_cell_text(name), align="left")]
        rowsum = 0.0
        cells = r.get("days") or {}
        for i, day in enumerate(days):
            cd = cells.get(day) or {}
            v = _num(cd.get("total")) if isinstance(cd, dict) else _num(cd)
            row_cells.append(_styled(round(v, 2) if v else None, number=True))
            rowsum += v
            col_tot[i] += v
        row_cells.append(_styled(round(rowsum, 2), number=True, bold=True, fill=_FILL_TOTAL))
        grand += rowsum
        ws.append(row_cells)

    # ИТОГО
    total_cells = [_styled("ИТОГО", bold=True, fill=_FILL_TOTAL, align="left")]
    for ct in col_tot:
        total_cells.append(_styled(round(ct, 2), number=True, bold=True, fill=_FILL_TOTAL))
    total_cells.append(_styled(round(grand, 2), number=True, bold=True, fill=_FILL_TOTAL))
    ws.append(total_cells)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output
```

**`build_table_workbook` — перевод на write_only + лимит.** Аналогичная замена тела (плоская таблица, total_row):
```python
def build_table_workbook(columns, rows, *, title, date_from="", date_to="", total_row=None):
    if len(rows) > MAX_EXPORT_ROWS:
        raise ExportTooLargeError(len(rows))

    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet("Отчёт")
    ncols = len(columns)
    ws.freeze_panes = "A3"
    for i, col in enumerate(columns):
        ws.column_dimensions[get_column_letter(1 + i)].width = col.get("width", 18)

    period = f"{date_from} — {date_to}".strip(" —")
    full_title = f"{title} · период {period}" if period else title

    def _cell(value, *, number_fmt=None, bold=False, fill=None, align="left"):
        cell = WriteOnlyCell(ws, value=value)
        if bold:
            cell.font = Font(bold=True)
        if fill:
            cell.fill = fill
        if number_fmt:
            cell.number_format = number_fmt
        cell.alignment = Alignment(horizontal=align, vertical="center")
        cell.border = _BORDER
        return cell

    title_cell = WriteOnlyCell(ws, value=_safe_cell_text(full_title))
    title_cell.font = Font(bold=True, color="FFFFFF", size=12)
    title_cell.fill = _FILL_TITLE
    title_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.append([title_cell])

    header = []
    for col in columns:
        align = "left" if col.get("fmt", "text") == "text" else "right"
        header.append(_cell(col["label"], bold=True, fill=_FILL_HEAD, align=align))
    ws.append(header)

    def _row_cells(r, *, bold=False, fill=None):
        out_cells = []
        for col in columns:
            fmt = col.get("fmt", "text")
            val = r.get(col["key"])
            if fmt == "text" or val is None:
                out_cells.append(_cell("" if val is None else _safe_cell_text(str(val)),
                                       bold=bold, fill=fill, align="left"))
            else:
                out_cells.append(_cell(_num(val), number_fmt=_TABLE_FMT[fmt],
                                       bold=bold, fill=fill, align="right"))
        return out_cells

    for r in rows:
        ws.append(_row_cells(r))
    if total_row:
        ws.append(_row_cells(total_row, bold=True, fill=_FILL_TOTAL))

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output
```

**`build_hierarchy_workbook` и `build_project_task_workbook` — только guard (обычный режим сохраняем).** В начало каждой функции, сразу после docstring/первой строки:
```python
    # build_hierarchy_workbook:
    if _count_hierarchy_rows(roots) > MAX_EXPORT_ROWS:
        raise ExportTooLargeError(_count_hierarchy_rows(roots))
    ...
    # build_project_task_workbook:
    if _count_hierarchy_rows(nodes) > MAX_EXPORT_ROWS:
        raise ExportTooLargeError(_count_hierarchy_rows(nodes))
```
> Эти два билдера остаются на обычном `openpyxl.Workbook()` ради outline-группировки строк (`row_dimensions[row].outline_level`) и `merge_cells` — write_only их ломает. Это сознательный компромисс: память экономим там, где она критична (матрица/плоские таблицы — самые широкие/длинные выгрузки за период), иерархия сохраняет UX-группировку.

**Обёртка точек вызова (HTTP 400 вместо 500).** Найти грепом все `build_*_workbook(...)` в `main/views.py` (и в `report_*`-модулях, если вызывают). Каждую обернуть:
```python
    from .report_excel import ExportTooLargeError
    try:
        output = build_matrix_workbook(...)
    except ExportTooLargeError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    # ... отдать FileResponse/HttpResponse как раньше
```

**Шаг 4. Запуск (ожидание: PASS).**
- `./.venv/bin/python manage.py test main.tests_report_excel_guard --settings=test_settings` → зелёные.
- `./.venv/bin/python manage.py test main.tests_report_excel --settings=test_settings` → зелёные (валидный xlsx).
- Standalone: `cd backends/python && api/.venv/bin/python -m unittest api.main.tests_report_excel` → зелёные.
- Регресс: `./.venv/bin/python manage.py test main.tests_reports --settings=test_settings` → 41/2-известные.

**Шаг 5. Доклад.** matrix и table переведены на write_only (линейная память), `_safe_cell_text` сохранён; иерархические билдеры оставлены в обычном режиме (обоснование: outline-группировка строк несовместима с write_only); для всех 4 — мягкий лимит `MAX_EXPORT_ROWS=50000` через `ExportTooLargeError` → HTTP 400 с понятным сообщением; точки вызова обёрнуты; `tests_report_excel` зелёные обоими способами.

---

## Задача 3.6 — Автоматическая синхронизация по расписанию [опус — архитектурное решение]

**Файлы:** Modify `backends/python/api/main/models.py` (новая модель `SyncRun`); Create `main/migrations/0013_syncrun.py`; Create `main/management/commands/sync_all_portals.py`; Create `main/sync_scheduler_service.py` (логика выбора портала + инкрементальный синк + журнал); Create `main/tests_scheduled_sync.py`. Опционально (минимально): `backends/python/api/start.sh`/`Dockerfile` — **НЕ требуется** (см. решение по механизму).

**Дыра (проверено).** Синк только по кнопке: `timesheet_sync` (views.py:1418) и `sync_project_board` (views.py:724). Планировщика нет: `start.sh` запускает только gunicorn (2 воркера × 4 потока, без cron/supervisord); `requirements.txt` НЕ содержит celery/apscheduler. Данные не обновляются, пока пользователь не нажмёт кнопку.

### Выбор механизма — ПРИНЯТО: вариант (а) management-команда + внешний cron платформы

Рассмотрены три варианта ТЗ:

**(а) Management-команда `sync_all_portals` + внешний cron Timeweb / CronJob платформы.**
- ➕ Не плодит процессов в контейнере; запуск изолирован, падение команды не роняет gunicorn.
- ➕ В проекте УЖЕ есть management-команды (`main/management/commands/purge_request_logs.py`) — паттерн родной, есть образец.
- ➕ Совместимо с тем, что миграции и так гоняются отдельным release-шагом — операционная культура «команда по расписанию» уже принята.
- ➕ Идемпотентно по своей природе (каждый запуск — отдельный процесс с чистым соединением; advisory-lock из 2.2 на боевом Postgres защитит от наложения с ручным синком).
- ➖ Требует, чтобы у платформы Timeweb была возможность cron/scheduled job, дергающего `python manage.py sync_all_portals` в том же контейнере/окружении. **См. открытый вопрос 3** (это инфраструктурное требование к заказчику).

**(б) Отдельный процесс-планировщик в контейнере (supervisord / второй процесс в start.sh).**
- ➕ Не зависит от cron платформы.
- ➖ Усложняет `start.sh`/Dockerfile (нужен supervisord или фоновый `&`-процесс + управление сигналами/перезапуском); один контейнер начинает держать два логических сервиса.
- ➖ При `--max-requests 1000` gunicorn перезапускает воркеры — фоновый процесс в том же контейнере это переживёт, но управление его жизненным циклом (graceful stop) ложится на самописный скрипт. Риск «зомби»-планировщика.
- ➖ Расход памяти контейнера растёт.

**(в) APScheduler в процессе gunicorn.**
- ➖➖ **Дисквалифицирующий минус:** gunicorn идёт в **2 воркера** (`--workers 2`, `start.sh`). APScheduler, поднятый в `wsgi`/`AppConfig.ready`, инициализируется в КАЖДОМ воркер-процессе → **2 параллельных планировщика** → дублирование запусков синка. Обходится только внешним лок-файлом/advisory-lock на сам планировщик (по сути воспроизводим то, что и так есть), плюс APScheduler — новая зависимость в `requirements.txt`. Сложнее и опаснее (а).
- ➖ Долгий синк (минуты на 103k записей) в потоке APScheduler внутри gunicorn конкурирует за пул потоков (`--threads 4`) с обработкой запросов.

**Обоснование выбора (а):** наименьшее число движущихся частей, родной для проекта паттерн (есть образец команды), не трогает Dockerfile/start.sh, идеально сочетается с advisory-lock из 2.2 (каждый запуск команды — свежее соединение/сессия PG, лок берётся честно), и обходит дисквалифицирующую проблему дублирования из (в). Полноценная очередь (Celery/Redis) — ЯВНО вне scope (спринт 4). Единственное условие — наличие планировщика задач у платформы (открытый вопрос 3); если его нет, fallback — вариант (б), описан в конце карточки как План Б.

### Обязательные требования и как они выполнены

1. **Инкрементальный синк (по дате изменения, не полный).** `TimesheetSyncService.sync_all(date_from, date_to)` при переданных датах идёт **scoped-путём** (`_sync_scoped` — фильтр по полю даты-отражения + createdTime за окно). Команда передаёт **окно последних N дней** (по умолчанию 7), что и есть инкремент. Для проектов — `ProjectSyncService.sync(incremental_since_minutes=...)` уже поддерживает инкремент (views.py:726-734), команда передаёт `incremental_since_minutes`.
2. **Журнал запусков.** Новая модель `SyncRun` (started_at, finished_at, scope, status, portals_total, portals_synced, items_synced, error_summary). Команда пишет одну запись на запуск.
3. **Совместимость с advisory-lock из 2.2.** Команда оборачивает синк каждого аккаунта в `account_sync_lock(account, scope)`; при `SyncLockBusy` (на Postgres — если ручной синк уже идёт) — пропускает этот аккаунт с пометкой `skipped_locked`, не падает. На sqlite (тесты) лок — no-op.
4. **Отключаемость на портал (флаг).** Флаг хранится в конфигурации портала (`app.option`, через `ConfigurationService`) — ключ `auto_sync_enabled` (по умолчанию `True`/включено, либо `False` — см. открытый вопрос 4). Команда читает конфиг портала и пропускает порталы с `auto_sync_enabled == False`. **Не требует миграции** (конфиг уже в app.option).
5. **Идемпотентность.** Синк уже идемпотентен (upsert по `(bitrix24_account, bitrix_id)`, `_save_batch` — `bulk_create` + `bulk_update` по `UPSERT_FIELDS`); повторный запуск не плодит дублей (покрыто `tests_sync_integration` из 2.6). Команда не добавляет недетерминизма.

### Скоупинг по порталам (важная деталь)

Данные привязаны к `Bitrix24Account` (per-user), а конфиг (`app.option`) — общий на портал (на `member_id`). На проде 131 аккаунт на ~небольшое число порталов. **Запускать синк по КАЖДОМУ из 131 аккаунта — расточительно и дублирует работу** (несколько аккаунтов одного портала тянут одни и те же данные в свои таблицы — это и есть проблема 3.7). Но менять скоупинг данных в 3.6 НЕЛЬЗЯ (это задача 3.7). Компромисс для 3.6:
- Команда группирует активные аккаунты по `member_id` и для каждого портала берёт **один представительный аккаунт** — предпочтительно `is_master_account=True`, иначе первый активный (`status="active"`) с валидным токеном. Синкает только его. Это резко сокращает работу (с 131 до числа порталов) и НЕ меняет схему (просто выбираем, кого синкать).
- **Обоснование:** до перестройки 3.7 данные всё равно дублируются на каждого пользователя; автосинк одного представителя на портал держит «общие» данные свежими для отчётов этого представителя. Полное выравнивание всех аккаунтов портала — задача 3.7. Фиксируем как осознанное ограничение 3.6 (см. открытый вопрос 5).

**Шаг 1. Падающий тест** — Create `main/tests_scheduled_sync.py` (Django-`TestCase`, sqlite, мок Bitrix; БЕЗ `sys.modules`/`django.setup()`):
```python
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.utils import timezone

from .models import Bitrix24Account, SyncRun
from .sync_scheduler_service import run_scheduled_sync, select_portal_accounts


def _account(member_id, master=True, b24_user_id=1, status="active"):
    return Bitrix24Account.objects.create(
        b24_user_id=b24_user_id, is_b24_user_admin=True, member_id=member_id,
        is_master_account=master, domain_url=f"{member_id}.bitrix24.ru",
        status=status, application_version=1,
    )


class SelectPortalAccountsTest(TestCase):
    def test_one_representative_per_member_prefers_master(self):
        m1_master = _account("m1", master=True, b24_user_id=1)
        _account("m1", master=False, b24_user_id=2)   # тот же портал, не мастер
        m2 = _account("m2", master=True, b24_user_id=3)
        reps = select_portal_accounts()
        rep_ids = {a.pk for a in reps}
        self.assertIn(m1_master.pk, rep_ids)
        self.assertIn(m2.pk, rep_ids)
        self.assertEqual(len(reps), 2)  # по одному на member_id

    def test_skips_inactive_accounts(self):
        _account("m3", master=True, status="inactive")
        reps = select_portal_accounts()
        self.assertEqual(len(reps), 0)


class RunScheduledSyncTest(TestCase):
    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_writes_syncrun_journal_and_calls_sync(self, mock_cfg_cls, mock_svc_cls):
        _account("m1", master=True)
        # конфиг портала: автосинк включён, маппинг есть
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {
            "sp_entity_type_id": 1, "fields_mapping": {"data": "createdTime"},
            "auto_sync_enabled": True,
        }
        mock_cfg_cls.return_value = mock_cfg
        mock_svc = MagicMock()
        mock_svc.sync_all.return_value = 42
        mock_svc_cls.return_value = mock_svc

        run = run_scheduled_sync(days=7)

        self.assertIsInstance(run, SyncRun)
        self.assertEqual(run.status, "success")
        self.assertEqual(run.portals_total, 1)
        self.assertEqual(run.portals_synced, 1)
        self.assertEqual(run.items_synced, 42)
        self.assertIsNotNone(run.finished_at)
        # sync_all вызван с окном дат (инкремент), не пустой
        args, kwargs = mock_svc.sync_all.call_args
        self.assertTrue(kwargs.get("date_from"))
        self.assertTrue(kwargs.get("date_to"))

    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_disabled_portal_is_skipped(self, mock_cfg_cls, mock_svc_cls):
        _account("m1", master=True)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {
            "sp_entity_type_id": 1, "fields_mapping": {"data": "createdTime"},
            "auto_sync_enabled": False,   # автосинк выключен на портале
        }
        mock_cfg_cls.return_value = mock_cfg
        mock_svc_cls.return_value = MagicMock()

        run = run_scheduled_sync(days=7)
        self.assertEqual(run.portals_total, 1)
        self.assertEqual(run.portals_synced, 0)   # пропущен по флагу
        mock_svc_cls.return_value.sync_all.assert_not_called()

    @patch("main.sync_scheduler_service.TimesheetSyncService")
    @patch("main.sync_scheduler_service.ConfigurationService")
    def test_one_portal_failure_does_not_abort_run(self, mock_cfg_cls, mock_svc_cls):
        _account("m1", master=True, b24_user_id=1)
        _account("m2", master=True, b24_user_id=3)
        mock_cfg = MagicMock()
        mock_cfg.get_configuration_sync.return_value = {
            "sp_entity_type_id": 1, "fields_mapping": {"data": "createdTime"},
            "auto_sync_enabled": True,
        }
        mock_cfg_cls.return_value = mock_cfg
        mock_svc = MagicMock()
        mock_svc.sync_all.side_effect = [RuntimeError("boom"), 10]  # m1 падает, m2 ок
        mock_svc_cls.return_value = mock_svc

        run = run_scheduled_sync(days=7)
        # запуск не упал; один портал успешен, статус partial
        self.assertEqual(run.portals_total, 2)
        self.assertEqual(run.portals_synced, 1)
        self.assertEqual(run.status, "partial")
        self.assertIn("boom", run.error_summary or "")
```

**Шаг 2. Запуск (ожидание: FAIL).** `cd backends/python/api && ./.venv/bin/python manage.py test main.tests_scheduled_sync --settings=test_settings` — упадёт (`SyncRun`/`sync_scheduler_service` ещё нет).

**Шаг 3. Реализация (ПОЛНЫЙ код).**

**Модель `SyncRun`** — добавить в `main/models.py` (после `SystemLog`):
```python
class SyncRun(models.Model):
    """Журнал запусков фоновой синхронизации по расписанию (задача 3.6)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    scope = models.CharField(max_length=20, default="timesheet")  # timesheet | project | all
    status = models.CharField(max_length=20, default="running")   # running|success|partial|error
    portals_total = models.IntegerField(default=0)
    portals_synced = models.IntegerField(default=0)
    items_synced = models.IntegerField(default=0)
    window_days = models.IntegerField(default=7)
    error_summary = models.TextField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "sync_run"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["started_at"], name="sync_run_started_idx"),
        ]
```

**Миграция** — Create `main/migrations/0013_syncrun.py` (сгенерировать `./.venv/bin/python manage.py makemigrations main --name syncrun`, затем СВЕРИТЬ, что зависит от `0012_requestlog_bitrix24_account_and_more` и создаёт `sync_run`). Не редактировать руками без надобности; имя файла должно быть `0013_syncrun.py`.

**Сервис** — Create `main/sync_scheduler_service.py`:
```python
"""Фоновая синхронизация по расписанию (задача 3.6).

Запускается management-командой sync_all_portals из внешнего планировщика
платформы (cron Timeweb). Для каждого портала (group by member_id) берёт
один представительный аккаунт (мастер, иначе первый активный), читает его
конфиг (app.option), и если автосинк включён — делает инкрементальный синк
трудозатрат за окно последних N дней. Падение одного портала не прерывает
остальные. Совместимо с advisory-lock из 2.2 (на Postgres лок берётся честно,
на sqlite no-op).
"""

import logging
from datetime import timedelta
from typing import List

from django.utils import timezone

from .models import Bitrix24Account, SyncRun
from .configuration_service import ConfigurationService
from .timesheet_sync_service import TimesheetSyncService
from .utils.decorators.sync_lock import account_sync_lock, SyncLockBusy

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_DAYS = 7


def select_portal_accounts() -> List[Bitrix24Account]:
    """Один представитель на портал (member_id): мастер, иначе первый активный."""
    active = Bitrix24Account.objects.filter(status="active").order_by("member_id", "-is_master_account")
    seen = set()
    reps: List[Bitrix24Account] = []
    for acc in active:
        if not acc.member_id or acc.member_id in seen:
            continue
        seen.add(acc.member_id)
        reps.append(acc)
    return reps


def run_scheduled_sync(days: int = DEFAULT_WINDOW_DAYS, scope: str = "timesheet") -> SyncRun:
    run = SyncRun.objects.create(scope=scope, status="running", window_days=days)

    now = timezone.now()
    date_to = now.date().isoformat()
    date_from = (now - timedelta(days=days)).date().isoformat()

    reps = select_portal_accounts()
    run.portals_total = len(reps)

    synced = 0
    items_total = 0
    errors: List[str] = []

    for account in reps:
        try:
            cfg_service = ConfigurationService(account.client, account)
            config = cfg_service.get_configuration_sync()

            if not config.get("auto_sync_enabled", True):
                logger.info("Auto-sync disabled for portal %s (account %s); skip.",
                            account.member_id, account.pk)
                continue
            if not config.get("sp_entity_type_id"):
                logger.info("Portal %s not configured (no sp_entity_type_id); skip.",
                            account.member_id)
                continue

            try:
                with account_sync_lock(account, scope="timesheet"):
                    service = TimesheetSyncService(account.client, account, config)
                    count = service.sync_all(date_from=date_from, date_to=date_to)
            except SyncLockBusy:
                logger.info("Portal %s sync skipped: lock busy (manual sync running).",
                            account.member_id)
                continue

            synced += 1
            items_total += int(count or 0)
            logger.info("Scheduled sync portal %s: %s items.", account.member_id, count)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Scheduled sync failed for portal %s (account %s)",
                             account.member_id, account.pk)
            errors.append(f"{account.member_id}: {type(exc).__name__}: {exc}")

    run.portals_synced = synced
    run.items_synced = items_total
    run.finished_at = timezone.now()
    if errors and synced > 0:
        run.status = "partial"
    elif errors and synced == 0:
        run.status = "error"
    else:
        run.status = "success"
    run.error_summary = "\n".join(errors)[:4000] if errors else None
    run.save()
    return run
```

**Команда** — Create `main/management/commands/sync_all_portals.py` (по образцу `purge_request_logs.py`):
```python
"""Management command: sync_all_portals

Фоновая инкрементальная синхронизация трудозатрат по всем настроенным
порталам. Запускается внешним планировщиком платформы (cron Timeweb).

Usage:
    python manage.py sync_all_portals
    python manage.py sync_all_portals --days 3
"""
from django.core.management.base import BaseCommand

from main.sync_scheduler_service import run_scheduled_sync, DEFAULT_WINDOW_DAYS


class Command(BaseCommand):
    help = "Инкрементальный фоновый синк трудозатрат по всем настроенным порталам."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=DEFAULT_WINDOW_DAYS,
            help=f"Окно инкремента в днях (по умолчанию {DEFAULT_WINDOW_DAYS}).",
        )

    def handle(self, *args, **options):
        days = options["days"]
        run = run_scheduled_sync(days=days)
        self.stdout.write(
            f"Scheduled sync done: status={run.status}, "
            f"portals {run.portals_synced}/{run.portals_total}, "
            f"items={run.items_synced}, window={run.window_days}d."
        )
```

**Изменения Dockerfile/start.sh — НЕ требуются** для варианта (а): команда вызывается внешним планировщиком как `python manage.py sync_all_portals --days 7`. **Инструкция для заказчика** (в раздел ручной проверки): в панели Timeweb (или cron окружения) добавить задание, например ежечасно: `cd /app && python manage.py sync_all_portals --days 2`. Миграцию `0013_syncrun` применить release-шагом (`python manage.py migrate --noinput`), как и прочие.

> **План Б (если у платформы НЕТ планировщика — открытый вопрос 3):** вариант (б) минимально — в `start.sh` перед `exec gunicorn` запустить лёгкий фоновый цикл отдельным процессом: `(while true; do python manage.py sync_all_portals --days 2 || true; sleep 3600; done) &`. Это добавляет один фоновый процесс в контейнер; advisory-lock и `try/except` в команде уже защищают от наложений. Реализуется в одну строку, но это изменение `start.sh` — выполнять ТОЛЬКО по подтверждению заказчика (см. открытый вопрос 3).

**Шаг 4. Запуск (ожидание: PASS).** `./.venv/bin/python manage.py test main.tests_scheduled_sync --settings=test_settings` → зелёные. Регресс: `./.venv/bin/python manage.py test main.tests_reports --settings=test_settings` → 41/2-известные. Проверить, что миграция применяется на тестовой sqlite (тест-раннер сам мигрирует).

**Шаг 5. Доклад.** Выбран вариант (а): команда `sync_all_portals` + внешний cron (обоснование — 2 воркера gunicorn дисквалифицируют APScheduler; команда — родной паттерн, не трогает Dockerfile/start.sh, идеально сочетается с advisory-lock 2.2). Инкремент — окно последних N дней через scoped-путь `sync_all(date_from,date_to)`. Журнал — модель `SyncRun` (миграция 0013). Флаг отключения — `auto_sync_enabled` в app.option (без миграции). Скоупинг — один представитель на `member_id` (обосновано, полное выравнивание — в 3.7). Падение портала не прерывает запуск (status partial/error). План Б (фоновый процесс в start.sh) описан на случай отсутствия cron у платформы — только по подтверждению заказчика.

---

## Задача 3.7 — Проект перестройки мультитенантности (ТОЛЬКО ПРОЕКТИРОВАНИЕ) [опус, кода нет]

> Этот раздел — **проектный документ**, а не код. В спринте 3 НЕ выполняется ни одной правки кода/схемы по этой задаче. Решение о выполнении (отдельный спринт 4) — за заказчиком.

### Проблема (проверено чтением `models.py`)

`Bitrix24Account` ключуется `unique_together = ("b24_user_id", "domain_url")` — **одна строка на КАЖДОГО пользователя портала**. `member_id` (идентификатор компании/портала) хранится (стр. 23), но НЕ является tenant-ключом и НЕ уникален. `TimesheetItem` и `ProjectCard` привязаны FK к `bitrix24_account` (per-user) с `unique_together` по `(bitrix24_account, bitrix_id)` / `(bitrix24_account, project_id)`. Следствие: при установке приложения несколькими сотрудниками одной компании каждый получает СВОЮ копию данных — на проде **131 аккаунт против 229 проектов** (число аккаунтов сопоставимо/превышает число реальных сущностей — данные раздуты и дублируются). Два руководителя одной компании могут видеть РАЗНЫЕ отчёты (их копии синкаются в разное время/с разной полнотой).

### Целевая схема: «одна компания (member_id) — одно хранилище»

- **Tenant-ключ — `member_id`** (идентификатор портала Битрикс24, стабильный для компании). Ввести модель `Portal` (или `Tenant`) с `member_id` как `unique`, хранящую общие данные портала: домен, статус установки, конфиг-кэш. `Bitrix24Account` остаётся как «учётка пользователя» (для OAuth-токенов конкретного пользователя — токены per-user), но получает FK `portal = ForeignKey(Portal, ...)` по `member_id`.
- **`TimesheetItem`/`ProjectCard` перепривязываются к `Portal`**, а не к `Bitrix24Account`. `unique_together` → `(portal, bitrix_id)` / `(portal, project_id)`. Тогда данные хранятся ОДИН раз на компанию.
- **Запросы отчётов скоупятся по `portal` (member_id), а не по `account`.** Точки скоупинга — везде, где сейчас `filter(bitrix24_account=...)` (в `report_queries.py`, `timesheet_sync_service.py`, `project_*`, `views.py`). Их перевести на `filter(portal=...)`, где `portal` определяется по `request.bitrix24_account.member_id`.
- **OAuth/токены остаются per-user** (каждый пользователь авторизуется своим токеном; для синка берётся любой валидный токен портала — как уже делает 3.6 «представитель портала»).

### Стратегия переезда БЕЗ простоя (zero-downtime, поэтапно)

Принцип — **expand/contract** (расширение схемы → двойная запись → backfill → переключение чтения → сжатие):

**Этап 0. Подготовка (обратносовместимо).**
- Миграция: создать модель `Portal` (`member_id unique`), для каждого существующего `member_id` создать ровно один `Portal` (data-migration, дедупликация по `member_id`). Добавить НУЛЛЕВЫЙ FK `portal` к `Bitrix24Account`, `TimesheetItem`, `ProjectCard` (nullable — пока не заполнен). Никаких удалений. Прод продолжает работать на `bitrix24_account`-скоупинге.

**Этап 1. Backfill `member_id`/`portal`.**
- Data-migration/команда: проставить `portal` всем `Bitrix24Account` по их `member_id`; затем `TimesheetItem.portal`/`ProjectCard.portal` = `portal` их `bitrix24_account`. Идемпотентно, батчами (по образцу `_save_batch`). Прогон в фоне, без простоя.

**Этап 2. Дедупликация данных портала.**
- В пределах каждого `Portal` среди `TimesheetItem` с одинаковым `bitrix_id` (но разными `bitrix24_account`) оставить ОДНУ запись (например от мастер-аккаунта), остальные пометить к удалению. Аналогично `ProjectCard` по `(portal, project_id)`/`(portal, project_item_id)`. **Осторожно:** перед включением `unique_together (portal, bitrix_id)` дубли должны быть устранены, иначе миграция уникального индекса упадёт. Дедуп — отдельная выверенная команда с отчётом (сколько схлопнуто), прогон на копии прода сперва.

**Этап 3. Двойное чтение → переключение.**
- Ввести флаг/настройку `USE_PORTAL_SCOPING`. Сначала запросы читают по `portal`, но с фолбэком на `account` если `portal` пуст (переходный период). Затем, когда backfill+дедуп завершены и проверены — переключить чтение полностью на `portal`.

**Этап 4. Включение ограничений и сжатие (contract).**
- Сделать `portal` NOT NULL; заменить `unique_together` на portal-версии; снять старые `(bitrix24_account, ...)` уникальные ограничения и, при желании, сам FK `bitrix24_account` на данных (или оставить как аудит-поле «кто принёс запись»). Удалить дедуп-«осиротевшие» строки.

### План отката

- Каждый этап — отдельная миграция; откат = обратная миграция + флаг `USE_PORTAL_SCOPING=False` (мгновенно возвращает чтение на `account`-скоупинг, пока `bitrix24_account`-данные ещё на месте — до Этапа 4 они НЕ удаляются). Критическая точка невозврата — Этап 4 (удаление дублей/снятие старых ограничений); до него откат дёшев. Поэтому Этапы 0-3 катятся и проверяются на проде, Этап 4 — только после длительного наблюдения.

### Риски

- **Дедупликация выберет «не ту» копию** (разная полнота у копий разных пользователей) → перед дедупом синкнуть всех представителей до полноты, выбирать копию мастер-аккаунта или с максимумом записей.
- **Уникальный индекс `(portal, bitrix_id)` упадёт на остаточных дублях** → дедуп ОБЯЗАН пройти и быть проверен до Этапа 4.
- **Расхождение токенов:** синк портала идёт под токеном представителя; если у него отозван доступ — нужен фолбэк на другого пользователя портала (3.6 «представитель» уже закладывает выбор; усилить выбором валидного токена).
- **Объём миграции данных** (103k+ записей × дубли) → батчевый backfill, прогон в окно низкой нагрузки, мониторинг блокировок Postgres.
- **Отчёты «поедут» при переключении** если где-то остался `account`-скоупинг → исчерпывающий греп `bitrix24_account=` и перевод ВСЕХ точек; флаг двойного чтения снижает риск.

### Оценка отдельного спринта 4

- Объём: новая модель `Portal` + FK на 3 модели + 3-4 data-migration + 2 команды (backfill, dedup) + перевод всех точек скоупинга (~десятки `filter(bitrix24_account=...)`) + флаг двойного чтения + тесты на sqlite (включая тест дедупа и тест эквивалентности отчётов до/после) + прогон на копии прода. **Оценка: ~250-350 тыс. токенов, отдельный спринт 4**, с обязательным прогоном на копии боевой БД перед Этапом 4. Решение о старте — за заказчиком (см. открытый вопрос 6).

---

## Задача 3.8 — Ревизия [соннет]

**Файлы:** без правок (только чтение + прогон).

**ТЗ ревизии:**
1. **Перепроверить 3.1-3.6 по коду** (чтением, не на память):
   - 3.1а: `pages/task.vue` — нет лаймовых `#c7f04f`/`#84cc16`/`rgba(190,242,100,*)`; оба модала на `B24Modal`; кнопки на `B24Button`; поля на B24Select/B24Switch/B24InputNumber/UiDatePickerInput; `useIframeResizeOnToggle` сохранён; вызовы `crm.item.update`/`callBatch` не изменены.
   - 3.1б: `TaskGroupComponent.vue`/`TaskItemRow.vue` — лайм убран; «Отразить» = B24Button success; edit/delete достижимы с клавиатуры (`focus-visible:opacity-100`); emits целы; `TaskNode.isExpanded` по-прежнему `ref(true)`.
   - 3.2: `useReportFilters.ts` — период в localStorage (`ms-report-period-v1`), выборки в sessionStorage по `reportKey`, SSR-guard `typeof window`; БЕЗ VueUse; `npm run lint` 0 ошибок; 6 страниц деструктурируют `syncWarning` и рендерят `ms-panel-warning` + `allowSyncFallback: true`.
   - 3.3: `raw-data.client.vue` — самописный `.status-bar` (шаблон+CSS+`statusMessage`/`isAnyLoading`) удалён; все 4 операции (sync/export/fields/loading) через `progress.begin/end`; `ProgressOverlay.vue` не менялся (или менялся минимально и обоснованно).
   - 3.4: `RecursiveTableRow.vue` — `isOpen = ref(props.level === 0)`; `<tr>` с `tabindex`/`@keydown.enter.space`/`aria-expanded`; `DateRangeFilter.vue` — `UiDatePickerInput` вместо `<input type=date>`, `flex-wrap`, внешний API (`update:dateFrom/dateTo`) сохранён.
   - 3.5: `report_excel.py` — `build_matrix_workbook`/`build_table_workbook` на `write_only` (`WriteOnlyCell`); `build_hierarchy_workbook`/`build_project_task_workbook` в обычном режиме с guard; `MAX_EXPORT_ROWS`/`ExportTooLargeError` есть; `_safe_cell_text` НЕ ослаблен; точки вызова в views обёрнуты в `except ExportTooLargeError -> 400`.
   - 3.6: `SyncRun` в models + миграция `0013`; `sync_scheduler_service.run_scheduled_sync`/`select_portal_accounts`; команда `sync_all_portals`; флаг `auto_sync_enabled`; `account_sync_lock` обёрнут вокруг синка аккаунта; Dockerfile/start.sh НЕ изменены (или изменены только по Плану Б с подтверждением).
2. **Полный прогон тестов:**
   - Django-семейство пофайльно через `manage.py test --settings=test_settings`: `tests_reports` (база 41/2-известные), `tests_report_excel`, `tests_report_excel_guard` (new 3.5), `tests_scheduled_sync` (new 3.6), `tests_inn_backfill`, `tests_security_logs`, `tests_security_excel_cors`, `tests_security_ratelimit`, `tests_security_roles`, и наследие спринта 2 (`tests_sync_threshold`, `tests_sync_lock`, `tests_user_cache`, `tests_report_perf`, `tests_sync_honest_errors`).
   - Автономные через unittest (`cd backends/python && api/.venv/bin/python -m unittest api.main.<модуль>`): `tests_fetch_paginated_batch`, `tests_project_fetch_keyset`, `tests_sync_scoped`, `tests_inn_apply_batch`, `tests_sync_integration`, **`tests_report_excel`** (ОБА способа — задача 3.5 его затронула).
   - Перед прогоном — `grep -L "sys.modules" main/tests_*.py`, убедиться, что новые модули 3.5/3.6 НЕ содержат `sys.modules` и НЕ делают `django.setup()` на верхнем уровне (иначе их нельзя в `manage.py test`).
3. **Фронт-проверки:** `npm run lint` (или `pnpm`) → 0 ошибок (покрывает `app/utils`+`app/composables`, то есть правку 3.2 в `useReportFilters.ts`). Напомнить: страницы/компоненты (3.1/3.3/3.4) линтом НЕ покрыты — для них ручной чек-лист обязателен.
4. **Grep-проверки:**
   - В `pages/task.vue`, `TaskGroupComponent.vue`, `TaskItemRow.vue` нет подстрок `c7f04f`, `84cc16`, `bef264`, `ecfccb`-hover (лаймовые отголоски). (ЗАМЕЧАНИЕ: `_FILL_PROJECT="ECFCCB"` в `report_excel.py` — это заливка Excel, НЕ трогать; грепать только фронт-файлы task.)
   - В `report_excel.py` есть `write_only=True` (в matrix/table), `ExportTooLargeError`, `MAX_EXPORT_ROWS`; `_safe_cell_text` по-прежнему вызывается в matrix/table.
   - `account_sync_lock` присутствует в `sync_scheduler_service.py`.
   - `useReportFilters.ts` содержит `localStorage` и `sessionStorage`, НЕ содержит `@vueuse`.
   - `syncWarning` и `ms-panel-warning` присутствуют во всех 6 файлах reports (employee, project, project-task, focus-analysis, revenue-leakage, time-discipline) + daily.

**Отчёт ревизии:** по каждой задаче 3.1-3.6 — закрыто/не закрыто, с указанием прогонов и их результатов; явно отметить, что 3.7 — только документ (кода нет, проверять нечего, кроме наличия раздела).

---

## Самопроверка плана

- **Покрыты ли все 8 задач?** Да: 3.1а (task.vue→B24), 3.1б (компоненты строк→B24), 3.2 (персистентность фильтров + панель syncWarning на 6 страниц), 3.3 (один индикатор), 3.4 (таблицы+календарь), 3.5 (Excel write_only+лимит), 3.6 (автосинк по расписанию), 3.7 (проектный документ мультитенантности), 3.8 (ревизия). Каждая исполняемая задача — с файлами Create/Modify, проверкой/падающим тестом (полный код там, где есть раннер), командами запуска с ожиданием, полным кодом реализации, докладом. Без `git commit` (за оркестратором).
- **Нет ли «TBD» / «добавить обработку»?** Нет: весь приводимый код — целиком; пороги/ключи/константы (`MAX_EXPORT_ROWS=50000`, `DEFAULT_WINDOW_DAYS=7`, ключи storage, имя миграции `0013_syncrun`) — конкретными значениями. Места, требующие подтверждения формы данных (`usersMap`, точная строка вставки панели), помечены явными примечаниями «перепроверить чтением» — это не TBD реализации, а защита от расхождения с фактической формой.
- **Совпадают ли имена функций/сигнатуры между задачами?** Проверено сквозное согласование:
  - `useReportFilters(reportKey = 'default')` (3.2) — необязательный аргумент, обратносовместимо со всеми текущими вызовами `useReportFilters()`; страницы проставляют `reportKey`.
  - `useReportGenerator` НЕ меняется (3.2 лишь деструктурирует уже существующий `syncWarning` — он был добавлен в возврат в спринте 2; проверено: daily.client.vue:63 его уже достаёт).
  - `UiDatePickerInput` (`components/ui/DatePickerInput.vue`) — общий компонент для 3.1а (модал) и 3.4 (DateRangeFilter); его API (`v-model`/`placeholder`) подтверждён чтением, не меняется.
  - `ExportTooLargeError`, `MAX_EXPORT_ROWS` — определены в `report_excel.py` (3.5), импортируются в `tests_report_excel_guard` (3.5) и в точках вызова views (3.5).
  - `SyncRun`, `run_scheduled_sync(days, scope)`, `select_portal_accounts()`, `DEFAULT_WINDOW_DAYS` — определены в models/`sync_scheduler_service.py` (3.6), импортируются в команде и тесте (3.6).
  - `account_sync_lock`/`SyncLockBusy` — из 2.2 (`utils/decorators/sync_lock.py`), переиспользуются в 3.6 без изменений (проверено чтением файла — сигнатура `account_sync_lock(account, scope)`).
  - `build_matrix_workbook`/`build_table_workbook`/`build_hierarchy_workbook`/`build_project_task_workbook` — сигнатуры (имена/порядок аргументов) НЕ меняются (3.5 правит только тела + добавляет guard), что сохраняет вызовы в views/`report_*`.
- **Совпадение фикстур:** все Django-тесты создают `Bitrix24Account.objects.create(...)` с обязательными полями (`b24_user_id`, `is_b24_user_admin`, `member_id`, `is_master_account`, `domain_url`, `status`, `application_version`) — как в существующих тестах спринта 2 и `tests_reports`.
- **Совпадение волн с непересечением:** доказано в таблице волн; критические общие файлы (`DateRangeFilter.vue` между 3.2 и 3.4; `raw-data.client.vue` между 3.3 и 3.4) разведены: 3.2 не трогает `DateRangeFilter` сам (только страницы, что его рендерят), 3.4 правит сам компонент в волне 2 (после 3.2) с сохранением внешнего API; 3.3 и 3.4 в волне 2 пишут разные файлы.

## Ручная проверка для заказчика (простыми словами)

1. **Экран ввода времени стал «родным».** В карточке задачи кнопки, окно редактирования записи, переключатель «учитывать в аналитике» и поля выглядят как на странице настроек (без чужой салатовой подсветки). Окно редактирования теперь закрывается клавишей Esc и «держит» фокус внутри — по Tab можно дойти до всех полей и сохранить запись без мыши. Сами часы сохраняются ровно как раньше.
2. **Фильтры отчётов не сбрасываются.** Выбрали период и сотрудников в одном отчёте, перешли в другой и вернулись — выбор сохранился. Период общий для всех отчётов и переживает перезагрузку страницы; выбор сотрудников/проектов запоминается отдельно для каждого отчёта в пределах сессии.
3. **Предупреждение «данные не обновлены» теперь на всех отчётах.** Раньше жёлтая плашка про устаревшие данные была только на «Ежедневной нагрузке»; теперь она появляется на всех 7 отчётах, если синхронизация не удалась — отчёт честно показывает последние сохранённые данные.
4. **Один индикатор загрузки на «Проверке данных».** Раньше при синхронизации/выгрузке крутились ДВА разных индикатора одновременно; теперь — ровно один (общий «бобёр»), на всех четырёх операциях (синхронизация, Excel, загрузка полей, загрузка данных).
5. **Таблицы отчётов удобнее.** Первый уровень в отчётных таблицах теперь раскрыт сразу (отчёт не выглядит пустым); строки с вложенностью можно раскрывать с клавиатуры (Enter/пробел). Поля периода — единый оформленный календарь вместо браузерных полей, и на узком экране они аккуратно переносятся.
6. **Excel не «положит» сервер.** Большие выгрузки (ежедневная нагрузка, плоские таблицы) теперь пишутся экономно по памяти. Если период/выборка слишком большие — вместо падения приложение покажет понятное сообщение «слишком большой период — сузьте выборку».
7. **Данные обновляются сами по расписанию.** Появилось фоновое обновление: данные по компании добираются (только изменившееся за последние дни) без нажатия кнопки. Запуски ведутся в журнал; на каждую компанию обновление можно отключить настройкой. **Что нужно от вас:** включить в панели хостинга (Timeweb) запуск команды `python manage.py sync_all_portals` по расписанию (например раз в час) — см. открытый вопрос 3.
8. **Готов проект «одна компания — одно хранилище».** Подготовлен детальный план будущей перестройки хранения (без кода в этом спринте): сегодня данные дублируются на каждого сотрудника компании; план описывает, как перейти к одной общей копии на компанию без остановки работы, с откатом и оценкой. Решение о выполнении (отдельный спринт 4) — за вами.
9. **Ничего из работающего не сломалось.** Базовый набор автотестов (41 проверка) остаётся зелёным; 2 давно известные ошибки в финансовом модуле — не новые и связаны с отключённой функцией.

---

## Открытые вопросы — решить ДО старта волны 1

1. **`B24Textarea` для поля «Описание» (задача 3.1а).** В проекте `B24Textarea` НЕ используется нигде (0 совпадений). Нужно подтвердить наличие компонента в библиотеке `@bitrix24/b24ui-nuxt` (исполнитель проверит грепом по `node_modules`). Если есть — используем `B24Textarea`; если нет — оставляем нативный `<textarea>` со стилем B24 (border/rounded/focus-ring) внутри `B24FormField`. Рекомендация: использовать `B24Textarea`, если он экспортируется; иначе нативный — это не блокер.
2. **Лимит строк Excel `MAX_EXPORT_ROWS = 50000` (задача 3.5).** Принято 50 000 строк данных. Нужно подтверждение, что на боевом объёме легитимные выгрузки (например, ежедневная нагрузка за квартал по всем сотрудникам) укладываются в лимит. Если реальны выгрузки больше — поднять порог или сделать его настройкой портала. Рекомендация: 50k безопасно по памяти даже в обычном режиме; матрица/таблицы (write_only) выдержат и больше, но лимит — общий предохранитель.
3. **Механизм запуска автосинка 3.6 — есть ли у Timeweb планировщик задач (КРИТИЧНО, инфраструктура).** Принят вариант (а): management-команда `sync_all_portals` + внешний cron платформы. Это требует, чтобы у хостинга Timeweb была возможность запускать `python manage.py sync_all_portals` по расписанию в том же окружении/контейнере. **Если такой возможности НЕТ** — переходим на План Б (фоновый процесс в `start.sh`), что МЕНЯЕТ `start.sh` (одна строка). Нужно решение заказчика: (1) подтвердить наличие cron у Timeweb и взять на себя настройку задания, ИЛИ (2) разрешить правку `start.sh` по Плану Б. Без этого 3.6 реализуется (команда+модель+тесты), но не запускается на проде.
4. **Дефолт флага `auto_sync_enabled` (задача 3.6).** Принято: по умолчанию `True` (автосинк включён для настроенных порталов). Альтернатива — по умолчанию `False` (явное включение на каждом портале). Рекомендация: `True` для настроенных порталов (есть `sp_entity_type_id`) — иначе фича не заработает, пока вручную не включат на каждом. Подтвердить.
5. **Скоупинг автосинка «один представитель на портал» (задача 3.6).** Принято: до перестройки 3.7 команда синкает по одному представительному аккаунту на `member_id` (мастер, иначе первый активный), а не по всем 131 аккаунту. Это держит «общие» данные свежими и экономит ресурсы, но НЕ выравнивает копии всех пользователей портала (это сделает 3.7). Подтвердить, что для отчётов представителя этого достаточно на переходный период. Рекомендация: да, полное выравнивание — задача 3.7.
6. **Старт спринта 4 по проекту 3.7.** 3.7 — только проектный документ. Нужно решение заказчика: запускать ли отдельный спринт 4 (перестройка «одна компания — одно хранилище», ~250-350 тыс. токенов, с прогоном на копии прода). Рекомендация: запускать после спринта 3 — текущее дублирование (131 аккаунт) реально раздувает БД и создаёт риск расхождения отчётов между руководителями.
