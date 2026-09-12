# Ревью архитектуры: фронтенд и дублирование логики между слоями

Дата: 13.09.2026. Срез: `99b2e14`. От `dev_ver2.0` он отстаёт на 2 коммита, но в них правились только docs, `.env.example` и демо-команда биллинга. Фронт в срезе и в `dev_ver2.0` одинаковый.
Метод: статический разбор, замеры через `wc`/`grep`. Сборка, тесты и `vue-tsc` не запускались.
Производительность бэкенда (синки, REST, N+1, индексы, кэш, gunicorn) в этом ревью не разбирается: у неё отдельное ревью.

Серьёзность: **В** — высокая: ошибка у пользователя или обход серверного правила. **С** — средняя: расхождения и дорогая поддержка. **Н** — низкая: гигиена.

## Главное

1. **Две записи идут мимо бэкенда.** Удаление записи списания уходит в Битрикс напрямую (`pages/embedded.vue:433`, `crm.item.delete`), поэтому запрет правок в закрытом периоде на удаление не действует. `stores/fieldConfig.ts:319` сам пишет `app.option.set timestamp_config` — это тот же ключ, который сохраняет бэкенд (`configuration_service.py:63`), и при гонке одна запись затрёт другую. То же поведение уже есть на `prod_2026`, так что это не регрессия.
2. **Токен после 60 минут.** JWT живёт 60 минут (`models.py:97`) и обновляется только в `initApp` при переходе между страницами. Обработчика 401 нет, это признано в комментарии `stores/api.ts:175`. Если вкладка задачи провисела открытой больше часа, первое же действие даёт 401. Дальше `processErrorGlobal` показывает фатальный экран: все ошибки, кроме 429, фатальны (`utils/apiErrors.ts:109`).
3. **Даты и числа форматируются по-разному.** Деньги форматируют 7 разных реализаций, часы — 6 разных правил.
   - `formatProjectHours` (`utils/projectBoard.ts:145`) округляет до целого: 7,5 ч превращается в «8 ч» в БДДС и в карточке проекта.
   - В 7 местах дата считается в UTC (`toISOString().slice(0,10)`). На вкладке задачи новая запись между 00:00 и 03:00 МСК получает вчерашнюю дату (`utils/timesheetEntry.ts:120`).
   - `reports/raw-data.client.vue:257` при любом положительном часовом поясе начинает период с последнего дня прошлого месяца.
4. **Большие страницы, копии логики и неполная типизация.**
   - Шесть страниц длиннее 800 строк, скрипт в них занимает до 945 строк.
   - Главная и доска проектов дублируют редактирование карточки проекта, причём главная теряет `response.warning`.
   - `stores/api.ts`: 1859 строк, 97 методов, 77 заголовков `Authorization` написаны вручную.
   - Типы ничего не проверяют: `vue-tsc` нет, `tsx` в тестах типы просто отбрасывает, ESLint смотрит только `utils/` и `composables/`.
5. **Бэкенд.** В `views.py` 4687 строк и 94 эндпоинта, у каждого одна и та же связка из 4 декораторов. 5 самодельных гейтов дословно повторяют `permission_required`. В 18 ответах клиенту уходит `str(exc)`. Списки обязательных ключей скопированы на фронт вручную (`views.py:360` → `utils/fieldMapping.ts:461`), и сверяет их тест только для финансов.

**Перед продом:** обязательного ничего. Все находки уже есть на `prod_2026`. Если релиз всё равно пересобирается, дешевле всего сразу закрыть П1 (токен) и П2 (UTC-даты): вместе около 1,5 ч машинной работы и 1,5 ч ручной.

---

## 1. Структура фронта

### 1.1 Размеры (топ-15, строки)

| Файл | Строк | Из них скрипт |
|---|---|---|
| utils/fieldMapping.ts | 2222 | — |
| stores/api.ts | 1859 | — |
| pages/settings/mapping.client.vue | 1646 | 945 |
| pages/settings/index.client.vue | 1209 | 511 |
| pages/pro.client.vue | 1099 | 501 |
| pages/finance/billing/new.client.vue | 1026 | 596 |
| utils/proPurchase.ts | 1021 | — |
| pages/projects/index.client.vue | 982 | 745 |
| pages/embedded.vue | 962 | 507 |
| components/common/SearchableSelect.vue | 927 | 717 |
| pages/index.client.vue | 827 | 611 |
| utils/bddsOperations.ts | 796 | — |
| utils/projectBoardView.ts | 730 | — |
| pages/settings/roles.client.vue | 695 | 320 |
| pages/settings/periods.client.vue | 689 | 315 |

Всего во фронте 85 `.vue` и 92 `.ts`, в сумме около 48 тыс. строк. Одних `utils/*.ts` 15,2 тыс. строк. Чистую логику в `utils/` вынесли хорошо, она покрыта 53 тестами. Страдают сами страницы.

### 1.2 Где страница смешивает загрузку, логику и вёрстку

| Место | Что смешано | Серьёзность |
|---|---|---|
| `pages/settings/mapping.client.vue` | 35 `ref` на три блока (учёт, проекты, финансы) по одной схеме: `isLoading*`, `isSuggesting*`, `*SpFields`, `*Mapping`, `*Suggestions`. Плюс 10 `catch` и 12 вызовов API. Три блока — это три копии одного жизненного цикла | С |
| `pages/index.client.vue` и `pages/projects/index.client.vue` | Одинаковые `mergeSelectOptions` (171 / 197), `drawerEmployeeOptions` / `drawerCompanyOptions` / `drawerLegalEntityOptions`, `loadMeta`, сохранение и архивация карточки. Дифф блока опций — 32 строки из 70. Поведение разошлось: главная (`:499`) игнорирует `response.warning`, доска (`:663`) его показывает | С |
| `pages/settings/index.client.vue:756–1209` | На одной странице настройки счёта, настройки БДДС, шаблоны документов, прогон уведомлений и пользовательские настройки. У каждого блока свои `*Saving`, `*Notice`, `*Error`, `*Dirty` | С |
| `pages/finance/billing/new.client.vue` | 24 `computed` про предупреждения, «нашу компанию» и группировку прямо в странице (152–450), хотя рядом уже есть `utils/billing*.ts` | Н |
| `pages/reports/project-report.client.vue` | Устаревший код с отступом в 4 пробела. Сам зовёт `crm.item.list` без пагинации (`:114`, видны только первые 50 записей), `sonet_group.get` и `crm.item.get`. Держит самодельную модалку (`:446`), `console.info` с ИНН (`:292`). Открывается с главной (`index.client.vue:582`) | С |
| `pages/embedded.vue` | Удаление, перенос часов в отчёт задачи через `callBatch` (`:496`), выгрузка CSV и нативный `confirm()` (`:425`) — всё в самой странице | С |

Что вынести:
- `useProjectCardEditor()` — справочники, опции, сохранение и архив из двух страниц;
- `useMappingBlock(kind)` — один жизненный цикл вместо трёх копий в mapping;
- `BillingSettingsCard` и `BddsSettingsCard` из `settings/index`;
- `downloadBlob(blob, name)` и `useReportExport` для отчётов (см. 2.6).

## 2. Дубли

### 2.1 Форматирование денег, часов и дат — С (одно место В)

**Деньги: 7 реализаций с разным выводом.**

| Функция | Вывод | Пробел |
|---|---|---|
| `utils/projectBoard.ts:127` formatProjectMoney | `toFixed(0)` без разрядов | обычный |
| `utils/projectBoard.ts:135` formatProjectCurrency | Intl, 0 знаков | NBSP от Intl |
| `utils/projectBoardView.ts:342` | «млн/тыс ₽» | Intl |
| `utils/homeDashboard.ts:570` formatMoney | `toLocaleString`, целые | — |
| `utils/billingFormat.ts:46/67` | разряды вручную в цикле, 2 знака | NBSP |
| `utils/proPurchase.ts:343/353` formatRub / formatRubKop | разряды регуляркой | NBSP |
| `utils/bddsOperations.ts:657` | Intl, 0 или 2 знака | Intl |

Константа `NBSP` объявлена трижды: `billingFormat.ts:17`, `proPurchase.ts:22`, `proPlan.ts:25`.

**Часы: 6 правил.**
- `projectBoard.ts:145` — до целого. Это ошибка: 7,5 выводится как «8 ч». 11 вызовов на `finance/bdds/index`, 7 на `bdds/[projectId]`, 3 в `ProjectBoardDrawer`.
- `projectBoardView.ts:327` — тоже до целого.
- `reportFormat.ts:5` — всегда 1 знак.
- `homeDashboard.ts:85` — округление до 0,1.
- `taskTabFormat.ts:46` — до 0,01 без разрядов.
- `billingFormat.ts:80` — 0,1, а целое остаётся целым.
- Ещё две локальные копии: `revenue-leakage.client.vue:67` (`toFixed(1)` плюс «ч» без пробела) и `periods.client.vue:351–636` (10 вызовов `toLocaleString` прямо в шаблоне).

**Даты.**
- В ISO-строку дату переводят 4 одинаковые функции: `proPurchase.ts:821` todayIso, `bddsOperations.ts:786` toIsoDate, `reportDateRange.ts:1` formatDateForInput, `projects/index.client.vue:393` toLocalDateString.
- В 7 местах дату берут в UTC:
  - `timesheetEntry.ts:120` — **В**: дата новой записи на вкладке задачи, при вызове из `embedded.vue:290`;
  - `raw-data.client.vue:257–258` — **В**, но это диагностический экран;
  - `CreateProjectDrawer.vue:102`;
  - `project-report.client.vue:35, 168`;
  - `placement-crm-deal-detail-tab.client.vue:40`;
  - `taskTabEntry.ts:95`.
- Для «ДД.ММ.ГГГГ» 8 функций. Без локали вызывают `toLocaleDateString()` в `RecursiveTableRow.vue:163`, `raw-data:426/441`, `daily:306` и `project-report:408` — формат там зависит от языка браузера.
- Подпись периода — три реализации: `reportFilterPresets.ts:316`, `taskTabFormat.ts:246`, `billingFormat.ts:121`.

**Куда свести.** Завести `utils/format.ts` с функциями `formatMoney(value, {digits, currency, short})`, `formatHours(value, {digits, unit})`, `formatPercent`, `formatDate`, `formatPeriod` и одной константой NBSP. Даты — в `utils/dates.ts` (`toLocalIsoDate`, `todayLocalIso`, `firstDayOfMonth`). Доменные модули (`billingFormat`, `bddsOperations`, `taskTabFormat`) остаются тонкими обёртками: у счёта свои требования к печатной форме.

### 2.2 Обработка ошибок API — С

**Статус из ошибки ofetch читают 5 копий одного кода:** `apiErrors.ts:39`, `billingErrors.ts:25` (плюс `readErrorPayload` и `readErrorCode`), `proPurchase.ts:1012`, `permissionMatrix.ts:629`, `appRoles.ts:468`. `bddsErrors.ts` уже переиспользует функции из `billingErrors` — это правильный путь, но общий разбор лежит в модуле счёта.

**Первопричина.** Перехватчик 403 в `stores/api.ts:200` заменяет ошибку голым `new Error(text)`, и у неё пропадают `status` и `data`. Из-за этого:
- `permissionMatrix.ts:639` и `appRoles.ts:474` узнают отказ по тарифу регуляркой `/не подключена/i` в тексте, хотя сервер присылает `code: feature_disabled`;
- там же регуляркой `/^\[[A-Z]+\]/` отсекается служебное сообщение ofetch.

Текст «Слишком много запросов…» продублирован строкой в `proPurchase.ts:1014`, хотя есть `RATE_LIMIT_NOTICE_TEXT`.

**Две политики показа ошибок.**
- 114 вызовов `processErrorGlobal`: всё, кроме 429, уходит на фатальный экран.
- Рядом свои плашки: `describeBillingError`, `describeBddsError`, `describeProApiError`, `describeMatrixSaveError`, `describeRoleAssignError`, `describeMappingSaveError` (`fieldMapping.ts:1991`).
- В `embedded.vue:405, 445` строка собирается как `'Ошибка…: ' + e.message`.

**Куда свести.**
1. Сделать в `apiErrors.ts` функцию `readApiError(e) → {status, code, message, payload}` и перенести туда три `read*` из `billingErrors`.
2. Перехватчик 403 не должен заменять ошибку: пусть дописывает поле `userMessage` к исходной.
3. `describe*` остаются по доменам, но читают только `readApiError`.
4. Регулярки по тексту заменить проверкой `code`.

### 2.3 Платные функции и права — Н/С

Слоёв много, но источник состояния один: `usePortalFeatures` и `/api/features`. Это хорошо. Лишнее:
- `useBddsFeature` (33 строки) равен `usePaidFeature('bdds', {flagEnabled: FINANCE_BDDS_ENABLED})`; `utils/bddsFeature.ts` (40 строк) — обёртка над `resolveFeatureAccess`.
- `BillingGate.vue` и `BddsGate.vue` после замены имён расходятся на 31 строку из ~100. Отличие — `billing_issue` и состояние счёта.
- У меню и у экрана разные модели доступа. Меню (`paidFeatures.resolvePaidFeatureState:123`) знает только `enabled/locked`, экран (`featureAccess.resolveFeatureAccess:305`) различает `readOnly`, `trial`, `grace`. Меню получает `access.enabled` и `badge` отдельными полями (`SectionNavigation.vue:101–107`).
- Флаг `FINANCE_FEATURE_ENABLED = false` объявлен локально в `pages/handler/placement-crm-deal-detail-tab.client.vue:25`, а не в `featureFlags.ts`.

**Куда свести.** Один `PaidFeatureGate.vue` с пропом `feature` и слотом для прав. `useBddsFeature` и `utils/bddsFeature.ts` удалить, а вызовы перевести на `usePaidFeature`.

### 2.4 Модалки и панели — С

- **4 самодельные боковые панели**, разметка скопирована, что признано в комментариях (`ProjectDetailsDrawer.vue:13`, `BillingCancelDrawer.vue:19`): `ProjectDetailsDrawer`, `CreateProjectDrawer.vue:418`, `ProjectBoardDrawer.vue:128`, `BillingCancelDrawer`.
- **2 самодельные модалки по центру:** `pro.client.vue:1077` и `project-report.client.vue:446`. У последней `min-w-[600px]`, в узком фрейме она не помещается.
- **Штатные:** `B24Modal` (`periods` ×3, `InnAssignModal`), `B24Slideover` (`HelpSidePanel`) и нативный `confirm()` (`embedded.vue:425`).
- **z-index:** 9999, 9995 и 50. Escape обрабатывает только `ProjectDetailsDrawer`.
- **CSS:** `.ms-modal-overlay` (`main.css:218`) используется всего в 2 файлах.

**Пустые состояния.** Класс `.ms-empty-state` встречается 20 раз в 10 файлах, общего компонента нет. Плашки `ms-note` встречаются 74 раза, `B24Alert` — 2 раза.

**Куда свести.** Сделать `AppDrawer.vue` (оверлей, `aside`, шапка/тело/подвал, Escape, единый z-index), `AppConfirm.vue` на `B24Modal` вместо `confirm()` и `EmptyState.vue`.

### 2.5 Фильтры периода — С

| Экран | Реализация |
|---|---|
| 7 отчётов | `ReportShell` → `ReportFilterBar` + `useReportFilters` + пресеты |
| Реестр и мастер счёта, `InnBackfillPanel` | `DateRangeFilter` |
| `finance/bdds/operations` | нативный `<input type="date">` + `firstDayOfMonth` (`:249`) |
| `reports/raw-data` | два `UiDatePickerInput` и своя логика по умолчанию (с ошибкой UTC) |
| `projects/index` (таймлайн) | свой расчёт диапазона (`:368–393`) |
| Главная | месяц через `homeDashboard.formatMonthValue` |

Нативный `type="date"` используется ещё в 9 местах форм. Это нормально, но выглядит иначе, чем `DatePickerInput`.

**Куда свести.** `DateRangeFilter` плюс `utils/dates.ts` с пресетами «этот / прошлый месяц / квартал» для всех экранов периода, кроме отчётов: у них пресеты хранятся в сохранённых фильтрах.

### 2.6 Выгрузки — Н

- 7 почти одинаковых `export*` в `stores/api.ts:490–600`.
- 11 копий цепочки «`createObjectURL` → `<a download>` → `revoke`» по страницам.
- 7 копий проверки «blob пришёл как JSON с ошибкой» (например, `reports/employee.client.vue:114`).

Свести в `apiStore.exportReport(kind, params)` и `utils/download.ts`.

### 2.7 Логика, повторённая на двух слоях

| Что | Фронт | Бэкенд | Сверка |
|---|---|---|---|
| Обязательные ключи СП проекта | `fieldMapping.ts:461` («Копия PROJECT_SPA_REQUIRED_MAPPING») | `views.py:360` | нет |
| Обязательные ключи финансов | `fieldMapping.ts:636` | `finance_operation_service.py:577` | есть: `tests/financeMapping.test.ts:49` читает `.py` |
| Поля СП «Доходы-расходы» | `FINANCE_MAPPING_ROWS` (`fieldMapping.ts:498`) | `installation_service.py` FINANCE_FIELD_DEFINITIONS | частично |
| Коды ролей и прав | `appRoles.ts:37–50` | `roles.py:78–98` | нет |
| Цена Pro по умолчанию | `proPlan.ts:18` (3000) | `pro_purchase_pricing.py:45` | нет, но сервер присылает цену |
| Проверка ИНН | `innValidation.ts` (96 строк) | `inn_validation.py` (101) | тест-зеркало без чтения `.py` |
| Шаблон строки счёта | `billingLineTemplate.ts` (384) | `billing_line_template.py` (281) | тесты с каждой стороны, общих фикстур нет |
| Автоопределение полей | `stores/fieldConfig.ts` AUTO_DETECT_MAPPING_RULES, пишет `app.option` | `fieldMapping.suggestMappingMatches` + сохранение через API | — третий механизм, **С** |

## 3. Контракт фронт ↔ бэкенд

### 3.1 Типы — С

- **Всё необязательно и шире нужного.** В `types/billing.ts` каждое поле — `?:` и `number | string | null` (`BillingDocumentPayload:184–232`). Проверки типов это не даёт, поэтому потребители нормализуют данные вручную (`toFiniteNumber` в `billingFormat`).
- **`BillingDocumentsResponse`** (`billing.ts:271`) допускает и `documents`, и `items`, хотя сервер присылает только `documents` (`views.py:4091`).
- **Поле без типа.** Поля документа сверены с `billing_service.serialize_document:1605`: у сервера есть `created_by_name`, в типе его нет.
- **`BddsProjectRecord`** (`types/bdds.ts:23`, 50 полей) собирается на сервере как `payload.update(metrics)` (`bdds_service.py:130`). Метрики приходят словарём из `project_budget_service`, статически сверить их невозможно.
- **Нетипизированный стор.** В `stores/api.ts` 58 вызовов `$api(` без дженерика и 20 методов возвращают `Record<string, unknown>` или `unknown`.
- **Типы ответов объявлены прямо в сторе** (`FinanceOperationRecord`, `api.ts:71`), а не в `types/`.

**Где поля пишутся руками в двух местах:** все строки таблицы 2.7, плюс ключи кэша. 9 раз повторяется литерал `clearCache('project-board', 'homepage-portfolio', 'filter-projects')`, ещё 4 раза — вариант с `project-board-meta`.

### 3.2 Проверка типов

- `vue-tsc` в `devDependencies` нет, скриптов `typecheck` и `tsc` нет.
- `nuxt build` типы не проверяет.
- `pnpm test` идёт через `tsx`, а он типы отбрасывает, поэтому **не проверяются даже `.ts`**.
- ESLint (`eslint.config.mjs`) смотрит только `app/utils` и `app/composables`.
- В репозитории нет CI: ветка `origin/claude/ci-frontend-tests` не влита.

**Оценка без запуска.** Можно ожидать **30–100 ошибок**, из них 60–70% — в 6–8 старых файлах. Основания:
- во всех 85 `.vue` стоит `lang="ts"`, `any` нет ни одного, а `@ts-expect-error` всего 14 (4 в `index.client.vue`, 3 в `fieldConfig.ts`, 4 в `iframe-resizer.ts`);
- `as unknown as` встречается 18 раз, `$b24!` — 6;
- `item[FIELDS.X]` на нетипизированных ответах `callMethod` — 7 раз;
- основная масса ожидается в `project-report`, `raw-data`, `reports/debug`, `settings/debug`, `install.vue`/`install.client.vue`, `slider/app-options`, `RecursiveTableRow`, `daily`.

Шаблоны `b24ui` добавят ошибки на пропсах: значения `color`, `size`.

**Как включать постепенно.**
1. Поставить `vue-tsc` и добавить скрипт `"typecheck": "nuxi typecheck"`. Первый прогон — только отчёт, число ошибок зафиксировать как базу.
2. В старые файлы из списка поставить `// @ts-nocheck` с пометкой в BACKLOG. Остальное довести до нуля.
3. В CI (или хотя бы в `make test`) падать при любой новой ошибке.
4. Снимать `@ts-nocheck` по одному файлу, начиная с `embedded.vue` и `index.client.vue`: это самые посещаемые экраны.

**Отдельно проверить.** Есть и `pages/install.vue` (242 строки, старый `BX24`), и `pages/install.client.vue` (296, `b24jssdk`). Оба дают маршрут `/install`, и какой из них реально отдаётся, из кода не видно — **С**.

## 4. Бэкенд-архитектура

### 4.1 Размеры и границы

**`views.py`: 4687 строк.**
- 137 функций, из них 94 эндпоинта; `urls.py` — 98 `path`.
- 47 импортов наверху и ещё 29 локальных импортов внутри функций — признак циклических зависимостей.
- Помимо вьюх, внутри лежит бизнес-логика:
  - `_build_project_spa_validation_payload` — 153 строки, `:452`;
  - `_save_configuration_with_project_sync` — 123 строки, `:2742`;
  - `export_raw_data` — 305 строк, `:3336`, Excel собирается прямо в `openpyxl`, хотя рядом есть `report_excel.py`;
  - `pro_request_required` — декоратор, объявлен во вьюхах (`:4416`).

Приблизительные разделы:

| Раздел | Строки | ≈ строк |
|---|---|---|
| Хелперы и валидация СП | 205–700 | 500 |
| Установка, токен, фильтры | 700–925 | 225 |
| Доска проектов | 926–1337 | 410 |
| Отчёты и выгрузки | 1338–1959, 3098–3176, 3336–3659 | 1020 |
| Периоды | 1960–2408 | 450 |
| Списания | 2409–2693 | 285 |
| Конфигурация и сопоставление | 2694–3097 | 400 |
| Логи, ИНН, здоровье | 3177–3335 | 160 |
| БДДС | 3660–3842 | 183 |
| Счёт и акт | 3843–4305 | 463 |
| Роли | 4306–4404 | 100 |
| Pro | 4405–4687 | 282 |

**`models.py`: 1120 строк, 23 модели** — учёт, портал, роли, логи, биллинг и Pro в одном файле. Размер пока терпимый, **Н**.

### 4.2 Повторяющиеся шаблоны

**Декораторы.** У 94 эндпоинтов одна и та же связка: `@xframe_options_exempt` (96), `@require_*` (94), `@log_errors("имя")` (94) и `@auth_required` (94). Кроме того, `@rate_limit` (36), `@csrf_exempt` (36), `@permission_required` (14), `@feature_required` (10). Порядок важен (комментарий `views.py:3862`), но держится вручную — **С**.

**Гейты-дубли — С.** `billing_settings._billing_gate:181` и три обёртки над ним (`billing_manager_required`, `billing_cancel_required`, `billing_money_view_required`), а также `bdds_settings.bdds_operations_manager_required:202` построчно повторяют `roles.permission_required:876`. Отличаются только `code` и `action`, а `permission_required` их и так принимает. Декоратор `utils/decorators/admin_required.py` в `views.py` больше не применяется.

**Разбор тела.**
- Две политики. `_load_request_json` (`:605`, 21 вызов) при мусоре молча возвращает `{}`. В 6 местах `json.loads(request.body)` (`:2417, 2868, 3267, 3298, 3344`) при мусоре честно отвечают 400.
- Кроме того, тело разбирает `collect_request_data` внутри `auth_required`, а `rate_limit` делает это ещё раз как запасной вариант. В сумме — до трёх разборов на запрос.

**Ответы с ошибкой.**
- Форма `{"error": …}` встречается 65 раз, `code` добавлен только в 25. Есть и `{"message": …}` (2).
- `except Exception` — 36.
- `str(exc)` уходит клиенту 18 раз, например `:856` при ошибке установки со статусом 500 и `:1020–1555`. Для доменных исключений это нормально, для неожиданных — утечка текста.

**Отчёты.** Пары «отчёт JSON / отчёт Excel» повторяют один конвейер: `materialize_rows` ×8, `_get_user_map` ×16, `build_project_title_lookups` ×10, `build_task_lookup` ×10. Отдача xlsx (`content_type` и `Content-Disposition`) повторяется 9 раз — **С**.

### 4.3 Как безопасно разрезать `views.py`

1. **Сначала сузить.** Пять гейтов заменить на `permission_required(PERM, code=…, action=…)`, `pro_request_required` перенести в `pro_purchase_service`. Ввести один `json_body(request, strict)` и `xlsx_response(output, filename)`. Поведение не меняется, существующие тесты остаются страховкой.
2. **Пакет `main/views/`.** Файл `__init__.py` реэкспортирует все имена (`from .billing import *` и так далее), тогда `urls.py` (`views.X`) не меняется. Разрезать по разделам из таблицы 4.1, по **одному разделу за PR**. Начать с изолированных: Pro, роли, БДДС, счёт — у них свои сервисы и отдельные тесты.
3. **Ловушка в тестах.** 46 вызовов `patch("main.views.<Имя>")` в 10 тестовых файлах на 8 имён: `ConfigurationService` ×15, `_build_project_spa_validation_payload` ×12, `TimesheetWriteService` ×7, `ProjectSyncService` ×6 и другие. После переноса функция ищет имя в глобалах своего модуля, и патч на `main.views.X` **молча перестаёт действовать**. В каждом PR цели патчей надо переписать на новый модуль и проверить, что тест падает, если убрать мок.
4. **Хелперы** `_build_project_spa_validation_payload` и `_save_configuration_with_project_sync` перенести в `configuration_service`, а `export_raw_data` — в `report_excel`.

## 5. Бандл

| Что | Где | Оценка | Серьёзность |
|---|---|---|---|
| `xlsx@0.18.5` | `package.json:27`, во фронте **не импортируется ни разу**: Excel собирает сервер | Мёртвая зависимость. У версии известные CVE-2023-30533 и CVE-2024-22363: в бандл не попадает, но шумит в аудите | Н |
| Material Symbols Outlined с полным диапазоном осей `opsz,wght,FILL,GRAD` | `nuxt.config.ts:103`, глобально в `<head>` | Загружается на каждой странице, включая вкладку задачи. Иконки нужны только 5 файлам: `embedded.vue`, `TaskEntryForm`, `TaskEntryRow`, `TaskTabCard`, `project-report`. Шрифт со всеми осями весит сотни КБ и больше, запрос идёт на Google Fonts из фрейма Б24. Точный вес снять в DevTools | С |
| `luxon` | Только `components/ui/DatePickerInput.vue` (4 вызова `DateTime`) | Около 20 КБ gzip ради календаря. Заменяется на `Date`/`Intl` | Н |
| Общий чанк layout | `layouts/default.vue` → `SectionNavigation` (импортирует `proPurchase.ts`, 1021 строка) и `MappingHealthBanner` → `useMappingHealth` (импортирует `fieldMapping.ts`, 2222 строки, с текстами строк сопоставления) | Около 3,2 тыс. строк логики и текстов грузятся на всех страницах ради двух маленьких функций (`shouldShowProNavButton`, `resolveMappingHealth`) | Н/С |
| Ленивая загрузка | `defineAsyncComponent`, `Lazy*` и `import()` не используются. Страницы `.client.vue` Nuxt делит сам, но тяжёлые панели (`CreateProjectDrawer`, 662 строки; `ProjectBoardDrawer`) грузятся вместе со страницей | Н |
| UI Kit в разметке | `<table>` 34 / `B24Table` 0; `<input>` 78 / `B24Input` 2; `<select>` 25 / `B24Select` 1; свой `SearchableSelect.vue` на 927 строк (9 мест) | На бандл не влияет, это стоимость поддержки. Часть решений осознанная (ограничения фрейма) | Н |

Графиков в зависимостях нет.

---

## Предложения рефакторинга

Оценки в часах. «Машинная» — агент пишет код и тесты. «Ручная» — приёмка человеком: смотреть экран во фрейме Б24, читать дифф.

| # | Что | Польза | Риск | Машинная | Ручная | Волна |
|---|---|---|---|---|---|---|
| П1 | Перед каждым запросом в `$api.onRequest` проверять токен (`ensureToken`), на 401 — один повторный запрос после `reinitToken`. Bearer ставить там же, а не в 77 местах | Нет фатального экрана после часа на одной странице | Низкий: дедупликация запроса токена уже есть (`api.ts:1343`) | 1 | 1 | Первый месяц, первым делом |
| П2 | `utils/dates.ts` (`toLocalIsoDate`, `todayLocalIso`, `firstDayOfMonth`): заменить 4 копии и 7 мест UTC | Дата новой записи ночью и начало периода в raw-data станут верными | Низкий | 0,5 | 0,5 | Первый месяц, первым делом |
| П3 | Серверная ручка удаления записи списания с проверкой закрытого периода, `embedded.vue:433` перевести на неё | Правило периода действует и на удаление | Средний: права на удаление в Б24 и авторство (см. `timesheet_write_service`) | 3 | 1,5 | Первый месяц |
| П4 | Убрать запись `app.option` из `stores/fieldConfig.ts`, автоопределение оставить только в `/settings/mapping`. `project-report.client.vue` перевести на API или удалить | Нет гонки за `timestamp_config`, остаётся один механизм подсказок полей | Средний: страница открывается с главной, нужно решить её судьбу | 4 | 2 | Первый месяц |
| П5 | `formatProjectHours` — до 0,1; `utils/format.ts` с одной константой NBSP. Сначала тесты-«слепки» на текущий вывод, затем перевод модулей по одному | Одинаковые числа на всех экранах, исправлено «7,5 → 8 ч» | Низкий для часов; средний при смене денежного вывода — нужно решение продукта | 3 | 2 | Первый месяц (часы), потом (деньги) |
| П6 | `readApiError` в `apiErrors.ts`; перехватчик 403 сохраняет `status` и `data`; убрать регулярки по тексту | Одна точка разбора, отказы по коду, а не по фразе | Средний: тесты `billingErrors`/`bddsErrors`/`appRoles` надо прогнать все | 2 | 1,5 | Первый месяц |
| П7 | Контракт-тест: бэкенд выгружает ключи `serialize_document`, `BddsService._serialize`, `PROJECT_SPA_REQUIRED_MAPPING` и коды ролей в JSON-фикстуру, TS-тест сверяет с типами и константами (по образцу `financeMapping.test.ts`). Сузить `?:` в `types/billing.ts` там, где сервер поле присылает всегда | Расхождение ловится тестом, а не в проде | Низкий | 4 | 1,5 | Первый месяц |
| П8 | `vue-tsc` + `nuxi typecheck`: отчёт, база ошибок, `@ts-nocheck` в старых файлах, запрет новых ошибок | Типы наконец проверяются | Низкий (только инструмент) | 2 (+4–8 на разбор) | 1 (+2) | Первый месяц — включение, потом — разбор |
| П9 | Бэкенд: 5 гейтов → `permission_required`; `json_body(request, strict)`; `xlsx_response`; не отдавать `str(exc)` из `except Exception` | Меньше кода в гейтах, одинаковые ответы | Низкий: у гейтов есть тесты `tests_security_roles`, `tests_roles_matrix` | 4 | 2 | Первый месяц |
| П10 | `useProjectCardEditor()` для главной и доски; на главной показывать `warning` | −150–200 строк, одно поведение | Средний: две самые посещаемые страницы | 3 | 2 | Первый месяц |
| П11 | Бандл: удалить `xlsx`; Material Symbols — сузить оси и подключить параметром `icon_names=` только нужные иконки (или перейти на `b24icons`); `luxon` заменить на `Intl` | Легче каждая страница и вкладка задачи, меньше внешних запросов | Низкий; для `icon_names` нужен визуальный осмотр вкладки | 2 | 1 | Первый месяц (xlsx, шрифт), потом (luxon) |
| П12 | `AppDrawer`, `AppConfirm`, `EmptyState`: перевести 4 панели, 2 модалки, `confirm()` и 10 пустых состояний | Единое поведение: Escape, z-index, узкий фрейм | Средний: высота фрейма и прокрутка во встройке | 4 | 3 | Потом |
| П13 | Общий фильтр периода (`DateRangeFilter` + пресеты) для `bdds/operations`, `raw-data`, таймлайна доски | Одинаковый ввод периода | Низкий | 3 | 2 | Потом |
| П14 | `PaidFeatureGate` вместо `BillingGate`/`BddsGate`; удалить `useBddsFeature` и `utils/bddsFeature.ts`; флаг сделки перенести в `featureFlags.ts` | −150 строк, одна модель доступа | Низкий | 2 | 1 | Потом |
| П15 | `stores/api.ts` разрезать по доменам (`api/reports.ts`, `board.ts`, `billing.ts`, `bdds.ts`, `periods.ts`, `config.ts`, `roles.ts`, `pro.ts`), ключи кэша — в константы; 7 `export*` → `exportReport(kind)` + `utils/download.ts` | Стор меньше 300 строк, у выгрузок одна точка | Средний: много импортов, стор используют все страницы | 5 | 2 | Потом (после П1, П6) |
| П16 | `mapping.client.vue` → `useMappingBlock(kind)`; `settings/index` → карточки счёта и БДДС | Страницы меньше 500 строк | Средний: мастер сопоставления недавно перестраивали | 5 | 3 | Потом |
| П17 | Разрез `views.py` на пакет по п. 4.3, по разделу за PR, с переписыванием 46 патчей | Файлы по 200–500 строк, понятные границы | Средний: молча отвалившиеся моки | 6 | 3 | Потом (после П9) |
| П18 | Выяснить, какой из `install.vue` / `install.client.vue` реально отдаётся, второй удалить | Нет двусмысленного маршрута установки | Низкий, но проверять на тестовом портале | 0,5 | 1 | Первый месяц |
| П19 | `models.py` → пакет `models/` (портал, учёт, роли, биллинг, Pro, логи) | Навигация по коду | Низкий: миграции не меняются, только импорты | 2 | 0,5 | Потом |

**Итого:** первый месяц — около 29 ч машинной работы и 17 ч ручной; потом — около 27 ч машинной и 14,5 ч ручной (без разбора ошибок `vue-tsc`).
