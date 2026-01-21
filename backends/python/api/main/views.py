from django.core.paginator import Paginator
from django.db.models import Q
from django.db.models import Q
from django.http import JsonResponse, HttpResponse
from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.clickjacking import xframe_options_exempt

from .utils.decorators import auth_required, log_errors
from .utils import AuthorizedRequest
from .models import ApplicationInstallation, TimesheetItem, RequestLog, SystemLog

from config import load_config
from .services import BitrixDataService, ReportService, TimesheetSyncService, ConfigurationService
from .installation_service import InstallationService, InstallationError

__all__ = [
    "root",
    "health",
    "health_check",
    "serve_spa",
    "get_enum",
    "get_list",
    "install",
    "get_token",
    "get_filter_options",
    "report_employee_project",
    "report_project_employee",
    "report_daily_workload",
    "timesheet_sync",
    "timesheet_list",
    "get_configuration",
    "save_configuration",
    "get_smart_processes",
    "get_sp_fields",
    "get_request_logs",
    "get_system_logs",
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

def health_check(request):
    """
    Public health check for deployment platforms (e.g. Timeweb Cloud Apps).
    No auth required.
    """
    return JsonResponse({
        "status": "ok",
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
@log_errors("install")
def install(request):
    """
    Handle Bitrix24 application installation.
    Supports HEAD/GET for Marketplace validation.
    """
    if request.method in ["HEAD", "GET"]:
        return HttpResponse(status=200)

    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    # Manual Auth Check since we removed @auth_required to support HEAD
    try:
        # Re-using the decorator logic or manually calling the auth service
        # Since @auth_required populated request.bitrix24_account, we need to do it here manually
        # effectively inlining the auth check for POST requests ONLY.
        
        # However, to keep it clean, let's keep @auth_required but make it smarter?
        # No, decorators are hard to make conditional on method easily without complexity.
        # Simplest way: wrapper function.
        pass
    except Exception:
        pass

    # Better approach: 
    # We can't easily inline the complex auth logic from decorators.
    # Let's use a dual-handler approach or simply wrap the logic.
    
    return _install_post_logic(request)

@require_POST
@auth_required
def _install_post_logic(request: AuthorizedRequest):
    bitrix24_account = request.bitrix24_account

    ApplicationInstallation.objects.update_or_create(
        bitrix_24_account=bitrix24_account,
        defaults={
            "status": bitrix24_account.status,
            "portal_license_family": "",
            "application_token": bitrix24_account.application_token,
        },
    )

    try:
        service = InstallationService(bitrix24_account.client, bitrix24_account)
        config = service.install_app_sync()
        return JsonResponse({"message": "Installation successful", "config": config})
    except InstallationError as e:
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        import traceback
        return JsonResponse({"error": f"Unexpected error: {str(e)}", "trace": traceback.format_exc()}, status=500)


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
    
    # Init services with config
    config_service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    config = config_service.get_configuration_sync()
    data_service = BitrixDataService(request.bitrix24_account.client, config)
    
    # Fetch Names
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
    
    # Config & Services
    config_service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    config = config_service.get_configuration_sync()
    data_service = BitrixDataService(request.bitrix24_account.client, config)
    
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
    
    config_service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    config = config_service.get_configuration_sync()
    data_service = BitrixDataService(request.bitrix24_account.client, config)

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
    config_service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    config = config_service.get_configuration_sync()
    
    service = TimesheetSyncService(request.bitrix24_account.client, request.bitrix24_account, config)
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


@xframe_options_exempt
@require_GET
@log_errors("get_configuration")
@auth_required
def get_configuration(request: AuthorizedRequest):
    service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    return JsonResponse(service.get_configuration_sync())


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("save_configuration")
@auth_required
def save_configuration(request: AuthorizedRequest):
    import json
    service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    try:
        body = json.loads(request.body)
        config = body.get('config', {})
        service.save_configuration_sync(config)
        return JsonResponse({"status": "success"})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@xframe_options_exempt
@require_GET
@log_errors("get_smart_processes")
@auth_required
def get_smart_processes(request: AuthorizedRequest):
    service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    return JsonResponse({"types": service.get_smart_processes_sync()})


@xframe_options_exempt
@require_GET
@log_errors("get_sp_fields")
@auth_required
def get_sp_fields(request: AuthorizedRequest):
    service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    entity_type_id = request.GET.get('entityTypeId')
    if not entity_type_id:
         return JsonResponse({"fields": []})
    
    return JsonResponse({"fields": service.get_sp_fields_sync(int(entity_type_id))})


@xframe_options_exempt
@require_GET
@log_errors("report_daily_workload")
@auth_required
def report_daily_workload(request: AuthorizedRequest):
    queryset = TimesheetItem.objects.filter(bitrix24_account=request.bitrix24_account)

    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    emp_ids = request.GET.getlist('employee_ids[]') 
    proj_ids = request.GET.getlist('project_ids[]')

    # Defaults for date if missing (current month)
    from datetime import date, timedelta
    if not date_from:
        today = date.today()
        date_from = date(today.year, today.month, 1).isoformat()
    if not date_to:
        today = date.today()
        date_to = today.isoformat()

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
        # Re-construct dictionary identical to what Service expects
        items.append({
            "sotrudnik_id": model_item.employee_id,
            "project_name": model_item.project_title,
            "kolichestvo_chasov": model_item.hours,
            "id_zadachi": model_item.task_id,
            "nazvanie_zadachi": model_item.task_hierarchy_titles[-1] if model_item.task_hierarchy_titles else "No Title",
            "opisanie": model_item.description,
            "data": model_item.date_reflection.isoformat() if model_item.date_reflection else None,
        })
    
    # Config lookup for user fetching (not strictly needed since fetch_users uses generic user.get, but cleaner)
    config_service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    config = config_service.get_configuration_sync()
    data_service = BitrixDataService(request.bitrix24_account.client, config)

    user_map = data_service.fetch_users(list(user_ids))
    
    report_service = ReportService()
    report = report_service.generate_daily_workload(items, user_map, date_from, date_to)
    
    return JsonResponse(report, safe=False)


@xframe_options_exempt
@require_GET
@log_errors("get_request_logs")
@auth_required
def get_request_logs(request: AuthorizedRequest):
    page_number = request.GET.get('page', 1)
    page_size = request.GET.get('limit', 50)
    
    queryset = RequestLog.objects.all().order_by('-timestamp')
    paginator = Paginator(queryset, page_size)
    page_obj = paginator.get_page(page_number)
    
    items = []
    for item in page_obj:
        items.append({
            "id": str(item.id),
            "timestamp": item.timestamp.isoformat(),
            "method": item.method,
            "path": item.path,
            "status_code": item.status_code,
            "duration_ms": item.duration_ms,
            "request_body": str(item.request_body) if item.request_body else "",
            "response_body": str(item.response_body) if item.response_body else "",
        })
        
    return JsonResponse({
        "items": items,
        "total": paginator.count,
        "page": page_obj.number,
        "pages": paginator.num_pages,
    })


@xframe_options_exempt
@require_GET
@log_errors("get_system_logs")
@auth_required
def get_system_logs(request: AuthorizedRequest):
    page_number = request.GET.get('page', 1)
    page_size = request.GET.get('limit', 50)
    
    queryset = SystemLog.objects.all().order_by('-timestamp')
    paginator = Paginator(queryset, page_size)
    page_obj = paginator.get_page(page_number)
    
    items = []
    for item in page_obj:
        items.append({
            "id": str(item.id),
            "timestamp": item.timestamp.isoformat(),
            "level": item.level,
            "module": item.module,
            "message": item.message,
            "traceback": item.traceback or ""
        })
        
    return JsonResponse({
        "items": items,
        "total": paginator.count,
        "page": page_obj.number,
        "pages": paginator.num_pages,
    })

@xframe_options_exempt
def serve_spa(request):
    """
    Serve index.html for any route (GET or POST) to support Bitrix24 iframe loading and SPA navigation.
    """
    try:
        # settings.BASE_DIR points to /app inside container
        # index.html is copied to /app/frontend_build/index.html
        index_path = settings.BASE_DIR / "frontend_build" / "index.html"
        with open(index_path, 'r') as f:
            return HttpResponse(f.read())
    except FileNotFoundError:
        return HttpResponse(
            f"Frontend not found at {index_path}. "
            "Please ensure 'npm run generate' ran successfully during build.",
            status=404
        )
