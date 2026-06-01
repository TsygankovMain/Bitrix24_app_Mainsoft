# Performance baseline — отчёты, май 2026

Документ описывает, как собрать **базовые тайминги** работы отчётов, чтобы потом сравнить с результатом точечных оптимизаций (плана `mossy-orbiting-patterson.md`, шаг 1.4).

## Что добавлено в код

- `backends/python/api/main/perf.py` — `ReportProfiler`: контекст-менеджер `with profiler.stage("name"):`, INFO-лог с тегом `[REPORT_PERF]`, заголовок `X-Report-Timings` в DEBUG-режиме.
- `backends/python/api/main/views.py` — все 7 отчётных эндпоинтов и `timesheet_sync` обёрнуты в profiler:
  - `report_employee_project`
  - `report_project_employee`
  - `report_project_task_employee`
  - `report_revenue_leakage`
  - `report_time_entry_discipline`
  - `report_focus_analysis`
  - `report_daily_workload`
  - `timesheet_sync`
- `frontend/app/composables/useReportGenerator.ts` — логирует `[report-perf]` в `console.info` при `import.meta.dev` или `?perf=1` в URL. Замеряет `sync_ms`, `fetch_ms`, `total_ms`.

## Как снять тайминги

### Backend (логи)

```bash
make dev-python
docker compose logs -f api-python | grep REPORT_PERF
```

Каждый отчёт даёт одну строку:

```
[REPORT_PERF] report_employee_project account=42 rows=1234 users=15 timings=queryset_build=2ms,materialize=312ms,user_map=890ms,project_lookup=45ms,build_items=8ms,service_generate=120ms,serialize=34ms,total=1411ms
```

### Frontend (DevTools)

1. Открыть приложение в Bitrix24 (или localhost через cloudpub).
2. К URL отчёта добавить `?perf=1` (если работаете не в dev-сборке).
3. Открыть DevTools → Console → искать `[report-perf]`.

Запись:

```
[report-perf] {
  report: "employee",
  sync_ms: 4200,
  fetch_ms: 1411,
  total_ms: 5615
}
```

При DEBUG=True backend также проставит заголовок `X-Report-Timings` — его видно в Network → Headers.

## Шаблон для записи baseline

Проведите минимум 3 прогона на каждый отчёт. Между прогонами **не перезапускайте backend** — это покажет эффект кэшей. Между сериями — **с очищенным кэшем** (`docker compose restart api-python`).

| Отчёт | Период | Холодный (1-й прогон) | Прогретый (3-й прогон) | Узкое место (наибольший stage) |
|---|---|---|---|---|
| Сотрудники | 30 дн | __ ms | __ ms | __ |
| Сотрудники | 90 дн | __ ms | __ ms | __ |
| Проекты | 30 дн | __ ms | __ ms | __ |
| Daily workload | 30 дн | __ ms | __ ms | __ |
| Revenue leakage | 30 дн | __ ms | __ ms | __ |
| Time discipline | 30 дн | __ ms | __ ms | __ |
| Focus analysis | 30 дн | __ ms | __ ms | __ |
| Project-task | 30 дн | __ ms | __ ms | __ |

Дополнительно: тайминги `timesheet_sync` (вызывается перед каждым отчётом из фронта).

| Sync | 1-й | 2-й | 3-й |
|---|---|---|---|
| timesheet_sync | __ ms | __ ms | __ ms |

## Что делать после сбора

Заполнить таблицу выше, найти 1-2 самых медленных stage. Дальше — действовать по плану `mossy-orbiting-patterson.md` пункт 1.4 (гипотезы A/B/C):

- **Если `sync_ms` доминирует** в `[report-perf]` → гипотеза A: TTL для `syncTimesheets` в `useReportGenerator.ts`.
- **Если `user_map` стабильно > 500 ms** → гипотеза B: кэш `_get_user_map` в `django.core.cache`.
- **Если `project_lookup` повторяется внутри одной сессии** → гипотеза C: кэш `build_project_title_lookups`.
- **Если `materialize` или `service_generate` > 1 сек на 1000+ строк** → DB-индекс или streaming в `report_services.py`.

**Не оптимизировать вслепую** — только то, что подтверждено цифрами.
