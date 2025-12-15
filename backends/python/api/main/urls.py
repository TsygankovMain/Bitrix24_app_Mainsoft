from django.urls import path
from .views import *

# Explicitly mapping URLs to views to match frontend api.ts calls
urlpatterns = [
    path('api', root, name='root'),
    path('api/health', health, name='health'),
    path('api/enum', get_enum, name='enum'),
    path('api/list', get_list, name='list'),
    
    # Auth & Install (Restored)
    path('api/install', install, name='install'),
    path('api/getToken', get_token, name='get_token'),

    # Filters & Reports
    path('api/get-filter-options', get_filter_options, name='get_filter_options'),
    path('api/report-employee-project', report_employee_project, name='report_employee_project'),
    path('api/report-project-employee', report_project_employee, name='report_project_employee'),
    path('api/report-daily-workload', report_daily_workload, name='report_daily_workload'),

    # Timesheets
    path('api/sync-timesheets', timesheet_sync, name='sync_timesheets'), # Matches api.ts: /api/sync-timesheets
    path('api/timesheets', timesheet_list, name='list_timesheets'),      # Matches api.ts: /api/timesheets

    # Configuration
    path('api/configuration', get_configuration, name='get_configuration'),
    path('api/configuration/save', save_configuration, name='save_configuration'),
    path('api/smart-processes', get_smart_processes, name='get_smart_processes'),
    path('api/smart-processes/fields', get_sp_fields, name='get_sp_fields'),
    
    # Logs
    path('api/logs/requests', get_request_logs, name='get_request_logs'),
    path('api/logs/system', get_system_logs, name='get_system_logs'),
]
