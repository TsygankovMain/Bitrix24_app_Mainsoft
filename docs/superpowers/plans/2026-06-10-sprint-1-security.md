# Спринт 1 «Закрыть дыры безопасности» — план исполнения

> Исполнение: волны параллельных агентов, файлы волн не пересекаются. Фиксации (commit) делает оркестратор после проверки каждой задачи. Ветка: `sprint-1-security`.

**Цель:** закрыть 3 критических + 4 важных находки аудита 2026-06-10. После спринта: чужой портал не читает наши ключи; рядовой сотрудник не достаёт админские функции и денежные отчёты; секретов в репозитории нет; Excel и CORS безопасны; вход и тяжёлые операции ограничены по частоте.

## Как запускать тесты (обязательно к прочтению исполнителями)

- Django-тесты: `cd backends/python/api && ./.venv/bin/python manage.py test main.<модуль> --settings=test_settings`
- **Базовая линия:** `main.tests_reports` — 41 тест, 2 ИЗВЕСТНЫЕ ошибки в `FinanceOperationServiceTest` (finance отключён флагом; существовали до спринта — не чинить, новых ошибок не добавлять).
- Автономные тесты (подменяют django в sys.modules!): `cd backends/python && api/.venv/bin/python -m unittest api.main.tests_fetch_paginated_batch` — модули с `sys.modules`-заглушками **никогда не запускать через manage.py test**: tests_fetch_paginated_batch, tests_project_fetch_keyset (+проверять grep'ом `sys.modules` перед добавлением в прогон).
- Docker не запущен; Python 3.9.6, Django 4.2.29 в `backends/python/api/.venv`. Путь проекта содержит пробелы и кириллицу — экранировать.

## Волны и непересечение файлов

| Волна | Задача | Файлы |
|---|---|---|
| 1 | 1.1 Журналы | models.py (+миграция), middleware.py, views.py (только get_request_logs/get_system_logs), main/management/, main/tests_security_logs.py |
| 1 | 1.2 Секреты | .gitignore, .env.example, docs/SECRETS_ROTATION.md (кода нет) |
| 1 | 1.3 Excel/CORS/админка | main/report_excel.py, api/settings.py, api/urls.py, api/config.py (флаг), main/tests_security_excel_cors.py |
| 2 | 1.4 Роли + traceback'и | models.py (JWT/поле), utils/decorators/ (новый admin_required), views.py (декораторы на ~25 точках, install), log_errors.py, frontend/app/stores/api.ts (обработка 403), main/tests_security_roles.py |
| 3 | 1.5 Частота запросов | utils/decorators/rate_limit.py (новый), views.py (getToken/sync/export), main/tests_security_ratelimit.py |
| 4 | 1.6 Ревизия | без правок (только чтение + прогон) |

## Задача 1.1 — Журналы: скоупинг, маскирование, очистка [соннет]

Дыра: `get_request_logs` (views.py:~1769) и `get_system_logs` (views.py:~1802) отдают `objects.all()`; middleware пишет тела `/api/getToken` и `/api/install` (токены!) в БД.

Шаги:
1. Падающие тесты (main/tests_security_logs.py, Django-семейство): (а) аккаунт A не видит записи аккаунта B в обоих журналах; (б) после POST на /api/getToken и /api/install в RequestLog нет записей этих путей; (в) redact: тело с `"AUTH_ID":"x"`, `Authorization: Bearer y`, `access_token`, `refresh_token` сохраняется замаскированным.
2. models.py: добавить в RequestLog и SystemLog поле `bitrix24_account = models.ForeignKey("Bitrix24Account", null=True, blank=True, on_delete=models.SET_NULL, db_index=True)` → `./.venv/bin/python manage.py makemigrations main --settings=test_settings`.
3. middleware.py: `/api/getToken`, `/api/install` → в SKIPPED_PATH_PREFIXES; функция `_redact_secrets(text)` (regex по ключам AUTH_ID, REFRESH_ID, access_token, refresh_token, token, Authorization → `"***"`) применяется к обоим телам; в RequestLog.objects.create передавать `bitrix24_account=getattr(request, "bitrix24_account", None)` (проставляется в auth_required.py:83/102, middleware выполняется после view).
4. views.py: оба журнала фильтровать `filter(bitrix24_account=request.bitrix24_account)` — старые записи без аккаунта не видны никому. Места записи SystemLog (grep SystemLog.objects.create) — передавать аккаунт, где он доступен.
5. Management-команда `purge_request_logs` (main/management/commands/): полная очистка RequestLog + SystemLog старше 30 дней. Обоснование: накопленные тела уже содержат токены, диагностическая ценность ниже риска; команда выполняется на проде при выкатке (упомянуть в отчёте).
6. Прогон новых тестов + базовой линии.

Приёмка: тесты (а)-(в) зелёные; в коде журнальных view нет `objects.all()`; миграция применяется на sqlite.

## Задача 1.2 — Секреты из репозитория [хайку]

Шаги: (1) в .gitignore раскомментировать `#.env` → `.env`; (2) `git rm --cached .env` (файл на диске НЕ трогать, значения НЕ менять); (3) `git ls-files | grep -x ".env"` — пусто; (4) сверить .env.example — только плейсхолдеры (реальных значений нет — проверить и доложить); (5) создать docs/SECRETS_ROTATION.md — памятка для не-программиста на русском: зачем (история git хранит старые ключи), как сменить CLIENT_SECRET (Bitrix24 → раздел разработчика → карточка приложения), как сменить CLOUDPUB_TOKEN (кабинет CloudPub), куда вписать (.env на сервере, имена переменных CLIENT_SECRET/CLOUDPUB_TOKEN), как перезапустить контейнер, как проверить что всё работает. Подчеркнуть: JWT_SECRET в проде должен быть случайным, не плейсхолдером.

Приёмка: .env вне индекса git, остаётся на диске; памятка читается без словаря программиста.

## Задача 1.3 — Excel-формулы, CORS, админка [соннет]

Шаги:
1. Падающие тесты (main/tests_security_excel_cors.py): (а) build_table_workbook/build_hierarchy_workbook/build_matrix_workbook со значением имени `=2+2` и `+CMD()` → при чтении openpyxl ячейка имеет тип текст и значение с префиксом `'`; (б) CORS-regex: `https://acme.bitrix24.ru`, `https://x.bitrix24.com.br` проходят, `https://a.bitrix24.com.attacker.io`, `https://bitrix24.ru` (без поддомена) — нет; (в) при выключенном флаге маршрута админки нет (resolve('/api/admin/') → 404).
2. report_excel.py: помощник `_safe_cell_text(value)` — для str, начинающихся с `=`, `+`, `-`, `@`, `\t`, `\r` → префикс `'`. Применить в местах записи пользовательского текста: строки 68 (`name` в _write_row), 199 (title), 207 (subtitle), 282 (имя узла), 338 (имя сотрудника), 384 (str-ветка _put в build_table_workbook). Статические подписи («ИТОГО», «Название») не трогать. Числа/None не трогать.
3. settings.py: regex → `r"^https://[a-z0-9][a-z0-9-]*\.bitrix24\.(ru|by|kz|com|de|es|fr|pl|it|in|eu|ua|mx|id|vn|com\.br|com\.tr|co\.uk)$"` (CORS_ALLOWED_ORIGINS из env сохраняются как есть).
4. Админка за флагом: в config.py добавить `django_admin_enabled` (env `DJANGO_ADMIN_ENABLED`, default False — по образцу остальных env-чтений environs); api/urls.py: маршрут админки добавлять условно.
5. Прогон новых тестов + базовой линии.

Приёмка: тесты зелёные; экспорт Excel визуально не изменился для обычных имён.

## Задача 1.4 — Права администратора + утечка traceback [опус]

Дизайн: при выдаче токена (`get_token`/install) сервер вызывает Bitrix `user.admin` от имени токена аккаунта (через существующий механизм клиента, как в остальном коде) и сохраняет в `account.is_b24_user_admin`. Новый декоратор `@admin_required` (после `@auth_required`): `request.bitrix24_account.is_b24_user_admin` или 403 `{"error": "Недостаточно прав"}`. JWT не раздуваем — проверка по полю аккаунта (он уже загружен).

Классификация (исполнитель ОБЯЗАН сверить с фактическим использованием в frontend/app/stores/api.ts и pages/ и доложить расхождения ДО правок):
- **Админские:** configuration/save; smart-processes/create, create-fields, create-field; logs/requests, logs/system; inn-backfill/*; project-spa/backfill-timesheet; project-board/run-daily-check; project-board/sync, update, update-stage, archive; export-raw-data; timesheets (превью «Сырых данных» — содержит ставки).
- **Денежные отчёты → admin-only (продуктовое ограничение спринта 1, роли руководителей — отдельное решение):** report-revenue-leakage(+export), report-employee-project(+export), report-project-employee(+export), report-project-task-employee(+export) — сверить, в каких реально есть ставки/деньги; часовые без денег (daily-workload, discipline, focus) оставить всем.
- **Всем авторизованным:** install, getToken, health, enum, list, фильтры, support/*, чтение configuration, project-board чтение (board/meta/card/companies/portfolio), project-spa/validation, stages, internal-lists, smart-processes чтение, sync-timesheets (нужен формированию отчётов), projects-health (сверить — админская страница? если зовётся только из settings — админский).
- Traceback'и: auth_required.py:108, views.py:572, views.py:1944, views.py:2120 — в ответ generic `{"error": "Внутренняя ошибка сервера"}` (или контекстное русское сообщение), полный traceback — в server-лог (logging.exception). log_errors.py:17 — проверить, не уходит ли tb клиенту.
- Фронт: в stores/api.ts — при 403 показывать понятную ошибку «Недостаточно прав» (минимально, без редизайна).
- Тесты (main/tests_security_roles.py): параметризованно — не-админ получает 403 по всему админскому списку; админ — 200/нормальный ответ (Bitrix-вызовы замокать); не-админ сохраняет доступ к открытому списку; в ответах ошибок нет подстроки "Traceback"/"traceback".

Приёмка: тесты зелёные; getToken обновляет is_b24_user_admin; задокументирован итоговый список admin-only.

## Задача 1.5 — Ограничение частоты запросов [соннет]

Без новых зависимостей: декоратор `@rate_limit(scope, max_requests, window_seconds)` на django.core.cache (LocMemCache — per-process; в плане фиксируем ограничение: при 2 воркерах фактический предел ×2 — приемлемо как первый барьер, отметить в коде комментарием-ограничением).
- /api/getToken: 10/мин по IP+domain из payload; sync-timesheets, project-board/sync: 6/мин по аккаунту; все *-export и export-raw-data: 12/мин по аккаунту.
- Превышение: 429 `{"error": "Слишком много запросов, повторите через минуту"}`.
- Тесты (main/tests_security_ratelimit.py) с подменой cache на locmem: N+1-й запрос → 429, окно истекает → снова 200.

## Задача 1.6 — Ревизия [соннет]

Перепроверить 1.1–1.5 чтением кода; grep-проверки: `objects.all()` нет в журнальных view; `format_exc` не попадает в JsonResponse; `git ls-files | grep .env` пуст; прогон всех Django-модулей тестов (пофайльно, кроме автономных) + автономного семейства. Отчёт: закрыто/не закрыто по каждой находке аудита.

## Ручная проверка для заказчика (после спринта)

1. Открыть приложение обычным сотрудником: вкладка в задаче работает, часовые отчёты открываются, денежные — «Недостаточно прав».
2. Под админом: всё работает как раньше.
3. Страница «Журналы» под обычным пользователем недоступна; под админом — только записи своего портала.
4. Выгрузить Excel с задачей, названной `=2+2` — в файле текст, формула не считается.
5. В репозитории нет файла .env (а на сервере приложение работает).
6. Прочитать docs/SECRETS_ROTATION.md и выполнить смену двух ключей (10 минут).
