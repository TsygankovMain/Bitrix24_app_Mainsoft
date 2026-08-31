from django.urls import path, re_path
from . import views

# Explicitly mapping URLs to views to match frontend api.ts calls
urlpatterns = [
    path('api', views.root, name='root'),
    path('api/health', views.health, name='health'),
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
    # --- Финансовый функционал (в планах) изолирован: views отсутствуют в views.py после merge prod_2026 ---
    # path('api/finance-operations', views.get_finance_operations, name='get_finance_operations'),
    # path('api/finance-operations/create', views.create_finance_operation, name='create_finance_operation'),
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
    # Финансовый функционал (в планах) изолирован — view отсутствует:
    # path('api/project-budget/notify', views.run_project_budget_notifier, name='run_project_budget_notifier'),
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
    # Финансовый функционал (в планах) изолирован — view отсутствует:
    # path('api/finance-spa/validation', views.get_finance_spa_validation, name='get_finance_spa_validation'),
    path('api/project-spa/stages', views.get_project_spa_stages, name='get_project_spa_stages'),
    path('api/smart-processes/create', views.create_smart_process, name='create_smart_process'),
    path('api/smart-processes/create-fields', views.create_fields, name='create_fields'),
    path('api/smart-processes/create-field', views.create_mapped_field, name='create_mapped_field'),
    
    # Logs
    path('api/logs/requests', views.get_request_logs, name='get_request_logs'),
    path('api/logs/system', views.get_system_logs, name='get_system_logs'),

    # SPA Entry Point (Catch-all for frontend routing), but never for `/api...`
    re_path(r'^(?!api(?:/|$)).*$', views.serve_spa, name='serve_spa'),
]
