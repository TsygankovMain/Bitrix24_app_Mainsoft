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
    path('api/report-employee-project', views.report_employee_project, name='report_employee_project'),
    path('api/report-project-employee', views.report_project_employee, name='report_project_employee'),
    path('api/report-daily-workload', views.report_daily_workload, name='report_daily_workload'),
    path('api/report-project-task-employee', views.report_project_task_employee, name='report_project_task_employee'),
    path('api/report-revenue-leakage', views.report_revenue_leakage, name='report_revenue_leakage'),
    path('api/report-time-entry-discipline', views.report_time_entry_discipline, name='report_time_entry_discipline'),
    path('api/report-focus-analysis', views.report_focus_analysis, name='report_focus_analysis'),

    # Timesheets
    path('api/sync-timesheets', views.timesheet_sync, name='sync_timesheets'), # Matches api.ts: /api/sync-timesheets
    path('api/timesheets', views.timesheet_list, name='list_timesheets'),      # Matches api.ts: /api/timesheets
    path('api/export-raw-data', views.export_raw_data, name='export_raw_data'),

    # Configuration
    path('api/configuration', views.get_configuration, name='get_configuration'),
    path('api/configuration/save', views.save_configuration, name='save_configuration'),
    path('api/smart-processes', views.get_smart_processes, name='get_smart_processes'),
    path('api/smart-processes/fields', views.get_sp_fields, name='get_sp_fields'),
    path('api/smart-processes/create', views.create_smart_process, name='create_smart_process'),
    path('api/smart-processes/create-fields', views.create_fields, name='create_fields'),
    
    # Logs
    path('api/logs/requests', views.get_request_logs, name='get_request_logs'),
    path('api/logs/system', views.get_system_logs, name='get_system_logs'),

    # SPA Entry Point (Catch-all for frontend routing)
    re_path(r'^.*$', views.serve_spa, name='serve_spa'),
]
