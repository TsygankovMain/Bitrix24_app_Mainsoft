# Code Review — May 2026

Точечный обзор: только серьёзные находки. Полный аудит не проводился (см. раздел «Что НЕ проверено»).

## Сводная таблица

| # | Проблема | Файл:строка | Серьёзность | Рекомендация | Оценка |
|---|----------|-------------|-------------|--------------|--------|
| 1 | Реальный `CLOUDPUB_TOKEN` и `CLIENT_SECRET` закоммичены в `.env` | `.env:4-6` (tracked в git) | **High** | Ревокация токенов, удаление из git-истории, активировать запись `.env` в `.gitignore` | 1–2 ч |
| 2 | Multi-tenant data leak: `RequestLog` / `SystemLog` без `bitrix24_account` | `models.py:230`, `views.py:1416,1449` | **High** | Добавить FK на аккаунт + миграция; фильтровать по `request.bitrix24_account` | 1–2 ч |
| 3 | `serve_spa` без `auth_required` обслуживает любые пути POST/GET | `views.py:1684-1701` | Medium | Поведение допустимо для SPA, но `request.path` логируется в `info` без санитизации — отдельный риск шумового лога | 15 мин |
| 4 | `install` POST-ветка делегирует в `_install_post_logic` через костыль вместо чистого решения | `views.py:498-529` | Medium | Заменить на единственный декоратор `@auth_required_if_post` или ранний выход | 30 мин |
| 5 | Нет лимита на размер `employee_ids[]` / `project_ids[]` в `__in` | `report_queries.py:46-58` | Medium | Обрезать до 1000 значений + ранний возврат при превышении | 20 мин |
| 6 | Нет rate limiting нигде в проекте, включая публичные `/install` и `/getToken` | `views.py:498,562`, `settings.py` | Medium | Добавить `django-ratelimit` или nginx-уровень на публичные эндпоинты | 1–2 ч |
| 7 | Дубликат-блок из 6 строк повторён 7 раз в отчётных эндпоинтах | `views.py:805-830, 838-863, 871-897, 905-941, 949-981, 989-???, 1340-1409` | Medium | Извлечь helper `_prepare_tree_report_data(request, profiler) -> (rows, user_map, items, project_lookup)` | 1 ч |
| 8 | `console.log/info/warn/error` в проде на горячем пути embedded.vue (31 шт) и fieldConfig.ts (10+) | `embedded.vue:43,499,530,550,569,616,666,690,...`, `fieldConfig.ts:93,107,111,219,229,...` | Medium | Завернуть в `if (import.meta.dev)` или удалить; `console.error` оставить только для боевых ошибок | 30 мин |
| 9 | Stack trace отдается клиенту в JSON-ответе при ошибке install/export_raw_data | `views.py:553-554, 1573-1574` | Medium | Не возвращать `traceback.format_exc()` в `JsonResponse` — логировать сервером, клиенту отдать `error_id` | 15 мин |
| 10 | DEBUG-режим выключает CORS-allow-list | `settings.py:119-120` | Low (но риск операционной ошибки) | Убрать `CORS_ALLOW_ALL_ORIGINS = DEBUG`, всегда явный список | 10 мин |

---

## High-severity (детально)

### 1. Реальные секреты в `.env` под git

**Файл:** `.env:4-6` (файл `.env` отслеживается, см. `git ls-files | grep env`)

**Что сейчас:**
```env
CLOUDPUB_TOKEN='6qOJbiFzecmAU5cZ5Frm6QIxDFCqRY0M8iJA-fb-L0I'
CLIENT_ID='local.69e12f02077816.57530392'
CLIENT_SECRET='F1V4X9sCuil8shlhil3bgN2GIP2L8lpzHpEgrqieVMM02JBYgn'
```

`.gitignore` строка 32: `#.env` — закомментирована, файл коммитится по факту. `.env.example` рядом, но прод-значения попали именно в `.env`.

**Что должно быть:**
- В `.gitignore`: раскомментировать `.env` (или явно `/.env`).
- Удалить `.env` из индекса: `git rm --cached .env` + новый коммит.
- `CLOUDPUB_TOKEN`, `CLIENT_SECRET`, `DJANGO_SUPERUSER_PASSWORD=admin123` — ревокация и ротация в Cloudpub / Bitrix24 Marketplace / Django admin соответственно.
- В git-истории секреты остаются → если репо публичное или шарится, обязателен `git filter-repo` / BFG.

**Почему важно:** `CLOUDPUB_TOKEN` даёт контроль над туннелем (можно перенаправить `wanly-evolved-lionfish.cloudpub.ru` куда угодно — фактически MITM на прод). `CLIENT_SECRET` локального приложения позволяет обмениваться кодом → токен и читать данные портала. `admin123` — прямой доступ в Django admin. Это инцидент, не находка.

---

### 2. Логи RequestLog/SystemLog не привязаны к tenant

**Файл:** `backends/python/api/main/models.py:230-264`

**Что сейчас:**
```python
class RequestLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(auto_now_add=True)
    method = models.CharField(max_length=10)
    path = models.TextField()
    status_code = models.IntegerField(null=True)
    duration_ms = models.FloatField(null=True)
    request_body = models.TextField(null=True)
    response_body = models.TextField(null=True)
    error_message = models.TextField(null=True)
```

И в `views.py:1416-1442`:
```python
@auth_required
def get_request_logs(request: AuthorizedRequest):
    ...
    queryset = RequestLog.objects.all().order_by('-timestamp')
    ...
```

**Что должно быть:**
- В модель добавить `bitrix24_account = models.ForeignKey(Bitrix24Account, on_delete=models.CASCADE, null=True, db_index=True)`.
- Заполнять в `RequestLoggingMiddleware` после auth_required.
- В `get_request_logs` / `get_system_logs` фильтровать `RequestLog.objects.filter(bitrix24_account=request.bitrix24_account)`.

**Почему важно:** любой авторизованный пользователь портала А, открыв админский раздел приложения, видит `request_body` / `response_body` всех остальных порталов B, C… Это утечка PII (имена сотрудников, описания задач) и потенциально JWT-фрагментов из тел запросов. Multi-tenant изоляция нарушена.

---

## Medium-severity (тезисно)

- **`serve_spa` логирует path в info** (`views.py:1689`). Атакующий может насорить в логи произвольным путём — переиспользуйте `logger.debug` или ограничьте длину.
- **`install` POST workaround** (`views.py:498-529`): 20 строк комментариев-размышлений и pass-блок без логики. Нужна чистая ветка `if request.method == "POST": return _install_post_logic(request)`, без exception-обёртки на ровном месте.
- **Нет защиты от больших списков фильтра** (`report_queries.py:46-58`): `employee_ids[]=1&employee_ids[]=2&...` без cap может породить SQL-запрос с десятком тысяч `IN`-значений. Хотя это authenticated-эндпоинт, всё равно ограничьте: `employee_ids = employee_ids[:1000]`.
- **Rate limiting отсутствует**. Особенно критично для `/install` (стр. 498) и `/getToken` (стр. 562) — публичные. Минимум — `django-ratelimit` на эти два эндпоинта (10 req/min на IP).
- **Копипаст в отчётных вьюхах**. После `ReportProfiler` каркас стал ещё более очевидно дублированным:
  ```python
  # повторяется 5 раз почти дословно
  with profiler.stage("queryset_build"):
      queryset = _get_filtered_timesheet_queryset(request)
  with profiler.stage("materialize"):
      rows = materialize_rows(queryset, TREE_REPORT_FIELDS)
  user_ids = {row["employee_id"] for row in rows if row.get("employee_id")}
  with profiler.stage("user_map"):
      user_map = _get_user_map(request, user_ids)
  with profiler.stage("project_lookup"):
      project_name_by_item, project_name_by_group = build_project_title_lookups(request.bitrix24_account)
  ```
  Извлечь:
  ```python
  def _prepare_tree_report_data(request, profiler, *, fields=TREE_REPORT_FIELDS, include_task_id=False):
      with profiler.stage("queryset_build"):
          queryset = _get_filtered_timesheet_queryset(request)
      with profiler.stage("materialize"):
          rows = materialize_rows(queryset, fields)
      user_ids = {row["employee_id"] for row in rows if row.get("employee_id")}
      with profiler.stage("user_map"):
          user_map = _get_user_map(request, user_ids)
      with profiler.stage("project_lookup"):
          by_item, by_group = build_project_title_lookups(request.bitrix24_account)
      with profiler.stage("build_items"):
          items = build_tree_report_items(rows, include_task_id=include_task_id, project_name_by_item=by_item, project_name_by_group=by_group)
      return rows, user_map, items
  ```
  Применимо к `report_employee_project`, `report_project_employee`, `report_project_task_employee`. Для `revenue_leakage`, `time_entry_discipline`, `focus_analysis` структура чуть другая (свои `materialize`-поля) — отдельный helper или параметризация.

- **Debug-логи в проде, frontend.** В `embedded.vue` 31 вызов `console.*`, в т.ч. `JSON.stringify(task)` (строка 499), что роняет производительность и шумит. Минимально:
  ```ts
  if (import.meta.dev) console.log(`...`, JSON.stringify(task))
  ```
  Или общий хелпер `debug(...)` в `frontend/app/utils/`.

- **`fieldConfig.ts:93,107,111`** — `console.log('[FieldConfig] Raw app.option.get response:', JSON.stringify(data))` логирует сырые данные конфигурации в DevTools каждого пользователя. Завернуть в `import.meta.dev` или убрать.

- **Stack trace в JSON-ответе клиенту** (`views.py:553, 1574`):
  ```python
  return JsonResponse({"error": ..., "trace": traceback.format_exc()}, status=500)
  ```
  Утечка структуры путей, имён модулей, версий библиотек. Логируйте сервером, клиенту — `error_id` и общая строка.

- **`CORS_ALLOW_ALL_ORIGINS = DEBUG`** (`settings.py:119`). Если кто-то случайно поднимет прод с `DEBUG=True`, CORS откроется всему интернету. Лучше: `CORS_ALLOW_ALL_ORIGINS = False` всегда, в dev добавить локальные origins через env.

- **`X_FRAME_OPTIONS = 'ALLOWALL'`** (`settings.py:124`) — нужно для iframe Bitrix24, но добавьте `Content-Security-Policy: frame-ancestors https://*.bitrix24.ru https://*.bitrix24.com` чтобы ограничить, кто может встраивать.

- **Комментарии «BUG FIX #3/#4»** (`views.py:1560,1569`) — это нормальные комментарии про особенности `crm.item.list` (total на верхнем уровне), не временные хаки. Оставить, но переписать без нумерации в стиле «Note: Bitrix24 returns total at top level…» — нумерация без issue tracker’а бессмысленна.

- **`FIX:` комментарии** (`views.py:1528,1533`) — описывают конкретное несоответствие имён полей фронт↔конфиг. Это data-conventions, а не bug-fix; можно убрать слово `FIX:` и оставить пояснение.

---

## Быстрые победы (≤30 мин каждая)

1. Удалить `.env` из git и ротировать токены — самое срочное.
2. Завернуть `console.log` на горячих путях `embedded.vue` (≥10 шт в hierarchy-цикле, строки 499, 530, 550, 569) в `import.meta.dev`.
3. Убрать `traceback.format_exc()` из JSON-ответов в `install`, `export_raw_data`.
4. Ограничить размер `employee_ids[]`/`project_ids[]` в `report_queries.py:46-58` (`[:1000]`).
5. Добавить `bitrix24_account` в `RequestLog`/`SystemLog` (миграция + middleware-заполнение + фильтр в двух вьюхах).

## Что НЕ проверено (намеренно)

- **Полный аудит зависимостей** (`requirements.txt`, `package.json` — наличие уязвимых версий).
- **Производительные тесты** на больших объёмах данных (>100k записей TimesheetItem).
- **Accessibility / a11y** во фронтенде.
- **Корректность бизнес-логики** в отчётах (math/aggregation).
- **Безопасность Docker-конфигов** (`docker-compose.yml`, `infrastructure/`).
- **Полный обзор `embedded.vue`** (1356 строк) и `views.py` (1701 строка) — только точечные участки.
- **PHP/Node бэкенды** — мёртвый шаблон, по запросу.
- **Git-история на предмет других утёкших секретов** в прошлых коммитах.
- **Тесты** (`tests_reports.py`) — coverage не оценивался.
- **Frontend security** (XSS через `v-html` — быстро прогрепано, не найдено в `app/`, но не каждый компонент проверен).
- **JWT-реализация** (срок жизни, refresh, алгоритм — `JWT_ALGORITHM=HS256` ОК, но валидация подписи в `auth_required` не читалась).
