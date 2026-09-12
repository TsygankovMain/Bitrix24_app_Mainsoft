from django.urls import path, re_path
from . import views

# Explicitly mapping URLs to views to match frontend api.ts calls
urlpatterns = [
    path('api', views.root, name='root'),
    path('api/health', views.health, name='health'),
    # Версия собранного фронта: по ней ловится устаревшая вкладка (см. app_version.py).
    path('api/app-version', views.app_version, name='app_version'),
    path('healthz', views.health_check, name='health_check'),
    path('api/enum', views.get_enum, name='enum'),
    path('api/list', views.get_list, name='list'),
    
    # Auth & Install (Restored)
    path('api/install', views.install, name='install'),
    path('api/getToken', views.get_token, name='get_token'),

    # Filters & Reports
    path('api/get-filter-options', views.get_filter_options, name='get_filter_options'),
    path('api/get-filter-employees', views.get_filter_employees, name='get_filter_employees'),
    path('api/get-filter-projects', views.get_filter_projects, name='get_filter_projects'),
    path('api/support/status', views.get_support_status, name='get_support_status'),
    path('api/support/connect', views.connect_support_line, name='connect_support_line'),
    path('api/project-board', views.get_project_board, name='get_project_board'),
    # БДДС по проектам (bdds), этап 1. Все четыре ручки закрыты подпиской
    # портала: @feature_required(FEATURE_BDDS) — в том числе на чтении, см.
    # комментарий к разделу в views.py.
    path('api/finance-operations', views.get_finance_operations, name='get_finance_operations'),
    path('api/finance-operations/create', views.create_finance_operation, name='create_finance_operation'),
    path('api/project-board/meta', views.get_project_board_meta, name='get_project_board_meta'),
    path('api/project-board/card', views.get_project_board_card, name='get_project_board_card'),
    path('api/project-board/companies', views.get_project_board_companies, name='get_project_board_companies'),
    path('api/project-board/companies/search', views.search_project_board_companies, name='search_project_board_companies'),
    path('api/project-board/my-companies', views.list_my_companies, name='list_my_companies'),
    path('api/homepage/portfolio', views.get_homepage_portfolio, name='get_homepage_portfolio'),
    path('api/project-board/sync', views.sync_project_board, name='sync_project_board'),
    path('api/project-spa/backfill-timesheet', views.run_project_spa_backfill, name='run_project_spa_backfill'),
    path('api/project-board/create', views.create_project_board, name='create_project_board'),
    path('api/project-board/update', views.update_project_board, name='update_project_board'),
    path('api/project-board/update-stage', views.update_project_board_stage, name='update_project_board_stage'),
    path('api/project-board/archive', views.archive_project_board, name='archive_project_board'),
    path('api/project-board/run-daily-check', views.run_project_board_daily_check, name='run_project_board_daily_check'),
    path('api/project-budget/notify', views.run_project_budget_notifier, name='run_project_budget_notifier'),
    # Реестр проектов с бюджетами и карточка одного проекта. Адрес с
    # <project_id> стоит ПОСЛЕ общего: разные префиксы после api/bdds/projects
    # пересечься не могут, но порядок оставлен привычным.
    path('api/bdds/projects', views.get_bdds_projects, name='get_bdds_projects'),
    path('api/bdds/projects/<str:project_id>', views.get_bdds_project, name='get_bdds_project'),
    path('api/report-employee-project', views.report_employee_project, name='report_employee_project'),
    path('api/report-project-employee', views.report_project_employee, name='report_project_employee'),
    path('api/report-daily-workload', views.report_daily_workload, name='report_daily_workload'),
    path('api/report-project-task-employee', views.report_project_task_employee, name='report_project_task_employee'),
    path('api/report-project-task-employee-export', views.report_project_task_employee_export, name='report_project_task_employee_export'),
    path('api/report-employee-project-export', views.report_employee_project_export, name='report_employee_project_export'),
    path('api/report-project-employee-export', views.report_project_employee_export, name='report_project_employee_export'),
    path('api/report-daily-workload-export', views.report_daily_workload_export, name='report_daily_workload_export'),
    path('api/report-revenue-leakage', views.report_revenue_leakage, name='report_revenue_leakage'),
    path('api/report-revenue-leakage-export', views.report_revenue_leakage_export, name='report_revenue_leakage_export'),
    path('api/report-time-entry-discipline', views.report_time_entry_discipline, name='report_time_entry_discipline'),
    path('api/report-time-entry-discipline-export', views.report_time_entry_discipline_export, name='report_time_entry_discipline_export'),
    path('api/report-focus-analysis', views.report_focus_analysis, name='report_focus_analysis'),
    path('api/report-focus-analysis-export', views.report_focus_analysis_export, name='report_focus_analysis_export'),

    # Timesheets
    path('api/sync-timesheets', views.timesheet_sync, name='sync_timesheets'), # Matches api.ts: /api/sync-timesheets
    # Запись часов через бэкенд, а не напрямую из браузера: единственное место,
    # где на списание можно наложить серверное правило (закрытие месяца).
    # Закрытие месяца: список периодов, проверка, закрытие, переоткрытие,
    # опоздавшие часы. Спека — docs/architecture/period-closing-spec.md.
    path('api/periods', views.periods_list, name='periods_list'),
    path('api/periods/check', views.period_check, name='period_check'),
    path('api/periods/close', views.period_close, name='period_close'),
    path('api/periods/close-bulk', views.period_close_bulk, name='period_close_bulk'),
    path('api/periods/fix', views.period_fix, name='period_fix'),
    path('api/periods/reopen', views.period_reopen, name='period_reopen'),
    path('api/periods/late', views.period_late_arrivals, name='period_late_arrivals'),
    path('api/timesheet/create', views.timesheet_create, name='timesheet_create'),
    path('api/timesheet/update', views.timesheet_update, name='timesheet_update'),
    path('api/timesheet-sync-status', views.timesheet_sync_status, name='timesheet_sync_status'),
    path('api/timesheets', views.timesheet_list, name='list_timesheets'),      # Matches api.ts: /api/timesheets
    path('api/users', views.get_users, name='get_users'),
    path('api/export-raw-data', views.export_raw_data, name='export_raw_data'),

    # ИНН: дозаполнение в карточках списания
    path('api/inn-backfill/scan', views.inn_backfill_scan, name='inn_backfill_scan'),
    path('api/inn-backfill/apply', views.inn_backfill_apply, name='inn_backfill_apply'),
    path('api/inn-backfill/project-items', views.inn_backfill_project_items, name='inn_backfill_project_items'),
    path('api/projects-health', views.projects_health, name='projects_health'),

    # Configuration
    path('api/configuration', views.get_configuration, name='get_configuration'),
    path('api/configuration/save', views.save_configuration, name='save_configuration'),
    path('api/bitrix/internal-lists', views.get_internal_lists, name='get_internal_lists'),
    path('api/smart-processes', views.get_smart_processes, name='get_smart_processes'),
    path('api/smart-processes/fields', views.get_sp_fields, name='get_sp_fields'),
    path('api/project-spa/validation', views.get_project_spa_validation, name='get_project_spa_validation'),
    # Валидация смарт-процесса «Доходы-расходы (App)» остаётся выключенной:
    # её смысл появится на ЭТАПЕ 2, когда у операции добавится десятое поле
    # «статья ДДС» и проверять станет что. Сегодня операции читаются и
    # пишутся (api/finance-operations), а неполное сопоставление полей
    # честно отдаётся кодом finance_spa_not_configured прямо оттуда.
    # path('api/finance-spa/validation', views.get_finance_spa_validation, name='get_finance_spa_validation'),
    path('api/project-spa/stages', views.get_project_spa_stages, name='get_project_spa_stages'),
    path('api/smart-processes/create', views.create_smart_process, name='create_smart_process'),
    path('api/smart-processes/create-fields', views.create_fields, name='create_fields'),
    path('api/smart-processes/create-field', views.create_mapped_field, name='create_mapped_field'),
    
    # Счёт и акт (billing). Контракт —
    # docs/superpowers/specs/2026-09-12-billing-mvp-contract.md.
    # Один адрес api/billing/documents на GET (реестр) и POST (выставление):
    # гейты прав и подписки висят внутри, на POST-ветке, чтобы реестр читался
    # и без права выставлять, и при выключенной подписке.
    path('api/features', views.get_features, name='get_features'),
    # Роли и права (функция «roles» тарифа Pro, main/roles.py): свои права,
    # каталог с назначениями и назначение роли.
    path('api/roles/me', views.roles_me, name='roles_me'),
    path('api/roles', views.roles_list, name='roles_list'),
    path('api/roles/assign', views.roles_assign, name='roles_assign'),
    # Покупка Pro: заявка на счёт (main/pro_purchase_service.py). Портал — из
    # авторизации, не из тела запроса.
    path('api/pro/offer', views.pro_offer, name='pro_offer'),
    path('api/pro/quote', views.pro_quote, name='pro_quote'),
    path('api/pro/requisites', views.pro_requisites, name='pro_requisites'),
    path('api/pro/requests', views.pro_requests_create, name='pro_requests_create'),
    path('api/pro/requests/current', views.pro_requests_current, name='pro_requests_current'),
    path('api/pro/requests/<str:request_id>/cancel', views.pro_requests_cancel, name='pro_requests_cancel'),
    path('api/pro/requests/<str:request_id>/invoice.pdf', views.pro_requests_invoice_pdf, name='pro_requests_invoice_pdf'),
    # Шаблоны генератора документов портала — для выбора в настройках.
    # Стоит ДО маршрута documents/<document_id>, но пересечься они всё равно
    # не могут: разные префиксы после api/billing.
    path('api/billing/templates', views.billing_templates, name='billing_templates'),
    path('api/billing/preview', views.billing_preview, name='billing_preview'),
    path('api/billing/documents', views.billing_documents, name='billing_documents'),
    path('api/billing/documents/<str:document_id>', views.billing_document_detail, name='billing_document_detail'),
    path('api/billing/documents/<str:document_id>/cancel', views.billing_document_cancel, name='billing_document_cancel'),
    path('api/billing/documents/<str:document_id>/act', views.billing_document_act, name='billing_document_act'),
    path('api/billing/documents/<str:document_id>/invoice-print', views.billing_document_invoice_print, name='billing_document_invoice_print'),
    path('api/billing/documents/<str:document_id>/detail.xlsx', views.billing_document_detail_export, name='billing_document_detail_export'),

    # Logs
    path('api/logs/requests', views.get_request_logs, name='get_request_logs'),
    path('api/logs/system', views.get_system_logs, name='get_system_logs'),

    # SPA Entry Point (Catch-all for frontend routing), but never for `/api...`
    re_path(r'^(?!api(?:/|$)).*$', views.serve_spa, name='serve_spa'),
]
