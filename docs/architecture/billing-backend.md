# Счёт и акт: устройство бэкенда

Реализация контракта `docs/superpowers/specs/2026-09-12-billing-mvp-contract.md`.
Ветка `claude/billing-mvp`. Здесь — что где лежит, какие решения приняты сверх
контракта и что осталось непроверенным.

## Модули

| Файл | За что отвечает |
|---|---|
| `main/models.py` | `PortalFeature`, `BillingDocument`, `BillingLine`, `BillingEntry` |
| `main/migrations/0022_billing.py` | таблицы и частичный уникальный индекс |
| `main/billing_service.py` | отбор списаний, суммы, группировки, транзакция записи, отмена, drift |
| `main/billing_crm_service.py` | смарт-счёт (`entityTypeId 31`), товарные строки, сверка, печать акта |
| `main/billing_features.py` | состояния платных функций и декоратор `feature_required` |
| `main/billing_settings.py` | настройки счёта из конфигурации и гейт прав `billing_manager_required` |
| `main/report_excel.py` | `build_billing_detail_workbook` — XLSX-детализация к акту |
| `main/management/commands/billing_feature.py` | включение и выключение функции порталу |

## Эндпоинты

Все под JWT, как остальные.

| Метод | Адрес | Гейты |
|---|---|---|
| GET | `/api/features` | — |
| POST | `/api/billing/preview` | права |
| POST | `/api/billing/documents` | права, подписка, лимит, замок портала |
| GET | `/api/billing/documents` | — |
| GET | `/api/billing/documents/<id>` | — |
| POST | `/api/billing/documents/<id>/cancel` | права |
| POST | `/api/billing/documents/<id>/act` | права, подписка |
| GET | `/api/billing/documents/<id>/detail.xlsx` | — |

Чтение реестра и карточки гейтов не имеет намеренно: при выключенной подписке
клиент не теряет доступ к уже выставленным документам, а отмена остаётся
разрешённой, чтобы ошибку можно было исправить.

## Три опорных решения

**1. Двойное выставление держит база.** Частичный уникальный индекс
`(bitrix24_account, timesheet_bitrix_id)` при действующем документе. Условие
индекса не может ссылаться на поле связанной модели, поэтому статус документа
продублирован на `BillingEntry.is_active`; пару «статус документа + is_active»
поддерживает только сервис (`create_document` и `cancel`).

**2. Сначала наша БД, потом CRM.** Документ и потреблённые списания пишутся
одной транзакцией ДО создания счёта: конфликт индекса обязан всплыть раньше,
чем на портале появится счёт, который приложение не сможет удалить. Если
CRM-шаг падает — `discard_failed`: документ без `crm_entity_id` удаляется, с
полученным id отменяется (след остаётся, списания освобождаются).

**3. Ответам REST верить нельзя.** После создания счёт и его товарные строки
перечитываются, сверяются и итог счёта, и сумма строк. Расхождение — отказ
выставления с кодом `crm_amount_mismatch`, а не «вроде получилось».

## Коды отказов

`bad_grouping`, `empty_selection`, `no_company`, `mixed_companies`,
`period_open` — негодный отбор (400). `already_invoiced` — 409 со списком
`document_ids`. `crm_invoice_failed`, `crm_productrows_failed`,
`crm_verify_failed`, `crm_amount_mismatch` — сбой канала CRM (502).
`act_template_missing` (400), `documentgenerator_unavailable`,
`act_generation_failed` (502) — печать акта; текст последней ошибки остаётся
в `BillingDocument.act_error`. `billing_forbidden` и `feature_disabled` — 403.

Коды предупреждений предпросмотра: `period_open`, `already_invoiced`,
`no_rate`, `mixed_companies`. У каждого есть признак `blocking`.

## Подписка и права

Состояние функции — `PortalFeature`, только на нашем сервере: `app.option`
портала пишется токеном приложения, то есть из консоли браузера. REST на
запись нет. Меняется командой:

```
python manage.py billing_feature --domain client.bitrix24.ru --state on
python manage.py billing_feature --member-id abc --state trial --trial-days 14
python manage.py billing_feature --list
```

Команда пишет строку каждой учётке портала, и чтение состояния тоже идёт по
всем учёткам одного `member_id`: учётка в этом приложении — запись на
сотрудника, и «включено администратору» не должно означать «выключено
бухгалтеру».

Выставлять и отменять может администратор портала или сотрудник из списка
`billing_accountants` в настройках приложения. Администратор проходит без
обращения к порталу — флаг уже в нашей БД.

## Настройки

Живут в общей конфигурации приложения (`app.option`, `ConfigurationService`),
параллельного механизма нет:

- `billing_allow_open_period` — разрешить выставление за незакрытый месяц;
- `billing_accountants` — список id «Бухгалтерии»;
- `billing_act_template_id` — шаблон акта генератора документов.

## Что не проверено живьём

Доступа на запись к порталу у разработки не было, поэтому по документации, а
не по эксперименту, сделано следующее:

- печать акта по смарт-счёту (`crm.documentgenerator.*`): состав полей
  `values`, наличие штатного шаблона акта, появление `pdfUrl` (собирается
  асинхронно и в первом ответе обычно пуст);
- код единицы измерения «час» (ОКЕИ 356) в товарной строке;
- кто и когда присваивает номер смарт-счёта: приложение перечитывает
  `accountNumber` после создания и не пытается задать номер само;
- поведение `taxRate`/`taxIncluded` в строке без товара из каталога.

Путь «создать свой шаблон акта» (`crm.documentgenerator.template.add`)
реализован, но вызывается только по явной передаче DOCX в base64 — обязательным
для первой версии он не сделан.
