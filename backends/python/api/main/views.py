from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.clickjacking import xframe_options_exempt

from .utils.decorators import auth_required, log_errors
from .utils import AuthorizedRequest
from .models import ApplicationInstallation, TimesheetItem

from config import load_config
from .services import BitrixDataService, ReportService, TimesheetSyncService

__all__ = [
    "root",
    "health",
    "get_enum",
    "get_list",
    "install",
    "get_token",
    "get_filter_options",
    "report_employee_project",
    "report_project_employee",
    "timesheet_sync",
    "timesheet_list",
]

config = load_config()


@xframe_options_exempt
@require_GET
@log_errors("root")
@auth_required
def root(request: AuthorizedRequest):
    return JsonResponse({"message": "Python Backend is running"})


@xframe_options_exempt
@require_GET
@log_errors("health")
@auth_required
def health(request: AuthorizedRequest):
    return JsonResponse({
        "status": "healthy",
        "backend": "python",
        "timestamp": timezone.now().timestamp(),
    })


@xframe_options_exempt
@require_GET
@log_errors("get_enum")
@auth_required
def get_enum(request: AuthorizedRequest):
    options = ["option 1", "option 2", "option 3"]
    return JsonResponse(options, safe=False)


@xframe_options_exempt
@require_GET
@log_errors("get_list")
@auth_required
def get_list(request: AuthorizedRequest):
    elements = ["element 1", "element 2", "element 3"]
    return JsonResponse(elements, safe=False)


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("install")
@auth_required
def install(request: AuthorizedRequest):
    bitrix24_account = request.bitrix24_account

    ApplicationInstallation.objects.update_or_create(
        bitrix_24_account=bitrix24_account,
        defaults={
            "status": bitrix24_account.status,
            "portal_license_family": "",
            "application_token": bitrix24_account.application_token,
        },
    )

    return JsonResponse({"message": "Installation successful"})


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("get_token")
@auth_required
def get_token(request: AuthorizedRequest):
    return JsonResponse({"token": request.bitrix24_account.create_jwt_token()})


@xframe_options_exempt
@require_GET
@log_errors("get_filter_options")
@auth_required
def get_filter_options(request: AuthorizedRequest):
    """
    Returns unique employees and projects for filtering.
    """
    queryset = TimesheetItem.objects.filter(bitrix24_account=request.bitrix24_account)
    
    # 1. Unique Employees
    emp_ids = list(queryset.values_list('employee_id', flat=True).distinct())
    
    # Fetch Names
    data_service = BitrixDataService(request.bitrix24_account.client)
    user_map = data_service.fetch_users(emp_ids)
    
    employees = []
    for uid in emp_ids:
        # Avoid empty users if data is inconsistent
        if not uid: continue
            
        employees.append({
            "id": str(uid),
            "name": user_map.get(str(uid), f"User {uid}")
        })
    
    # 2. Unique Projects
    projs = queryset.values('project_id', 'project_title').distinct()
    projects = []
    seen_ids = set()
    
    for p in projs:
        pid = p['project_id']
        ptitle = p['project_title']
        
        # Determine strict ID for frontend
        if not pid and not ptitle:
            continue
            
        # Preference: Use project_id. 
        # Fallback: project_title.
        # This ID is what will be sent back in filter params.
        final_id = str(pid) if pid else str(ptitle)
        
        if final_id not in seen_ids:
            Title = ptitle or "Без названия"
            projects.append({
                "id": final_id,
                "name": Title
            })
            seen_ids.add(final_id)

    return JsonResponse({
        "employees": sorted(employees, key=lambda x: x['name']),
        "projects": sorted(projects, key=lambda x: x['name'])
    })


@xframe_options_exempt
@require_GET
@log_errors("report_employee_project")
@auth_required
def report_employee_project(request: AuthorizedRequest):
    queryset = TimesheetItem.objects.filter(bitrix24_account=request.bitrix24_account)
    
    # Filters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    emp_ids = request.GET.getlist('employee_ids[]')
    proj_ids = request.GET.getlist('project_ids[]')
    
    # Date Filtering
    if date_from:
        queryset = queryset.filter(date_reflection__gte=date_from)
    if date_to:
        queryset = queryset.filter(date_reflection__lte=date_to)
        
    # Employee Filtering
    if emp_ids:
        queryset = queryset.filter(employee_id__in=emp_ids)
        
    # Project Filtering
    # Handles both ID-based and Title-based IDs (backward compatibility)
    if proj_ids:
        q_obj = Q(project_id__in=proj_ids) | Q(project_title__in=proj_ids)
        queryset = queryset.filter(q_obj)

    items = []
    user_ids = set()
    
    for model_item in queryset:
        user_ids.add(model_item.employee_id)
        # Construct item for Service
        items.append({
            "sotrudnik_id": model_item.employee_id,
            "project_name": model_item.project_title,
            "kolichestvo_chasov": model_item.hours,
            "id_zadach_ierarhiya": model_item.task_hierarchy_ids,
            "title_zadach_ierarhiya": model_item.task_hierarchy_titles,
            "uchitivaem": model_item.is_billable,
            "opisanie": model_item.description,
            "data": model_item.date_reflection.isoformat() if model_item.date_reflection else None,
            "nazvanie_zadachi": model_item.task_hierarchy_titles[-1] if model_item.task_hierarchy_titles else "No Title"
        })
    
    data_service = BitrixDataService(request.bitrix24_account.client)
    user_map = data_service.fetch_users(list(user_ids))
    
    report_service = ReportService()
    report = report_service.generate_employee_projects(items, user_map)
    
    return JsonResponse(report, safe=False)


@xframe_options_exempt
@require_GET
@log_errors("report_project_employee")
@auth_required
def report_project_employee(request: AuthorizedRequest):
    queryset = TimesheetItem.objects.filter(bitrix24_account=request.bitrix24_account)

    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    emp_ids = request.GET.getlist('employee_ids[]') 
    proj_ids = request.GET.getlist('project_ids[]')

    if date_from:
        queryset = queryset.filter(date_reflection__gte=date_from)
    if date_to:
        queryset = queryset.filter(date_reflection__lte=date_to)
        
    if emp_ids:
        queryset = queryset.filter(employee_id__in=emp_ids)
        
    if proj_ids:
        q_obj = Q(project_id__in=proj_ids) | Q(project_title__in=proj_ids)
        queryset = queryset.filter(q_obj)

    items = []
    user_ids = set()
    for model_item in queryset:
        user_ids.add(model_item.employee_id)
        items.append({
            "sotrudnik_id": model_item.employee_id,
            "project_name": model_item.project_title,
            "kolichestvo_chasov": model_item.hours,
            "id_zadach_ierarhiya": model_item.task_hierarchy_ids,
            "title_zadach_ierarhiya": model_item.task_hierarchy_titles,
            "uchitivaem": model_item.is_billable,
            "opisanie": model_item.description,
            "data": model_item.date_reflection.isoformat() if model_item.date_reflection else None,
            "nazvanie_zadachi": model_item.task_hierarchy_titles[-1] if model_item.task_hierarchy_titles else "No Title"
        })
    
    data_service = BitrixDataService(request.bitrix24_account.client)
    user_map = data_service.fetch_users(list(user_ids))
    
    report_service = ReportService()
    report = report_service.generate_project_employees(items, user_map)
    
    return JsonResponse(report, safe=False)


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("timesheet_sync")
@auth_required
def timesheet_sync(request: AuthorizedRequest):
    service = TimesheetSyncService(request.bitrix24_account.client, request.bitrix24_account)
    count = service.sync_all()
    return JsonResponse({"status": "success", "count": count})


@xframe_options_exempt
@require_GET
@log_errors("timesheet_list")
@auth_required
def timesheet_list(request: AuthorizedRequest):
    queryset = TimesheetItem.objects.filter(bitrix24_account=request.bitrix24_account).order_by('-date_reflection', '-bitrix_id')
    
    page_number = request.GET.get('page', 1)
    page_size = request.GET.get('limit', 50)
    
    paginator = Paginator(queryset, page_size)
    page_obj = paginator.get_page(page_number)
    
    items = []
    for item in page_obj:
        items.append({
            "id": item.bitrix_id,
            "task_id": item.task_id,
            "employee_id": item.employee_id,
            "hours": item.hours,
            "is_billable": item.is_billable,
            "non_billable_hours": item.non_billable_hours,
            "description": item.description,
            "project_title": item.project_title,
            "date": item.date_reflection.isoformat() if item.date_reflection else None,
            "created_at": item.created_at.isoformat()
        })
        
    return JsonResponse({
        "items": items,
        "total": paginator.count,
        "page": page_obj.number,
        "pages": paginator.num_pages,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
    })
