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

    # Timesheets
    path('api/sync-timesheets', timesheet_sync, name='sync_timesheets'), # Matches api.ts: /api/sync-timesheets
    path('api/timesheets', timesheet_list, name='list_timesheets'),      # Matches api.ts: /api/timesheets
]
