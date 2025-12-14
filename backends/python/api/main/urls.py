from django.urls import path
from .views import *

urlpatterns = [
    path('api', root, name='root'),
    path('api/health', health, name='health'),
    path('api/enum', get_enum, name='enum'),
    path('api/list', get_list, name='list'),
    path('api/install', install, name='install'),
    path('api/getToken', get_token, name='get_token'),
    path('api/reports/employee-project', report_employee_project, name='report_employee_project'),
    path('api/reports/project-employee', report_project_employee, name='report_project_employee'),
    path('api/timesheets/sync', timesheet_sync, name='timesheet_sync'),
    path('api/timesheets', timesheet_list, name='timesheet_list'),
]
