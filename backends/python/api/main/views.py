from collections import defaultdict

from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponse
from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.clickjacking import xframe_options_exempt

from .utils.decorators import admin_required, auth_required, log_errors, rate_limit
from .utils.decorators.sync_lock import sync_lock, account_sync_lock, SyncLockBusy
from .utils import AuthorizedRequest
from .models import ApplicationInstallation, TimesheetItem, RequestLog, SystemLog, ProjectCard

import logging
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
    invalidate_project_runtime_caches,
)
from .installation_service import InstallationService, InstallationError
from .perf import ReportProfiler
from .report_queries import (
    TREE_REPORT_FIELDS,
    build_filtered_timesheet_queryset,
    build_project_title_lookups,
    build_tree_report_items,
    materialize_rows,
    resolve_project_name_for_row,
)
from .report_excel import (
    build_project_task_workbook,
    build_hierarchy_workbook,
    build_matrix_workbook,
    build_table_workbook,
    _safe_cell_text,
)
from .inn_backfill_service import InnBackfillService

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
    "get_support_status",
    "connect_support_line",
    "get_project_board",
    "get_project_board_meta",
    "get_project_board_card",
    "sync_project_board",
    "update_project_board",
    "update_project_board_stage",
    "archive_project_board",
    "run_project_board_daily_check",
    "get_project_board_companies",
    "get_homepage_portfolio",
    "get_internal_lists",
    "report_employee_project",
    "report_project_employee",
    "report_daily_workload",
    "report_project_task_employee",
    "report_project_task_employee_export",
    "report_employee_project_export",
    "report_project_employee_export",
    "report_daily_workload_export",
    "report_revenue_leakage_export",
    "report_time_entry_discipline_export",
    "report_focus_analysis_export",
    "inn_backfill_scan",
    "inn_backfill_apply",
    "inn_backfill_project_items",
    "projects_health",
    "report_revenue_leakage",
    "report_time_entry_discipline",
    "report_focus_analysis",
    "timesheet_sync",
    "timesheet_list",
    "get_configuration",
    "save_configuration",
    "get_smart_processes",
    "get_sp_fields",
    "get_project_spa_validation",
    "get_project_spa_stages",
    "run_project_spa_backfill",
    "get_request_logs",
    "get_system_logs",
    "create_smart_process",
    "create_fields",
    "create_mapped_field",
    "export_raw_data",
]

config = load_config()
logger = logging.getLogger(__name__)


def _get_filtered_timesheet_queryset(request: AuthorizedRequest):
    return build_filtered_timesheet_queryset(
        request.bitrix24_account,
        {
            "date_from": request.GET.get("date_from"),
            "date_to": request.GET.get("date_to"),
            "employee_ids[]": request.GET.getlist("employee_ids[]"),
            "project_ids[]": request.GET.getlist("project_ids[]"),
            "employee_mode": request.GET.get("employee_mode", "include"),
            "project_mode": request.GET.get("project_mode", "include"),
        },
    )


def _get_user_map(request: AuthorizedRequest, user_ids):
    if not user_ids:
        return {}

    config_service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    config = config_service.get_configuration_sync()
    data_service = BitrixDataService(request.bitrix24_account.client, config, request.bitrix24_account)
    return data_service.fetch_users(list(user_ids))


def _get_data_service(request: AuthorizedRequest):
    config_service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    config = config_service.get_configuration_sync()
    return BitrixDataService(request.bitrix24_account.client, config, request.bitrix24_account)


def _build_employee_filter_options(request: AuthorizedRequest):
    data_service = _get_data_service(request)
    return data_service.fetch_active_users()


def _build_project_filter_options(request: AuthorizedRequest):
    queryset = TimesheetItem.objects.filter(bitrix24_account=request.bitrix24_account)
    active_project_rows = list(
        get_project_card_queryset(request.bitrix24_account)
        .filter(is_archived=False)
        .values("project_id", "project_name")
    )
    active_project_ids = {row["project_id"] for row in active_project_rows if row.get("project_id")}
    active_project_names = {row["project_name"] for row in active_project_rows if row.get("project_name")}
    projs = queryset.values("project_id", "project_title").distinct()
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


PROJECT_SPA_REQUIRED_MAPPING = {
    "title": "string",
    "bitrix_group_id": "project_identifier",
    "stage_id": "stage",
    "is_support": "boolean",
    "project_hours_budget": "double",
    "hourly_rate": "double",
    "curator_id": "employee",
    "company_id": "crm_company",
    "our_legal_entity_id": "crm_company",
    "start_date": "date",
    "finish_date": "date",
    "is_archived": "boolean",
}

PROJECT_SPA_TYPE_ALIASES = {
    "string": {"string", "text", "char"},
    "integer": {"integer", "int"},
    "double": {"double", "float", "money"},
    "boolean": {"boolean", "bool"},
    "employee": {"employee", "user", "crm_status"},
    "crm_company": {"crm_company", "crm", "string"},
    "date": {"date", "datetime"},
    "project_identifier": {"integer", "int", "string", "text", "char"},
    "stage": {"string", "text", "char", "crm_status", "status"},
}


def _normalize_field_type(value):
    if value is None:
        return ""
    return str(value).strip().lower()


def _is_project_field_type_compatible(expected_type, actual_type):
    actual = _normalize_field_type(actual_type)
    expected_aliases = PROJECT_SPA_TYPE_ALIASES.get(expected_type, {expected_type})
    return actual in expected_aliases


def _collect_project_spa_linkage_issues(sync_service: ProjectSyncService, entity_type_id: int, project_mapping: dict):
    items = sync_service.fetch_project_sp_items(entity_type_id)
    normalized = [
        sync_service.normalize_project_item(item, project_mapping, {}, {}, {})
        for item in items
    ]

    duplicate_map = defaultdict(set)
    duplicate_item_map = defaultdict(set)
    missing_group_link_count = 0
    for item in normalized:
        bitrix_group_id = str(item.get("project_id") or "").strip()
        project_item_id = str(item.get("project_item_id") or "").strip()
        if not bitrix_group_id:
            missing_group_link_count += 1
            continue
        if project_item_id:
            duplicate_map[bitrix_group_id].add(project_item_id)
            duplicate_item_map[project_item_id].add(bitrix_group_id)

    duplicate_links = [
        {
            "bitrix_group_id": group_id,
            "project_item_ids": sorted(project_item_ids),
        }
        for group_id, project_item_ids in duplicate_map.items()
        if len(project_item_ids) > 1
    ]
    duplicate_item_links = [
        {
            "project_item_id": project_item_id,
            "bitrix_group_ids": sorted(group_ids),
        }
        for project_item_id, group_ids in duplicate_item_map.items()
        if len(group_ids) > 1
    ]

    return {
        "total_items": len(normalized),
        "missing_group_link_count": missing_group_link_count,
        "duplicate_group_link_count": len(duplicate_links),
        "duplicate_group_links": duplicate_links,
        "duplicate_project_item_link_count": len(duplicate_item_links),
        "duplicate_project_item_links": duplicate_item_links,
    }


def _build_project_spa_validation_payload(
    config_service: ConfigurationService,
    account,
    config: dict,
):
    config = config_service.normalize_configuration_sync(config)
    try:
        entity_type_id = int(config.get("project_sp_entity_type_id") or 0)
    except (TypeError, ValueError):
        entity_type_id = 0
    project_mapping = config.get("project_fields_mapping") or {}
    if not isinstance(project_mapping, dict):
        project_mapping = {}

    required_keys = list(PROJECT_SPA_REQUIRED_MAPPING.keys())
    missing_mapping_keys = []
    missing_fields_in_sp = []
    type_mismatches = []
    warnings = []
    access_error = None
    write_access_error = None
    linkage_issues = {
        "total_items": 0,
        "missing_group_link_count": 0,
        "duplicate_group_link_count": 0,
        "duplicate_group_links": [],
        "duplicate_project_item_link_count": 0,
        "duplicate_project_item_links": [],
    }

    if not entity_type_id:
        return {
            "is_configured": False,
            "is_valid": False,
            "entity_type_id": 0,
            "required_mapping_keys": required_keys,
            "missing_mapping_keys": required_keys,
            "missing_fields_in_sp": [],
            "type_mismatches": [],
            "access_error": "Не выбран Смарт-процесс ПРОЕКТ в настройках.",
            "write_access_error": "Не выбран Смарт-процесс ПРОЕКТ в настройках.",
            "warnings": ["Project SPA не настроен."],
            "linkage_issues": linkage_issues,
        }

    fields_meta = config_service.get_sp_fields_sync(entity_type_id)
    fields_by_id = {str(field.get("id") or ""): field for field in fields_meta if field.get("id")}
    fields_by_id_lower = {key.lower(): value for key, value in fields_by_id.items()}

    for mapping_key, expected_type in PROJECT_SPA_REQUIRED_MAPPING.items():
        mapped_field = str(project_mapping.get(mapping_key) or "").strip()
        if not mapped_field:
            missing_mapping_keys.append(mapping_key)
            continue

        field_meta = fields_by_id.get(mapped_field) or fields_by_id_lower.get(mapped_field.lower())
        if not field_meta:
            missing_fields_in_sp.append({"key": mapping_key, "mapped_field": mapped_field})
            continue

        actual_type = field_meta.get("type")
        if not _is_project_field_type_compatible(expected_type, actual_type):
            type_mismatches.append(
                {
                    "key": mapping_key,
                    "mapped_field": mapped_field,
                    "expected_type": expected_type,
                    "actual_type": _normalize_field_type(actual_type),
                }
            )

    try:
        account.client._bitrix_token.call_method(
            "crm.item.list",
            {"entityTypeId": entity_type_id, "select": ["id"], "start": 0},
        )
    except Exception as exc:
        access_error = str(exc)

    try:
        sample_items_response = account.client._bitrix_token.call_method(
            "crm.item.list",
            {"entityTypeId": entity_type_id, "select": ["id", "title"], "start": 0},
        )
        sample_items = sample_items_response.get("result", [])
        if isinstance(sample_items, dict):
            sample_items = sample_items.get("items") or sample_items.get("result") or []
        sample_id = None
        for row in sample_items or []:
            sample_id = row.get("id") or row.get("ID")
            if sample_id:
                break
        if sample_id:
            account.client._bitrix_token.call_method(
                "crm.item.update",
                {
                    "entityTypeId": entity_type_id,
                    "id": int(sample_id) if str(sample_id).isdigit() else sample_id,
                    "fields": {},
                },
            )
        else:
            warnings.append("Права на обновление не проверены: в Project SPA нет элементов для no-op update.")
    except Exception as exc:
        exc_text = str(exc)
        benign_markers = ("fields", "empty", "пуст")
        if any(marker in exc_text.lower() for marker in benign_markers):
            warnings.append("Права на обновление подтверждены частично: no-op update не принял пустой payload.")
        else:
            write_access_error = exc_text

    try:
        sync_service = ProjectSyncService(account.client, account)
        linkage_issues = _collect_project_spa_linkage_issues(sync_service, entity_type_id, project_mapping)
    except Exception as exc:
        warnings.append(f"Не удалось проверить связность Project SPA: {exc}")

    if linkage_issues["missing_group_link_count"] > 0:
        warnings.append(
            f"Есть проекты без bitrix_group_id: {linkage_issues['missing_group_link_count']}."
        )
    if linkage_issues["duplicate_group_link_count"] > 0:
        warnings.append(
            f"Есть конфликты group_id -> project_item_id: {linkage_issues['duplicate_group_link_count']}."
        )
    if linkage_issues["duplicate_project_item_link_count"] > 0:
        warnings.append(
            f"Есть конфликты project_item_id -> group_id: {linkage_issues['duplicate_project_item_link_count']}."
        )

    is_valid = (
        not missing_mapping_keys
        and not missing_fields_in_sp
        and not type_mismatches
        and access_error is None
        and write_access_error is None
    )

    return {
        "is_configured": True,
        "is_valid": is_valid,
        "entity_type_id": entity_type_id,
        "required_mapping_keys": required_keys,
        "missing_mapping_keys": missing_mapping_keys,
        "missing_fields_in_sp": missing_fields_in_sp,
        "type_mismatches": type_mismatches,
        "access_error": access_error,
        "write_access_error": write_access_error,
        "warnings": warnings,
        "linkage_issues": linkage_issues,
    }


def _load_request_json(request: AuthorizedRequest):
    try:
        return json.loads(request.body or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _apply_created_at_filters(queryset, created_from, created_to):
    from datetime import date, datetime, time, timedelta

    current_tz = timezone.get_current_timezone()

    def parse_date(raw_value):
        if not raw_value:
            return None
        try:
            return date.fromisoformat(str(raw_value)[:10])
        except (TypeError, ValueError):
            return None

    parsed_from = parse_date(created_from)
    parsed_to = parse_date(created_to)

    if parsed_from:
        queryset = queryset.filter(created_at__gte=timezone.make_aware(datetime.combine(parsed_from, time.min), current_tz))
    if parsed_to:
        next_day = parsed_to + timedelta(days=1)
        queryset = queryset.filter(created_at__lt=timezone.make_aware(datetime.combine(next_day, time.min), current_tz))
    return queryset


def _serialize_support_status(payload):
    return {
        "configured": bool(payload.get("configured")),
        "code": payload.get("code") or "",
        "status": payload.get("status") or "not_connected",
        "dialog_id": payload.get("dialog_id") or "",
        "connected_at": payload.get("connected_at"),
        "error": payload.get("error") or "",
    }


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


def _refresh_admin_flag(account) -> None:
    """Refresh ``account.is_b24_user_admin`` from the Bitrix ``user.admin`` method.

    Called from the auth/install flow once the account token is available. A
    failed Bitrix call must NOT break authentication — the previous value is kept
    and only a warning is logged.
    """
    try:
        response = account.client._bitrix_token.call_method("user.admin", {})
        is_admin = bool(response.get("result") if isinstance(response, dict) else response)

        if account.is_b24_user_admin != is_admin:
            account.is_b24_user_admin = is_admin
            account.save(update_fields=["is_b24_user_admin"])
    except Exception:
        logger.warning("Could not refresh is_b24_user_admin via user.admin for account %s", account.pk, exc_info=True)


@xframe_options_exempt
@csrf_exempt
@log_errors("install")
def install(request):
    """
    Handle Bitrix24 application installation.
    Supports HEAD/GET for Marketplace validation.
    """
    logger.info("Install view called. Method=%s Path=%s", request.method, request.path)
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

    _refresh_admin_flag(bitrix24_account)

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
        support = _serialize_support_status(service.get_support_line_status())
        return JsonResponse({"message": "Installation successful", "config": config, "support": support})
    except InstallationError as e:
        return JsonResponse({"error": str(e)}, status=500)
    except Exception:
        logger.exception("Unexpected error during installation")
        return JsonResponse({"error": "Внутренняя ошибка сервера"}, status=500)


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("get_token")
@rate_limit("get_token", 10, 60, key="ip_domain")
@auth_required
def get_token(request: AuthorizedRequest):
    _refresh_admin_flag(request.bitrix24_account)
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
@log_errors("get_support_status")
@auth_required
def get_support_status(request: AuthorizedRequest):
    service = InstallationService(request.bitrix24_account.client, request.bitrix24_account)
    return JsonResponse(_serialize_support_status(service.get_support_line_status()))


@xframe_options_exempt
@require_POST
@log_errors("connect_support_line")
@auth_required
def connect_support_line(request: AuthorizedRequest):
    service = InstallationService(request.bitrix24_account.client, request.bitrix24_account)
    payload = _serialize_support_status(service.connect_support_line_sync(force=True))
    return JsonResponse(payload)


@xframe_options_exempt
@require_GET
@log_errors("get_project_board")
@auth_required
def get_project_board(request: AuthorizedRequest):
    service = ProjectCardService(request.bitrix24_account.client, request.bitrix24_account)
    return JsonResponse(service.get_board_data())


@xframe_options_exempt
@require_GET
@log_errors("get_project_board_meta")
@auth_required
def get_project_board_meta(request: AuthorizedRequest):
    service = ProjectCardService(request.bitrix24_account.client, request.bitrix24_account)
    return JsonResponse(service.get_meta())


@xframe_options_exempt
@require_GET
@log_errors("get_project_board_card")
@auth_required
def get_project_board_card(request: AuthorizedRequest):
    project_id = str(request.GET.get("project_id") or "").strip()
    if not project_id:
        return JsonResponse({"error": "project_id is required"}, status=400)

    service = ProjectCardService(request.bitrix24_account.client, request.bitrix24_account)

    try:
        return JsonResponse({"card": service.get_card_data(project_id)})
    except ProjectCard.DoesNotExist:
        # "Карточки ещё нет" — не ошибка сервера, а валидное состояние:
        # для задач/групп без синхронизированного ProjectCard placement просто не показывает блок.
        # Возвращаем 200 с null, чтобы ofetch на фронте не бросал FetchError и не блокировал
        # нативное списание времени в Битрикс24.
        return JsonResponse({"card": None})
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@xframe_options_exempt
@require_GET
@log_errors("get_project_board_companies")
@auth_required
def get_project_board_companies(request: AuthorizedRequest):
    service = ProjectCardService(request.bitrix24_account.client, request.bitrix24_account)
    return JsonResponse({"companies": service.get_companies()})


@xframe_options_exempt
@require_GET
@log_errors("get_homepage_portfolio")
@auth_required
def get_homepage_portfolio(request: AuthorizedRequest):
    service = ProjectCardService(request.bitrix24_account.client, request.bitrix24_account)
    return JsonResponse(service.get_homepage_snapshot())


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("sync_project_board")
@auth_required
@admin_required
@rate_limit("sync", 6, 60, key="account")
@sync_lock("project")
def sync_project_board(request: AuthorizedRequest):
    service = ProjectSyncService(request.bitrix24_account.client, request.bitrix24_account)
    incremental_raw = request.GET.get("incremental_since_minutes")
    incremental_since_minutes = None
    if incremental_raw:
        try:
            incremental_since_minutes = int(incremental_raw)
        except (TypeError, ValueError):
            return JsonResponse({"error": "incremental_since_minutes must be integer"}, status=400)
    try:
        return JsonResponse(service.sync(incremental_since_minutes=incremental_since_minutes))
    except Exception:
        logger.exception("Project board sync failed for account %s", request.bitrix24_account.pk)
        return JsonResponse(
            {
                "status": "warning",
                "sync_mode": "failed",
                "synced": 0,
                "created": 0,
                "updated": 0,
                "skipped_missing_group_link": 0,
                "skipped_conflict_linking": 0,
                "warning": (
                    "Синхронизацию проектов выполнить не удалось. "
                    "Показаны последние сохраненные данные."
                ),
            }
        )


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("run_project_spa_backfill")
@auth_required
@admin_required
def run_project_spa_backfill(request: AuthorizedRequest):
    service = ProjectSyncService(request.bitrix24_account.client, request.bitrix24_account)
    return JsonResponse(service.backfill_timesheet_project_items())


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("update_project_board")
@auth_required
@admin_required
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
@admin_required
def update_project_board_stage(request: AuthorizedRequest):
    payload = _load_request_json(request)
    project_id = payload.get("project_id")
    stage = payload.get("stage")

    if not project_id or not stage:
        return JsonResponse({"error": "project_id and stage are required"}, status=400)

    service = ProjectCardService(request.bitrix24_account.client, request.bitrix24_account)

    try:
        result = service.update_stage(str(project_id), str(stage))
        return JsonResponse(result)
    except ProjectCard.DoesNotExist:
        return JsonResponse({"error": "Проект не найден"}, status=404)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("archive_project_board")
@auth_required
@admin_required
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
@admin_required
def run_project_board_daily_check(request: AuthorizedRequest):
    service = ProjectStageAutomationService(request.bitrix24_account)
    return JsonResponse(service.run_daily_check())


@xframe_options_exempt
@require_GET
@log_errors("report_employee_project")
@auth_required
@admin_required
def report_employee_project(request: AuthorizedRequest):
    profiler = ReportProfiler("report_employee_project", account_id=request.bitrix24_account.pk)
    with profiler.stage("queryset_build"):
        queryset = _get_filtered_timesheet_queryset(request)
    with profiler.stage("materialize"):
        rows = materialize_rows(queryset, TREE_REPORT_FIELDS)
    user_ids = {row["employee_id"] for row in rows if row.get("employee_id")}
    with profiler.stage("user_map"):
        user_map = _get_user_map(request, user_ids)
    with profiler.stage("project_lookup"):
        project_name_by_item, project_name_by_group = build_project_title_lookups(request.bitrix24_account)
    with profiler.stage("build_items"):
        items = build_tree_report_items(
            rows,
            project_name_by_item=project_name_by_item,
            project_name_by_group=project_name_by_group,
        )
    with profiler.stage("service_generate"):
        report_service = ReportService()
        report = report_service.generate_employee_projects(items, user_map)
    profiler.set_metric("rows", len(rows))
    profiler.set_metric("users", len(user_ids))
    with profiler.stage("serialize"):
        response = JsonResponse(report, safe=False)
    profiler.attach_to_response(response)
    profiler.log()
    return response


@xframe_options_exempt
@require_GET
@log_errors("report_project_employee")
@auth_required
@admin_required
def report_project_employee(request: AuthorizedRequest):
    profiler = ReportProfiler("report_project_employee", account_id=request.bitrix24_account.pk)
    with profiler.stage("queryset_build"):
        queryset = _get_filtered_timesheet_queryset(request)
    with profiler.stage("materialize"):
        rows = materialize_rows(queryset, TREE_REPORT_FIELDS)
    user_ids = {row["employee_id"] for row in rows if row.get("employee_id")}
    with profiler.stage("user_map"):
        user_map = _get_user_map(request, user_ids)
    with profiler.stage("project_lookup"):
        project_name_by_item, project_name_by_group = build_project_title_lookups(request.bitrix24_account)
    with profiler.stage("build_items"):
        items = build_tree_report_items(
            rows,
            project_name_by_item=project_name_by_item,
            project_name_by_group=project_name_by_group,
        )
    with profiler.stage("service_generate"):
        report_service = ReportService()
        report = report_service.generate_project_employees(items, user_map)
    profiler.set_metric("rows", len(rows))
    profiler.set_metric("users", len(user_ids))
    with profiler.stage("serialize"):
        response = JsonResponse(report, safe=False)
    profiler.attach_to_response(response)
    profiler.log()
    return response

@xframe_options_exempt
@require_GET
@log_errors("report_project_task_employee")
@auth_required
@admin_required
def report_project_task_employee(request: AuthorizedRequest):
    """Report: Project -> Task Hierarchy -> Employee -> Items"""
    profiler = ReportProfiler("report_project_task_employee", account_id=request.bitrix24_account.pk)
    with profiler.stage("queryset_build"):
        queryset = _get_filtered_timesheet_queryset(request)
    with profiler.stage("materialize"):
        rows = materialize_rows(queryset, TREE_REPORT_FIELDS)
    user_ids = {row["employee_id"] for row in rows if row.get("employee_id")}
    with profiler.stage("user_map"):
        user_map = _get_user_map(request, user_ids)
    with profiler.stage("project_lookup"):
        project_name_by_item, project_name_by_group = build_project_title_lookups(request.bitrix24_account)
    with profiler.stage("build_items"):
        items = build_tree_report_items(
            rows,
            include_task_id=True,
            project_name_by_item=project_name_by_item,
            project_name_by_group=project_name_by_group,
        )
    with profiler.stage("service_generate"):
        report_service = ReportService()
        report = report_service.generate_project_task_employees(items, user_map)
    profiler.set_metric("rows", len(rows))
    profiler.set_metric("users", len(user_ids))
    with profiler.stage("serialize"):
        response = JsonResponse(report, safe=False)
    profiler.attach_to_response(response)
    profiler.log()
    return response


@xframe_options_exempt
@require_GET
@log_errors("report_project_task_employee_export")
@auth_required
@admin_required
@rate_limit("export", 12, 60, key="account")
def report_project_task_employee_export(request: AuthorizedRequest):
    """Excel-выгрузка отчёта «Учет по проектам/задачам» с сохранением иерархии."""
    queryset = _get_filtered_timesheet_queryset(request)
    rows = materialize_rows(queryset, TREE_REPORT_FIELDS)
    user_ids = {row["employee_id"] for row in rows if row.get("employee_id")}
    user_map = _get_user_map(request, user_ids)
    project_name_by_item, project_name_by_group = build_project_title_lookups(request.bitrix24_account)
    items = build_tree_report_items(
        rows,
        include_task_id=True,
        project_name_by_item=project_name_by_item,
        project_name_by_group=project_name_by_group,
    )
    report = ReportService().generate_project_task_employees(items, user_map)

    date_from = request.GET.get("date_from") or ""
    date_to = request.GET.get("date_to") or ""
    output = build_project_task_workbook(report, date_from=date_from, date_to=date_to)

    suffix = f"_{date_from}_{date_to}".strip("_")
    filename = f"report_project_task{('_' + suffix) if suffix else ''}.xlsx".replace("__", "_")
    response = HttpResponse(
        output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@xframe_options_exempt
@require_GET
@log_errors("report_employee_project_export")
@auth_required
@admin_required
@rate_limit("export", 12, 60, key="account")
def report_employee_project_export(request: AuthorizedRequest):
    """Excel-выгрузка отчёта «По сотрудникам/проектам» с сохранением иерархии."""
    queryset = _get_filtered_timesheet_queryset(request)
    rows = materialize_rows(queryset, TREE_REPORT_FIELDS)
    user_ids = {row["employee_id"] for row in rows if row.get("employee_id")}
    user_map = _get_user_map(request, user_ids)
    project_name_by_item, project_name_by_group = build_project_title_lookups(request.bitrix24_account)
    items = build_tree_report_items(
        rows,
        project_name_by_item=project_name_by_item,
        project_name_by_group=project_name_by_group,
    )
    roots = ReportService().generate_employee_projects(items, user_map)

    date_from = request.GET.get("date_from") or ""
    date_to = request.GET.get("date_to") or ""
    output = build_hierarchy_workbook(roots, title="Отчет по сотрудникам",
                                      date_from=date_from, date_to=date_to)

    response = HttpResponse(
        output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="report_employee_project.xlsx"'
    return response


@xframe_options_exempt
@require_GET
@log_errors("report_project_employee_export")
@auth_required
@admin_required
@rate_limit("export", 12, 60, key="account")
def report_project_employee_export(request: AuthorizedRequest):
    """Excel-выгрузка отчёта «По проектам/сотрудникам» с сохранением иерархии."""
    queryset = _get_filtered_timesheet_queryset(request)
    rows = materialize_rows(queryset, TREE_REPORT_FIELDS)
    user_ids = {row["employee_id"] for row in rows if row.get("employee_id")}
    user_map = _get_user_map(request, user_ids)
    project_name_by_item, project_name_by_group = build_project_title_lookups(request.bitrix24_account)
    items = build_tree_report_items(
        rows,
        project_name_by_item=project_name_by_item,
        project_name_by_group=project_name_by_group,
    )
    roots = ReportService().generate_project_employees(items, user_map)

    date_from = request.GET.get("date_from") or ""
    date_to = request.GET.get("date_to") or ""
    output = build_hierarchy_workbook(roots, title="Отчет по проектам",
                                      date_from=date_from, date_to=date_to)

    response = HttpResponse(
        output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="report_project_employee.xlsx"'
    return response


@xframe_options_exempt
@require_GET
@log_errors("report_daily_workload_export")
@auth_required
@rate_limit("export", 12, 60, key="account")
def report_daily_workload_export(request: AuthorizedRequest):
    """Excel-выгрузка отчёта «Ежедневная нагрузка» в виде матрицы сотрудник×день."""
    from datetime import date
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    if not date_from:
        today = date.today()
        date_from = date(today.year, today.month, 1).isoformat()
    if not date_to:
        today = date.today()
        date_to = today.isoformat()

    queryset = build_filtered_timesheet_queryset(
        request.bitrix24_account,
        {
            "date_from": date_from,
            "date_to": date_to,
            "employee_ids[]": request.GET.getlist("employee_ids[]"),
            "project_ids[]": request.GET.getlist("project_ids[]"),
            "employee_mode": request.GET.get("employee_mode", "include"),
            "project_mode": request.GET.get("project_mode", "include"),
        },
    )
    project_name_by_item, project_name_by_group = build_project_title_lookups(request.bitrix24_account)
    rows = materialize_rows(
        queryset,
        (
            "employee_id",
            "project_item_id",
            "project_id",
            "project_title",
            "hours",
            "task_id",
            "task_hierarchy_titles",
            "description",
            "date_reflection",
        ),
    )
    user_ids = {row["employee_id"] for row in rows if row.get("employee_id")}
    user_map = _get_user_map(request, user_ids)
    items = [
        {
            "sotrudnik_id": row["employee_id"],
            "project_name": resolve_project_name_for_row(row, project_name_by_item, project_name_by_group),
            "kolichestvo_chasov": row["hours"],
            "id_zadachi": row["task_id"],
            "nazvanie_zadachi": row["task_hierarchy_titles"][-1] if row.get("task_hierarchy_titles") else "No Title",
            "opisanie": row["description"],
            "data": row["date_reflection"].isoformat() if row.get("date_reflection") else None,
        }
        for row in rows
    ]

    report = ReportService().generate_daily_workload(items, user_map, date_from, date_to)
    output = build_matrix_workbook(report["header_days"], report["rows"],
                                   title="Ежедневная нагрузка",
                                   date_from=date_from, date_to=date_to)

    response = HttpResponse(
        output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="report_daily_workload.xlsx"'
    return response


@xframe_options_exempt
@require_GET
@log_errors("report_revenue_leakage_export")
@auth_required
@admin_required
@rate_limit("export", 12, 60, key="account")
def report_revenue_leakage_export(request: AuthorizedRequest):
    """Excel-выгрузка отчёта «Потери выручки» в виде таблицы."""
    queryset = _get_filtered_timesheet_queryset(request)
    project_name_by_item, project_name_by_group = build_project_title_lookups(request.bitrix24_account)
    rows = list(queryset.values(
        'employee_id',
        'project_item_id',
        'project_id',
        'project_title',
        'hours',
        'is_billable',
    ))

    user_ids = {row['employee_id'] for row in rows if row.get('employee_id')}
    user_map = _get_user_map(request, user_ids)

    items = [{
        "sotrudnik_id": row["employee_id"],
        "project_name": resolve_project_name_for_row(row, project_name_by_item, project_name_by_group),
        "kolichestvo_chasov": row["hours"],
        "uchitivaem": row["is_billable"],
    } for row in rows]

    report = ReportService().generate_revenue_leakage(items, user_map)

    # Выгружаем risk_rows (детальные данные по рискам)
    table_rows = report.get("risk_rows", [])
    columns = [
        {"key": "project_name", "label": "Проект", "fmt": "text", "width": 25},
        {"key": "employee_name", "label": "Сотрудник", "fmt": "text", "width": 20},
        {"key": "total_hours", "label": "Всего часов", "fmt": "hours", "width": 14},
        {"key": "billable_hours", "label": "Учтено часов", "fmt": "hours", "width": 14},
        {"key": "non_billable_hours", "label": "Не учтено часов", "fmt": "hours", "width": 14},
        {"key": "loss_rate", "label": "Доля потерь, %", "fmt": "hours", "width": 14},
    ]

    date_from = request.GET.get("date_from") or ""
    date_to = request.GET.get("date_to") or ""
    output = build_table_workbook(columns, table_rows, title="Потери выручки",
                                  date_from=date_from, date_to=date_to)

    response = HttpResponse(
        output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="report_revenue_leakage.xlsx"'
    return response


@xframe_options_exempt
@require_GET
@log_errors("report_time_entry_discipline_export")
@auth_required
@rate_limit("export", 12, 60, key="account")
def report_time_entry_discipline_export(request: AuthorizedRequest):
    """Excel-выгрузка отчёта «Дисциплина внесения времени» в виде таблицы."""
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

    report = ReportService().generate_time_entry_discipline(items, user_map)

    # Выгружаем employee_rows (детальные данные по сотрудникам)
    table_rows = report.get("employee_rows", [])
    columns = [
        {"key": "employee_name", "label": "Сотрудник", "fmt": "text", "width": 20},
        {"key": "entry_count", "label": "Записей", "fmt": "int", "width": 12},
        {"key": "same_day_share", "label": "В день записи, доля", "fmt": "percent", "width": 16},
        {"key": "avg_lag_days", "label": "Средн. отставание, дней", "fmt": "hours", "width": 16},
        {"key": "late_entries", "label": "Запис. >1дня назад", "fmt": "int", "width": 14},
        {"key": "max_lag_days", "label": "Макс. отставание, дней", "fmt": "int", "width": 16},
        {"key": "risk_level", "label": "Уровень риска", "fmt": "text", "width": 14},
    ]

    date_from = request.GET.get("date_from") or ""
    date_to = request.GET.get("date_to") or ""
    output = build_table_workbook(columns, table_rows, title="Дисциплина внесения времени",
                                  date_from=date_from, date_to=date_to)

    response = HttpResponse(
        output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="report_time_entry_discipline.xlsx"'
    return response


@xframe_options_exempt
@require_GET
@log_errors("report_focus_analysis_export")
@auth_required
@rate_limit("export", 12, 60, key="account")
def report_focus_analysis_export(request: AuthorizedRequest):
    """Excel-выгрузка отчёта «Фокус и распыление» в виде таблицы."""
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

    report = ReportService().generate_focus_analysis(items, user_map)

    # Выгружаем employee_rows (детальные данные по сотрудникам)
    table_rows = report.get("employee_rows", [])
    columns = [
        {"key": "employee_name", "label": "Сотрудник", "fmt": "text", "width": 20},
        {"key": "project_count", "label": "Кол-во проектов", "fmt": "int", "width": 14},
        {"key": "task_count", "label": "Кол-во задач", "fmt": "int", "width": 14},
        {"key": "entry_count", "label": "Записей", "fmt": "int", "width": 12},
        {"key": "total_hours", "label": "Всего часов", "fmt": "hours", "width": 14},
        {"key": "avg_entry_hours", "label": "Средняя запись, ч", "fmt": "hours", "width": 14},
        {"key": "focus_index", "label": "Индекс фокуса", "fmt": "percent", "width": 14},
        {"key": "top_project_hours", "label": "Часов на топ проект", "fmt": "hours", "width": 16},
        {"key": "risk_level", "label": "Уровень риска", "fmt": "text", "width": 14},
    ]

    date_from = request.GET.get("date_from") or ""
    date_to = request.GET.get("date_to") or ""
    output = build_table_workbook(columns, table_rows, title="Фокус и распыление",
                                  date_from=date_from, date_to=date_to)

    response = HttpResponse(
        output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="report_focus_analysis.xlsx"'
    return response


@xframe_options_exempt
@require_GET
@log_errors("report_revenue_leakage")
@auth_required
@admin_required
def report_revenue_leakage(request: AuthorizedRequest):
    profiler = ReportProfiler("report_revenue_leakage", account_id=request.bitrix24_account.pk)
    with profiler.stage("queryset_build"):
        queryset = _get_filtered_timesheet_queryset(request)
    with profiler.stage("project_lookup"):
        project_name_by_item, project_name_by_group = build_project_title_lookups(request.bitrix24_account)
    with profiler.stage("materialize"):
        rows = list(queryset.values(
            'employee_id',
            'project_item_id',
            'project_id',
            'project_title',
            'hours',
            'is_billable',
        ))

    user_ids = {row['employee_id'] for row in rows if row.get('employee_id')}
    with profiler.stage("user_map"):
        user_map = _get_user_map(request, user_ids)

    with profiler.stage("build_items"):
        items = [{
            "sotrudnik_id": row["employee_id"],
            "project_name": resolve_project_name_for_row(row, project_name_by_item, project_name_by_group),
            "kolichestvo_chasov": row["hours"],
            "uchitivaem": row["is_billable"],
        } for row in rows]

    with profiler.stage("service_generate"):
        report_service = ReportService()
        report = report_service.generate_revenue_leakage(items, user_map)
    profiler.set_metric("rows", len(rows))
    profiler.set_metric("users", len(user_ids))
    with profiler.stage("serialize"):
        response = JsonResponse(report)
    profiler.attach_to_response(response)
    profiler.log()
    return response


@xframe_options_exempt
@require_GET
@log_errors("report_time_entry_discipline")
@auth_required
def report_time_entry_discipline(request: AuthorizedRequest):
    profiler = ReportProfiler("report_time_entry_discipline", account_id=request.bitrix24_account.pk)
    with profiler.stage("queryset_build"):
        queryset = _get_filtered_timesheet_queryset(request)
    with profiler.stage("materialize"):
        rows = list(queryset.values(
            'employee_id',
            'date_reflection',
            'source_created_at',
            'created_at',
        ))

    user_ids = {row['employee_id'] for row in rows if row.get('employee_id')}
    with profiler.stage("user_map"):
        user_map = _get_user_map(request, user_ids)

    with profiler.stage("build_items"):
        items = [{
            "sotrudnik_id": row["employee_id"],
            "date_reflection": row["date_reflection"],
            "source_created_at": row["source_created_at"],
            "created_at": row["created_at"],
        } for row in rows]

    with profiler.stage("service_generate"):
        report_service = ReportService()
        report = report_service.generate_time_entry_discipline(items, user_map)
    profiler.set_metric("rows", len(rows))
    profiler.set_metric("users", len(user_ids))
    with profiler.stage("serialize"):
        response = JsonResponse(report)
    profiler.attach_to_response(response)
    profiler.log()
    return response


@xframe_options_exempt
@require_GET
@log_errors("report_focus_analysis")
@auth_required
def report_focus_analysis(request: AuthorizedRequest):
    profiler = ReportProfiler("report_focus_analysis", account_id=request.bitrix24_account.pk)
    with profiler.stage("queryset_build"):
        queryset = _get_filtered_timesheet_queryset(request)
    with profiler.stage("materialize"):
        rows = list(queryset.values(
            'employee_id',
            'project_title',
            'task_id',
            'hours',
        ))

    user_ids = {row['employee_id'] for row in rows if row.get('employee_id')}
    with profiler.stage("user_map"):
        user_map = _get_user_map(request, user_ids)

    with profiler.stage("build_items"):
        items = [{
            "sotrudnik_id": row["employee_id"],
            "project_name": row["project_title"],
            "task_id": row["task_id"],
            "kolichestvo_chasov": row["hours"],
        } for row in rows]

    with profiler.stage("service_generate"):
        report_service = ReportService()
        report = report_service.generate_focus_analysis(items, user_map)
    profiler.set_metric("rows", len(rows))
    profiler.set_metric("users", len(user_ids))
    with profiler.stage("serialize"):
        response = JsonResponse(report)
    profiler.attach_to_response(response)
    profiler.log()
    return response


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("timesheet_sync")
@auth_required
@rate_limit("sync", 6, 60, key="account")
@sync_lock("timesheet")
def timesheet_sync(request: AuthorizedRequest):
    profiler = ReportProfiler("timesheet_sync", account_id=request.bitrix24_account.pk)
    with profiler.stage("config"):
        config_service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
        config = config_service.get_configuration_sync()

    # Читаем необязательные даты из тела запроса (scoped/отчётный путь)
    try:
        body = json.loads(request.body or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        body = {}
    date_from = body.get("date_from")
    date_to = body.get("date_to")
    is_scoped = bool(date_from and date_to)

    service = TimesheetSyncService(request.bitrix24_account.client, request.bitrix24_account, config)
    try:
        with profiler.stage("sync_all"):
            count = service.sync_all(date_from=date_from, date_to=date_to)
        # refresh_writeoff_stats нужен только для доски проектов (полный синк).
        # При scoped-запросе (отчёт за период) пропускаем — экономит время.
        if not is_scoped:
            with profiler.stage("refresh_writeoff_stats"):
                project_card_service = ProjectCardService(request.bitrix24_account.client, request.bitrix24_account)
                project_card_service.refresh_writeoff_stats()
    except Exception:
        logger.exception("Timesheet sync failed for account %s", request.bitrix24_account.pk)
        profiler.set_metric("status", "error")
        profiler.log()
        return JsonResponse(
            {
                "status": "warning",
                "count": 0,
                "warning": "Не удалось обновить данные из Битрикс24. Используются последние сохраненные данные.",
            }
        )

    with profiler.stage("invalidate_caches"):
        invalidate_project_runtime_caches(request.bitrix24_account)
    profiler.set_metric("count", count)
    response = JsonResponse({"status": "success", "count": count})
    profiler.attach_to_response(response)
    profiler.log()
    return response


@xframe_options_exempt
@require_GET
@log_errors("timesheet_list")
@auth_required
@admin_required
def timesheet_list(request: AuthorizedRequest):
    queryset = TimesheetItem.objects.filter(bitrix24_account=request.bitrix24_account).order_by('-created_at', '-bitrix_id')

    # Filter by record creation date (created_at)
    created_from = request.GET.get('created_from')
    created_to = request.GET.get('created_to')
    queryset = _apply_created_at_filters(queryset, created_from, created_to)

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
@admin_required
def save_configuration(request: AuthorizedRequest):
    service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    try:
        body = json.loads(request.body)
        config = body.get('config', {})
        if not isinstance(config, dict):
            return JsonResponse({"error": "Некорректный формат конфигурации."}, status=400)

        config = service.normalize_configuration_sync(config)

        warnings = []
        project_validation = None
        try:
            should_validate_project_spa = int(config.get("project_sp_entity_type_id") or 0) > 0
        except (TypeError, ValueError):
            should_validate_project_spa = False

        if should_validate_project_spa:
            try:
                project_validation = _build_project_spa_validation_payload(service, request.bitrix24_account, config)
            except Exception as validation_exc:
                logger.exception("Configuration save validation failed: %s", validation_exc)
                warnings.append(
                    "Проверка Project SPA временно недоступна. Настройки сохранены, "
                    "но валидацию рекомендуется повторить позже."
                )

        if should_validate_project_spa and project_validation and not project_validation.get("is_valid"):
            return JsonResponse(
                {
                    "status": "validation_error",
                    "error": "Конфигурация Project SPA невалидна. Исправьте ошибки и повторите сохранение.",
                    "validation": project_validation,
                },
                status=400,
            )

        service.save_configuration_sync(config)
        invalidate_project_runtime_caches(request.bitrix24_account)

        response_payload = {"status": "success"}
        if should_validate_project_spa:
            project_sync_service = ProjectSyncService(request.bitrix24_account.client, request.bitrix24_account)
            try:
                with account_sync_lock(request.bitrix24_account, scope="project"):
                    sync_result = project_sync_service.sync()
                response_payload["project_sync"] = sync_result
            except SyncLockBusy:
                warnings.append(
                    "Синхронизация проектов уже выполняется, повторите позже."
                )
                response_payload["project_sync"] = {
                    "status": "warning",
                    "warning": "Синхронизация проектов уже выполняется, повторите позже.",
                }
            except Exception as sync_exc:
                logger.exception("Configuration save project sync failed: %s", sync_exc)
                warnings.append(
                    "Настройки сохранены, но автосинхронизация проектов завершилась ошибкой."
                )
                response_payload["project_sync"] = {
                    "status": "warning",
                    "warning": "Автосинхронизация проектов завершилась ошибкой.",
                }

            try:
                backfill_result = project_sync_service.backfill_timesheet_project_items()
                response_payload["timesheet_backfill"] = backfill_result
            except Exception as backfill_exc:
                logger.exception("Configuration save timesheet backfill failed: %s", backfill_exc)
                warnings.append(
                    "Настройки сохранены, но backfill связей меток времени завершился ошибкой."
                )
                response_payload["timesheet_backfill"] = {
                    "status": "warning",
                    "warning": "Backfill связей меток времени завершился ошибкой.",
                }

        if warnings:
            response_payload["warning"] = " ".join(warnings)

        return JsonResponse(response_payload)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Некорректное JSON тело запроса."}, status=400)
    except Exception:
        logger.exception("Configuration save failed")
        return JsonResponse({"error": "Внутренняя ошибка сервера"}, status=500)


@xframe_options_exempt
@require_GET
@log_errors("get_internal_lists")
@auth_required
def get_internal_lists(request: AuthorizedRequest):
    service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    iblock_type_id = request.GET.get('iblockTypeId', 'lists')
    socnet_group_id = request.GET.get('socnetGroupId')
    socnet_group_value = int(socnet_group_id) if socnet_group_id and str(socnet_group_id).isdigit() else None
    return JsonResponse({"lists": service.get_internal_lists_sync(iblock_type_id=iblock_type_id, socnet_group_id=socnet_group_value)})


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
@log_errors("get_project_spa_validation")
@auth_required
def get_project_spa_validation(request: AuthorizedRequest):
    config_service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    config = config_service.get_configuration_sync()
    payload = _build_project_spa_validation_payload(config_service, request.bitrix24_account, config)
    return JsonResponse(payload)


@xframe_options_exempt
@require_GET
@log_errors("get_project_spa_stages")
@auth_required
def get_project_spa_stages(request: AuthorizedRequest):
    config_service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    config = config_service.get_configuration_sync()
    entity_type_id_raw = request.GET.get("entityTypeId") or config.get("project_sp_entity_type_id") or 0
    try:
        entity_type_id = int(entity_type_id_raw)
    except (TypeError, ValueError):
        return JsonResponse({"error": "Некорректный entityTypeId"}, status=400)

    if not entity_type_id:
        return JsonResponse({"error": "Не выбран Смарт-процесс ПРОЕКТ"}, status=400)

    try:
        payload = config_service.get_project_spa_stages_sync(entity_type_id)
        return JsonResponse({"status": "success", **payload})
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("create_smart_process")
@auth_required
@admin_required
def create_smart_process(request: AuthorizedRequest):
    """Create a new Smart Process from settings page."""
    try:
        service = InstallationService(request.bitrix24_account.client, request.bitrix24_account)
        result = service.create_smart_process_only()
        return JsonResponse({"status": "success", **result})
    except InstallationError as e:
        return JsonResponse({"error": str(e)}, status=400)
    except Exception:
        logger.exception("create operation failed")
        return JsonResponse({"error": "Внутренняя ошибка сервера"}, status=500)


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("create_fields")
@auth_required
@admin_required
def create_fields(request: AuthorizedRequest):
    """Create all required fields in the selected Smart Process."""
    import json as json_module
    try:
        body = json_module.loads(request.body)
        sp_id = body.get('entityTypeId')
        if not sp_id:
            return JsonResponse({"error": "Не указан ID смарт-процесса"}, status=400)

        service = InstallationService(request.bitrix24_account.client, request.bitrix24_account)
        result = service.create_fields_only(int(sp_id))
        return JsonResponse({"status": "success", **result})
    except InstallationError as e:
        return JsonResponse({"error": str(e)}, status=400)
    except Exception:
        logger.exception("create operation failed")
        return JsonResponse({"error": "Внутренняя ошибка сервера"}, status=500)


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("create_mapped_field")
@auth_required
@admin_required
def create_mapped_field(request: AuthorizedRequest):
    import json as json_module
    try:
        body = json_module.loads(request.body)
        sp_id = body.get('entityTypeId')
        field_key = body.get('fieldKey')
        mapping_type = body.get('mappingType') or 'timesheet'

        if not sp_id:
            return JsonResponse({"error": "Не указан ID смарт-процесса"}, status=400)
        if not field_key:
            return JsonResponse({"error": "Не указан ключ поля"}, status=400)

        service = InstallationService(request.bitrix24_account.client, request.bitrix24_account)
        result = service.create_single_field(int(sp_id), str(field_key), str(mapping_type))
        return JsonResponse({"status": "success", **result})
    except InstallationError as e:
        return JsonResponse({"error": str(e)}, status=400)
    except Exception:
        logger.exception("create operation failed")
        return JsonResponse({"error": "Внутренняя ошибка сервера"}, status=500)


@xframe_options_exempt
@require_GET
@log_errors("report_daily_workload")
@auth_required
def report_daily_workload(request: AuthorizedRequest):
    profiler = ReportProfiler("report_daily_workload", account_id=request.bitrix24_account.pk)
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

    with profiler.stage("queryset_build"):
        queryset = build_filtered_timesheet_queryset(
            request.bitrix24_account,
            {
                "date_from": date_from,
                "date_to": date_to,
                "employee_ids[]": request.GET.getlist("employee_ids[]"),
                "project_ids[]": request.GET.getlist("project_ids[]"),
                "employee_mode": request.GET.get("employee_mode", "include"),
                "project_mode": request.GET.get("project_mode", "include"),
            },
        )
    with profiler.stage("project_lookup"):
        project_name_by_item, project_name_by_group = build_project_title_lookups(request.bitrix24_account)
    with profiler.stage("materialize"):
        rows = materialize_rows(
            queryset,
            (
                "employee_id",
                "project_item_id",
                "project_id",
                "project_title",
                "hours",
                "task_id",
                "task_hierarchy_titles",
                "description",
                "date_reflection",
            ),
        )
    user_ids = {row["employee_id"] for row in rows if row.get("employee_id")}
    with profiler.stage("user_map"):
        user_map = _get_user_map(request, user_ids)
    with profiler.stage("build_items"):
        items = [
            {
                "sotrudnik_id": row["employee_id"],
                "project_name": resolve_project_name_for_row(row, project_name_by_item, project_name_by_group),
                "kolichestvo_chasov": row["hours"],
                "id_zadachi": row["task_id"],
                "nazvanie_zadachi": row["task_hierarchy_titles"][-1] if row.get("task_hierarchy_titles") else "No Title",
                "opisanie": row["description"],
                "data": row["date_reflection"].isoformat() if row.get("date_reflection") else None,
            }
            for row in rows
        ]

    with profiler.stage("service_generate"):
        report_service = ReportService()
        report = report_service.generate_daily_workload(items, user_map, date_from, date_to)
    profiler.set_metric("rows", len(rows))
    profiler.set_metric("users", len(user_ids))
    with profiler.stage("serialize"):
        response = JsonResponse(report, safe=False)
    profiler.attach_to_response(response)
    profiler.log()
    return response


@xframe_options_exempt
@require_GET
@log_errors("get_request_logs")
@auth_required
@admin_required
def get_request_logs(request: AuthorizedRequest):
    page_number = request.GET.get('page', 1)
    page_size = request.GET.get('limit', 50)
    
    queryset = RequestLog.objects.filter(bitrix24_account=request.bitrix24_account).order_by('-timestamp')
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
@admin_required
def get_system_logs(request: AuthorizedRequest):
    page_number = request.GET.get('page', 1)
    page_size = request.GET.get('limit', 50)
    
    queryset = SystemLog.objects.filter(bitrix24_account=request.bitrix24_account).order_by('-timestamp')
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
@require_GET
@log_errors("inn_backfill_scan")
@auth_required
@admin_required
def inn_backfill_scan(request: AuthorizedRequest):
    """Поиск карточек списания без ИНН за период + предлагаемые значения из проекта."""
    config_service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    config = config_service.get_configuration_sync()
    service = InnBackfillService(request.bitrix24_account.client, request.bitrix24_account, config)
    err = service.ensure_inn_fields()
    if err:
        return JsonResponse({"error": err}, status=400)
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    project_ids = request.GET.getlist("project_ids[]")
    result = service.scan(date_from, date_to, project_ids)
    return JsonResponse(result, safe=False)


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("inn_backfill_apply")
@auth_required
@admin_required
def inn_backfill_apply(request: AuthorizedRequest):
    """Запись ИНН в поля OUR_INN/CLIENT_INN выбранных карточек списания (crm.item.update)."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)
    items = body.get("items", [])
    if not isinstance(items, list) or not items:
        return JsonResponse({"error": "Не переданы карточки для простановки"}, status=400)
    config_service = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account)
    config = config_service.get_configuration_sync()
    service = InnBackfillService(request.bitrix24_account.client, request.bitrix24_account, config)
    err = service.ensure_inn_fields()
    if err:
        return JsonResponse({"error": err}, status=400)
    result = service.apply(items)
    return JsonResponse(result, safe=False)


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("inn_backfill_project_items")
@auth_required
@admin_required
def inn_backfill_project_items(request: AuthorizedRequest):
    """Резолв карточек проекта для простановки/замены ИНН (запись делает фронт чанками)."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)
    config = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account).get_configuration_sync()
    service = InnBackfillService(request.bitrix24_account.client, request.bitrix24_account, config)
    err = service.ensure_inn_fields()
    if err:
        return JsonResponse({"error": err}, status=400)
    result = service.project_items(
        body.get("project_id", ""), body.get("date_from", ""), body.get("date_to", ""),
        body.get("our_inn", ""), body.get("client_inn", ""), bool(body.get("overwrite")),
    )
    return JsonResponse(result, safe=False)


@xframe_options_exempt
@require_GET
@log_errors("projects_health")
@auth_required
@admin_required
def projects_health(request: AuthorizedRequest):
    """Список незаполненных проектов (нет данных для ИНН)."""
    config = ConfigurationService(request.bitrix24_account.client, request.bitrix24_account).get_configuration_sync()
    service = InnBackfillService(request.bitrix24_account.client, request.bitrix24_account, config)
    return JsonResponse(service.projects_health(), safe=False)


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("export_raw_data")
@auth_required
@admin_required
@rate_limit("export", 12, 60, key="account")
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
    except Exception:
        logger.exception("export_raw_data: failed to fetch smart-process fields")
        return JsonResponse(
            {"error": "Внутренняя ошибка сервера"},
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

    # ---------------------------------------------------------------------------
    # Helpers — локальные, не зависят от Django/request
    # ---------------------------------------------------------------------------
    def _extract_raw_items(response: dict) -> list:
        """Извлекает список items из ответа crm.item.list (одиночного или батчевого)."""
        result = response.get("result", {})
        if isinstance(result, dict):
            items = result.get("items")
            if items is None:
                items = result.get("result", [])
        else:
            items = result
        return items if isinstance(items, list) else []

    def _raw_data_offset_fallback(bx_token, eid, f_filter, f_select, page_size=50) -> list:
        """Резервный offset-цикл (исходная реализация). Используется при сбое батч-выборки."""
        fallback_items = []
        fb_start = 0
        while True:
            fb_resp = bx_token.call_method(
                "crm.item.list",
                {
                    "entityTypeId": int(eid),
                    "filter": f_filter,
                    "select": f_select if f_select else ["*"],
                    "start": fb_start,
                },
            )
            fb_result = fb_resp.get("result", {})
            fb_page = fb_result.get("items", [])
            fallback_items.extend(fb_page)
            fb_total = fb_resp.get("total", fb_result.get("total", 0))
            fb_start += page_size
            if not fb_page or len(fb_page) < page_size or fb_start >= fb_total:
                break
        return fallback_items

    # ---------------------------------------------------------------------------
    # Fetch all items — батч-выборка по образцу _fetch_all_pages_batched
    # ---------------------------------------------------------------------------
    import logging as _logging
    _log = _logging.getLogger(__name__)

    bx_token = request.bitrix24_account.client._bitrix_token
    _select = selected_fields if selected_fields else ["*"]
    _eid = int(entity_type_id)

    all_items = []
    try:
        # Первая страница — получаем items + total
        first_response = bx_token.call_method(
            "crm.item.list",
            {
                "entityTypeId": _eid,
                "filter": crm_filter,
                "select": _select,
                "start": 0,
            },
        )
        first_items = _extract_raw_items(first_response)
        first_result = first_response.get("result", {})
        # total лежит на верхнем уровне ответа (BUG FIX #3)
        total = first_response.get(
            "total",
            first_result.get("total", 0) if isinstance(first_result, dict) else 0,
        )
        try:
            total = int(total)
        except (TypeError, ValueError):
            total = len(first_items)

        all_items = list(first_items)
        page_size = 50

        if total > page_size:
            # Строим батч для всех оставшихся офсетов одним HTTP-запросом
            offsets = list(range(page_size, total, page_size))
            methods = {
                f"p{off}": (
                    "crm.item.list",
                    {
                        "entityTypeId": _eid,
                        "filter": crm_filter,
                        "select": _select,
                        "start": off,
                    },
                )
                for off in offsets
            }
            _log.info(
                "export_raw_data: fetching %s batch-offset pages (total=%s)",
                len(offsets),
                total,
            )
            batches_resp = bx_token.call_batches(methods, halt=False)

            # batches_resp["result"]["result"][key] = содержимое response["result"]
            # одиночного crm.item.list, т.е. {"items": [...]}
            try:
                sub_results = batches_resp.get("result", {}).get("result", {})
            except Exception:
                sub_results = {}

            if not isinstance(sub_results, dict):
                try:
                    sub_results = {str(i): v for i, v in enumerate(sub_results)}
                except Exception:
                    sub_results = {}

            batch_items_count = 0
            for key, sub_result in sub_results.items():
                try:
                    page_items = _extract_raw_items({"result": sub_result})
                    all_items.extend(page_items)
                    batch_items_count += len(page_items)
                except Exception as exc:
                    _log.warning(
                        "export_raw_data: could not parse batch sub-result key=%s: %s",
                        key,
                        exc,
                    )

            # Оборонительная проверка: если батч вернул 0 при ненулевом total — fallback
            if batch_items_count == 0 and total > page_size:
                _log.warning(
                    "export_raw_data: batch returned 0 items (total=%s, offsets=%s); "
                    "falling back to offset pagination.",
                    total,
                    len(offsets),
                )
                all_items = _raw_data_offset_fallback(bx_token, _eid, crm_filter, _select)

    except Exception as e:
        # Батч-выборка упала полностью — пробуем резервный offset-цикл
        _log.warning(
            "export_raw_data: batched fetch failed (%s); falling back to offset pagination.",
            e,
        )
        try:
            all_items = _raw_data_offset_fallback(bx_token, _eid, crm_filter, _select)
        except Exception:
            logger.exception("export_raw_data: failed to fetch items from Bitrix24")
            return JsonResponse(
                {
                    "error": "Внутренняя ошибка сервера",
                },
                status=500,
            )

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
        cell = ws.cell(row=1, column=col_idx, value=_safe_cell_text(str(header)))
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

            cell = ws.cell(row=row_idx, column=col_idx, value=_safe_cell_text(str_value))
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
    logger.info("serve_spa called. Method=%s Path=%s", request.method, request.path)
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
