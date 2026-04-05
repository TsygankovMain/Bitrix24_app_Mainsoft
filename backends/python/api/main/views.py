from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse, HttpResponse
from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.clickjacking import xframe_options_exempt

from .utils.decorators import auth_required, log_errors
from .utils import AuthorizedRequest
from .models import ApplicationInstallation, TimesheetItem, RequestLog, SystemLog, ProjectCard

import json
import openpyxl
from openpyxl.styles import Font, Alignment

from config import load_config
from .services import (
    BitrixDataService,
    ReportService,
    TimesheetSyncService,
    ConfigurationService,
    ProjectCardService,
    ProjectSyncService,
    ProjectStageAutomationService,
    get_project_card_queryset,
)
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
    "get_filter_employees",
    "get_filter_projects",
    "get_project_board",
    "sync_project_board",
    "update_project_board",
    "update_project_board_stage",
    "archive_project_board",
    "run_project_board_daily_check",
    "get_project_board_companies",
    "report_employee_project",
    "report_project_employee",
    "report_daily_workload",
    "report_project_task_employee",
    "report_revenue_leakage",
    "report_time_entry_discipline",
    "report_focus_analysis",
    "timesheet_sync",
    "timesheet_list",
    "get_configuration",
    "save_configuration",
    "get_smart_processes",
    "get_sp_fields",
    "get_request_logs",
    "get_system_logs",
    "create_smart_process",
    "create_fields",
    "export_raw_data",
]

config = load_config()


def _get_filtered_timesheet_queryset(request: AuthorizedRequest):
    queryset = TimesheetItem.objects.filter(bitrix24_account=request.bitrix24_account)
    archived_cards = get_project_card_queryset(request.bitrix24_account).filter(is_archived=True)
    archived_project_ids = [project_id for project_id in archived_cards.values_list('project_id', flat=True) if project_id]
    archived_project_names = [project_name for project_name in archived_cards.values_list('project_name', flat=True) if project_name]

    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    emp_ids = request.GET.getlist('employee_ids[]')
    proj_ids = request.GET.getlist('project_ids[]')
    employee_mode = request.GET.get('employee_mode', 'include')
    project_mode = request.GET.get('project_mode', 'include')

    if date_from:
        queryset = queryset.filter(date_reflection__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(date_reflection__date__lte=date_to)
    if archived_project_ids or archived_project_names:
        archived_q = Q()
        if archived_project_ids:
            archived_q |= Q(project_id__in=archived_project_ids)
        if archived_project_names:
            archived_q |= Q(project_title__in=archived_project_names)
        queryset = queryset.exclude(archived_q)
    if emp_ids:
        if employee_mode == 'exclude':
            queryset = queryset.exclude(employee_id__in=emp_ids)
        else:
            queryset = queryset.filter(employee_id__in=emp_ids)
    if proj_ids:
        project_q = Q(project_id__in=proj_ids) | Q(project_title__in=proj_ids)
        if project_mode == 'exclude':
            queryset = queryset.exclude(project_q)
        else:
            queryset = queryset.filter(project_q)

    return queryset


def _get_user_map(request: AuthorizedRequest, user_ids):
    if not user_ids:
        return {}

    config_service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    config = config_service.get_configuration_sync()
    data_service = BitrixDataService(request.bitrix24_account.client, config)
    return data_service.fetch_users(list(user_ids))


def _get_data_service(request: AuthorizedRequest):
    config_service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    config = config_service.get_configuration_sync()
    return BitrixDataService(request.bitrix24_account.client, config)


def _build_employee_filter_options(request: AuthorizedRequest):
    data_service = _get_data_service(request)
    return data_service.fetch_active_users()


def _build_project_filter_options(request: AuthorizedRequest):
    queryset = TimesheetItem.objects.filter(bitrix24_account=request.bitrix24_account)
    project_cards = get_project_card_queryset(request.bitrix24_account)
    active_project_ids = set(
        project_id
        for project_id in project_cards.filter(is_archived=False)
        .values_list('project_id', flat=True)
        if project_id
    )
    active_project_names = set(
        project_name
        for project_name in project_cards.filter(is_archived=False)
        .values_list('project_name', flat=True)
        if project_name
    )
    projs = queryset.values('project_id', 'project_title').distinct()
    projects = []
    seen_ids = set()

    for project in projs:
        project_id = project['project_id']
        project_title = project['project_title']

        if not project_id and not project_title:
            continue

        final_id = str(project_id) if project_id else str(project_title)
        if (active_project_ids or active_project_names) and final_id not in active_project_ids and (project_title or "") not in active_project_names:
            continue
        if final_id in seen_ids:
            continue

        projects.append({
            "id": final_id,
            "name": project_title or "Без названия"
        })
        seen_ids.add(final_id)

    return sorted(projects, key=lambda item: item["name"])


def _load_request_json(request: AuthorizedRequest):
    try:
        return json.loads(request.body or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


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
    print(f"DEBUG: install view called. Method: {request.method} Path: {request.path}")
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
    return JsonResponse({
        "employees": _build_employee_filter_options(request),
        "projects": _build_project_filter_options(request)
    })


@xframe_options_exempt
@require_GET
@log_errors("get_filter_employees")
@auth_required
def get_filter_employees(request: AuthorizedRequest):
    return JsonResponse({"employees": _build_employee_filter_options(request)})


@xframe_options_exempt
@require_GET
@log_errors("get_filter_projects")
@auth_required
def get_filter_projects(request: AuthorizedRequest):
    return JsonResponse({"projects": _build_project_filter_options(request)})


@xframe_options_exempt
@require_GET
@log_errors("get_project_board")
@auth_required
def get_project_board(request: AuthorizedRequest):
    service = ProjectCardService(request.bitrix24_account.client, request.bitrix24_account)
    return JsonResponse(service.get_board_data())


@xframe_options_exempt
@require_GET
@log_errors("get_project_board_companies")
@auth_required
def get_project_board_companies(request: AuthorizedRequest):
    service = ProjectCardService(request.bitrix24_account.client, request.bitrix24_account)
    return JsonResponse({"companies": service.get_companies()})


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("sync_project_board")
@auth_required
def sync_project_board(request: AuthorizedRequest):
    service = ProjectSyncService(request.bitrix24_account.client, request.bitrix24_account)
    return JsonResponse(service.sync())


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("update_project_board")
@auth_required
def update_project_board(request: AuthorizedRequest):
    payload = _load_request_json(request)
    project_id = payload.get("project_id")
    if not project_id:
        return JsonResponse({"error": "project_id is required"}, status=400)

    service = ProjectCardService(request.bitrix24_account.client, request.bitrix24_account)

    try:
        result = service.update_project_card(str(project_id), payload)
        return JsonResponse(result)
    except ProjectCard.DoesNotExist:
        return JsonResponse({"error": "Проект не найден"}, status=404)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("update_project_board_stage")
@auth_required
def update_project_board_stage(request: AuthorizedRequest):
    payload = _load_request_json(request)
    project_id = payload.get("project_id")
    stage = payload.get("stage")

    if not project_id or not stage:
        return JsonResponse({"error": "project_id and stage are required"}, status=400)

    service = ProjectCardService(request.bitrix24_account.client, request.bitrix24_account)

    try:
        card = service.update_stage(str(project_id), str(stage))
        return JsonResponse({"card": card})
    except ProjectCard.DoesNotExist:
        return JsonResponse({"error": "Проект не найден"}, status=404)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("archive_project_board")
@auth_required
def archive_project_board(request: AuthorizedRequest):
    payload = _load_request_json(request)
    project_id = payload.get("project_id")
    is_archived = str(payload.get("is_archived", "")).strip().lower() in {"1", "true", "y", "yes", "on"}

    if not project_id:
        return JsonResponse({"error": "project_id is required"}, status=400)

    service = ProjectCardService(request.bitrix24_account.client, request.bitrix24_account)

    try:
        result = service.archive_project(str(project_id), is_archived)
        return JsonResponse(result)
    except ProjectCard.DoesNotExist:
        return JsonResponse({"error": "Проект не найден"}, status=404)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("run_project_board_daily_check")
@auth_required
def run_project_board_daily_check(request: AuthorizedRequest):
    service = ProjectStageAutomationService(request.bitrix24_account)
    return JsonResponse(service.run_daily_check())


@xframe_options_exempt
@require_GET
@log_errors("report_employee_project")
@auth_required
def report_employee_project(request: AuthorizedRequest):
    queryset = _get_filtered_timesheet_queryset(request)

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
            "nazvanie_zadachi": model_item.task_hierarchy_titles[-1] if model_item.task_hierarchy_titles else "No Title",
            "id_elem": model_item.bitrix_id,
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
    queryset = _get_filtered_timesheet_queryset(request)

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
            "nazvanie_zadachi": model_item.task_hierarchy_titles[-1] if model_item.task_hierarchy_titles else "No Title",
            "id_elem": model_item.bitrix_id,
        })
    
    config_service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    config = config_service.get_configuration_sync()
    data_service = BitrixDataService(request.bitrix24_account.client, config)

    user_map = data_service.fetch_users(list(user_ids))
    
    report_service = ReportService()
    report = report_service.generate_project_employees(items, user_map)
    
    return JsonResponse(report, safe=False)

@xframe_options_exempt
@require_GET
@log_errors("report_project_task_employee")
@auth_required
def report_project_task_employee(request: AuthorizedRequest):
    """Report: Project -> Task Hierarchy -> Employee -> Items"""
    queryset = _get_filtered_timesheet_queryset(request)

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
            "nazvanie_zadachi": model_item.task_hierarchy_titles[-1] if model_item.task_hierarchy_titles else "No Title",
            "id_zadachi": model_item.task_id,
            "id_elem": model_item.bitrix_id,
        })

    config_service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    config = config_service.get_configuration_sync()
    data_service = BitrixDataService(request.bitrix24_account.client, config)

    user_map = data_service.fetch_users(list(user_ids))

    report_service = ReportService()
    report = report_service.generate_project_task_employees(items, user_map)

    return JsonResponse(report, safe=False)


@xframe_options_exempt
@require_GET
@log_errors("report_revenue_leakage")
@auth_required
def report_revenue_leakage(request: AuthorizedRequest):
    queryset = _get_filtered_timesheet_queryset(request)
    rows = list(queryset.values(
        'employee_id',
        'project_title',
        'hours',
        'is_billable',
    ))

    user_ids = {row['employee_id'] for row in rows if row.get('employee_id')}
    user_map = _get_user_map(request, user_ids)

    items = [{
        "sotrudnik_id": row["employee_id"],
        "project_name": row["project_title"],
        "kolichestvo_chasov": row["hours"],
        "uchitivaem": row["is_billable"],
    } for row in rows]

    report_service = ReportService()
    report = report_service.generate_revenue_leakage(items, user_map)
    return JsonResponse(report)


@xframe_options_exempt
@require_GET
@log_errors("report_time_entry_discipline")
@auth_required
def report_time_entry_discipline(request: AuthorizedRequest):
    queryset = _get_filtered_timesheet_queryset(request)
    rows = list(queryset.values(
        'employee_id',
        'date_reflection',
        'source_created_at',
        'created_at',
    ))

    user_ids = {row['employee_id'] for row in rows if row.get('employee_id')}
    user_map = _get_user_map(request, user_ids)

    items = [{
        "sotrudnik_id": row["employee_id"],
        "date_reflection": row["date_reflection"],
        "source_created_at": row["source_created_at"],
        "created_at": row["created_at"],
    } for row in rows]

    report_service = ReportService()
    report = report_service.generate_time_entry_discipline(items, user_map)
    return JsonResponse(report)


@xframe_options_exempt
@require_GET
@log_errors("report_focus_analysis")
@auth_required
def report_focus_analysis(request: AuthorizedRequest):
    queryset = _get_filtered_timesheet_queryset(request)
    rows = list(queryset.values(
        'employee_id',
        'project_title',
        'task_id',
        'hours',
    ))

    user_ids = {row['employee_id'] for row in rows if row.get('employee_id')}
    user_map = _get_user_map(request, user_ids)

    items = [{
        "sotrudnik_id": row["employee_id"],
        "project_name": row["project_title"],
        "task_id": row["task_id"],
        "kolichestvo_chasov": row["hours"],
    } for row in rows]

    report_service = ReportService()
    report = report_service.generate_focus_analysis(items, user_map)
    return JsonResponse(report)


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
    queryset = TimesheetItem.objects.filter(bitrix24_account=request.bitrix24_account).order_by('-created_at', '-bitrix_id')

    # Filter by record creation date (created_at)
    created_from = request.GET.get('created_from')
    created_to = request.GET.get('created_to')
    if created_from:
        queryset = queryset.filter(created_at__date__gte=created_from)
    if created_to:
        queryset = queryset.filter(created_at__date__lte=created_to)

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
@csrf_exempt
@require_POST
@log_errors("create_smart_process")
@auth_required
def create_smart_process(request: AuthorizedRequest):
    """Create a new Smart Process from settings page."""
    try:
        service = InstallationService(request.bitrix24_account.client, request.bitrix24_account)
        config = service.create_smart_process_only()
        return JsonResponse({"status": "success", "config": config})
    except InstallationError as e:
        return JsonResponse({"error": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"error": f"Unexpected error: {str(e)}"}, status=500)


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("create_fields")
@auth_required
def create_fields(request: AuthorizedRequest):
    """Create all required fields in the selected Smart Process."""
    import json as json_module
    try:
        body = json_module.loads(request.body)
        sp_id = body.get('entityTypeId')
        if not sp_id:
            return JsonResponse({"error": "Не указан ID смарт-процесса"}, status=400)

        service = InstallationService(request.bitrix24_account.client, request.bitrix24_account)
        config = service.create_fields_only(int(sp_id))
        return JsonResponse({"status": "success", "config": config})
    except InstallationError as e:
        return JsonResponse({"error": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"error": f"Unexpected error: {str(e)}"}, status=500)


@xframe_options_exempt
@require_GET
@log_errors("report_daily_workload")
@auth_required
def report_daily_workload(request: AuthorizedRequest):
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    # Defaults for date if missing (current month)
    from datetime import date
    if not date_from:
        today = date.today()
        date_from = date(today.year, today.month, 1).isoformat()
    if not date_to:
        today = date.today()
        date_to = today.isoformat()

    queryset = _get_filtered_timesheet_queryset(request)
    queryset = queryset.filter(date_reflection__date__gte=date_from, date_reflection__date__lte=date_to)

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
@csrf_exempt
@require_POST
@log_errors("export_raw_data")
@auth_required
def export_raw_data(request: AuthorizedRequest):
    """
    Export raw CRM items from Bitrix24 Smart Process to Excel.
    Accepts JSON body with: date_from, date_to, date_type ('creation' or 'reflection'), fields (list of field IDs).
    - Employee fields are resolved to "Lastname Firstname" format.
    - All values are written as strings (number_format='@') to prevent type coercion.
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, Exception):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    date_from = body.get("date_from", "")
    date_to = body.get("date_to", "")
    date_type = body.get("date_type", "reflection")  # 'creation' or 'reflection'
    selected_fields = body.get("fields", [])

    # Load configuration to get entity_type_id and field mapping
    config_service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    config = config_service.get_configuration_sync()

    entity_type_id = config.get("sp_entity_type_id", 0)
    if not entity_type_id:
        return JsonResponse({"error": "Смарт-процесс не настроен. Перейдите в Настройки и выберите смарт-процесс."}, status=400)

    # Get field definitions for header names and type info
    # Wrapped in try/except: if crm.item.fields fails it should not kill the whole export
    try:
        fields_meta = config_service.get_sp_fields_sync(int(entity_type_id))
    except Exception as e:
        import traceback
        return JsonResponse(
            {"error": f"Ошибка при получении полей смарт-процесса: {str(e)}",
             "trace": traceback.format_exc()},
            status=500
        )

    field_labels = {f["id"]: f["title"] for f in fields_meta}

    # Identify employee-type fields so we can resolve IDs to names later
    employee_field_ids = {f["id"] for f in fields_meta if f.get("type") == "employee"}

    # If no specific fields requested, take all available
    if not selected_fields:
        selected_fields = [f["id"] for f in fields_meta]

    # Build Bitrix24 filter based on date_type
    crm_filter = {}
    # FIX: frontend sends "creation", not "created"
    if date_type == "creation":
        date_field_from = ">=CREATED_TIME"
        date_field_to = "<=CREATED_TIME"
    else:
        # FIX: the reflection date field key in config is "data", not "date_reflection"
        fields_mapping = config.get("fields_mapping", {})
        reflection_field = fields_mapping.get("data", "CREATED_TIME")
        date_field_from = f">={reflection_field}"
        date_field_to = f"<={reflection_field}"

    if date_from:
        crm_filter[date_field_from] = date_from
    if date_to:
        crm_filter[date_field_to] = date_to

    # Fetch all items with pagination
    all_items = []
    start = 0
    page_size = 50

    while True:
        try:
            response = request.bitrix24_account.client._bitrix_token.call_method(
                "crm.item.list",
                {
                    "entityTypeId": int(entity_type_id),
                    "filter": crm_filter,
                    "select": selected_fields if selected_fields else ["*"],
                    "start": start,
                }
            )
            # BUG FIX #3: Bitrix24 returns 'total' at the TOP level of the response,
            # not inside 'result'. Must read from raw response before it's unpacked.
            result = response.get("result", {})
            items = result.get("items", [])
            all_items.extend(items)

            # total is at root level for crm.item.list
            total = response.get("total", result.get("total", 0))
            start += page_size
            # BUG FIX #4: also stop if we got fewer items than page_size (last page)
            if not items or len(items) < page_size or start >= total:
                break
        except Exception as e:
            import traceback
            return JsonResponse({"error": f"Ошибка при получении данных из Bitrix24: {str(e)}", "trace": traceback.format_exc()}, status=500)

    # --- Resolve employee IDs to names ---
    user_map = {}  # {str(user_id): "Фамилия Имя"}

    # Collect unique user IDs only from employee fields that were selected
    selected_employee_fields = [fid for fid in selected_fields if fid in employee_field_ids]
    user_ids_to_fetch = set()
    for item in all_items:
        for fid in selected_employee_fields:
            val = item.get(fid)
            if isinstance(val, list):
                for v in val:
                    if v:
                        user_ids_to_fetch.add(str(v))
            elif val:
                user_ids_to_fetch.add(str(val))

    # Fetch user names via user.get with FILTER (uppercase) — proven approach from BitrixDataService
    # user.get accepts an array of IDs in FILTER[ID], returns list of user objects in result
    if user_ids_to_fetch:
        uid_list = list(user_ids_to_fetch)
        BATCH_SIZE = 50
        for i in range(0, len(uid_list), BATCH_SIZE):
            chunk = uid_list[i:i + BATCH_SIZE]
            try:
                user_response = request.bitrix24_account.client._bitrix_token.call_method(
                    "user.get",
                    {"FILTER": {"ID": chunk}}
                )
                users = user_response.get("result", [])
                for u in users:
                    if not isinstance(u, dict):
                        continue
                    uid = str(u.get("ID", ""))
                    # Format: "Фамилия Имя" (without patronymic)
                    parts = [u.get("LAST_NAME", ""), u.get("NAME", "")]
                    name = " ".join(p for p in parts if p).strip()
                    if uid:
                        user_map[uid] = name if name else uid
            except Exception:
                # Non-critical: fall back to showing raw IDs
                pass

    def resolve_employee(val) -> str:
        """Convert employee field value to human-readable name string."""
        if isinstance(val, list):
            names = [user_map.get(str(v), str(v)) for v in val if v is not None]
            return "; ".join(names)
        elif val is not None:
            return user_map.get(str(val), str(val))
        return ""

    # --- Build Excel workbook ---
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Сырые данные"

    header_font = Font(bold=True)
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # Write headers
    headers = [field_labels.get(fid, fid) for fid in selected_fields]
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=str(header))
        cell.font = header_font
        cell.alignment = header_alignment

    # Write data rows — all values as strings, employee fields resolved to names
    for row_idx, item in enumerate(all_items, start=2):
        for col_idx, fid in enumerate(selected_fields, start=1):
            raw_value = item.get(fid, "")

            # Resolve employee fields to names
            if fid in employee_field_ids:
                str_value = resolve_employee(raw_value)
            elif isinstance(raw_value, (list, dict)):
                str_value = json.dumps(raw_value, ensure_ascii=False)
            elif raw_value is None:
                str_value = ""
            else:
                str_value = str(raw_value)

            cell = ws.cell(row=row_idx, column=col_idx, value=str_value)
            # Force Excel to treat the cell as text (prevents large numbers → scientific notation)
            cell.number_format = '@'

    # Auto-adjust column widths
    for col in ws.columns:
        max_len: int = 0
        for cell in col:
            if cell.value:
                max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[col[0].column_letter].width = min(int(max_len) + 4, 50)

    # Return as HTTP response with Excel content type
    import io
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    response = HttpResponse(
        output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = "attachment; filename=raw_data_export.xlsx"
    return response


@xframe_options_exempt
@csrf_exempt
def serve_spa(request):
    """
    Serve index.html for any route (GET or POST) to support Bitrix24 iframe loading and SPA navigation.
    """
    print(f"DEBUG: serve_spa view called. Method: {request.method} Path: {request.path}")
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
